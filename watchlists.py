"""
watchlists.py — ready-made baskets of US-market tickers so you can batch-test
an idea across many stocks with one command (--preset NAME).

These are just convenient starting lists of liquid, well-known US symbols; they
are NOT recommendations. Edit them freely, or pass your own with --ticker.
"""

PRESETS = {
    # Mega-cap US tech — the most-traded names on the US market.
    "megacap": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO",
    ],
    # Higher-volatility US names — the kind people chase for fast 10% moves
    # (and exactly where a stop-loss gets hit most).
    "volatile": [
        "TSLA", "NVDA", "AMD", "PLTR", "COIN", "MARA", "SMCI", "RIVN", "AFRM",
    ],
    # Broad US index / sector ETFs — the "boring" benchmark to beat.
    "index": [
        "SPY", "QQQ", "DIA", "IWM",
    ],
    # A slice of the Dow-style US large caps across sectors.
    "bluechip": [
        "JPM", "JNJ", "WMT", "PG", "XOM", "KO", "HD", "V", "UNH", "DIS",
    ],
}


def resolve(names):
    """Expand a list that may contain preset names OR raw tickers into tickers."""
    out = []
    for n in names:
        key = n.lower()
        if key in PRESETS:
            out.extend(PRESETS[key])
        else:
            out.append(n.upper())
    # de-dup, preserve order
    seen = set()
    result = []
    for t in out:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result
