#!/usr/bin/env python3
"""
tracker/live_scanner.py — Live runner daemon

Runs continuously, checking all tracked coins every 60 seconds.
Posts an alert the moment a coin crosses a new tier (2x/3x/5x/10x/20x).
Tier cooldown: 30 min per tier per coin (no repeats).

Run as daemon: python tracker/live_scanner.py
"""
import json
import os
import sys
import io
import time
import logging
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    LIVE_SCAN_STATE, TIER_COOLDOWN_MIN, PUMP_THRESHOLDS,
    TRACK_MAX_AGE_HOURS, DATA_DIR, LOG_DIR,
)
from utils.dexscreener import get_live_mc_batch
from utils.formatter import format_single_runner
from utils.queue_utils import load_tracked, append_milestone

SCAN_INTERVAL = 60          # seconds between scans
LOCK_FILE     = DATA_DIR / "live_scanner.lock"

# ── Logging ───────────────────────────────────────────────────────────────────
log_path = LOG_DIR / "live_scanner.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [live_scanner] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ── Lock file ─────────────────────────────────────────────────────────────────

def write_lock():
    LOCK_FILE.write_text(str(os.getpid()))

def release_lock():
    try:
        LOCK_FILE.unlink()
    except Exception:
        pass


# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if LIVE_SCAN_STATE.exists():
        try:
            with open(LIVE_SCAN_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_scan": 0, "alerts": {}}


def save_state(state: dict):
    with open(LIVE_SCAN_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ── Tier logic ────────────────────────────────────────────────────────────────

def highest_new_threshold(mult: float, coin_alerts: dict, now: float) -> float | None:
    cooldown = TIER_COOLDOWN_MIN * 60
    for thresh in sorted(PUMP_THRESHOLDS, reverse=True):
        if mult < thresh:
            continue
        key  = f"{thresh}x"
        last = coin_alerts.get(key, 0)
        if now - last >= cooldown:
            return thresh
    return None


# ── Single scan pass ──────────────────────────────────────────────────────────

def run_scan(state: dict) -> dict:
    now   = time.time()
    coins = load_tracked(max_age_hours=TRACK_MAX_AGE_HOURS)

    if not coins:
        state["last_scan"] = now
        save_state(state)
        return state

    mints     = list(coins.keys())
    live_data = get_live_mc_batch(mints)

    alerts_state = state.get("alerts", {})
    new_alerts   = dict(alerts_state)
    runners      = []

    for mint, coin in coins.items():
        entry_mc = coin.get("entry_mc", 0)
        if entry_mc <= 0:
            continue

        live = live_data.get(mint)
        if not live or live["mc"] <= 0:
            continue

        current_mc = live["mc"]
        mult       = round(current_mc / max(entry_mc, 1), 1)

        if mult < 2.0:
            continue

        coin_alerts = new_alerts.get(mint, {})
        thresh = highest_new_threshold(mult, coin_alerts, now)
        if thresh is None:
            continue

        coin_alerts[f"{thresh}x"] = now
        new_alerts[mint] = coin_alerts

        append_milestone({
            "mint":       mint,
            "name":       coin.get("name", coin.get("symbol", "?")),
            "symbol":     coin.get("symbol", "?"),
            "multiplier": mult,
            "entry_mc":   entry_mc,
            "current_mc": current_mc,
            "timestamp":  now,
        })

        runners.append({
            "mint":       mint,
            "name":       coin.get("name", coin.get("symbol", "?")),
            "symbol":     coin.get("symbol", "?"),
            "mult":       mult,
            "thresh":     thresh,
            "entry_mc":   entry_mc,
            "current_mc": current_mc,
            "liq":        live["liq"],
            "vol_h1":     live["vol_h1"],
            "buys_h1":    live["buys_h1"],
            "sells_h1":   live["sells_h1"],
        })

    state["last_scan"] = now
    state["alerts"]    = new_alerts
    save_state(state)

    if not runners:
        logger.info(f"Scanned {len(mints)} coins — 0 new runners")
        return state

    runners.sort(key=lambda x: -x["mult"])
    logger.info(f"Scanned {len(mints)} coins — {len(runners)} runners: " +
                ", ".join(f"{r['name']} {r['mult']}x" for r in runners))

    # Post each runner immediately as it's found
    try:
        from notifier.discord_poster import DiscordPoster
        discord = DiscordPoster()
    except Exception as e:
        logger.error(f"Discord init: {e}")
        discord = None

    try:
        from notifier.telegram_bot import TelegramNotifier
        telegram = TelegramNotifier()
    except Exception as e:
        logger.error(f"Telegram init: {e}")
        telegram = None

    for r in runners:
        discord_msg  = format_single_runner(r, platform="discord")
        telegram_msg = format_single_runner(r, platform="telegram")

        if discord:
            try:
                discord.post_runner(discord_msg)
            except Exception as e:
                logger.error(f"Discord post ({r['name']}): {e}")

        if telegram:
            try:
                telegram.broadcast_text(telegram_msg)
            except Exception as e:
                logger.error(f"Telegram post ({r['name']}): {e}")

        time.sleep(0.3)  # brief gap between individual posts

    return state


# ── Main daemon loop ──────────────────────────────────────────────────────────

def main():
    logger.info(f"Live scanner daemon starting (PID {os.getpid()})")
    write_lock()

    state = load_state()

    try:
        while True:
            try:
                state = run_scan(state)
            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)

            time.sleep(SCAN_INTERVAL)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down live scanner daemon")
    finally:
        release_lock()


if __name__ == "__main__":
    main()
