import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DEFAULT_SETTINGS, DEFAULT_SPOT_SETTINGS
from storage.redis_client import redis_set

redis_set("settings", json.dumps(DEFAULT_SETTINGS))
redis_set("spot_settings", json.dumps(DEFAULT_SPOT_SETTINGS))
print("Redis: settings и spot_settings сброшены до дефолтов")
