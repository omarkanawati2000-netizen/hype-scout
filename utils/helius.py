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
