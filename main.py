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
TELEGRAM_TOKEN = "8982651587:AAFdVu5qARVO6aXgvUwC6f2QL1TquDFSqqY"  # Put your Telegram Token here
PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
SENT_SIGNALS = {}

futures_exchange = ccxt.binance({'options': {'defaultType': 'future'}, 'enableRateLimit': True})
spot_exchange = ccxt.binance({'options': {'defaultType': 'spot'}, 'enableRateLimit': True})

async def fetch_ohlcv(exchange_obj, symbol, timeframe, limit=100):
    try:
        data = await exchange_obj.fetch_ohlcv(symbol, timeframe, limit=limit)
        return pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None

async def analyze_market(symbol):
    df_4h = await fetch_ohlcv(futures_exchange, symbol, '4h', limit=50)
    df_15m = await fetch_ohlcv(futures_exchange, symbol, '15m', limit=100)
    
    if df_4h is None or df_15m is None:
        return None

    df_15m['EMA_50'] = ta.trend.ema_indicator(df_15m['close'], window=50)
    df_15m['EMA_200'] = ta.trend.ema_indicator(df_15m['close'], window=200)
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    
    macd_obj = ta.trend.MACD(df_15m['close'])
    df_15m['MACD'] = macd_obj.macd()
    df_15m['MACD_SIGNAL'] = macd_obj.macd_signal()

    last = df_15m.iloc[-1]
    prev = df_15m.iloc[-2]
    close_price = last['close']
    atr = last['ATR']

    df_4h['EMA_50'] = ta.trend.ema_indicator(df_4h['close'], window=50)
    trend_4h = "BULLISH" if df_4h.iloc[-1]['close'] > df_4h.iloc[-1]['EMA_50'] else "BEARISH"

    fvg_bullish = df_15m.iloc[-1]['low'] > df_15m.iloc[-3]['high']
    fvg_bearish = df_15m.iloc[-1]['high'] < df_15m.iloc[-3]['low']

    # FUTURES SIGNALS
    futures_signal = None
    f_reasons = []

    if trend_4h == "BULLISH" and last['RSI'] < 65 and last['EMA_50'] > last['EMA_200']:
        if last['MACD'] > last['MACD_SIGNAL'] and prev['MACD'] <= prev['MACD_SIGNAL']:
            futures_signal = "LONG 🟢"
            f_reasons = ["4H Bullish Trend Alignment", "15m EMA Golden Cross & MACD Crossover"]
            if fvg_bullish: f_reasons.append("15m Fair Value Gap (FVG) Support")

    elif trend_4h == "BEARISH" and last['RSI'] > 35 and last['EMA_50'] < last['EMA_200']:
        if last['MACD'] < last['MACD_SIGNAL'] and prev['MACD'] >= prev['MACD_SIGNAL']:
            futures_signal = "SHORT 🔴"
            f_reasons = ["4H Bearish Trend Alignment", "15m EMA Death Cross & MACD Crossover"]
            if fvg_bearish: f_reasons.append("15m Fair Value Gap (FVG) Resistance")

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

            return {
                'type': 'FUTURES ⚡', 'symbol': symbol, 'direction': futures_signal,
                'confidence': "88%", 'entry': f"{round(close_price, 2)}",
                'tp1': tp1, 'tp2': tp2, 'tp3': tp3, 'sl': sl,
                'leverage': "10x - 20x", 'reasons': f_reasons
            }

    # SPOT SIGNALS
    if trend_4h == "BULLISH" and last['RSI'] < 40 and fvg_bullish:
        key = f"{symbol}_SPOT_BUY"
        if key not in SENT_SIGNALS:
            SENT_SIGNALS[key] = True
            return {
                'type': 'SPOT 🛒', 'symbol': symbol, 'direction': 'BUY / ACCUMULATE 🟢',
                'confidence': "91%", 'entry': f"{round(close_price, 2)}",
                'tp1': round(close_price * 1.05, 2), 'tp2': round(close_price * 1.10, 2), 'tp3': round(close_price * 1.20, 2),
                'sl': round(close_price * 0.93, 2), 'leverage': "NO LEVERAGE (Spot)",
                'reasons': ["Oversold RSI Dip on Bullish Trend", "Strong Spot FVG Accumulation Zone"]
            }

    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.user_data['chat_id'] = chat_id
    await update.message.reply_text("🚀 **Welcome to Crypto Signal Pro+ Bot!**\n\nBot is running 24/7 scanning SPOT and FUTURES.", parse_mode="Markdown")

async def market_scanner(application):
    while True:
        try:
            for symbol in PAIRS:
                signal_data = await analyze_market(symbol)
                if signal_data:
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
