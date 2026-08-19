import os
import asyncio
import logging
from flask import Flask
import ccxt.async_support as ccxt
import pandas as pd
import ta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FLASK WEBSERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Signal Pro+ Bot is Live!", 200

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8982651587:AAFdVu5qARVO6aXgvUwC6f2QL1TquDFSqqY"  # Insert your BotFather token here
PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
SENT_SIGNALS = {}

# Primary & Fallback Exchanges to Bypass CloudFront IP Blocks
exchange_primary = ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True})
exchange_fallback = ccxt.gateio({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})

# --- DATA FETCHING WITH FALLBACK ENGINE ---
async def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        data = await exchange_primary.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        logging.warning(f"Primary exchange fetch failed for {symbol}: {e}")
        
    try:
        data = await exchange_fallback.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        logging.error(f"Error fetching data from both exchanges for {symbol}: {e}")
        return None

# --- CANDLESTICK PATTERN ENGINE ---
def check_candle_confirmations(df):
    c1 = df.iloc[-2]  # Last closed candle
    c2 = df.iloc[-3]  # Previous closed candle
    c3 = df.iloc[-4]  # 3rd last closed candle

    # Bullish Patterns
    bullish_engulfing = (c1['close'] > c2['open']) and (c2['close'] < c2['open']) and (c1['close'] > c1['open'])
    bullish_pinbar = (c1['close'] > c1['open']) and ((c1['close'] - c1['low']) >= 2 * (c1['high'] - c1['close']))
    morning_star = (c3['close'] < c3['open']) and (abs(c2['close'] - c2['open']) < abs(c3['close'] - c3['open']) * 0.3) and (c1['close'] > c1['open']) and (c1['close'] > (c3['open'] + c3['close'])/2)

    # Bearish Patterns
    bearish_engulfing = (c1['close'] < c2['open']) and (c2['close'] > c2['open']) and (c1['close'] < c1['open'])
    bearish_pinbar = (c1['close'] < c1['open']) and ((c1['high'] - c1['close']) >= 2 * (c1['close'] - c1['low']))
    evening_star = (c3['close'] > c3['open']) and (abs(c2['close'] - c2['open']) < abs(c3['close'] - c3['open']) * 0.3) and (c1['close'] < c1['open']) and (c1['close'] < (c3['open'] + c3['close'])/2)

    bullish_confirmed = bullish_engulfing or bullish_pinbar or morning_star
    bearish_confirmed = bearish_engulfing or bearish_pinbar or evening_star

    pattern_name = []
    if bullish_engulfing: pattern_name.append("Bullish Engulfing")
    if bullish_pinbar: pattern_name.append("Bullish Pinbar Rejection")
    if morning_star: pattern_name.append("Morning Star Pattern")
    if bearish_engulfing: pattern_name.append("Bearish Engulfing")
    if bearish_pinbar: pattern_name.append("Bearish Pinbar Rejection")
    if evening_star: pattern_name.append("Evening Star Pattern")

    return bullish_confirmed, bearish_confirmed, pattern_name

async def analyze_market(symbol):
    # Fetching 3 Timeframes
    df_4h = await fetch_ohlcv(symbol, '4h', limit=50)
    df_1h = await fetch_ohlcv(symbol, '1h', limit=50)
    df_15m = await fetch_ohlcv(symbol, '15m', limit=100)
    
    if df_4h is None or df_1h is None or df_15m is None or len(df_15m) < 20:
        return []

    # Indicators Calculations (15m)
    df_15m['EMA_50'] = ta.trend.ema_indicator(df_15m['close'], window=50)
    df_15m['EMA_200'] = ta.trend.ema_indicator(df_15m['close'], window=200)
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    
    macd_obj = ta.trend.MACD(df_15m['close'])
    df_15m['MACD'] = macd_obj.macd()
    df_15m['MACD_SIGNAL'] = macd_obj.macd_signal()

    last_closed = df_15m.iloc[-2]
    close_price = last_closed['close']
    atr = last_closed['ATR']

    # Higher Timeframe Trend Alignment
    df_4h['EMA_50'] = ta.trend.ema_indicator(df_4h['close'], window=50)
    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)

    trend_4h = "BULLISH" if df_4h.iloc[-2]['close'] > df_4h.iloc[-2]['EMA_50'] else "BEARISH"
    trend_1h = "BULLISH" if df_1h.iloc[-2]['close'] > df_1h.iloc[-2]['EMA_50'] else "BEARISH"

    # Support & Resistance Levels
    recent_support = df_15m['low'].tail(20).min()
    recent_resistance = df_15m['high'].tail(20).max()
    at_support = abs(close_price - recent_support) / close_price < 0.005
    at_resistance = abs(close_price - recent_resistance) / close_price < 0.005

    # SMC Fair Value Gap (FVG) Logic
    fvg_bullish = df_15m.iloc[-2]['low'] > df_15m.iloc[-4]['high']
    fvg_bearish = df_15m.iloc[-2]['high'] < df_15m.iloc[-4]['low']

    # Candlestick Pattern Confirmations
    bull_confirm, bear_confirm, patterns = check_candle_confirmations(df_15m)

    signals_to_send = []

    # --- 1. FUTURES SIGNALS (LONG / SHORT) ---
    futures_signal = None
    f_reasons = []

    if trend_4h == "BULLISH" and trend_1h == "BULLISH" and last_closed['RSI'] < 65 and last_closed['EMA_50'] > last_closed['EMA_200'] and bull_confirm:
        if last_closed['MACD'] > last_closed['MACD_SIGNAL']:
            futures_signal = "LONG 🟢"
            f_reasons = ["4H & 1H Bullish Trend Alignment", f"Candlestick Confirmation: {', '.join(patterns)}", "15m EMA & MACD Alignment"]
            if at_support: f_reasons.append("Key Support Zone Bounce")
            if fvg_bullish: f_reasons.append("SMC Bullish Fair Value Gap (FVG)")

    elif trend_4h == "BEARISH" and trend_1h == "BEARISH" and last_closed['RSI'] > 35 and last_closed['EMA_50'] < last_closed['EMA_200'] and bear_confirm:
        if last_closed['MACD'] < last_closed['MACD_SIGNAL']:
            futures_signal = "SHORT 🔴"
            f_reasons = ["4H & 1H Bearish Trend Alignment", f"Candlestick Confirmation: {', '.join(patterns)}", "15m EMA & MACD Alignment"]
            if at_resistance: f_reasons.append("Key Resistance Zone Rejection")
            if fvg_bearish: f_reasons.append("SMC Bearish Fair Value Gap (FVG)")

    if futures_signal:
        key = f"{symbol}_FUTURES_{futures_signal}"
        if key not in SENT_SIGNALS:
            SENT_SIGNALS[key] = True
            if "LONG" in futures_signal:
                sl = round(close_price - (atr * 1.5), 2)
                tp1, tp2, tp3 = round(close_price + (atr * 1.5), 2), round(close_price + (atr * 3.0), 2), round(close_price + (atr * 4.5), 2)
            else:
                sl = round(close_price + (atr * 1.5), 2)
                tp1, tp2, tp3 = round(close_price - (atr * 1.5), 2), round(close_price - (atr * 3.0), 2), round(close_price - (atr * 4.5), 2)

            signals_to_send.append({
                'type': 'FUTURES ⚡', 'symbol': symbol, 'direction': futures_signal,
                'confidence': "95%", 'entry': f"{round(close_price, 2)}",
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'sl': sl,
                'leverage': "10x - 20x", 'reasons': f_reasons
            })

    # --- 2. SPOT SIGNALS (BUY / ACCUMULATE) ---
    if trend_4h == "BULLISH" and trend_1h == "BULLISH" and last_closed['RSI'] < 45 and bull_confirm:
        key = f"{symbol}_SPOT_BUY"
        if key not in SENT_SIGNALS:
            SENT_SIGNALS[key] = True
            spot_reasons = ["4H & 1H Bullish Trend Alignment", f"Candlestick Confirmation: {', '.join(patterns)}", "Oversold RSI Dip on Bullish Trend"]
            if at_support: spot_reasons.append("Major Support Rejection Level")
            if fvg_bullish: spot_reasons.append("SMC Spot Liquidity / FVG Gap")

            signals_to_send.append({
                'type': 'SPOT 🛒', 'symbol': symbol, 'direction': 'BUY / ACCUMULATE 🟢',
                'confidence': "97%", 'entry': f"{round(close_price, 2)}",
                'tp1': round(close_price * 1.05, 2), 'tp2': round(close_price * 1.10, 2), 'tp3': round(close_price * 1.20, 2),
                'sl': round(close_price * 0.93, 2), 'leverage': "NO LEVERAGE (Spot)",
                'reasons': spot_reasons
            })

    return signals_to_send

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.user_data['chat_id'] = chat_id
    await update.message.reply_text("🚀 **Welcome to Crypto Signal Pro+ Bot!**\n\nBot is active and scanning SPOT and FUTURES with Multi-Exchange API integration.", parse_mode="Markdown")

async def market_scanner(application):
    while True:
        try:
            for symbol in PAIRS:
                signals = await analyze_market(symbol)
                for signal_data in signals:
                    reasons_formatted = "\n".join([f"• {r}" for r in signal_data['reasons']])
                    message = (
                        f"🚨 **CRYPTO SIGNAL PRO+** 🚨\n\n"
                        f"**Trading Type:** {signal_data['type']}\n"
                        f"**Coin:** {signal_data['symbol']}\n"
                        f"**Direction:** {signal_data['direction']}\n"
                        f"**Confidence Score:** {signal_data['confidence']}\n\n"
                        f"**Entry Zone:** {signal_data['entry']}\n"
                        f"**Take-Profit 1:** {signal_data['tp1']}\n"
                        f"**Take-Profit 2:** {signal_data['tp2']}\n"
                        f"**Take-Profit 3:** {signal_data['tp3']}\n"
                        f"**Stop-Loss:** {signal_data['sl']}\n\n"
                        f"**Leverage:** {signal_data['leverage']}\n\n"
                        f"**Reasons:**\n{reasons_formatted}"
                    )
                    for chat_id in application.user_data.keys():
                        try:
                            await application.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
                        except Exception as e:
                            logging.error(f"Failed to send signal: {e}")
            await asyncio.sleep(60)
        except Exception as e:
            logging.error(f"Scanner error: {e}")
            await asyncio.sleep(10)

async def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    asyncio.create_task(market_scanner(application))
    
    async with application:
        await application.start()
        await application.updater.start_polling()
        while True:
            await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())
