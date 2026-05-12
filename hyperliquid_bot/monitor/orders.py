from api.hyperliquid import get_orders
from utils.formatters import format_order_alert, send_message


def process_wallet_orders(wallet, wallet_name, wallet_orders):
    orders = get_orders(wallet)
    prev_orders = wallet_orders.get(wallet, set())
    current_orders = set()
    for order in orders:
        oid = str(order.get("oid", ""))
        current_orders.add(oid)
        if oid not in prev_orders:
            send_message(format_order_alert(order, wallet, wallet_name))
    wallet_orders[wallet] = current_orders
