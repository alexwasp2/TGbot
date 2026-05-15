import state
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_ID
from storage.persistence import save_custom_data, save_settings, save_spot_settings
from utils.formatters import fmt_usd, get_min_wall_usd
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
            vol_to = "∞" if tier["vol_to"] >= 999999 else f"${tier['vol_to']}M"
            msg += f"{i+1}. ${tier['vol_from']}M–{vol_to} → {wall}\n"
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


async def noise_raise_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, market, symbol, pct_str = query.data.split(":")
    except ValueError:
        await query.answer("Неизвестная команда")
        return

    pct = int(pct_str) / 100
    custom = state.spot_custom_walls if market == "spot" else state.custom_walls
    volumes = state.spot_symbol_volumes if market == "spot" else state.symbol_volumes

    vol = volumes.get(symbol, 0)
    current = custom.get(symbol, get_min_wall_usd(vol, market))
    new_val = round(current * (1 + pct))
    custom[symbol] = new_val

    from storage.persistence import save_custom_data
    save_custom_data()

    market_label = "Спот" if market == "spot" else "Фьюч"
    await query.answer(
        f"✅ {symbol} ({market_label}): {fmt_usd(current)} → {fmt_usd(new_val)}",
        show_alert=True,
    )
