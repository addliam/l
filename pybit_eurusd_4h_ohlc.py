"""
Download EURUSD OHLC candles (4h timeframe) from Bybit using pybit.

Install:
    pip install pybit pandas

Usage:
    python pybit_eurusd_4h_ohlc.py
    python pybit_eurusd_4h_ohlc.py --start 2026-01-01 --end 2026-09-24 --out eurusd_4h.csv

Notes
-----
- Bybit's v5 REST API is used via pybit.unified_trading.HTTP.
- Kline endpoint: GET /v5/market/kline
  https://bybit-exchange.github.io/docs/v5/market/kline
- interval="240" is the 4-hour candle (Bybit intervals are in minutes for
  numeric values: 1,3,5,15,30,60,120,240,360,720, plus D/W/M).
- A single call returns at most 1000 candles, so long ranges are paginated
  by walking the `end` cursor backwards to the oldest candle of each batch.
- EURUSD may not exist under every `category`. Bybit added FX majors as
  linear perpetuals (symbolType "forex"); if `--category linear` returns no
  data for EURUSD, run instruments_info() below to confirm the symbol is
  currently listed and under which category, since listings change.
"""

import argparse
import time
from datetime import datetime, timezone

from pybit.unified_trading import HTTP


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def check_symbol_listed(session: HTTP, category: str, symbol: str) -> None:
    info = session.get_instruments_info(category=category, symbol=symbol)
    rows = info.get("result", {}).get("list", [])
    if not rows:
        raise SystemExit(
            f"{symbol} not found under category={category!r}. "
            "List instruments (no symbol filter) to find the correct "
            "category/name, e.g. session.get_instruments_info(category='linear')."
        )


def fetch_ohlc(
    symbol: str = "EURUSD",
    category: str = "linear",
    interval: str = "240",
    start_str: str = "2026-01-01",
    end_str: str | None = None,
    testnet: bool = False,
):
    session = HTTP(testnet=testnet)
    check_symbol_listed(session, category, symbol)

    start_ms = to_ms(start_str)
    end_ms = to_ms(end_str) if end_str else int(time.time() * 1000)

    all_rows = []
    cursor_end = end_ms
    while True:
        resp = session.get_kline(
            category=category,
            symbol=symbol,
            interval=interval,
            start=start_ms,
            end=cursor_end,
            limit=1000,
        )
        rows = resp["result"]["list"]  # newest-first: [startTime, O, H, L, C, volume, turnover]
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = int(rows[-1][0])
        if oldest_ts <= start_ms:
            break
        cursor_end = oldest_ts - 1
        time.sleep(0.1)  # be polite to the rate limit

    # de-dupe, sort ascending, trim to requested start, cast numerics
    by_ts = {int(r[0]): r for r in all_rows}
    ordered = sorted(by_ts.items())
    candles = []
    for ts, (_, o, h, l, c, vol, turnover) in ordered:
        if ts < start_ms:
            continue
        candles.append(
            {
                "timestamp": datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(vol),
                "turnover": float(turnover),
            }
        )
    return candles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--category", default="linear", choices=["linear", "spot", "inverse"])
    parser.add_argument("--interval", default="240", help="4h = 240 (minutes)")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default=None, help="defaults to now (UTC)")
    parser.add_argument("--testnet", action="store_true")
    parser.add_argument("--out", default="eurusd_4h_ohlc.csv")
    args = parser.parse_args()

    candles = fetch_ohlc(
        symbol=args.symbol,
        category=args.category,
        interval=args.interval,
        start_str=args.start,
        end_str=args.end,
        testnet=args.testnet,
    )

    if not candles:
        print("No candles returned.")
        return

    import csv

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(candles[0].keys()))
        writer.writeheader()
        writer.writerows(candles)

    print(f"Wrote {len(candles)} candles to {args.out}")
    print(f"Range: {candles[0]['timestamp']} -> {candles[-1]['timestamp']}")


if __name__ == "__main__":
    main()
