import json
from datetime import datetime, timezone

coins = []
try:
    with open('data/tracked_coins.jsonl') as f:
        for line in f:
            try:
                c = json.loads(line.strip())
                coins.append(c)
            except:
                pass
except Exception as e:
    print(f"tracked_coins error: {e}")

milestones = []
try:
    with open('data/performance_milestones.jsonl') as f:
        for line in f:
            try:
                m = json.loads(line.strip())
                milestones.append(m)
            except:
                pass
except Exception as e:
    print(f"milestones error: {e}")

# Get best multiplier per coin name
best = {}
for c in coins:
    name = c.get('name', c.get('symbol', '?'))
    mult = float(c.get('current_multiplier', c.get('multiplier', 1)))
    entry = float(c.get('entry_mc', c.get('entry_market_cap', 0)))
    current = float(c.get('current_mc', c.get('market_cap', 0)))
    if name not in best or mult > best[name]['mult']:
        best[name] = {'mult': mult, 'entry': entry, 'current': current, 'name': name}

for m in milestones:
    name = m.get('name', m.get('symbol', '?'))
    mult = float(m.get('peak_multiplier', m.get('multiplier', 1)))
    entry = float(m.get('entry_mc', 0))
    peak = float(m.get('peak_mc', m.get('current_mc', 0)))
    if name not in best or mult > best[name]['mult']:
        best[name] = {'mult': mult, 'entry': entry, 'current': peak, 'name': name}

ranked = sorted(best.values(), key=lambda x: x['mult'], reverse=True)[:15]
now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
print(f"HYPE SCOUT LEADERBOARD - Top {len(ranked)} - {now}")
print("=" * 40)
for i, r in enumerate(ranked, 1):
    medal = ["1st", "2nd", "3rd"][i-1] if i <= 3 else f"#{i}"
    print(f"{medal} {r['name']} - {r['mult']:.1f}x (${r['entry']/1000:.1f}K -> ${r['current']/1000:.1f}K)")
