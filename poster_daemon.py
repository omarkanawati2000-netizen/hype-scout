#!/usr/bin/env python3
"""
poster_daemon.py — Hype Scout v2 Poster Daemon

Reads alerts_queue.jsonl every 10s.
Posts unposted entries to Discord + Telegram.
Marks entries posted=True, writes to tracked_coins.jsonl.
Max 3 posts per pass to avoid spam.
Single-instance via file lock.
"""
import json
import logging
import os
import sys
import io
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    POSTER_LOCK, POSTER_SLEEP, MAX_POST_PER_RUN, LOG_DIR,
    TELEGRAM_BOT_TOKEN,
)
from notifier.discord_poster import DiscordPoster
from notifier.telegram_bot import TelegramNotifier
from utils.formatter import format_discord_alert, format_telegram_alert
from utils.queue_utils import read_queue, write_queue, append_tracked

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "poster.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("poster")

discord   = DiscordPoster()
telegram  = TelegramNotifier() if TELEGRAM_BOT_TOKEN else None


# ── Lock ──────────────────────────────────────────────────────────────────────

def acquire_lock() -> bool:
    try:
        fd = os.open(str(POSTER_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        pass

    try:
        existing_pid = int(open(POSTER_LOCK).read().strip())
        try:
            os.kill(existing_pid, 0)
            logger.error(f"Poster already running (PID {existing_pid}). Exiting.")
            return False
        except (OSError, ProcessLookupError):
            logger.warning(f"Stale lock (PID {existing_pid}), taking over.")
            os.remove(POSTER_LOCK)
            fd = os.open(str(POSTER_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
    except Exception as e:
        logger.error(f"Lock error: {e}")
        return False


def release_lock():
    try:
        pid = int(open(POSTER_LOCK).read().strip())
        if pid == os.getpid():
            os.remove(POSTER_LOCK)
    except Exception:
        pass


# ── Build tracker entry ───────────────────────────────────────────────────────

def make_tracked_entry(d: dict, discord_msg_id: str = None) -> dict:
    return {
        "mint":            d.get("mint"),
        "name":            d.get("name"),
        "symbol":          d.get("symbol"),
        "entry_mc":        d.get("market_cap", 0),
        "current_mc":      d.get("market_cap", 0),
        "liquidity_usd":   d.get("liquidity_usd", 0),
        "vol_h1":          d.get("vol_h1", 0),
        "buys_h1":         d.get("buys_h1", 0),
        "sells_h1":        d.get("sells_h1", 0),
        "bonding_curve":   d.get("bonding_curve_progress", 0),
        "posted_at":       int(time.time()),
        "added_at":        datetime.now().isoformat(),
        "pump_alerts":     {},
        "last_check":      None,
        "discord_msg_id":  discord_msg_id,   # original scan alert message ID
    }


# ── Process queue ─────────────────────────────────────────────────────────────

def process_queue():
    entries = read_queue()
    if not entries:
        return

    # Group unposted by mint, pick best ATH MC per mint
    by_mint: dict = defaultdict(list)
    for e in entries:
        if not e.get("posted", False):
            by_mint[e["mint"]].append(e)

    if not by_mint:
        return

    # Limit posts per pass
    to_post = dict(list(by_mint.items())[:MAX_POST_PER_RUN])
    posted_mints: set = set()

    for mint, items in to_post.items():
        best = max(items, key=lambda x: x.get("ath_market_cap", 0))

        # Format messages
        try:
            discord_msg  = format_discord_alert(best)
            telegram_msg = format_telegram_alert(best) if telegram else None
        except Exception as e:
            logger.error(f"Format error for {best.get('name')}: {e}")
            posted_mints.add(mint)
            continue

        # Post to Discord — capture message ID for jump links
        discord_msg_id = discord.post_alert(discord_msg)

        # Post to Telegram subscribers
        tg_ok = 0
        if telegram and telegram_msg:
            tg_ok = telegram.broadcast_alert(best)

        if discord_msg_id:
            posted_mints.add(mint)
            append_tracked(make_tracked_entry(best, discord_msg_id=discord_msg_id))
            logger.info(
                f"✅ {best.get('name')} ${best.get('market_cap', 0):,.0f} "
                f"| Discord ✓ | Telegram: {tg_ok} subs"
            )
            time.sleep(1.5)  # avoid rate limits
        else:
            logger.warning(f"❌ Discord failed for {best.get('name')}")

    # Mark posted in queue
    if posted_mints:
        fresh = read_queue()
        now   = int(time.time())
        for e in fresh:
            if e["mint"] in posted_mints and not e.get("posted", False):
                e["posted"]    = True
                e["posted_at"] = now
        write_queue(fresh)
        logger.info(f"Marked {len(posted_mints)} mints as posted.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Poster daemon v2 starting (PID {os.getpid()})...")

    if not acquire_lock():
        sys.exit(0)

    try:
        while True:
            try:
                process_queue()
            except Exception as e:
                logger.error(f"Loop error: {e}\n{traceback.format_exc()}")
            time.sleep(POSTER_SLEEP)
    except KeyboardInterrupt:
        logger.info("Poster stopped by user.")
    finally:
        release_lock()
        logger.info("Poster daemon stopped.")
