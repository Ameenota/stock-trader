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
from unittest.mock import AsyncMock, MagicMock, patch
from google.adk.events import Event, EventActions
from google.adk.agents.invocation_context import InvocationContext
from app.agent import EscalationChecker, TargetAllocation, AdvisorCritique
from app.broker_executor import BrokerExecutor

@pytest.mark.asyncio
async def test_escalation_checker_approved():
    """Verify EscalationChecker raises escalate=True event if critique is approved."""
    checker = EscalationChecker(name="test_checker")
    
    # Mock InvocationContext
    mock_ctx = MagicMock()
    mock_ctx.session.state = {
        "advisor_critique": AdvisorCritique(approved=True, feedback="Approved Nvidia buy.")
    }
    
    events = []
    async for event in checker._run_async_impl(mock_ctx):
        events.append(event)
        
    assert len(events) == 1
    assert events[0].actions is not None
    assert events[0].actions.escalate is True


@pytest.mark.asyncio
async def test_escalation_checker_rejected():
    """Verify EscalationChecker does NOT raise escalate=True event if critique is rejected."""
    checker = EscalationChecker(name="test_checker")
    
    # Mock InvocationContext
    mock_ctx = MagicMock()
    mock_ctx.session.state = {
        "advisor_critique": AdvisorCritique(approved=False, feedback="Nvidia is overbought (RSI > 70).")
    }
    
    events = []
    async for event in checker._run_async_impl(mock_ctx):
        events.append(event)
        
    assert len(events) == 1
    assert events[0].actions is None or not events[0].actions.escalate


@pytest.mark.asyncio
async def test_execution_controller_rebalance_calculations():
    """Verify that raw agent allocations cannot cross the execution boundary."""
    # 1. Mock the Robinhood tools
    mock_get_portfolio = AsyncMock()
    mock_get_portfolio.run_async.return_value = {
        "structuredContent": {
            "data": {
                "cash": "15.00",      # Starting cash is $15.00 (15% of $100.00 total equity)
                "total_value": "100.00"
            }
        }
    }

    mock_get_equity_positions = AsyncMock()
    mock_get_equity_positions.run_async.return_value = {
        "structuredContent": {
            "data": {
                "positions": [
                    {"symbol": "MU", "quantity": "1.0"},    # $29.00 value
                    {"symbol": "DELL", "quantity": "2.0"},  # $56.00 value
                ]
            }
        }
    }

    mock_get_equity_quotes = AsyncMock()
    mock_get_equity_quotes.run_async.return_value = {
        "structuredContent": {
            "data": {
                "results": [
                    {"quote": {"symbol": "MU", "last_trade_price": "29.00"}},
                    {"quote": {"symbol": "DELL", "last_trade_price": "28.00"}},
                    {"quote": {"symbol": "TSM", "last_trade_price": "30.00"}},
                ]
            }
        }
    }

    mock_place_equity_order = AsyncMock()
    mock_place_equity_order.run_async.return_value = {"status": "success", "order_id": "mock-id"}

    mock_tools = [
        MagicMock(name="get_portfolio"),
        MagicMock(name="get_equity_positions"),
        MagicMock(name="get_equity_quotes"),
        MagicMock(name="place_equity_order"),
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

    # 2. Define approved allocations
    # Total Equity = $15 (cash) + $29 (MU) + $56 (DELL) = $100.
    # Target allocations:
    # - TSM: 30% ($30.00) -> Currently $0 (not held). New Buy.
    # - MU: 30% ($30.00) -> Currently $29 (29%). Absolute delta is 1% which is <= 3% position tolerance. Should skip rebalancing!
    # - DELL: 30% ($30.00) -> Currently $56 (56%). Absolute delta is 26% which is > 3% position tolerance. Should scale down.
    approved_allocations = [
        {"ticker": "TSM", "weight_pct": 0.30},
        {"ticker": "MU", "weight_pct": 0.30},
        {"ticker": "DELL", "weight_pct": 0.30},
    ]

    controller = BrokerExecutor(
        toolset=mock_toolset,
        account_number="MOCK_ACCOUNT_48661",
        dataset_id="test_dataset"
    )

    with pytest.raises(TypeError, match="ValidatedExecutionPlan"):
        await controller.execute_rebalance(approved_allocations)
    mock_toolset.get_tools.assert_not_awaited()
