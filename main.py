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
    return "Institutional SMC Engine v3 (News Shield + BTC Correlation Active)!", 200

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
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
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
    """Gano High-Impact News da ke tafe ta CryptoPanic & News APIs"""
    try:
        # CryptoPanic free public news endpoint
        url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&filter=important"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            for post in results[:5]:
                title = post.get('title', '').lower()
                # Tace hot news keywords
                if any(kw in title for kw in ['cpi', 'fomc', 'sec', 'fed rate', 'binance', 'inflation', 'crackdown']):
                    return True, post.get('title')
    except Exception:
        pass
    return False, None

def execute_paper_trade(signal_data):
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
        f"💰 **Capital:** ${allocated_capital:,.2f}\n"
        f"📥 **Entry:** {signal_data['entry']}\n"
        f"🛑 **Stop Loss:** {signal_data['sl']}\n"
        f"🎯 **Target TP1:** {signal_data['tp1']}\n"
        f"🎯 **Target TP2:** {signal_data['tp2']}\n"
        f"🎯 **Target TP3:** {signal_data['tp3']}\n"
        f"⏱️ **Time:** {trade['open_time']}\n\n"
        f"💡 **Confirmations:**\n{reasons_formatted}"
    )
    send_telegram_message(paper_msg)

async def check_active_paper_trades(mexc, gate):
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
            elif current_price >= trade['tp3']:
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

async def check_order_book_analysis(mexc, gate, symbol):
    try:
        ob = await mexc.fetch_order_book(symbol, limit=20)
    except Exception:
        try:
            ob = await gate.fetch_order_book(symbol, limit=20)
        except Exception:
            return 1.0, 0

    total_bids = sum([b[1] for b in ob['bids']])
    total_asks = sum([a[1] for a in ob['asks']])

    if total_asks == 0:
        return 1.0, total_bids

    ratio = total_bids / total_asks
    return ratio, (total_bids + total_asks)

async def get_btc_trend(mexc, gate):
    df_btc = await fetch_ohlcv(mexc, gate, 'BTC/USDT', '1h', limit=100)
    if df_btc is None:
        return "NEUTRAL"

    df_btc['EMA_50'] = ta.trend.ema_indicator(df_btc['close'], window=50)
    closed = df_btc.iloc[-2]

    if closed['close'] > closed['EMA_50']:
        return "BULLISH"
    elif closed['close'] < closed['EMA_50']:
        return "BEARISH"
    return "NEUTRAL"

async def analyze_market(mexc, gate, symbol, btc_trend):
    df_4h = await fetch_ohlcv(mexc, gate, symbol, '4h', limit=300)
    df_1h = await fetch_ohlcv(mexc, gate, symbol, '1h', limit=300)
    df_15m = await fetch_ohlcv(mexc, gate, symbol, '15m', limit=150)

    if df_4h is None or df_1h is None or df_15m is None:
        return None, 0

    df_1h['EMA_50'] = ta.trend.ema_indicator(df_1h['close'], window=50)
    df_15m['EMA_50'] = ta.trend.ema_indicator(df_15m['close'], window=50)
    df_15m['RSI'] = ta.momentum.rsi(df_15m['close'], window=14)
    df_15m['ATR'] = ta.volatility.average_true_range(df_15m['high'], df_15m['low'], df_15m['close'], window=14)
    df_15m['Vol_MA'] = df_15m['volume'].rolling(window=20).mean()

    closed_1h = df_1h.iloc[-2]
    closed_15m = df_15m.iloc[-2]
    close_price, atr, rsi = closed_15m['close'], closed_15m['ATR'], closed_15m['RSI']

    ob_ratio, ob_volume = await check_order_book_analysis(mexc, gate, symbol)

    strong_support = min(df_4h['low'].iloc[:-1].tail(50).min(), df_1h['low'].iloc[:-1].tail(30).min())
    strong_resistance = max(df_4h['high'].iloc[:-1].tail(50).max(), df_1h['high'].iloc[:-1].tail(30).max())

    at_strong_supp = (close_price - strong_support) / close_price < 0.015
    at_strong_res = (strong_resistance - close_price) / close_price < 0.015
    has_strong_volume = closed_15m['volume'] >= (closed_15m['Vol_MA'] * 1.2)

    confidence_score_long = 0
    reasons_long = []

    confidence_score_short = 0
    reasons_short = []

    # LONG CONFLUENCE
    if closed_15m['close'] > closed_15m['EMA_50']:
        confidence_score_long += 20
        reasons_long.append("15m Trend: Above EMA 50")

    if has_strong_volume:
        confidence_score_long += 15
        reasons_long.append("Volume: Institutional Volume Spike (>1.2x)")

    if rsi < 40:
        confidence_score_long += 15
        reasons_long.append(f"RSI Momentum: Oversold Zone ({rsi:.1f})")

    if at_strong_supp:
        confidence_score_long += 20
        reasons_long.append("SMC Zone: HTF Strong Demand Block")

    if ob_ratio >= 1.3:
        confidence_score_long += 15
        reasons_long.append(f"Order Book: Strong Buyer Support ({ob_ratio:.1f}x)")

    # SHORT CONFLUENCE
    if closed_15m['close'] < closed_15m['EMA_50']:
        confidence_score_short += 20
        reasons_short.append("15m Trend: Below EMA 50")

    if has_strong_volume:
        confidence_score_short += 15
        reasons_short.append("Volume: Institutional Volume Spike (>1.2x)")

    if rsi > 60:
        confidence_score_short += 15
        reasons_short.append(f"RSI Momentum: Overbought Zone ({rsi:.1f})")

    if at_strong_res:
        confidence_score_short += 20
        reasons_short.append("SMC Zone: HTF Strong Supply Block")

    if ob_ratio <= 0.7:
        confidence_score_short += 15
        reasons_short.append(f"Order Book: Heavy Selling Pressure ({ob_ratio:.1f}x)")

    is_btc_dependent = symbol in BTC_CORRELATED_COINS

    signal_type = None
    final_score = 0
    final_reasons = []

    if confidence_score_long >= 80:
        if not is_btc_dependent or (is_btc_dependent and btc_trend == "BULLISH"):
            signal_type = "FUTURE LONG 🚀" if confidence_score_long >= 85 else "SPOT BUY 🛒"
            final_score = confidence_score_long
            final_reasons = reasons_long
            if is_btc_dependent:
                final_reasons.append("BTC Alignment: BTC in Uptrend")

    elif confidence_score_short >= 85:
        if not is_btc_dependent or (is_btc_dependent and btc_trend == "BEARISH"):
            signal_type = "FUTURE SHORT 📉"
            final_score = confidence_score_short
            final_reasons = reasons_short
            if is_btc_dependent:
                final_reasons.append("BTC Alignment: BTC in Downtrend")

    current_max_score = max(confidence_score_long, confidence_score_short)

    if signal_type:
        if "BUY" in signal_type or "LONG" in signal_type:
            sl = close_price - (atr * 2.5)
            risk = close_price - sl
            tp1, tp2, tp3 = close_price + (risk * 1.8), close_price + (risk * 2.8), close_price + (risk * 4.0)
        else:
            sl = close_price + (atr * 2.5)
            risk = sl - close_price
            tp1, tp2, tp3 = close_price - (risk * 1.8), close_price - (risk * 2.8), close_price - (risk * 4.0)

        return {
            'symbol': symbol,
            'signal_type': signal_type,
            'confidence': f"{final_score}%",
            'entry': format_price(close_price),
            'tp1': format_price(tp1),
            'tp2': format_price(tp2),
            'tp3': format_price(tp3),
            'sl': format_price(sl),
            'reasons': final_reasons
        }, final_score

    return None, current_max_score

async def market_scanner():
    print("=== STARTING PRECISION SMC SIGNAL ENGINE V3 (NEWS SHIELD ACTIVE) ===", flush=True)
    send_telegram_message("🎯 Precision Crypto Signal Engine Active (News Shield Protection Engaged)!")

    mexc = ccxt.mexc({'enableRateLimit': True})
    gate = ccxt.gate({'enableRateLimit': True})

    while True:
        try:
            current_time = time.time()
            await check_active_paper_trades(mexc, gate)

            # MATAKI NA 1: DUBUN LABARAI (NEWS CHECK)
            has_news, news_title = check_high_impact_news()
            if has_news:
                print(f"⚠️ [NEWS SHIELD ACTIVE] High-Impact Event Detected: '{news_title}'. Pausing scanner cycle!", flush=True)
                send_telegram_message(f"⚠️ **NEWS SHIELD PROTECT** ⚠️\n\nHigh Impact News Event Detected: *{news_title}*\n\nPausing market scanning for safety.")
                await asyncio.sleep(600)  # Tsaya na minti 10 sannan ka sake duba labarai
                continue

            # MATAKI NA 2: DUBUN BTC TREND
            btc_trend = await get_btc_trend(mexc, gate)
            print(f"--- CURRENT BTC MARKET TREND: {btc_trend} ---", flush=True)

            # MATAKI NA 3: SCANNING NA COINS
            for index, symbol in enumerate(TOP_COINS, start=1):
                try:
                    signal_data, current_score = await analyze_market(mexc, gate, symbol, btc_trend)

                    print(f"[{index}/{len(TOP_COINS)}] Scanned {symbol} | Confluence Score: {current_score}%", flush=True)

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
