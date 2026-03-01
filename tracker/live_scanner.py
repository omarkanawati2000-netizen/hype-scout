#!/usr/bin/env python3
"""
tracker/live_scanner.py — Live runner scanner (cron: every 5 min)

Fetches live MC from DexScreener for all tracked coins (last 24h) using
batch API calls (up to 29 mints per request) for speed.

Alerts coins currently at 2x+ vs entry MC, with 30-min cooldown per tier.

Output:
    LIVE|<n> runners   → posted to #early-trending-runners + Telegram
    QUIET              → no runners found
    SKIP|<reason>      → interval not elapsed
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
from utils.dexscreener import get_live_mc_batch
from utils.formatter import format_single_runner
from utils.queue_utils import load_tracked, append_milestone

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

    # Mark scan started (so concurrent runs know we're running)
    state["last_scan"] = now
    save_state(state)

    coins = load_tracked(max_age_hours=TRACK_MAX_AGE_HOURS)
    if not coins:
        print("QUIET")
        return

    # ── Batch DexScreener fetch (29 mints per request) ──────────────────
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

        # Record milestone so leaderboard can show all-time peak
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

    runners.sort(key=lambda x: -x["mult"])

    # Save updated alert timestamps
    state["alerts"] = new_alerts
    save_state(state)

    if not runners:
        print(f"QUIET|Scanned {len(mints)} coins, 0 runners")
        return

    # Post one alert per runner (individual messages, not batched)
    discord_poster  = None
    telegram_notif  = None
    try:
        from notifier.discord_poster import DiscordPoster
        discord_poster = DiscordPoster()
    except Exception as e:
        print(f"Discord init error: {e}", file=sys.stderr)

    try:
        from notifier.telegram_bot import TelegramNotifier
        telegram_notif = TelegramNotifier()
    except Exception as e:
        print(f"Telegram init error: {e}", file=sys.stderr)

    for r in runners:
        discord_msg  = format_single_runner(r, platform="discord")
        telegram_msg = format_single_runner(r, platform="telegram")

        if discord_poster:
            try:
                discord_poster.post_runner(discord_msg)
            except Exception as e:
                print(f"Discord post error ({r['name']}): {e}", file=sys.stderr)

        if telegram_notif:
            try:
                telegram_notif.broadcast_text(telegram_msg)
            except Exception as e:
                print(f"Telegram post error ({r['name']}): {e}", file=sys.stderr)

        time.sleep(0.5)  # slight gap between posts

    summary = ", ".join(f"{r['name']} {r['mult']}x" for r in runners[:5])
    print(f"LIVE|{len(runners)} runners: {summary}")


if __name__ == "__main__":
    main()
