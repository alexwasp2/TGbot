import json
import os
from datetime import datetime, timezone

from config import DEFAULT_SETTINGS, DEFAULT_SPOT_SETTINGS, TIER_RANGES, SETTINGS_FILE, SPOT_SETTINGS_FILE, VOLUME_FILE, CUSTOM_DATA_FILE, SPIKE_SETTINGS_FILE, SPIKE_THRESHOLD_PCT, SPIKE_INTERVAL_SEC, SPIKE_MIN_VOLUME_M, SPIKE_COOLDOWN_MIN
import state
from storage.redis_client import redis_get, redis_set


def _enforce_tier_ranges(settings):
    for i, ranges in enumerate(TIER_RANGES):
        if i < len(settings.get("tiers", [])):
            settings["tiers"][i]["vol_from"] = ranges["vol_from"]
            settings["tiers"][i]["vol_to"] = ranges["vol_to"]


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
            _enforce_tier_ranges(state.settings)
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


def load_spot_settings():
    data = redis_get("spot_settings")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            state.spot_settings = dict(DEFAULT_SPOT_SETTINGS)
            state.spot_settings.update(loaded)
            if "tiers" not in loaded or not isinstance(loaded.get("tiers"), list):
                state.spot_settings["tiers"] = DEFAULT_SPOT_SETTINGS["tiers"]
            _enforce_tier_ranges(state.spot_settings)
            print("Redis: спот-настройки загружены")
            return
        except Exception as e:
            print(f"Redis spot ошибка: {e}")
    if os.path.exists(SPOT_SETTINGS_FILE):
        try:
            with open(SPOT_SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
            state.spot_settings = dict(DEFAULT_SPOT_SETTINGS)
            state.spot_settings.update(loaded)
            print("Файл: спот-настройки загружены")
            return
        except Exception as e:
            print(f"Ошибка файла spot: {e}")
    state.spot_settings = dict(DEFAULT_SPOT_SETTINGS)
    print("Используются дефолт спот-настройки")


def save_spot_settings():
    redis_set("spot_settings", json.dumps(state.spot_settings))
    try:
        with open(SPOT_SETTINGS_FILE, "w") as f:
            json.dump(state.spot_settings, f)
    except Exception as e:
        print(f"Ошибка сохранения спот-настроек: {e}")


def load_custom_data():
    redis_ok = False

    data = redis_get("custom_walls")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                state.custom_walls = {k: float(v) for k, v in loaded.items()}
                redis_ok = True
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
                redis_ok = True
        except:
            pass

    data = redis_get("spot_custom_walls")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                state.spot_custom_walls = {k: float(v) for k, v in loaded.items()}
        except:
            pass

    if not redis_ok and os.path.exists(CUSTOM_DATA_FILE):
        try:
            with open(CUSTOM_DATA_FILE, "r") as f:
                saved = json.load(f)
            if isinstance(saved.get("custom_walls"), dict):
                state.custom_walls = {k: float(v) for k, v in saved["custom_walls"].items()}
            if isinstance(saved.get("watched_wallets"), dict):
                state.watched_wallets = saved["watched_wallets"]
            if isinstance(saved.get("spot_custom_walls"), dict):
                state.spot_custom_walls = {k: float(v) for k, v in saved["spot_custom_walls"].items()}
            print("Файл: custom_data загружен")
        except Exception as e:
            print(f"Ошибка загрузки custom_data: {e}")


def save_custom_data():
    redis_set("custom_walls", json.dumps(state.custom_walls))
    redis_set("watched_wallets", json.dumps(state.watched_wallets))
    redis_set("spot_custom_walls", json.dumps(state.spot_custom_walls))
    try:
        with open(CUSTOM_DATA_FILE, "w") as f:
            json.dump({
                "custom_walls": state.custom_walls,
                "watched_wallets": state.watched_wallets,
                "spot_custom_walls": state.spot_custom_walls,
            }, f)
    except Exception as e:
        print(f"Ошибка сохранения custom_data: {e}")


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


def load_spike_settings():
    default = {
        "enabled": True,
        "threshold_pct": SPIKE_THRESHOLD_PCT,
        "interval_sec": SPIKE_INTERVAL_SEC,
        "min_volume_m": SPIKE_MIN_VOLUME_M,
        "cooldown_min": SPIKE_COOLDOWN_MIN,
    }
    data = redis_get("spike_settings")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            state.spike_settings = {**default, **loaded}
            print("Redis: spike_settings загружены")
            return
        except Exception as e:
            print(f"Redis spike ошибка: {e}")
    if os.path.exists(SPIKE_SETTINGS_FILE):
        try:
            with open(SPIKE_SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
            state.spike_settings = {**default, **loaded}
            print("Файл: spike_settings загружены")
            return
        except Exception as e:
            print(f"Ошибка файла spike: {e}")
    state.spike_settings = default
    print("Используются дефолт spike_settings")


def save_spike_settings():
    redis_set("spike_settings", json.dumps(state.spike_settings))
    try:
        with open(SPIKE_SETTINGS_FILE, "w") as f:
            json.dump(state.spike_settings, f)
    except Exception as e:
        print(f"Ошибка сохранения spike_settings: {e}")
