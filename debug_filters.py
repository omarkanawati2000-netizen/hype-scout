from utils.helius import get_holder_concentration
from utils.queue_utils import load_tracked

coins = load_tracked(max_age_hours=24)
print("Testing concentration filter on 5 coins...\n")
for mint, c in list(coins.items())[:5]:
    name = c.get("name", "?")[:30]
    conc = get_holder_concentration(mint)
    if conc:
        flag = "🚩 BUNDLE" if conc["top3_pct"] > 60 else ("🚩 WHALE" if conc["top1_pct"] > 50 else "✅ OK")
        print(f"{flag} {name}")
        print(f"   top1={conc['top1_pct']}%  top3={conc['top3_pct']}%  supply={conc['total_supply']:,.0f}")
    else:
        print(f"❓ {name} — no data")
    print()
