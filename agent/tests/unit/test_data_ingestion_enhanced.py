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

import time
from unittest.mock import MagicMock, patch
import pytest
import pandas as pd
from datetime import datetime, timezone
from app.tools.data_ingestion import fetch_ticker_market_data, ingest_market_data

@pytest.fixture
def mock_news_data():
    current_time = 1700000000.0  # Constant reference time
    def get_iso_str(ts):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    return [
        {
            "id": "1",
            "content": {
                "id": "1",
                "contentType": "STORY",
                "title": "AI Hardware Demand Surges",
                "summary": "NVDA reports record chip orders from tech giants.",
                "pubDate": get_iso_str(current_time - 7200),  # 2 hours ago
            }
        }
    ]

@patch("app.tools.data_ingestion.yf.Ticker")
def test_fetch_ticker_market_data_success(mock_ticker_class, mock_news_data):
    current_time = 1700000000.0

    mock_ticker_instance = MagicMock()
    # Mock news
    mock_ticker_instance.news = mock_news_data
    
    # Mock fundamental info
    mock_ticker_instance.info = {
        "recommendationKey": "buy",
        "targetMeanPrice": 150.0,
        "currentPrice": 140.0
    }
    
    # Mock history dataframe (45 closing values to satisfy pandas-ta MACD/RSI requirement)
    close_prices = [float(100 + i) for i in range(45)]
    mock_ticker_instance.history.return_value = pd.DataFrame({
        "Close": close_prices
    })
    
    mock_ticker_class.return_value = mock_ticker_instance

    results = fetch_ticker_market_data("NVDA", current_time=current_time)

    # Calculate expected values
    expected_current_price = 144.0
    expected_ma_20 = sum(close_prices[-20:]) / 20  # 134.5
    expected_ratio = expected_current_price / expected_ma_20

    # Verification
    assert len(results["news"]) == 1
    assert results["news"][0]["title"] == "AI Hardware Demand Surges"
    assert results["analyst_consensus"] == "buy"
    assert results["target_price"] == 150.0
    assert results["current_price"] == expected_current_price
    assert pytest.approx(results["moving_average_20d"]) == expected_ma_20
    assert pytest.approx(results["price_to_ma_ratio"]) == expected_ratio
    assert results["rsi"] is not None
    assert results["macd"] is not None
    assert results["macd_signal"] is not None


@patch("app.tools.data_ingestion.yf.Ticker")
def test_fetch_ticker_market_data_empty_history_fallback(mock_ticker_class, mock_news_data):
    current_time = 1700000000.0

    mock_ticker_instance = MagicMock()
    mock_ticker_instance.news = mock_news_data
    mock_ticker_instance.info = {
        "recommendationKey": "hold",
        "targetMeanPrice": 120.0,
        "currentPrice": 115.0
    }
    # Return empty history to trigger fallback
    mock_ticker_instance.history.return_value = pd.DataFrame()
    mock_ticker_class.return_value = mock_ticker_instance

    results = fetch_ticker_market_data("AMD", current_time=current_time)

    # Verification
    assert results["analyst_consensus"] == "hold"
    assert results["target_price"] == 120.0
    assert results["current_price"] == 115.0  # Fell back to currentPrice info
    assert results["moving_average_20d"] is None
    assert results["price_to_ma_ratio"] is None
    assert results["rsi"] is None
    assert results["macd"] is None
    assert results["macd_signal"] is None


@patch("app.tools.data_ingestion.yf.Ticker")
def test_ingest_market_data_structure(mock_ticker_class, mock_news_data):
    current_time = 1700000000.0

    mock_ticker_instance = MagicMock()
    mock_ticker_instance.news = mock_news_data
    mock_ticker_instance.info = {
        "recommendationKey": "strong_buy",
        "targetMeanPrice": 200.0
    }
    close_prices = [float(150 + i) for i in range(45)]
    mock_ticker_instance.history.return_value = pd.DataFrame({
        "Close": close_prices
    })
    mock_ticker_class.return_value = mock_ticker_instance

    results = ingest_market_data(current_time=current_time)

    expected_tickers = ["NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT"]
    assert set(results.keys()) == set(expected_tickers)

    for ticker in expected_tickers:
        data = results[ticker]
        assert isinstance(data["news"], list)
        assert len(data["news"]) == 1
        assert data["analyst_consensus"] == "strong_buy"
        assert data["target_price"] == 200.0
        assert data["current_price"] == 194.0
        assert data["moving_average_20d"] == 184.5
        assert pytest.approx(data["price_to_ma_ratio"]) == (194.0 / 184.5)
        assert data["rsi"] is not None
        assert data["macd"] is not None
        assert data["macd_signal"] is not None
