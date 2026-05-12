import requests

import state


def api_post(payload):
    r = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
    if r.status_code == 200:
        return r.json()
    raise Exception(f"API вернул {r.status_code}")


def get_positions(wallet):
    return api_post({"type": "clearinghouseState", "user": wallet}).get("assetPositions", [])


def get_orders(wallet):
    return api_post({"type": "openOrders", "user": wallet})


def get_last_position_size(coin, wallet):
    try:
        data = api_post({"type": "userFills", "user": wallet})
        fills = [f for f in data if f.get("coin") == coin]
        if not fills:
            return None
        return sum(float(f.get("px", 0)) * float(f.get("sz", 0)) for f in fills[:20])
    except:
        return None


def get_hl_volume_data():
    data = api_post({"type": "metaAndAssetCtxs"})
    universe = data[0].get("universe", [])
    ctxs = data[1]
    result = {}
    for i, asset in enumerate(universe):
        if i >= len(ctxs):
            break
        result[asset.get("name", "")] = float(ctxs[i].get("dayNtlVlm", 0))
    return result


def calc_changes(hours_ago):
    keys = sorted(state.volume_history.keys())
    if len(keys) < hours_ago + 1:
        return None
    current = state.volume_history[keys[-1]]
    prev = state.volume_history[keys[-(hours_ago + 1)]]
    result = []
    for coin, vol in current.items():
        if coin in prev and prev[coin] > 0:
            pct = ((vol - prev[coin]) / prev[coin]) * 100
            result.append({"coin": coin, "volume": vol, "pct": pct})
    result.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return result
