"""Test dev holding filter on recent Pump.fun tokens."""
import asyncio, aiohttp, sys
sys.path.insert(0, ".")
from config import PUMP_API_BASE
from utils.helius import get_dev_holding_pct

async def fetch_tokens():
    url = f"{PUMP_API_BASE}/coins?offset=0&limit=10&sort=created&order=desc"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            return await r.json()

tokens = asyncio.run(fetch_tokens())
print(f"Checking dev holdings on {len(tokens)} fresh tokens...\n")

for t in tokens[:8]:
    mint    = t.get("mint", "")
    name    = t.get("name", "?")[:28]
    creator = t.get("creator", "")
    mc      = t.get("usd_market_cap", 0)

    if not creator:
        print(f"  {name} — no creator field")
        continue

    dev_pct = get_dev_holding_pct(mint, creator)
    if dev_pct is None:
        flag = "❓ no data"
    elif dev_pct > 15:
        flag = f"🚩 FILTERED — dev holds {dev_pct}%"
    elif dev_pct > 0:
        flag = f"✅ OK — dev holds {dev_pct}%"
    else:
        flag = "✅ clean — dev holds 0%"

    print(f"  {name[:28]} (${mc:,.0f}) → {flag}")
