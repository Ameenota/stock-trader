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
from app.tools.ticker_universe import (
    ACTIVE_TICKERS,
    MAX_ACTIVE_WATCHLIST_SIZE,
    TICKER_SECTORS,
    TICKER_UNIVERSE,
    determine_active_watchlist,
)


def test_universe_is_multi_sector_and_fallback_remains_capped():
    assert len(TICKER_UNIVERSE) >= 120
    assert len(set(TICKER_SECTORS.values())) >= 11
    assert len(ACTIVE_TICKERS) == MAX_ACTIVE_WATCHLIST_SIZE
    assert len({TICKER_SECTORS[ticker] for ticker in ACTIVE_TICKERS}) >= 8


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_with_owned_holdings(mock_ticker_class, mock_get_holdings, mock_get_recently_sold):
    """Verify that currently owned stocks are always forced into the active watchlist."""
    # Mock holdings: We own META and MSFT
    mock_get_holdings.return_value = ["META", "MSFT"]
    # No recently sold
    mock_get_recently_sold.return_value = []

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
    assert len(watchlist) == MAX_ACTIVE_WATCHLIST_SIZE
    
    # Assert all items are unique
    assert len(set(watchlist)) == 11
    # Assert they are all within the TICKER_UNIVERSE
    for ticker in watchlist:
        assert ticker in TICKER_UNIVERSE


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_required_paper_holding_survives_shared_screen(
    mock_ticker_class, mock_get_holdings, mock_get_recently_sold
):
    """A holding from a non-default account must receive full daily analysis."""
    mock_get_holdings.return_value = []
    mock_get_recently_sold.return_value = []

    def mock_history_side_effect(ticker):
        mock_ticker = MagicMock()
        prices = [100.0] * 60
        if ticker == "META":
            prices[-1] = 80.0
        mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
        return mock_ticker

    mock_ticker_class.side_effect = mock_history_side_effect

    watchlist, details = await determine_active_watchlist(
        dataset_id="test_dataset",
        return_details=True,
        required_tickers=["META"],
    )

    assert watchlist[0] == "META"
    assert details["META"]["status"] == "SELECTED"
    assert details["META"]["reason"] == "Owned position promotion"


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_filters_sma_and_sorts_momentum(mock_ticker_class, mock_get_holdings, mock_get_recently_sold):
    """Verify that candidates below 50d SMA are filtered, and valid candidates are ranked by momentum."""
    # No owned holdings
    mock_get_holdings.return_value = []
    # No recently sold
    mock_get_recently_sold.return_value = []

    # We will configure mock history based on the ticker symbol
    def mock_history_side_effect(ticker):
        mock_ticker = MagicMock()
        
        if ticker == "GOOGL":
            # Rising trend: SMA is ~50, current price is 60 (momentum = 1.2)
            prices = [50.0] * 49 + [60.0]
            mock_ticker.history.return_value = pd.DataFrame({"Close": prices})
        elif ticker == "AMZN":
            # Downward trend: SMA is ~104, current price is 80 (momentum = 0.77, should be filtered out).
            # Last 25 days alternate to introduce gains and keep RSI at ~50 (avoiding the <25 oversold bypass).
            prices = [120.0] * 35 + ([80.0, 82.0] * 12) + [80.0]
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

    # Watchlist must still be padded to exactly 11 tickers
    assert len(watchlist) == MAX_ACTIVE_WATCHLIST_SIZE


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_candidate_watchlist_is_sector_balanced_and_capped(
    mock_ticker_class, mock_get_holdings, mock_get_recently_sold
):
    mock_get_holdings.return_value = []
    mock_get_recently_sold.return_value = []

    def mock_history_side_effect(ticker):
        mock_ticker = MagicMock()
        # Every ticker passes. Earlier catalog entries have equal momentum, so
        # the per-sector gate—not incidental network order—must diversify them.
        mock_ticker.history.return_value = pd.DataFrame({"Close": [100.0] * 60})
        return mock_ticker

    mock_ticker_class.side_effect = mock_history_side_effect
    watchlist = await determine_active_watchlist(dataset_id="test_dataset")

    assert len(watchlist) == MAX_ACTIVE_WATCHLIST_SIZE
    sector_counts = {}
    for ticker in watchlist:
        sector = TICKER_SECTORS[ticker]
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    assert max(sector_counts.values()) <= 2
    assert len(sector_counts) >= 6


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_filters_recently_sold(mock_ticker_class, mock_get_holdings, mock_get_recently_sold):
    """Verify that recently sold stocks are excluded from the watchlist candidates and padding."""
    # No owned holdings
    mock_get_holdings.return_value = []
    # Recently sold: "NVDA" and "AMD"
    mock_get_recently_sold.return_value = ["NVDA", "AMD"]

    # Configure mock history: rising trend (current price > sma_50)
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.history.return_value = pd.DataFrame({
        "Close": [float(i) for i in range(60)]
    })
    mock_ticker_class.return_value = mock_ticker_instance

    watchlist, details = await determine_active_watchlist(dataset_id="test_dataset", return_details=True)

    # NVDA and AMD should NOT be in the watchlist because they were recently sold
    assert "NVDA" not in watchlist
    assert "AMD" not in watchlist
    assert len(watchlist) == MAX_ACTIVE_WATCHLIST_SIZE
    
    # Assert they are filtered in details with correct reason
    assert details["NVDA"]["status"] == "FILTERED"
    assert details["NVDA"]["reason"] == "Recently sold (21-day cool-down)"
    assert details["AMD"]["status"] == "FILTERED"
    assert details["AMD"]["reason"] == "Recently sold (21-day cool-down)"
