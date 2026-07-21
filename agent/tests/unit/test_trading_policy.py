import math
from datetime import UTC, datetime, timedelta

import pytest

from app.trading_policy import (
    AssetPolicyMetrics,
    HoldingState,
    RiskOverride,
    TradeAction,
    ValidatedExecutionPlan,
    validate_pretrade_plan,
)

NOW = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)


def metrics(ticker: str, *, observed_at: datetime = NOW) -> AssetPolicyMetrics:
    return AssetPolicyMetrics(
        ticker=ticker,
        observed_at=observed_at,
        sentiment_ewma=0.3,
        sentiment_volatility=0.2,
        drawdown_pct=12.0,
        forward_pe=30.0,
        is_20d_high=False,
        macd_bullish_cross=False,
        final_signal="HOLD",
    )


def custom_metrics(ticker: str, **changes) -> AssetPolicyMetrics:
    values = {
        "ticker": ticker,
        "observed_at": NOW,
        "sentiment_ewma": 0.3,
        "sentiment_volatility": 0.2,
        "drawdown_pct": 12.0,
        "forward_pe": 30.0,
        "is_20d_high": False,
        "macd_bullish_cross": False,
        "final_signal": "HOLD",
    }
    values.update(changes)
    return AssetPolicyMetrics(**values)


def validate(allocations=None, holdings=None, **overrides):
    if allocations is None:
        allocations = [
            {"ticker": "NVDA", "weight_pct": 0.30},
            {"ticker": "MU", "weight_pct": 0.30},
            {"ticker": "MRVL", "weight_pct": 0.30},
        ]
    if holdings is None:
        holdings = []
    tickers = {a["ticker"].upper() for a in allocations if a.get("ticker")} | {
        h.ticker for h in holdings
    }
    kwargs = {
        "advisor_approved": True,
        "decision_id": "2026-07-20-close-48661-p0-v1",
        "account_number": "mock-48661",
        "allocations": allocations,
        "holdings": holdings,
        "metrics_by_ticker": {ticker: metrics(ticker) for ticker in tickers},
        "overrides_by_ticker": {
            ticker: RiskOverride(ticker, False, False) for ticker in tickers
        },
        "total_equity": 100.0,
        "allowed_tickers": {"NVDA", "MU", "MRVL", "DELL", "TSM", "TLT"},
        "already_executed": False,
        "now": NOW,
    }
    kwargs.update(overrides)
    return validate_pretrade_plan(**kwargs)


def assert_code(decision, code):
    assert not decision.allowed
    assert decision.plan is None
    assert code in decision.reason_codes


def test_valid_three_position_proposal_creates_plan():
    decision = validate()
    assert decision.allowed
    assert isinstance(decision.plan, ValidatedExecutionPlan)
    assert {trade.action for trade in decision.planned_trades} == {TradeAction.ENTER}


@pytest.mark.parametrize("approved", [False, None])
def test_missing_or_rejected_critique_fails(approved):
    assert_code(validate(advisor_approved=approved), "ADVISOR_NOT_APPROVED")


def test_duplicate_decision_fails():
    assert_code(validate(already_executed=True), "DUPLICATE_DECISION_ID")


def test_missing_decision_fails():
    assert_code(validate(decision_id=" "), "MISSING_DECISION_ID")


def test_unauthorized_account_fails():
    assert_code(validate(account_number="bad-12345"), "UNAUTHORIZED_ACCOUNT")


def test_unknown_ticker_fails():
    assert_code(validate([{"ticker": "AAPL", "weight_pct": 0.30}]), "UNKNOWN_TICKER")


def test_duplicate_allocation_fails():
    assert_code(
        validate(
            [{"ticker": "MU", "weight_pct": 0.30}, {"ticker": "mu", "weight_pct": 0.30}]
        ),
        "DUPLICATE_ALLOCATION",
    )


@pytest.mark.parametrize("weight", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_weights_fail(weight):
    assert_code(validate([{"ticker": "MU", "weight_pct": weight}]), "INVALID_WEIGHT")


def test_four_positive_targets_fail():
    allocations = [
        {"ticker": ticker, "weight_pct": 0.20}
        for ticker in ("MU", "MRVL", "DELL", "TSM")
    ]
    assert_code(validate(allocations), "TOO_MANY_POSITIONS")


def test_gross_exposure_above_95_percent_fails():
    allocations = [
        {"ticker": ticker, "weight_pct": 0.32} for ticker in ("MU", "MRVL", "DELL")
    ]
    decision = validate(allocations)
    assert_code(decision, "GROSS_EXPOSURE_EXCEEDED")
    assert "CASH_RESERVE_VIOLATION" in decision.reason_codes


def test_sell_and_buy_mix_fails():
    holding = HoldingState("DELL", 2, 30, 60, 0.60, 30)
    decision = validate(
        [{"ticker": "DELL", "weight_pct": 0.30}, {"ticker": "MU", "weight_pct": 0.30}],
        [holding],
    )
    assert_code(decision, "SAME_DAY_SELL_BUY")


def test_sell_only_proposal_can_pass():
    holding = HoldingState("DELL", 2, 30, 60, 0.60, 30)
    decision = validate(
        [{"ticker": "DELL", "weight_pct": 0.30}],
        [holding],
        overrides_by_ticker={"DELL": RiskOverride("DELL", True, False)},
    )
    assert decision.allowed
    assert decision.planned_trades[0].action is TradeAction.REDUCE


def test_stale_metrics_fail():
    stale = {
        ticker: metrics(ticker, observed_at=NOW - timedelta(days=2))
        for ticker in ("NVDA", "MU", "MRVL")
    }
    assert_code(validate(metrics_by_ticker=stale), "STALE_MARKET_METRICS")


def test_missing_metrics_and_risk_data_fail_closed():
    assert_code(validate(metrics_by_ticker={}), "MISSING_MARKET_METRICS")
    assert_code(validate(overrides_by_ticker={}), "RISK_DATA_UNAVAILABLE")


def test_order_notional_cap_is_enforced():
    assert_code(
        validate(
            [{"ticker": "MU", "weight_pct": 0.30}],
            total_equity=200,
        ),
        "ORDER_NOTIONAL_EXCEEDED",
    )


def test_paper_order_cap_scales_with_paper_equity():
    decision = validate(
        [{"ticker": "MU", "weight_pct": 0.30}],
        total_equity=10_000,
        account_number="PAPER",
        account_id="exp-paper",
        execution_mode="PAPER",
    )
    assert decision.allowed
    assert decision.planned_trades[0].delta_weight == pytest.approx(0.30)


def test_plan_cannot_be_constructed_directly():
    with pytest.raises(TypeError, match="must be created"):
        ValidatedExecutionPlan(
            decision_id="x",
            account_number="mock-48661",
            created_at=NOW,
            expires_at=NOW,
            allocations={},
            planned_trades=(),
        )


def test_path_a_boundary_and_path_b_volatility_rules():
    assert validate([{"ticker": "MU", "weight_pct": 0.30}]).allowed
    failed_a = validate(
        [{"ticker": "MU", "weight_pct": 0.30}],
        metrics_by_ticker={"MU": custom_metrics("MU", sentiment_volatility=0.401)},
    )
    assert_code(failed_a, "ENTRY_GATE_FAILED")
    passed_b = validate(
        [{"ticker": "MU", "weight_pct": 0.30}],
        metrics_by_ticker={
            "MU": custom_metrics(
                "MU",
                drawdown_pct=0,
                sentiment_volatility=0.60,
                is_20d_high=True,
                macd_bullish_cross=True,
            )
        },
    )
    assert passed_b.allowed
    failed_b = validate(
        [{"ticker": "MU", "weight_pct": 0.30}],
        metrics_by_ticker={
            "MU": custom_metrics(
                "MU",
                drawdown_pct=0,
                sentiment_volatility=0.851,
                is_20d_high=True,
                macd_bullish_cross=True,
            )
        },
    )
    assert_code(failed_b, "ENTRY_GATE_FAILED")


def test_existing_high_volatility_holding_can_hold_but_not_exit_for_volatility():
    holding = HoldingState("MU", 1, 30, 30, 0.30, 24)
    high_vol = {
        "MU": custom_metrics("MU", sentiment_volatility=0.665, sentiment_ewma=0.353)
    }
    assert validate(
        [{"ticker": "MU", "weight_pct": 0.30}], [holding], metrics_by_ticker=high_vol
    ).allowed
    assert_code(
        validate([], [holding], metrics_by_ticker=high_vol), "EXIT_NOT_AUTHORIZED"
    )


def test_hard_and_soft_exit_rules():
    young = HoldingState("MU", 1, 30, 30, 0.30, 2)
    hard = validate(
        [],
        [young],
        metrics_by_ticker={"MU": custom_metrics("MU", sentiment_ewma=-0.51)},
    )
    assert hard.allowed
    mature = HoldingState("MU", 1, 30, 30, 0.30, 21)
    soft = validate(
        [],
        [mature],
        metrics_by_ticker={
            "MU": custom_metrics("MU", sentiment_ewma=0.049, final_signal="LIQUIDATE")
        },
    )
    assert soft.allowed
    day_20 = HoldingState("MU", 1, 30, 30, 0.30, 20)
    decision = validate(
        [],
        [day_20],
        metrics_by_ticker={
            "MU": custom_metrics("MU", sentiment_ewma=0.049, final_signal="LIQUIDATE")
        },
    )
    assert_code(decision, "HOLDING_PERIOD_VIOLATION")
    assert_code(
        validate(
            [],
            [mature],
            metrics_by_ticker={
                "MU": custom_metrics(
                    "MU", sentiment_ewma=0.05, final_signal="LIQUIDATE"
                )
            },
        ),
        "EXIT_NOT_AUTHORIZED",
    )


@pytest.mark.parametrize(
    "override",
    [
        RiskOverride("MU", True, False),
        RiskOverride("MU", False, True),
    ],
)
def test_stop_and_macro_overrides_ignore_holding_age(override):
    holding = HoldingState("MU", 1, 30, 30, 0.30, 1)
    assert validate([], [holding], overrides_by_ticker={"MU": override}).allowed


def test_july_20_regression_fixture():
    holdings = [
        HoldingState("MU", 1, 29.3, 29.3, 0.293, 24),
        HoldingState("MRVL", 1, 28.6, 28.6, 0.286, 21),
        HoldingState("SNDK", 1, 26.7, 26.7, 0.267, 2),
    ]
    metric_map = {
        "MU": custom_metrics("MU", sentiment_ewma=0.353, sentiment_volatility=0.665),
        "MRVL": custom_metrics(
            "MRVL", sentiment_ewma=0.284, sentiment_volatility=0.552
        ),
        "SNDK": custom_metrics(
            "SNDK", sentiment_ewma=0.425, sentiment_volatility=0.526
        ),
    }
    override_map = {ticker: RiskOverride(ticker, False, False) for ticker in metric_map}
    allocations = [
        {"ticker": holding.ticker, "weight_pct": holding.weight} for holding in holdings
    ]
    assert validate(
        allocations,
        holdings,
        metrics_by_ticker=metric_map,
        overrides_by_ticker=override_map,
        allowed_tickers={"MU", "MRVL", "SNDK"},
    ).allowed
    add_mu = [
        {"ticker": "MU", "weight_pct": 0.34},
        {"ticker": "MRVL", "weight_pct": 0.286},
        {"ticker": "SNDK", "weight_pct": 0.267},
    ]
    assert_code(
        validate(
            add_mu,
            holdings,
            metrics_by_ticker=metric_map,
            overrides_by_ticker=override_map,
            allowed_tickers={"MU", "MRVL", "SNDK"},
        ),
        "ADD_GATE_FAILED",
    )
    exit_mu = [allocation for allocation in allocations if allocation["ticker"] != "MU"]
    assert_code(
        validate(
            exit_mu,
            holdings,
            metrics_by_ticker=metric_map,
            overrides_by_ticker=override_map,
            allowed_tickers={"MU", "MRVL", "SNDK"},
        ),
        "EXIT_NOT_AUTHORIZED",
    )
