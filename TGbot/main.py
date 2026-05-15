import requests
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import TG_BOT_TOKEN, TG_CHAT_ID
from storage.persistence import load_settings, load_spot_settings, load_volume_history, load_custom_data
from monitor.positions import monitor_loop
from api.binance import binance_thread
from bot.handlers import start, message_handler, railway_command
from bot.noise_report import build_noise_report
from telegram.ext import Application, CommandHandler, MessageHandler, filters


def daily_report_thread():
    warsaw = ZoneInfo("Europe/Warsaw")
    while True:
        now = datetime.now(warsaw)
        target = now.replace(hour=19, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        build_noise_report()


def main():
    load_settings()
    load_spot_settings()
    load_volume_history()
    load_custom_data()
    print("✅ Монитор запущен!")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TG_CHAT_ID, "text": "✅ Бот запущен! Напиши /start", "parse_mode": "HTML"},
            timeout=10,
        )
    except:
        pass

    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=binance_thread, daemon=True).start()
    threading.Thread(target=daily_report_thread, daemon=True).start()

    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("railway", railway_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
