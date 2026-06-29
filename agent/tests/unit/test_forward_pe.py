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
from app.tools.data_ingestion import fetch_ticker_market_data, run_sentiment_analysis_pipeline

def test_fetch_ticker_market_data_extracts_forward_pe():
    """Verify that fetch_ticker_market_data successfully retrieves forwardPE from stock.info."""
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.info = {
        "recommendationKey": "buy",
        "targetMeanPrice": 150.0,
        "forwardPE": 45.2,
    }
    # Mock stock.history to return an empty DataFrame or none to bypass technical calculation
    mock_ticker_instance.history.return_value = None

    with patch("app.tools.data_ingestion.yf.Ticker", return_value=mock_ticker_instance):
        data = fetch_ticker_market_data("NVDA")
        assert data["forward_pe"] == 45.2
        assert data["analyst_consensus"] == "buy"
        assert data["target_price"] == 150.0

def test_fetch_ticker_market_data_handles_missing_forward_pe():
    """Verify that fetch_ticker_market_data defaults forward_pe to None when missing."""
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.info = {
        "recommendationKey": "buy",
    }
    mock_ticker_instance.history.return_value = None

    with patch("app.tools.data_ingestion.yf.Ticker", return_value=mock_ticker_instance):
        data = fetch_ticker_market_data("NVDA")
        assert data["forward_pe"] is None

@pytest.mark.asyncio
@patch("app.tools.data_ingestion.ingest_market_data")
@patch("app.tools.bigquery_service.get_recent_sentiment_scores")
@patch("app.tools.ticker_universe.determine_active_watchlist")
async def test_run_sentiment_analysis_pipeline_attaches_forward_pe(
    mock_determine_watchlist, mock_get_recent_scores, mock_ingest
):
    """Verify that run_sentiment_analysis_pipeline correctly maps forward_pe to ranked_portfolio and graveyard rows."""
    # 1. Mock watchlist
    mock_determine_watchlist.return_value = (["NVDA", "TLT"], {
        "NVDA": {"status": "ACTIVE"},
        "TLT": {"status": "ACTIVE"},
        "SMCI": {"status": "FILTERED", "reason": "Below 50-day SMA"}
    })

    # 2. Mock market data with forwardPE values
    def mock_ingest_side_effect(tickers=None, **kwargs):
        if tickers == ["SPY"]:
            return {"SPY": {"current_price": 500.0}}
        return {
            "NVDA": {
                "news": [{"content": {"title": "NVDA News"}}],
                "current_price": 140.0,
                "rsi": 50.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "drawdown_pct": 5.0,
                "sustained_rsi_drop": False,
                "is_20d_high": False,
                "macd_bullish_cross": False,
                "forward_pe": 45.0
            },
            "TLT": {
                "news": [],
                "current_price": 95.0,
                "rsi": 50.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "drawdown_pct": 0.0,
                "sustained_rsi_drop": False,
                "is_20d_high": False,
                "macd_bullish_cross": False,
                "forward_pe": None
            }
        }
    mock_ingest.side_effect = mock_ingest_side_effect

    mock_get_recent_scores.return_value = {}

    # Mock Gemini sentiment response
    from app.tools.ranking import SentimentAnalysisResponse, SentimentAnalysis
    mock_session = MagicMock()
    mock_session.state = {
        "sentiment_result": SentimentAnalysisResponse(analyses=[
            SentimentAnalysis(ticker="NVDA", raw_score=0.50, thesis="Strong AI trend"),
            SentimentAnalysis(ticker="TLT", raw_score=0.00, thesis="No news")
        ])
    }

    with patch("google.adk.sessions.InMemorySessionService.create_session", return_value=mock_session), \
         patch("google.adk.sessions.InMemorySessionService.get_session", return_value=mock_session), \
         patch("google.adk.runners.Runner.run_async") as mock_run:

        async def async_run_gen(*args, **kwargs):
            for val in []:
                yield val
        mock_run.side_effect = async_run_gen

        ranked_portfolio, graveyard_rows = await run_sentiment_analysis_pipeline(dataset_id="test_dataset")

        # 3. Assertions
        nvda_item = next(item for item in ranked_portfolio if item["ticker"] == "NVDA")
        assert nvda_item["forward_pe"] == 45.0

        tlt_item = next(item for item in ranked_portfolio if item["ticker"] == "TLT")
        assert tlt_item["forward_pe"] is None

        # Verify graveyard and benchmark have forward_pe set to None
        smci_item = next(item for item in graveyard_rows if item["ticker"] == "SMCI")
        assert smci_item["forward_pe"] is None

        spy_item = next(item for item in graveyard_rows if item["ticker"] == "SPY")
        assert spy_item["forward_pe"] is None
