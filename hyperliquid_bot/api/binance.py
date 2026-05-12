import asyncio
import json

import requests
import websockets

import state
from config import TG_BOT_TOKEN, TG_CHAT_ID
from monitor.walls import check_orderbook_walls


def fetch_binance_tickers():
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=15)
        data = r.json()
        symbols = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            vol = float(item.get("quoteVolume", 0))
            if vol > 0:
                state.symbol_volumes[sym] = vol
            symbols.append(sym)
        print(f"Binance: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance ticker ошибка: {e}")
        return []


async def binance_ws_stream(symbol):
    url = f"wss://fstream.binance.com/ws/{symbol.lower()}@depth20@100ms"
    error_count = 0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                error_count = 0
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    check_orderbook_walls(symbol, data.get("b", []), data.get("a", []))
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS ошибка {symbol}: {e}")
            await asyncio.sleep(5)


async def run_binance_monitor():
    symbols = fetch_binance_tickers()
    if not symbols:
        return
    print(f"Binance: запускаю {len(symbols)} WS стримов")
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TG_CHAT_ID, "text": f"🔥 Binance стакан: {len(symbols)} монет", "parse_mode": "HTML"},
            timeout=10,
        )
    except:
        pass
    await asyncio.gather(*[asyncio.create_task(binance_ws_stream(s)) for s in symbols])


def binance_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_binance_monitor())
