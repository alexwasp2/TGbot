import time

import state
from api.hyperliquid import get_hl_volume_data
from utils.formatters import fmt_usd, send_message


def detect_spikes(prev: dict, curr: dict, settings: dict) -> list:
    min_vol = settings["min_volume_m"] * 1_000_000
    threshold = settings["threshold_pct"]
    results = []
    for coin, vol_curr in curr.items():
        if vol_curr <= min_vol:
            continue
        vol_prev = prev.get(coin, 0)
        if vol_prev == 0:
            continue
        pct = (vol_curr - vol_prev) / vol_prev * 100
        if pct >= threshold:
            results.append({"coin": coin, "vol_prev": vol_prev, "vol_curr": vol_curr, "pct": pct})
    return results


def _send_spike_alert(alert: dict):
    coin = alert["coin"]
    pct = alert["pct"]
    msg = (
        f"📈 <b>Volume Spike: {coin} +{pct:.0f}%</b>\n"
        f"24h Vol: {fmt_usd(alert['vol_prev'])} → {fmt_usd(alert['vol_curr'])}"
    )
    send_message(msg)
    print(f"[volume_spikes] spike: {coin} +{pct:.0f}%")


def volume_spike_thread():
    while True:
        interval = state.spike_settings.get("interval_sec", 300)
        try:
            if not state.spike_settings.get("enabled", True):
                time.sleep(interval)
                continue

            data = get_hl_volume_data()
            snapshot = {"timestamp": time.time(), "volumes": data}

            with state.spike_lock:
                state.spike_snapshots.append(snapshot)
                if len(state.spike_snapshots) < 2:
                    time.sleep(interval)
                    continue
                prev = state.spike_snapshots[-2]["volumes"]
                curr = state.spike_snapshots[-1]["volumes"]

            now = time.time()
            cooldown_sec = state.spike_settings.get("cooldown_min", 30) * 60

            for alert in detect_spikes(prev, curr, state.spike_settings):
                coin = alert["coin"]
                if now - state.spike_cooldowns.get(coin, 0) < cooldown_sec:
                    continue
                _send_spike_alert(alert)
                state.spike_cooldowns[coin] = now

        except Exception as e:
            print(f"[volume_spikes] ошибка: {e}")

        time.sleep(interval)
