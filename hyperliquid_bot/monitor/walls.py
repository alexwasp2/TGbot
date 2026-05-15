import time

import state
from utils.formatters import fmt_usd, fmt_val, get_min_wall_usd, send_message

wall_candidates = {}        # {(symbol, round(price,6), side): tick_count}
spot_wall_candidates = {}   # same structure for spot


def check_orderbook_walls(symbol, bids, asks, market="futures"):
    try:
        s = state.spot_settings if market == "spot" else state.settings
        if market == "spot":
            print(f"SPOT CHECK: {symbol}, vol={state.spot_symbol_volumes.get(symbol, 0):.0f}, bids={len(bids)}")
        if "cooldown_min" not in s:
            return

        now = time.time()
        cooldowns = state.spot_wall_cooldowns if market == "spot" else state.wall_cooldowns
        cooldown = s["cooldown_min"] * 60
        if symbol in cooldowns and now - cooldowns[symbol] < cooldown:
            return
        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2
        price_range = s["price_range_pct"] / 100
        price_low = mid_price * (1 - price_range)
        price_high = mid_price * (1 + price_range)

        all_orders = []
        for price, qty in bids:
            p, q = float(price), float(qty)
            if price_low <= p <= price_high and q > 0:
                all_orders.append({"price": p, "qty": q, "value": p * q, "side": "BID",
                                   "dist_pct": (mid_price - p) / mid_price * 100})
        for price, qty in asks:
            p, q = float(price), float(qty)
            if price_low <= p <= price_high and q > 0:
                all_orders.append({"price": p, "qty": q, "value": p * q, "side": "ASK",
                                   "dist_pct": (p - mid_price) / mid_price * 100})

        if len(all_orders) < 5:
            return

        avg_value = sum(o["value"] for o in all_orders) / len(all_orders)
        volumes = state.spot_symbol_volumes if market == "spot" else state.symbol_volumes
        vol_24h = volumes.get(symbol, 0)

        if vol_24h < s["min_symbol_volume_m"] * 1_000_000:
            return

        custom = state.spot_custom_walls if market == "spot" else state.custom_walls
        min_wall = custom.get(symbol, get_min_wall_usd(vol_24h, market))
        multiplier = s["min_multiplier"]

        candidates = spot_wall_candidates if market == "spot" else wall_candidates

        walls = [o for o in all_orders if o["value"] >= avg_value * multiplier and o["value"] >= min_wall]
        if not walls:
            for key in list(candidates):
                if key[0] == symbol:
                    candidates[key] -= 1
                    if candidates[key] <= 0:
                        del candidates[key]
            return

        walls.sort(key=lambda x: x["value"], reverse=True)
        top = walls[0]

        current_keys = {(symbol, round(o["price"], 6), o["side"]) for o in walls}
        for key in list(candidates):
            if key[0] == symbol and key not in current_keys:
                candidates[key] -= 1
                if candidates[key] <= 0:
                    del candidates[key]

        bid_walls = [o for o in walls if o["side"] == "BID"]
        ask_walls = [o for o in walls if o["side"] == "ASK"]

        if bid_walls and ask_walls:
            top_bid_val = max(o["value"] for o in bid_walls)
            top_ask_val = max(o["value"] for o in ask_walls)
            top_bid_dist = min(o["dist_pct"] for o in bid_walls)
            top_ask_dist = min(o["dist_pct"] for o in ask_walls)

            size_ratio = min(top_bid_val, top_ask_val) / max(top_bid_val, top_ask_val)
            avg_dist = (top_bid_dist + top_ask_dist) / 2
            dist_diff_ratio = abs(top_bid_dist - top_ask_dist) / avg_dist if avg_dist > 0 else 1

            if size_ratio > 0.80 and dist_diff_ratio < 0.30:
                return

        wall_key = (symbol, round(top["price"], 6), top["side"])
        candidates[wall_key] = candidates.get(wall_key, 0) + 1
        if candidates[wall_key] < 3:
            return

        dist_pct = top["dist_pct"]
        side_emoji = "🟢" if top["side"] == "BID" else "🔴"
        market_marker = "S" if market == "spot" else "F"
        lots = top["value"] / top["price"] if top["price"] > 0 else 0
        vol_str = (
            f"${vol_24h/1_000_000_000:.1f}B"
            if vol_24h >= 1_000_000_000
            else f"${vol_24h/1_000_000:.0f}M"
        )

        p = top["price"]
        if p >= 100:
            price_str = f"${round(p):,}"
        elif p >= 1:
            price_str = f"${p:.2f}"
        elif p >= 0.01:
            price_str = f"${p:.4f}"
        else:
            price_str = f"${p:.6f}"

        parts = [
            f"🧱 <b>Плотняха на</b> <code>{symbol}</code> {market_marker} {side_emoji}",
            "",
            f"💰 {fmt_usd(top['value'])} ({fmt_val(lots)} лотов)",
            f"🎯 Цена: {price_str}",
            f"📏 {dist_pct:.2f}% от текущей цены",
            f"📊 Объём 24ч: {vol_str}",
        ]
        if len(walls) > 1:
            parts += ["", f"🔥 Кластер: {len(walls)} плотняхи рядом!"]

        send_message("\n".join(parts))
        cooldowns[symbol] = now
        candidates[wall_key] = 0
        print(f"Плотняха [{market_marker}]: {symbol} {fmt_usd(top['value'])}")

    except Exception as e:
        print(f"Ошибка анализа {symbol}: {e}")
