# Spot Market Monitoring — Design Spec
**Date:** 2026-05-15  
**Status:** Approved

## Summary

Add Binance Spot orderbook wall detection alongside existing Binance Futures monitoring. Spot and futures have fully independent settings (filters, tiers, custom coins). The UI settings menu gains a Фьюч/Спот selector. Alerts are labelled with F (futures) or S (spot) markers that are non-copyable (outside `<code>` tag).

---

## Architecture

**Approach B — Parameterized shared module.**  
`check_orderbook_walls(symbol, bids, asks, market="futures")` reads the correct state dicts based on `market`. No duplicate logic, single point of change for wall detection algorithm.

---

## State (`state.py`)

New fields added:

```python
spot_settings = dict(DEFAULT_SPOT_SETTINGS)   # independent filters + tiers
spot_custom_walls = {}                          # per-symbol thresholds for spot
spot_wall_cooldowns = {}                        # cooldown tracking for spot
spot_symbol_volumes = {}                        # 24h spot volumes, keyed by symbol
```

`wall_candidates` and `spot_wall_candidates` live as **module-level dicts in `walls.py`** (not in state) — they are transient and reset on restart:

```python
# walls.py module level
wall_candidates = {}
spot_wall_candidates = {}
```

---

## Config (`config.py`)

New `DEFAULT_SPOT_SETTINGS` with softer defaults (spot volumes are lower than futures):

```python
DEFAULT_SPOT_SETTINGS = {
    "price_range_pct": 2.0,
    "cooldown_min": 5,
    "min_multiplier": 3,
    "min_symbol_volume_m": 1,   # lower than futures default (10)
    "tiers": [
        {"vol_from": 1,    "vol_to": 10,    "min_wall": 100},
        {"vol_from": 10,   "vol_to": 50,    "min_wall": 200},
        {"vol_from": 50,   "vol_to": 200,   "min_wall": 500},
        {"vol_from": 200,  "vol_to": 1000,  "min_wall": 1000},
        {"vol_from": 1000, "vol_to": 999999, "min_wall": 2000},
    ]
}
```

---

## Persistence (`persistence.py`)

`spot_settings` and `spot_custom_walls` saved/loaded under new Redis keys and JSON file keys. Same dual Redis→file fallback pattern as existing settings.

- Redis keys: `spot_settings`, `spot_custom_walls`
- JSON file: `custom_data.json` gains `spot_custom_walls` field; `settings.json` gains `spot_settings` field

---

## Wall Detection (`monitor/walls.py`)

Function signature:

```python
def check_orderbook_walls(symbol, bids, asks, market="futures"):
```

Internal routing:

```python
s         = state.spot_settings      if market == "spot" else state.settings
cooldowns = state.spot_wall_cooldowns if market == "spot" else state.wall_cooldowns
custom    = state.spot_custom_walls   if market == "spot" else state.custom_walls
candidates = spot_wall_candidates    if market == "spot" else wall_candidates
```

Detection logic — unchanged.

Alert format — market marker added **outside** `<code>` tag (non-copyable):

```
# Futures:
🧱 <b>Плотняха на</b> <code>BTCUSDT</code> F 🔴

# Spot:
🧱 <b>Плотняха на</b> <code>BTCUSDT</code> S 🟢
```

`symbol_volumes` dict stores both futures and spot volumes. Spot volumes are stored under the same symbol key since the ticker symbol is identical (e.g. `BTCUSDT`).

---

## Binance API (`api/binance.py`)

New function `fetch_spot_tickers()` — calls `api.binance.com/api/v3/ticker/24hr`, returns `{symbol: volume}` for USDT pairs. Volumes stored in a new `state.spot_symbol_volumes` dict (separate from futures volumes).

Symbol selection for spot WebSocket streams: **intersection** of futures symbols and spot symbols. Only coins that exist on both markets are monitored.

New WebSocket stream function:

```python
async def binance_spot_ws_stream(symbol):
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@depth20@100ms"
    # same reconnect logic as futures stream
    # calls check_orderbook_walls(symbol, ..., market="spot")
```

`run_binance_monitor()` launches both futures and spot streams in one `asyncio.gather`:

```python
async def run_binance_monitor():
    futures_symbols = fetch_binance_tickers()
    spot_symbols    = fetch_spot_tickers()
    both = set(futures_symbols) & set(spot_symbols)
    await asyncio.gather(
        *[asyncio.create_task(binance_ws_stream(s))      for s in futures_symbols],
        *[asyncio.create_task(binance_spot_ws_stream(s)) for s in both],
    )
```

---

## UI — Keyboards (`bot/keyboards.py`)

New function:

```python
def settings_type_keyboard():
    # shown immediately after ⚙️ Настройки
    return ReplyKeyboardMarkup([
        ["📈 Фьюч", "💰 Спот"],
        ["🔙 Назад"],
    ], resize_keyboard=True)
```

Modified function (adds `market` param):

```python
def settings_menu_keyboard(market="futures"):
    label = "⚙️ Настройки — Фьюч" if market == "futures" else "⚙️ Настройки — Спот"
    # same buttons: Фильтры, Тиры, Монеты, Назад
```

---

## UI — Handlers (`bot/handlers.py`)

**Settings entry flow:**

1. User taps ⚙️ Настройки → bot shows `settings_type_keyboard()`
2. User taps 📈 Фьюч or 💰 Спот → `user_state[uid] = {"mode": "settings_menu", "market": "futures"|"spot"}` → bot shows `settings_menu_keyboard(market)`
3. From there, all existing handlers (filters, tiers, coins) read `market` from `user_state` and write to the correct dict.

**Defensive market read everywhere:**

```python
market = state.user_state.get(uid, {}).get("market", "futures")
```

Never use direct index — protects stale sessions where `market` key may be absent.

**Handler routing:**

| mode | market=futures | market=spot |
|------|---------------|-------------|
| filters | `state.settings` | `state.spot_settings` |
| tiers | `state.settings["tiers"]` | `state.spot_settings["tiers"]` |
| coins | `state.custom_walls` | `state.spot_custom_walls` |

Save calls route to matching persistence functions (`save_settings()` vs `save_spot_settings()`).

---

## Sprints

### Sprint 1 — Foundation (state + config + persistence)
- `DEFAULT_SPOT_SETTINGS` in `config.py`
- `spot_settings`, `spot_custom_walls`, `spot_wall_cooldowns` in `state.py`
- `save_spot_settings()`, `load_spot_settings()` in `persistence.py`
- **Verification (me):** `python -c "import state; print(state.spot_settings)"` — no errors
- **Verification (you):** restart bot, confirm no import errors

### Sprint 2 — Wall detection core (`walls.py`)
- `market` param in `check_orderbook_walls`
- `spot_wall_candidates` module-level dict
- F/S marker in alert, outside `<code>`
- `state.spot_symbol_volumes` for volume lookup in spot path
- **Verification (me):** call function manually with both markets, assert correct dict access
- **Verification (you):** confirm futures alerts still show F marker, no regressions

### Sprint 3 — Binance Spot WebSocket (`binance.py`)
- `fetch_spot_tickers()` + `state.spot_symbol_volumes`
- `binance_spot_ws_stream()` on `stream.binance.com:9443`
- Intersection logic, both stream types in `run_binance_monitor()`
- **Verification (me):** bot starts, logs show `Binance Spot: N монет`
- **Verification (you):** watch logs for spot stream connections, no crashes

### Sprint 4 — UI (`keyboards.py` + `handlers.py`)
- `settings_type_keyboard()`, `settings_menu_keyboard(market)`
- Фьюч/Спот selector handler, market routing
- `.get("market", "futures")` everywhere
- **Verification (me):** walk full flow in bot: Настройки → Спот → Тиры → change value → confirm futures tiers unchanged
- **Verification (you):** full settings flow test on both markets
