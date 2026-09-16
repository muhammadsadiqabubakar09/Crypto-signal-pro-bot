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
    return "Institutional SMC Engine Active with Strict 80%+ Score Filters!", 200

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
    'JUP/USDT', 'ORDI/USDT', 'MEME/USDT', 'NOT/USDT', 'WLD/USDT', 'ONDO/USDT', 'ENA/USDT', 'STRK/USDT',
    'TAO/USDT', 'PENDLE/USDT', 'POPCAT/USDT', 'TON/USDT', 'TRX/USDT', 'FTM/USDT', 'BRETT/USDT', '1000SATS/USDT', 'AKT/USDT', 'SNX/USDT'
]

LARGE_CAP_COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'TON/USDT', 'TRX/USDT',
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'BCH/USDT', 'LTC/USDT',
    'SUI/USDT', 'NEAR/USDT', 'APT/USDT'
]

SENT_SIGNALS = {}
ACTIVE_PAPER_TRADES = []
COOLDOWN_SECONDS = 60 * 60  # Cooldown na awa 1

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

def execute_paper_trade(signal_data):
    """Sanya Paper Trade ta atomatik tare da tace duplicated trades"""
    symbol = signal_data['symbol']

    for trade in ACTIVE_PAPER_TRADES:
        if trade['symbol'] == symbol:
            return

    entry_price = float(signal_data['entry'])
    sl = float(signal_data['sl'])
    tp1 = float(signal_data['tp1'])
    tp2 = float(signal_data['tp2'])
    tp3 = float(signal_data['tp3'])
    signal_type = signal_data['signal_type']
    reasons = signal_data.get('reasons', [])

    allocated_capital = 5000.0 if symbol in LARGE_CAP_COINS else 2000.0
    coin_amount = allocated_capital / entry_price

    trade = {
        'symbol': symbol,
        'type': 'LONG' if ("BUY" in signal_type or "LONG" in signal_type) else 'SHORT',
        'entry': entry_price,
        'capital': allocated_capital,
        'amount': coin_amount,
        'sl': sl,
        'original_sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'tp3': tp3,
        'hit_tp1': False,
        'open_time': time.strftime('%H:%M:%S')
    }

    ACTIVE_PAPER_TRADES.append(trade)

    reasons_formatted = "\n".join([f"• {r}" for r in reasons])

    paper_msg = (
        f"📝 **AUTOMATED PAPER TRADE OPENED** 📝\n\n"
        f"🪙 **Coin:** {symbol}\n"
        f"📈 **Type:** {trade['type']}\n"
        f"💰 **Position Capital:** ${allocated_capital:,.2f}\n"
        f"📥 **Entry Price:** {signal_data['entry']}\n"
        f"🛑 **Stop Loss:** {signal_data['sl']}\n"
        f"🎯 **Target TP1:** {signal_data['tp1']}\n"
        f"🎯 **Target TP2:** {signal_data['tp2']}\n"
        f"🎯 **Target TP3:** {signal_data['tp3']}\n"
        f"⏱️ **Time:** {trade['open_time']}\n\n"
        f"💡 **High-Confluence Confirmations:**\n{reasons_formatted}"
    )
    send_telegram_message(paper_msg)

async def check_active_paper_trades(mexc, gate):
    """Sa ido a kan paper trades tare da sarrafa Breakeven/Partial Profits"""
    global ACTIVE_PAPER_TRADES
    if not ACTIVE_PAPER_TRADES:
        return

    for trade in ACTIVE_PAPER_TRADES[:]:
        symbol = trade['symbol']
        try:
            ticker = await mexc.fetch_ticker(symbol)
            current_price = ticker['close']
        except Exception:
            try:
                ticker = await gate.fetch_ticker(symbol)
                current_price = ticker['close']
            except Exception:
                continue

        is_long = trade['type'] == 'LONG'
        closed = False
        pnl = 0.0
        reason = ""

        if is_long:
            if current_price >= trade['tp1'] and not trade['hit_tp1']:
                trade['hit_tp1'] = True
                trade['sl'] = trade['entry']
                send_telegram_message(f"🎯 **{symbol} TP1 Hit!** Moving Stop Loss to Breakeven ({format_price(trade['entry'])}).")

            if current_price <= trade['sl']:
                closed = True
                pnl = (trade['sl'] - trade['entry']) * trade['amount']
                reason = "🛡️ Breakeven Exit" if trade['hit_tp1'] else "🛑 Stop Loss Hit"
            elif current_price >= trade['tp3']:
                closed = True
                pnl = (trade['tp3'] - trade['entry']) * trade['amount']
                reason = "🎯 TP3 Hit (Maximum Profit!)"

        else:
            if current_price <= trade['tp1'] and not trade['hit_tp1']:
                trade['hit_tp1'] = True
                trade['sl'] = trade['entry']
                send_telegram_message(f"🎯 **{symbol} SHORT TP1 Hit!** Moving Stop Loss to Breakeven ({format_price(trade['entry'])}).")

            if current_price >= trade['sl']:
                closed = True
                pnl = (trade['entry'] - trade['sl']) * trade['amount']
                reason = "🛡️ Breakeven Exit" if trade['hit_tp1'] else "🛑 Stop Loss Hit"
            elif current_price <= trade['tp3']:
                closed = True
                pnl = (trade['entry'] - trade['tp3']) * trade['amount']
                reason = "🎯 TP3 Hit (Maximum Profit!)"

        if closed:
            ACTIVE_PAPER_TRADES.remove(trade)
            pnl_icon = "🟢 Profit" if pnl >= 0 else "🔴 Loss"
            close_msg = (
                f"🔔 **PAPER TRADE CLOSED** 🔔\n\n"
                f"🪙 **Coin:** {symbol}\n"
                f"📌 **Status:** {reason}\n"
                f"💵 **Exit Price:** {format_price(current_price)}\n"
                f"📊 **Result PnL:** {pnl_icon} ${pnl:,.2f}"
            )
            send_telegram_message(close_msg)

async def fetch_ohlcv(mexc, gate, symbol, timeframe, limit=300):
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
    recent_lows = df['low'].iloc[:-1].tail(30).values
    recent_highs = df['high'].iloc[:-1].tail(30).values
    current_close = df.iloc[-2]['close']

    double_bottom, double_top = False, False

    if len(recent_lows) >= 30:
        min_low_1, min_low_2 = min(recent_lows[:15]), min(recent_lows[15:])
        if abs(min_low_1 - min_low_2) / current_close < 0.0035 and current_close > min_low_2:
            double_bottom = True

    if len(recent_highs) >= 30:
        max_high_1, max_high_2 = max(recent_highs[:15]), max(recent_highs[15:])
        if abs(max_high_1 - max_high_2) / current_close < 0.0035 and current_close < max_high_2:
            double_top = True

    return double_bottom, double_top

def detect_candlestick_patterns(df):
    c0, c1, c2 = df.iloc[-2], df.iloc[-3], df.iloc[-4]

    def body(c): return abs(c['close'] - c['open'])
    def is_green(c): return c['close'] > c['open']
    def is_red(c): return c['close'] < c['open']
    def upper_wick(c): return c['high'] - max(c['open'], c['close'])
    def lower_wick(c): return min(c['open'], c['close']) - c['low']

    bullish_pattern, bearish_pattern = None, None

    if is_green(c0) and is_red(c1) and c0['close'] > c1['open'] and c0['open'] < c1['close']:
        bullish_pattern = "Bullish Engulfing"
    elif lower_wick(c0) > (2 * body(c0)) and upper_wick(c0) <= (0.3 * body(c0)):
        bullish_pattern = "Hammer Pattern"
    elif abs(c0['low'] - c1['low']) / c0['close'] < 0.0015 and is_red(c1) and is_green(c0):
        bullish_pattern = "Tweezer Bottom"

    if is_red(c0) and is_green(c1) and c0['close'] < c1['open'] and c0['open'] > c1['close']:
        bearish_pattern = "Bearish Engulfing"
    elif abs(c0['high'] - c1['high']) / c0['close'] < 0.0015 and is_green(c1) and is_red(c0):
        bearish_pattern = "Tweezer Top"

    return bullish_pattern, bearish_pattern

def check_choch_bullish(df_15m):
    return df_15m.iloc[-2]['close'] > df_15m['high'].iloc[:-2].tail(10).max()

def check_choch_bearish(df_15m):
    return df_15m.iloc[-2]['close'] < df_15m['low'].iloc[:-2].tail(10).min()

async def analyze_market(mexc, gate, symbol):
    df_4h = await fetch_ohlcv(mexc, gate, symbol, '4h', limit=300)
    df_1h = await fetch_ohlcv(mexc, gate, symbol, '1h', limit=300)
    df_15m = await fetch_ohlcv(mexc, gate, symbol, '15m', limit=150)

    if df_4h is None or df_1h is None or df_15m is None:
        return None, 0

    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)
    df_15m['EMA_50'] = ta.trend.ema_indicator(df_15m['close'], window=50)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()

    closed_1h = df_1h.iloc[-2]
    closed_15m = df_15m.iloc[-2]
    close_price, atr = closed_15m['close'], closed_15m['ATR']

    strong_support = min(df_4h['low'].iloc[:-1].tail(50).min(), df_1h['low'].iloc[:-1].tail(30).min())
    strong_resistance = max(df_4h['high'].iloc[:-1].tail(50).max(), df_1h['high'].iloc[:-1].tail(30).max())

    double_bottom, double_top = detect_chart_patterns(df_15m)
    recent_low_sweep = closed_15m['low'] < df_15m['low'].iloc[:-3].tail(15).min()
    recent_high_sweep = closed_15m['high'] > df_15m['high'].iloc[:-3].tail(15).max()
    bullish_15m, bearish_15m = detect_candlestick_patterns(df_15m)

    has_bullish_choch = check_choch_bullish(df_15m)
    has_bearish_choch = check_choch_bearish(df_15m)
    
    # Institutional Volume Requirement (1.2x Average Volume)
    has_strong_volume = closed_15m['volume'] >= (closed_15m['Vol_MA'] * 1.2)

    at_strong_res = (strong_resistance - close_price) / close_price < 0.012
    at_strong_supp = (close_price - strong_support) / close_price < 0.012

    confidence_score = 0
    reasons = []
    signal_type = None

    # STRICT LONG SETUP (Requires 80%+ Score)
    if (closed_1h['close'] > closed_1h['EMA_50']) and has_bullish_choch and has_strong_volume:
        confidence_score += 35
        reasons.append("SMC Structure: Bullish CHOCH Confirmed (15m)")
        reasons.append("Institutional Volume: Above 1.2x Average")

        if at_strong_supp:
            confidence_score += 20
            reasons.append("SMC Zone: HTF Strong Demand Block")
        if double_bottom:
            confidence_score += 15
            reasons.append("Pattern: W-Pattern Formed")
        if recent_low_sweep:
            confidence_score += 15
            reasons.append("Liquidity: Sell-Side Liquidity Swept")
        if bullish_15m:
            confidence_score += 10
            reasons.append(f"Candlestick: {bullish_15m}")

        if confidence_score >= 80:
            signal_type = "FUTURE LONG 🚀" if confidence_score >= 85 else "SPOT BUY 🛒"

    # STRICT SHORT SETUP (Requires 85%+ Score - High Quality Reversal or Continuation)
    elif (has_bearish_choch or (at_strong_res and bearish_15m)) and has_strong_volume:
        confidence_score += 35
        reasons.append("SMC Structure: Bearish Breakdown/Reversal Confirmed")
        reasons.append("Institutional Volume: Above 1.2x Average")

        if at_strong_res:
            confidence_score += 20
            reasons.append("SMC Zone: HTF Strong Supply/Resistance Block")
        if double_top:
            confidence_score += 15
            reasons.append("Pattern: M-Pattern Formed")
        if recent_high_sweep:
            confidence_score += 15
            reasons.append("Liquidity: Buy-Side Liquidity Swept")
        if bearish_15m:
            confidence_score += 10
            reasons.append(f"Candlestick: {bearish_15m}")

        if confidence_score >= 85:
            signal_type = "FUTURE SHORT 📉"

    if signal_type:
        if "BUY" in signal_type or "LONG" in signal_type:
            sl = close_price - (atr * 2.0)
            risk = close_price - sl
            tp1, tp2, tp3 = close_price + (risk * 1.8), close_price + (risk * 2.8), close_price + (risk * 4.0)
        else:
            sl = close_price + (atr * 2.0)
            risk = sl - close_price
            tp1, tp2, tp3 = close_price - (risk * 1.8), close_price - (risk * 2.8), close_price - (risk * 4.0)

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
        }, confidence_score

    return None, confidence_score

async def market_scanner():
    print("=== STARTING PRECISION SMC SIGNAL & PAPER TRADING SCANNER ===", flush=True)
    send_telegram_message("🎯 Precision Crypto Signal Engine Active (Strict High Quality Mode)!")

    mexc = ccxt.mexc({'enableRateLimit': True})
    gate = ccxt.gate({'enableRateLimit': True})

    try:
        while True:
            current_time = time.time()
            await check_active_paper_trades(mexc, gate)

            for index, symbol in enumerate(TOP_COINS, start=1):
                signal_data, current_score = await analyze_market(mexc, gate, symbol)

                if signal_data:
                    signal_type = signal_data['signal_type']
                    signal_key = f"{symbol}_{signal_type}"

                    if (current_time - SENT_SIGNALS.get(signal_key, 0)) >= COOLDOWN_SECONDS:
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
                        execute_paper_trade(signal_data)

                await asyncio.sleep(0.3)

            await asyncio.sleep(120)

    finally:
        await mexc.close()
        await gate.close()

if __name__ == '__main__':
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

    while True:
        try:
            asyncio.run(market_scanner())
        except Exception as e:
            print(f"[CRITICAL ERROR] Scanner crashed: {e}. Restarting in 10 seconds...", flush=True)
            time.sleep(10)
