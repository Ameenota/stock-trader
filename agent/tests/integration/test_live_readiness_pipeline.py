from datetime import UTC, datetime

from app.agent import _risk_required_proposal
from app.trading_policy import (
    AssetPolicyMetrics,
    HoldingState,
    RiskOverride,
    TradeAction,
    validate_pretrade_plan,
)

NOW = datetime.now(UTC)


def policy_for_exit(*, override):
    holding = HoldingState("MU", 1, 30, 30, 0.30, 2)
    metrics = AssetPolicyMetrics("MU", NOW, 0.3, 0.7, 12, 30, False, False, "HOLD")
    return validate_pretrade_plan(
        advisor_approved=True,
        decision_id="today-close-48661-p0-v1",
        account_number="mock-48661",
        allocations=[],
        holdings=[holding],
        metrics_by_ticker={"MU": metrics},
        overrides_by_ticker={"MU": override},
        total_equity=100,
        allowed_tickers={"MU", "TLT"},
        already_executed=False,
        now=NOW,
    )


def test_atr_breach_authorizes_exit_before_21_days():
    decision = policy_for_exit(override=RiskOverride("MU", True, False))
    assert decision.allowed
    assert decision.planned_trades[0].action is TradeAction.EXIT
    assert "ATR_STOP_BREACH" in decision.planned_trades[0].reason_codes


def test_macro_risk_off_constructs_sell_only_target_when_equity_is_held():
    holdings = [{"symbol": "MU", "equity": 30.0}]
    spy = type("Spy", (), {"available": True, "macro_risk_off": True})()
    proposal = _risk_required_proposal(
        holdings, 100, {"MU": RiskOverride("MU", False, True)}, spy
    )
    assert proposal["allocations"] == []
    assert proposal["decisions"][0]["signal"] == "LIQUIDATE"


def test_macro_risk_off_target_is_30_percent_tlt_when_no_sell_is_required():
    spy = type("Spy", (), {"available": True, "macro_risk_off": True})()
    proposal = _risk_required_proposal([], 100, {}, spy)
    assert proposal["allocations"] == [{"ticker": "TLT", "weight_pct": 0.30}]


def test_missing_spy_data_blocks_add_but_does_not_force_exit():
    holding = HoldingState("MU", 1, 30, 30, 0.30, 30)
    metrics = AssetPolicyMetrics("MU", NOW, 0.3, 0.2, 12, 30, False, False, "HOLD")
    unavailable = RiskOverride(
        "MU", False, False, stop_data_available=True, macro_data_available=False
    )
    hold = validate_pretrade_plan(
        advisor_approved=True,
        decision_id="hold",
        account_number="mock-48661",
        allocations=[{"ticker": "MU", "weight_pct": 0.30}],
        holdings=[holding],
        metrics_by_ticker={"MU": metrics},
        overrides_by_ticker={"MU": unavailable},
        total_equity=100,
        allowed_tickers={"MU"},
        already_executed=False,
        now=NOW,
    )
    assert hold.allowed
    add = validate_pretrade_plan(
        advisor_approved=True,
        decision_id="add",
        account_number="mock-48661",
        allocations=[{"ticker": "MU", "weight_pct": 0.34}],
        holdings=[holding],
        metrics_by_ticker={"MU": metrics},
        overrides_by_ticker={"MU": unavailable},
        total_equity=100,
        allowed_tickers={"MU"},
        already_executed=False,
        now=NOW,
    )
    assert not add.allowed
    assert "RISK_DATA_UNAVAILABLE" in add.reason_codes
