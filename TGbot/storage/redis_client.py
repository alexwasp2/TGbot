import requests
from config import UPSTASH_URL, UPSTASH_TOKEN


def redis_get(key):
    if not UPSTASH_URL:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=10,
        )
        return r.json().get("result")
    except:
        return None


def redis_set(key, value):
    if not UPSTASH_URL:
        return
    try:
        requests.post(
            f"{UPSTASH_URL}/pipeline",
            headers={
                "Authorization": f"Bearer {UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            json=[["SET", key, value]],
            timeout=10,
        )
    except:
        pass
