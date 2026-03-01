#!/usr/bin/env python3
"""
scanner/poller.py — Pump.fun REST API Poller

Polls the Pump.fun API every 30s for new tokens.
Filters by MC range, bonding curve progress, and liquidity.
Makes extra calls to Helius (holder count) and DexScreener (volume).
Writes qualifying tokens to data/alerts_queue.jsonl.
Single-instance protected via file lock.
"""
import asyncio
import json
import logging
import os
import sys
import io
from datetime import datetime
from pathlib import Path

# Windows UTF-8 fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp
from config import (
    PUMP_API_BASE, POLL_INTERVAL, PUMP_BATCH_SIZE,
    MC_MIN_USD, MC_MAX_USD, BC_MAX_PCT, MIN_SOL_LIQ, MIN_HOLDERS,
    POLLER_LOCK, LOG_DIR,
)
from utils.dexscreener import get_volume
from utils.helius import get_holder_count, get_dev_holding_pct
from utils.queue_utils import append_to_queue, append_seen_mint, load_seen_mints

# ── Filter thresholds ─────────────────────────────────────────────────────────
MAX_DEV_PCT        = 15.0  # skip if creator holds > 15% of supply
MAX_BUY_SELL_RATIO = 8.0   # skip if buys:sells > 8:1 (only for tokens > 10 min old)
MIN_AGE_FOR_BS_CHECK = 10  # minutes — don't apply buy/sell filter to brand new tokens

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "scanner.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("poller")

# ── Global state ──────────────────────────────────────────────────────────────
seen_tokens: set = set()


# ── Single-instance lock ──────────────────────────────────────────────────────

def acquire_lock():
    import time
    time.sleep(0.3)
    my_pid = os.getpid()
    while True:
        try:
            fd = os.open(str(POLLER_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(my_pid).encode())
            os.close(fd)
            logger.info(f"Lock acquired (PID {my_pid})")
            return
        except FileExistsError:
            try:
                with open(POLLER_LOCK, "r") as lf:
                    owner_pid = int(lf.read().strip())
            except Exception:
                try:
                    os.remove(POLLER_LOCK)
                except Exception:
                    pass
                continue
            try:
                os.kill(owner_pid, 0)
                logger.error(f"Poller already running (PID {owner_pid}). Exiting.")
                sys.exit(0)
            except (OSError, ProcessLookupError):
                logger.warning(f"Stale lock PID {owner_pid}, removing.")
                try:
                    os.remove(POLLER_LOCK)
                except Exception:
                    pass


def release_lock():
    try:
        os.remove(POLLER_LOCK)
    except Exception:
        pass


# ── Fetch tokens ──────────────────────────────────────────────────────────────

async def fetch_recent_tokens() -> list:
    url = f"{PUMP_API_BASE}/coins?offset=0&limit={PUMP_BATCH_SIZE}&sort=created&order=desc"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get("coins", [])
    except Exception as e:
        logger.error(f"Fetch error: {e}")
    return []


# ── Analyze token ─────────────────────────────────────────────────────────────

async def analyze_token(token: dict) -> dict | None:
    try:
        mint       = token.get("mint")
        name       = token.get("name", "Unknown")
        symbol     = token.get("symbol", "???")
        mc         = token.get("usd_market_cap", 0)
        real_sol   = token.get("real_sol_reserves", 0)
        virt_sol   = token.get("virtual_sol_reserves", real_sol + 1)
        bc_pct     = (real_sol / virt_sol * 100) if virt_sol > 0 else 0
        created_ms = token.get("created_timestamp", 0)
        age_minutes = ((datetime.now().timestamp() * 1000) - created_ms) / 60000

        # Apply filters
        if not (MC_MIN_USD <= mc <= MC_MAX_USD):
            return None
        if bc_pct >= BC_MAX_PCT:
            return None
        if real_sol < (MIN_SOL_LIQ * 1e9):  # convert SOL to lamports
            return None

        # Holder check (rug protection)
        holder_count = get_holder_count(mint)
        if holder_count is not None and holder_count < MIN_HOLDERS:
            logger.debug(f"Filtered {name}: only {holder_count} holders")
            return None

        # Volume data (needed for buy/sell ratio check)
        vol_data = get_volume(mint)

        # ── Buy/sell ratio filter ─────────────────────────────────────────────
        # Skip tokens >10 min old with extremely lopsided buy pressure (fake demand)
        buys  = vol_data.get("buys_h1", 0) or 0
        sells = vol_data.get("sells_h1", 0) or 0
        if age_minutes > MIN_AGE_FOR_BS_CHECK and sells > 0:
            ratio = buys / sells
            if ratio > MAX_BUY_SELL_RATIO:
                logger.info(f"Filtered {name}: buy/sell ratio {ratio:.1f}:1 (max {MAX_BUY_SELL_RATIO}:1)")
                return None
        elif age_minutes > MIN_AGE_FOR_BS_CHECK and sells == 0 and buys > 20:
            # 20+ buys, zero sells after 10 min = coordinated pump
            logger.info(f"Filtered {name}: {buys} buys, 0 sells after {age_minutes:.0f}min")
            return None

        # ── Dev wallet holding filter ─────────────────────────────────────────
        # Check if the creator is holding a large chunk of supply (rug setup)
        creator = token.get("creator", "")
        if creator:
            dev_pct = get_dev_holding_pct(mint, creator)
            if dev_pct is not None and dev_pct > MAX_DEV_PCT:
                logger.info(f"Filtered {name}: dev holds {dev_pct:.1f}% of supply (max {MAX_DEV_PCT}%)")
                return None

        # Compute derived fields
        liq_usd = (real_sol / 1e9) * 200  # estimate: 1 SOL ≈ $200
        ath     = token.get("ath_market_cap", mc)

        return {
            "mint":                    mint,
            "name":                    name,
            "symbol":                  symbol,
            "market_cap":              mc,
            "ath_market_cap":          ath,
            "liquidity_usd":           liq_usd,
            "age_minutes":             age_minutes,
            "bonding_curve_progress":  bc_pct,
            "holder_count":            holder_count,
            "real_sol_reserves":       real_sol,
            "vol_h1":                  vol_data["vol_h1"],
            "vol_m5":                  vol_data["vol_m5"],
            "buys_h1":                 vol_data["buys_h1"],
            "sells_h1":                vol_data["sells_h1"],
            "created_at":              token.get("created_timestamp"),
            "creator":                 token.get("creator", ""),
            "twitter":                 token.get("twitter"),
            "dexscreener_url":         f"https://dexscreener.com/solana/{mint}",
            "pump_url":                f"https://pump.fun/{mint}",
            "tier":                    "early",
            "posted":                  False,
            "timestamp":               datetime.now().timestamp(),
            "source":                  "pump_poller_v2",
        }
    except Exception as e:
        logger.debug(f"Analysis error: {e}")
    return None


# ── Main poll loop ────────────────────────────────────────────────────────────

async def poll_loop():
    logger.info("Pump.fun Poller v2 starting...")
    # Load persistent seen mints
    seen_tokens.update(load_seen_mints())
    logger.info(f"Pre-loaded {len(seen_tokens)} seen mints")

    while True:
        try:
            tokens = await fetch_recent_tokens()
            new_count = 0
            alert_count = 0

            for token in tokens:
                mint = token.get("mint")
                if mint and mint not in seen_tokens:
                    seen_tokens.add(mint)
                    append_seen_mint(mint)
                    alert = await analyze_token(token)
                    if alert:
                        append_to_queue(alert)
                        alert_count += 1
                    new_count += 1

            logger.info(f"Polled {len(tokens)} tokens | {new_count} new | {alert_count} queued")
        except Exception as e:
            logger.error(f"Poll loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    acquire_lock()
    try:
        asyncio.run(poll_loop())
    except KeyboardInterrupt:
        logger.info("Poller stopped by user.")
    finally:
        release_lock()
