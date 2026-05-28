# Volume Spike Monitor — Design Spec
Date: 2026-05-28

## Overview

Add a volume spike monitor to the existing Python Telegram bot. The monitor watches Hyperliquid Futures 24h volume every N minutes, detects coins with significant growth, and sends Telegram alerts. All thresholds are configurable via the bot's menu.

## Architecture

New module `monitor/volume_spikes.py` runs as a dedicated daemon thread started in `main.py`, following the same pattern as `monitor/walls.py`. The thread polls `get_hl_volume_data()` (already exists in `api/hyperliquid.py`) on a configurable interval and stores snapshots in an in-memory ring buffer.

### Files changed

| File | Change |
|------|--------|
| `monitor/volume_spikes.py` | **New** — spike detection loop |
| `state.py` | Add `spike_settings`, `spike_snapshots`, `spike_cooldowns` |
| `config.py` | Add default constants for spike settings |
| `storage/persistence.py` | Add `load_spike_settings` / `save_spike_settings` |
| `bot/handlers.py` | Add handlers for spike settings menu |
| `bot/keyboards.py` | Add spike settings keyboard |
| `main.py` | Register new daemon thread |

## State

```python
# state.py additions
import collections

spike_settings = {
    "enabled": True,
    "threshold_pct": 50,    # alert if volume grew by this %
    "interval_sec": 300,    # polling interval in seconds
    "min_volume_m": 10,     # minimum 24h volume in $M to consider
    "cooldown_min": 30,     # silence per-coin after alert, in minutes
}

spike_snapshots = collections.deque(maxlen=12)
# each entry: {"timestamp": float, "volumes": {"BTC": 1_200_000_000, ...}}

spike_cooldowns = {}
# structure: {"BTC": 1748123456.0}  — timestamp of last alert per coin
```

## Monitoring Logic (`monitor/volume_spikes.py`)

```
loop every interval_sec:
  if not spike_settings["enabled"]: sleep; continue
  snapshot = get_hl_volume_data()
  spike_snapshots.append({"timestamp": now, "volumes": snapshot})
  if len(spike_snapshots) < 2: continue  # skip first iteration

  prev = spike_snapshots[-2]["volumes"]
  curr = spike_snapshots[-1]["volumes"]

  for coin, vol_curr in curr.items():
    if vol_curr < min_volume_m * 1_000_000: skip
    if coin not in prev: skip
    pct = (vol_curr - prev[coin]) / prev[coin] * 100
    if pct < threshold_pct: skip
    if time.time() - spike_cooldowns.get(coin, 0) < cooldown_sec: skip
    send_alert(coin, prev[coin], vol_curr, pct)
    spike_cooldowns[coin] = time.time()
```

## Alert Format

```
📈 Volume Spike: BTC +73%
24h Vol: $1.2B → $2.1B
```

Sent via existing `send_message()` from `utils/formatters.py`.

## Persistence

`spike_settings` is saved/loaded via `persistence.py` following the same Redis-first, JSON-fallback pattern as `spot_settings`. Key: `spike_settings`. File: `spike_settings.json`.

`spike_snapshots` and `spike_cooldowns` are in-memory only — no persistence needed.

## Bot Menu

New button **"📈 Спайки объёма"** added to the main keyboard in `keyboards.py`.

Pressing it shows current settings with two action buttons:
- **⏸ Выключить / ▶️ Включить** — toggle enabled
- **🔧 Настроить** — enter settings flow

Settings flow uses existing `user_state` pattern: bot asks each field one at a time (threshold → interval → min_volume → cooldown), user types a number, bot saves and confirms.

## Config Defaults (`config.py`)

```python
SPIKE_THRESHOLD_PCT = 50
SPIKE_INTERVAL_SEC  = 300
SPIKE_MIN_VOLUME_M  = 10
SPIKE_COOLDOWN_MIN  = 30
```

## Edge Cases

- **First snapshot**: skipped — `len(spike_snapshots) < 2`
- **Coin missing from prev snapshot**: skipped — new listing or API gap
- **prev[coin] == 0**: skipped — avoids division by zero
- **Bot restart**: snapshots reset to empty, cooldowns reset; first alert per coin fires after two intervals
- **API error**: log and sleep, do not crash thread

## Out of Scope

- Spot market (Futures only)
- Negative spikes / volume drops
- Persistent cooldowns across restarts
