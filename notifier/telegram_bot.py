#!/usr/bin/env python3
"""
notifier/telegram_bot.py — Public Telegram Signal Bot

Commands:
  /start        — Welcome message
  /subscribe    — Subscribe to real-time alerts
  /unsubscribe  — Unsubscribe from alerts
  /status       — Show scanner stats
  /runners      — Show current active runners (2x+)
  /leaderboard  — Top 10 performers last 24h
  /help         — List commands

Run as a standalone process: python -m notifier.telegram_bot
Or import TelegramNotifier for programmatic broadcasting.
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TELEGRAM_BOT_TOKEN, SUBSCRIBERS_FILE, PENDING_FILE, TRACKED_FILE, QUEUE_FILE, TELEGRAM_ADMIN_IDS
from utils.formatter import format_telegram_alert, format_runner_msg, format_leaderboard, fmt_usd, tier_emoji
from utils.queue_utils import load_tracked, load_milestones

logger = logging.getLogger(__name__)


# ── Subscriber management ──────────────────────────────────────────────────────
# Storage format: {"chat_id": {"chat_id": int, "username": str, "name": str, "joined_at": str}}

def load_subscribers_raw() -> dict:
    """Load full subscriber dict {str(chat_id): info}."""
    if not SUBSCRIBERS_FILE.exists():
        return {}
    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Migrate old list format → new dict format
            if isinstance(data, list):
                return {str(cid): {"chat_id": cid, "username": "", "name": "", "joined_at": ""} for cid in data}
            return data
    except Exception:
        return {}


def load_subscribers() -> list:
    """Return list of chat_ids (int) for broadcasting."""
    raw = load_subscribers_raw()
    return [int(k) for k in raw.keys()]


def save_subscribers(subs: dict):
    try:
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(subs, f, indent=2)
    except Exception as e:
        logger.error(f"Subscriber save error: {e}")


def add_subscriber(chat_id: int, username: str = "", name: str = "") -> bool:
    subs = load_subscribers_raw()
    key = str(chat_id)
    if key not in subs:
        subs[key] = {
            "chat_id":   chat_id,
            "username":  username,
            "name":      name,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        save_subscribers(subs)
        return True
    return False


def remove_subscriber(chat_id: int) -> bool:
    subs = load_subscribers_raw()
    key = str(chat_id)
    if key in subs:
        del subs[key]
        save_subscribers(subs)
        return True
    return False


def get_subscriber_list() -> list:
    """Return list of subscriber info dicts, sorted by join date."""
    raw = load_subscribers_raw()
    return sorted(raw.values(), key=lambda x: x.get("joined_at", ""))


# ── Pending request management ────────────────────────────────────────────────

def load_pending() -> dict:
    """Load pending requests dict {str(chat_id): info}."""
    if not PENDING_FILE.exists():
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_pending(pending: dict):
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2)
    except Exception as e:
        logger.error(f"Pending save error: {e}")


def add_pending(chat_id: int, username: str = "", name: str = "") -> bool:
    """Add a pending request. Returns False if already pending or subscribed."""
    if str(chat_id) in load_subscribers_raw():
        return False  # already subscribed
    pending = load_pending()
    key = str(chat_id)
    if key in pending:
        return False  # already pending
    pending[key] = {
        "chat_id":      chat_id,
        "username":     username,
        "name":         name,
        "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_pending(pending)
    return True


def remove_pending(chat_id: int) -> dict | None:
    """Remove and return a pending request, or None if not found."""
    pending = load_pending()
    key = str(chat_id)
    entry = pending.pop(key, None)
    if entry:
        save_pending(pending)
    return entry


# ── TelegramNotifier — broadcast helper ───────────────────────────────────────

class TelegramNotifier:
    """Lightweight broadcaster using raw HTTP (no bot polling needed)."""

    def __init__(self, token: str = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self._base = f"https://api.telegram.org/bot{self.token}"

    def _send(self, chat_id: int | str, text: str, parse_mode: str = "HTML") -> bool:
        import requests as req_lib
        url = f"{self._base}/sendMessage"
        try:
            resp = req_lib.post(url, json={
                "chat_id":    chat_id,
                "text":       text[:4096],
                "parse_mode": parse_mode,
                "disable_web_page_preview": False,
            }, timeout=10)
            if not resp.ok:
                logger.error(f"Telegram HTTP {resp.status_code}: {resp.text}")
            return resp.ok
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def broadcast_alert(self, alert_dict: dict) -> int:
        """Broadcast a token alert to all subscribers. Returns success count."""
        if not self.token:
            return 0
        msg  = format_telegram_alert(alert_dict)
        subs = load_subscribers()  # returns list of int chat_ids
        ok   = 0
        for chat_id in subs:
            if self._send(chat_id, msg):
                ok += 1
        return ok

    def broadcast_text(self, text: str) -> int:
        """Broadcast raw HTML text to all subscribers."""
        if not self.token:
            return 0
        subs = load_subscribers()
        ok   = 0
        for chat_id in subs:
            if self._send(chat_id, text):
                ok += 1
        return ok

    def get_subscriber_count(self) -> int:
        return len(load_subscribers())

    def send_to(self, chat_id: int | str, text: str) -> bool:
        return self._send(chat_id, text)


# ── Bot command handlers ───────────────────────────────────────────────────────

async def run_bot():
    """Run the full bot with command polling using python-telegram-bot."""
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes
    except ImportError:
        logger.error(
            "python-telegram-bot not installed. Run: pip install python-telegram-bot>=20.0"
        )
        sys.exit(1)

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN not set in .env — "
            "get one from @BotFather on Telegram."
        )
        sys.exit(1)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "👋 <b>Welcome to Hype Scout!</b>\n\n"
            "🔥 I scan Pump.fun every 30 seconds and alert you to early-stage Solana "
            "memecoins before they pump.\n\n"
            "📡 <b>What I track:</b>\n"
            "  • Market cap: $5K–$60K\n"
            "  • Bonding curve &lt;85%\n"
            "  • Minimum holder protection\n"
            "  • Live 2x/3x/5x/10x runner alerts\n\n"
            "Use /subscribe to start receiving real-time alerts.\n"
            "Use /help to see all commands."
        )

    async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id  = update.effective_chat.id
        user     = update.effective_user
        username = f"@{user.username}" if user and user.username else "(no username)"
        name     = user.full_name if user else "Unknown"

        # Already subscribed?
        if str(chat_id) in load_subscribers_raw():
            await update.message.reply_text("You're already subscribed! 🟢")
            return

        # Already pending?
        if str(chat_id) in load_pending():
            await update.message.reply_html(
                "⏳ <b>Your request is pending approval.</b>\n"
                "You'll get a message when you're approved!"
            )
            return

        # Add to pending + notify admin
        added = add_pending(chat_id, username=username, name=name)
        if added:
            await update.message.reply_html(
                "📨 <b>Access request sent!</b>\n\n"
                "The admin will review your request. "
                "You'll receive a message here once approved. 🙏"
            )
            logger.info(f"Access request from: {name} {username} (chat_id: {chat_id})")

            # DM every admin
            notifier = TelegramNotifier()
            for admin_id in TELEGRAM_ADMIN_IDS:
                notifier.send_to(admin_id,
                    f"🔔 <b>New Subscription Request</b>\n\n"
                    f"👤 Name: <b>{name}</b>\n"
                    f"🔖 Username: {username}\n"
                    f"🆔 Chat ID: <code>{chat_id}</code>\n\n"
                    f"To approve: <code>/approve {chat_id}</code>\n"
                    f"To deny:    <code>/deny {chat_id}</code>"
                )
        else:
            await update.message.reply_text("You're already subscribed! 🟢")

    async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if remove_subscriber(chat_id):
            await update.message.reply_text("❌ Unsubscribed. You won't receive alerts anymore.")
        else:
            await update.message.reply_text("You weren't subscribed.")

    async def cmd_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Admin only: /approve <chat_id>"""
        if TELEGRAM_ADMIN_IDS and update.effective_chat.id not in TELEGRAM_ADMIN_IDS:
            await update.message.reply_text("⛔ Admin only.")
            return

        if not ctx.args:
            await update.message.reply_text("Usage: /approve <chat_id>")
            return

        try:
            target_id = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("Invalid chat_id — must be a number.")
            return

        entry = remove_pending(target_id)
        if not entry:
            # Check if already subscribed
            if str(target_id) in load_subscribers_raw():
                await update.message.reply_text(f"⚠️ {target_id} is already subscribed.")
            else:
                await update.message.reply_text(f"⚠️ No pending request found for {target_id}.")
            return

        add_subscriber(target_id, username=entry.get("username", ""), name=entry.get("name", ""))
        name     = entry.get("name", "Unknown")
        username = entry.get("username", "")

        await update.message.reply_html(f"✅ Approved <b>{name}</b> {username} (<code>{target_id}</code>)")

        # Notify the new subscriber
        notifier = TelegramNotifier()
        notifier.send_to(target_id,
            "✅ <b>You've been approved!</b>\n\n"
            "Welcome to Hype Scout 🚀 You'll now receive real-time Solana memecoin alerts.\n\n"
            "Use /unsubscribe anytime to stop."
        )
        logger.info(f"Approved subscriber: {name} {username} ({target_id})")

    async def cmd_deny(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Admin only: /deny <chat_id>"""
        if TELEGRAM_ADMIN_IDS and update.effective_chat.id not in TELEGRAM_ADMIN_IDS:
            await update.message.reply_text("⛔ Admin only.")
            return

        if not ctx.args:
            await update.message.reply_text("Usage: /deny <chat_id>")
            return

        try:
            target_id = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("Invalid chat_id — must be a number.")
            return

        entry = remove_pending(target_id)
        if not entry:
            await update.message.reply_text(f"⚠️ No pending request found for {target_id}.")
            return

        name     = entry.get("name", "Unknown")
        username = entry.get("username", "")
        await update.message.reply_html(f"❌ Denied <b>{name}</b> {username} (<code>{target_id}</code>)")

        # Optionally notify the denied user
        notifier = TelegramNotifier()
        notifier.send_to(target_id,
            "❌ <b>Access request denied.</b>\n\n"
            "Your subscription request was not approved at this time."
        )
        logger.info(f"Denied request: {name} {username} ({target_id})")

    async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Admin only: show pending requests."""
        if TELEGRAM_ADMIN_IDS and update.effective_chat.id not in TELEGRAM_ADMIN_IDS:
            await update.message.reply_text("⛔ Admin only.")
            return

        pending = load_pending()
        if not pending:
            await update.message.reply_text("✅ No pending requests.")
            return

        lines = [f"⏳ <b>Pending Requests ({len(pending)})</b>\n"]
        for entry in sorted(pending.values(), key=lambda x: x.get("requested_at", "")):
            cid      = entry.get("chat_id")
            name     = entry.get("name", "Unknown")
            username = entry.get("username", "")
            when     = entry.get("requested_at", "?")
            lines.append(
                f"👤 <b>{name}</b> {username}\n"
                f"   🆔 <code>{cid}</code> · {when}\n"
                f"   /approve {cid}  |  /deny {cid}\n"
            )

        await update.message.reply_html("\n".join(lines))

    async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        import json as _json
        subs  = load_subscribers()
        coins = load_tracked(max_age_hours=24)

        # Count confirmed runners from live scan state (accurate, no live fetch needed)
        runner_count = 0
        try:
            from config import LIVE_SCAN_STATE
            if LIVE_SCAN_STATE.exists():
                scan_state = _json.loads(LIVE_SCAN_STATE.read_text(encoding="utf-8"))
                runner_count = sum(1 for alerts in scan_state.get("alerts", {}).values() if alerts)
        except Exception:
            pass

        # Queue depth
        queue_depth = 0
        try:
            from config import QUEUE_FILE
            if QUEUE_FILE.exists():
                queue_depth = sum(
                    1 for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not _json.loads(line).get("posted", True)
                )
        except Exception:
            pass

        await update.message.reply_html(
            f"📊 <b>Hype Scout Status</b>\n\n"
            f"👥 Subscribers: <b>{len(subs)}</b>\n"
            f"🪙 Coins tracked (24h): <b>{len(coins)}</b>\n"
            f"🚀 Coins w/ alerts fired: <b>{runner_count}</b>\n"
            f"📥 Queue pending: <b>{queue_depth}</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')} MST"
        )

    async def cmd_runners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        from utils.dexscreener import get_live_mc
        import time as _time

        await update.message.reply_text("🔍 Fetching live prices... (this takes ~10s)")

        coins = load_tracked(max_age_hours=24)
        runners = []

        for mint, c in coins.items():
            entry_mc = c.get("entry_mc", 0)
            if entry_mc <= 0:
                continue
            # Fetch LIVE market cap from DexScreener
            live = get_live_mc(mint)
            if not live or live["mc"] <= 0:
                continue
            current_mc = live["mc"]
            mult = round(current_mc / max(entry_mc, 1), 1)
            if mult >= 2.0:
                runners.append({
                    "mint":       mint,
                    "name":       c.get("name", "?"),
                    "symbol":     c.get("symbol", "?"),
                    "mult":       mult,
                    "entry_mc":   entry_mc,
                    "current_mc": current_mc,
                    "liq":        live.get("liq", 0),
                    "vol_h1":     live.get("vol_h1", 0),
                    "buys_h1":    live.get("buys_h1", 0),
                    "sells_h1":   live.get("sells_h1", 0),
                })
            _time.sleep(0.3)  # DexScreener rate limit

        if not runners:
            await update.message.reply_text("No active runners right now. Check back soon! 👀")
            return

        runners.sort(key=lambda x: -x["mult"])
        msg = format_runner_msg(runners[:10], platform="telegram")
        await update.message.reply_html(msg)

    async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        from utils.dexscreener import get_live_mc
        import time as _time

        await update.message.reply_text("🏆 Building leaderboard with live prices...")

        coins = load_tracked(max_age_hours=24)

        # Also pull peak tiers from live_scan_state (already-fired alerts)
        peak_map = {}
        try:
            import json as _json
            from config import LIVE_SCAN_STATE
            if LIVE_SCAN_STATE.exists():
                scan_state = _json.loads(LIVE_SCAN_STATE.read_text(encoding="utf-8"))
                for mint, alerts in scan_state.get("alerts", {}).items():
                    fired_tiers = [float(k.replace("x", "")) for k in alerts.keys()]
                    if fired_tiers:
                        peak_map[mint] = max(fired_tiers)
        except Exception:
            pass

        leaderboard = []
        for mint, c in coins.items():
            entry_mc = c.get("entry_mc", 0)
            if entry_mc <= 0:
                continue
            # Fetch live MC from DexScreener
            live = get_live_mc(mint)
            current_mc = live["mc"] if live else 0
            live_mult = round(current_mc / max(entry_mc, 1), 1) if current_mc > 0 else 0
            peak_mult = max(peak_map.get(mint, 0), live_mult)
            if peak_mult >= 2.0:
                leaderboard.append({
                    "mint":       mint,
                    "name":       c.get("name", "?"),
                    "symbol":     c.get("symbol", "?"),
                    "entry_mc":   entry_mc,
                    "current_mc": current_mc,
                    "peak_mc":    max(current_mc, entry_mc * peak_mult),
                    "peak_mult":  peak_mult,
                    "age_str":    c.get("added_at", "")[:10],
                })
            _time.sleep(0.3)  # DexScreener rate limit

        if not leaderboard:
            await update.message.reply_text("No leaderboard data yet. Check back soon!")
            return

        leaderboard.sort(key=lambda x: -x["peak_mult"])
        msg = format_leaderboard(leaderboard[:10], platform="telegram")
        await update.message.reply_html(msg)

    async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Admin-only dashboard."""
        if TELEGRAM_ADMIN_IDS and update.effective_chat.id not in TELEGRAM_ADMIN_IDS:
            await update.message.reply_text("⛔ Admin only.")
            return

        import json as _json
        import os as _os

        # ── Section: Subscribers ──────────────────────────────────────────────
        pending_count = len(load_pending())
        subs = get_subscriber_list()
        sub_lines = []
        for i, s in enumerate(subs, 1):
            name     = s.get("name", "Unknown")
            username = s.get("username", "")
            joined   = s.get("joined_at", "?")
            display  = f"{name} {username}".strip()
            sub_lines.append(f"  {i}. {display} · {joined}")
        sub_block = "\n".join(sub_lines) if sub_lines else "  No subscribers yet"

        # ── Section: Win Rate ─────────────────────────────────────────────────
        coins = load_tracked(max_age_hours=24)
        total_tracked = len(coins)
        winners = 0
        try:
            from config import LIVE_SCAN_STATE
            if LIVE_SCAN_STATE.exists():
                scan_state = _json.loads(LIVE_SCAN_STATE.read_text(encoding="utf-8"))
                winners = sum(1 for alerts in scan_state.get("alerts", {}).values() if alerts)
        except Exception:
            pass
        win_rate = f"{(winners / total_tracked * 100):.1f}%" if total_tracked > 0 else "N/A"

        # ── Section: Today's throughput ───────────────────────────────────────
        total_posted = 0
        queue_pending = 0
        try:
            from config import QUEUE_FILE
            if QUEUE_FILE.exists():
                lines = [l for l in QUEUE_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
                total_posted  = sum(1 for l in lines if _json.loads(l).get("posted", False))
                queue_pending = sum(1 for l in lines if not _json.loads(l).get("posted", True))
        except Exception:
            pass

        # ── Section: System health ────────────────────────────────────────────
        from config import POLLER_LOCK, POSTER_LOCK
        def check_lock(lock_path):
            try:
                pid = int(lock_path.read_text().strip())
                _os.kill(pid, 0)
                return f"✅ alive (PID {pid})"
            except Exception:
                return "❌ down"

        scanner_status = check_lock(POLLER_LOCK)
        poster_status  = check_lock(POSTER_LOCK)
        tg_status      = "✅ alive (this process)"

        # ── Build message ─────────────────────────────────────────────────────
        msg = (
            f"🔐 <b>ADMIN PANEL</b> · {datetime.now().strftime('%Y-%m-%d %H:%M')} MST\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"

            f"👥 <b>Subscribers ({len(subs)})</b>  |  ⏳ Pending: {pending_count} (/pending)\n"
            f"{sub_block}\n\n"

            f"📊 <b>Win Rate (24h)</b>\n"
            f"  Tracked: <b>{total_tracked}</b> coins\n"
            f"  Hit 2x+: <b>{winners}</b> coins\n"
            f"  Rate: <b>{win_rate}</b>\n\n"

            f"📥 <b>Throughput</b>\n"
            f"  Posted today: <b>{total_posted}</b>\n"
            f"  Queue pending: <b>{queue_pending}</b>\n\n"

            f"🖥 <b>System Health</b>\n"
            f"  Scanner: {scanner_status}\n"
            f"  Poster:  {poster_status}\n"
            f"  TG Bot:  {tg_status}\n"
        )

        if len(msg) > 4000:
            msg = msg[:3990] + "\n…(truncated)"
        await update.message.reply_html(msg)

    async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "🤖 <b>Hype Scout Commands</b>\n\n"
            "/subscribe — Request access to real-time alerts\n"
            "/unsubscribe — Stop receiving alerts\n"
            "/status — Scanner stats\n"
            "/runners — Active coins at 2x+ (live)\n"
            "/leaderboard — Top performers today (live)\n"
            "/help — This message\n\n"
            "📡 Scanning Pump.fun every 30 seconds.\n"
            "⚠️ Subscriptions require admin approval."
        )

    # ── Build and run app ─────────────────────────────────────────────────────
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("subscribe",   cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("approve",     cmd_approve))
    app.add_handler(CommandHandler("deny",        cmd_deny))
    app.add_handler(CommandHandler("pending",     cmd_pending))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("runners",     cmd_runners))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("admin",       cmd_admin))
    app.add_handler(CommandHandler("help",        cmd_help))

    return app


def start_bot():
    """Start the Telegram bot — manages its own event loop (PTB 20+ style)."""
    try:
        from telegram.ext import Application
    except ImportError:
        print("Run: pip install python-telegram-bot>=20.0")
        sys.exit(1)

    if not TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in .env")
        sys.exit(1)

    logger.info("Starting Telegram bot polling...")

    async def _build_and_run():
        app = await run_bot()
        # run_polling manages its own lifecycle
        async with app:
            await app.start()
            await app.updater.start_polling(allowed_updates=["message"])
            logger.info("Telegram bot is live. Press Ctrl+C to stop.")
            # Keep running until interrupted
            import signal as sig
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for s in (sig.SIGINT, sig.SIGTERM):
                try:
                    loop.add_signal_handler(s, stop_event.set)
                except NotImplementedError:
                    pass  # Windows doesn't support add_signal_handler
            try:
                await stop_event.wait()
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                await app.updater.stop()
                await app.stop()

    asyncio.run(_build_and_run())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    start_bot()
