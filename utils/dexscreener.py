"""
utils/dexscreener.py — DexScreener API wrapper
"""
import logging
import time
import requests as req_lib

logger = logging.getLogger(__name__)

DEXSCREENER_URL       = "https://api.dexscreener.com/latest/dex/tokens/{}"
_TIMEOUT              = 10
_RATE_LIMIT_SLEEP     = 0.4   # seconds between single calls
_BATCH_RATE_LIMIT     = 1.0   # seconds between batch calls
_BATCH_SIZE           = 29    # max mints per batch request


def _fetch(mint: str) -> list:
    """Raw fetch of DexScreener pairs for a single mint."""
    try:
        url  = DEXSCREENER_URL.format(mint)
        resp = req_lib.get(url, headers={"User-Agent": "HypeScout/2.0"}, timeout=_TIMEOUT)
        return resp.json().get("pairs") or []
    except Exception as e:
        logger.debug(f"DexScreener fetch error for {mint}: {e}")
        return []


def _fetch_batch(mints: list) -> dict:
    """
    Batch fetch pairs for up to 29 mints in a single API call.
    Returns dict: {mint: [pairs...]}
    """
    if not mints:
        return {}
    try:
        joined = ",".join(mints)
        url    = DEXSCREENER_URL.format(joined)
        resp   = req_lib.get(url, headers={"User-Agent": "HypeScout/2.0"}, timeout=_TIMEOUT)
        pairs  = resp.json().get("pairs") or []
        # Group pairs by baseToken address
        result = {m: [] for m in mints}
        for p in pairs:
            addr = (p.get("baseToken") or {}).get("address", "")
            if addr in result:
                result[addr].append(p)
        return result
    except Exception as e:
        logger.debug(f"DexScreener batch fetch error: {e}")
        return {m: [] for m in mints}


def get_live_mc_batch(mints: list) -> dict:
    """
    Batch-fetch live MC + liquidity for a list of mints.
    Splits into groups of _BATCH_SIZE, rate-limited between batches.
    Returns dict: {mint: {mc, liq, vol_h1, buys_h1, sells_h1}}
    """
    results = {}
    for i in range(0, len(mints), _BATCH_SIZE):
        chunk      = mints[i:i + _BATCH_SIZE]
        batch_data = _fetch_batch(chunk)
        for mint, pairs in batch_data.items():
            if not pairs:
                results[mint] = {"mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0}
                continue
            best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0))
            vol  = best.get("volume") or {}
            txns = best.get("txns") or {}
            results[mint] = {
                "mc":       float(best.get("marketCap", 0) or best.get("fdv", 0) or 0),
                "liq":      float((best.get("liquidity") or {}).get("usd", 0) or 0),
                "vol_h1":   float(vol.get("h1", 0) or 0),
                "buys_h1":  int((txns.get("h1") or {}).get("buys", 0) or 0),
                "sells_h1": int((txns.get("h1") or {}).get("sells", 0) or 0),
            }
        if i + _BATCH_SIZE < len(mints):
            time.sleep(_BATCH_RATE_LIMIT)
    return results


def get_volume(mint: str) -> dict:
    """
    Fetch 1h and 5m volume + buy/sell tx counts (single mint).
    Returns: {vol_h1, vol_m5, buys_h1, sells_h1}
    """
    pairs = _fetch(mint)
    if not pairs:
        return {"vol_h1": 0, "vol_m5": 0, "buys_h1": 0, "sells_h1": 0}
    p    = pairs[0]
    vol  = p.get("volume") or {}
    txns = p.get("txns") or {}
    return {
        "vol_h1":   float(vol.get("h1", 0) or 0),
        "vol_m5":   float(vol.get("m5", 0) or 0),
        "buys_h1":  int((txns.get("h1") or {}).get("buys", 0) or 0),
        "sells_h1": int((txns.get("h1") or {}).get("sells", 0) or 0),
    }


def get_live_mc(mint: str) -> dict:
    """
    Fetch live market cap and liquidity (single mint, highest-liq pair).
    Returns: {mc, liq, vol_h1, buys_h1, sells_h1}
    """
    pairs = _fetch(mint)
    if not pairs:
        return {"mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0}
    best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0))
    vol  = best.get("volume") or {}
    txns = best.get("txns") or {}
    return {
        "mc":       float(best.get("marketCap", 0) or best.get("fdv", 0) or 0),
        "liq":      float((best.get("liquidity") or {}).get("usd", 0) or 0),
        "vol_h1":   float(vol.get("h1", 0) or 0),
        "buys_h1":  int((txns.get("h1") or {}).get("buys", 0) or 0),
        "sells_h1": int((txns.get("h1") or {}).get("sells", 0) or 0),
    }
