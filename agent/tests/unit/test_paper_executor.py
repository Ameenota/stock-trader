from datetime import UTC, datetime, timedelta

import pytest

from app.paper_executor import (
    PaperHolding,
    PaperPortfolio,
    execute_paper_rebalance,
    recapitalize_paper_portfolio,
)
from app.trading_policy import ValidatedExecutionPlan


NOW = datetime.now(UTC)


def plan(allocations, decision_id="2026-07-21-close-paper-execution"):
    return ValidatedExecutionPlan._create(
        decision_id=decision_id,
        account_number="PAPER",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        allocations=allocations,
        planned_trades=(),
        account_id="paper-one",
        execution_mode="PAPER",
    )


def test_buy_persists_cash_quantity_and_cost_basis():
    result = execute_paper_rebalance(
        plan=plan({"MU": 0.30}),
        portfolio=PaperPortfolio(100.0, ()),
        prices={"MU": 10.0},
    )
    assert result.portfolio.cash == pytest.approx(70.0)
    assert result.portfolio.holdings[0].shares == pytest.approx(3.0)
    assert result.portfolio.holdings[0].average_buy_price == pytest.approx(10.0)
    assert result.portfolio.total_equity == pytest.approx(100.0)


def test_sell_day_defers_buys_and_full_exit_removes_position():
    result = execute_paper_rebalance(
        plan=plan({"NVDA": 0.30}),
        portfolio=PaperPortfolio(
            70.0, (PaperHolding("MU", 3.0, 10.0, 10.0),)
        ),
        prices={"MU": 10.0, "NVDA": 20.0},
    )
    assert [fill.side for fill in result.fills] == ["sell"]
    assert result.portfolio.cash == pytest.approx(100.0)
    assert result.portfolio.holdings == ()


def test_ids_are_deterministic_and_costs_reconcile():
    kwargs = dict(
        plan=plan({"MU": 0.30}),
        portfolio=PaperPortfolio(100.0, ()),
        prices={"MU": 10.0},
        fee_bps=10,
        slippage_bps=20,
    )
    first = execute_paper_rebalance(**kwargs)
    second = execute_paper_rebalance(**kwargs)
    assert first.snapshot_id == second.snapshot_id
    assert first.fills[0].trade_id == second.fills[0].trade_id
    assert first.portfolio.total_equity < 100.0


def test_missing_quote_and_nonpaper_plan_fail_closed():
    with pytest.raises(ValueError, match="Missing paper prices"):
        execute_paper_rebalance(
            plan=plan({"MU": 0.30}),
            portfolio=PaperPortfolio(100.0, ()),
            prices={},
        )
    real_plan = ValidatedExecutionPlan._create(
        decision_id="x",
        account_number="mock-48661",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        allocations={},
        planned_trades=(),
    )
    with pytest.raises(ValueError, match="PAPER plan"):
        execute_paper_rebalance(
            plan=real_plan, portfolio=PaperPortfolio(100.0, ()), prices={}
        )


def test_recapitalization_preserves_positions_and_sets_exact_equity():
    original = PaperPortfolio(
        70.0, (PaperHolding("META", 0.03, 1000.0, 1000.0),)
    )
    adjusted = recapitalize_paper_portfolio(original, 10_000.0)
    assert adjusted.cash == pytest.approx(9_970.0)
    assert adjusted.holdings == original.holdings
    assert adjusted.total_equity == pytest.approx(10_000.0)


def test_recapitalization_rejects_target_below_holdings_value():
    original = PaperPortfolio(
        0.0, (PaperHolding("META", 1.0, 1000.0, 1000.0),)
    )
    with pytest.raises(ValueError, match="below current holdings"):
        recapitalize_paper_portfolio(original, 999.0)
