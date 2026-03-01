import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
import os

api_key    = os.getenv("TWITTER_API_KEY")
api_secret = os.getenv("TWITTER_API_SECRET")
at         = os.getenv("TWITTER_ACCESS_TOKEN")
at_secret  = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
bearer     = os.getenv("TWITTER_BEARER_TOKEN")

print("API Key:", api_key[:8] + "..." if api_key else "MISSING")
print("API Secret:", api_secret[:8] + "..." if api_secret else "MISSING")
print("Access Token:", at[:20] + "..." if at else "MISSING")
print("Access Secret:", at_secret[:8] + "..." if at_secret else "MISSING")

import tweepy

# Try v1.1 API first (simpler auth test)
try:
    auth = tweepy.OAuth1UserHandler(api_key, api_secret, at, at_secret)
    api = tweepy.API(auth)
    me = api.verify_credentials()
    print(f"\nv1.1 Auth OK — @{me.screen_name}")
except Exception as e:
    print(f"\nv1.1 Auth failed: {e}")

# Try v2 client
try:
    client = tweepy.Client(
        consumer_key=api_key, consumer_secret=api_secret,
        access_token=at, access_token_secret=at_secret
    )
    me2 = client.get_me()
    print(f"v2 Auth OK — {me2.data}")
except Exception as e:
    print(f"v2 Auth failed: {e}")
