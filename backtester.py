#!/usr/bin/env python3
"""
backtester.py — Test the "buy today, sell within a few days for a quick %" idea
against real historical data, honestly.

The whole point of this tool is to let you SEE, on years of real data, how often
a short-hold / take-profit strategy actually wins vs. loses — before you risk a
cent. It does not predict the future and it will not tell you what to buy today.
It tells you how an idea WOULD have performed, which is the only honest edge a
retail trader can get.

Trade model (deliberately realistic, not rosy):
  - A signal is evaluated on the CLOSE of day t.
  - You ENTER at the OPEN of day t+1 (you cannot trade at a close you are still
    using to decide — pretending otherwise is how backtests lie to you).
  - You then hold up to `--hold` trading days. On each held day:
      * if the day's HIGH reaches your take-profit price  -> exit at target,
      * if the day's LOW  reaches your stop-loss price     -> exit at stop,
      * if BOTH happen on the same day, we assume the STOP hit first (the
        conservative, pessimistic assumption — real life is rarely kinder).
  - If neither triggers within the hold window, you exit at the CLOSE of the
    last held day ("time stop").
  - Every trade pays `--cost` in round-trip costs (commission + slippage), in %.

Metrics reported:
  - How often the +target% was actually reached inside the hold window
    (this is the reality check on "10% in 3 days").
  - Win rate, average / median / best / worst trade return.
  - Expectancy per trade (the number that actually decides if you make money).
  - A compounded equity curve using only NON-OVERLAPPING trades, with max
    drawdown, compared against simply buying and holding the stock.

Run `python backtester.py --help` for options.
"""

from __future__ import annotations

import argparse
import sys
import numpy as np
import pandas as pd

from data import load_prices


# --------------------------------------------------------------------------- #
# Signals: given an OHLCV frame, return a boolean Series — True on days where a
# trade may be entered (evaluated on that day's close; entry is next open).
# --------------------------------------------------------------------------- #
def signal_everyday(df: pd.DataFrame, **_) -> pd.Series:
    """Enter every single day. The pure 'just pick something daily' baseline."""
    return pd.Series(True, index=df.index)


def signal_momentum(df: pd.DataFrame, lookback: int = 20, **_) -> pd.Series:
    """Enter when today's close is above its N-day moving average (uptrend)."""
    ma = df["Close"].rolling(lookback).mean()
    return df["Close"] > ma


def signal_breakout(df: pd.DataFrame, lookback: int = 20, **_) -> pd.Series:
    """Enter when today's close is a new N-day high (momentum breakout)."""
    prior_high = df["Close"].shift(1).rolling(lookback).max()
    return df["Close"] >= prior_high


def signal_dip(df: pd.DataFrame, lookback: int = 5, drop_pct: float = 5.0, **_) -> pd.Series:
    """Enter after a sharp drop of >= drop_pct% over the last N days (mean reversion)."""
    change = df["Close"] / df["Close"].shift(lookback) - 1.0
    return change <= -(drop_pct / 100.0)


SIGNALS = {
    "everyday": signal_everyday,
    "momentum": signal_momentum,
    "breakout": signal_breakout,
    "dip": signal_dip,
}


# --------------------------------------------------------------------------- #
# Core simulation
# --------------------------------------------------------------------------- #
def simulate(
    df: pd.DataFrame,
    signal: pd.Series,
    hold: int,
    target_pct: float,
    stop_pct: float,
    cost_pct: float,
) -> pd.DataFrame:
    """Return a DataFrame of individual trades with entry/exit and net return."""
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    dates = df.index
    sig = signal.reindex(df.index).fillna(False).to_numpy()

    tp = target_pct / 100.0
    sl = stop_pct / 100.0
    cost = cost_pct / 100.0
    n = len(df)

    trades = []
    for t in range(n - 1):
        if not sig[t]:
            continue
        entry_i = t + 1  # enter at next open
        entry = o[entry_i]
        if not np.isfinite(entry) or entry <= 0:
            continue
        tp_price = entry * (1 + tp)
        sl_price = entry * (1 - sl)

        exit_i = min(entry_i + hold - 1, n - 1)
        exit_price = c[exit_i]
        outcome = "time_stop"
        hit_target = False

        last = min(entry_i + hold - 1, n - 1)
        for k in range(entry_i, last + 1):
            day_low = lo[k]
            day_high = h[k]
            stop_hit = day_low <= sl_price
            targ_hit = day_high >= tp_price
            if stop_hit and targ_hit:
                # Conservative: assume the stop filled first.
                exit_i, exit_price, outcome = k, sl_price, "stop"
                break
            if stop_hit:
                exit_i, exit_price, outcome = k, sl_price, "stop"
                break
            if targ_hit:
                exit_i, exit_price, outcome, hit_target = k, tp_price, "target", True
                break

        gross = exit_price / entry - 1.0
        net = gross - cost  # round-trip cost
        trades.append(
            {
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_i],
                "days_held": exit_i - entry_i + 1,
                "entry": entry,
                "exit": exit_price,
                "outcome": outcome,
                "hit_target_in_window": hit_target,
                "gross_return_pct": gross * 100,
                "net_return_pct": net * 100,
            }
        )

    return pd.DataFrame(trades)


def non_overlapping_equity(trades: pd.DataFrame, start_equity: float = 10_000.0):
    """Compound only trades that don't overlap (sequential capital), for a real curve."""
    if trades.empty:
        return pd.Series(dtype=float), 0.0, 0
    equity = start_equity
    curve = []
    free_from = pd.Timestamp.min
    used = 0
    for _, tr in trades.sort_values("entry_date").iterrows():
        if tr["entry_date"] < free_from:
            continue  # capital still tied up in a prior trade
        equity *= 1 + tr["net_return_pct"] / 100.0
        curve.append((tr["exit_date"], equity))
        free_from = tr["exit_date"]
        used += 1
    s = pd.Series(dict(curve))
    return s, (equity / start_equity - 1) * 100, used


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    return dd.min() * 100


def buy_and_hold_pct(df: pd.DataFrame) -> float:
    return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def report(ticker, df, trades, args):
    print("=" * 68)
    print(f"  {ticker}   strategy='{args.strategy}'   "
          f"{df.index[0].date()} -> {df.index[-1].date()}  ({len(df)} days)")
    print("=" * 68)
    print(f"  Rule: enter next open, hold up to {args.hold} days, "
          f"take-profit +{args.target}% / stop -{args.stop}%, "
          f"cost {args.cost}%/round-trip")
    print("-" * 68)

    if trades.empty:
        print("  No trades were triggered by this signal over this period.")
        return

    net = trades["net_return_pct"]
    wins = net > 0
    hit = trades["hit_target_in_window"]

    print(f"  Trades taken .................. {len(trades)}")
    print(f"  Hit +{args.target:.0f}% target in window .. "
          f"{hit.mean()*100:5.1f}%   <-- the reality check")
    print(f"  Win rate (net > 0) ........... {wins.mean()*100:5.1f}%")
    print(f"  Average trade (net) .......... {net.mean():+6.2f}%   <-- expectancy")
    print(f"  Median trade (net) ........... {net.median():+6.2f}%")
    print(f"  Best / Worst trade ........... {net.max():+6.2f}% / {net.min():+6.2f}%")
    print(f"  Std dev per trade ............ {net.std():6.2f}%")
    oc = trades["outcome"].value_counts()
    print(f"  Exits: target={oc.get('target',0)}  "
          f"stop={oc.get('stop',0)}  time_stop={oc.get('time_stop',0)}")
    print("-" * 68)

    equity, total_ret, used = non_overlapping_equity(trades)
    bh = buy_and_hold_pct(df)
    print(f"  Compounded over {used} non-overlapping trades:")
    print(f"    Strategy total return ...... {total_ret:+7.1f}%")
    print(f"    Max drawdown ............... {max_drawdown_pct(equity):+7.1f}%")
    print(f"    Buy & hold {ticker} same period {bh:+7.1f}%")
    print("-" * 68)

    exp = net.mean()
    if exp <= 0:
        verdict = ("NEGATIVE expectancy — this loses money on average. "
                   "Every trade is a coin flip you pay to play.")
    elif exp < args.cost:
        verdict = ("Barely positive and smaller than your trading costs' margin "
                   "for error — fragile, likely noise.")
    else:
        verdict = ("Positive expectancy in THIS backtest. Verify on other tickers "
                   "and periods before trusting it; past results != future.")
    print(f"  VERDICT: {verdict}")
    print("=" * 68)

    if args.save_trades:
        trades.to_csv(args.save_trades, index=False)
        print(f"  Full trade log written to {args.save_trades}")


# --------------------------------------------------------------------------- #
def build_signal(name, df, args) -> pd.Series:
    fn = SIGNALS[name]
    return fn(df, lookback=args.lookback, drop_pct=args.drop)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Honestly backtest a short-hold, quick-profit stock idea.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--ticker", "-t", nargs="+", default=["AAPL"],
                   help="One or more ticker symbols, e.g. -t AAPL MSFT NVDA")
    p.add_argument("--strategy", "-s", choices=list(SIGNALS), default="everyday",
                   help="Entry signal to test")
    p.add_argument("--hold", type=int, default=3, help="Max trading days to hold")
    p.add_argument("--target", type=float, default=10.0, help="Take-profit target %%")
    p.add_argument("--stop", type=float, default=5.0, help="Stop-loss %%")
    p.add_argument("--cost", type=float, default=0.2,
                   help="Round-trip cost %% (commission + slippage)")
    p.add_argument("--start", default="2015-01-01", help="History start date")
    p.add_argument("--end", default=None, help="History end date (default: today)")
    p.add_argument("--lookback", type=int, default=20,
                   help="Lookback window for momentum/breakout/dip signals")
    p.add_argument("--drop", type=float, default=5.0,
                   help="Drop %% threshold for the 'dip' signal")
    p.add_argument("--allow-synthetic", action="store_true",
                   help="If real data can't be fetched, use fake data to demo the engine")
    p.add_argument("--no-cache", action="store_true", help="Ignore local CSV cache")
    p.add_argument("--save-trades", default=None,
                   help="Write the full per-trade log to this CSV path")
    args = p.parse_args(argv)

    for ticker in args.ticker:
        try:
            df = load_prices(
                ticker, start=args.start, end=args.end,
                allow_synthetic=args.allow_synthetic, use_cache=not args.no_cache,
            )
        except Exception as exc:
            print(f"[{ticker}] {exc}", file=sys.stderr)
            continue
        if len(df) < args.hold + 2:
            print(f"[{ticker}] not enough data ({len(df)} rows).", file=sys.stderr)
            continue
        sig = build_signal(args.strategy, df, args)
        trades = simulate(df, sig, args.hold, args.target, args.stop, args.cost)
        report(ticker, df, trades, args)
        print()


if __name__ == "__main__":
    main()
