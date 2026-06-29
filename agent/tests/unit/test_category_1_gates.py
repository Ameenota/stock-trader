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
import numpy as np
from unittest.mock import MagicMock, patch
from app.tools.ticker_universe import determine_active_watchlist
from app.tools.data_ingestion import run_sentiment_analysis_pipeline, ingest_market_data


@pytest.mark.asyncio
@patch("app.tools.bigquery_service.get_recently_sold_tickers")
@patch("app.tools.bigquery_service.get_latest_portfolio_holdings")
@patch("app.tools.ticker_universe.yf.Ticker")
async def test_determine_active_watchlist_sma_bypass_for_oversold(mock_ticker_class, mock_get_holdings, mock_get_recently_sold):
    """Verify that candidate stocks below 50d SMA are promoted if they are deeply oversold (RSI < 25)."""
    # No owned holdings
    mock_get_holdings.return_value = []
    # No recently sold
    mock_get_recently_sold.return_value = []

    # Configure mock history based on the ticker symbol
    def mock_history_side_effect(ticker):
        mock_ticker = MagicMock()
        
        if ticker == "AMZN":
            # Below SMA: SMA is ~100, current price is 80 (momentum = 0.8), but RSI is 0 (deeply oversold due to sudden drop)
            prices = [100.0] * 49 + [80.0]
            df = pd.DataFrame({"Close": prices})
            mock_ticker.history.return_value = df
        elif ticker == "GOOGL":
            # Below SMA: SMA is ~104, current price is 80 (momentum = 0.77), and RSI is ~50 (not oversold)
            prices = [120.0] * 35 + ([80.0, 82.0] * 12) + [80.0]
            df = pd.DataFrame({"Close": prices})
            mock_ticker.history.return_value = df
        else:
            # All other tickers are below SMA and not oversold
            prices = [120.0] * 35 + ([80.0, 82.0] * 12) + [80.0]
            df = pd.DataFrame({"Close": prices})
            mock_ticker.history.return_value = df
            
        return mock_ticker

    mock_ticker_class.side_effect = mock_history_side_effect

    watchlist = await determine_active_watchlist(dataset_id="test_dataset")

    # AMZN should be promoted to watchlist because it is deeply oversold (RSI < 25) despite being below SMA
    assert "AMZN" in watchlist

    # GOOGL should NOT be in the watchlist because it is below SMA and not oversold
    assert "GOOGL" not in watchlist


@pytest.mark.asyncio
@patch("app.tools.data_ingestion.ingest_market_data")
@patch("app.tools.bigquery_service.get_recent_sentiment_scores")
@patch("app.tools.ticker_universe.determine_active_watchlist")
@patch("google.adk.runners.Runner")
async def test_no_news_decay_bypass_logic(mock_runner_class, mock_determine_watchlist, mock_get_recent_scores, mock_ingest):
    """Verify that tickers with no news bypass Gemini API calls and receive a 30% decayed EWMA sentiment score."""
    # 1. Mock watchlist: MSFT and AMD
    mock_determine_watchlist.return_value = (["MSFT", "AMD"], {"MSFT": {"status": "ACTIVE"}, "AMD": {"status": "ACTIVE"}})

    # 2. Mock market data: MSFT has news, AMD has NO news
    mock_ingest.return_value = {
        "MSFT": {
            "news": [{"content": {"title": "MSFT Earnings"}}],
            "current_price": 400.0,
            "rsi": 45.0,
            "macd": 0.5,
            "macd_signal": 0.3,
            "drawdown_pct": 2.0,
            "sustained_rsi_drop": False,
            "is_20d_high": True,
            "macd_bullish_cross": True
        },
        "AMD": {
            "news": [],  # No news!
            "current_price": 150.0,
            "rsi": 35.0,
            "macd": -0.2,
            "macd_signal": -0.1,
            "drawdown_pct": 12.0,
            "sustained_rsi_drop": False,
            "is_20d_high": False,
            "macd_bullish_cross": False
        }
    }

    # 3. Mock BigQuery historical sentiment for AMD: past scores average out to +0.40
    mock_get_recent_scores.side_effect = lambda tickers, limit, dataset_id: {
        "AMD": [0.40, 0.40, 0.40]
    } if "AMD" in tickers else {}

    # 4. Mock the Gemini session runner to only return MSFT analysis
    mock_runner_instance = MagicMock()
    mock_runner_class.return_value = mock_runner_instance

    # Mock runner's asynchronous generator
    async def async_run_gen(*args, **kwargs):
        for val in []:
            yield val

    mock_runner_instance.run_async.side_effect = async_run_gen

    # Mock session state retrieval for Gemini sentiment
    from app.tools.ranking import SentimentAnalysisResponse, SentimentAnalysis
    mock_session = MagicMock()
    mock_session.state = {
        "sentiment_result": SentimentAnalysisResponse(analyses=[
            SentimentAnalysis(ticker="MSFT", raw_score=0.80, thesis="Strong earnings beat.")
        ])
    }
    
    with patch("google.adk.sessions.InMemorySessionService.create_session", return_value=mock_session), \
         patch("google.adk.sessions.InMemorySessionService.get_session", return_value=mock_session):
         
        ranked_portfolio, _ = await run_sentiment_analysis_pipeline(dataset_id="test_dataset")

        # 5. Assertions
        # Both MSFT and AMD should be ranked in the output
        tickers = [item["ticker"] for item in ranked_portfolio]
        assert "MSFT" in tickers
        assert "AMD" in tickers

        # Find AMD's decayed score: BQ EWMA is 0.40, decayed raw_score = 0.40 * 0.7 = 0.28
        amd_item = next(item for item in ranked_portfolio if item["ticker"] == "AMD")
        assert amd_item["raw_score"] == 0.28
        assert "Damped prior sentiment trend" in amd_item["thesis"]


@pytest.mark.asyncio
@patch("app.tools.data_ingestion.ingest_market_data")
@patch("app.tools.bigquery_service.get_recent_sentiment_scores")
@patch("app.tools.ticker_universe.determine_active_watchlist")
async def test_liquidation_floor_override(mock_determine_watchlist, mock_get_recent_scores, mock_ingest):
    """Verify that a relative bottom-3 rank 'LIQUIDATE' signal is overridden to 'HOLD' if EWMA >= 0.05."""
    # 1. Watchlist of 5 tickers (so bottom-3 are liquidations)
    tickers = ["A", "B", "C", "D", "E"]
    mock_determine_watchlist.return_value = (tickers, {t: {"status": "ACTIVE"} for t in tickers})

    # 2. Mock market data
    mock_ingest.return_value = {
        t: {
            "news": [{"content": {"title": "News"}}],
            "current_price": 100.0,
            "rsi": 50.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "drawdown_pct": 5.0,
            "sustained_rsi_drop": False,
            "is_20d_high": False,
            "macd_bullish_cross": False
        } for t in tickers
    }

    # 3. Mock BigQuery historical scores: return scores that average above +0.05 for all tickers
    mock_get_recent_scores.return_value = {
        t: [0.10, 0.10, 0.10] for t in tickers
    }

    # 4. Mock Gemini sentiment to return flat scores, sorting order: A < B < C < D < E
    # Even though raw scores are flat/low, BQ EWMA is +0.10 (>= 0.05)
    from app.tools.ranking import SentimentAnalysisResponse, SentimentAnalysis
    mock_session = MagicMock()
    mock_session.state = {
        "sentiment_result": SentimentAnalysisResponse(analyses=[
            SentimentAnalysis(ticker="A", raw_score=-0.05, thesis="Thesis A"),
            SentimentAnalysis(ticker="B", raw_score=0.00, thesis="Thesis B"),
            SentimentAnalysis(ticker="C", raw_score=0.01, thesis="Thesis C"),
            SentimentAnalysis(ticker="D", raw_score=0.10, thesis="Thesis D"),
            SentimentAnalysis(ticker="E", raw_score=0.25, thesis="Thesis E"),
        ])
    }

    with patch("google.adk.sessions.InMemorySessionService.create_session", return_value=mock_session), \
         patch("google.adk.sessions.InMemorySessionService.get_session", return_value=mock_session), \
         patch("google.adk.runners.Runner.run_async") as mock_run:

        # Mock runner async generator
        async def async_run_gen(*args, **kwargs):
            for val in []:
                yield val
        mock_run.side_effect = async_run_gen

        ranked_portfolio, _ = await run_sentiment_analysis_pipeline(dataset_id="test_dataset")

        # Sort the output by relative rank to inspect A, B, C (ranks 1, 2, 3)
        ranked_portfolio.sort(key=lambda x: x["relative_rank"])

        # A, B, C would normally be flagged as LIQUIDATE because they are ranks 1, 2, 3.
        # But their 5-day EWMA sentiment is +0.10 (>= +0.05).
        # Therefore, their signals must be overridden to HOLD.
        for item in ranked_portfolio[:3]:
            assert item["signal"] == "HOLD"
            assert "Liquidation Override" in item["thesis"]
