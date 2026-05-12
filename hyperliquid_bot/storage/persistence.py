import json
import os
from datetime import datetime, timezone

from config import DEFAULT_SETTINGS, SETTINGS_FILE, VOLUME_FILE
import state
from storage.redis_client import redis_get, redis_set


def load_settings():
    data = redis_get("settings")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            state.settings = dict(DEFAULT_SETTINGS)
            state.settings.update(loaded)
            if "tiers" not in loaded or not isinstance(loaded.get("tiers"), list):
                state.settings["tiers"] = DEFAULT_SETTINGS["tiers"]
            print("Redis: настройки загружены")
            return
        except Exception as e:
            print(f"Redis ошибка: {e}")
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
                state.settings = dict(DEFAULT_SETTINGS)
                state.settings.update(loaded)
                print("Файл: настройки загружены")
        except Exception as e:
            print(f"Ошибка файла: {e}")
            state.settings = dict(DEFAULT_SETTINGS)
    else:
        state.settings = dict(DEFAULT_SETTINGS)
        print("Используются дефолт настройки")


def save_settings():
    with open(SETTINGS_FILE, "w") as f:
        json.dump(state.settings, f)
    redis_set("settings", json.dumps(state.settings))


def load_custom_data():
    data = redis_get("custom_walls")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                state.custom_walls = loaded
        except:
            pass
    data = redis_get("watched_wallets")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                state.watched_wallets = loaded
        except:
            pass


def save_custom_data():
    redis_set("custom_walls", json.dumps(state.custom_walls))
    redis_set("watched_wallets", json.dumps(state.watched_wallets))


def load_volume_history():
    data = redis_get("volume_history")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                state.volume_history = {k: v for k, v in loaded.items() if isinstance(v, dict)}
                if state.volume_history:
                    print(f"Redis: volume_history загружен, {len(state.volume_history)} снимков")
                    return
        except Exception as e:
            print(f"Redis volume ошибка: {e}")
    if os.path.exists(VOLUME_FILE):
        try:
            with open(VOLUME_FILE, "r") as f:
                state.volume_history = json.load(f)
        except:
            pass


def save_volume_snapshot():
    from api.hyperliquid import get_hl_volume_data
    try:
        current = get_hl_volume_data()
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        state.volume_history[hour_key] = current
        keys = sorted(state.volume_history.keys())
        if len(keys) > 48:
            for old_key in keys[:-48]:
                del state.volume_history[old_key]
        redis_set("volume_history", json.dumps(state.volume_history))
        print(f"Объём сохранён: {hour_key}")
    except Exception as e:
        print(f"Ошибка сохранения объёма: {e}")
