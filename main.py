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
    return "Professional Crypto Signal Bot is Live & Healthy!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

PRIMARY_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'SUI/USDT',
    'NEAR/USDT', 'PEPE/USDT', 'FET/USDT', 'APT/USDT', 'POL/USDT'
]
SECONDARY_PAIRS = ['DOT/USDT', 'LTC/USDT', 'SHIB/USDT', 'ARB/USDT', 'INJ/USDT']

SENT_SIGNALS = {}
COOLDOWN_SECONDS = 4 * 3600  # 4 Hours Cooldown

def send_telegram_message(message):
    """Safely send messages to Telegram"""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN":
        logging.error("Telegram token is not configured correctly.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"[TELEGRAM] Response Status: {response.status_code}", flush=True)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}", flush=True)

async def fetch_ohlcv(mexc, gate, symbol, timeframe, limit=100):
    """Fetch Candlestick Data safely with exchange reconnection"""
    try:
        data = await mexc.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e_mexc:
        try:
            data = await gate.fetch_ohlcv(symbol, timeframe, limit=limit)
            return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception:
            return None

async def check_order_book_depth(mexc, gate, symbol):
    """Check Order Book Depth"""
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
    """Multi-Timeframe Analysis Engine"""
    df_4h = await fetch_ohlcv(mexc, gate, symbol, '4h', limit=100)
    df_1h = await fetch_ohlcv(mexc, gate, symbol, '1h', limit=100)
    df_15m = await fetch_ohlcv(mexc, gate, symbol, '15m', limit=100)
    df_5m = await fetch_ohlcv(mexc, gate, symbol, '5m', limit=100)

    if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
        return None

    df_4h['EMA_200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)

    close_4h, ema_200_4h = df_4h.iloc[-1]['close'], df_4h.iloc[-1]['EMA_200']
    close_1h, ema_50_1h = df_1h.iloc[-1]['close'], df_1h.iloc[-1]['EMA_50']

    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()
    df_5m['RSI'] = ta.momentum.rsi(df_5m['close'], window=14)

    last_15m = df_15m.iloc[-1]
    last_5m = df_5m.iloc[-1]
    close_price, atr = last_15m['close'], last_15m['ATR']

    recent_support = df_15m['low'].tail(20).min()
    recent_resistance = df_15m['high'].tail(20).max()
    at_support = (close_price - recent_support) / close_price < 0.006
    at_resistance = (recent_resistance - close_price) / close_price < 0.006

    bids_vol, asks_vol = await check_order_book_depth(mexc, gate, symbol)

    confidence_score = 0
    reasons = []
    signal_type = None

    # BUY / LONG
    if close_4h > ema_200_4h and close_1h > ema_50_1h:
        confidence_score += 30
        reasons.append("HTF Trend Alignment (4H > EMA200 & 1H > EMA50)")

        if at_support:
            confidence_score += 25
            reasons.append("Price Rejection at Key Support Zone (Order Block)")

        if bids_vol > asks_vol * 1.2:
            confidence_score += 20
            reasons.append("Order Book Depth: Strong Buy Wall Detected")

        if last_15m['RSI'] < 48 and last_5m['RSI'] < 45:
            confidence_score += 15
            reasons.append("LTF RSI Oversold Recovery")

        if last_15m['volume'] > last_15m['Vol_MA'] * 1.1:
            confidence_score += 10
            reasons.append("High Volume Spike Confirmation")

        if confidence_score >= 85:
            signal_type = "FUTURE LONG 🚀"
        elif confidence_score >= 75:
            signal_type = "SPOT BUY 🛒"

    # SELL / SHORT
    elif close_4h < ema_200_4h and close_1h < ema_50_1h:
        confidence_score += 30
        reasons.append("HTF Trend Alignment (4H < EMA200 & 1H < EMA50)")

        if at_resistance:
            confidence_score += 25
            reasons.append("Price Rejection at Key Resistance Zone")

        if asks_vol > bids_vol * 1.2:
            confidence_score += 20
            reasons.append("Order Book Depth: Strong Sell Wall Detected")

        if last_15m['RSI'] > 52 and last_5m['RSI'] > 55:
            confidence_score += 15
            reasons.append("LTF RSI Overbought Rejection")

        if last_15m['volume'] > last_15m['Vol_MA'] * 1.1:
            confidence_score += 10
            reasons.append("High Volume Spike Confirmation")

        if confidence_score >= 75:
            signal_type = "FUTURE SHORT 📉"

    if confidence_score >= 75 and signal_type:
        if "BUY" in signal_type or "LONG" in signal_type:
            sl = round(close_price - (atr * 1.5), 4)
            risk = close_price - sl
            tp1, tp2, tp3 = round(close_price + (risk * 1.5), 4), round(close_price + (risk * 3.0), 4), round(recent_resistance, 4)
        else:
            sl = round(close_price + (atr * 1.5), 4)
            risk = sl - close_price
            tp1, tp2, tp3 = round(close_price - (risk * 1.5), 4), round(close_price - (risk * 3.0), 4), round(recent_support, 4)

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
    """Main Scanner Loop with Safe Async Exchange Management"""
    print("=== STARTING MARKET SCANNER LOOP ===", flush=True)
    send_telegram_message("🤖 Crypto Signal Pro Bot Active! Scanning market via Dual Exchanges (MEXC/Gate.io)...")

    # Dynamic exchange instantiation inside loop
    mexc = ccxt.mexc({'enableRateLimit': True})
    gate = ccxt.gate({'enableRateLimit': True})

    try:
        while True:
            current_time = time.time()
            all_pairs = PRIMARY_PAIRS + SECONDARY_PAIRS
            print(f"[SCANNER] Starting new scan cycle at {time.strftime('%H:%M:%S')}", flush=True)

            for symbol in all_pairs:
                signal_data = await analyze_market(mexc, gate, symbol)

                if signal_data:
                    signal_type = signal_data['signal_type']
                    signal_key = f"{symbol}_{signal_type}"

                    last_sent = SENT_SIGNALS.get(signal_key, 0)
                    if (current_time - last_sent) >= COOLDOWN_SECONDS:
                        SENT_SIGNALS[signal_key] = current_time

                        reasons_text = "\n".join([f"- {r}" for r in signal_data['reasons']])
                        leverage_text = "None (Spot Order)" if "SPOT" in signal_type else "5x - 10x"

                        msg = (
                            f"🚨 CRYPTO SIGNAL PRO 🚨\n\n"
                            f"🪙 Coin: {signal_data['symbol']}\n"
                            f"🎯 Signal Type: {signal_data['signal_type']}\n"
                            f"📊 Confidence Score: {signal_data['confidence']}\n\n"
                            f"📥 Entry Zone: {signal_data['entry']}\n"
                            f"🛑 Stop Loss: {signal_data['sl']}\n"
                            f"🎯 TP 1 (1:1.5 RR): {signal_data['tp1']}\n"
                            f"🎯 TP 2 (1:3.0 RR): {signal_data['tp2']}\n"
                            f"🎯 TP 3 (Structure Target): {signal_data['tp3']}\n\n"
                            f"⚖️ Suggested Leverage: {leverage_text}\n\n"
                            f"💡 Analytical Reasons:\n{reasons_text}"
                        )
                        send_telegram_message(msg)

                await asyncio.sleep(2)

            print("[SCANNER] Scan cycle finished. Sleeping for 10 minutes...", flush=True)
            await asyncio.sleep(600)

    finally:
        await mexc.close()
        await gate.close()

def main_loop():
    """Auto-restart Async Loop if network drops"""
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
