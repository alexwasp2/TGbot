import requests

import state
from config import TG_BOT_TOKEN, TG_CHAT_ID


def fmt_usd(val):
    val = float(val)
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    elif val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}"


def fmt_val(val):
    val = float(val)
    if val >= 1_000_000_000:
        return f"{val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"{val/1_000_000:.1f}M"
    elif val >= 1_000:
        return f"{val/1_000:.0f}K"
    return f"{val:.0f}"


def get_min_wall_usd(volume_24h_usd, market="futures"):
    vol_m = volume_24h_usd / 1_000_000
    tiers = state.spot_settings["tiers"] if market == "spot" else state.settings["tiers"]
    for tier in tiers:
        if tier["vol_from"] <= vol_m < tier["vol_to"]:
            return tier["min_wall"] * 1000
    return 2_000_000


def should_send_alert():
    return not state.alerts_paused and len(state.users_in_settings) == 0


def send_message(text):
    if not should_send_alert():
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except:
        pass


def parse_position(pos):
    p = pos.get("position", {})
    size = float(p.get("szi", 0))
    entry = float(p.get("entryPx", 0) or 0)
    return {
        "coin": p.get("coin", ""),
        "size": size,
        "entry": entry,
        "value": abs(size * entry),
        "direction": "LONG 🟢" if size > 0 else "SHORT 🔴",
        "leverage": p.get("leverage", {}).get("value", 1),
    }


def format_position_alert(p, change_type, wallet, wallet_name, last_size=None):
    labels = {
        "new": "🚨 Новая позиция!",
        "changed": "📝 Изменение позиции!",
        "closed": "❌ Позиция закрыта!",
    }
    parts = [
        f"<b>{labels[change_type]}</b>",
        f"👤 <b>{wallet_name}</b>",
        "",
        f"💎 {p['coin']} — {p['direction']}",
        f"💰 Размер: {fmt_usd(p['value'])}",
        f"📈 Вход: ${p['entry']}",
        f"⚡️ Плечо: {p['leverage']}x",
    ]
    if last_size and change_type == "new":
        parts += ["", f"📊 В прошлый раз: {fmt_usd(last_size)}"]
    parts += ["", f'🔗 <a href="https://hyperdash.com/?snoop={wallet}">HyperDash</a>']
    return "\n".join(parts)


def format_order_alert(order, wallet, wallet_name):
    side = "BUY 🟢" if order.get("side") == "B" else "SELL 🔴"
    price = float(order.get("limitPx", 0))
    size = float(order.get("sz", 0))
    coin = order.get("coin", "")
    parts = [
        "📋 <b>Новый лимитный ордер!</b>",
        f"👤 <b>{wallet_name}</b>",
        "",
        f"💎 {coin} — {side}",
        f"💰 Размер: {fmt_usd(size * price)}",
        f"🎯 Цена: ${price}",
        "",
        f'🔗 <a href="https://hyperdash.com/?snoop={wallet}">HyperDash</a>',
    ]
    return "\n".join(parts)


def send_report(text, inline_keyboard=None):
    """Отправляет сообщение с опциональной inline-клавиатурой (для дневного репорта)."""
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if inline_keyboard:
        payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"send_report error: {e}")
