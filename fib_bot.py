"""
fib_bot.py - Fibonacci retracement ALERT bot (alerts only, no trading).
Works in Pydroid 3: uses only the Python standard library.

Idea: find the latest swing (high/low), wait for price to pull back into
the 0.5-0.618 zone, and alert when the candle closes back in trend direction.
"""
import json, os, urllib.request, urllib.parse

PAIRS = {"EUR/USD": "EURUSD=X", "Gold": "GC=F"}
INTERVAL, RANGE = "1h", "30d"
SWING = 5          # candles each side to confirm a swing point
MIN_RR = 1.0       # minimum risk-reward to TP1
ZONE = (0.5, 0.618)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def get_candles(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol)
           + f"?interval={INTERVAL}&range={RANGE}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))
    r = data["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    rows = [(o, h, l, c) for o, h, l, c in
            zip(q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, l, c)]
    return rows


def swings(c):
    """Return list of (index, 'H'/'L', price) confirmed swing points."""
    out = []
    for i in range(SWING, len(c) - SWING):
        hi = c[i][1]
        lo = c[i][2]
        if all(hi >= c[j][1] for j in range(i - SWING, i + SWING + 1)):
            out.append((i, "H", hi))
        elif all(lo <= c[j][2] for j in range(i - SWING, i + SWING + 1)):
            out.append((i, "L", lo))
    return out


def analyse(name, c):
    sw = swings(c)
    if len(sw) < 2:
        return None
    (i1, t1, p1), (i2, t2, p2) = sw[-2], sw[-1]
    if t1 == t2:
        return None
    o, h, l, close = c[-1]
    rng = abs(p2 - p1)
    if rng == 0:
        return None

    if t1 == "L" and t2 == "H":      # up-swing -> look for BUY pullback
        side = "BUY"
        z_hi = p2 - rng * ZONE[0]
        z_lo = p2 - rng * ZONE[1]
        touched = l <= z_hi and close >= z_lo and close > o
        entry, sl = close, p2 - rng * 0.786 - rng * 0.05
        tp1, tp2 = p2, p2 + rng * 0.272
        if close < sl:
            return None
    else:                            # down-swing -> look for SELL pullback
        side = "SELL"
        z_lo = p2 + rng * ZONE[0]
        z_hi = p2 + rng * ZONE[1]
        touched = h >= z_lo and close <= z_hi and close < o
        entry, sl = close, p2 + rng * 0.786 + rng * 0.05
        tp1, tp2 = p2, p2 - rng * 0.272
        if close > sl:
            return None

    if not touched:
        return None
    risk = abs(entry - sl)
    rr = abs(tp1 - entry) / risk if risk else 0
    if rr < MIN_RR:
        return None
    d = 5 if name == "EUR/USD" else 2
    return (f"FIB {side} {name} ({INTERVAL})\n"
            f"Entry: {entry:.{d}f}\nStop: {sl:.{d}f}\n"
            f"TP1: {tp1:.{d}f}\nTP2: {tp2:.{d}f}\nRR to TP1: {rr:.2f}")


def send(text):
    print(text, "\n")
    if not (TOKEN and CHAT):
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
    urllib.request.urlopen(url, data=body, timeout=20)


def main():
    found = 0
    for name, sym in PAIRS.items():
        try:
            msg = analyse(name, get_candles(sym))
        except Exception as e:
            print(f"{name}: error {e}")
            continue
        if msg:
            found += 1
            send(msg)
        else:
            print(f"{name}: no FIB setup")
    if not found:
        print("No alerts this run.")


if __name__ == "__main__":
    main()
  
