from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.risk_controls import (
    calculate_spy_regime,
    calculate_trailing_stop,
    completed_daily_bars,
    true_ranges,
    wilder_atr,
)


def bars(rows, start="2026-01-01"):
    return pd.DataFrame(
        rows,
        columns=["High", "Low", "Close"],
        index=pd.date_range(start, periods=len(rows), freq="D"),
    )


def test_true_range_ordinary_gap_up_and_gap_down():
    frame = bars([(10, 8, 9), (13, 11, 12), (10, 7, 8)])
    assert true_ranges(frame).tolist() == [2, 4, 5]


def test_wilder_atr_initialization_and_update():
    frame = bars([(10 + i, 8 + i, 9 + i) for i in range(15)])
    atr = wilder_atr(frame)
    assert atr.iloc[:13].isna().all()
    assert atr.iloc[13] == pytest.approx(2)
    assert atr.iloc[14] == pytest.approx(2)


def test_insufficient_atr_history_is_unavailable():
    result = calculate_trailing_stop(
        "MU", bars([(10, 8, 9)] * 13), entry_date=date(2026, 1, 1)
    )
    assert not result.available
    assert result.reason == "RISK_DATA_UNAVAILABLE"


def test_stop_rises_and_never_decreases():
    rising = [(100 + i, 98 + i, 99 + i) for i in range(16)]
    first = calculate_trailing_stop(
        "MU", bars(rising[:15]), entry_date=date(2026, 1, 14)
    )
    second = calculate_trailing_stop("MU", bars(rising), entry_date=date(2026, 1, 14))
    assert second.current_stop > first.current_stop
    falling = [*rising[:15], (90, 88, 89)]
    fallen = calculate_trailing_stop("MU", bars(falling), entry_date=date(2026, 1, 14))
    assert fallen.current_stop == pytest.approx(first.current_stop)


def test_close_below_prior_stop_breaches_but_new_stop_does_not_look_ahead():
    base = [(100, 99, 99.5)] * 14
    raised = [*base, (110, 109, 109.5)]
    no_lookahead = calculate_trailing_stop(
        "MU", bars(raised), entry_date=date(2026, 1, 14)
    )
    assert not no_lookahead.breached
    breached = calculate_trailing_stop(
        "MU", bars([*raised, (100, 98, 99)]), entry_date=date(2026, 1, 14)
    )
    assert breached.breached


def test_incomplete_current_bar_is_excluded():
    now = datetime(2026, 7, 20, 19, 0, tzinfo=UTC)  # 15:00 New York
    frame = pd.DataFrame(
        [(10, 8, 9), (20, 18, 19)],
        columns=["High", "Low", "Close"],
        index=["2026-07-19", "2026-07-20"],
    )
    assert len(completed_daily_bars(frame, now)) == 1


def test_duplicate_and_nonfinite_bars_fail():
    now = datetime(2026, 7, 20, 23, 0, tzinfo=UTC)
    duplicate = pd.DataFrame(
        [(10, 8, 9), (11, 9, 10)],
        columns=["High", "Low", "Close"],
        index=["2026-07-19", "2026-07-19"],
    )
    with pytest.raises(ValueError, match="duplicate"):
        completed_daily_bars(duplicate, now)
    with pytest.raises(ValueError, match="non-finite"):
        completed_daily_bars(bars([(10, 8, float("nan"))]), now)


def test_spy_regime_above_below_and_insufficient():
    observed = datetime(2026, 7, 20, tzinfo=UTC)
    above = bars([(100, 99, 100)] * 199 + [(102, 101, 102)])
    assert not calculate_spy_regime(above, observed_at=observed).macro_risk_off
    below = bars([(100, 99, 100)] * 199 + [(90, 89, 90)])
    assert calculate_spy_regime(below, observed_at=observed).macro_risk_off
    assert not calculate_spy_regime(below.iloc[:199], observed_at=observed).available
