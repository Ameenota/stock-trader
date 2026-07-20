"""Pure downside-risk calculations using completed daily bars only."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class TrailingStopResult:
    ticker: str
    available: bool
    as_of_session: date | None
    atr: float | None
    previous_stop: float | None
    current_stop: float | None
    highest_high: float | None
    breached: bool
    reason: str


@dataclass(frozen=True)
class SpyRegimeResult:
    available: bool
    observed_at: datetime
    last_session: date | None
    close: float | None
    sma_200: float | None
    macro_risk_off: bool
    reason: str


def completed_daily_bars(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(frame, pd.DataFrame) or not {"High", "Low", "Close"}.issubset(
        frame.columns
    ):
        raise ValueError("daily bars require High, Low, and Close columns")
    bars = frame.loc[:, ["High", "Low", "Close"]].copy()
    parsed_index = pd.to_datetime(bars.index)
    session_dates = [value.date() for value in parsed_index]
    if len(session_dates) != len(set(session_dates)):
        raise ValueError("daily bars contain duplicate sessions")
    bars.index = pd.Index(session_dates, name="session")
    bars = bars.sort_index()
    for column in ("High", "Low", "Close"):
        values = pd.to_numeric(bars[column], errors="coerce")
        if values.isna().any() or not values.map(math.isfinite).all():
            raise ValueError(f"daily bars contain non-finite {column} values")
        bars[column] = values.astype(float)
    ny_now = now.astimezone(NEW_YORK)
    if (
        not bars.empty
        and bars.index[-1] == ny_now.date()
        and ny_now.time() < time(16, 15)
    ):
        bars = bars.iloc[:-1]
    return bars


def true_ranges(bars: pd.DataFrame) -> pd.Series:
    if bars.empty:
        return pd.Series(dtype=float)
    ranges: list[float] = []
    previous_close: float | None = None
    for _, row in bars.iterrows():
        high, low, close = float(row.High), float(row.Low), float(row.Close)
        if previous_close is None:
            value = high - low
        else:
            value = max(
                high - low, abs(high - previous_close), abs(low - previous_close)
            )
        ranges.append(value)
        previous_close = close
    return pd.Series(ranges, index=bars.index, dtype=float, name="true_range")


def wilder_atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    if period <= 0:
        raise ValueError("ATR period must be positive")
    tr = true_ranges(bars)
    result = pd.Series(float("nan"), index=tr.index, dtype=float, name="atr")
    if len(tr) < period:
        return result
    result.iloc[period - 1] = float(tr.iloc[:period].mean())
    for index in range(period, len(tr)):
        result.iloc[index] = (
            (result.iloc[index - 1] * (period - 1)) + tr.iloc[index]
        ) / period
    return result


def calculate_trailing_stop(
    ticker: str,
    bars: pd.DataFrame,
    *,
    entry_date: date,
    period: int = 14,
    multiplier: float = 3.0,
) -> TrailingStopResult:
    atr_values = wilder_atr(bars, period)
    eligible = [
        index
        for index in bars.index
        if (index.date() if hasattr(index, "date") else index) >= entry_date
        and not pd.isna(atr_values.loc[index])
    ]
    if not eligible:
        return TrailingStopResult(
            ticker.upper(),
            False,
            None,
            None,
            None,
            None,
            None,
            False,
            "RISK_DATA_UNAVAILABLE",
        )
    stop: float | None = None
    previous_stop: float | None = None
    highest_high: float | None = None
    breached = False
    last_session: date | None = None
    last_atr: float | None = None
    for session in eligible:
        row = bars.loc[session]
        atr = float(atr_values.loc[session])
        close = float(row.Close)
        high = float(row.High)
        previous_stop = stop
        if previous_stop is not None and close < previous_stop:
            breached = True
        candidate = high - multiplier * atr
        stop = candidate if stop is None else max(stop, candidate)
        highest_high = high if highest_high is None else max(highest_high, high)
        last_session = session.date() if hasattr(session, "date") else session
        last_atr = atr
    return TrailingStopResult(
        ticker.upper(),
        True,
        last_session,
        last_atr,
        previous_stop,
        stop,
        highest_high,
        breached,
        "ATR_STOP_BREACH" if breached else "ATR_STOP_ACTIVE",
    )


def calculate_spy_regime(
    bars: pd.DataFrame, *, observed_at: datetime, period: int = 200
) -> SpyRegimeResult:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if len(bars) < period:
        return SpyRegimeResult(
            False, observed_at, None, None, None, False, "RISK_DATA_UNAVAILABLE"
        )
    closes = bars["Close"].iloc[-period:]
    close = float(closes.iloc[-1])
    sma = float(closes.mean())
    risk_off = close < sma
    return SpyRegimeResult(
        True,
        observed_at,
        bars.index[-1],
        close,
        sma,
        risk_off,
        "MACRO_RISK_OFF" if risk_off else "MACRO_RISK_ON",
    )
