#!/usr/bin/env python3
"""
tracker/runner_digest.py — Milestone digest (cron: every 10 min)

Reads performance_milestones.jsonl + tracked_coins.jsonl.
Finds coins not yet digested that hit >= 2x.
Shows best milestone per coin, sorted highest first.

Output:
    DIGEST|<message>  → post to #early-trending-runners + Telegram
    NO_NEW            → nothing new to digest
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

from config import DIGEST_STATE, TRACK_MAX_AGE_HOURS, PUMP_THRESHOLDS
from utils.formatter import tier_emoji, fmt_usd
from utils.queue_utils import load_tracked, load_milestones

DIGEST_INTERVAL = 600  # 10 minutes

# Tier buckets — a coin can appear in the digest once per tier it crosses
DIGEST_TIERS = [2.0, 5.0, 10.0, 25.0, 100.0]

def tier_bucket(mult: float) -> float:
    """Return the highest tier threshold this multiplier qualifies for."""
    for t in reversed(DIGEST_TIERS):
        if mult >= t:
            return t
    return 2.0


def load_state() -> dict:
    if DIGEST_STATE.exists():
        try:
            with open(DIGEST_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_digest": 0, "seen_keys": []}


def save_state(state: dict):
    with open(DIGEST_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def build_digest_msg(hits: list, now_str: str) -> str:
    count = len(hits)
    noun  = "coin" if count == 1 else "coins"
    lines = [
        f"📬 **PumpScanner Milestone Digest** · {now_str}",
        f"_New milestones in the last 10 min — {count} {noun}_",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for h in hits:
        emoji = tier_emoji(h["mult"])
        mint  = h["mint"]
        dex   = f"https://dexscreener.com/solana/{mint}"
        pump  = f"https://pump.fun/{mint}"
        lines.append(
            f"{emoji} **{h['name']}** hit **{h['mult']:.1f}x** "
            f"({fmt_usd(h['entry_mc'])} → {fmt_usd(h['peak_mc'])})\n"
            f"    [Chart](<{dex}>) · [Pump](<{pump}>)"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def main():
    force = "--force" in sys.argv
    state = load_state()
    now   = time.time()

    elapsed = now - state.get("last_digest", 0)
    if not force and elapsed < DIGEST_INTERVAL:
        print("NO_NEW")
        return

    seen_keys = set(state.get("seen_keys", []))
    coins     = load_tracked(max_age_hours=TRACK_MAX_AGE_HOURS)
    milestones = load_milestones()

    # Build best-multiplier map from milestones
    # Key: mint → best hit this cycle that hasn't been digested at its tier yet
    best_mult: dict = {}
    for m in milestones:
        mint = m.get("mint", "")
        mult = m.get("multiplier", 0)
        if mult < 2.0:
            continue
        tier = tier_bucket(mult)
        tier_key = f"{mint}:{tier}"
        if tier_key in seen_keys:
            continue  # already announced this tier for this coin
        existing = best_mult.get(mint)
        if not existing or mult > existing["mult"]:
            tg_mid = coins.get(mint, {}).get("telegram_msg_id") or m.get("telegram_msg_id")
            best_mult[mint] = {
                "mint":            mint,
                "mult":            mult,
                "tier":            tier,
                "entry_mc":        m.get("entry_mc", 0),
                "peak_mc":         m.get("current_mc", 0),
                "name":            m.get("name", coins.get(mint, {}).get("name", "?")),
                "telegram_msg_id": tg_mid,
            }

    # Also check tracked coins live multiplier (in case no milestone recorded yet)
    for mint, c in coins.items():
        entry_mc   = c.get("entry_mc", 0)
        current_mc = c.get("current_mc", 0)
        if entry_mc <= 0 or current_mc <= 0:
            continue
        mult = round(current_mc / entry_mc, 1)
        if mult < 2.0:
            continue
        tier = tier_bucket(mult)
        tier_key = f"{mint}:{tier}"
        if tier_key in seen_keys:
            continue
        existing = best_mult.get(mint)
        if not existing or mult > existing["mult"]:
            best_mult[mint] = {
                "mint":            mint,
                "mult":            mult,
                "tier":            tier,
                "entry_mc":        entry_mc,
                "peak_mc":         current_mc,
                "name":            c.get("name", "?"),
                "telegram_msg_id": c.get("telegram_msg_id"),
            }

    if not best_mult:
        state["last_digest"] = now
        save_state(state)
        print("NO_NEW")
        return

    hits = sorted(best_mult.values(), key=lambda x: -x["mult"])
    now_str = datetime.now().strftime("%H:%M")
    msg = build_digest_msg(hits, now_str)

    # Update state — store tier-based keys so coins can reappear at higher tiers
    new_tier_keys = {f"{h['mint']}:{h['tier']}" for h in hits}
    state["last_digest"] = now
    state["seen_keys"]   = list(seen_keys | new_tier_keys)
    save_state(state)

    # Post to Discord + Telegram
    try:
        from notifier.discord_poster import DiscordPoster
        DiscordPoster().post_runner(msg)
    except Exception:
        pass
    try:
        from notifier.telegram_bot import TelegramNotifier
        # Convert to Telegram HTML (rebuild with platform=telegram)
        tg_lines = [
            "📬 <b>PumpScanner Milestone Digest</b> · " + now_str,
            f"<i>New milestones in the last 10 min — {len(hits)} coin{'s' if len(hits) != 1 else ''}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
        ]
        TG_CHANNEL_NUMERIC = "3816610028"
        for h in hits:
            from utils.formatter import tier_emoji, fmt_usd
            emoji  = tier_emoji(h["mult"])
            mint   = h["mint"]
            tg_mid = h.get("telegram_msg_id")
            if tg_mid:
                name_link = f'<a href="https://t.me/c/{TG_CHANNEL_NUMERIC}/{tg_mid}">{h["name"]}</a>'
            else:
                name_link = f'<a href="https://pump.fun/{mint}">{h["name"]}</a>'
            tg_lines.append(
                f'{emoji} {name_link} hit <b>{h["mult"]:.1f}x</b> '
                f'({fmt_usd(h["entry_mc"])} → {fmt_usd(h["peak_mc"])})\n'
                f'    <a href="https://dexscreener.com/solana/{mint}">Chart</a> · '
                f'<a href="https://pump.fun/{mint}">Pump</a>'
            )
        tg_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        TelegramNotifier().broadcast_text("\n".join(tg_lines))
    except Exception:
        pass

    print(f"DIGEST|{msg}")


if __name__ == "__main__":
    main()
