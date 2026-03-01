#!/usr/bin/env python3
"""
tracker/leaderboard.py — Hourly leaderboard (cron: every 1 hour)

Top 15 coins by peak multiplier in last 24h. Uses live DexScreener data
via batch fetch for accurate current multipliers.
Medal rankings: 🥇🥈🥉, tier emojis: 🚀⚡🔥💥

Output:
    LEADERBOARD|<message>  → post to #early-trending-runners + Telegram
    SKIP|<reason>          → cooldown not elapsed or no data
"""
import json
import sys
import io
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LEADERBOARD_STATE, TRACK_MAX_AGE_HOURS, DISCORD_RUNNERS_CHANNEL
from utils.formatter import format_leaderboard
from utils.dexscreener import get_live_mc_batch
from utils.queue_utils import load_tracked, load_milestones

LEADERBOARD_INTERVAL = 3600  # 1 hour
LEADERBOARD_SIZE     = 15


def load_state() -> dict:
    if LEADERBOARD_STATE.exists():
        try:
            with open(LEADERBOARD_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_posted": 0}


def save_state(state: dict):
    with open(LEADERBOARD_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def main():
    force = "--force" in sys.argv
    state = load_state()
    now   = time.time()

    elapsed = now - state.get("last_posted", 0)
    if not force and elapsed < LEADERBOARD_INTERVAL:
        remaining = int((LEADERBOARD_INTERVAL - elapsed) / 60)
        print(f"SKIP|Next leaderboard in {remaining}m")
        return

    coins      = load_tracked(max_age_hours=TRACK_MAX_AGE_HOURS)
    milestones = load_milestones()

    if not coins:
        state["last_posted"] = now
        save_state(state)
        print("SKIP|No tracked coins")
        return

    # ── Live batch fetch from DexScreener ──────────────────────────────
    mints     = list(coins.keys())
    live_data = get_live_mc_batch(mints)

    # Build peak multiplier from milestones (historical highs)
    # Also track recording count per mint for sanity cap
    peak_map:   dict = {}   # mint → peak_mult
    mult_list:  dict = {}   # mint → sorted list of all recorded mults

    for m in milestones:
        mint = m.get("mint", "")
        mult = m.get("multiplier", 0)
        if not mint:
            continue
        if mult > peak_map.get(mint, 0):
            peak_map[mint] = mult
        mult_list.setdefault(mint, []).append(mult)

    # Sanity cap: > 500x requires 3+ milestone recordings
    # If fewer recordings, use the 2nd-highest confirmed mult instead
    SANITY_CAP      = 500.0
    MIN_RECORDINGS  = 3
    for mint, peak in list(peak_map.items()):
        if peak > SANITY_CAP:
            recordings = sorted(mult_list.get(mint, []), reverse=True)
            if len(recordings) < MIN_RECORDINGS:
                # Not enough confirmation — use 2nd highest if available, else drop
                fallback = recordings[1] if len(recordings) >= 2 else 0
                peak_map[mint] = fallback

    # Build leaderboard entries
    leaderboard = []
    for mint, c in coins.items():
        entry_mc = c.get("entry_mc", 0)
        if entry_mc <= 0:
            continue

        # Live current MC from DexScreener — only use if data is reliable
        live       = live_data.get(mint, {})
        current_mc = live.get("mc", 0)
        reliable   = live.get("reliable", True)
        if not reliable:
            current_mc = 0  # discard bad MC data, fall back to milestone peak only
        live_mult = round(current_mc / entry_mc, 1) if current_mc > 0 else 0

        # Peak is max of all-time milestone high and current live (if reliable)
        peak_mult = max(peak_map.get(mint, 0), live_mult)

        if peak_mult < 2.0:
            continue

        peak_mc = max(current_mc, entry_mc * peak_mult)
        leaderboard.append({
            "mint":       mint,
            "name":       c.get("name", "?"),
            "symbol":     c.get("symbol", "?"),
            "entry_mc":   entry_mc,
            "current_mc": current_mc,
            "peak_mc":    peak_mc,
            "peak_mult":  peak_mult,
            "age_str":    c.get("added_at", "")[:10],
        })

    if not leaderboard:
        state["last_posted"] = now
        save_state(state)
        print("SKIP|No runners in last 24h")
        return

    leaderboard.sort(key=lambda x: -x["peak_mult"])
    top = leaderboard[:LEADERBOARD_SIZE]

    discord_msg  = format_leaderboard(top, platform="discord")
    telegram_msg = format_leaderboard(top, platform="telegram")

    state["last_posted"] = now
    save_state(state)

    # Post to Discord + Telegram
    try:
        from notifier.discord_poster import DiscordPoster
        discord = DiscordPoster()
        msg_id  = discord.post_runner(discord_msg)

        if msg_id:
            # Unpin previous leaderboard message, then pin the new one
            prev_pin = state.get("pinned_message_id")
            if prev_pin:
                discord.unpin_message(str(DISCORD_RUNNERS_CHANNEL), prev_pin)
            if discord.pin_message(str(DISCORD_RUNNERS_CHANNEL), msg_id):
                state["pinned_message_id"] = msg_id
                save_state(state)  # persist the new pin ID
    except Exception as e:
        print(f"Discord error: {e}", file=sys.stderr)

    try:
        from notifier.telegram_bot import TelegramNotifier
        TelegramNotifier().broadcast_text(telegram_msg)
    except Exception as e:
        print(f"Telegram error: {e}", file=sys.stderr)

    print(f"LEADERBOARD|{len(top)} entries posted")


if __name__ == "__main__":
    main()
