import os

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
DEFAULT_WALLET = os.environ.get("WALLET", "")

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

MIN_SIZE_USD = 100000
MIN_CHANGE_USD = 100000
CHECK_INTERVAL = 30
VOLUME_SAVE_INTERVAL = 3600
VOLUME_FILE = "volume_history.json"
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "price_range_pct": 2.0,
    "cooldown_min": 5,
    "min_multiplier": 3,
    "min_symbol_volume_m": 10,
    "tiers": [
        {"vol_from": 10,   "vol_to": 50,    "min_wall": 200},
        {"vol_from": 50,   "vol_to": 80,    "min_wall": 300},
        {"vol_from": 100,  "vol_to": 300,   "min_wall": 500},
        {"vol_from": 500,  "vol_to": 1000,  "min_wall": 1000},
        {"vol_from": 5000, "vol_to": 999999, "min_wall": 3000},
    ]
}
