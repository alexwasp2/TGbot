import time

import state
from config import MIN_SIZE_USD, MIN_CHANGE_USD, CHECK_INTERVAL, VOLUME_SAVE_INTERVAL
from api.hyperliquid import get_positions, get_last_position_size
from storage.persistence import save_volume_snapshot
from utils.formatters import parse_position, format_position_alert, send_message
from monitor.orders import process_wallet_orders


def monitor_loop():
    wallet_positions = {}
    wallet_orders = {}
    last_volume_save = 0

    while True:
        try:
            if time.time() - last_volume_save > VOLUME_SAVE_INTERVAL:
                save_volume_snapshot()
                last_volume_save = time.time()

            for wallet, wallet_name in list(state.watched_wallets.items()):
                try:
                    positions = get_positions(wallet)
                    current = {}
                    for pos in positions:
                        p = parse_position(pos)
                        if p["value"] < MIN_SIZE_USD:
                            continue
                        current[p["coin"]] = p

                    prev = wallet_positions.get(wallet, {})
                    for coin, p in current.items():
                        if coin not in prev:
                            last_size = get_last_position_size(coin, wallet)
                            send_message(format_position_alert(p, "new", wallet, wallet_name, last_size))
                        else:
                            diff = abs(p["value"] - prev[coin]["value"])
                            if diff >= MIN_CHANGE_USD:
                                send_message(format_position_alert(p, "changed", wallet, wallet_name))
                    for coin in prev:
                        if coin not in current:
                            send_message(format_position_alert(prev[coin], "closed", wallet, wallet_name))
                    wallet_positions[wallet] = current

                    process_wallet_orders(wallet, wallet_name, wallet_orders)

                except Exception as e:
                    print(f"Ошибка кошелька {wallet_name}: {e}")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Ошибка HL: {e}")
            time.sleep(60)
