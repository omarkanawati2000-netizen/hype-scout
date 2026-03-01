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

# ── MC sanity check config ────────────────────────────────────────────────────
# If the max/min MC ratio across all DEX pairs exceeds this, flag as unreliable.
# e.g. 10.0 means if one pair shows 10x the MC of another, something is wrong.
MC_OUTLIER_RATIO      = 10.0
# Minimum liquidity (USD) for a pair to be included in cross-check.
# Pairs below this are likely dead pools with stale/garbage pricing.
MIN_PAIR_LIQ_USD      = 50.0
# Need at least this many valid pairs to cross-check. With only 1 source,
# we trust it (nothing to compare against) but note single-source status.
MIN_SOURCES_FOR_CHECK = 2


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


def _pick_best_pair_validated(pairs: list) -> dict:
    """
    Select the best pair from a DexScreener pairs list, with MC cross-validation.

    Strategy:
      1. Filter pairs to those with liquidity >= MIN_PAIR_LIQ_USD (skip dead pools).
         If none pass, fall back to all pairs with a valid MC.
      2. Collect MC values across all valid pairs.
      3. If 2+ sources: compute spread = max_mc / min_mc. If spread >= MC_OUTLIER_RATIO,
         the token's MC data is inconsistent across DEXes — flag reliable=False.
      4. Pick the highest-liquidity pair as the primary data source (best price discovery).

    Returns dict with keys: mc, liq, vol_h1, buys_h1, sells_h1, reliable, mc_spread, sources_checked
    """
    _empty = {
        "mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0,
        "reliable": True, "mc_spread": 1.0, "sources_checked": 0,
    }

    if not pairs:
        return _empty

    # Step 1: filter to pairs with enough liquidity for valid pricing
    liq_filtered = [
        p for p in pairs
        if float((p.get("liquidity") or {}).get("usd", 0) or 0) >= MIN_PAIR_LIQ_USD
        and float(p.get("marketCap", 0) or p.get("fdv", 0) or 0) > 0
    ]
    # Fallback: if liquidity filter removes everything, use any pair with a MC
    valid = liq_filtered or [
        p for p in pairs if float(p.get("marketCap", 0) or p.get("fdv", 0) or 0) > 0
    ]

    if not valid:
        return _empty

    # Step 2: collect MCs for cross-check
    mcs = [float(p.get("marketCap", 0) or p.get("fdv", 0) or 0) for p in valid]
    mcs_nonzero = [m for m in mcs if m > 0]
    sources_checked = len(mcs_nonzero)
    reliable = True
    mc_spread = 1.0

    # Step 3: cross-validate if we have 2+ sources
    if sources_checked >= MIN_SOURCES_FOR_CHECK:
        mc_max = max(mcs_nonzero)
        mc_min = min(mcs_nonzero)
        if mc_min > 0:
            mc_spread = mc_max / mc_min
            if mc_spread >= MC_OUTLIER_RATIO:
                reliable = False
                logger.warning(
                    f"MC outlier detected: {sources_checked} pairs, "
                    f"spread={mc_spread:.1f}x (min=${mc_min:,.0f} max=${mc_max:,.0f}) — flagging unreliable"
                )

    # Step 4: pick highest-liq pair as primary
    best = max(valid, key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0))
    vol  = best.get("volume") or {}
    txns = best.get("txns") or {}

    return {
        "mc":              float(best.get("marketCap", 0) or best.get("fdv", 0) or 0),
        "liq":             float((best.get("liquidity") or {}).get("usd", 0) or 0),
        "vol_h1":          float(vol.get("h1", 0) or 0),
        "buys_h1":         int((txns.get("h1") or {}).get("buys", 0) or 0),
        "sells_h1":        int((txns.get("h1") or {}).get("sells", 0) or 0),
        "reliable":        reliable,
        "mc_spread":       round(mc_spread, 1),
        "sources_checked": sources_checked,
    }


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
                results[mint] = {
                    "mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0,
                    "reliable": True, "mc_spread": 1.0, "sources_checked": 0,
                }
                continue
            results[mint] = _pick_best_pair_validated(pairs)
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
    Returns: {mc, liq, vol_h1, buys_h1, sells_h1, reliable, mc_spread, sources_checked}
    """
    pairs = _fetch(mint)
    if not pairs:
        return {"mc": 0, "liq": 0, "vol_h1": 0, "buys_h1": 0, "sells_h1": 0,
                "reliable": True, "mc_spread": 1.0, "sources_checked": 0}
    return _pick_best_pair_validated(pairs)
