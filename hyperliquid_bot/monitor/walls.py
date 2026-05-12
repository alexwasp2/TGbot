import time

import state
from utils.formatters import fmt_usd, fmt_val, get_min_wall_usd, send_message


def check_orderbook_walls(symbol, bids, asks):
    try:
        if "cooldown_min" not in state.settings:
            return

        now = time.time()
        cooldown = state.settings["cooldown_min"] * 60
        if symbol in state.wall_cooldowns and now - state.wall_cooldowns[symbol] < cooldown:
            return
        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2
        price_range = state.settings["price_range_pct"] / 100
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
        vol_24h = state.symbol_volumes.get(symbol, 0)

        if vol_24h < state.settings["min_symbol_volume_m"] * 1_000_000:
            return

        min_wall = state.custom_walls.get(symbol, get_min_wall_usd(vol_24h))
        multiplier = state.settings["min_multiplier"]

        walls = [o for o in all_orders if o["value"] >= avg_value * multiplier and o["value"] >= min_wall]
        if not walls:
            return

        walls.sort(key=lambda x: x["value"], reverse=True)
        top = walls[0]

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

        dist_pct = top["dist_pct"]
        side_emoji = "🟢" if top["side"] == "BID" else "🔴"
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
            f"🧱 <b>Плотняха на</b> <code>{symbol}</code> {side_emoji}",
            "",
            f"💰 {fmt_usd(top['value'])} ({fmt_val(lots)} лотов)",
            f"🎯 Цена: {price_str}",
            f"📏 {dist_pct:.2f}% от текущей цены",
            f"📊 Объём 24ч: {vol_str}",
        ]
        if len(walls) > 1:
            parts += ["", f"🔥 Кластер: {len(walls)} плотняхи рядом!"]

        send_message("\n".join(parts))
        state.wall_cooldowns[symbol] = now
        print(f"Плотняха: {symbol} {fmt_usd(top['value'])}")

    except Exception as e:
        print(f"Ошибка анализа {symbol}: {e}")
