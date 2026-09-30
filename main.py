import os
import time
import asyncio
import logging
from threading import Thread
from flask import Flask
import ccxt.async_support as ccxt
import pandas as pd
import ta
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

@app.route('/')
def home():
    return "Institutional SMC Engine v3.2 (High-Winrate Filters Active)!", 200

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

BTC_CORRELATED_COINS = [
    'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'AVAX/USDT',
    'LINK/USDT', 'SUI/USDT', 'NEAR/USDT', 'APT/USDT', 'POL/USDT', 'DOT/USDT',
    'LTC/USDT', 'ARB/USDT', 'INJ/USDT', 'TIA/USDT', 'OP/USDT', 'RENDER/USDT',
    'SEI/USDT', 'STX/USDT', 'RUNE/USDT', 'AAVE/USDT', 'ICP/USDT', 'FIL/USDT',
    'ATOM/USDT', 'ETC/USDT', 'XLM/USDT', 'UNI/USDT', 'BCH/USDT', 'LDO/USDT',
    'KAS/USDT', 'ONDO/USDT', 'ENA/USDT', 'STRK/USDT', 'TAO/USDT', 'PENDLE/USDT',
    'TON/USDT', 'TRX/USDT', 'FTM/USDT', 'AKT/USDT', 'SNX/USDT'
]

INDEPENDENT_COINS = [
    'DOGE/USDT', 'PEPE/USDT', 'FET/USDT', 'SHIB/USDT', 'WIF/USDT', 'FLOKI/USDT',
    'BONK/USDT', 'GALA/USDT', 'JUP/USDT', 'ORDI/USDT', 'MEME/USDT', 'NOT/USDT',
    'WLD/USDT', 'POPCAT/USDT', 'BRETT/USDT', '1000SATS/USDT'
]

TOP_COINS = BTC_CORRELATED_COINS + INDEPENDENT_COINS

LARGE_CAP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'TON/USDT', 'TRX/USDT',
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'BCH/USDT', 'LTC/USDT',
    'SUI/USDT', 'NEAR/USDT', 'APT/USDT'
]

SENT_SIGNALS = {}
ACTIVE_PAPER_TRADES = []
COOLDOWN_SECONDS = 60 * 60

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN":
        logging.error("Telegram token not configured correctly.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}", flush=True)
        return False

def format_price(price):
    if price is None or price == 0:
        return "0.0"
    if price < 0.0001:
        return f"{price:.8f}"
    elif price < 0.01:
        return f"{price:.6f}"
    elif price < 1.0:
        return f"{price:.4f}"
    else:
        return f"{price:.2f}"

def check_high_impact_news():
    """Gano High-Impact News da ke tafe tare da kariya daga krashewa (Fail-Safe)"""
    try:
        url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&filter=important"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            for post in results[:5]:
                title = post.get('title', '').lower()
                if any(kw in title for kw in ['cpi', 'fomc', 'sec', 'fed rate', 'binance', 'inflation', 'crackdown']):
                    return True, post.get('title')
    except Exception as e:
        print(f"[NEWS CHECK NOTICE] News API bypassed cleanly: {e}", flush=True)
    return False, None
                            if "FUTURE" in signal_type:
                                leverage_text = "⚡ 5x - 10x (Cross / Isolated)"
                            else:
                                leverage_text = "🚫 No Leverage (Spot Buy 1x)"

                            msg = (
                                f"🚨 **HIGH PROBABILITY SIGNAL** 🚨\n\n"
                                f"🪙 **Coin:** {signal_data['symbol']}\n"
                                f"🎯 **Action:** {signal_data['signal_type']}\n"
                                f"📊 **Score:** {signal_data['confidence']}\n\n"
                                f"📥 **Entry Zone:** {signal_data['entry']}\n"
                                f"🛑 **Stop Loss:** {signal_data['sl']}\n"
                                f"🎯 **TP 1:** {signal_data['tp1']}\n"
                                f"🎯 **TP 2:** {signal_data['tp2']}\n"
                                f"🎯 **TP 3:** {signal_data['tp3']}\n\n"
                                f"⚖️️ **Leverage:** {leverage_text}\n\n"
                                f"💡 **Confluence & Confirmations:**\n{reasons_text}"
                            )
                            send_telegram_message(msg)
                            execute_paper_trade(signal_data)

                except Exception as inner_e:
                    print(f"[SCAN ERROR] Failed processing {symbol}: {inner_e}", flush=True)

                await asyncio.sleep(0.3)

            print("=== SCANNER CYCLE COMPLETE - WAITING FOR NEXT LOOP ===", flush=True)
            await asyncio.sleep(120)

        except Exception as e:
            print(f"[CRITICAL ERROR] Scanner loop crashed: {e}. Retrying in 10s...", flush=True)
            await asyncio.sleep(10)

if __name__ == '__main__':
    flask_thread = Thread(target=start_flask, daemon=True)
    flask_thread.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(market_scanner())
    except Exception as fatal_e:
        print(f"[FATAL ERROR] Main event loop died: {fatal_e}", flush=True)
