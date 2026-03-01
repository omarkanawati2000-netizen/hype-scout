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
    LIVE_SCAN_STATE, TRACK_MAX_AGE_HOURS, DATA_DIR, LOG_DIR,
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


# ── Alert logic ───────────────────────────────────────────────────────────────
# Rules:
#   1. Fire if current mult is a new all-time high for this coin
#   2. Fire if >= 2h since last alert and coin still >= 2x (re-pump catch)

REPUMP_COOLDOWN = 7200  # 2 hours in seconds
MIN_ALERT_GAP   = 600   # 10 minutes minimum between any alerts for same coin

def should_alert(mult: float, coin_state: dict, now: float) -> bool:
    peak       = coin_state.get("peak_mult", 0)
    last_alert = coin_state.get("last_alerted_at", 0)
    since_last = now - last_alert

    # Enforce 10-min minimum gap regardless of anything else
    if since_last < MIN_ALERT_GAP:
        return False

    # Rule 1: new all-time high
    if mult > peak:
        return True

    # Rule 2: re-pump after 2h silence
    if mult >= 2.0 and since_last >= REPUMP_COOLDOWN:
        return True

    return False


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

        # ── MC sanity check ───────────────────────────────────────────────────
        # If multiple DEX sources disagree wildly on MC, the data is unreliable.
        # Skip the alert to avoid posting garbage multipliers (e.g. 2596x when
        # real move is 8x). The spread and source count are logged for debugging.
        if not live.get("reliable", True):
            sources = live.get("sources_checked", "?")
            spread  = live.get("mc_spread", "?")
            logger.warning(
                f"Skipping {coin.get('name', mint)} — MC unreliable: "
                f"{sources} sources, {spread}x spread across pairs"
            )
            continue

        current_mc = live["mc"]
        mult       = round(current_mc / max(entry_mc, 1), 1)

        if mult < 2.0:
            continue

        coin_state = new_alerts.get(mint, {})

        if not should_alert(mult, coin_state, now):
            continue

        # Update state: track peak and last alert time
        new_peak = max(mult, coin_state.get("peak_mult", 0))
        new_alerts[mint] = {
            "peak_mult":      new_peak,
            "last_alerted_at": now,
        }

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
            "mint":           mint,
            "name":           coin.get("name", coin.get("symbol", "?")),
            "symbol":         coin.get("symbol", "?"),
            "mult":           mult,
            "thresh":         mult,
            "entry_mc":       entry_mc,
            "current_mc":     current_mc,
            "liq":            live["liq"],
            "vol_h1":         live["vol_h1"],
            "buys_h1":        live["buys_h1"],
            "sells_h1":       live["sells_h1"],
            "discord_msg_id": coin.get("discord_msg_id"),  # jump link to original alert
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

    try:
        from notifier.twitter_poster import TwitterPoster
        twitter = TwitterPoster()
    except Exception as e:
        logger.error(f"Twitter init: {e}")
        twitter = None

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

        if twitter:
            try:
                twitter.post_runner(r)
            except Exception as e:
                logger.error(f"Twitter post ({r['name']}): {e}")

        time.sleep(0.5)  # brief gap between individual posts

    # ── Recap tweets (3h / 12h) ───────────────────────────────────────────────
    if twitter:
        try:
            from utils.queue_utils import load_milestones
            recent = load_milestones(max_age_hours=12)
            twitter.maybe_post_recap(recent)
        except Exception as e:
            logger.error(f"Recap tweet error: {e}")

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
