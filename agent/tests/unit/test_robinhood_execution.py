import math
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.broker_executor import BrokerExecutor, ExecutionStatus
from app.tools.bigquery_service import get_last_buy_timestamp, insert_portfolio_snapshot
from app.tools.robinhood_service import (
    BrokerConnectionError,
    BrokerPayloadError,
    BrokerToolUnavailableError,
    QuoteValidationError,
    parse_quotes,
)
from app.trading_policy import (
    AssetPolicyMetrics,
    RiskOverride,
    ValidatedExecutionPlan,
    validate_pretrade_plan,
)


def tool(name, response=None, side_effect=None):
    value = MagicMock()
    value.name = name
    value.run_async = AsyncMock(return_value=response, side_effect=side_effect)
    return value


def portfolio(cash="100", buying_power="100"):
    return {
        "structuredContent": {
            "data": {"cash": cash, "buying_power": {"buying_power": buying_power}}
        }
    }


def positions(items=None):
    return {"structuredContent": {"data": {"positions": items or []}}}


def quotes(prices):
    return {
        "structuredContent": {
            "data": {
                "results": [
                    {"quote": {"symbol": ticker, "last_trade_price": str(price)}}
                    for ticker, price in prices.items()
                ]
            }
        }
    }


def make_toolset(
    *,
    portfolio_response=None,
    position_response=None,
    quote_response=None,
    order_response=None,
    order_side_effect=None,
    omit=(),
):
    mapping = {
        "get_portfolio": tool("get_portfolio", portfolio_response or portfolio()),
        "get_equity_positions": tool(
            "get_equity_positions", position_response or positions()
        ),
        "get_equity_quotes": tool(
            "get_equity_quotes", quote_response or quotes({"NVDA": 100})
        ),
        "place_equity_order": tool(
            "place_equity_order",
            order_response or {"status": "accepted", "order_id": "order-1"},
            order_side_effect,
        ),
    }
    selected = [value for name, value in mapping.items() if name not in omit]
    toolset = MagicMock()
    toolset.get_tools = AsyncMock(return_value=selected)
    toolset.mapping = mapping
    return toolset


def metric(ticker):
    return AssetPolicyMetrics(
        ticker, datetime.now(UTC), 0.3, 0.2, 12, 30, False, False, "HOLD"
    )


def plan(allocations, holdings=None, allowed_tickers=None):
    holdings = holdings or []
    tickers = {a["ticker"] for a in allocations} | {h.ticker for h in holdings}
    decision = validate_pretrade_plan(
        advisor_approved=True,
        decision_id="today-close-48661-p0-v1",
        account_number="MOCK_ACCOUNT_48661",
        allocations=allocations,
        holdings=holdings,
        metrics_by_ticker={ticker: metric(ticker) for ticker in tickers},
        overrides_by_ticker={
            ticker: RiskOverride(ticker, False, False) for ticker in tickers
        },
        total_equity=100,
        allowed_tickers=allowed_tickers or {"NVDA", "MU", "DELL", "TSM"},
        already_executed=False,
        now=datetime.now(UTC),
    )
    assert decision.allowed, decision.reason_codes
    return decision.plan


@patch("app.tools.bigquery_service.get_bigquery_client")
def test_get_last_buy_timestamp_matches_buy_and_strong_buy(mock_get_client):
    client = MagicMock()
    mock_get_client.return_value = client
    row = MagicMock(timestamp=datetime(2026, 6, 24, 23, 31, 46, tzinfo=UTC))
    client.query.return_value.result.return_value = [row]
    assert get_last_buy_timestamp("TSM", False, "test_dataset") == row.timestamp
    assert "action IN ('BUY', 'STRONG BUY')" in client.query.call_args[0][0]


@patch("app.tools.bigquery_service.get_bigquery_client")
def test_insert_portfolio_snapshot(mock_get_client):
    client = MagicMock(project="test-project")
    mock_get_client.return_value = client
    insert_portfolio_snapshot(
        {
            "account_number": "••••48661",
            "total_equity": 100,
            "total_cash": 15,
            "buying_power": 15,
            "unrealized_gain_loss": 0,
            "unrealized_gain_loss_percent": 0,
            "holdings": "[]",
        },
        "test_dataset",
    )
    assert (
        client.load_table_from_json.call_args[0][1]
        == "test-project.test_dataset.portfolio_snapshot"
    )


@pytest.mark.asyncio
async def test_raw_allocations_fail_before_tools():
    toolset = make_toolset()
    executor = BrokerExecutor(toolset, "MOCK_ACCOUNT_48661")
    with pytest.raises(TypeError):
        await executor.execute_rebalance([{"ticker": "NVDA", "weight_pct": 0.3}])
    toolset.get_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_forged_paper_plan_fails_before_tools():
    toolset = make_toolset()
    now = datetime.now(UTC)
    paper_plan = ValidatedExecutionPlan._create(
        decision_id="paper-forgery",
        account_number="MOCK_ACCOUNT_48661",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        allocations={},
        planned_trades=(),
        account_id="paper-one",
        execution_mode="PAPER",
    )
    with pytest.raises(ValueError, match="Paper execution plans"):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            paper_plan
        )
    toolset.get_tools.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_portfolio_tool_aborts_without_orders():
    toolset = make_toolset(omit={"get_portfolio"})
    with pytest.raises(BrokerToolUnavailableError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )
    toolset.mapping["place_equity_order"].run_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_portfolio_timeout_aborts_without_orders():
    toolset = make_toolset()
    toolset.mapping["get_portfolio"].run_async.side_effect = TimeoutError("timeout")
    with pytest.raises(BrokerConnectionError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )
    toolset.mapping["place_equity_order"].run_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"structuredContent": {"data": {"buying_power": {"buying_power": "100"}}}},
        {"structuredContent": {"data": {"cash": "100"}}},
    ],
)
async def test_missing_cash_or_buying_power_aborts(response):
    toolset = make_toolset(portfolio_response=response)
    with pytest.raises(BrokerPayloadError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )


@pytest.mark.asyncio
async def test_malformed_positions_abort():
    toolset = make_toolset(
        position_response={"structuredContent": {"data": {"positions": "bad"}}}
    )
    with pytest.raises(BrokerPayloadError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )


@pytest.mark.asyncio
async def test_missing_quote_aborts_whole_batch():
    toolset = make_toolset(quote_response=quotes({"MU": 100}))
    with pytest.raises(QuoteValidationError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )
    toolset.mapping["place_equity_order"].run_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_price", [0, -1, math.nan, math.inf])
async def test_invalid_quote_aborts(bad_price):
    toolset = make_toolset(quote_response=quotes({"NVDA": bad_price}))
    with pytest.raises(QuoteValidationError):
        await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )


def test_stale_and_crossed_quotes_fail():
    received = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)
    stale = {
        "structuredContent": {
            "data": {
                "results": [
                    {
                        "quote": {
                            "symbol": "NVDA",
                            "last_trade_price": "100",
                            "timestamp": "2026-07-20T19:57:00Z",
                        }
                    }
                ]
            }
        }
    }
    with pytest.raises(QuoteValidationError, match="stale"):
        parse_quotes(stale, {"NVDA"}, received_at=received)
    crossed = {
        "structuredContent": {
            "data": {
                "results": [
                    {
                        "quote": {
                            "symbol": "NVDA",
                            "last_trade_price": "100",
                            "bid_price": "101",
                            "ask_price": "100",
                        }
                    }
                ]
            }
        }
    }
    with pytest.raises(QuoteValidationError, match="crossed"):
        parse_quotes(crossed, {"NVDA"}, received_at=received)


@pytest.mark.asyncio
@patch("app.broker_executor.insert_trade_record")
async def test_successful_sell_defers_drifted_buy(mock_log):
    # The validated proposal was buy-only, but authoritative broker state drifted and
    # now requires a DELL reduction. The executor must submit/simulate only the sell.
    validated = plan(
        [{"ticker": "DELL", "weight_pct": 0.3}, {"ticker": "MU", "weight_pct": 0.3}]
    )
    state_positions = positions(
        [{"symbol": "DELL", "quantity": "2", "average_buy_price": "30"}]
    )
    toolset = make_toolset(
        portfolio_response=portfolio("40", "40"),
        position_response=state_positions,
        quote_response=quotes({"DELL": 30, "MU": 100}),
    )
    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "true"}):
        result = await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            validated
        )
    assert result.status is ExecutionStatus.COMPLETED
    assert [receipt.ticker for receipt in result.receipts] == ["DELL"]
    assert [order.ticker for order in result.deferred_buys] == ["MU"]


@pytest.mark.asyncio
async def test_buy_only_uses_authoritative_buying_power():
    toolset = make_toolset(portfolio_response=portfolio("100", "4"))
    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        result = await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )
    assert result.status is ExecutionStatus.ABORTED
    assert "buying power" in result.reason.lower()
    toolset.mapping["place_equity_order"].run_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"status": "rejected", "order_id": "x"},
        {"status": "accepted"},
    ],
)
async def test_rejected_or_unknown_buy_stops(response):
    toolset = make_toolset(
        order_response=response, quote_response=quotes({"NVDA": 100, "MU": 100})
    )
    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        result = await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan(
                [
                    {"ticker": "NVDA", "weight_pct": 0.3},
                    {"ticker": "MU", "weight_pct": 0.3},
                ]
            )
        )
    assert result.status is ExecutionStatus.ABORTED
    assert toolset.mapping["place_equity_order"].run_async.await_count == 1


def test_direct_executor_rejects_bad_account():
    with pytest.raises(ValueError):
        BrokerExecutor(make_toolset(), "bad-12345")


@pytest.mark.asyncio
async def test_direct_executor_rejects_ticker_outside_central_allowlist():
    toolset = make_toolset(quote_response=quotes({"ZZZZ": 100}))
    validated = plan([{"ticker": "ZZZZ", "weight_pct": 0.3}], allowed_tickers={"ZZZZ"})
    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        with pytest.raises(ValueError, match="outside the authorized"):
            await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
                validated
            )
    toolset.mapping["place_equity_order"].run_async.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.broker_executor.asyncio.sleep", new_callable=AsyncMock)
@patch("app.broker_executor.insert_trade_record")
async def test_filled_order_reconciliation_mismatch_fails_after_three_checks(
    mock_log, mock_sleep
):
    toolset = make_toolset(
        order_response={"status": "filled", "order_id": "filled-1"},
        quote_response=quotes({"NVDA": 100}),
    )
    toolset.mapping["get_equity_positions"].run_async.side_effect = [
        positions(),
        positions(),
        positions(),
        positions(),
    ]
    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        result = await BrokerExecutor(toolset, "MOCK_ACCOUNT_48661").execute_rebalance(
            plan([{"ticker": "NVDA", "weight_pct": 0.3}])
        )
    assert result.status is ExecutionStatus.RECONCILIATION_FAILED
    assert toolset.mapping["get_equity_positions"].run_async.await_count == 4
    assert mock_sleep.await_count == 2
