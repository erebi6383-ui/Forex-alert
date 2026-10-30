"""CRT + SMC alert bot (alerts only, no trading).

Rules (simplified, mechanical):
1. CRT candle  = second-last closed H4 candle (its high/low = range)
2. Sweep       = last closed H4 candle breaks one side but closes back inside
3. Confirm     = on M15, a close that breaks the recent 12-candle high (buy)
                 or low (sell) = break of structure (BOS), after the sweep
4. SL beyond the sweep wick, TP1 = 50% of range, TP2 = other side of range
5. Skip the setup if RR to TP2 is below MIN_RR
"""
import os
import pandas as pd
import requests

PAIRS = {"EUR/USD": "EURUSD=X", "Gold": "GC=F"}
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT = os.environ.get("TELEGRAM_CHAT_ID")
LOOKBACK = 12      # M15 candles used to define structure
SCAN = 4           # only alert on BOS within the last 4 closed M15 candles
MIN_RR = 1.0       # minimum reward-to-risk to TP2


def get(sym, interval, period):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    r = requests.get(url, params={"interval": interval, "range": period},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"Open": q["open"], "High": q["high"],
                       "Low": q["low"], "Close": q["close"]},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
    return df.dropna()


def check(name, sym):
    now = pd.Timestamp.now(tz="UTC")
    h1 = get(sym, "1h", "1mo")
    h4 = h1.resample("4h").agg({"Open": "first", "High": "max",
                                "Low": "min", "Close": "last"}).dropna()
    h4 = h4[h4.index + pd.Timedelta(hours=4) <= now]   # closed candles only
    if len(h4) < 2:
        return None
    c1, c2 = h4.iloc[-2], h4.iloc[-1]
    c2_end = h4.index[-1] + pd.Timedelta(hours=4)
    if now > c2_end + pd.Timedelta(hours=4):
        return None   # sweep candle is old, setup expired

    rng = c1.High - c1.Low
    if c2.Low < c1.Low and c1.Low < c2.Close <= c1.High:
        side = "BUY"
    elif c2.High > c1.High and c1.Low <= c2.Close < c1.High:
        side = "SELL"
    else:
        return None

    m = get(sym, "15m", "5d")
    m = m[m.index + pd.Timedelta(minutes=15) <= now]
    n = len(m)
    for i in range(max(n - SCAN, LOOKBACK), n):
        if m.index[i] < c2_end:
            continue
        win = m.iloc[i - LOOKBACK:i]
        close = m.Close.iloc[i]
        if side == "BUY" and close > win.High.max():
            fvg = m.Low.iloc[i] > m.High.iloc[i - 2]
            sl = c2.Low - 0.1 * rng
            tp1, tp2 = c1.Low + 0.5 * rng, c1.High
        elif side == "SELL" and close < win.Low.min():
            fvg = m.High.iloc[i] < m.Low.iloc[i - 2]
            sl = c2.High + 0.1 * rng
            tp1, tp2 = c1.High - 0.5 * rng, c1.Low
        else:
            continue
        risk = abs(close - sl)
        reward1 = abs(tp1 - close)
        reward2 = abs(tp2 - close)
        if (side == "BUY" and tp1 <= close) or (side == "SELL" and tp1 >= close):
            return None   # price already past TP1
        if risk == 0 or reward2 / risk < MIN_RR:
            return None   # not enough room to TP2
        d = 3 if close < 1000 else 2
        return (f"CRT+SMC {side} - {name}\n"
                f"Time: {m.index[i]:%Y-%m-%d %H:%M} UTC\n"
                f"H4 range: {c1.Low:.{d}f} - {c1.High:.{d}f}\n"
                f"Entry: {close:.{d}f}\n"
                f"SL: {sl:.{d}f}\n"
                f"TP1 (50%): {tp1:.{d}f}\n"
                f"TP2: {tp2:.{d}f}\n"
                f"RR to TP1: {reward1 / risk:.1f}\n"
                f"RR to TP2: {reward2 / risk:.1f}\n"
                f"FVG: {'yes' if fvg else 'no'}")
    return None


def send(text):
    if TOKEN and CHAT:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": text}, timeout=20)
    else:
        print(text)   # test mode (e.g. Pydroid 3 without secrets)


if __name__ == "__main__":
    found = False
    for name, sym in PAIRS.items():
        try:
            msg = check(name, sym)
        except Exception as e:
            print(f"{name} error: {e}")
            continue
        if msg:
            found = True
            send(msg)
    if not found:
        print("No CRT+SMC setups right now.")
