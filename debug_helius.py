import os, requests, json
from dotenv import load_dotenv
load_dotenv()

url  = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY')}"
mint = "B3wdZAsJpTNMbJvFDecNnUHDXeNUiHGhEwJTH3VMNSY4"

# Test batch call
batch = [
    {"jsonrpc":"2.0","id":1,"method":"getTokenLargestAccounts","params":[mint]},
    {"jsonrpc":"2.0","id":2,"method":"getTokenSupply","params":[mint]},
]
r = requests.post(url, json=batch, timeout=8)
print("Status:", r.status_code)
data = r.json()
print("Response type:", type(data).__name__)
print(json.dumps(data, indent=2)[:1000])
