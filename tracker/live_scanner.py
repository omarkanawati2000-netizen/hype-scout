#!/usr/bin/env python3
"""
tracker/live_scanner.py — Live runner scanner (cron: every 5 min)

Fetches live MC from DexScreener for all tracked coins (last 24h).
Alerts coins currently at 2x+ vs entry MC, with 30-min cooldown per tier.

Output:
    LIVE|<message>   → post to #early-trending-runners + Telegram subscribers
    QUIET            → nothing running, do nothing
    SKIP|<reason>    → cooldown not elapsed
"""
import json
import os
import sys
import io
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    LIVE_SCAN_STATE, TIER_COOLDOWN_MIN, PUMP_THRESHOLDS,
    TRACK_MAX_AGE_HOURS,
)
from utils.dexscreener import get_live_mc
from utils.formatter import format_runner_msg
from utils.queue_utils import load_tracked

SCAN_INTERVAL = 300  # 5 minutes


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


def main():
    force = "--force" in sys.argv
    state = load_state()
    now   = time.time()

    elapsed = now - state.get("last_scan", 0)
    if not force and elapsed < SCAN_INTERVAL:
        remaining = int((SCAN_INTERVAL - elapsed) / 60)
        print(f"SKIP|Next scan in {remaining}m")
        return

    coins = load_tracked(max_age_hours=TRACK_MAX_AGE_HOURS)
    if not coins:
        state["last_scan"] = now
        save_state(state)
        print("QUIET")
        return

    alerts_state    = state.get("alerts", {})
    new_alerts      = dict(alerts_state)
    runners         = []

    for mint, coin in coins.items():
        entry_mc = coin.get("entry_mc", 0)
        if entry_mc <= 0:
            continue

        live = get_live_mc(mint)
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

        time.sleep(0.4)  # DexScreener rate limit

    runners.sort(key=lambda x: -x["mult"])
    state["last_scan"] = now
    state["alerts"]    = new_alerts
    save_state(state)

    if not runners:
        print("QUIET")
        return

    discord_msg  = format_runner_msg(runners, platform="discord")
    telegram_msg = format_runner_msg(runners, platform="telegram")

    # Post directly to Discord #early-trending-runners
    try:
        from notifier.discord_poster import DiscordPoster
        DiscordPoster().post_runner(discord_msg)
    except Exception as e:
        pass

    # Broadcast to all Telegram subscribers
    try:
        from notifier.telegram_bot import TelegramNotifier
        TelegramNotifier().broadcast_text(telegram_msg)
    except Exception as e:
        pass

    print(f"LIVE|{discord_msg}")


if __name__ == "__main__":
    main()
