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
from app.tools.data_ingestion import (
    MAX_NEWS_ARTICLES_PER_TICKER,
    MAX_SENTIMENT_ARTICLES_PER_RUN,
    build_bounded_news_payload,
    fetch_ticker_news,
    ingest_market_news,
)


from datetime import datetime, timezone

@pytest.fixture
def mock_news_data():
    current_time = 1700000000.0  # Constant reference time

    # Helper to generate UTC ISO strings
    def get_iso_str(ts):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    # Mock nested news items matching the new yfinance structure
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
        },
        {
            "id": "2",
            "content": {
                "id": "2",
                "contentType": "STORY",
                "title": "Old Market Analysis",
                "summary": "Older summary of market movements.",
                "pubDate": get_iso_str(current_time - 90000),  # 25 hours ago
            }
        },
        {
            "id": "3",
            "content": {
                "id": "3",
                "contentType": "STORY",
                "title": "Breaking Tech Update",
                "summary": "Update with no timestamp.",
                # Missing pubDate
            }
        },
        {
            "id": "4",
            "content": {
                "id": "4",
                "contentType": "STORY",
                "title": "On the Dot Update",
                "summary": "Exactly 24 hours ago.",
                "pubDate": get_iso_str(current_time - 86400),  # Exactly 24 hours ago
            }
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
    from app.tools.ticker_universe import get_active_tickers
    expected_tickers = get_active_tickers()
    assert set(results.keys()) == set(expected_tickers)

    for ticker in expected_tickers:
        assert isinstance(results[ticker], list)
        assert len(results[ticker]) == 2


@patch("app.tools.data_ingestion.yf.Ticker")
def test_fetch_ticker_news_caps_articles_and_keeps_newest(mock_ticker_class):
    current_time = 1700000000.0
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.news = [
        {
            "content": {
                "title": f"Article {offset}",
                "summary": f"Summary {offset}",
                "pubDate": datetime.fromtimestamp(
                    current_time - offset, tz=timezone.utc
                ).isoformat(),
            }
        }
        for offset in (500, 100, 400, 200, 300)
    ]
    mock_ticker_class.return_value = mock_ticker_instance

    results = fetch_ticker_news("NVDA", current_time=current_time)

    assert len(results) == MAX_NEWS_ARTICLES_PER_TICKER
    assert [item["title"] for item in results] == [
        "Article 100",
        "Article 200",
        "Article 300",
    ]


def test_bounded_payload_enforces_per_ticker_and_whole_run_caps():
    market_data = {
        f"TICKER{ticker_index}": {
            "news": [
                {"title": f"{ticker_index}-{article_index}", "summary": "news"}
                for article_index in range(10)
            ]
        }
        for ticker_index in range(20)
    }

    payload = build_bounded_news_payload(market_data)

    assert sum(len(news) for news in payload.values()) == MAX_SENTIMENT_ARTICLES_PER_RUN
    assert all(len(news) <= MAX_NEWS_ARTICLES_PER_TICKER for news in payload.values())
    # Round-robin admission gives every ticker at least one article before any
    # ticker receives a second, avoiding first-ticker dominance.
    assert all(len(news) >= 1 for news in payload.values())
