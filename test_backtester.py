"""
test_backtester.py — verify the trade engine on hand-built data where the
correct answer is known by construction. Run: python test_backtester.py
"""
import pandas as pd
from backtester import simulate, non_overlapping_equity, max_drawdown_pct


def frame(rows):
    idx = pd.bdate_range("2020-01-01", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"]).assign(Volume=1)


def only(df, i):
    """Signal that fires on exactly one bar index i."""
    s = pd.Series(False, index=df.index)
    s.iloc[i] = True
    return s


def test_target_hit():
    # Signal day 0. Enter at open of day 1 (=100). Day 2 high 111 hits +10% (110).
    df = frame([
        [ 99, 100,  98, 100],   # 0 signal
        [100, 101,  99, 100],   # 1 entry open=100
        [100, 111, 100, 105],   # 2 high 111 >= 110 -> target
        [105, 106, 104, 105],   # 3
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=5, cost_pct=0.0)
    assert len(tr) == 1
    r = tr.iloc[0]
    assert r["outcome"] == "target", r["outcome"]
    assert r["hit_target_in_window"]
    assert abs(r["gross_return_pct"] - 10.0) < 1e-9, r["gross_return_pct"]
    print("PASS test_target_hit")


def test_stop_hit():
    # Enter at open of day 1 (=100). Day 1 low 94 hits -5% (95) -> stop.
    df = frame([
        [ 99, 100,  98, 100],   # 0 signal
        [100, 101,  94,  96],   # 1 entry open=100, low 94 <= 95 -> stop
        [ 96,  97,  95,  96],   # 2
        [ 96,  97,  95,  96],   # 3
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=5, cost_pct=0.0)
    r = tr.iloc[0]
    assert r["outcome"] == "stop", r["outcome"]
    assert not r["hit_target_in_window"]
    assert abs(r["gross_return_pct"] - (-5.0)) < 1e-9, r["gross_return_pct"]
    print("PASS test_stop_hit")


def test_time_stop():
    # Neither target nor stop reached; exit at close of last held day.
    df = frame([
        [ 99, 100,  98, 100],   # 0 signal
        [100, 102,  99, 101],   # 1 entry open=100
        [101, 103, 100, 102],   # 2
        [102, 104, 101, 103],   # 3 last held day, close 103
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=5, cost_pct=0.0)
    r = tr.iloc[0]
    assert r["outcome"] == "time_stop", r["outcome"]
    assert r["days_held"] == 3
    assert abs(r["gross_return_pct"] - 3.0) < 1e-9, r["gross_return_pct"]
    print("PASS test_time_stop")


def test_stop_first_when_both_hit():
    # Same day hits BOTH target and stop -> engine must assume stop first.
    df = frame([
        [ 99, 100,  98, 100],   # 0 signal
        [100, 112,  94, 100],   # 1 high 112>=110 AND low 94<=95 -> stop wins
        [100, 101,  99, 100],   # 2
        [100, 101,  99, 100],   # 3
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=5, cost_pct=0.0)
    r = tr.iloc[0]
    assert r["outcome"] == "stop", r["outcome"]
    assert abs(r["gross_return_pct"] - (-5.0)) < 1e-9
    print("PASS test_stop_first_when_both_hit")


def test_cost_applied():
    df = frame([
        [ 99, 100,  98, 100],
        [100, 100,  99, 100],   # entry open=100
        [100, 100,  99, 100],
        [100, 100,  99, 100],   # flat -> time stop at 100, gross 0
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=5, cost_pct=0.2)
    r = tr.iloc[0]
    assert abs(r["gross_return_pct"] - 0.0) < 1e-9
    assert abs(r["net_return_pct"] - (-0.2)) < 1e-9, r["net_return_pct"]
    print("PASS test_cost_applied")


def test_entry_is_next_open_not_signal_close():
    # Signal close is 100 but next open is 90; entry must be 90.
    df = frame([
        [ 99, 100,  98, 100],   # 0 signal close 100
        [ 90,  99,  89,  95],   # 1 entry open MUST be 90
        [ 95,  96,  94,  95],
        [ 95,  96,  94,  95],
    ])
    tr = simulate(df, only(df, 0), hold=3, target_pct=10, stop_pct=50, cost_pct=0.0)
    r = tr.iloc[0]
    assert abs(r["entry"] - 90.0) < 1e-9, r["entry"]
    print("PASS test_entry_is_next_open_not_signal_close")


def test_equity_and_drawdown():
    # Two sequential non-overlapping trades: +10% then -5% (net, cost 0).
    df = frame([
        [100, 100, 100, 100],   # 0 signal A
        [100, 111, 100, 110],   # 1 entry 100 -> target 110 (+10%)
        [110, 111, 110, 110],   # 2
        [110, 110, 110, 110],   # 3 signal B
        [110, 111, 104, 105],   # 4 entry 110 -> stop at 104.5 (-5%)
        [104, 105, 104, 104],   # 5
    ])
    sig = pd.Series(False, index=df.index)
    sig.iloc[0] = True
    sig.iloc[3] = True
    tr = simulate(df, sig, hold=2, target_pct=10, stop_pct=5, cost_pct=0.0)
    assert len(tr) == 2, len(tr)
    eq, total, used = non_overlapping_equity(tr, start_equity=10_000)
    # 10000 * 1.10 * 0.95 = 10450 -> +4.5%
    assert abs(total - 4.5) < 1e-6, total
    dd = max_drawdown_pct(eq)  # 11000 -> 10450 = -5%
    assert abs(dd - (-5.0)) < 1e-6, dd
    print("PASS test_equity_and_drawdown")


if __name__ == "__main__":
    test_target_hit()
    test_stop_hit()
    test_time_stop()
    test_stop_first_when_both_hit()
    test_cost_applied()
    test_entry_is_next_open_not_signal_close()
    test_equity_and_drawdown()
    print("\nAll tests passed.")
