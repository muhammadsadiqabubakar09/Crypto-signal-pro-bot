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
    return "Institutional SMC, Chart Patterns & Indicators Signal Engine Active!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

TOP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT',
    'LINK/USDT', 'SUI/USDT', 'NEAR/USDT', 'PEPE/USDT', 'FET/USDT', 'APT/USDT', 'POL/USDT', 'DOT/USDT',
    'LTC/USDT', 'SHIB/USDT', 'ARB/USDT', 'INJ/USDT', 'TIA/USDT', 'OP/USDT', 'RENDER/USDT', 'WIF/USDT',
    'FLOKI/USDT', 'BONK/USDT', 'SEI/USDT', 'STX/USDT', 'GALA/USDT', 'RUNE/USDT', 'AAVE/USDT', 'ICP/USDT',
    'FIL/USDT', 'ATOM/USDT', 'ETC/USDT', 'XLM/USDT', 'UNI/USDT', 'BCH/USDT', 'LDO/USDT', 'KAS/USDT',
    'JUP/USDT', 'ORDI/USDT', 'MEME/USDT', 'NOT/USDT', 'WLD/USDT', 'ONDO/USDT', 'ENA/USDT', 'STRK/USDT'
]

SENT_SIGNALS = {}
COOLDOWN_SECONDS = 45 * 60  # 45 Minutes Cooldown per coin

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

def format_price(price):
    """Dynamic Precision Formatter for Small and Large Prices"""
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

async def fetch_ohlcv(mexc, gate, symbol, timeframe, limit=300):
    """Fetch Deep Candlestick Data safely (Limit=300 for Strong S/R)"""
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

def detect_chart_patterns(df):
    """Detect Double Bottom (W) and Double Top (M) Patterns using Closed Candles"""
    recent_lows = df['low'].iloc[:-1].tail(30).values
    recent_highs = df['high'].iloc[:-1].tail(30).values
    current_close = df.iloc[-2]['close']

    double_bottom = False
    double_top = False

    if len(recent_lows) >= 30:
        min_low_1 = min(recent_lows[:15])
        min_low_2 = min(recent_lows[15:])
        
        # Check if two lows are within 0.35% range
        if abs(min_low_1 - min_low_2) / current_close < 0.0035:
            if current_close > min_low_2:
                double_bottom = True

    if len(recent_highs) >= 30:
        max_high_1 = max(recent_highs[:15])
        max_high_2 = max(recent_highs[15:])
        
        # Check if two highs are within 0.35% range
        if abs(max_high_1 - max_high_2) / current_close < 0.0035:
            if current_close < max_high_2:
                double_top = True

    return double_bottom, double_top

def detect_candlestick_patterns(df):
    """CLOSED CANDLESTICK ONLY Recognition Engine"""
    c0 = df.iloc[-2]  # Closed Candle
    c1 = df.iloc[-3]  
    c2 = df.iloc[-4]  

    def body(c): return abs(c['close'] - c['open'])
    def is_green(c): return c['close'] > c['open']
    def is_red(c): return c['close'] < c['open']
    def upper_wick(c): return c['high'] - max(c['open'], c['close'])
    def lower_wick(c): return min(c['open'], c['close']) - c['low']

    bullish_pattern = None
    bearish_pattern = None

    if is_green(c0) and is_red(c1) and c0['close'] > c1['open'] and c0['open'] < c1['close']:
        bullish_pattern = "Bullish Engulfing"
    elif lower_wick(c0) > (2 * body(c0)) and upper_wick(c0) <= (0.3 * body(c0)):
        bullish_pattern = "Hammer Pattern"
    elif upper_wick(c0) > (2 * body(c0)) and lower_wick(c0) <= (0.3 * body(c0)) and is_green(c0):
        bullish_pattern = "Inverted Hammer"
    elif abs(c0['low'] - c1['low']) / c0['close'] < 0.0015 and is_red(c1) and is_green(c0):
        bullish_pattern = "Tweezer Bottom"
    elif is_green(c0) and body(c0) > (0.85 * (c0['high'] - c0['low'])):
        bullish_pattern = "Bullish Marubozu"
    elif is_red(c2) and body(c1) < (0.3 * body(c2)) and is_green(c0) and c0['close'] > ((c2['open'] + c2['close']) / 2):
        bullish_pattern = "Morning Star"
    elif is_green(c2) and is_green(c1) and is_green(c0) and c0['close'] > c1['close'] > c2['close']:
        bullish_pattern = "Three White Soldiers"

    if is_red(c0) and is_green(c1) and c0['close'] < c1['open'] and c0['open'] > c1['close']:
        bearish_pattern = "Bearish Engulfing"
    elif abs(c0['high'] - c1['high']) / c0['close'] < 0.0015 and is_green(c1) and is_red(c0):
        bearish_pattern = "Tweezer Top"
    elif is_red(c0) and body(c0) > (0.85 * (c0['high'] - c0['low'])):
        bearish_pattern = "Bearish Marubozu"
    elif is_green(c2) and body(c1) < (0.3 * body(c2)) and is_red(c0) and c0['close'] < ((c2['open'] + c2['close']) / 2):
        bearish_pattern = "Evening Star"

    return bullish_pattern, bearish_pattern

async def analyze_market(mexc, gate, symbol):
    """Deep SMC + Chart Patterns + Indicator Analysis Engine"""
    df_4h = await fetch_ohlcv(mexc, gate, symbol, '4h', limit=300)
    df_1h = await fetch_ohlcv(mexc, gate, symbol, '1h', limit=300)
    df_15m = await fetch_ohlcv(mexc, gate, symbol, '15m', limit=150)
    df_5m = await fetch_ohlcv(mexc, gate, symbol, '5m', limit=100)

    if df_4h is None or df_1h is None or df_15m is None or df_5m is None:
        return None

    # Trend Indicators
    df_4h['EMA_200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)

    closed_4h = df_4h.iloc[-2]
    closed_1h = df_1h.iloc[-2]

    # Strong Support & Resistance from Deep 4H & 1H Data
    strong_support_4h = df_4h['low'].iloc[:-1].tail(50).min()
    strong_resistance_4h = df_4h['high'].iloc[:-1].tail(50).max()
    
    strong_support_1h = df_1h['low'].iloc[:-1].tail(30).min()
    strong_resistance_1h = df_1h['high'].iloc[:-1].tail(30).max()

    strong_support = min(strong_support_4h, strong_support_1h)
    strong_resistance = max(strong_resistance_4h, strong_resistance_1h)

    minor_support = df_15m['low'].iloc[:-1].tail(20).min()
    minor_resistance = df_15m['high'].iloc[:-1].tail(20).max()

    # Chart Pattern Detection
    double_bottom, double_top = detect_chart_patterns(df_15m)

    # SMC Structures (BOS / CHoCH & FVG Check)
    fvg_bullish = df_1h.iloc[-2]['low'] > df_1h.iloc[-4]['high']
    fvg_bearish = df_1h.iloc[-2]['high'] < df_1h.iloc[-4]['low']

    recent_low_sweep = df_15m.iloc[-2]['low'] < df_15m['low'].iloc[:-3].tail(15).min()
    recent_high_sweep = df_15m.iloc[-2]['high'] > df_15m['high'].iloc[:-3].tail(15).max()

    # Technical Indicators
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()
    df_5m['RSI'] = ta.momentum.rsi(df_5m['close'], window=14)

    closed_15m = df_15m.iloc[-2]
    closed_5m = df_5m.iloc[-2]
    close_price, atr = closed_15m['close'], closed_15m['ATR']

    at_strong_supp = (close_price - strong_support) / close_price < 0.012
    at_strong_res = (strong_resistance - close_price) / close_price < 0.012

    bullish_15m, bearish_15m = detect_candlestick_patterns(df_15m)
    bids_vol, asks_vol = await check_order_book_depth(mexc, gate, symbol)

    confidence_score = 0
    reasons = []
    signal_type = None

    # --- BUY / LONG SETUP ---
    if closed_1h['close'] > closed_1h['EMA_50'] or closed_4h['close'] > closed_4h['EMA_200']:
        confidence_score += 20
        reasons.append("Trend: HTF Bullish Market Structure")

        if at_strong_supp:
            confidence_score += 20
            reasons.append("SMC Zone: HTF Strong Support / Demand Block")

        if double_bottom:
            confidence_score += 15
            reasons.append("Chart Pattern: Double Bottom (W-Pattern) Confirmed")

        if recent_low_sweep:
            confidence_score += 10
            reasons.append("SMC Liquidity: Sell-Side Liquidity Swept")

        if fvg_bullish:
            confidence_score += 10
            reasons.append("SMC Imbalance: Bullish FVG Retest")

        if bullish_15m:
            confidence_score += 10
            reasons.append(f"Candle Pattern: {bullish_15m} (Closed Candle)")

        if 25 <= closed_15m['RSI'] <= 38 or 25 <= closed_5m['RSI'] <= 38:
            confidence_score += 5
            reasons.append(f"RSI Oversold Zone: 15m RSI ({round(closed_15m['RSI'], 1)})")

        if bids_vol > asks_vol:
            confidence_score += 5
            reasons.append("Order Book: Higher Buying Pressure")

        if closed_15m['volume'] > closed_15m['Vol_MA']:
            confidence_score += 5
            reasons.append("Volume: High Volume Surge")

        if confidence_score >= 75:
            signal_type = "FUTURE LONG 🚀" if confidence_score >= 80 else "SPOT BUY 🛒"

    # --- SELL / SHORT SETUP ---
    elif closed_1h['close'] < closed_1h['EMA_50'] or closed_4h['close'] < closed_4h['EMA_200']:
        confidence_score += 20
        reasons.append("Trend: HTF Bearish Market Structure")

        if at_strong_res:
            confidence_score += 20
            reasons.append("SMC Zone: HTF Strong Resistance / Supply Block")

        if double_top:
            confidence_score += 15
            reasons.append("Chart Pattern: Double Top (M-Pattern) Confirmed")

        if recent_high_sweep:
            confidence_score += 10
            reasons.append("SMC Liquidity: Buy-Side Liquidity Swept")

        if fvg_bearish:
            confidence_score += 10
            reasons.append("SMC Imbalance: Bearish FVG Retest")

        if bearish_15m:
            confidence_score += 10
            reasons.append(f"Candle Pattern: {bearish_15m} (Closed Candle)")

        if 62 <= closed_15m['RSI'] <= 78 or 62 <= closed_5m['RSI'] <= 78:
            confidence_score += 5
            reasons.append(f"RSI Overbought Zone: 15m RSI ({round(closed_15m['RSI'], 1)})")

        if asks_vol > bids_vol:
            confidence_score += 5
            reasons.append("Order Book: Higher Selling Pressure")

        if closed_15m['volume'] > closed_15m['Vol_MA']:
            confidence_score += 5
            reasons.append("Volume: High Volume Surge")

        if confidence_score >= 75:
            signal_type = "FUTURE SHORT 📉"

    # ACCURATE TAKE PROFIT & STOP LOSS CALCULATION
    if confidence_score >= 75 and signal_type:
        if "BUY" in signal_type or "LONG" in signal_type:
            sl = close_price - (atr * 1.5)
            risk = close_price - sl
            tp1 = close_price + (risk * 1.5)
            tp2 = close_price + (risk * 3.0)
            
            calculated_tp3 = close_price + (risk * 4.5)
            tp3 = max(calculated_tp3, minor_resistance) if minor_resistance > tp2 else calculated_tp3

        else:
            sl = close_price + (atr * 1.5)
            risk = sl - close_price
            tp1 = close_price - (risk * 1.5)
            tp2 = close_price - (risk * 3.0)
            
            calculated_tp3 = close_price - (risk * 4.5)
            tp3 = min(calculated_tp3, minor_support) if minor_support < tp2 else calculated_tp3

        return {
            'symbol': symbol,
            'signal_type': signal_type,
            'confidence': f"{confidence_score}%",
            'entry': format_price(close_price),
            'tp1': format_price(tp1), 
            'tp2': format_price(tp2), 
            'tp3': format_price(tp3),
            'sl': format_price(sl),
            'reasons': reasons
        }

    return None

async def market_scanner():
    """Fast Continuous Scanner Loop with Detailed Render Logs"""
    print("=== STARTING PRECISION SMC SIGNAL SCANNER ===", flush=True)
    send_telegram_message("🎯 Precision Crypto Signal Bot (Deep SMC + Patterns + Indicators) Active!")

    mexc = ccxt.mexc({'enableRateLimit': True})
    gate = ccxt.gate({'enableRateLimit': True})

    try:
        while True:
            current_time = time.time()
            print(f"[SCANNER] Cycle started at {time.strftime('%H:%M:%S')}", flush=True)

            for index, symbol in enumerate(TOP_COINS, start=1):
                print(f"[SCANNER] ({index}/{len(TOP_COINS)}) Scanning {symbol}...", flush=True)
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
                            f"💡 Confluence & Confirmations:\n{reasons_text}"
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
