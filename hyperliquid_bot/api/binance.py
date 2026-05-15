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
        print(f"Binance Futures: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance ticker ошибка: {e}")
        return []


def fetch_spot_tickers():
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15)
        data = r.json()
        symbols = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            vol = float(item.get("quoteVolume", 0))
            if vol > 0:
                state.spot_symbol_volumes[sym] = vol
            symbols.append(sym)
        print(f"Binance Spot: {len(symbols)} USDT монет")
        return symbols
    except Exception as e:
        print(f"Binance spot ticker ошибка: {e}")
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
                    check_orderbook_walls(symbol, data.get("b", []), data.get("a", []), market="futures")
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS фьюч ошибка {symbol}: {e}")
            await asyncio.sleep(5)


async def binance_spot_ws_stream(symbol):
    url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@depth20@100ms"
    error_count = 0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                error_count = 0
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    check_orderbook_walls(symbol, data.get("bids", []), data.get("asks", []), market="spot")
        except Exception as e:
            error_count += 1
            if error_count == 1:
                print(f"WS спот ошибка {symbol}: {e}")
            await asyncio.sleep(5)


async def run_binance_monitor():
    futures_symbols = fetch_binance_tickers()
    spot_symbols = fetch_spot_tickers()
    if not futures_symbols and not spot_symbols:
        return

    both = set(futures_symbols) & set(spot_symbols)
    print(f"Binance: {len(futures_symbols)} фьюч + {len(both)} спот стримов")

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": f"🔥 Binance стакан: {len(futures_symbols)} фьюч + {len(both)} спот монет",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except:
        pass

    tasks = [asyncio.create_task(binance_ws_stream(s)) for s in futures_symbols]
    tasks += [asyncio.create_task(binance_spot_ws_stream(s)) for s in both]
    await asyncio.gather(*tasks)


def binance_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_binance_monitor())
