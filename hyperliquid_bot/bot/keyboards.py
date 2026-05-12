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


def settings_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🎛 Фильтры", "📈 Тиры"],
        ["🎯 Монеты", "🔙 Назад"],
    ], resize_keyboard=True)


def railway_keyboard():
    return ReplyKeyboardMarkup([
        ["⛔ Остановить деплой"],
        ["▶️ Запустить деплой"],
        ["🔙 Назад"],
    ], resize_keyboard=True)
