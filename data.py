"""
data.py — Price data loader for the strategy backtester.

Loading order for each ticker:
  1. A local cache CSV in ./data_cache/<TICKER>.csv (fast, offline, reproducible).
  2. yfinance download from Yahoo Finance (requires internet), then cached.
  3. If both fail AND --allow-synthetic is set, a synthetic random-walk series
     so the engine can be demonstrated offline. Synthetic data is NOT real and
     must never be used to judge a real strategy — it exists only to prove the
     backtest math runs.

Columns returned (a pandas DataFrame indexed by date):
    Open, High, Low, Close, Volume
"""

from __future__ import annotations

import os
import sys
import numpy as np
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")


def _cache_path(ticker: str) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.upper()}.csv")


def _load_from_cache(ticker: str) -> pd.DataFrame | None:
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return _normalize(df, ticker)


def _save_to_cache(ticker: str, df: pd.DataFrame) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(_cache_path(ticker))


def _load_from_yfinance(ticker: str, start: str, end: str | None) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        df = yf.download(
            ticker, start=start, end=end, progress=False, auto_adjust=True
        )
    except Exception as exc:  # network blocked, bad ticker, etc.
        print(f"  yfinance download failed for {ticker}: {exc}", file=sys.stderr)
        return None
    if df is None or len(df) == 0:
        return None
    # yfinance may return a MultiIndex column frame for a single ticker.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return _normalize(df, ticker)


def _make_synthetic(ticker: str, start: str, end: str | None, seed: int) -> pd.DataFrame:
    """Deterministic geometric random walk. Same ticker+seed => same data."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.today().normalize()
    days = pd.bdate_range(start_ts, end_ts)
    n = len(days)
    # Seed off the ticker name so different tickers look different but stable.
    rng = np.random.default_rng(seed + (abs(hash(ticker.upper())) % 100_000))
    mu, sigma = 0.0003, 0.02  # ~daily drift and vol, roughly equity-like
    rets = rng.normal(mu, sigma, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    intraday = np.abs(rng.normal(0, sigma / 2, n))
    high = close * (1 + intraday)
    low = close * (1 - intraday)
    open_ = np.concatenate([[close[0]], close[:-1]]) * (
        1 + rng.normal(0, sigma / 4, n)
    )
    vol = rng.integers(1_000_000, 10_000_000, n)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=days,
    )
    return _normalize(df, ticker)


def _normalize(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    df = df.rename(columns={c: str(c).title() for c in df.columns})
    needed = ["Open", "High", "Low", "Close"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: data missing columns {missing}")
    if "Volume" not in df.columns:
        df["Volume"] = np.nan
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


def load_prices(
    ticker: str,
    start: str = "2015-01-01",
    end: str | None = None,
    allow_synthetic: bool = False,
    seed: int = 42,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Return an OHLCV DataFrame for `ticker`, trying cache -> yfinance -> synthetic."""
    ticker = ticker.upper()

    if use_cache:
        cached = _load_from_cache(ticker)
        if cached is not None and len(cached) > 0:
            return cached.loc[start:end] if end else cached.loc[start:]

    live = _load_from_yfinance(ticker, start, end)
    if live is not None and len(live) > 0:
        _save_to_cache(ticker, live)
        return live

    if allow_synthetic:
        print(
            f"  WARNING: using SYNTHETIC data for {ticker}. Results are meaningless "
            f"for real trading — this only proves the engine runs.",
            file=sys.stderr,
        )
        return _make_synthetic(ticker, start, end, seed)

    raise RuntimeError(
        f"Could not load real data for {ticker}. No cache, and the network download "
        f"failed (are you online / behind a proxy?). Re-run with --allow-synthetic "
        f"to demo the engine on fake data, or drop a CSV at {_cache_path(ticker)}."
    )
