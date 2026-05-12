import state
from api.hyperliquid import calc_changes


def get_analytics_text(hours_ago, label):
    result = calc_changes(hours_ago)
    if result is None:
        keys = sorted(state.volume_history.keys())
        return f"⏳ Мало данных. Есть {len(keys)} снимков из {hours_ago + 1} нужных."
    msg = f"📊 <b>Изменение объёма за {label}:</b>\n\n"
    for r in result[:15]:
        sign = "+" if r["pct"] > 0 else ""
        msg += f"• {r['coin']}: {sign}{r['pct']:.0f}%\n"
    return msg
