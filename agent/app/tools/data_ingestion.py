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


def fetch_ticker_market_data(ticker: str, current_time: float | None = None) -> Dict[str, Any]:
    """Fetches news, analyst recommendations, target mean price, current price, and 20-day SMA.

    Args:
        ticker: The stock ticker symbol.
        current_time: Reference unix timestamp for news filtering.

    Returns:
        A dictionary containing:
            - 'news': List of 24h news dicts.
            - 'analyst_consensus': str or None
            - 'target_price': float or None
            - 'current_price': float or None
            - 'moving_average_20d': float or None
            - 'price_to_ma_ratio': float or None
    """
    if current_time is None:
        current_time = time.time()

    data = {
        "news": [],
        "analyst_consensus": None,
        "target_price": None,
        "current_price": None,
        "moving_average_20d": None,
        "price_to_ma_ratio": None
    }

    try:
        stock = yf.Ticker(ticker)
    except Exception:
        return data

    # 1. Fetch News
    try:
        news_list = stock.news
        if news_list:
            filtered_news = []
            for item in news_list:
                content = item.get("content", {})
                pub_date_str = content.get("pubDate")
                if not pub_date_str:
                    continue

                try:
                    pub_date_str = pub_date_str.replace("Z", "+00:00")
                    publish_time = datetime.fromisoformat(pub_date_str).timestamp()
                except Exception:
                    continue

                if current_time - publish_time <= 86400:
                    title = content.get("title", "")
                    summary = content.get("summary", "")
                    filtered_news.append({
                        "title": title,
                        "summary": summary
                    })
            data["news"] = filtered_news
    except Exception:
        pass

    # 2. Fetch Analyst Info
    try:
        info = stock.info
        if info:
            data["analyst_consensus"] = info.get("recommendationKey")
            target = info.get("targetMeanPrice")
            if target is not None:
                data["target_price"] = float(target)
    except Exception:
        pass

    # 3. Fetch History for Momentum
    try:
        # Use 2mo to ensure we have at least 20 trading days
        history = stock.history(period="2mo")
        if history is not None and not history.empty and "Close" in history.columns:
            close_prices = history["Close"]
            if len(close_prices) > 0:
                data["current_price"] = float(close_prices.iloc[-1])
                # Compute 20-day simple moving average
                ma_20_series = close_prices.tail(20)
                data["moving_average_20d"] = float(ma_20_series.mean())
                if data["moving_average_20d"] and data["moving_average_20d"] > 0:
                    data["price_to_ma_ratio"] = data["current_price"] / data["moving_average_20d"]
    except Exception:
        pass

    # Fallback for current_price from info if history failed
    if data["current_price"] is None:
        try:
            info = stock.info
            if info:
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                if price is not None:
                    data["current_price"] = float(price)
        except Exception:
            pass

    return data


def ingest_market_data(current_time: float | None = None) -> Dict[str, Dict[str, Any]]:
    """Ingests latest market data (news + metrics) for the 10 predefined assets.

    Args:
        current_time: Reference unix timestamp. Defaults to time.time().

    Returns:
        A dictionary mapping tickers to their market data dictionary.
    """
    if current_time is None:
        current_time = time.time()

    results = {}
    for ticker in TICKERS:
        results[ticker] = fetch_ticker_market_data(ticker, current_time=current_time)
    return results


def print_portfolio_table(portfolio: list) -> None:
    """Renders a beautiful ASCII table of the ranked portfolio and trade signals."""
    print("\n" + "="*145)
    print(f"{'Ticker':<6} | {'Score':<6} | {'Rank':<5} | {'Signal':<11} | {'Price':<8} | {'20d SMA':<8} | {'Price/MA':<8} | {'Consensus':<10} | {'Thesis'}")
    print("="*145)
    for item in portfolio:
        thesis = item.get("thesis", "")
        # Truncate thesis if it's too long for a clean terminal output
        truncated_thesis = thesis[:60] + "..." if len(thesis) > 60 else thesis
        price = item.get("current_price")
        price_str = f"${price:.2f}" if price is not None else "N/A"
        ma = item.get("moving_average_20d")
        ma_str = f"${ma:.2f}" if ma is not None else "N/A"
        ratio = item.get("price_to_ma_ratio")
        ratio_str = f"{ratio:.3f}" if ratio is not None else "N/A"
        consensus = item.get("analyst_consensus") or "N/A"
        
        print(f"{item['ticker']:<6} | {item['raw_score']:<6.2f} | {item['relative_rank']:<5} | {item['signal']:<11} | {price_str:<8} | {ma_str:<8} | {ratio_str:<8} | {consensus:<10} | {truncated_thesis}")
    print("="*145 + "\n")
