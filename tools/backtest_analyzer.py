#!/usr/bin/env python3
"""
tools/backtest_analyzer.py — Read-only backtest analysis.

Joins scan_log.jsonl (candidates + filter data) with performance_milestones.jsonl
(outcomes) to surface which filter values correlate with runners vs duds.

READ-ONLY: this script never modifies config, scanner, or state files.
It posts a report to Discord #bot-logs and prints to stdout.

Usage:
    python tools/backtest_analyzer.py [--min-hours 4]
"""
import sys
import json
import math
import argparse
import io
from pathlib import Path
from datetime import datetime
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DATA_DIR, DISCORD_BOT_TOKEN
import requests

# ── Config ─────────────────────────────────────────────────────────────────────
SCAN_LOG_FILE    = DATA_DIR / "scan_log.jsonl"
MILESTONES_FILE  = DATA_DIR / "performance_milestones.jsonl"
DISCORD_CHANNEL  = "1475223354066600036"   # #bot-logs

# Runner thresholds we care about
RUNNER_TIERS = [2.0, 5.0, 10.0]

# Features to analyze — (field_name, higher_is_worse, display_name)
FEATURES = [
    ("dev_pct",                True,  "Dev wallet %"),
    ("bs_ratio",               True,  "Buy/sell ratio"),
    ("age_minutes",            False, "Age at scan (min)"),
    ("holder_count",           False, "Holder count"),
    ("bonding_curve_progress", True,  "Bonding curve %"),
    ("buys_h1",                False, "Buys (1h)"),
    ("vol_h1",                 False, "Volume 1h ($)"),
]

# How many candidates we need before analysis is meaningful
MIN_CANDIDATES = 50


# ── Data loading ────────────────────────────────────────────────────────────────

def load_scan_log() -> list[dict]:
    if not SCAN_LOG_FILE.exists():
        return []
    rows = []
    with open(SCAN_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def load_peak_mults() -> dict[str, float]:
    """Return {mint: peak_multiplier} from performance_milestones.jsonl."""
    if not MILESTONES_FILE.exists():
        return {}
    peaks: dict[str, float] = {}
    with open(MILESTONES_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                mint = e.get("mint", "")
                mult = e.get("multiplier") or e.get("mult") or 0
                if mint and mult > peaks.get(mint, 0):
                    peaks[mint] = mult
            except Exception:
                pass
    return peaks


# ── Stats helpers ───────────────────────────────────────────────────────────────

def median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]


def mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def fmt_num(v: float) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"{v:.1f}"


# ── Threshold scanner ───────────────────────────────────────────────────────────

def scan_threshold(
    candidates: list[dict],
    field: str,
    higher_is_worse: bool,
    runner_field: str = "peak_2x",
) -> dict | None:
    """
    For a given field, scan candidate thresholds and find the one that:
    - Removes the most non-runners (duds)
    - Removes the fewest runners
    - Net win rate delta is positive

    Returns the best threshold dict or None if field has no signal.
    """
    vals = [(c.get(field), c.get(runner_field, False)) for c in candidates]
    vals = [(v, r) for v, r in vals if v is not None]
    if len(vals) < 20:
        return None

    all_vals = sorted(set(v for v, _ in vals))
    # Use up to 40 candidate breakpoints (percentiles)
    if len(all_vals) > 40:
        breakpoints = [percentile([v for v, _ in vals], p) for p in range(5, 96, 3)]
    else:
        breakpoints = all_vals

    total_runners = sum(1 for _, r in vals if r)
    total_duds    = len(vals) - total_runners
    if total_runners == 0 or total_duds == 0:
        return None

    base_win_rate = total_runners / len(vals)

    best = None
    best_score = 0.0

    for bp in breakpoints:
        if higher_is_worse:
            # filter = remove coins where field > bp
            kept = [(v, r) for v, r in vals if v <= bp]
            filtered_runners = sum(1 for v, r in vals if v > bp and r)
            filtered_duds    = sum(1 for v, r in vals if v > bp and not r)
        else:
            # filter = remove coins where field < bp
            kept = [(v, r) for v, r in vals if v >= bp]
            filtered_runners = sum(1 for v, r in vals if v < bp and r)
            filtered_duds    = sum(1 for v, r in vals if v < bp and not r)

        if not kept:
            continue

        kept_runners = sum(1 for _, r in kept if r)
        new_win_rate = kept_runners / len(kept) if kept else 0
        win_rate_delta = new_win_rate - base_win_rate

        pct_runners_lost = filtered_runners / total_runners if total_runners > 0 else 0
        pct_duds_removed = filtered_duds / total_duds if total_duds > 0 else 0

        # Score: reward dud removal, penalise runner loss heavily
        score = pct_duds_removed - (pct_runners_lost * 3)

        if score > best_score and pct_runners_lost <= 0.15:
            best_score = score
            best = {
                "threshold":       round(bp, 2),
                "direction":       "max" if higher_is_worse else "min",
                "duds_removed_pct": round(pct_duds_removed * 100, 1),
                "runners_lost_pct": round(pct_runners_lost * 100, 1),
                "win_rate_before":  round(base_win_rate * 100, 1),
                "win_rate_after":   round(new_win_rate * 100, 1),
                "win_rate_delta":   round(win_rate_delta * 100, 2),
                "alerts_removed":   filtered_duds + filtered_runners,
                "total":            len(vals),
                "score":            round(best_score, 4),
            }

    return best


# ── Current filter auditor ─────────────────────────────────────────────────────

def audit_current_filters(candidates: list[dict]) -> list[str]:
    """Report on coins that were actually filtered and whether any were runners."""
    rejected = [c for c in candidates if not c.get("filter_passed", True)]
    if not rejected:
        return ["No rejected candidates in dataset yet."]

    lines = [f"**Current filter audit** ({len(rejected)} rejected)"]

    # Group by reject reason
    by_reason: dict[str, list] = defaultdict(list)
    for c in rejected:
        reason = c.get("filter_reject_reason") or "unknown"
        key    = reason.split(":")[0]  # e.g. "dev_pct" from "dev_pct:12.3"
        by_reason[key].append(c)

    for reason, coins in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        runners = [c for c in coins if c.get("peak_2x", False)]
        runner_5x = [c for c in coins if c.get("peak_5x", False)]
        fp_rate = len(runners) / len(coins) * 100 if coins else 0
        lines.append(
            f"• `{reason}`: {len(coins)} rejected | {len(runners)} were 2x+ runners "
            f"({fp_rate:.0f}% false-positive) | {len(runner_5x)} were 5x+"
        )

    return lines


# ── Report builder ──────────────────────────────────────────────────────────────

def build_report(candidates: list[dict], peaks: dict[str, float]) -> str:
    # Attach outcome labels to each candidate
    for c in candidates:
        mint = c.get("mint", "")
        pk   = peaks.get(mint, 0.0)
        c["peak_mult"]  = pk
        c["peak_2x"]    = pk >= 2.0
        c["peak_5x"]    = pk >= 5.0
        c["peak_10x"]   = pk >= 10.0

    passed    = [c for c in candidates if c.get("filter_passed", True)]
    rejected  = [c for c in candidates if not c.get("filter_passed", True)]
    runners_2 = [c for c in passed if c["peak_2x"]]
    runners_5 = [c for c in passed if c["peak_5x"]]
    runners_10= [c for c in passed if c["peak_10x"]]
    duds      = [c for c in passed if not c["peak_2x"]]

    total_p   = len(passed)
    wr_2  = len(runners_2)  / total_p * 100 if total_p else 0
    wr_5  = len(runners_5)  / total_p * 100 if total_p else 0
    wr_10 = len(runners_10) / total_p * 100 if total_p else 0

    now_str = datetime.now().strftime("%b %-d %I:%M %p MST") if sys.platform != "win32" else \
              f"{datetime.now().strftime('%b')} {datetime.now().day} {datetime.now().hour % 12 or 12}:{datetime.now().strftime('%M')} {'AM' if datetime.now().hour < 12 else 'PM'} MST"

    lines = [
        f"📊 **Backtest Report** — {now_str}",
        f"Dataset: **{len(candidates)}** total scanned | **{total_p}** passed filters | **{len(rejected)}** rejected",
        f"Win rates (passed): 2x+ **{wr_2:.1f}%** | 5x+ **{wr_5:.1f}%** | 10x+ **{wr_10:.1f}%**",
        "",
    ]

    if total_p < MIN_CANDIDATES:
        lines.append(f"⏳ Not enough data yet — need {MIN_CANDIDATES}+ passed candidates (have {total_p}). Check back later.")
        return "\n".join(lines)

    # ── Feature comparison: runners vs duds ────────────────────────────────
    lines.append("**Feature comparison — runners (2x+) vs non-runners:**")
    for field, higher_is_worse, label in FEATURES:
        r_vals = [c[field] for c in runners_2 if c.get(field) is not None]
        d_vals = [c[field] for c in duds      if c.get(field) is not None]
        if not r_vals or not d_vals:
            continue
        r_med = median(r_vals)
        d_med = median(d_vals)
        arrow = "↑" if r_med > d_med else "↓"
        lines.append(
            f"• `{field}` ({label}): runners median **{fmt_num(r_med)}** {arrow} | "
            f"duds median **{fmt_num(d_med)}** (n={len(r_vals)} runners, {len(d_vals)} duds)"
        )
    lines.append("")

    # ── Threshold suggestions ────────────────────────────────────────────────
    suggestions = []
    for field, higher_is_worse, label in FEATURES:
        result = scan_threshold(passed, field, higher_is_worse, "peak_2x")
        if result and result["win_rate_delta"] >= 0.5:
            suggestions.append((field, label, result))

    if suggestions:
        lines.append("**🔧 Filter suggestions** (read-only — no changes made):")
        for field, label, r in sorted(suggestions, key=lambda x: -x[2]["win_rate_delta"]):
            direction_str = f"< {r['threshold']}" if r["direction"] == "min" else f"> {r['threshold']}"
            lines.append(
                f"• Filter `{field} {direction_str}` → "
                f"removes **{r['duds_removed_pct']}%** of duds | "
                f"loses **{r['runners_lost_pct']}%** of runners | "
                f"win rate {r['win_rate_before']}% → **{r['win_rate_after']}%** "
                f"(+{r['win_rate_delta']}pp)"
            )
    else:
        lines.append("**🔧 Filter suggestions:** No high-confidence thresholds found yet — more data needed.")
    lines.append("")

    # ── Current filter audit ─────────────────────────────────────────────────
    # Attach peaks to rejected too
    for c in rejected:
        pk = peaks.get(c.get("mint", ""), 0.0)
        c["peak_2x"] = pk >= 2.0
        c["peak_5x"] = pk >= 5.0

    audit = audit_current_filters(candidates)
    lines.extend(audit)

    return "\n".join(lines)


# ── Discord poster ──────────────────────────────────────────────────────────────

def post_to_discord(text: str):
    if not DISCORD_BOT_TOKEN:
        print("[warn] No Discord bot token — skipping post")
        return
    # Split if over 1900 chars
    chunks = []
    lines  = text.split("\n")
    chunk  = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 1900:
            chunks.append(chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk:
        chunks.append(chunk)

    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
    for chunk in chunks:
        try:
            resp = requests.post(url, json={"content": chunk.strip()}, headers=headers, timeout=10)
            if resp.status_code not in (200, 201):
                print(f"[warn] Discord post failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[error] Discord post error: {e}")


# ── Entry point ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-hours", type=float, default=0,
                        help="Only include scan_log entries from the last N hours (0 = all)")
    parser.add_argument("--no-discord", action="store_true",
                        help="Print report but do not post to Discord")
    args = parser.parse_args()

    print("Loading scan log...")
    candidates = load_scan_log()
    print(f"Loaded {len(candidates)} scan log entries")

    if args.min_hours > 0:
        cutoff = datetime.now().timestamp() - args.min_hours * 3600
        candidates = [c for c in candidates if c.get("timestamp", 0) >= cutoff]
        print(f"Filtered to {len(candidates)} entries from last {args.min_hours}h")

    print("Loading performance milestones...")
    peaks = load_peak_mults()
    print(f"Loaded peak multipliers for {len(peaks)} mints")

    if not candidates:
        msg = "📊 **Backtest Report**: No scan_log.jsonl data yet — scanner needs to run for a few hours first."
        print(msg)
        if not args.no_discord:
            post_to_discord(msg)
        return

    report = build_report(candidates, peaks)
    print("\n" + "="*60)
    print(report)
    print("="*60 + "\n")

    if not args.no_discord:
        post_to_discord(report)
        print("Report posted to Discord #bot-logs")


if __name__ == "__main__":
    main()
