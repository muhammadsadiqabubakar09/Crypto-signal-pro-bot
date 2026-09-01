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

# --- FLASK WEBSERVER FOR RENDER PORT BINDING ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Precision SMC Crypto Signal Engine is Active!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# TOP HIGH-VOLUME COINS FOR DAY TRADING & SCALPING
TOP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT',
    'LINK/USDT', 'SUI/USDT', 'NEAR/USDT', 'PEPE/USDT', 'FET/USDT', 'APT/USDT', 'POL/USDT', 'DOT/USDT',
    'LTC/USDT', 'SHIB/USDT', 'ARB/USDT', 'INJ/USDT', 'TIA/USDT', 'OP/USDT', 'RENDER/USDT', 'WIF/USDT',
    'FLOKI/USDT', 'BONK/USDT', 'SEI/USDT', 'STX/USDT', 'GALA/USDT', 'RUNE/USDT', 'AAVE/USDT', 'ICP/USDT',
    'FIL/USDT', 'ATOM/USDT', 'ETC/USDT', 'XLM/USDT', 'UNI/USDT', 'BCH/USDT', 'LDO/USDT', 'KAS/USDT',
    'JUP/USDT', 'ORDI/USDT', 'MEME/USDT', 'NOT/USDT', 'WLD/USDT', 'ONDO/USDT', 'ENA/USDT', 'STRK/USDT'
]

SENT_SIGNALS = {}
COOLDOWN_SECONDS = 45 * 60  # 45 Minutes Cooldown per coin to avoid duplicates

def send_telegram_message(message):
    """Safely send messages to Telegram"""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN":
        logging.error("Telegram token not configured correctly.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}", flush=True)
        return False

async def fetch_ohlcv(mexc, gate, symbol, timeframe, limit=100):
    """Fetch Candlestick Data safely"""
    try:
        data = await mexc.fetch_ohlcv(symbol, timeframe, limit=limit)
        if data and len(data) > 0:
            return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception:
        pass
        
    try:
        data = await gate.fetch_ohlcv(symbol, timeframe, limit=limit)
        if data and len(data) > 0:
            return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception:
        pass

    return None

async def check_order_book_depth(mexc, gate, symbol):
    """Check Order Book Depth Pressure"""
    try:
        order_book = await mexc.fetch_order_book(symbol, limit=20)
        return sum([b[1] for b in order_book['bids']]), sum([a[1] for a in order_book['asks']])
    except Exception:
        try:
            order_book = await gate.fetch_order_book(symbol, limit=20)
            return sum([b[1] for b in order_book['bids']]), sum([a[1] for a in order_book['asks']])
        except Exception:
            return 0, 0

async def analyze_market(mexc, gate, symbol):
    """High-Probability SMC Structure & Confluence Engine"""
    df_4h = await fetch_ohlcv(mexc, gate, symbol, '4h', limit=50)
    df_1h = await fetch_ohlcv(mexc, gate, symbol, '1h', limit=50)
    df_15m = await fetch_ohlcv(mexc, gate, symbol, '15m', limit=50)
    df_5m = await fetch_ohlcv(mexc, gate, symbol, '5m', limit=50)

    if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
        return None

    # Trend Determination (EMA 200 & EMA 50)
    df_4h['EMA_200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)

    close_4h = df_4h.iloc[-1]['close']
    ema_200_4h = df_4h.iloc[-1]['EMA_200'] if not pd.isna(df_4h.iloc[-1]['EMA_200']) else df_4h['close'].mean()
    close_1h, ema_50_1h = df_1h.iloc[-1]['close'], df_1h.iloc[-1]['EMA_50']

    # Strong Support & Resistance (HTF - 4H/1H)
    strong_support = min(df_4h['low'].tail(15).min(), df_1h['low'].tail(15).min())
    strong_resistance = max(df_4h['high'].tail(15).max(), df_1h['high'].tail(15).max())

    # Minor Support/Resistance & Order Block Detection (LTF - 15m)
    minor_support = df_15m['low'].tail(15).min()
    minor_resistance = df_15m['high'].tail(15).max()

    # Indicators (15m & 5m)
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()
    df_5m['RSI'] = ta.momentum.rsi(df_5m['close'], window=14)

    last_15m = df_15m.iloc[-1]
    last_5m = df_5m.iloc[-1]
    close_price, atr = last_15m['close'], last_15m['ATR']

    # Proximity Calculations
    at_strong_supp = (close_price - strong_support) / close_price < 0.008
    at_minor_supp = (close_price - minor_support) / close_price < 0.005
    at_strong_res = (strong_resistance - close_price) / close_price < 0.008
    at_minor_res = (minor_resistance - close_price) / close_price < 0.005

    bids_vol, asks_vol = await check_order_book_depth(mexc, gate, symbol)

    confidence_score = 0
    reasons = []
    signal_type = None

    # --- BUY / LONG SETUP ---
    if close_1h > ema_50_1h or close_4h > ema_200_4h:
        confidence_score += 20
        reasons.append("Trend: HTF Bullish Structure")

        if at_strong_supp:
            confidence_score += 30
            reasons.append("Structure: Testing Strong Support Zone (4H/1H)")
        elif at_minor_supp:
            confidence_score += 20
            reasons.append("Structure: Testing Minor Support / 15m Bullish Order Block")

        # RSI Filter (30 - 40 Support Zone)
        if 30 <= last_15m['RSI'] <= 42 or 30 <= last_5m['RSI'] <= 42:
            confidence_score += 20
            reasons.append(f"RSI Support Zone: 15m RSI ({round(last_15m['RSI'], 1)}) / 5m RSI ({round(last_5m['RSI'], 1)})")

        if bids_vol > asks_vol:
            confidence_score += 15
            reasons.append("Order Book: Higher Buying Demand (Bids > Asks)")

        if last_15m['volume'] > last_15m['Vol_MA']:
            confidence_score += 15
            reasons.append("Volume: Spiking Above 20-MA")

        if confidence_score >= 65:
            signal_type = "FUTURE LONG 🚀" if confidence_score >= 75 else "SPOT BUY 🛒"

    # --- SELL / SHORT SETUP ---
    elif close_1h < ema_50_1h or close_4h < ema_200_4h:
        confidence_score += 20
        reasons.append("Trend: HTF Bearish Structure")

        if at_strong_res:
            confidence_score += 30
            reasons.append("Structure: Rejection at Strong Resistance Zone (4H/1H)")
        elif at_minor_res:
            confidence_score += 20
            reasons.append("Structure: Rejection at Minor Resistance / 15m Bearish Order Block")

        # RSI Filter (65 - 90 Resistance Zone)
        if 60 <= last_15m['RSI'] <= 85 or 60 <= last_5m['RSI'] <= 85:
            confidence_score += 20
            reasons.append(f"RSI Resistance Zone: 15m RSI ({round(last_15m['RSI'], 1)}) / 5m RSI ({round(last_5m['RSI'], 1)})")

        if asks_vol > bids_vol:
            confidence_score += 15
            reasons.append("Order Book: Higher Selling Pressure (Asks > Bids)")

        if last_15m['volume'] > last_15m['Vol_MA']:
            confidence_score += 15
            reasons.append("Volume: Spiking Above 20-MA")

        if confidence_score >= 65:
            signal_type = "FUTURE SHORT 📉"

    if confidence_score >= 65 and signal_type:
        if "BUY" in signal_type or "LONG" in signal_type:
            sl = round(close_price - (atr * 1.5), 4)
            risk = close_price - sl
            tp1 = round(close_price + (risk * 1.5), 4)
            tp2 = round(close_price + (risk * 3.0), 4)
            tp3 = round(minor_resistance, 4) if minor_resistance > close_price else round(close_price + (risk * 4.0), 4)
        else:
            sl = round(close_price + (atr * 1.5), 4)
            risk = sl - close_price
            tp1 = round(close_price - (risk * 1.5), 4)
            tp2 = round(close_price - (risk * 3.0), 4)
            tp3 = round(minor_support, 4) if minor_support < close_price else round(close_price - (risk * 4.0), 4)

        return {
            'symbol': symbol,
            'signal_type': signal_type,
            'confidence': f"{confidence_score}%",
            'entry': round(close_price, 4),
            'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
            'sl': sl,
            'reasons': reasons
        }

    return None

async def market_scanner():
    """Fast Continuous Scanner Loop"""
    print("=== STARTING PRECISION SMC SIGNAL SCANNER ===", flush=True)
    send_telegram_message("🎯 Precision Crypto Signal Bot Updated & Active! Monitoring Market Structure...")

    mexc = ccxt.mexc({'enableRateLimit': True})
    gate = ccxt.gate({'enableRateLimit': True})

    try:
        while True:
            current_time = time.time()
            print(f"[SCANNER] Cycle started at {time.strftime('%H:%M:%S')}", flush=True)

            for symbol in TOP_COINS:
                signal_data = await analyze_market(mexc, gate, symbol)

                if signal_data:
                    signal_type = signal_data['signal_type']
                    signal_key = f"{symbol}_{signal_type}"

                    last_sent = SENT_SIGNALS.get(signal_key, 0)
                    if (current_time - last_sent) >= COOLDOWN_SECONDS:
                        SENT_SIGNALS[signal_key] = current_time

                        reasons_text = "\n".join([f"- {r}" for r in signal_data['reasons']])
                        leverage_text = "None (Spot Order)" if "SPOT" in signal_type else "5x - 10x (Day/Scalp)"

                        msg = (
                            f"🚨 HIGH PROBABILITY SIGNAL 🚨\n\n"
                            f"🪙 Coin: {signal_data['symbol']}\n"
                            f"🎯 Action: {signal_data['signal_type']}\n"
                            f"📊 Score: {signal_data['confidence']}\n\n"
                            f"📥 Entry Zone: {signal_data['entry']}\n"
                            f"🛑 Stop Loss: {signal_data['sl']}\n"
                            f"🎯 TP 1: {signal_data['tp1']}\n"
                            f"🎯 TP 2: {signal_data['tp2']}\n"
                            f"🎯 TP 3: {signal_data['tp3']}\n\n"
                            f"⚖️ Leverage: {leverage_text}\n\n"
                            f"💡 Confluence & Reasons:\n{reasons_text}"
                        )
                        send_telegram_message(msg)

                await asyncio.sleep(0.3)

            print("[SCANNER] Cycle finished. Resting for 2 minutes...", flush=True)
            await asyncio.sleep(120)

    finally:
        await mexc.close()
        await gate.close()

def main_loop():
    """Auto-restart Async Loop"""
    while True:
        try:
            asyncio.run(market_scanner())
        except Exception as e:
            print(f"[CRITICAL ERROR] Scanner crashed: {e}. Restarting in 10 seconds...", flush=True)
            time.sleep(10)

if __name__ == '__main__':
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    main_loop()
