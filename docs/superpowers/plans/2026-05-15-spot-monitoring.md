# Spot Market Monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Binance Spot orderbook wall detection with fully independent settings (filters, tiers, custom coins) alongside existing futures monitoring, with a Фьюч/Спот selector in the settings UI.

**Architecture:** Parameterized `check_orderbook_walls(symbol, bids, asks, market="futures")` reads the correct state dicts based on `market`. Futures and spot WebSocket streams run concurrently under one `asyncio.gather`. Settings UI adds a market type selector before the existing settings menu. All market routing in handlers uses `.get("market", "futures")` for stale-session safety.

**Tech Stack:** Python, python-telegram-bot, websockets, requests, Upstash Redis (REST)

**Spec:** `docs/superpowers/specs/2026-05-15-spot-monitoring-design.md`

---

## File Map

| File | Change |
|------|--------|
| `hyperliquid_bot/config.py` | Add `DEFAULT_SPOT_SETTINGS`, `SPOT_SETTINGS_FILE` |
| `hyperliquid_bot/state.py` | Add `spot_settings`, `spot_custom_walls`, `spot_wall_cooldowns`, `spot_symbol_volumes` |
| `hyperliquid_bot/storage/persistence.py` | Add `load_spot_settings()`, `save_spot_settings()`, extend `load_custom_data`/`save_custom_data` for `spot_custom_walls` |
| `hyperliquid_bot/main.py` | Add `load_spot_settings()` call |
| `hyperliquid_bot/utils/formatters.py` | Add `market` param to `get_min_wall_usd` |
| `hyperliquid_bot/monitor/walls.py` | Parameterize `check_orderbook_walls`, add `spot_wall_candidates`, add F/S markers |
| `hyperliquid_bot/api/binance.py` | Add `fetch_spot_tickers()`, `binance_spot_ws_stream()`, update `run_binance_monitor()` |
| `hyperliquid_bot/bot/keyboards.py` | Add `settings_type_keyboard()`, add `market` param to `settings_menu_keyboard()` |
| `hyperliquid_bot/bot/handlers.py` | Add Фьюч/Спот selector flow, route all settings modes by market |

---

## Task 1: Foundation — config, state, persistence

**Files:**
- Modify: `hyperliquid_bot/config.py`
- Modify: `hyperliquid_bot/state.py`
- Modify: `hyperliquid_bot/storage/persistence.py`
- Modify: `hyperliquid_bot/main.py`

- [ ] **Step 1.1: Add DEFAULT_SPOT_SETTINGS and SPOT_SETTINGS_FILE to config.py**

In `hyperliquid_bot/config.py`, add after the `DEFAULT_SETTINGS` block:

```python
SPOT_SETTINGS_FILE = "spot_settings.json"

DEFAULT_SPOT_SETTINGS = {
    "price_range_pct": 2.0,
    "cooldown_min": 5,
    "min_multiplier": 3,
    "min_symbol_volume_m": 1,
    "tiers": [
        {"vol_from": 1,    "vol_to": 10,    "min_wall": 100},
        {"vol_from": 10,   "vol_to": 50,    "min_wall": 200},
        {"vol_from": 50,   "vol_to": 200,   "min_wall": 500},
        {"vol_from": 200,  "vol_to": 1000,  "min_wall": 1000},
        {"vol_from": 1000, "vol_to": 999999, "min_wall": 2000},
    ]
}
```

- [ ] **Step 1.2: Add spot fields to state.py**

Replace the entire `hyperliquid_bot/state.py` with:

```python
from config import DEFAULT_SETTINGS, DEFAULT_SPOT_SETTINGS, DEFAULT_WALLET

settings = dict(DEFAULT_SETTINGS)
spot_settings = dict(DEFAULT_SPOT_SETTINGS)
alerts_paused = False
users_in_settings = set()
custom_walls = {}
spot_custom_walls = {}
watched_wallets = {DEFAULT_WALLET: "Трейдер 1"} if DEFAULT_WALLET else {}
volume_history = {}
wall_cooldowns = {}
spot_wall_cooldowns = {}
symbol_volumes = {}
spot_symbol_volumes = {}
user_state = {}
```

- [ ] **Step 1.3: Verify state imports**

```
cd hyperliquid_bot && python -c "import state; print('spot_settings min_vol:', state.spot_settings['min_symbol_volume_m']); print('OK')"
```

Expected:
```
spot_settings min_vol: 1
OK
```

- [ ] **Step 1.4: Add load_spot_settings and save_spot_settings to persistence.py**

Update the import line at the top of `hyperliquid_bot/storage/persistence.py`:

```python
from config import DEFAULT_SETTINGS, DEFAULT_SPOT_SETTINGS, SETTINGS_FILE, SPOT_SETTINGS_FILE, VOLUME_FILE, CUSTOM_DATA_FILE
```

Then add these two functions after `save_settings()`:

```python
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
```

- [ ] **Step 1.5: Extend load_custom_data to load spot_custom_walls**

In `load_custom_data()`, add this block after the `redis_get("watched_wallets")` section (right before `if not redis_ok`):

```python
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
```

And in the file-fallback block (inside `if not redis_ok and os.path.exists(CUSTOM_DATA_FILE):`), after loading `watched_wallets`, add:

```python
            if isinstance(saved.get("spot_custom_walls"), dict):
                state.spot_custom_walls = {k: float(v) for k, v in saved["spot_custom_walls"].items()}
```

- [ ] **Step 1.6: Extend save_custom_data to save spot_custom_walls**

Replace the `save_custom_data()` function body with:

```python
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
```

- [ ] **Step 1.7: Add load_spot_settings call to main.py**

In `hyperliquid_bot/main.py`, update the import:

```python
from storage.persistence import load_settings, load_spot_settings, load_volume_history, load_custom_data
```

And in `main()`, add `load_spot_settings()` right after `load_settings()`:

```python
    load_settings()
    load_spot_settings()
    load_volume_history()
    load_custom_data()
```

- [ ] **Step 1.8: Verify persistence imports**

```
cd hyperliquid_bot && python -c "from storage.persistence import load_spot_settings, save_spot_settings; print('OK')"
```

Expected:
```
OK
```

- [ ] **Step 1.9: Commit**

```bash
git add hyperliquid_bot/config.py hyperliquid_bot/state.py hyperliquid_bot/storage/persistence.py hyperliquid_bot/main.py
git commit -m "feat(sprint1): add spot state, config defaults, persistence"
```

---

## Task 2: Wall detection core — walls.py + formatters.py

**Files:**
- Modify: `hyperliquid_bot/utils/formatters.py`
- Modify: `hyperliquid_bot/monitor/walls.py`

- [ ] **Step 2.1: Update get_min_wall_usd to accept market param**

In `hyperliquid_bot/utils/formatters.py`, replace the `get_min_wall_usd` function:

```python
def get_min_wall_usd(volume_24h_usd, market="futures"):
    vol_m = volume_24h_usd / 1_000_000
    tiers = state.spot_settings["tiers"] if market == "spot" else state.settings["tiers"]
    for tier in tiers:
        if tier["vol_from"] <= vol_m < tier["vol_to"]:
            return tier["min_wall"] * 1000
    return 2_000_000
```

- [ ] **Step 2.2: Rewrite walls.py with market param and spot_wall_candidates**

Replace the entire `hyperliquid_bot/monitor/walls.py` with:

```python
import time

import state
from utils.formatters import fmt_usd, fmt_val, get_min_wall_usd, send_message

wall_candidates = {}        # {(symbol, round(price,6), side): tick_count}
spot_wall_candidates = {}   # same structure for spot


def check_orderbook_walls(symbol, bids, asks, market="futures"):
    try:
        s = state.spot_settings if market == "spot" else state.settings
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
```

- [ ] **Step 2.3: Verify walls.py imports cleanly**

```
cd hyperliquid_bot && python -c "from monitor.walls import check_orderbook_walls, wall_candidates, spot_wall_candidates; print('OK')"
```

Expected:
```
OK
```

- [ ] **Step 2.4: Smoke-test market routing**

```
cd hyperliquid_bot && python -c "
import state
from monitor.walls import check_orderbook_walls
state.spot_settings['cooldown_min'] = 99
state.settings['cooldown_min'] = 1
check_orderbook_walls('TESTUSDT', [], [], market='spot')
check_orderbook_walls('TESTUSDT', [], [], market='futures')
print('No crash — routing OK')
"
```

Expected:
```
No crash — routing OK
```

- [ ] **Step 2.5: Commit**

```bash
git add hyperliquid_bot/utils/formatters.py hyperliquid_bot/monitor/walls.py
git commit -m "feat(sprint2): parameterize walls by market, add F/S alert markers"
```

---

## Task 3: Binance Spot WebSocket

**Files:**
- Modify: `hyperliquid_bot/api/binance.py`

- [ ] **Step 3.1: Replace binance.py with spot support**

Replace the entire `hyperliquid_bot/api/binance.py` with:

```python
import asyncio
import json

import requests
import websockets

import state
from config import TG_BOT_TOKEN, TG_CHAT_ID
from monitor.walls import check_orderbook_walls


def fetch_binance_tickers():
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
                state.symbol_volumes[sym] = vol
            symbols.append(sym)
        print(f"Binance Futures: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance ticker ошибка: {e}")
        return []


def fetch_spot_tickers():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15)
        data = r.json()
        symbols = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            vol = float(item.get("quoteVolume", 0))
            if vol > 0:
                state.spot_symbol_volumes[sym] = vol
            symbols.append(sym)
        print(f"Binance Spot: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance spot ticker ошибка: {e}")
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
                    check_orderbook_walls(symbol, data.get("b", []), data.get("a", []), market="futures")
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS фьюч ошибка {symbol}: {e}")
            await asyncio.sleep(5)


async def binance_spot_ws_stream(symbol):
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@depth20@100ms"
    error_count = 0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                error_count = 0
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    check_orderbook_walls(symbol, data.get("b", []), data.get("a", []), market="spot")
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS спот ошибка {symbol}: {e}")
            await asyncio.sleep(5)


async def run_binance_monitor():
    futures_symbols = fetch_binance_tickers()
    spot_symbols = fetch_spot_tickers()
    if not futures_symbols and not spot_symbols:
        return

    both = set(futures_symbols) & set(spot_symbols)
    print(f"Binance: {len(futures_symbols)} фьюч + {len(both)} спот стримов")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": f"🔥 Binance стакан: {len(futures_symbols)} фьюч + {len(both)} спот монет",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except:
        pass

    tasks = [asyncio.create_task(binance_ws_stream(s)) for s in futures_symbols]
    tasks += [asyncio.create_task(binance_spot_ws_stream(s)) for s in both]
    await asyncio.gather(*tasks)


def binance_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_binance_monitor())
```

- [ ] **Step 3.2: Verify binance.py imports**

```
cd hyperliquid_bot && python -c "from api.binance import fetch_spot_tickers, binance_spot_ws_stream; print('OK')"
```

Expected:
```
OK
```

- [ ] **Step 3.3: Test spot ticker fetch (requires network)**

```
cd hyperliquid_bot && python -c "
import state
from api.binance import fetch_spot_tickers
syms = fetch_spot_tickers()
print(f'Spot symbols: {len(syms)}')
print(f'spot_symbol_volumes: {len(state.spot_symbol_volumes)}')
print('BTCUSDT present:', 'BTCUSDT' in syms)
"
```

Expected (approximate):
```
Binance Spot: ~500 USDT монет
Spot symbols: ~500
spot_symbol_volumes: ~500
BTCUSDT present: True
```

- [ ] **Step 3.4: Commit**

```bash
git add hyperliquid_bot/api/binance.py
git commit -m "feat(sprint3): add Binance spot WebSocket streams"
```

---

## Task 4: UI — keyboards and handlers

**Files:**
- Modify: `hyperliquid_bot/bot/keyboards.py`
- Modify: `hyperliquid_bot/bot/handlers.py`

- [ ] **Step 4.1: Replace keyboards.py**

Replace the entire `hyperliquid_bot/bot/keyboards.py` with:

```python
import state
from telegram import ReplyKeyboardMarkup


def main_menu_keyboard():
    pause_label = "▶️ Возобновить" if state.alerts_paused else "⏸ Пауза"
    return ReplyKeyboardMarkup([
        ["📊 Аналитика", "⚙️ Настройки"],
        ["👛 Кошельки", pause_label],
    ], resize_keyboard=True)


def back_keyboard():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)


def wallets_manage_keyboard():
    buttons = [["➕ Добавить"]]
    for addr, name in state.watched_wallets.items():
        buttons.append([name])
    buttons.append(["🔙 Назад"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def settings_type_keyboard():
    return ReplyKeyboardMarkup([
        ["📈 Фьюч", "💰 Спот"],
        ["🔙 Назад"],
    ], resize_keyboard=True)


def settings_menu_keyboard(market="futures"):
    label = "Фьюч" if market == "futures" else "Спот"
    return ReplyKeyboardMarkup([
        ["🎛 Фильтры", "📈 Тиры"],
        [f"🎯 Монеты ({label})", "🔙 Назад"],
    ], resize_keyboard=True)


def railway_keyboard():
    return ReplyKeyboardMarkup([
        ["⛔ Остановить деплой"],
        ["▶️ Запустить деплой"],
        ["🔙 Назад"],
    ], resize_keyboard=True)
```

Note: "🎯 Монеты" button gains a market label so the user can see which market they're editing at a glance. The handler must match this new button text.

- [ ] **Step 4.2: Replace handlers.py**

Replace the entire `hyperliquid_bot/bot/handlers.py` with:

```python
import state
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_ID
from storage.persistence import save_custom_data, save_settings, save_spot_settings
from utils.formatters import fmt_usd
from bot.keyboards import (
    main_menu_keyboard, back_keyboard, wallets_manage_keyboard,
    settings_type_keyboard, settings_menu_keyboard, railway_keyboard,
)
from bot.analytics import get_analytics_text


def is_admin(update: Update) -> bool:
    return str(update.effective_user.id) == str(ADMIN_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state.user_state.pop(uid, None)
    state.users_in_settings.discard(uid)
    await update.message.reply_text(
        "👋 <b>HyperLiquid монитор</b>\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def railway_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    uid = update.effective_user.id
    state.user_state[uid] = {"mode": "railway"}
    await update.message.reply_text(
        "🚂 <b>Управление Railway</b>\n\nОстановка деплоя отключит бота через несколько секунд.",
        parse_mode="HTML",
        reply_markup=railway_keyboard(),
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()

    # Главное меню
    if text == "📊 Аналитика":
        state.user_state.pop(uid, None)
        state.users_in_settings.discard(uid)
        state.user_state[uid] = {"mode": "analytics"}
        kb = ReplyKeyboardMarkup([
            ["⚡️ За 1 час", "📊 За 24 часа"],
            ["🔙 Назад"],
        ], resize_keyboard=True)
        await update.message.reply_text("📊 <b>Аналитика</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb)
        return

    if text == "⚙️ Настройки":
        state.user_state.pop(uid, None)
        state.users_in_settings.add(uid)
        state.user_state[uid] = {"mode": "settings_type"}
        await update.message.reply_text(
            "⚙️ <b>Настройки</b>\n\nВыбери рынок:",
            parse_mode="HTML",
            reply_markup=settings_type_keyboard(),
        )
        return

    if text in ("📈 Фьюч", "💰 Спот"):
        market = "futures" if text == "📈 Фьюч" else "spot"
        label = "Фьюч" if market == "futures" else "Спот"
        state.user_state[uid] = {"mode": "settings_menu", "market": market}
        await update.message.reply_text(
            f"⚙️ <b>Настройки — {label}</b>",
            parse_mode="HTML",
            reply_markup=settings_menu_keyboard(market),
        )
        return

    if text == "👛 Кошельки":
        state.users_in_settings.discard(uid)
        await update.message.reply_text("👛 <b>Кошельки</b>", parse_mode="HTML", reply_markup=wallets_manage_keyboard())
        return

    if text in ("⏸ Пауза", "▶️ Возобновить"):
        state.alerts_paused = not state.alerts_paused
        status = "⏸ Алерты на паузе" if state.alerts_paused else "▶️ Алерты активны"
        await update.message.reply_text(f"<b>{status}</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    # Аналитика
    if text == "⚡️ За 1 час":
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(get_analytics_text(1, "1 час"), parse_mode="HTML", reply_markup=kb)
        return

    if text == "📊 За 24 часа":
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(get_analytics_text(24, "24 часа"), parse_mode="HTML", reply_markup=kb)
        return

    # Настройки — кнопки меню
    if text == "🎛 Фильтры":
        market = state.user_state.get(uid, {}).get("market", "futures")
        s = state.spot_settings if market == "spot" else state.settings
        label = "Спот" if market == "spot" else "Фьюч"
        msg = f"⚙️ <b>Фильтры ({label}):</b>\n\n"
        msg += f"📏 Радиус: ±{s['price_range_pct']}%\n"
        msg += f"⏱ Кулдаун: {s['cooldown_min']} мин\n"
        msg += f"📈 Множитель: {s['min_multiplier']}x\n"
        msg += f"📊 Мин. объём: ${s['min_symbol_volume_m']}M\n\n"
        msg += "Отправь число для изменения:"
        kb = ReplyKeyboardMarkup(
            [["📏 Радиус", "⏱ Кулдаун"], ["📈 Множитель", "📊 Объём"], ["🔙 Назад"]],
            resize_keyboard=True,
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        state.user_state[uid] = {"mode": "filters", "market": market}
        return

    if text == "📈 Тиры":
        market = state.user_state.get(uid, {}).get("market", "futures")
        s = state.spot_settings if market == "spot" else state.settings
        label = "Спот" if market == "spot" else "Фьюч"
        t = s["tiers"]
        msg = f"📈 <b>Тиры по объёму ({label}):</b>\n\n"
        for i, tier in enumerate(t):
            wall = f"${tier['min_wall']}K" if tier["min_wall"] < 1000 else f"${tier['min_wall'] // 1000}M"
            msg += f"{i+1}. ${tier['vol_from']}M–${tier['vol_to']}M → {wall}\n"
        msg += "\nОтправь номер для изменения:"
        kb = ReplyKeyboardMarkup([["1", "2", "3"], ["4", "5"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        state.user_state[uid] = {"mode": "tiers", "market": market}
        return

    if text in ("🎯 Монеты (Фьюч)", "🎯 Монеты (Спот)"):
        market = "futures" if "Фьюч" in text else "spot"
        custom = state.spot_custom_walls if market == "spot" else state.custom_walls
        label = "Спот" if market == "spot" else "Фьюч"
        if not custom:
            msg = f"🎯 <b>Кастомные монеты ({label})</b>\n\nПока пусто.\n\n"
        else:
            msg = f"🎯 <b>Кастомные монеты ({label}):</b>\n\n"
            for sym, wall in custom.items():
                msg += f"• {sym}: {fmt_usd(wall)}\n"
            msg += "\n"
        msg += "➕ Добавить/изменить:\n<code>BTCUSDT 5000000</code>\n\n"
        msg += "❌ Удалить:\n<code>BTCUSDT 0</code>"
        kb = ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        state.user_state[uid] = {"mode": "coins", "market": market}
        return

    # Кошельки
    if text == "➕ Добавить":
        await update.message.reply_text(
            "Отправь в формате:\n<code>0x123...abc Имя</code>",
            parse_mode="HTML",
            reply_markup=back_keyboard(),
        )
        state.user_state[uid] = {"mode": "add_wallet"}
        return

    # Обработка режимов ввода
    mode = state.user_state.get(uid, {}).get("mode")

    if mode == "settings_type":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            state.users_in_settings.discard(uid)
            await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    if mode == "settings_menu":
        if text == "🔙 Назад":
            state.user_state[uid] = {"mode": "settings_type"}
            await update.message.reply_text(
                "⚙️ <b>Настройки</b>\n\nВыбери рынок:",
                parse_mode="HTML",
                reply_markup=settings_type_keyboard(),
            )
        return

    if mode == "analytics":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            state.users_in_settings.discard(uid)
            await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        kb = ReplyKeyboardMarkup([["⚡️ За 1 час", "📊 За 24 часа"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text("📊 <b>Аналитика</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb)
        return

    if mode == "add_wallet":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("👛 <b>Кошельки</b>", parse_mode="HTML", reply_markup=wallets_manage_keyboard())
            return
        parts = text.split()
        if len(parts) >= 2 and parts[0].startswith("0x") and len(parts[0]) >= 30:
            addr = parts[0]
            name = " ".join(parts[1:])
            state.watched_wallets[addr] = name
            save_custom_data()
            await update.message.reply_text(f"✅ Добавлен: <b>{name}</b>", parse_mode="HTML", reply_markup=wallets_manage_keyboard())
            state.user_state.pop(uid, None)
        else:
            await update.message.reply_text("❌ Формат: <code>0x123...abc Имя</code>", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "coins":
        market = state.user_state.get(uid, {}).get("market", "futures")
        custom = state.spot_custom_walls if market == "spot" else state.custom_walls
        if text == "🔙 Назад":
            state.user_state[uid] = {"mode": "settings_menu", "market": market}
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
            return
        parts = text.upper().split()
        if len(parts) == 2:
            sym, wall_str = parts
            try:
                wall = int(wall_str)
                if wall == 0:
                    custom.pop(sym, None)
                    await update.message.reply_text(f"✅ Удалён: {sym}", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
                else:
                    custom[sym] = wall
                    await update.message.reply_text(f"✅ {sym}: {fmt_usd(wall)}", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
                save_custom_data()
                state.user_state.pop(uid, None)
            except:
                await update.message.reply_text(
                    "❌ Ошибка. Формат: <code>BTCUSDT 5000000</code>",
                    parse_mode="HTML",
                    reply_markup=back_keyboard(),
                )
        else:
            await update.message.reply_text(
                "❌ Формат: <code>BTCUSDT 5000000</code>",
                parse_mode="HTML",
                reply_markup=back_keyboard(),
            )
        return

    if mode == "filters":
        market = state.user_state.get(uid, {}).get("market", "futures")
        s = state.spot_settings if market == "spot" else state.settings
        if text == "🔙 Назад":
            state.user_state[uid] = {"mode": "settings_menu", "market": market}
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
            return
        if text in ("📏 Радиус", "⏱ Кулдаун", "📈 Множитель", "📊 Объём"):
            state.user_state[uid] = {"mode": "filters", "market": market, "type": text}
            await update.message.reply_text("Введи число:", parse_mode="HTML", reply_markup=back_keyboard())
            return
        try:
            val = float(text.replace(",", "."))
            filter_type = state.user_state.get(uid, {}).get("type")
            if filter_type == "📏 Радиус":
                s["price_range_pct"] = val
            elif filter_type == "⏱ Кулдаун":
                s["cooldown_min"] = int(val)
            elif filter_type == "📈 Множитель":
                s["min_multiplier"] = val
            elif filter_type == "📊 Объём":
                s["min_symbol_volume_m"] = val
            save_spot_settings() if market == "spot" else save_settings()
            state.user_state[uid] = {"mode": "settings_menu", "market": market}
            await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
        except:
            await update.message.reply_text("❌ Введи число", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "tiers":
        market = state.user_state.get(uid, {}).get("market", "futures")
        s = state.spot_settings if market == "spot" else state.settings
        if text == "🔙 Назад":
            state.user_state[uid] = {"mode": "settings_menu", "market": market}
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
            return
        current_idx = state.user_state.get(uid, {}).get("idx")
        if current_idx is not None:
            use_millions = current_idx >= 3
            try:
                val = int(text)
                s["tiers"][current_idx]["min_wall"] = val * 1000 if use_millions else val
                save_spot_settings() if market == "spot" else save_settings()
                state.user_state[uid] = {"mode": "settings_menu", "market": market}
                await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard(market))
            except:
                unit = "$M" if use_millions else "$K"
                await update.message.reply_text(f"❌ Введи целое число (в {unit}):", parse_mode="HTML", reply_markup=back_keyboard())
        else:
            try:
                tier_num = int(text) - 1
                if 0 <= tier_num < len(s["tiers"]):
                    state.user_state[uid] = {"mode": "tiers", "market": market, "idx": tier_num}
                    unit = "$M" if tier_num >= 3 else "$K"
                    await update.message.reply_text(f"Введи мин. стену в {unit}:", parse_mode="HTML", reply_markup=back_keyboard())
                else:
                    await update.message.reply_text(
                        f"❌ Неверный номер. Введи от 1 до {len(s['tiers'])}:",
                        parse_mode="HTML",
                        reply_markup=back_keyboard(),
                    )
            except:
                await update.message.reply_text(
                    f"❌ Введи номер тира (1–{len(s['tiers'])}):",
                    parse_mode="HTML",
                    reply_markup=back_keyboard(),
                )
        return

    if mode == "railway":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        if not is_admin(update):
            await update.message.reply_text("⛔ Нет доступа.")
            return
        if text == "⛔ Остановить деплой":
            await update.message.reply_text(
                "⏳ Останавливаю деплой...\n\nБот уйдёт в офлайн через несколько секунд.",
                parse_mode="HTML",
                reply_markup=railway_keyboard(),
            )
            try:
                from api.railway import stop_service
                stop_service()
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}", parse_mode="HTML", reply_markup=railway_keyboard())
            return
        if text == "▶️ Запустить деплой":
            try:
                from api.railway import start_service
                start_service()
                await update.message.reply_text("✅ Деплой запущен!", parse_mode="HTML", reply_markup=railway_keyboard())
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}", parse_mode="HTML", reply_markup=railway_keyboard())
            return

    # Назад
    if text == "🔙 Назад":
        state.user_state.pop(uid, None)
        state.users_in_settings.discard(uid)
        await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    # Инфо о кошельке
    for addr, name in state.watched_wallets.items():
        if text == name:
            short = addr[:6] + "..." + addr[-4:]
            kb = ReplyKeyboardMarkup([[f"❌ Удалить {name}"], ["🔙 Назад"]], resize_keyboard=True)
            msg = f"👤 <b>{name}</b>\n<code>{short}</code>\n\n"
            msg += f'🔗 <a href="https://hyperdash.com/?snoop={addr}">Открыть HyperDash</a>'
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
            state.user_state[uid] = {"mode": "wallet_info", "addr": addr}
            return

    # Удалить кошелёк
    for addr, name in list(state.watched_wallets.items()):
        if text == f"❌ Удалить {name}":
            del state.watched_wallets[addr]
            save_custom_data()
            await update.message.reply_text(f"✅ Удалён: {name}", parse_mode="HTML", reply_markup=main_menu_keyboard())
            state.user_state.pop(uid, None)
            return
```

- [ ] **Step 4.3: Verify handlers.py imports**

```
cd hyperliquid_bot && python -c "from bot.handlers import message_handler; print('OK')"
```

Expected:
```
OK
```

- [ ] **Step 4.4: Commit**

```bash
git add hyperliquid_bot/bot/keyboards.py hyperliquid_bot/bot/handlers.py
git commit -m "feat(sprint4): add Фьюч/Спот settings selector, route handlers by market"
```

---

## Final Verification Checklist

- [ ] Bot starts: `cd hyperliquid_bot && python main.py` — no import errors in first 5 seconds
- [ ] Logs show `Binance Futures: N монет` and `Binance Spot: N монет`
- [ ] ⚙️ Настройки → shows Фьюч / Спот buttons
- [ ] Фьюч → shows Фильтры / Тиры / Монеты (Фьюч) menu
- [ ] Спот → shows Фильтры / Тиры / Монеты (Спот) menu
- [ ] Change a Спот tier, then check Фьюч tiers — they must be unchanged
- [ ] 🔙 from Фильтры/Тиры → back to market settings menu (not main menu)
- [ ] 🔙 from market settings menu → back to Фьюч/Спот selector
- [ ] 🔙 from Фьюч/Спот selector → back to main menu
- [ ] Futures wall alerts show `F` marker (not inside code tag)
- [ ] Spot wall alerts show `S` marker (not inside code tag)
