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

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from app.tools.ticker_universe import determine_active_watchlist, TICKER_UNIVERSE, ACTIVE_TICKERS


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_with_owned_holdings(mock_ticker_class, mock_get_holdings):
    """Verify that currently owned stocks are always forced into the active watchlist."""
    # Mock holdings: We own META and MSFT
    mock_get_holdings.return_value = ["META", "MSFT"]

    # Mock yfinance for the rest of the tickers
    mock_ticker_instance = MagicMock()
    
    # Return 60 days of closing prices where price is steady (momentum = 1.0)
    mock_ticker_instance.history.return_value = pd.DataFrame({
        "Close": [100.0] * 60
    })
    mock_ticker_class.return_value = mock_ticker_instance

    watchlist = await determine_active_watchlist(dataset_id="test_dataset")

    # Verify owned tickers are forced into the watchlist first
    assert "META" in watchlist
    assert "MSFT" in watchlist
    assert len(watchlist) == 10
    
    # Assert all items are unique
    assert len(set(watchlist)) == 10
    # Assert they are all within the TICKER_UNIVERSE
    for ticker in watchlist:
        assert ticker in TICKER_UNIVERSE


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_filters_sma_and_sorts_momentum(mock_ticker_class, mock_get_holdings):
    """Verify that candidates below 50d SMA are filtered, and valid candidates are ranked by momentum."""
    # No owned holdings
    mock_get_holdings.return_value = []

    # We will configure mock history based on the ticker symbol
    def mock_history_side_effect(ticker):
        mock_ticker = MagicMock()
        
        if ticker == "GOOGL":
            # Rising trend: SMA is ~50, current price is 60 (momentum = 1.2)
            prices = [50.0] * 49 + [60.0]
            mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
        elif ticker == "AMZN":
            # Downward trend: SMA is ~100, current price is 80 (momentum = 0.8, should be filtered out)
            prices = [100.0] * 49 + [80.0]
            mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
        elif ticker == "PLTR":
            # High rising trend: SMA is ~20, current price is 30 (momentum = 1.5)
            prices = [20.0] * 49 + [30.0]
            mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
        else:
            # Flat trend: SMA is 100, current price is 100 (momentum = 1.0)
            prices = [100.0] * 60
            mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
            
        return mock_ticker

    mock_ticker_class.side_effect = mock_history_side_effect

    watchlist = await determine_active_watchlist(dataset_id="test_dataset")

    # AMZN should NOT be in the watchlist because its current price (80) is below its 50d SMA (100)
    assert "AMZN" not in watchlist

    # PLTR should be ranked HIGHER than GOOGL and flat trend tickers because of higher momentum (1.5 vs 1.2 vs 1.0)
    # Since there are no owned holdings, the top picks start the watchlist.
    # PLTR (1.5) should be first, GOOGL (1.2) should be second.
    assert watchlist[0] == "PLTR"
    assert watchlist[1] == "GOOGL"

    # Watchlist must still be padded to exactly 10 tickers
    assert len(watchlist) == 10
