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
from typing import Dict, List, Any
import yfinance as yf

# Predefined list of 9 AI infrastructure stocks + 1 market hedge ETF
TICKERS = ["NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT"]


from datetime import datetime

def fetch_ticker_news(ticker: str, current_time: float | None = None) -> List[Dict[str, str]]:
    """Fetches news for a specific ticker and filters for the last 24 hours.

    Args:
        ticker: The stock ticker symbol.
        current_time: Reference unix timestamp. Defaults to time.time().

    Returns:
        A list of dictionaries containing 'title' and 'summary' of the news.
    """
    if current_time is None:
        current_time = time.time()

    try:
        stock = yf.Ticker(ticker)
        news_list = stock.news
    except Exception:
        return []

    if not news_list:
        return []

    filtered_news = []
    for item in news_list:
        content = item.get("content", {})
        pub_date_str = content.get("pubDate")
        if not pub_date_str:
            continue

        try:
            # Parse ISO 8601 string to timestamp
            # Replace 'Z' with UTC offset '+00:00' to support python ISO format parser compatibility
            pub_date_str = pub_date_str.replace("Z", "+00:00")
            publish_time = datetime.fromisoformat(pub_date_str).timestamp()
        except Exception:
            continue

        # 86400 seconds = 24 hours
        if current_time - publish_time <= 86400:
            title = content.get("title", "")
            summary = content.get("summary", "")
            filtered_news.append({
                "title": title,
                "summary": summary
            })

    return filtered_news


def ingest_market_news(current_time: float | None = None) -> Dict[str, List[Dict[str, str]]]:
    """Ingests latest 24-hour news for the 10 predefined AI infrastructure and hedge assets.

    Args:
        current_time: Reference unix timestamp. Defaults to time.time().

    Returns:
        A dictionary mapping tickers to their list of filtered news items.
    """
    if current_time is None:
        current_time = time.time()

    results = {}
    for ticker in TICKERS:
        results[ticker] = fetch_ticker_news(ticker, current_time=current_time)
    return results
