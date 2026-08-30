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

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FLASK WEBSERVER (FOR RENDER PORT BINDING) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Professional Crypto Signal Bot is Live & Healthy!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# Primary High-Volume Coins (Top Priority)
PRIMARY_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'SUI/USDT',
    'NEAR/USDT', 'PEPE/USDT', 'FET/USDT', 'APT/USDT', 'MATIC/USDT'
]

# Secondary / Optional Coins
SECONDARY_PAIRS = ['DOT/USDT', 'LTC/USDT', 'SHIB/USDT', 'ARBV/USDT', 'INJ/USDT']

# Anti-Duplicate & Cooldown Tracker
SENT_SIGNALS = {}
COOLDOWN_SECONDS = 4 * 3600  # 4 Hours Cooldown

# --- DUAL EXCHANGES (MEXC & GATE.IO - CLOUD FRIENDLY) ---
mexc_exchange = ccxt.mexc({'enableRateLimit': True})
gate_exchange = ccxt.gate({'enableRateLimit': True})

def send_telegram_message(message):
    """Function to send messages to Telegram"""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logging.error("Telegram token is not configured correctly.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Error sending Telegram message: {e}")

async def fetch_ohlcv(symbol, timeframe, limit=100):
    """Fetch Candlestick Data from Exchange (Primary: MEXC, Fallback: Gate.io)"""
    try:
        data = await mexc_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e_mexc:
        logging.warning(f"MEXC failed for {symbol} ({timeframe}), switching to Gate.io: {e_mexc}")
        try:
            data = await gate_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except Exception as e_gate:
            logging.error(f"Gate.io also failed for {symbol} ({timeframe}): {e_gate}")
            return None

async def check_order_book_depth(symbol):
    """Check Buy/Sell Walls for Order Book Depth Analysis"""
    try:
        order_book = await mexc_exchange.fetch_order_book(symbol, limit=20)
        bids_volume = sum([bid[1] for bid in order_book['bids']])
        asks_volume = sum([ask[1] for ask in order_book['asks']])
        return bids_volume, asks_volume
    except Exception:
        try:
            order_book = await gate_exchange.fetch_order_book(symbol, limit=20)
            bids_volume = sum([bid[1] for bid in order_book['bids']])
            asks_volume = sum([ask[1] for ask in order_book['asks']])
            return bids_volume, asks_volume
        except Exception as e:
            logging.warning(f"Could not fetch order book for {symbol}: {e}")
            return 0, 0

async def analyze_market(symbol):
    """Multi-Timeframe Analysis Engine (4H, 1H, 15m, 5m)"""
    df_4h = await fetch_ohlcv(symbol, '4h', limit=100)
    df_1h = await fetch_ohlcv(symbol, '1h', limit=100)
    df_15m = await fetch_ohlcv(symbol, '15m', limit=100)
    df_5m = await fetch_ohlcv(symbol, '5m', limit=100)

    if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
        return None

    # Trend Indicators (4H & 1H)
    df_4h['EMA_200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)

    close_4h = df_4h.iloc[-1]['close']
    ema_200_4h = df_4h.iloc[-1]['EMA_200']
    close_1h = df_1h.iloc[-1]['close']
    ema_50_1h = df_1h.iloc[-1]['EMA_50']

    # Entry Indicators (15m & 5m)
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()

    df_5m['RSI'] = ta.momentum.rsi(df_5m['close'], window=14)

    last_15m = df_15m.iloc[-1]
    last_5m = df_5m.iloc[-1]
    close_price = last_15m['close']
    atr = last_15m['ATR']

    # Key Support and Resistance Zones (SMC Core)
    recent_support = df_15m['low'].tail(20).min()
    recent_resistance = df_15m['high'].tail(20).max()
    at_support = (close_price - recent_support) / close_price < 0.006
    at_resistance = (recent_resistance - close_price) / close_price < 0.006

    # Fetch Order Book Depth
    bids_vol, asks_vol = await check_order_book_depth(symbol)

    # Scoring & Direction Calculation
    confidence_score = 0
    reasons = []
    direction = None

    # --- BUY / LONG EVALUATION ---
    if close_4h > ema_200_4h and close_1h > ema_50_1h:
        direction = "LONG 🟢"
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
            reasons.append("LTF RSI Oversold Recovery (15m/5m Confirmation)")

        if last_15m['volume'] > last_15m['Vol_MA'] * 1.1:
            confidence_score += 10
            reasons.append("High Volume Spike Confirmation")

    # --- SELL / SHORT EVALUATION ---
    elif close_4h < ema_200_4h and close_1h < ema_50_1h:
        direction = "SHORT 🔴"
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
            reasons.append("LTF RSI Overbought Rejection (15m/5m Confirmation)")

        if last_15m['volume'] > last_15m['Vol_MA'] * 1.1:
            confidence_score += 10
            reasons.append("High Volume Spike Confirmation")

    # Minimum threshold to send signal is 75%
    if confidence_score >= 75 and direction:
        # Dynamic ATR Stop Loss & Take Profit Targets
        if "LONG" in direction:
            sl = round(close_price - (atr * 1.5), 4)
            risk = close_price - sl
            tp1 = round(close_price + (risk * 1.5), 4)
            tp2 = round(close_price + (risk * 3.0), 4)
            tp3 = round(recent_resistance, 4)
        else:
            sl = round(close_price + (atr * 1.5), 4)
            risk = sl - close_price
            tp1 = round(close_price - (risk * 1.5), 4)
            tp2 = round(close_price - (risk * 3.0), 4)
            tp3 = round(recent_support, 4)

        return {
            'symbol': symbol,
            'direction': direction,
            'confidence': f"{confidence_score}%",
            'entry': round(close_price, 4),
            'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
            'sl': sl,
            'reasons': reasons
        }

    return None

async def market_scanner():
    """Main Loop: Scan market every 10 minutes with Duplicate Signal Prevention"""
    send_telegram_message("🤖 *Crypto Signal Pro Bot Active! Scanning market via Dual Exchanges (MEXC/Gate.io)...*")

    while True:
        try:
            current_time = time.time()
            all_pairs = PRIMARY_PAIRS + SECONDARY_PAIRS

            for symbol in all_pairs:
                signal_data = await analyze_market(symbol)

                if signal_data:
                    direction = signal_data['direction']
                    signal_key = f"{symbol}_{direction}"

                    # Anti-Duplicate Check
                    last_sent = SENT_SIGNALS.get(signal_key, 0)
                    if (current_time - last_sent) >= COOLDOWN_SECONDS:
                        SENT_SIGNALS[signal_key] = current_time

                        reasons_text = "\n".join([f"• {r}" for r in signal_data['reasons']])
                        msg = (
                            f"🚨 **CRYPTO SIGNAL PRO** 🚨\n\n"
                            f"🪙 **Coin:** {signal_data['symbol']}\n"
                            f"🎯 **Direction:** {signal_data['direction']}\n"
                            f"📊 **Confidence Score:** {signal_data['confidence']}\n\n"
                            f"📥 **Entry Zone:** `{signal_data['entry']}`\n"
                            f"🛑 **Stop Loss:** `{signal_data['sl']}`\n"
                            f"🎯 **TP 1 (1:1.5 RR):** `{signal_data['tp1']}`\n"
                            f"🎯 **TP 2 (1:3.0 RR):** `{signal_data['tp2']}`\n"
                            f"🎯 **TP 3 (Structure Target):** `{signal_data['tp3']}`\n\n"
                            f"⚖️ **Suggested Leverage:** 5x - 10x\n\n"
                            f"💡 **Analytical Reasons:**\n{reasons_text}"
                        )
                        send_telegram_message(msg)

                await asyncio.sleep(2)  # Delay to respect API rate limits

            # 10-minute sleep interval before the next scan cycle (600 seconds)
            await asyncio.sleep(600)

        except Exception as e:
            logging.error(f"Error in scanner loop: {e}")
            await asyncio.sleep(30)

async def main():
    # Run Flask Webserver
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    # Start market scanning loop
    await market_scanner()

if __name__ == '__main__':
    asyncio.run(main())
