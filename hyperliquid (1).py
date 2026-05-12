import requests
import time
import threading
import json
import os
import asyncio
import websockets
from datetime import datetime, timezone
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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
        {"vol_from": 5000, "vol_to": 999999,"min_wall": 3000},
    ]
}

settings = dict(DEFAULT_SETTINGS)
alerts_paused = False
users_in_settings = set()
custom_walls = {}
watched_wallets = {DEFAULT_WALLET: "Трейдер 1"} if DEFAULT_WALLET else {}
volume_history = {}
wall_cooldowns = {}
symbol_volumes = {}
user_state = {}

# ───────────────────────── Redis ─────────────────────────

def redis_get(key):
    if not UPSTASH_URL:
        return None
    try:
        r = requests.get(f"{UPSTASH_URL}/get/{key}",
                         headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=10)
        return r.json().get("result")
    except:
        return None

def redis_set(key, value):
    if not UPSTASH_URL:
        return
    try:
        requests.post(f"{UPSTASH_URL}/pipeline",
                      headers={"Authorization": f"Bearer {UPSTASH_TOKEN}",
                               "Content-Type": "application/json"},
                      json=[["SET", key, value]], timeout=10)
    except:
        pass

# ───────────────────────── Load/Save ─────────────────────────

def load_settings():
    global settings
    data = redis_get("settings")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            settings = dict(DEFAULT_SETTINGS)
            settings.update(loaded)
            if "tiers" not in loaded or not isinstance(loaded.get("tiers"), list):
                settings["tiers"] = DEFAULT_SETTINGS["tiers"]
            print("Redis: настройки загружены")
            return
        except Exception as e:
            print(f"Redis ошибка: {e}")
            pass
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
                settings = dict(DEFAULT_SETTINGS)
                settings.update(loaded)
                print("Файл: настройки загружены")
        except Exception as e:
            print(f"Ошибка файла: {e}")
            settings = dict(DEFAULT_SETTINGS)
    else:
        settings = dict(DEFAULT_SETTINGS)
        print("Используются дефолт настройки")

def save_settings():
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)
    redis_set("settings", json.dumps(settings))

def load_custom_data():
    global custom_walls, watched_wallets
    data = redis_get("custom_walls")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str): loaded = json.loads(loaded)
            if isinstance(loaded, dict): custom_walls = loaded
        except: pass
    data = redis_get("watched_wallets")
    if data:
        try:
            loaded = json.loads(data) if isinstance(data, str) else data
            if isinstance(loaded, str): loaded = json.loads(loaded)
            if isinstance(loaded, dict): watched_wallets = loaded
        except: pass

def save_custom_data():
    redis_set("custom_walls", json.dumps(custom_walls))
    redis_set("watched_wallets", json.dumps(watched_wallets))

def load_volume_history():
    global volume_history
    data = redis_get("volume_history")
    if data:
        try:
            loaded = json.loads(data)
            if isinstance(loaded, str):
                loaded = json.loads(loaded)
            if isinstance(loaded, dict):
                volume_history = {k: v for k, v in loaded.items() if isinstance(v, dict)}
                if volume_history:
                    print(f"Redis: volume_history загружен, {len(volume_history)} снимков")
                    return
        except Exception as e:
            print(f"Redis volume ошибка: {e}")
    if os.path.exists(VOLUME_FILE):
        try:
            with open(VOLUME_FILE, "r") as f:
                volume_history = json.load(f)
        except:
            pass

def save_volume_snapshot():
    global volume_history
    try:
        current = get_hl_volume_data()
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        volume_history[hour_key] = current
        keys = sorted(volume_history.keys())
        if len(keys) > 48:
            for old_key in keys[:-48]:
                del volume_history[old_key]
        redis_set("volume_history", json.dumps(volume_history))
        print(f"Объём сохранён: {hour_key}")
    except Exception as e:
        print(f"Ошибка сохранения объёма: {e}")

# ───────────────────────── Helpers ─────────────────────────

def fmt_usd(val):
    if val >= 1_000_000_000:
        return f"${val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    elif val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}"

def fmt_val(val):
    if val >= 1_000_000_000:
        return f"{val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"{val/1_000_000:.1f}M"
    elif val >= 1_000:
        return f"{val/1_000:.0f}K"
    return f"{val:.0f}"

def get_min_wall_usd(volume_24h_usd):
    vol_m = volume_24h_usd / 1_000_000
    for tier in settings["tiers"]:
        if tier["vol_from"] <= vol_m < tier["vol_to"]:
            return tier["min_wall"] * 1000
    return 2_000_000

def should_send_alert():
    return not alerts_paused and len(users_in_settings) == 0

def send_message(text):
    if not should_send_alert():
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

# ───────────────────────── API ─────────────────────────

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
    keys = sorted(volume_history.keys())
    if len(keys) < hours_ago + 1:
        return None
    current = volume_history[keys[-1]]
    prev = volume_history[keys[-(hours_ago + 1)]]
    result = []
    for coin, vol in current.items():
        if coin in prev and prev[coin] > 0:
            pct = ((vol - prev[coin]) / prev[coin]) * 100
            result.append({"coin": coin, "volume": vol, "pct": pct})
    result.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return result

# ───────────────────────── Position/Order Formatters ─────────────────────────

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
        "leverage": p.get("leverage", {}).get("value", 1)
    }

def format_position_alert(p, change_type, wallet, wallet_name, last_size=None):
    labels = {"new": "🚨 Новая позиция!", "changed": "📝 Изменение позиции!", "closed": "❌ Позиция закрыта!"}
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

# ───────────────────────── Orderbook Wall Detection ─────────────────────────

def check_orderbook_walls(symbol, bids, asks):
    try:
        if "cooldown_min" not in settings:
            return
        
        now = time.time()
        cooldown = settings["cooldown_min"] * 60
        if symbol in wall_cooldowns and now - wall_cooldowns[symbol] < cooldown:
            return
        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2
        price_range = settings["price_range_pct"] / 100
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
        vol_24h = symbol_volumes.get(symbol, 0)

        if vol_24h < settings["min_symbol_volume_m"] * 1_000_000:
            return

        min_wall = custom_walls.get(symbol, get_min_wall_usd(vol_24h))
        multiplier = settings["min_multiplier"]

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
        vol_str = f"${vol_24h/1_000_000_000:.1f}B" if vol_24h >= 1_000_000_000 else f"${vol_24h/1_000_000:.0f}M"

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
        wall_cooldowns[symbol] = now
        print(f"Плотняха: {symbol} {fmt_usd(top['value'])}")

    except Exception as e:
        print(f"Ошибка анализа {symbol}: {e}")

# ───────────────────────── Binance WS ─────────────────────────

def fetch_binance_tickers():
    global symbol_volumes
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=15)
        data = r.json()
        symbols = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            vol = float(item.get("quoteVolume", 0))
            if vol > 0:
                symbol_volumes[sym] = vol
            symbols.append(sym)
        print(f"Binance: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance ticker ошибка: {e}")
        return []

async def binance_ws_stream(symbol):
    url = f"wss://fstream.binance.com/ws/{symbol.lower()}@depth20@100ms"
    error_count = 0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                error_count = 0
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    check_orderbook_walls(symbol, data.get("b", []), data.get("a", []))
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS ошибка {symbol}: {e}")
            await asyncio.sleep(5)

async def run_binance_monitor():
    symbols = fetch_binance_tickers()
    if not symbols:
        return
    print(f"Binance: запускаю {len(symbols)} WS стримов")
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID,
                                 "text": f"🔥 Binance стакан: {len(symbols)} монет", "parse_mode": "HTML"}, timeout=10)
    except:
        pass
    await asyncio.gather(*[asyncio.create_task(binance_ws_stream(s)) for s in symbols])

def binance_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_binance_monitor())

# ───────────────────────── HyperLiquid monitor ─────────────────────────

def monitor_loop():
    wallet_positions = {}
    wallet_orders = {}
    last_volume_save = 0

    while True:
        try:
            if time.time() - last_volume_save > VOLUME_SAVE_INTERVAL:
                save_volume_snapshot()
                last_volume_save = time.time()

            for wallet, wallet_name in list(watched_wallets.items()):
                try:
                    positions = get_positions(wallet)
                    current = {}
                    for pos in positions:
                        p = parse_position(pos)
                        if p["value"] < MIN_SIZE_USD:
                            continue
                        current[p["coin"]] = p

                    prev = wallet_positions.get(wallet, {})
                    for coin, p in current.items():
                        if coin not in prev:
                            last_size = get_last_position_size(coin, wallet)
                            send_message(format_position_alert(p, "new", wallet, wallet_name, last_size))
                        else:
                            diff = abs(p["value"] - prev[coin]["value"])
                            if diff >= MIN_CHANGE_USD:
                                send_message(format_position_alert(p, "changed", wallet, wallet_name))
                    for coin in prev:
                        if coin not in current:
                            send_message(format_position_alert(prev[coin], "closed", wallet, wallet_name))
                    wallet_positions[wallet] = current

                    orders = get_orders(wallet)
                    prev_orders = wallet_orders.get(wallet, set())
                    current_orders = set()
                    for order in orders:
                        oid = str(order.get("oid", ""))
                        current_orders.add(oid)
                        if oid not in prev_orders:
                            send_message(format_order_alert(order, wallet, wallet_name))
                    wallet_orders[wallet] = current_orders

                except Exception as e:
                    print(f"Ошибка кошелька {wallet_name}: {e}")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Ошибка HL: {e}")
            time.sleep(60)

# ───────────────────────── Keyboards (REPLY KEYBOARDS - СНИЗУ) ─────────────────────────

def main_menu_keyboard():
    global alerts_paused
    pause_label = "▶️ Возобновить" if alerts_paused else "⏸ Пауза"
    return ReplyKeyboardMarkup([
        ["📊 Аналитика", "⚙️ Настройки"],
        ["👛 Кошельки", pause_label],
    ], resize_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)

def wallets_manage_keyboard():
    buttons = [["➕ Добавить"]]
    for addr, name in watched_wallets.items():
        buttons.append([name])
    buttons.append(["🔙 Назад"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def settings_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🎛 Фильтры", "📈 Тиры"],
        ["🎯 Монеты", "🔙 Назад"],
    ], resize_keyboard=True)

# ───────────────────────── Bot Handlers ─────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_state.pop(uid, None)
    users_in_settings.discard(uid)
    await update.message.reply_text(
        "👋 <b>HyperLiquid монитор</b>\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global alerts_paused
    uid = update.effective_user.id
    text = update.message.text.strip()

    # Главное меню
    if text == "📊 Аналитика":
        user_state.pop(uid, None)
        users_in_settings.discard(uid)
        user_state[uid] = {"mode": "analytics"}
        kb = ReplyKeyboardMarkup([
            ["⚡️ За 1 час", "📊 За 24 часа"],
            ["🔙 Назад"],
        ], resize_keyboard=True)
        await update.message.reply_text("📊 <b>Аналитика</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb)
        return

    if text == "⚙️ Настройки":
        users_in_settings.add(uid)
        await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
        return

    if text == "👛 Кошельки":
        users_in_settings.discard(uid)
        kb = wallets_manage_keyboard()
        await update.message.reply_text("👛 <b>Кошельки</b>", parse_mode="HTML", reply_markup=kb)
        return

    if text == "⏸ Пауза" or text == "▶️ Возобновить":
        alerts_paused = not alerts_paused
        status = "⏸ Алерты на паузе" if alerts_paused else "▶️ Алерты активны"
        await update.message.reply_text(f"<b>{status}</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    # Аналитика
    if text == "⚡️ За 1 час":
        result = calc_changes(1)
        if result is None:
            keys = sorted(volume_history.keys())
            msg = f"⏳ Мало данных. Есть {len(keys)} снимков из 2 нужных."
        else:
            msg = "📊 <b>Изменение объёма за 1 час:</b>\n\n"
            for r in result[:15]:
                sign = "+" if r["pct"] > 0 else ""
                msg += f"• {r['coin']}: {sign}{r['pct']:.0f}%\n"
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    if text == "📊 За 24 часа":
        result = calc_changes(24)
        if result is None:
            keys = sorted(volume_history.keys())
            msg = f"⏳ Мало данных. Есть {len(keys)} снимков из 25 нужных."
        else:
            msg = "📊 <b>Изменение объёма за 24 часа:</b>\n\n"
            for r in result[:15]:
                sign = "+" if r["pct"] > 0 else ""
                msg += f"• {r['coin']}: {sign}{r['pct']:.0f}%\n"
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    # Настройки
    if text == "🎛 Фильтры":
        s = settings
        msg = f"⚙️ <b>Фильтры:</b>\n\n"
        msg += f"📏 Радиус: ±{s['price_range_pct']}%\n"
        msg += f"⏱ Кулдаун: {s['cooldown_min']} мин\n"
        msg += f"📈 Множитель: {s['min_multiplier']}x\n"
        msg += f"📊 Мин. объём: ${s['min_symbol_volume_m']}M\n\n"
        msg += "Отправь число для изменения:"
        kb = ReplyKeyboardMarkup([["📏 Радиус", "⏱ Кулдаун"], ["📈 Множитель", "📊 Объём"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        user_state[uid] = {"mode": "filters"}
        return

    if text == "📈 Тиры":
        t = settings["tiers"]
        msg = "📈 <b>Тиры по объёму:</b>\n\n"
        for i, tier in enumerate(t):
            wall = f"${tier['min_wall']}K" if tier['min_wall'] < 1000 else f"${tier['min_wall']//1000}M"
            msg += f"{i+1}. ${tier['vol_from']}M–${tier['vol_to']}M → {wall}\n"
        msg += "\nОтправь номер для изменения:"
        kb = ReplyKeyboardMarkup([["1", "2", "3"], ["4", "5"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        user_state[uid] = {"mode": "tiers"}
        return

    if text == "🎯 Монеты":
        if not custom_walls:
            msg = "🎯 Пока нет кастомных монет.\n\nФормат: <code>BTCUSDT 5000000</code>"
        else:
            msg = "🎯 <b>Кастомные монеты:</b>\n\n"
            for sym, wall in custom_walls.items():
                msg += f"• {sym}: {fmt_usd(wall)}\n"
            msg += "\nОтправь <code>МОНЕТА 0</code> чтобы удалить"
        kb = ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        user_state[uid] = {"mode": "coins"}
        return

    # Кошельки
    if text == "➕ Добавить":
        await update.message.reply_text("Отправь в формате:\n<code>0x123...abc Имя</code>", parse_mode="HTML", reply_markup=back_keyboard())
        user_state[uid] = {"mode": "add_wallet"}
        return

    # Обработка режимов ввода
    mode = user_state.get(uid, {}).get("mode")

    if mode == "analytics":
        if text == "🔙 Назад":
            user_state.pop(uid, None)
            users_in_settings.discard(uid)
            await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        # Handle unknown input in analytics - just re-show the analytics menu
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text("📊 <b>Аналитика</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb)
        return

    if mode == "add_wallet":
        if text == "🔙 Назад":
            user_state.pop(uid, None)
            await update.message.reply_text("👛 <b>Кошельки</b>", parse_mode="HTML", reply_markup=wallets_manage_keyboard())
            return
        parts = text.split()
        if len(parts) >= 2 and parts[0].startswith("0x") and len(parts[0]) >= 30:
            addr = parts[0]
            name = " ".join(parts[1:])
            watched_wallets[addr] = name
            save_custom_data()
            await update.message.reply_text(f"✅ Добавлен: <b>{name}</b>", parse_mode="HTML", reply_markup=wallets_manage_keyboard())
            user_state.pop(uid, None)
        else:
            await update.message.reply_text("❌ Формат: <code>0x123...abc Имя</code>", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "coins":
        if text == "🔙 Назад":
            user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        parts = text.upper().split()
        if len(parts) == 2:
            sym, wall_str = parts
            try:
                wall = int(wall_str)
                if wall == 0:
                    custom_walls.pop(sym, None)
                    await update.message.reply_text(f"✅ Удалён: {sym}", parse_mode="HTML", reply_markup=settings_menu_keyboard())
                else:
                    custom_walls[sym] = wall
                    await update.message.reply_text(f"✅ {sym}: {fmt_usd(wall)}", parse_mode="HTML", reply_markup=settings_menu_keyboard())
                save_custom_data()
                user_state.pop(uid, None)
            except:
                await update.message.reply_text("❌ Ошибка. Формат: <code>BTCUSDT 5000000</code>", parse_mode="HTML", reply_markup=back_keyboard())
        else:
            await update.message.reply_text("❌ Формат: <code>BTCUSDT 5000000</code>", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "filters":
        if text == "🔙 Назад":
            user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        if text in ["📏 Радиус", "⏱ Кулдаун", "📈 Множитель", "📊 Объём"]:
            user_state[uid] = {"mode": "filters", "type": text}
            await update.message.reply_text(f"Введи число:", parse_mode="HTML", reply_markup=back_keyboard())
            return
        try:
            val = float(text.replace(",", "."))
            filter_type = user_state.get(uid, {}).get("type")
            if filter_type == "📏 Радиус":
                settings["price_range_pct"] = val
            elif filter_type == "⏱ Кулдаун":
                settings["cooldown_min"] = int(val)
            elif filter_type == "📈 Множитель":
                settings["min_multiplier"] = val
            elif filter_type == "📊 Объём":
                settings["min_symbol_volume_m"] = val
            save_settings()
            await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            user_state.pop(uid, None)
        except:
            await update.message.reply_text("❌ Введи число", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "tiers":
        if text == "🔙 Назад":
            user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        current_idx = user_state.get(uid, {}).get("idx")
        if current_idx is not None:
            try:
                val = int(text)
                settings["tiers"][current_idx]["min_wall"] = val
                save_settings()
                await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard())
                user_state.pop(uid, None)
            except:
                await update.message.reply_text("❌ Введи целое число (в $K):", parse_mode="HTML", reply_markup=back_keyboard())
        else:
            try:
                tier_num = int(text) - 1
                if 0 <= tier_num < len(settings["tiers"]):
                    user_state[uid] = {"mode": "tiers", "idx": tier_num}
                    await update.message.reply_text("Введи мин. стену в $K:", parse_mode="HTML", reply_markup=back_keyboard())
                else:
                    await update.message.reply_text(f"❌ Неверный номер. Введи от 1 до {len(settings['tiers'])}:", parse_mode="HTML", reply_markup=back_keyboard())
            except:
                await update.message.reply_text(f"❌ Введи номер тира (1–{len(settings['tiers'])}):", parse_mode="HTML", reply_markup=back_keyboard())
        return

    # Назад
    if text == "🔙 Назад":
        user_state.pop(uid, None)
        users_in_settings.discard(uid)
        await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    # Инфо о кошельке
    for addr, name in watched_wallets.items():
        if text == name:
            short = addr[:6] + "..." + addr[-4:]
            kb = ReplyKeyboardMarkup([
                [f"❌ Удалить {name}"],
                ["🔙 Назад"],
            ], resize_keyboard=True)
            msg = f"👤 <b>{name}</b>\n<code>{short}</code>\n\n"
            msg += f'🔗 <a href="https://hyperdash.com/?snoop={addr}">Открыть HyperDash</a>'
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
            user_state[uid] = {"mode": "wallet_info", "addr": addr}
            return

    # Удалить кошелёк
    for addr, name in list(watched_wallets.items()):
        if text == f"❌ Удалить {name}":
            del watched_wallets[addr]
            save_custom_data()
            await update.message.reply_text(f"✅ Удалён: {name}", parse_mode="HTML", reply_markup=main_menu_keyboard())
            user_state.pop(uid, None)
            return

# ───────────────────────── Main ─────────────────────────

def main():
    load_settings()
    load_volume_history()
    load_custom_data()
    print("✅ Монитор запущен!")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID,
                                 "text": "✅ Бот запущен! Напиши /start",
                                 "parse_mode": "HTML"}, timeout=10)
    except:
        pass

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=binance_thread, daemon=True).start()

    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
