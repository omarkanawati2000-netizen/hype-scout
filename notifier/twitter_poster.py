"""
notifier/twitter_poster.py — Auto-tweet runner alerts to @PumpScannerTool

Milestones (fires once per coin per tier): 3x / 5x / 10x / 15x / 20x / 25x / 50x / 100x

Recap schedule:
  - Every 3h  → top 3 runners from past 3h
  - Every 12h → top 10 runners from past 12h

State tracked in data/twitter_state.json
"""
import json
import logging
import random
import sys
import time
from pathlib import Path

import requests as req

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    TWITTER_API_KEY, TWITTER_API_SECRET,
    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET,
    TWITTER_BEARER_TOKEN,
    DISCORD_BOT_TOKEN,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TWITTER_DEMO_MODE = False  # True = Discord preview, False = real tweets

THRESHOLDS = [3.0, 5.0, 10.0, 15.0, 20.0, 25.0, 50.0, 100.0]  # milestone tweet triggers

RECAP_3H_INTERVAL  = 3 * 3600   # 3 hours
RECAP_12H_INTERVAL = 12 * 3600  # 12 hours
RECAP_3H_COUNT     = 3
RECAP_12H_COUNT    = 10

DISCORD_PREVIEW_CHANNEL = "1475223354066600036"  # #bot-logs
STATE_FILE = DATA_DIR / "twitter_state.json"


# ── State ──────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "fired_thresholds": {},   # mint -> [3.0, 5.0, ...]
        "last_tweet_at":    0,
        "last_3h_recap":    0,
        "last_12h_recap":   0,
    }


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── Threshold helper ───────────────────────────────────────────────────────────

def get_tweet_threshold(mult: float, fired: list) -> float | None:
    """Return the highest unfired threshold this mult has crossed, or None."""
    eligible = [t for t in THRESHOLDS if mult >= t and t not in fired]
    return max(eligible) if eligible else None


# ── Formatters ─────────────────────────────────────────────────────────────────

def _fmt_usd(val: float) -> str:
    if val >= 1_000_000: return f"${val/1_000_000:.1f}M"
    if val >= 1_000:     return f"${val/1_000:.0f}K"
    return f"${val:.0f}"


def _fmt_mult(m: float) -> str:
    return f"{m:.0f}X" if m >= 10 else f"{m:.1f}X".rstrip("0X").rstrip(".") + "X"


# ── Per-milestone tweet templates ──────────────────────────────────────────────

_TEMPLATES = {
    3.0: [
        "${ticker} is already at 3X\n\nPumpScanner flagged it at entry ({entry_mc}). still moving",
        "🔍 ${ticker} just crossed 3X from a {entry_mc} entry\n\nscanner caught it before the move",
        "${ticker} up 3X and climbing 📈\n\nPumpScanner had this at {entry_mc} entry\n\ncatch the next one → link in bio",
    ],
    5.0: [
        "${ticker} just hit 5X 🚀\n\nstill running from the {entry_mc} entry PumpScanner flagged",
        "update: ${ticker} is now up 5X\n\nwas a {entry_mc} market cap when the scanner caught it",
        "🚨 ${ticker} crossing 5X right now\n\nPumpScanner alert went out at {entry_mc}. this is what we do\n\nfree alerts → link in bio",
    ],
    10.0: [
        "${ticker} just crossed 10X 🔥\n\nentry was at {entry_mc}. currently at {current_mc}\n\nPumpScanner catches these early",
        "10X on ${ticker} 🤯\n\nscanner flagged it at {entry_mc} before anyone was talking about it",
        "🚨 ${ticker} is running hard — just hit 10X\n\nfrom a {entry_mc} entry. PumpScanner had this\n\nfree alerts → link in bio $sol",
    ],
    15.0: [
        "${ticker} just crossed 15X 👀\n\nPumpScanner had this at {entry_mc}. now {current_mc}\n\nstill going",
        "15X on ${ticker} 🚀\n\nflagged at {entry_mc} entry. this is what early looks like",
        "🔥 ${ticker} up 15X from the scanner entry signal\n\n{entry_mc} → {current_mc}\n\ncatch the next one → link in bio",
    ],
    20.0: [
        "${ticker} just hit 20X 💀\n\ncaught at {entry_mc} — now {current_mc}\n\nPumpScanner called it",
        "20X. ${ticker}. scanner entry was {entry_mc} 🤯\n\nthese are the ones that matter",
        "🚨 ${ticker} up 20X from the PumpScanner signal\n\n{entry_mc} → {current_mc}\n\nfree alerts → link in bio $sol",
    ],
    25.0: [
        "${ticker} just went 25X 💀\n\ncaught at {entry_mc} by PumpScanner. now sitting at {current_mc}",
        "25X on ${ticker}. not a typo 🚀\n\n{entry_mc} → {current_mc}\n\nalerts went out at entry",
        "🔥 ${ticker} up 25X from the PumpScanner entry signal\n\nthis is why we scan pump.fun 24/7\n\nlink in bio $sol",
    ],
    50.0: [
        "${ticker} is a 50X runner 🏆\n\nPumpScanner flagged it at {entry_mc}\n\n{entry_mc} → {current_mc}. insane",
        "50X on ${ticker} 💀\n\nscanner caught this at {entry_mc} before the crowd\n\nfree alerts → link in bio",
        "🚨 ${ticker} just crossed 50X\n\n{entry_mc} entry → {current_mc} now\n\nPumpScanner $sol",
    ],
    100.0: [
        "${ticker} just hit 100X 🏆\n\n{entry_mc} → {current_mc}. PumpScanner flagged this at entry",
        "100X. ${ticker}. PumpScanner called it at {entry_mc} 🤯\n\nthis is what the scanner is built for\n\nlink in bio",
        "💀 ${ticker} is a 100X runner\n\ncaught at {entry_mc} entry. running to {current_mc}\n\nPumpScanner $sol",
    ],
}

# Roughly 1 in 4 tweets gets a subtle CTA appended
_CTA_LINES = [
    "\n\nfree alerts → link in bio",
    "\n\ntelegram in bio",
    "\n\ncatch the next one → link in bio",
]
_CTA_FREQUENCY = 4  # append CTA every N tweets


_tweet_counter = [0]  # mutable int to track CTA rotation

def format_milestone_tweet(runner: dict, threshold: float) -> str:
    name       = runner.get("name", "COIN")
    symbol     = runner.get("symbol", name).upper().replace("$", "").strip()
    entry_mc   = _fmt_usd(runner.get("entry_mc", 0))
    current_mc = _fmt_usd(runner.get("current_mc", 0))

    templates = _TEMPLATES.get(threshold, _TEMPLATES[3.0])
    text = random.choice(templates).format(
        ticker=symbol,
        entry_mc=entry_mc,
        current_mc=current_mc,
    )

    # Append subtle CTA roughly 1 in every N tweets
    _tweet_counter[0] += 1
    if _tweet_counter[0] % _CTA_FREQUENCY == 0 and "link in bio" not in text and "telegram" not in text:
        text += random.choice(_CTA_LINES)

    return text[:280]


# ── Recap formatters ───────────────────────────────────────────────────────────

def format_3h_recap(runners: list) -> str:
    """Top N runners from past 3h — brag format."""
    lines = "\n".join(
        f"${r['symbol'].upper()} — {_fmt_mult(r['mult'])}"
        for r in runners[:RECAP_3H_COUNT]
    )
    return (
        f"past 3 hours from PumpScanner 👇\n\n"
        f"{lines}\n\n"
        f"all flagged at entry. free telegram alerts → link in bio"
    )[:280]


def format_12h_recap(runners: list) -> str:
    """Top N runners from past 12h — flex format."""
    pairs = [f"${r['symbol'].upper()} {_fmt_mult(r['mult'])}" for r in runners[:RECAP_12H_COUNT]]
    # Two per line to keep it compact
    rows = [" | ".join(pairs[i:i+2]) for i in range(0, len(pairs), 2)]
    body = "\n".join(rows)
    return (
        f"PumpScanner's top runners — last 12 hours 👇\n\n"
        f"{body}\n\n"
        f"all caught at entry. free telegram → link in bio"
    )[:280]


# ── Discord preview (demo mode) ────────────────────────────────────────────────

def _post_discord_preview(text: str, label: str = "TWEET PREVIEW"):
    try:
        resp = req.post(
            f"https://discord.com/api/v10/channels/{DISCORD_PREVIEW_CHANNEL}/messages",
            headers={
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"content": f"**[{label}]**\n```\n{text}\n```"},
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.warning(f"Discord preview failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"Discord preview error: {e}")


# ── Main class ─────────────────────────────────────────────────────────────────

class TwitterPoster:
    def __init__(self):
        self._client = None
        self._ready  = False

        if not all([TWITTER_API_KEY, TWITTER_API_SECRET,
                    TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
            logger.warning("Twitter credentials not configured")
            return

        try:
            import tweepy
            self._client = tweepy.Client(
                bearer_token        = TWITTER_BEARER_TOKEN or None,
                consumer_key        = TWITTER_API_KEY,
                consumer_secret     = TWITTER_API_SECRET,
                access_token        = TWITTER_ACCESS_TOKEN,
                access_token_secret = TWITTER_ACCESS_TOKEN_SECRET,
            )
            self._ready = True
            mode = "DEMO" if TWITTER_DEMO_MODE else "LIVE"
            logger.info(f"Twitter poster ready [{mode}] — milestones: {THRESHOLDS}")
        except Exception as e:
            logger.error(f"Twitter init error: {e}")

    def _tweet(self, text: str, label: str = "TWEET") -> bool:
        if TWITTER_DEMO_MODE:
            _post_discord_preview(text, label)
            return True
        try:
            resp = self._client.create_tweet(text=text)
            tweet_id = resp.data.get("id") if resp.data else "?"
            logger.info(f"Tweeted [{label}] id={tweet_id}")
            return True
        except Exception as e:
            logger.error(f"Tweet error [{label}]: {e}")
            return False

    def post_runner(self, runner: dict) -> bool:
        """Check milestones and tweet if a new threshold is crossed."""
        if not self._ready:
            return False

        mint  = runner.get("mint", "")
        mult  = runner.get("mult", 0)
        name  = runner.get("name", "?")

        state = _load_state()
        fired = state.setdefault("fired_thresholds", {}).get(mint, [])

        threshold = get_tweet_threshold(mult, fired)
        if threshold is None:
            return False  # no new milestone to announce

        text = format_milestone_tweet(runner, threshold)
        ok   = self._tweet(text, label=f"{name} {threshold}x")

        if ok:
            fired.append(threshold)
            state["fired_thresholds"][mint] = fired
            state["last_tweet_at"] = time.time()
            _save_state(state)

        return ok

    @staticmethod
    def _dedup_runners(runners: list) -> list:
        """Keep only the peak multiplier entry per coin, sorted highest first."""
        best: dict = {}
        for r in runners:
            mint = r.get("mint", r.get("symbol", ""))
            if not mint:
                continue
            if mint not in best or r.get("mult", 0) > best[mint].get("mult", 0):
                best[mint] = r
        return sorted(best.values(), key=lambda x: -x.get("mult", 0))

    def maybe_post_recap(self, recent_runners: list):
        """Post 3h or 12h recap if it's time. Pass recent runners sorted by mult desc."""
        if not self._ready or not recent_runners:
            return

        state = _load_state()
        now   = time.time()

        # 3h recap
        if now - state.get("last_3h_recap", 0) >= RECAP_3H_INTERVAL:
            raw_3h     = [r for r in recent_runners if now - r.get("timestamp", 0) <= RECAP_3H_INTERVAL]
            runners_3h = self._dedup_runners(raw_3h)
            if len(runners_3h) >= 2:  # need at least 2 distinct coins
                text = format_3h_recap(runners_3h)
                if self._tweet(text, "3H RECAP"):
                    state["last_3h_recap"] = now
                    _save_state(state)

        # 12h recap
        if now - state.get("last_12h_recap", 0) >= RECAP_12H_INTERVAL:
            raw_12h     = [r for r in recent_runners if now - r.get("timestamp", 0) <= RECAP_12H_INTERVAL]
            runners_12h = self._dedup_runners(raw_12h)
            if len(runners_12h) >= 5:  # need at least 5 distinct coins
                text = format_12h_recap(runners_12h)
                if self._tweet(text, "12H RECAP"):
                    state["last_12h_recap"] = now
                    _save_state(state)


if __name__ == "__main__":
    poster = TwitterPoster()
    # Test milestone tweet
    test_runner = {
        "mint": "test_mint_abc123",
        "name": "TestCoin",
        "symbol": "TEST",
        "mult": 10.4,
        "entry_mc": 7500,
        "current_mc": 78000,
        "timestamp": time.time(),
    }
    print("--- Milestone tweet ---")
    poster.post_runner(test_runner)

    # Test recaps
    fake_runners = [
        {"symbol": "LION",  "mult": 18.2, "timestamp": time.time() - 1800},
        {"symbol": "DOVE",  "mult": 7.4,  "timestamp": time.time() - 3000},
        {"symbol": "WOLF",  "mult": 5.1,  "timestamp": time.time() - 5400},
        {"symbol": "BEAR",  "mult": 4.2,  "timestamp": time.time() - 7200},
        {"symbol": "TIGER", "mult": 3.5,  "timestamp": time.time() - 9000},
    ]
    print("\n--- 3h recap ---")
    print(format_3h_recap(fake_runners[:3]))
    print("\n--- 12h recap ---")
    print(format_12h_recap(fake_runners))
