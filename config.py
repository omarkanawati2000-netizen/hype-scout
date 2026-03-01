"""
config.py — Central configuration for Hype Scout v2
Loads from .env, provides typed constants to all modules.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR  = BASE_DIR / "logs"

# Create dirs if missing
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv(BASE_DIR / ".env")

# ── API Keys ──────────────────────────────────────────────────────────────────
HELIUS_API_KEY      = os.getenv("HELIUS_API_KEY", "")
DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Discord Channels ───────────────────────────────────────────────────────────
DISCORD_EARLY_TRENDING_CHANNEL = os.getenv("DISCORD_EARLY_TRENDING_CHANNEL", "1477161564460159097")
DISCORD_RUNNERS_CHANNEL        = os.getenv("DISCORD_RUNNERS_CHANNEL", "1477453762959249559")

# ── Telegram (optional) ────────────────────────────────────────────────────────
TELEGRAM_CHANNEL_ID   = os.getenv("TELEGRAM_CHANNEL_ID", "")
TELEGRAM_ADMIN_IDS    = [int(x) for x in os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").split(",") if x.strip()]

# ── Scanner Thresholds ─────────────────────────────────────────────────────────
MC_MIN_USD      = float(os.getenv("MC_MIN_USD", "5000"))
MC_MAX_USD      = float(os.getenv("MC_MAX_USD", "60000"))
BC_MAX_PCT      = float(os.getenv("BC_MAX_PCT", "85"))        # bonding curve %
MIN_SOL_LIQ     = float(os.getenv("MIN_SOL_LIQ", "0.5"))      # SOL liquidity
MIN_HOLDERS     = int(os.getenv("MIN_HOLDERS", "10"))

# ── Runtime ────────────────────────────────────────────────────────────────────
POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL", "30"))       # seconds between scans
POSTER_SLEEP    = int(os.getenv("POSTER_SLEEP", "10"))        # seconds between poster passes
MAX_POST_PER_RUN = int(os.getenv("MAX_POST_PER_RUN", "3"))   # max alerts per poster pass

# ── Tracker ────────────────────────────────────────────────────────────────────
TRACK_MAX_AGE_HOURS = int(os.getenv("TRACK_MAX_AGE_HOURS", "24"))
TIER_COOLDOWN_MIN   = int(os.getenv("TIER_COOLDOWN_MIN", "30"))    # minutes per tier cooldown
PUMP_THRESHOLDS     = [2.0, 3.0, 5.0, 10.0, 20.0]

# ── File Paths ─────────────────────────────────────────────────────────────────
QUEUE_FILE       = DATA_DIR / "alerts_queue.jsonl"
TRACKED_FILE     = DATA_DIR / "tracked_coins.jsonl"
SEEN_MINTS_FILE  = DATA_DIR / "seen_mints.txt"
MILESTONES_FILE  = DATA_DIR / "performance_milestones.jsonl"
SUBSCRIBERS_FILE = DATA_DIR / "telegram_subscribers.json"
PENDING_FILE     = DATA_DIR / "pending_requests.json"
DIGEST_STATE     = DATA_DIR / "digest_state.json"
LIVE_SCAN_STATE  = DATA_DIR / "live_scan_state.json"
LEADERBOARD_STATE = DATA_DIR / "leaderboard_state.json"
POLLER_LOCK      = DATA_DIR / "poller.lock"
POSTER_LOCK      = DATA_DIR / "poster.lock"

# ── Pump.fun API ───────────────────────────────────────────────────────────────
PUMP_API_BASE    = "https://frontend-api-v3.pump.fun"
PUMP_BATCH_SIZE  = 50
DEXSCREENER_API  = "https://api.dexscreener.com/latest/dex/tokens"
HELIUS_RPC_URL   = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
