from utils.queue_utils import load_tracked, load_milestones
from utils.dexscreener import get_live_mc_batch

milestones = load_milestones()
coins = load_tracked(max_age_hours=24)
peak_map = {}
mult_list = {}
for m in milestones:
    mint = m.get("mint", "")
    mult = m.get("multiplier", m.get("mult", 0))
    if not mint: continue
    if mult > peak_map.get(mint, 0): peak_map[mint] = mult
    mult_list.setdefault(mint, []).append(mult)

for mint, peak in list(peak_map.items()):
    if peak > 500:
        recs = sorted(mult_list.get(mint, []), reverse=True)
        peak_map[mint] = recs[1] if len(recs) >= 2 else 0

mints = list(coins.keys())
live_data = get_live_mc_batch(mints)

board = []
for mint, c in coins.items():
    entry_mc = c.get("entry_mc", 0)
    if not entry_mc: continue
    live = live_data.get(mint, {})
    cur_mc = live.get("mc", 0) if live.get("reliable", True) else 0
    live_mult = round(cur_mc / entry_mc, 1) if cur_mc > 0 else 0
    peak = max(peak_map.get(mint, 0), live_mult)
    if peak < 2: continue
    board.append({"name": c.get("name", "?"), "peak": peak, "mint": mint[:16]})

board.sort(key=lambda x: -x["peak"])
print("Top 10:")
for i, e in enumerate(board[:10]):
    print(f"  #{i+1} {e['name']} — {e['peak']}x")
