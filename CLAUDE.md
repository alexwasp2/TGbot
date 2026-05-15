# HyperLiquid Tgbot — CLAUDE.md

## Правила поведения

**Перед любым действием, требующим разрешения пользователя** (запись файлов, git-операции, запуск процессов, сетевые запросы, удаление и т.п.) — воспроизводи системный звук:

```powershell
# Windows (PowerShell)
[System.Media.SystemSounds]::Beep.Play()
```

```python
# Python (кросс-платформенно)
import winsound; winsound.MessageBeep()  # Windows
# import os; os.system("afplay /System/Library/Sounds/Tink.aiff")  # macOS
# import os; os.system("paplay /usr/share/sounds/freedesktop/stereo/bell.oga")  # Linux
```

Звук должен воспроизводиться **до** отображения запроса на подтверждение, не после.

## Запуск

```bash
cd TGbot
python main.py
```

Зависимости: `uv sync` или `pip install -r requirements.txt`.  
Переменные окружения: `TG_BOT_TOKEN`, `TG_CHAT_ID`, `WALLET`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `RAILWAY_TOKEN`, `RAILWAY_SERVICE_ID`, `RAILWAY_ENVIRONMENT_ID`, `ADMIN_ID`.

---

## Карта файлов — что трогать для каких задач

### Логика Telegram-бота (команды, кнопки, меню)
- `TGbot/bot/handlers.py` — все обработчики сообщений и команд (`/start`, `/railway`, весь `message_handler`). Добавить новую кнопку / команду — сюда.
- `TGbot/bot/keyboards.py` — ReplyKeyboard-раскладки. Изменить кнопки меню — сюда.
- `TGbot/main.py` — регистрация хэндлеров в `Application`, запуск потоков мониторинга. Добавить новую `/command` — регистрировать здесь.

### Аналитика и отображение данных
- `TGbot/bot/analytics.py` — текст аналитики объёмов (функция `get_analytics_text`). Изменить формат вывода аналитики — сюда.
- `TGbot/utils/formatters.py` — все форматеры (`fmt_usd`, `fmt_val`, `format_position_alert`, `format_order_alert`, `send_message`). Изменить формат алертов или логику отправки — сюда.

### Мониторинг позиций и ордеров
- `TGbot/monitor/positions.py` — основной цикл `monitor_loop`: следит за позициями кошельков, отправляет алерты при открытии/изменении/закрытии. Порог `MIN_SIZE_USD`, `MIN_CHANGE_USD` — в `config.py`.
- `TGbot/monitor/orders.py` — следит за новыми ордерами кошельков. Изменить логику алертов ордеров — сюда.
- `TGbot/monitor/walls.py` — детект стен в стакане через Binance WebSocket. Логика порогов, тиков, кулдаунов — здесь.

### API — внешние запросы
- `TGbot/api/hyperliquid.py` — все запросы к HyperLiquid API (`/info`): позиции, ордера, объёмы, fills. Сломался HL API — идти сюда.
- `TGbot/api/binance.py` — Binance Futures WebSocket + REST (тикеры объёмов, подписка на стаканы). Проблема с WebSocket стаканами — идти сюда.
- `TGbot/api/railway.py` — GraphQL-запросы к Railway API (stop/start сервиса). Проблема с `/railway` командой — идти сюда.

### Хранение данных
- `TGbot/storage/redis_client.py` — низкоуровневый клиент Upstash Redis (REST API). Проблема с подключением к Redis — идти сюда.
- `TGbot/storage/persistence.py` — загрузка/сохранение настроек, истории объёмов, custom_walls — сначала Redis, fallback на локальные JSON-файлы. Данные не сохраняются или не загружаются — идти сюда.

### Настройки и конфигурация
- `TGbot/config.py` — все переменные окружения, дефолтные значения (`MIN_SIZE_USD`, `CHECK_INTERVAL`, `DEFAULT_SETTINGS` с тирами). Изменить дефолтные пороги или добавить новую env-переменную — сюда.
- `TGbot/state.py` — глобальное in-memory состояние (`settings`, `watched_wallets`, `volume_history`, `user_state` и др.). Добавить новое глобальное поле — сюда.

---

## Архитектура потоков

```
main.py
  ├── threading: monitor_loop()       ← monitor/positions.py (HL API каждые 30с)
  ├── threading: binance_thread()     ← api/binance.py (WebSocket стаканы)
  └── Application.run_polling()       ← bot/handlers.py (Telegram polling)
```

Все три потока работают параллельно. `state.py` — общая память между потоками (без блокировок, race condition возможен при записи).

---

## Персистентность

Настройки и данные сохраняются двойным образом: сначала в **Upstash Redis** (REST), при недоступности — в локальные JSON-файлы (`settings.json`, `volume_history.json`, `custom_data.json`). При старте `load_settings()` пробует Redis, потом файл, потом дефолты.
