"""
utils/queue_utils.py — Shared file I/O for queue, tracked coins, and seen mints.
All functions are safe for concurrent reads; writes use atomic replace where possible.
"""
import json
import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from config import QUEUE_FILE, TRACKED_FILE, SEEN_MINTS_FILE, MILESTONES_FILE

logger = logging.getLogger(__name__)


# ── Queue (alerts_queue.jsonl) ─────────────────────────────────────────────────

def read_queue() -> list:
    """Read all entries from alerts_queue.jsonl. Tolerates malformed lines."""
    if not QUEUE_FILE.exists():
        return []
    entries = []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        logger.warning(f"Queue read error: {e}")
    return entries


def write_queue(entries: list):
    """Atomically rewrite the queue file."""
    tmp = str(QUEUE_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        os.replace(tmp, QUEUE_FILE)
    except Exception as e:
        logger.error(f"Queue write error: {e}")
        try:
            os.remove(tmp)
        except Exception:
            pass


def append_to_queue(entry: dict):
    """Append a single entry to the queue (non-atomic, fast path for scanner)."""
    try:
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Queue append error: {e}")


# ── Tracked coins (tracked_coins.jsonl) ───────────────────────────────────────

def load_tracked(max_age_hours: int = 24) -> dict:
    """
    Load tracked coins added within max_age_hours.
    Returns {mint: entry_dict}. Last entry per mint wins (handles duplicates).
    """
    if not TRACKED_FILE.exists():
        return {}
    cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
    coins = {}
    try:
        with open(TRACKED_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    mint = e.get("mint", "")
                    if not mint or e.get("entry_mc", 0) <= 0:
                        continue
                    # Parse timestamp
                    added_at = e.get("added_at") or e.get("entry_time")
                    ts = 0
                    if added_at:
                        if isinstance(added_at, (int, float)):
                            ts = float(added_at)
                        else:
                            try:
                                ts = datetime.fromisoformat(str(added_at)).timestamp()
                            except Exception:
                                pass
                    if ts and ts < cutoff:
                        continue
                    coins[mint] = e
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Tracked load error: {e}")
    return coins


def append_tracked(entry: dict):
    """Append a new tracked coin entry."""
    try:
        with open(TRACKED_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Tracked append error: {e}")


def save_tracked(coins: dict):
    """Atomically rewrite tracked coins from a {mint: entry} dict."""
    tmp = str(TRACKED_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for entry in coins.values():
                f.write(json.dumps(entry) + "\n")
        os.replace(tmp, TRACKED_FILE)
    except Exception as e:
        logger.error(f"Tracked save error: {e}")


# ── Seen mints (seen_mints.txt) ────────────────────────────────────────────────

def load_seen_mints() -> set:
    """Load all seen mints from persistent dedup file."""
    seen = set()
    if not SEEN_MINTS_FILE.exists():
        return seen
    try:
        with open(SEEN_MINTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                m = line.strip()
                if m:
                    seen.add(m)
    except Exception as e:
        logger.warning(f"Seen mints load error: {e}")
    return seen


def append_seen_mint(mint: str):
    """Append a mint to the persistent dedup file."""
    try:
        with open(SEEN_MINTS_FILE, "a", encoding="utf-8") as f:
            f.write(mint + "\n")
    except Exception as e:
        logger.error(f"Seen mint append error: {e}")


# ── Performance milestones ─────────────────────────────────────────────────────

def append_milestone(entry: dict):
    """Append a performance milestone event."""
    try:
        with open(MILESTONES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Milestone append error: {e}")


def load_milestones(max_age_hours: int = 0) -> list:
    """Load performance milestones, optionally filtered by age.

    Normalises 'multiplier' -> 'mult' so callers always get 'mult'.
    Returns entries sorted newest-first.
    """
    if not MILESTONES_FILE.exists():
        return []
    import time as _time
    cutoff = _time.time() - max_age_hours * 3600 if max_age_hours > 0 else 0
    entries = []
    try:
        with open(MILESTONES_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                        # normalise field name
                        if "multiplier" in e and "mult" not in e:
                            e["mult"] = e["multiplier"]
                        if cutoff and e.get("timestamp", 0) < cutoff:
                            continue
                        entries.append(e)
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Milestones load error: {e}")
    return entries
