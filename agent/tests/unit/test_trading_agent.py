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
from unittest.mock import MagicMock
from app.agent import validate_and_intercept_trades

@pytest.mark.asyncio
async def test_validate_and_intercept_trades_invalid_account():
    """Verify that targeting an unauthorized account raises a ValueError."""
    mock_tool = MagicMock()
    mock_tool.name = "place_order"
    
    # Unauthorized account ending in 12345
    args = {"account_number": "12345", "symbol": "NVDA", "quantity": 1}
    mock_context = MagicMock()

    with pytest.raises(ValueError, match="All actions are restricted to account ending in 48661"):
        await validate_and_intercept_trades(mock_tool, args, mock_context)


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_valid_account():
    """Verify that a valid account ending in 48661 passes account checks."""
    mock_tool = MagicMock()
    mock_tool.name = "get_holdings"
    
    # Authorized account
    args = {"account_number": "account-48661"}
    mock_context = MagicMock()

    # Should not raise exception
    res = await validate_and_intercept_trades(mock_tool, args, mock_context)
    assert res is None  # Pass-through


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_invalid_symbol():
    """Verify that trading an unauthorized stock raises a ValueError."""
    mock_tool = MagicMock()
    mock_tool.name = "buy_stock"
    
    # Valid account but a symbol absent from the versioned central allowlist.
    args = {"account_number": "48661", "symbol": "ZZZZ", "quantity": 1}
    mock_context = MagicMock()

    with pytest.raises(ValueError, match="outside the authorized asset universe"):
        await validate_and_intercept_trades(mock_tool, args, mock_context)


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_list_symbols_valid():
    """Verify that a valid list of stock symbols passes checks."""
    mock_tool = MagicMock()
    mock_tool.name = "get_quotes"
    
    args = {"account_number": "48661", "symbols": ["MU", "DELL", "TSM"]}
    mock_context = MagicMock()

    res = await validate_and_intercept_trades(mock_tool, args, mock_context)
    assert res is None  # Pass-through


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_list_symbols_invalid():
    """Verify that an invalid stock symbol in a list raises a ValueError."""
    mock_tool = MagicMock()
    mock_tool.name = "get_quotes"
    
    args = {"account_number": "48661", "symbols": ["MU", "ZZZZ", "TSM"]}
    mock_context = MagicMock()

    with pytest.raises(ValueError, match="outside the authorized asset universe"):
        await validate_and_intercept_trades(mock_tool, args, mock_context)


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_dry_run_execution():
    """Verify that SKIP_LIVE_TRADES=true intercepts write operations and mocks success."""
    # Set dry-run env flag
    os.environ["SKIP_LIVE_TRADES"] = "true"
    
    mock_tool = MagicMock()
    mock_tool.name = "place_order"
    
    # Valid arguments
    args = {"account_number": "48661", "symbol": "NVDA", "quantity": 1}
    mock_context = MagicMock()

    res = await validate_and_intercept_trades(mock_tool, args, mock_context)
    
    # Verification
    assert res is not None
    assert res["status"] == "success"
    assert "Simulated execution" in res["message"]
    assert res["simulated"] is True


@pytest.mark.asyncio
async def test_validate_and_intercept_trades_dry_run_query_passthrough():
    """Verify that SKIP_LIVE_TRADES=true does NOT intercept read operations (queries)."""
    os.environ["SKIP_LIVE_TRADES"] = "true"
    
    mock_tool = MagicMock()
    mock_tool.name = "get_portfolio"
    
    # Valid arguments
    args = {"account_number": "48661"}
    mock_context = MagicMock()

    res = await validate_and_intercept_trades(mock_tool, args, mock_context)
    
    # Must be None so the real query proceeds to the MCP server
    assert res is None
