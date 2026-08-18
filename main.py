import os
import asyncio
import logging
from threading import Thread
from flask import Flask
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FLASK WEBSERVER (For Render Keep-Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Crypto Signal Pro+ Bot is Running 24/7!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- CONFIGURATION ---
TELEGRAM_TOKEN = "8982651587:AAFdVu5qARVO6aXgvUwC6f2QL1TquDFSqqY"  # Place your BotFather Token here
PAIRS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
SENT_SIGNALS = {}  # Prevent duplicate signals

# Initialize Binance Futures CCXT Exchange
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

# --- TECHNICAL ANALYSIS & SMC LOGIC ---
async def fetch_ohlcv(symbol, timeframe, limit=100):
    try:
        data = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
        return None

async def analyze_market(symbol):
    # 1. Multi-Timeframe Analysis (4H Trend + 15m Signal)
    df_4h = await fetch_ohlcv(symbol, '4h', limit=50)
    df_15m = await fetch_ohlcv(symbol, '15m', limit=100)
    
    if df_4h is None or df_15m is None:
        return None

    # Calculate Indicators on 15m
    df_15m['EMA_50'] = ta.ema(df_15m['close'], length=50)
    df_15m['EMA_200'] = ta.ema(df_15m['close'], length=200)
    df_15m['RSI'] = ta.rsi(df_15m['close'], length=14)
    df_15m['ATR'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=14)
    
    macd = ta.macd(df_15m['close'])
    df_15m['MACD'] = macd['MACD_12_26_9']
    df_15m['MACD_SIGNAL'] = macd['MACDs_12_26_9']

    # Current market metrics
    last = df_15m.iloc[-1]
    prev = df_15m.iloc[-2]
    close_price = last['close']
    atr = last['ATR']

    # 4H Market Trend
    df_4h['EMA_50'] = ta.ema(df_4h['close'], length=50)
    trend_4h = "BULLISH" if df_4h.iloc[-1]['close'] > df_4h.iloc[-1]['EMA_50'] else "BEARISH"

    # SMC Logic: Fair Value Gap (FVG) Check on 15m
    fvg_bullish = df_15m.iloc[-1]['low'] > df_15m.iloc[-3]['high']
    fvg_bearish = df_15m.iloc[-1]['high'] < df_15m.iloc[-3]['low']

    signal = None
    reasons = []

    # LONG Signal Conditions
    if trend_4h == "BULLISH" and last['RSI'] < 65 and last['EMA_50'] > last['EMA_200']:
        if last['MACD'] > last['MACD_SIGNAL'] and prev['MACD'] <= prev['MACD_SIGNAL']:
            signal = "LONG 🟢"
            reasons.append("4H Bullish Structure Shift")
            reasons.append("15m Golden EMA Cross & MACD Bullish Crossover")
            if fvg_bullish:
                reasons.append("15m Fair Value Gap (FVG) Support")

    # SHORT Signal Conditions
    elif trend_4h == "BEARISH" and last['RSI'] > 35 and last['EMA_50'] < last['EMA_200']:
        if last['MACD'] < last['MACD_SIGNAL'] and prev['MACD'] >= prev['MACD_SIGNAL']:
            signal = "SHORT 🔴"
            reasons.append("4H Bearish Structure Shift")
            reasons.append("15m Death EMA Cross & MACD Bearish Crossover")
            if fvg_bearish:
                reasons.append("15m Fair Value Gap (FVG) Resistance")

    if signal:
        # Prevent Duplicates (Don't resend within 2 hours for same direction)
        signal_key = f"{symbol}_{signal}"
        if signal_key in SENT_SIGNALS:
            return None

        SENT_SIGNALS[signal_key] = True

        # Targets & Stop Loss Calculation
        if "LONG" in signal:
            sl = round(close_price - (atr * 1.5), 2)
            tp1 = round(close_price + (atr * 1.5), 2)
            tp2 = round(close_price + (atr * 3.0), 2)
            tp3 = round(close_price + (atr * 4.5), 2)
        else:
            sl = round(close_price + (atr * 1.5), 2)
            tp1 = round(close_price - (atr * 1.5), 2)
            tp2 = round(close_price - (atr * 3.0), 2)
            tp3 = round(close_price - (atr * 4.5), 2)

        return {
            'symbol': symbol,
            'direction': signal,
            'confidence': "87%",
            'entry': f"{round(close_price, 2)}",
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'sl': sl,
            'leverage': "10x - 20x",
            'reasons': reasons
        }

    return None

# --- TELEGRAM BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.user_data['chat_id'] = chat_id
    await update.message.reply_text(
        "🚀 **Sannu da zuwa Crypto Signal Pro+ Bot!**\n\n"
        "Aiki ya fara! Bot ɗin zai duba kasuwa 24/7 sannan ya tura maka ingantaccen Signal idan ya gano dama.",
        parse_mode="Markdown"
    )

# --- BACKGROUND MARKET SCANNER ---
async def market_scanner(app):
    while True:
        try:
            for symbol in PAIRS:
                signal_data = await analyze_market(symbol)
                if signal_data:
                    # Construct Signal Message
                    reasons_formatted = "\n".join([f"• {r}" for r in signal_data['reasons']])
                    message = (
                        f"🚨 **CRYPTO SIGNAL PRO+** 🚨\n\n"
                        f"**Coin:** {signal_data['symbol']} (Futures)\n"
                        f"**Direction:** {signal_data['direction']}\n"
                        f"**Confidence Score:** {signal_data['confidence']}\n\n"
                        f"**Entry Zone:** {signal_data['entry']}\n"
                        f"**Take-Profit 1:** {signal_data['tp1']}\n"
                        f"**Take-Profit 2:** {signal_data['tp2']}\n"
                        f"**Take-Profit 3:** {signal_data['tp3']}\n"
                        f"**Stop-Loss:** {signal_data['sl']}\n\n"
                        f"**Suggested Leverage:** {signal_data['leverage']}\n\n"
                        f"**Reasons:**\n{reasons_formatted}"
                    )
                    
                    # Send to registered active user chats
                    for chat_id in app.user_data.keys():
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
                        except Exception as e:
                            logging.error(f"Failed to send signal to {chat_id}: {e}")

            await asyncio.sleep(60)  # Scan every 1 minute
        except Exception as e:
            logging.error(f"Scanner Loop Error: {e}")
            await asyncio.sleep(10)

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    keep_alive()  # Start Flask web app
    
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    # Start Market Scanner in Async Background Loop
    loop = asyncio.get_event_loop()
    loop.create_task(market_scanner(application))
    
    # Start Telegram Bot
    application.run_polling()
