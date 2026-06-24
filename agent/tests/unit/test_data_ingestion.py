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
from app.tools.data_ingestion import fetch_ticker_news, ingest_market_news


@pytest.fixture
def mock_news_data():
    current_time = 1700000000.0  # Constant reference time

    # Mock news items
    return [
        {
            # Within 24 hours (2 hours ago)
            "title": "AI Hardware Demand Surges",
            "summary": "NVDA reports record chip orders from tech giants.",
            "providerPublishTime": int(current_time - 7200),
            "publisher": "Tech News",
            "link": "https://example.com/nvda-news-1",
        },
        {
            # Outside 24 hours (25 hours ago)
            "title": "Old Market Analysis",
            "summary": "Older summary of market movements.",
            "providerPublishTime": int(current_time - 90000),
            "publisher": "Finance Daily",
            "link": "https://example.com/nvda-news-2",
        },
        {
            # Missing publish time
            "title": "Breaking Tech Update",
            "summary": "Update with no timestamp.",
            "publisher": "Global News",
            "link": "https://example.com/nvda-news-3",
        },
        {
            # Exactly 24 hours ago (boundary condition)
            "title": "On the Dot Update",
            "summary": "Exactly 24 hours ago.",
            "providerPublishTime": int(current_time - 86400),
            "publisher": "FinTech",
            "link": "https://example.com/nvda-news-4",
        },
    ]


@patch("app.tools.data_ingestion.yf.Ticker")
def test_fetch_ticker_news_filtering(mock_ticker_class, mock_news_data):
    current_time = 1700000000.0

    # Configure the mock Ticker instance news attribute
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.news = mock_news_data
    mock_ticker_class.return_value = mock_ticker_instance

    results = fetch_ticker_news("NVDA", current_time=current_time)

    # We expect exactly 2 items: "AI Hardware Demand Surges" (2 hours ago)
    # and "On the Dot Update" (24 hours ago).
    # "Old Market Analysis" (25 hours ago) should be filtered out.
    # "Breaking Tech Update" (no publish time) should be ignored.
    assert len(results) == 2

    assert results[0]["title"] == "AI Hardware Demand Surges"
    assert results[0]["summary"] == "NVDA reports record chip orders from tech giants."

    assert results[1]["title"] == "On the Dot Update"
    assert results[1]["summary"] == "Exactly 24 hours ago."

    # Verify keys are strictly "title" and "summary"
    for item in results:
        assert list(item.keys()) == ["title", "summary"]


@patch("app.tools.data_ingestion.yf.Ticker")
def test_ingest_market_news_structure(mock_ticker_class, mock_news_data):
    current_time = 1700000000.0

    mock_ticker_instance = MagicMock()
    mock_ticker_instance.news = mock_news_data
    mock_ticker_class.return_value = mock_ticker_instance

    results = ingest_market_news(current_time=current_time)

    # Predefined tickers lists: should have keys for all 10 tickers
    expected_tickers = ["NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT"]
    assert set(results.keys()) == set(expected_tickers)

    for ticker in expected_tickers:
        assert isinstance(results[ticker], list)
        assert len(results[ticker]) == 2
