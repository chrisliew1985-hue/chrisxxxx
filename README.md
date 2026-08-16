# Short-Hold Strategy Backtester

A small, honest tool to test the idea: **"buy a stock and sell it within a few
days for a quick ~10% profit."**

It does **not** tell you what to buy today, and it makes no predictions. What it
does is let you run that idea against *years of real historical data* and see —
in plain numbers — how often it would actually have won versus lost. For a
retail trader, understanding the odds of your own idea is the only real edge
available. A confident daily "pick" is not.

## The honest bottom line (before you even run it)

A stock that *can* move +10% in 3 days is, by definition, volatile enough to
move **−10% in 3 days** just as easily. Short holding windows are dominated by
noise, not skill. When you run this on real, liquid stocks you will almost
always find:

- the +10%-in-3-days target is hit only a small fraction of the time,
- after a realistic stop-loss and trading costs, the average trade is roughly a
  coin flip or **negative**,
- and "buy and hold" usually beats the frantic in-and-out version.

That is the lesson this tool is built to let you verify with your own eyes,
rather than take on faith.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Test the pure "just buy something every day and flip it in 3 days" idea on Apple:

```bash
python backtester.py --ticker AAPL --strategy everyday --hold 3 --target 10 --stop 5
```

Test a momentum version across several stocks:

```bash
python backtester.py -t AAPL MSFT NVDA TSLA -s momentum --hold 3 --target 10 --stop 5
```

Save every simulated trade to a CSV so you can inspect it in a spreadsheet:

```bash
python backtester.py -t NVDA -s breakout --save-trades nvda_trades.csv
```

### Options

| Flag | Meaning | Default |
|------|---------|---------|
| `--ticker`, `-t` | One or more symbols | `AAPL` |
| `--strategy`, `-s` | `everyday`, `momentum`, `breakout`, `dip` | `everyday` |
| `--hold` | Max trading days to hold | `3` |
| `--target` | Take-profit target, % | `10` |
| `--stop` | Stop-loss, % | `5` |
| `--cost` | Round-trip cost (commission + slippage), % | `0.2` |
| `--start` / `--end` | Date range of history | `2015-01-01` / today |
| `--lookback` | Window for momentum/breakout/dip | `20` |
| `--drop` | Drop threshold for the `dip` signal, % | `5` |
| `--save-trades` | Write full trade log to a CSV | off |
| `--allow-synthetic` | If data can't be fetched, use fake data to demo the engine | off |
| `--no-cache` | Ignore the local CSV cache | off |

## How the simulation works (and why it's fair, not rosy)

- A signal is evaluated on the **close** of a day.
- You **enter at the next day's open** — you can't trade at a price you're still
  using to make the decision. Backtests that enter at the signal's own close are
  cheating, and they inflate results.
- You hold up to `--hold` trading days. On each held day the engine checks the
  real intraday High/Low:
  - hit the take-profit price → exit at target,
  - hit the stop-loss price → exit at stop,
  - **if both happen on the same day, it assumes the stop hit first** (the
    pessimistic assumption — reality is rarely more generous),
  - otherwise, exit at the close of the final held day (a "time stop").
- Every trade pays `--cost`% round-trip for commission and slippage.

## What the report tells you

- **Hit +target% in window** — how often your dream actually happened. This is
  the direct reality check on "10% in 3 days."
- **Win rate** and **average trade (expectancy)** — expectancy is the number
  that decides whether you make or lose money over many trades.
- **Compounded return vs. buy & hold**, plus **max drawdown** — using only
  non-overlapping trades, so the equity curve reflects real capital.
- A plain-English **verdict**.

## Data

Data loads in this order: local cache CSV → `yfinance` (Yahoo Finance, needs
internet) → synthetic (only with `--allow-synthetic`, for offline demos).
Downloaded data is cached under `data_cache/` so re-runs are fast and offline.

You can also supply your own data by dropping a CSV at
`data_cache/<TICKER>.csv` with a date index and `Open,High,Low,Close,Volume`
columns.

## Tests

```bash
python test_backtester.py
```

These verify the trade engine on hand-built data where the correct answer is
known by construction (entry timing, target/stop/time-stop exits, the
stop-first rule, cost handling, compounding, and drawdown).

## A note on what this is for

This is a **learning and risk-awareness tool.** Use it to stress-test ideas and,
most likely, to talk yourself *out* of strategies that only sound good. Nothing
here is financial advice, and past performance never guarantees future results.
If you want to grow money, the boring, well-evidenced answer — broad,
low-cost, diversified investing held for years — beats short-term trading for
almost everyone. This tool exists to help you see why, on your own terms.
