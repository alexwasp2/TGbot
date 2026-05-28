# Volume Spike Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Futures volume spike monitor to the existing Python Telegram bot — detects coins with >N% 24h volume growth every M minutes and sends alerts, fully configurable via the bot's menu.

**Architecture:** New daemon thread `volume_spike_thread()` in `monitor/volume_spikes.py` polls `get_hl_volume_data()` on a configurable interval, stores snapshots in a `collections.deque(maxlen=12)` ring buffer protected by a `threading.Lock`, and calls `detect_spikes()` (pure function, testable in isolation). Settings persisted to Redis + JSON file via `persistence.py` following the existing `spot_settings` pattern. Bot menu added as new section in `handlers.py`/`keyboards.py`.

**Tech Stack:** Python, python-telegram-bot, Upstash Redis REST, pytest

---

### Task 1: Config defaults

**Files:**
- Modify: `TGbot/config.py`

- [ ] **Step 1: Add spike constants to config.py**

Open `TGbot/config.py` and append after the `DEFAULT_SPOT_SETTINGS` block:

```python
SPIKE_SETTINGS_FILE = "spike_settings.json"
SPIKE_THRESHOLD_PCT = 50
SPIKE_INTERVAL_SEC  = 300
SPIKE_MIN_VOLUME_M  = 10
SPIKE_COOLDOWN_MIN  = 30
```

- [ ] **Step 2: Verify the file parses**

```
cd TGbot
python -c "from config import SPIKE_THRESHOLD_PCT, SPIKE_INTERVAL_SEC, SPIKE_MIN_VOLUME_M, SPIKE_COOLDOWN_MIN, SPIKE_SETTINGS_FILE; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```
git add TGbot/config.py
git commit -m "feat(spikes): add spike config defaults"
```

---

### Task 2: State variables

**Files:**
- Modify: `TGbot/state.py`

- [ ] **Step 1: Add spike state to state.py**

Open `TGbot/state.py` and add at the top (after the existing imports) and at the bottom (after the existing variables):

```python
# At the top, add:
import collections
import threading
```

Then append at the end of `TGbot/state.py`:

```python
spike_settings = {
    "enabled": True,
    "threshold_pct": 50,
    "interval_sec": 300,
    "min_volume_m": 10,
    "cooldown_min": 30,
}
spike_snapshots = collections.deque(maxlen=12)
spike_cooldowns = {}
spike_lock = threading.Lock()
```

- [ ] **Step 2: Verify**

```
python -c "import state; print(state.spike_settings, type(state.spike_snapshots), type(state.spike_lock))"
```

Expected: `{'enabled': True, ...} <class 'collections.deque'> <class '_thread.lock'>`

- [ ] **Step 3: Commit**

```
git add TGbot/state.py
git commit -m "feat(spikes): add spike_settings, spike_snapshots, spike_cooldowns, spike_lock to state"
```

---

### Task 3: Persistence

**Files:**
- Modify: `TGbot/storage/persistence.py`

- [ ] **Step 1: Add load_spike_settings and save_spike_settings**

Open `TGbot/storage/persistence.py`. Add to the imports at the top:

```python
from config import DEFAULT_SETTINGS, DEFAULT_SPOT_SETTINGS, TIER_RANGES, SETTINGS_FILE, SPOT_SETTINGS_FILE, VOLUME_FILE, CUSTOM_DATA_FILE, SPIKE_SETTINGS_FILE, SPIKE_THRESHOLD_PCT, SPIKE_INTERVAL_SEC, SPIKE_MIN_VOLUME_M, SPIKE_COOLDOWN_MIN
```

Then append these two functions at the end of the file:

```python
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
```

- [ ] **Step 2: Verify**

```
python -c "from storage.persistence import load_spike_settings, save_spike_settings; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```
git add TGbot/storage/persistence.py
git commit -m "feat(spikes): add load/save spike_settings to persistence"
```

---

### Task 4: Spike monitor — logic + tests

**Files:**
- Create: `TGbot/monitor/volume_spikes.py`
- Create: `TGbot/tests/__init__.py`
- Create: `TGbot/tests/test_volume_spikes.py`

- [ ] **Step 1: Write the failing tests**

Create `TGbot/tests/__init__.py` (empty file).

Create `TGbot/tests/test_volume_spikes.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitor.volume_spikes import detect_spikes


def test_spike_above_threshold():
    prev = {"BTC": 1_000_000_000, "ETH": 500_000_000}
    curr = {"BTC": 1_600_000_000, "ETH": 520_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert len(results) == 1
    assert results[0]["coin"] == "BTC"
    assert abs(results[0]["pct"] - 60.0) < 0.01
    assert results[0]["vol_prev"] == 1_000_000_000
    assert results[0]["vol_curr"] == 1_600_000_000


def test_spike_below_threshold_excluded():
    prev = {"BTC": 1_000_000_000}
    curr = {"BTC": 1_300_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_below_min_volume_excluded():
    prev = {"SMALL": 5_000_000}
    curr = {"SMALL": 10_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_zero_prev_volume_skipped():
    prev = {"BTC": 0}
    curr = {"BTC": 1_000_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_coin_missing_from_prev_skipped():
    prev = {}
    curr = {"BTC": 1_000_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []
```

- [ ] **Step 2: Run tests — verify they fail**

```
cd TGbot
python -m pytest tests/test_volume_spikes.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` (file doesn't exist yet).

- [ ] **Step 3: Create monitor/volume_spikes.py**

Create `TGbot/monitor/volume_spikes.py`:

```python
import time

import state
from api.hyperliquid import get_hl_volume_data
from utils.formatters import fmt_usd, send_message


def detect_spikes(prev: dict, curr: dict, settings: dict) -> list:
    min_vol = settings["min_volume_m"] * 1_000_000
    threshold = settings["threshold_pct"]
    results = []
    for coin, vol_curr in curr.items():
        if vol_curr < min_vol:
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
```

- [ ] **Step 4: Run tests — verify they pass**

```
cd TGbot
python -m pytest tests/test_volume_spikes.py -v
```

Expected:
```
test_volume_spikes.py::test_spike_above_threshold PASSED
test_volume_spikes.py::test_spike_below_threshold_excluded PASSED
test_volume_spikes.py::test_spike_below_min_volume_excluded PASSED
test_volume_spikes.py::test_spike_zero_prev_volume_skipped PASSED
test_volume_spikes.py::test_spike_coin_missing_from_prev_skipped PASSED
5 passed
```

- [ ] **Step 5: Commit**

```
git add TGbot/monitor/volume_spikes.py TGbot/tests/__init__.py TGbot/tests/test_volume_spikes.py
git commit -m "feat(spikes): add detect_spikes logic and volume_spike_thread"
```

---

### Task 5: Bot keyboard

**Files:**
- Modify: `TGbot/bot/keyboards.py`

- [ ] **Step 1: Add spike_menu_keyboard and update main_menu_keyboard**

Open `TGbot/bot/keyboards.py`. Replace `main_menu_keyboard`:

```python
def main_menu_keyboard():
    pause_label = "▶️ Возобновить" if state.alerts_paused else "⏸ Пауза"
    return ReplyKeyboardMarkup([
        ["📊 Аналитика", "⚙️ Настройки"],
        ["👛 Кошельки", "📈 Спайки"],
        [pause_label],
    ], resize_keyboard=True)
```

Then append at the end of `TGbot/bot/keyboards.py`:

```python
def spike_menu_keyboard():
    toggle = "⏸ Выключить спайки" if state.spike_settings.get("enabled", True) else "▶️ Включить спайки"
    return ReplyKeyboardMarkup([
        [toggle],
        ["🎯 Порог", "⏱ Интервал"],
        ["📊 Мин. объём", "🕐 Кулдаун"],
        ["🔙 Назад"],
    ], resize_keyboard=True)
```

- [ ] **Step 2: Verify**

```
python -c "import state; from bot.keyboards import main_menu_keyboard, spike_menu_keyboard; print(main_menu_keyboard()); print(spike_menu_keyboard())"
```

Expected: two keyboard objects printed without errors.

- [ ] **Step 3: Commit**

```
git add TGbot/bot/keyboards.py
git commit -m "feat(spikes): add spike_menu_keyboard, update main_menu_keyboard"
```

---

### Task 6: Bot handlers

**Files:**
- Modify: `TGbot/bot/handlers.py`

- [ ] **Step 1: Update imports in handlers.py**

In `TGbot/bot/handlers.py`, update the `storage.persistence` import line to:

```python
from storage.persistence import save_custom_data, save_settings, save_spot_settings, save_spike_settings
```

Update the `bot.keyboards` import line to:

```python
from bot.keyboards import (
    main_menu_keyboard, back_keyboard, wallets_manage_keyboard,
    settings_type_keyboard, settings_menu_keyboard, railway_keyboard,
    spike_menu_keyboard,
)
```

- [ ] **Step 2: Add "📈 Спайки" handler in message_handler**

In `TGbot/bot/handlers.py`, find the block that handles `if text == "👛 Кошельки":` and add the spike handler immediately after it (before the `if text in ("⏸ Пауза", ...):` block):

```python
    if text == "📈 Спайки":
        state.user_state.pop(uid, None)
        state.users_in_settings.discard(uid)
        s = state.spike_settings
        status = "✅ Включён" if s.get("enabled", True) else "⏸ Выключен"
        msg = (
            f"📈 <b>Volume Spikes</b>\n\n"
            f"Статус: {status}\n"
            f"Порог: {s['threshold_pct']}%\n"
            f"Интервал: {s['interval_sec']}с\n"
            f"Мин. объём: ${s['min_volume_m']}M\n"
            f"Кулдаун: {s['cooldown_min']} мин"
        )
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=spike_menu_keyboard())
        state.user_state[uid] = {"mode": "spike_menu"}
        return
```

- [ ] **Step 3: Add spike_menu mode handler**

In `TGbot/bot/handlers.py`, find the block `if mode == "railway":` and add the spike mode handlers immediately before it:

```python
    if mode == "spike_menu":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("👋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return
        if text in ("⏸ Выключить спайки", "▶️ Включить спайки"):
            state.spike_settings["enabled"] = not state.spike_settings.get("enabled", True)
            save_spike_settings()
            s = state.spike_settings
            status = "✅ Включён" if s["enabled"] else "⏸ Выключен"
            msg = (
                f"📈 <b>Volume Spikes</b>\n\n"
                f"Статус: {status}\n"
                f"Порог: {s['threshold_pct']}%\n"
                f"Интервал: {s['interval_sec']}с\n"
                f"Мин. объём: ${s['min_volume_m']}M\n"
                f"Кулдаун: {s['cooldown_min']} мин"
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=spike_menu_keyboard())
            return
        prompts = {
            "🎯 Порог":      ("threshold_pct", f"Введи порог роста в %\n(текущий: {state.spike_settings['threshold_pct']}%)"),
            "⏱ Интервал":   ("interval_sec",  f"Введи интервал в секундах\n(текущий: {state.spike_settings['interval_sec']}с)"),
            "📊 Мин. объём": ("min_volume_m",  f"Введи мин. 24h объём в $M\n(текущий: ${state.spike_settings['min_volume_m']}M)"),
            "🕐 Кулдаун":   ("cooldown_min",  f"Введи кулдаун в минутах\n(текущий: {state.spike_settings['cooldown_min']} мин)"),
        }
        if text in prompts:
            key, prompt = prompts[text]
            state.user_state[uid] = {"mode": "spike_setting", "key": key}
            await update.message.reply_text(prompt, parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "spike_setting":
        key = state.user_state.get(uid, {}).get("key")
        if text == "🔙 Назад":
            state.user_state[uid] = {"mode": "spike_menu"}
            s = state.spike_settings
            status = "✅ Включён" if s.get("enabled", True) else "⏸ Выключен"
            msg = (
                f"📈 <b>Volume Spikes</b>\n\n"
                f"Статус: {status}\n"
                f"Порог: {s['threshold_pct']}%\n"
                f"Интервал: {s['interval_sec']}с\n"
                f"Мин. объём: ${s['min_volume_m']}M\n"
                f"Кулдаун: {s['cooldown_min']} мин"
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=spike_menu_keyboard())
            return
        try:
            val = float(text.replace(",", "."))
            if key in ("threshold_pct", "cooldown_min", "interval_sec"):
                val = int(val)
            state.spike_settings[key] = val
            save_spike_settings()
            state.user_state[uid] = {"mode": "spike_menu"}
            s = state.spike_settings
            status = "✅ Включён" if s.get("enabled", True) else "⏸ Выключен"
            msg = (
                f"✅ Сохранено!\n\n"
                f"📈 <b>Volume Spikes</b>\n\n"
                f"Статус: {status}\n"
                f"Порог: {s['threshold_pct']}%\n"
                f"Интервал: {s['interval_sec']}с\n"
                f"Мин. объём: ${s['min_volume_m']}M\n"
                f"Кулдаун: {s['cooldown_min']} мин"
            )
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=spike_menu_keyboard())
        except ValueError:
            await update.message.reply_text("❌ Введи число", parse_mode="HTML", reply_markup=back_keyboard())
        return
```

- [ ] **Step 4: Verify the file parses**

```
python -c "import ast; ast.parse(open('bot/handlers.py').read()); print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```
git add TGbot/bot/handlers.py
git commit -m "feat(spikes): add spike settings menu to bot handlers"
```

---

### Task 7: Wire up in main.py

**Files:**
- Modify: `TGbot/main.py`

- [ ] **Step 1: Import and register spike thread + load settings**

In `TGbot/main.py`, add to the imports:

```python
from monitor.volume_spikes import volume_spike_thread
from storage.persistence import load_settings, load_spot_settings, load_volume_history, load_custom_data, load_spike_settings
```

(Replace the existing `load_settings, load_spot_settings, load_volume_history, load_custom_data` import with the line above.)

In the `main()` function, add `load_spike_settings()` right after `load_custom_data()`:

```python
    load_settings()
    load_spot_settings()
    load_volume_history()
    load_custom_data()
    load_spike_settings()
```

Add the spike thread right after the other threads:

```python
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=binance_thread, daemon=True).start()
    threading.Thread(target=daily_report_thread, daemon=True).start()
    threading.Thread(target=volume_spike_thread, daemon=True).start()
```

- [ ] **Step 2: Verify main.py parses**

```
python -c "import ast; ast.parse(open('main.py').read()); print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Run all tests one final time**

```
python -m pytest tests/ -v
```

Expected: 5 passed, 0 failed.

- [ ] **Step 4: Commit**

```
git add TGbot/main.py
git commit -m "feat(spikes): wire up volume_spike_thread and load_spike_settings in main"
```

---

## Self-Review

**Spec coverage:**
- ✅ New daemon thread in `monitor/volume_spikes.py`
- ✅ `detect_spikes()` pure function with 5 tests
- ✅ `spike_settings`, `spike_snapshots`, `spike_cooldowns`, `spike_lock` in state
- ✅ Config defaults in `config.py`
- ✅ Redis-first persistence in `persistence.py`
- ✅ Bot menu with toggle + 4 configurable fields
- ✅ Division by zero guard (`vol_prev == 0`)
- ✅ Thread safety (`spike_lock`)
- ✅ API error handling (`try/except` in thread loop)
- ✅ First-snapshot skip (`len(spike_snapshots) < 2`)
- ✅ Per-coin cooldown

**Placeholder scan:** No TBDs, no "implement later", all code blocks complete.

**Type consistency:**
- `detect_spikes` returns `list` of `{"coin", "vol_prev", "vol_curr", "pct"}` — used identically in `_send_spike_alert` and tests ✅
- `spike_settings` keys (`threshold_pct`, `interval_sec`, `min_volume_m`, `cooldown_min`) consistent across state, config, persistence, handlers, keyboards ✅
