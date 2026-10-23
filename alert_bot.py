#!/usr/bin/env python3
"""Forex signal ALERTS to Telegram. Never trades, needs no broker login."""
import os
import sys

import pandas as pd
import requests

NAME, SYMBOL = "EUR/USD", "EURUSD=X"
FAST, SLOW, ATR_N, SL_ATR, TP_ATR = 30, 100, 14, 3.0, 6.0
MAX_AGE_MIN = 90   # ignore stale candles (market closed / weekend)


def telegram(text):
    token, chat = os.environ["TELEGRAM_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=30)
    r.raise_for_status()
    print("Telegram message sent.")


def candles():
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}",
                     params=dict(interval="1h", range="60d"),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"time": pd.to_datetime(res["timestamp"], unit="s"),
                       **{k: q[k] for k in ("open", "high", "low", "close")}}).dropna()
    now = pd.Timestamp.now("UTC").tz_localize(None)
    df = df[df["time"] + pd.Timedelta(hours=1) <= now].reset_index(drop=True)
    return df, now


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


def main(mode):
    if mode == "test":
        return telegram("Test alert: your forex alert bot is connected.")
    df, now = candles()
    df = indicators(df)
    last = df.iloc[-1]
    age_min = (now - (last["time"] + pd.Timedelta(hours=1))).total_seconds() / 60
    px = last["close"]

    if mode == "status":
        trend = "UP (fast above slow)" if last["f"] > last["s"] else "DOWN (fast below slow)"
        nz = df.index[df["sig"] != 0]
        recent = (f"{'BUY' if df['sig'][nz[-1]] == 1 else 'SELL'} crossover "
                  f"{len(df) - 1 - nz[-1]} candles ago") if len(nz) else "none found"
        return telegram(f"{NAME} status\nPrice: {px:.5f}\nTrend: {trend}\n"
                        f"Last signal: {recent}\nLatest candle is {age_min:.0f} min old.")

    if age_min > MAX_AGE_MIN:
        return print("Latest candle is old (market closed?). No alert.")
    if last["sig"] == 0:
        return print("No new crossover. No alert.")
    side = int(last["sig"])
    stop, target = px - side * SL_ATR * last["atr"], px + side * TP_ATR * last["atr"]
    telegram(f"{'BUY' if side == 1 else 'SELL'} signal on {NAME} (1h)\n"
             f"Price: {px:.5f}\nSuggested stop: {stop:.5f}\nSuggested target: {target:.5f}\n"
             f"Candle closed: {str(last['time'] + pd.Timedelta(hours=1))[:16]} UTC\n"
             "Alert only. Not financial advice.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "alert")
