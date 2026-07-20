"""Deterministic authorization boundary between agent proposals and broker tools."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

POLICY_VERSION = "p0-v1"
_PLAN_TOKEN = object()
_EPSILON = 1e-9


class TradeAction(StrEnum):
    ENTER = "ENTER"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _ticker(value: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("ticker must not be empty")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str
    ticker: str | None = None


@dataclass(frozen=True)
class HoldingState:
    ticker: str
    shares: float
    price: float
    equity: float
    weight: float
    days_held: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _ticker(self.ticker))
        for name in ("shares", "price", "equity", "weight"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.shares < 0 or self.price < 0 or self.equity < 0 or self.weight < 0:
            raise ValueError("holding numeric values must be non-negative")
        if self.days_held < 0:
            raise ValueError("days_held must be non-negative")


@dataclass(frozen=True)
class AssetPolicyMetrics:
    ticker: str
    observed_at: datetime
    sentiment_ewma: float
    sentiment_volatility: float
    drawdown_pct: float
    forward_pe: float | None
    is_20d_high: bool
    macd_bullish_cross: bool
    final_signal: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _ticker(self.ticker))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        for name in ("sentiment_ewma", "sentiment_volatility", "drawdown_pct"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.forward_pe is not None:
            object.__setattr__(
                self, "forward_pe", _finite(self.forward_pe, "forward_pe")
            )
        object.__setattr__(self, "final_signal", str(self.final_signal).strip().upper())


@dataclass(frozen=True)
class RiskOverride:
    ticker: str
    stop_breached: bool
    macro_risk_off: bool
    reason: str = ""
    stop_data_available: bool = True
    macro_data_available: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _ticker(self.ticker))


@dataclass(frozen=True)
class PlannedTrade:
    ticker: str
    action: TradeAction
    current_weight: float
    target_weight: float
    delta_weight: float
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidatedExecutionPlan:
    decision_id: str
    account_number: str
    created_at: datetime
    expires_at: datetime
    allocations: Mapping[str, float]
    planned_trades: tuple[PlannedTrade, ...]
    policy_version: str = POLICY_VERSION
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _PLAN_TOKEN:
            raise TypeError(
                "ValidatedExecutionPlan must be created by validate_pretrade_plan"
            )
        object.__setattr__(
            self, "allocations", MappingProxyType(dict(self.allocations))
        )

    @classmethod
    def _create(
        cls,
        *,
        decision_id: str,
        account_number: str,
        created_at: datetime,
        expires_at: datetime,
        allocations: Mapping[str, float],
        planned_trades: Sequence[PlannedTrade],
    ) -> ValidatedExecutionPlan:
        return cls(
            decision_id=decision_id,
            account_number=account_number,
            created_at=created_at,
            expires_at=expires_at,
            allocations=allocations,
            planned_trades=tuple(planned_trades),
            _token=_PLAN_TOKEN,
        )


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    decision_id: str
    normalized_allocations: Mapping[str, float]
    planned_trades: tuple[PlannedTrade, ...]
    violations: tuple[PolicyViolation, ...]
    plan: ValidatedExecutionPlan | None = None

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(violation.code for violation in self.violations)


def _classify_action(current: float, target: float) -> TradeAction:
    if current <= _EPSILON and target > _EPSILON:
        return TradeAction.ENTER
    if current > _EPSILON and target > current + 0.03 + _EPSILON:
        return TradeAction.ADD
    if current > _EPSILON and target <= _EPSILON:
        return TradeAction.EXIT
    if current > _EPSILON and target < current - 0.03 - _EPSILON:
        return TradeAction.REDUCE
    return TradeAction.HOLD


def validate_pretrade_plan(
    *,
    advisor_approved: bool,
    decision_id: str,
    account_number: str,
    allocations: list[dict],
    holdings: list[HoldingState],
    metrics_by_ticker: dict[str, AssetPolicyMetrics],
    overrides_by_ticker: dict[str, RiskOverride],
    total_equity: float,
    allowed_tickers: set[str],
    already_executed: bool,
    now: datetime,
    metrics_max_age: timedelta = timedelta(hours=36),
) -> PolicyDecision:
    """Validate a complete proposal. Any violation cancels the entire plan."""
    now = _aware(now, "now")
    violations: list[PolicyViolation] = []
    normalized: dict[str, float] = {}
    allowed = {_ticker(ticker) for ticker in allowed_tickers}

    if advisor_approved is not True:
        violations.append(
            PolicyViolation(
                "ADVISOR_NOT_APPROVED", "Final advisor approval is required."
            )
        )
    clean_decision_id = str(decision_id).strip()
    if not clean_decision_id:
        violations.append(
            PolicyViolation(
                "MISSING_DECISION_ID", "A deterministic decision ID is required."
            )
        )
    if already_executed:
        violations.append(
            PolicyViolation(
                "DUPLICATE_DECISION_ID", "This decision has already executed."
            )
        )
    if not str(account_number).strip().endswith("48661"):
        violations.append(
            PolicyViolation("UNAUTHORIZED_ACCOUNT", "The account is not authorized.")
        )

    try:
        equity = _finite(total_equity, "total_equity")
        if equity <= 0:
            raise ValueError
    except (TypeError, ValueError):
        equity = 0.0
        violations.append(
            PolicyViolation(
                "INVALID_WEIGHT", "Total equity must be finite and positive."
            )
        )

    for allocation in allocations:
        try:
            ticker = _ticker(allocation.get("ticker", ""))
        except (AttributeError, ValueError):
            violations.append(
                PolicyViolation(
                    "UNKNOWN_TICKER", "Allocation ticker is missing or invalid."
                )
            )
            continue
        if ticker not in allowed:
            violations.append(
                PolicyViolation(
                    "UNKNOWN_TICKER", "Ticker is outside the allowlist.", ticker
                )
            )
        if ticker in normalized:
            violations.append(
                PolicyViolation(
                    "DUPLICATE_ALLOCATION", "Ticker appears more than once.", ticker
                )
            )
            continue
        try:
            weight = _finite(allocation.get("weight_pct"), "weight_pct")
            if weight < 0 or weight > 1:
                raise ValueError
        except (TypeError, ValueError):
            violations.append(
                PolicyViolation(
                    "INVALID_WEIGHT",
                    "Weight must be finite and between zero and one.",
                    ticker,
                )
            )
            continue
        normalized[ticker] = weight

    positive_targets = {
        ticker: weight for ticker, weight in normalized.items() if weight > _EPSILON
    }
    if len(positive_targets) > 3:
        violations.append(
            PolicyViolation(
                "TOO_MANY_POSITIONS",
                "At most three positive target positions are allowed.",
            )
        )
    gross_exposure = sum(positive_targets.values())
    if gross_exposure > 0.95 + _EPSILON:
        violations.append(
            PolicyViolation("GROSS_EXPOSURE_EXCEEDED", "Target exposure exceeds 95%.")
        )
        violations.append(
            PolicyViolation(
                "CASH_RESERVE_VIOLATION", "Target cash would fall below 5%."
            )
        )

    holding_map = {holding.ticker: holding for holding in holdings}
    for ticker, weight in positive_targets.items():
        if ticker not in holding_map and abs(weight - 0.30) > _EPSILON:
            violations.append(
                PolicyViolation(
                    "INVALID_WEIGHT", "A new position must target 30%.", ticker
                )
            )

    tickers = set(holding_map) | set(positive_targets)
    normalized_metrics = {
        _ticker(key): value for key, value in metrics_by_ticker.items()
    }
    normalized_overrides = {
        _ticker(key): value for key, value in overrides_by_ticker.items()
    }
    for ticker in sorted(tickers):
        metrics = normalized_metrics.get(ticker)
        if metrics is None or metrics.ticker != ticker:
            violations.append(
                PolicyViolation(
                    "MISSING_MARKET_METRICS", "Market metrics are required.", ticker
                )
            )
        elif metrics.observed_at > now or now - metrics.observed_at > metrics_max_age:
            violations.append(
                PolicyViolation(
                    "STALE_MARKET_METRICS", "Market metrics are stale.", ticker
                )
            )

    planned: list[PlannedTrade] = []
    for ticker in sorted(tickers):
        current = holding_map[ticker].weight if ticker in holding_map else 0.0
        target = normalized.get(ticker, 0.0)
        action = _classify_action(current, target)
        reason_codes: list[str] = []
        metrics = normalized_metrics.get(ticker)
        override = normalized_overrides.get(ticker)
        if metrics is not None:
            if action in (TradeAction.ENTER, TradeAction.ADD):
                risk_available = bool(
                    override
                    and override.macro_data_available
                    and (action is TradeAction.ENTER or override.stop_data_available)
                )
                if not risk_available:
                    violations.append(
                        PolicyViolation(
                            "RISK_DATA_UNAVAILABLE",
                            "Required downside-risk data is unavailable.",
                            ticker,
                        )
                    )
                    planned.append(
                        PlannedTrade(ticker, action, current, target, target - current)
                    )
                    continue
                if ticker == "TLT":
                    reason_codes.append("DEFENSIVE_ASSET")
                else:
                    valuation_ok = (
                        metrics.forward_pe is None or metrics.forward_pe <= 80
                    )
                    path_a = (
                        metrics.drawdown_pct >= 10
                        and metrics.sentiment_ewma > 0.10
                        and metrics.sentiment_volatility <= 0.40
                        and valuation_ok
                    )
                    path_b = (
                        metrics.is_20d_high is True
                        and metrics.macd_bullish_cross is True
                        and metrics.sentiment_volatility <= 0.85
                        and valuation_ok
                    )
                    if path_a:
                        reason_codes.append("PATH_A")
                    elif path_b:
                        reason_codes.append("PATH_B")
                    else:
                        code = (
                            "ENTRY_GATE_FAILED"
                            if action is TradeAction.ENTER
                            else "ADD_GATE_FAILED"
                        )
                        violations.append(
                            PolicyViolation(
                                code,
                                f"{action.value} requires a valid deterministic entry path.",
                                ticker,
                            )
                        )
            elif action in (TradeAction.REDUCE, TradeAction.EXIT):
                hard_exit = False
                if override and override.stop_breached:
                    reason_codes.append("ATR_STOP_BREACH")
                    hard_exit = True
                if override and override.macro_risk_off:
                    reason_codes.append("MACRO_RISK_OFF")
                    hard_exit = True
                if metrics.sentiment_ewma < -0.50:
                    reason_codes.append("HARD_NEGATIVE_SENTIMENT")
                    hard_exit = True
                holding = holding_map.get(ticker)
                soft_exit = bool(
                    holding
                    and holding.days_held >= 21
                    and metrics.final_signal == "LIQUIDATE"
                    and metrics.sentiment_ewma < 0.05
                )
                if soft_exit:
                    reason_codes.append("SOFT_EXIT")
                if not hard_exit and not soft_exit:
                    violations.append(
                        PolicyViolation(
                            "EXIT_NOT_AUTHORIZED",
                            "No deterministic reduction/exit rule is satisfied.",
                            ticker,
                        )
                    )
                    if (
                        holding
                        and holding.days_held < 21
                        and metrics.final_signal == "LIQUIDATE"
                    ):
                        violations.append(
                            PolicyViolation(
                                "HOLDING_PERIOD_VIOLATION",
                                "Soft exit is blocked before 21 completed days.",
                                ticker,
                            )
                        )
            else:
                reason_codes.append("WITHIN_TOLERANCE")
        planned.append(
            PlannedTrade(
                ticker, action, current, target, target - current, tuple(reason_codes)
            )
        )

    has_sell = any(
        trade.action in (TradeAction.REDUCE, TradeAction.EXIT) for trade in planned
    )
    has_buy = any(
        trade.action in (TradeAction.ENTER, TradeAction.ADD) for trade in planned
    )
    if has_sell and has_buy:
        violations.append(
            PolicyViolation(
                "SAME_DAY_SELL_BUY", "Sell and buy actions cannot share a market date."
            )
        )

    max_order_notional = (
        min(0.35 * equity, float(os.environ.get("MAX_ORDER_NOTIONAL_USD", "35.00")))
        if equity
        else 0.0
    )
    if equity:
        for trade in planned:
            if trade.action is TradeAction.HOLD:
                continue
            if abs(trade.delta_weight) * equity > max_order_notional + 0.01:
                violations.append(
                    PolicyViolation(
                        "ORDER_NOTIONAL_EXCEEDED",
                        "Estimated order exceeds the configured cap.",
                        trade.ticker,
                    )
                )

    decision = PolicyDecision(
        allowed=not violations,
        decision_id=clean_decision_id,
        normalized_allocations=MappingProxyType(dict(normalized)),
        planned_trades=tuple(planned),
        violations=tuple(violations),
    )
    if violations:
        return decision
    plan = ValidatedExecutionPlan._create(
        decision_id=clean_decision_id,
        account_number=str(account_number).strip(),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        allocations=normalized,
        planned_trades=planned,
    )
    return PolicyDecision(
        allowed=True,
        decision_id=clean_decision_id,
        normalized_allocations=decision.normalized_allocations,
        planned_trades=decision.planned_trades,
        violations=(),
        plan=plan,
    )
