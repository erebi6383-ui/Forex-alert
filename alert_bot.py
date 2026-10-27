#!/usr/bin/env python3
"""
Forex signal ALERTS to Telegram for several pairs plus Deriv Step Index.
It never trades and needs no broker login.

Strategy: 1h candles, EMA 30/100 crossover, ATR-based stop/target.

Usage:  python alert_bot.py alert    (message only for pairs with a NEW crossover)
        python alert_bot.py status   (one message with the current trend of every pair)
        python alert_bot.py test     (sends a test message)

Needs env vars TELEGRAM_TOKEN and TELEGRAM_CHAT_ID. Not financial advice.
"""
import json
import os
import sys
import time

import pandas as pd
import requests

PAIRS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "EUR_JPY", "STEP"]
FAST, SLOW, ATR_N, SL_ATR, TP_ATR = 30, 100, 14, 3.0, 6.0
MAX_AGE_MIN = 90   # ignore stale candles (market closed / weekend)

# Deriv synthetic markets: key -> (Deriv symbol, display name)
DERIV = {"STEP": ("stpRNG", "Step Index")}
DERIV_URL = "wss://api.derivws.com/trading/v1/options/ws/public"


def telegram(text):
    token, chat = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=30)
    r.raise_for_status()
    print("Telegram message sent.")


def closed_only(df):
    now = pd.Timestamp.now("UTC").tz_localize(None)
    df = df[df["time"] + pd.Timedelta(hours=1) <= now].reset_index(drop=True)  # closed candles only
    return df, now


def deriv_candles(symbol):
    import websocket   # pip package: websocket-client
    ws = websocket.create_connection(DERIV_URL, timeout=30)
    try:
        ws.send(json.dumps({"ticks_history": symbol, "adjust_start_time": 1, "count": 500,
                            "end": "latest", "granularity": 3600, "style": "candles"}))
        data = json.loads(ws.recv())
    finally:
        ws.close()
    if "error" in data:
        raise RuntimeError(data["error"]["message"])
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["epoch"], unit="s")
    df = df[["time", "open", "high", "low", "close"]].dropna()
    return closed_only(df)


def candles(pair):
    if pair in DERIV:
        return deriv_candles(DERIV[pair][0])
    symbol = pair.replace("_", "") + "=X"
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params=dict(interval="1h", range="60d"),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"time": pd.to_datetime(res["timestamp"], unit="s"),
                       **{k: q[k] for k in ("open", "high", "low", "close")}}).dropna()
    return closed_only(df)


def indicators(df):
    df = df.copy()
    df["f"] = df["close"].ewm(span=FAST, adjust=False).mean()
    df["s"] = df["close"].ewm(span=SLOW, adjust=False).mean()
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()
    d = df["f"] - df["s"]
    df["sig"] = 0
    df.loc[(d > 0) & (d.shift() <= 0), "sig"] = 1
    df.loc[(d < 0) & (d.shift() >= 0), "sig"] = -1
    return df


def check(pair, mode):
    """Return a message string (or None if there is nothing to report)."""
    if pair in DERIV:
        name, dg = DERIV[pair][1], 2
    else:
        name, dg = pair.replace("_", "/"), (3 if "JPY" in pair else 5)
    df, now = candles(pair)
    df = indicators(df)
    last = df.iloc[-1]
    age_min = (now - (last["time"] + pd.Timedelta(hours=1))).total_seconds() / 60
    px = last["close"]

    if mode == "status":
        trend = "UP" if last["f"] > last["s"] else "DOWN"
        nz = df.index[df["sig"] != 0]
        recent = (f"{'BUY' if df['sig'][nz[-1]] == 1 else 'SELL'} {len(df) - 1 - nz[-1]} candles ago"
                  ) if len(nz) else "none found"
        return f"{name}: {px:.{dg}f}, trend {trend}, last signal {recent}"

    if age_min > MAX_AGE_MIN:
        print(f"{name}: latest candle is old (market closed?). No alert.")
        return None
    if last["sig"] == 0:
        print(f"{name}: no new crossover.")
        return None
    side = int(last["sig"])
    stop, target = px - side * SL_ATR * last["atr"], px + side * TP_ATR * last["atr"]
    return (f"{'BUY' if side == 1 else 'SELL'} signal on {name} (1h)\n"
            f"Price: {px:.{dg}f}\nSuggested stop: {stop:.{dg}f}\nSuggested target: {target:.{dg}f}\n"
            f"Candle closed: {str(last['time'] + pd.Timedelta(hours=1))[:16]} UTC\n"
            "Alert only. Not financial advice.")


def main(mode):
    if mode == "test":
        return telegram("Test alert: your forex alert bot is connected.")
    lines, worked = [], 0
    for pair in PAIRS:
        try:
            msg = check(pair, mode)
            worked += 1
        except Exception as e:   # one pair failing must not stop the others
            print(f"{pair}: error: {e}")
            continue
        if msg and mode == "status":
            lines.append(msg)
        elif msg:
            telegram(msg)
        time.sleep(1)
    if lines:
        telegram("Status (1h, EMA 30/100)\n\n" + "\n".join(lines))
    if worked == 0:
        sys.exit("No pair could be checked.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "alert")
