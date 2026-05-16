from datetime import datetime
from zoneinfo import ZoneInfo

import state
from utils.formatters import fmt_usd, get_min_wall_usd, send_report

MIN_ALERTS = 10
WARSAW = ZoneInfo("Europe/Warsaw")


def build_noise_report():
    """Строит и отправляет дневной репорт шумных монет. Сбрасывает счётчики."""
    today = datetime.now(WARSAW).strftime("%d.%m.%Y")

    futures_noisy = sorted(
        [(sym, cnt) for sym, cnt in state.alert_counts["futures"].items() if cnt >= MIN_ALERTS],
        key=lambda x: -x[1],
    )
    spot_noisy = sorted(
        [(sym, cnt) for sym, cnt in state.alert_counts["spot"].items() if cnt >= MIN_ALERTS],
        key=lambda x: -x[1],
    )

    if not futures_noisy and not spot_noisy:
        send_report(f"📊 Шумных монет за {today} нет (порог: {MIN_ALERTS}+ алертов)")
        state.alert_counts = {"futures": {}, "spot": {}}
        return

    lines = [f"📊 <b>Шумные монеты за {today}</b>", ""]

    if futures_noisy:
        lines.append("📈 <b>Фьючи:</b>")
        for sym, cnt in futures_noisy:
            vol = state.symbol_volumes.get(sym, 0)
            auto = get_min_wall_usd(vol, "futures")
            custom = state.custom_walls.get(sym)
            threshold = f"кастом {fmt_usd(custom)}" if custom else f"авто {fmt_usd(auto)}"
            lines.append(f"• <code>{sym}</code> — {cnt} алертов (порог: {threshold})")
        lines.append("")

    if spot_noisy:
        lines.append("💰 <b>Спот:</b>")
        for sym, cnt in spot_noisy:
            vol = state.spot_symbol_volumes.get(sym, 0)
            auto = get_min_wall_usd(vol, "spot")
            custom = state.spot_custom_walls.get(sym)
            threshold = f"кастом {fmt_usd(custom)}" if custom else f"авто {fmt_usd(auto)}"
            lines.append(f"• <code>{sym}</code> — {cnt} алертов (порог: {threshold})")
        lines.append("")

    lines.append("👇 Подними порог чтобы заглушить:")

    # Inline keyboard: по 2 кнопки на монету
    keyboard = []
    for sym, _ in futures_noisy:
        keyboard.append([
            {"text": f"{sym} F +25%", "callback_data": f"noise:futures:{sym}:25"},
            {"text": f"{sym} F +50%", "callback_data": f"noise:futures:{sym}:50"},
        ])
    for sym, _ in spot_noisy:
        keyboard.append([
            {"text": f"{sym} S +25%", "callback_data": f"noise:spot:{sym}:25"},
            {"text": f"{sym} S +50%", "callback_data": f"noise:spot:{sym}:50"},
        ])

    keyboard.append([{"text": "▶️ Возобновить алерты", "callback_data": "resume_alerts"}])
    state.alerts_paused = True
    send_report("\n".join(lines), inline_keyboard=keyboard)
    state.alert_counts = {"futures": {}, "spot": {}}
