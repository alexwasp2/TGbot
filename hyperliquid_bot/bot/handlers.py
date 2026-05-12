import state
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from storage.persistence import save_custom_data, save_settings
from utils.formatters import fmt_usd
from bot.keyboards import main_menu_keyboard, back_keyboard, wallets_manage_keyboard, settings_menu_keyboard
from bot.analytics import get_analytics_text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state.user_state.pop(uid, None)
    state.users_in_settings.discard(uid)
    await update.message.reply_text(
        "👋 <b>HyperLiquid монитор</b>\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
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
        state.users_in_settings.add(uid)
        await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
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

    # Настройки
    if text == "🎛 Фильтры":
        s = state.settings
        msg = "⚙️ <b>Фильтры:</b>\n\n"
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
        state.user_state[uid] = {"mode": "filters"}
        return

    if text == "📈 Тиры":
        t = state.settings["tiers"]
        msg = "📈 <b>Тиры по объёму:</b>\n\n"
        for i, tier in enumerate(t):
            wall = f"${tier['min_wall']}K" if tier["min_wall"] < 1000 else f"${tier['min_wall'] // 1000}M"
            msg += f"{i+1}. ${tier['vol_from']}M–${tier['vol_to']}M → {wall}\n"
        msg += "\nОтправь номер для изменения:"
        kb = ReplyKeyboardMarkup([["1", "2", "3"], ["4", "5"], ["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        state.user_state[uid] = {"mode": "tiers"}
        return

    if text == "🎯 Монеты":
        if not state.custom_walls:
            msg = "🎯 Пока нет кастомных монет.\n\nФормат: <code>BTCUSDT 5000000</code>"
        else:
            msg = "🎯 <b>Кастомные монеты:</b>\n\n"
            for sym, wall in state.custom_walls.items():
                msg += f"• {sym}: {fmt_usd(wall)}\n"
            msg += "\nОтправь <code>МОНЕТА 0</code> чтобы удалить"
        kb = ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        state.user_state[uid] = {"mode": "coins"}
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
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        parts = text.upper().split()
        if len(parts) == 2:
            sym, wall_str = parts
            try:
                wall = int(wall_str)
                if wall == 0:
                    state.custom_walls.pop(sym, None)
                    await update.message.reply_text(f"✅ Удалён: {sym}", parse_mode="HTML", reply_markup=settings_menu_keyboard())
                else:
                    state.custom_walls[sym] = wall
                    await update.message.reply_text(f"✅ {sym}: {fmt_usd(wall)}", parse_mode="HTML", reply_markup=settings_menu_keyboard())
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
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        if text in ("📏 Радиус", "⏱ Кулдаун", "📈 Множитель", "📊 Объём"):
            state.user_state[uid] = {"mode": "filters", "type": text}
            await update.message.reply_text("Введи число:", parse_mode="HTML", reply_markup=back_keyboard())
            return
        try:
            val = float(text.replace(",", "."))
            filter_type = state.user_state.get(uid, {}).get("type")
            if filter_type == "📏 Радиус":
                state.settings["price_range_pct"] = val
            elif filter_type == "⏱ Кулдаун":
                state.settings["cooldown_min"] = int(val)
            elif filter_type == "📈 Множитель":
                state.settings["min_multiplier"] = val
            elif filter_type == "📊 Объём":
                state.settings["min_symbol_volume_m"] = val
            save_settings()
            await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            state.user_state.pop(uid, None)
        except:
            await update.message.reply_text("❌ Введи число", parse_mode="HTML", reply_markup=back_keyboard())
        return

    if mode == "tiers":
        if text == "🔙 Назад":
            state.user_state.pop(uid, None)
            await update.message.reply_text("⚙️ <b>Настройки</b>", parse_mode="HTML", reply_markup=settings_menu_keyboard())
            return
        current_idx = state.user_state.get(uid, {}).get("idx")
        if current_idx is not None:
            try:
                val = int(text)
                state.settings["tiers"][current_idx]["min_wall"] = val
                save_settings()
                await update.message.reply_text("✅ Сохранено!", parse_mode="HTML", reply_markup=settings_menu_keyboard())
                state.user_state.pop(uid, None)
            except:
                await update.message.reply_text("❌ Введи целое число (в $K):", parse_mode="HTML", reply_markup=back_keyboard())
        else:
            try:
                tier_num = int(text) - 1
                if 0 <= tier_num < len(state.settings["tiers"]):
                    state.user_state[uid] = {"mode": "tiers", "idx": tier_num}
                    await update.message.reply_text("Введи мин. стену в $K:", parse_mode="HTML", reply_markup=back_keyboard())
                else:
                    await update.message.reply_text(
                        f"❌ Неверный номер. Введи от 1 до {len(state.settings['tiers'])}:",
                        parse_mode="HTML",
                        reply_markup=back_keyboard(),
                    )
            except:
                await update.message.reply_text(
                    f"❌ Введи номер тира (1–{len(state.settings['tiers'])}):",
                    parse_mode="HTML",
                    reply_markup=back_keyboard(),
                )
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
