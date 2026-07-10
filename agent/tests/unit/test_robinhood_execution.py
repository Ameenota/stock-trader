# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from app.broker_executor import BrokerExecutor
from app.tools.bigquery_service import get_last_buy_timestamp, insert_portfolio_snapshot

# ==============================================================================
# 1. Tests for BQ Queries that Robinhood / Execution Controller depends on
# ==============================================================================

@patch("app.tools.bigquery_service.get_bigquery_client")
def test_get_last_buy_timestamp_matches_buy_and_strong_buy(mock_get_client):
    """Verify that get_last_buy_timestamp queries both BUY and STRONG BUY actions."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    # Mock query job returning a timestamp
    mock_row = MagicMock()
    mock_row.timestamp = datetime(2026, 6, 24, 23, 31, 46, tzinfo=timezone.utc)
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [mock_row]
    mock_client.query.return_value = mock_query_job

    # Execute
    ts = get_last_buy_timestamp(ticker="TSM", dry_run=False, dataset_id="test_dataset")

    # Assertions
    assert ts == datetime(2026, 6, 24, 23, 31, 46, tzinfo=timezone.utc)
    mock_client.query.assert_called_once()
    query_str = mock_client.query.call_args[0][0]
    
    # Assert query checks both actions
    assert "action IN ('BUY', 'STRONG BUY')" in query_str
    
    # Verify parameters passed to query
    job_config = mock_client.query.call_args[1]["job_config"]
    params = {p.name: p.value for p in job_config.query_parameters}
    assert params["ticker"] == "TSM"
    assert params["dry_run"] is False

@patch("app.tools.bigquery_service.get_bigquery_client")
def test_get_last_buy_timestamp_returns_none_if_no_record(mock_get_client):
    """Verify that get_last_buy_timestamp returns None if no matching records are returned."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_query_job = MagicMock()
    mock_query_job.result.return_value = []
    mock_client.query.return_value = mock_query_job

    ts = get_last_buy_timestamp(ticker="TSM", dry_run=True, dataset_id="test_dataset")
    assert ts is None


@patch("app.tools.bigquery_service.get_bigquery_client")
def test_insert_portfolio_snapshot(mock_get_client):
    """Verify that insert_portfolio_snapshot submits the snapshot schema correctly."""
    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_get_client.return_value = mock_client
    
    mock_job = MagicMock()
    mock_client.load_table_from_json.return_value = mock_job

    snapshot = {
        "account_number": "••••48661",
        "total_equity": 100.0,
        "total_cash": 15.0,
        "buying_power": 15.0,
        "unrealized_gain_loss": 0.0,
        "unrealized_gain_loss_percent": 0.0,
        "holdings": "[]"
    }

    insert_portfolio_snapshot(snapshot, dataset_id="test_dataset")

    mock_client.load_table_from_json.assert_called_once()
    call_args = mock_client.load_table_from_json.call_args
    assert call_args[0][0][0]["account_number"] == "••••48661"
    assert call_args[0][1] == "test-project.test_dataset.portfolio_snapshot"


# ==============================================================================
# 2. Tests for BrokerExecutor (Live Execution & Overdraft Guardrail)
# ==============================================================================

@pytest.mark.asyncio
@patch("app.broker_executor.insert_trade_record")
async def test_execution_controller_live_trading_mode(mock_log_trade):
    """Verify that place_equity_order is called and logs dry_run=False when SKIP_LIVE_TRADES=false."""
    # 1. Setup mock Robinhood tools
    mock_get_portfolio = AsyncMock()
    mock_get_portfolio.run_async.return_value = {
        "structuredContent": {"data": {"cash": "100.00", "total_value": "100.00"}}
    }
    mock_get_equity_positions = AsyncMock()
    mock_get_equity_positions.run_async.return_value = {
        "structuredContent": {"data": {"positions": []}}
    }
    mock_get_equity_quotes = AsyncMock()
    mock_get_equity_quotes.run_async.return_value = {
        "structuredContent": {"data": {"results": [{"quote": {"symbol": "NVDA", "last_trade_price": "100.00"}}]}}
    }
    mock_place_equity_order = AsyncMock()
    mock_place_equity_order.run_async.return_value = {"status": "success", "order_id": "live-order-id"}

    mock_tools = [
        MagicMock(name="get_portfolio"),
        MagicMock(name="get_equity_positions"),
        MagicMock(name="get_equity_quotes"),
        MagicMock(name="place_equity_order")
    ]
    mock_tools[0].name = "get_portfolio"
    mock_tools[0].run_async = mock_get_portfolio.run_async
    mock_tools[1].name = "get_equity_positions"
    mock_tools[1].run_async = mock_get_equity_positions.run_async
    mock_tools[2].name = "get_equity_quotes"
    mock_tools[2].run_async = mock_get_equity_quotes.run_async
    mock_tools[3].name = "place_equity_order"
    mock_tools[3].run_async = mock_place_equity_order.run_async

    mock_toolset = MagicMock()
    mock_toolset.get_tools = AsyncMock(return_value=mock_tools)

    # 2. Setup controller and run under SKIP_LIVE_TRADES=false
    controller = BrokerExecutor(
        toolset=mock_toolset,
        account_number="MOCK_ACCOUNT_48661",
        dataset_id="test_dataset"
    )

    approved_allocations = [{"ticker": "NVDA", "weight_pct": 0.30}]

    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        await controller.execute_rebalance(approved_allocations)

        # 3. Assertions: place_equity_order should be called since it is live mode!
        mock_place_equity_order.run_async.assert_called_once()
        order_args = mock_place_equity_order.run_async.call_args[1]["args"]
        assert order_args["symbol"] == "NVDA"
        assert order_args["side"] == "buy"
        assert order_args["quantity"] == "0.300000"

        # 4. Verify insert_trade_record was logged with dry_run=False
        mock_log_trade.assert_called_once()
        log_kwargs = mock_log_trade.call_args[1]
        assert log_kwargs["ticker"] == "NVDA"
        assert log_kwargs["action"] == "BUY"
        assert log_kwargs["dry_run"] is False


@pytest.mark.asyncio
@patch("app.broker_executor.insert_trade_record")
async def test_execution_controller_overdraft_guardrail(mock_log_trade):
    """Verify that buy orders are skipped if required buy amount exceeds max spendable buying power."""
    # 1. Setup mock Robinhood tools with low cash ($10 cash, $100 total equity)
    mock_get_portfolio = AsyncMock()
    mock_get_portfolio.run_async.return_value = {
        "structuredContent": {"data": {"cash": "10.00", "total_value": "100.00"}}
    }
    mock_get_equity_positions = AsyncMock()
    mock_get_equity_positions.run_async.return_value = {
        "structuredContent": {"data": {"positions": [{"symbol": "MU", "quantity": "3.0", "average_buy_price": "30.00"}]}}
    }
    mock_get_equity_quotes = AsyncMock()
    mock_get_equity_quotes.run_async.return_value = {
        "structuredContent": {"data": {"results": [
            {"quote": {"symbol": "MU", "last_trade_price": "30.00"}},  # $90 equity
            {"quote": {"symbol": "NVDA", "last_trade_price": "100.00"}}
        ]}}
    }
    mock_place_equity_order = AsyncMock()

    mock_tools = [
        MagicMock(name="get_portfolio"),
        MagicMock(name="get_equity_positions"),
        MagicMock(name="get_equity_quotes"),
        MagicMock(name="place_equity_order")
    ]
    mock_tools[0].name = "get_portfolio"
    mock_tools[0].run_async = mock_get_portfolio.run_async
    mock_tools[1].name = "get_equity_positions"
    mock_tools[1].run_async = mock_get_equity_positions.run_async
    mock_tools[2].name = "get_equity_quotes"
    mock_tools[2].run_async = mock_get_equity_quotes.run_async
    mock_tools[3].name = "place_equity_order"
    mock_tools[3].run_async = mock_place_equity_order.run_async

    mock_toolset = MagicMock()
    mock_toolset.get_tools = AsyncMock(return_value=mock_tools)

    controller = BrokerExecutor(
        toolset=mock_toolset,
        account_number="MOCK_ACCOUNT_48661",
        dataset_id="test_dataset"
    )

    # We want to buy $30 of NVDA, but we only have $10 cash. 
    # Available buying power = $10.
    # Cash reserve = 5% of $100 total equity = $5.
    # Max spend = $10 - $5 = $5.
    # Since $30 > $5, the overdraft guardrail should trigger.
    approved_allocations = [
        {"ticker": "MU", "weight_pct": 0.90},   # Keep MU
        {"ticker": "NVDA", "weight_pct": 0.30}  # Propose buying NVDA (needs $30.00)
    ]

    with patch.dict(os.environ, {"SKIP_LIVE_TRADES": "false"}):
        await controller.execute_rebalance(approved_allocations)
        # 2. Assertions: place_equity_order should NOT be called because of overdraft guardrail!
        mock_place_equity_order.run_async.assert_not_called()
        mock_log_trade.assert_not_called()


@pytest.mark.asyncio
@patch("app.tools.robinhood_service.fetch_robinhood_portfolio_state")
@patch("app.tools.bigquery_service.insert_portfolio_snapshot")
async def test_log_portfolio_snapshot_calculates_correct_unrealized_gain_loss(mock_insert, mock_fetch_state):
    """Verify that log_portfolio_snapshot correctly calculates position-level unrealized gain/loss."""
    # Mock data:
    # cash = 11.00, buying_power = 11.00
    # Holdings:
    # 1. MU: 2 shares @ avg buy price $10, current price $12 (equity $24, gain +$4)
    # 2. MRVL: 5 shares @ avg buy price $6, current price $5 (equity $25, loss -$5)
    # Total holdings equity = $49.00
    # Total cost basis = 2 * 10 + 5 * 6 = $50.00
    # Expected unrealized gain/loss = $49.00 - $50.00 = -$1.00
    # Expected unrealized gain/loss percent = -1.0 / 50.0 * 100 = -2.0%
    mock_fetch_state.return_value = (
        11.00,
        11.00,
        [
            {"symbol": "MU", "shares": 2.0, "average_buy_price": 10.0, "current_price": 12.0, "equity": 24.0},
            {"symbol": "MRVL", "shares": 5.0, "average_buy_price": 6.0, "current_price": 5.0, "equity": 25.0}
        ]
    )

    from app.tools.robinhood_service import log_portfolio_snapshot
    with patch.dict(os.environ, {"ROBINHOOD_ACCOUNT_NUMBER": "586548661", "SKIP_LIVE_TRADES": "true"}):
        await log_portfolio_snapshot(summary="Test summary", dataset_id="test_dataset")

    mock_insert.assert_called_once()
    snapshot = mock_insert.call_args[0][0]
    
    assert snapshot["total_equity"] == 60.0  # 11.00 cash + 49.00 holdings
    assert snapshot["total_cash"] == 11.00
    assert snapshot["unrealized_gain_loss"] == -1.0
    assert snapshot["unrealized_gain_loss_percent"] == -2.0
    assert snapshot["account_number"] == "••••48661"
