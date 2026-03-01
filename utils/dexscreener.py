"""
utils/dexscreener.py — DexScreener API wrapper
"""
import logging
import requests as req_lib

logger = logging.getLogger(__name__)

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"
_TIMEOUT = 8
_RATE_LIMIT_SLEEP = 0.4  # seconds between calls to avoid throttle


def _fetch(mint: str) -> list:
    """Raw fetch of DexScreener pairs for a mint."""
    try:
        url = DEXSCREENER_URL.format(mint)
        resp = req_lib.get(url, headers={"User-Agent": "HypeScout/2.0"}, timeout=_TIMEOUT)
        return resp.json().get("pairs") or []
    except Exception as e:
        logger.debug(f"DexScreener fetch error for {mint}: {e}")
        return []


def get_volume(mint: str) -> dict:
    """
    Fetch 1h and 5m volume + buy/sell tx counts.
    Returns: {vol_h1, vol_m5, buys_h1, sells_h1}
    """
    pairs = _fetch(mint)
    if not pairs:
        return {"vol_h1": 0, "vol_m5": 0, "buys_h1": 0, "sells_h1": 0}
    p = pairs[0]
    vol  = p.get("volume", {})
    txns = p.get("txns", {})
    return {
        "vol_h1":   float(vol.get("h1", 0) or 0),
        "vol_m5":   float(vol.get("m5", 0) or 0),
        "buys_h1":  int(txns.get("h1", {}).get("buys", 0) or 0),
        "sells_h1": int(txns.get("h1", {}).get("sells", 0) or 0),
    }


def get_live_mc(mint: str) -> dict:
    """
    Fetch live market cap and liquidity (picks pair with highest liquidity).
    Returns: {mc, liq, vol_h1, buys_h1, sells_h1}
    """
    pairs = _fetch(mint)
    if not pairs:
        return {"mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0}
    best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
    vol  = best.get("volume", {})
    txns = best.get("txns", {})
    return {
        "mc":       float(best.get("marketCap", 0) or best.get("fdv", 0) or 0),
        "liq":      float(best.get("liquidity", {}).get("usd", 0) or 0),
        "vol_h1":   float(vol.get("h1", 0) or 0),
        "buys_h1":  int(txns.get("h1", {}).get("buys", 0) or 0),
        "sells_h1": int(txns.get("h1", {}).get("sells", 0) or 0),
    }
