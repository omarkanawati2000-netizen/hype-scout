"""
utils/helius.py — Helius RPC wrapper for Solana holder counts
"""
import json
import logging
import requests
import sys
import os

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from config import HELIUS_RPC_URL

logger = logging.getLogger(__name__)

_TIMEOUT = 5


def get_holder_count(mint: str) -> int | None:
    """
    Fetch holder count via Helius getTokenLargestAccounts RPC.
    Returns int (number of top accounts) or None if unavailable.
    Note: This returns the number of largest accounts (max 20), not total holders.
    A return of <10 is a strong rug-protection signal.
    """
    if not HELIUS_RPC_URL or "your-api-key" in HELIUS_RPC_URL.lower():
        return None
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint],
        }
        resp = requests.post(HELIUS_RPC_URL, json=payload, timeout=_TIMEOUT)
        result = resp.json()
        if "result" in result and result["result"]:
            accounts = result["result"].get("value", result["result"])
            if isinstance(accounts, list):
                return len(accounts)
    except Exception as e:
        logger.debug(f"Helius RPC error for {mint}: {e}")
    return None


def get_holder_concentration(mint: str) -> dict | None:
    """
    Returns top-holder concentration data for bundle/whale detection.

    Makes 2 RPC calls (batched in one HTTP request):
      - getTokenLargestAccounts  → top 20 holders + balances
      - getTokenSupply           → total supply

    Returns dict:
        top1_pct   : % of supply held by largest wallet
        top3_pct   : % of supply held by top 3 wallets combined
        top_amounts: list of uiAmount for top 3 holders
        total_supply: total token supply (ui)
    Or None if data is unavailable.
    """
    if not HELIUS_RPC_URL or "your-api-key" in HELIUS_RPC_URL.lower():
        return None
    try:
        batch = [
            {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [mint]},
            {"jsonrpc": "2.0", "id": 2, "method": "getTokenSupply",          "params": [mint]},
        ]
        resp    = requests.post(HELIUS_RPC_URL, json=batch, timeout=_TIMEOUT)
        results = resp.json()

        if not isinstance(results, list) or len(results) < 2:
            return None

        # Parse largest accounts
        r1       = next((r for r in results if r.get("id") == 1), {})
        accounts = r1.get("result", {}).get("value", [])
        if not accounts:
            return None

        amounts = sorted(
            [float(a.get("uiAmount") or 0) for a in accounts],
            reverse=True,
        )

        # Parse total supply
        r2           = next((r for r in results if r.get("id") == 2), {})
        supply_info  = r2.get("result", {}).get("value", {})
        total_supply = float(supply_info.get("uiAmount") or 0)

        if total_supply <= 0:
            return None

        top1_pct = (amounts[0] / total_supply * 100) if amounts else 0
        top3_sum = sum(amounts[:3])
        top3_pct = (top3_sum / total_supply * 100)

        return {
            "top1_pct":    round(top1_pct, 1),
            "top3_pct":    round(top3_pct, 1),
            "top_amounts": amounts[:3],
            "total_supply": total_supply,
        }

    except Exception as e:
        logger.debug(f"Helius concentration error for {mint}: {e}")
    return None
