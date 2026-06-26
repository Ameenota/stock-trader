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
import pandas as pd
import pandas_ta as ta
import yfinance as yf

# Terminal colors for beautiful outputs
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_MAGENTA = "\033[95m"
CLR_CYAN = "\033[96m"

from app.tools.ticker_universe import get_active_tickers

# Predefined list of 9 AI infrastructure stocks + 1 market hedge ETF
TICKERS = get_active_tickers()


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


def ingest_market_news(tickers: List[str] | None = None, current_time: float | None = None) -> Dict[str, List[Dict[str, str]]]:
    """Ingests latest 24-hour news for a list of assets (defaults to active tickers).

    Args:
        tickers: Optional list of tickers. Defaults to active tickers.
        current_time: Reference unix timestamp. Defaults to time.time().

    Returns:
        A dictionary mapping tickers to their list of filtered news items.
    """
    if current_time is None:
        current_time = time.time()

    target_tickers = tickers if tickers is not None else TICKERS
    results = {}
    for ticker in target_tickers:
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
        "price_to_ma_ratio": None,
        "rsi": None,
        "macd": None,
        "macd_signal": None
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

    # 3. Fetch History for Momentum & Technical Indicators
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
                
                # Compute Technical Indicators (RSI & MACD) using pandas-ta
                try:
                    rsi_series = history.ta.rsi(close="Close", length=14)
                    if rsi_series is not None and not rsi_series.empty:
                        last_rsi = rsi_series.iloc[-1]
                        data["rsi"] = float(last_rsi) if pd.notnull(last_rsi) else None
                except Exception:
                    pass
                
                try:
                    macd_df = history.ta.macd(close="Close", fast=12, slow=26, signal=9)
                    if macd_df is not None and not macd_df.empty:
                        # pandas-ta columns for MACD default parameters: MACD_12_26_9, MACDs_12_26_9
                        macd_val = macd_df.iloc[-1].get("MACD_12_26_9")
                        macd_sig_val = macd_df.iloc[-1].get("MACDs_12_26_9")
                        data["macd"] = float(macd_val) if pd.notnull(macd_val) else None
                        data["macd_signal"] = float(macd_sig_val) if pd.notnull(macd_sig_val) else None
                except Exception:
                    pass
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


def ingest_market_data(tickers: List[str] | None = None, current_time: float | None = None) -> Dict[str, Dict[str, Any]]:
    """Ingests latest market data (news + metrics) for a list of assets (defaults to active tickers).

    Args:
        tickers: Optional list of tickers. Defaults to active tickers.
        current_time: Reference unix timestamp. Defaults to time.time().

    Returns:
        A dictionary mapping tickers to their market data dictionary.
    """
    if current_time is None:
        current_time = time.time()

    target_tickers = tickers if tickers is not None else TICKERS
    results = {}
    for ticker in target_tickers:
        results[ticker] = fetch_ticker_market_data(ticker, current_time=current_time)
    return results


def print_portfolio_table(portfolio: list) -> None:
    """Renders a beautiful ASCII table of the ranked portfolio and trade signals."""
    print("\n" + "="*175)
    print(f"{CLR_BOLD}{CLR_BLUE}{'Ticker':<6} | {'Score':<6} | {'Rank':<5} | {'Signal':<11} | {'Price':<8} | {'20d SMA':<8} | {'Price/MA':<8} | {'RSI':<6} | {'MACD':<8} | {'MACD Sig':<8} | {'Consensus':<10} | {'Thesis'}{CLR_RESET}")
    print("="*175)
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
        rsi = item.get("rsi")
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        macd = item.get("macd")
        macd_str = f"{macd:.3f}" if macd is not None else "N/A"
        macd_sig = item.get("macd_signal")
        macd_sig_str = f"{macd_sig:.3f}" if macd_sig is not None else "N/A"
        consensus = item.get("analyst_consensus") or "N/A"
        
        signal = item.get("signal", "")
        signal_val = f"{signal:<11}"
        if "STRONG BUY" in signal:
            signal_display = f"{CLR_BOLD}{CLR_GREEN}{signal_val}{CLR_RESET}"
        elif "LIQUIDATE" in signal:
            signal_display = f"{CLR_BOLD}{CLR_RED}{signal_val}{CLR_RESET}"
        elif "HOLD" in signal:
            signal_display = f"{CLR_BOLD}{CLR_YELLOW}{signal_val}{CLR_RESET}"
        else:
            signal_display = signal_val
            
        score = item.get("raw_score", 0.0)
        score_val = f"{score:+.2f}"
        if score > 0:
            score_display = f"{CLR_GREEN}{score_val:<6}{CLR_RESET}"
        elif score < 0:
            score_display = f"{CLR_RED}{score_val:<6}{CLR_RESET}"
        else:
            score_display = f"{score_val:<6}"
            
        ticker_display = f"{CLR_BOLD}{item['ticker']:<6}{CLR_RESET}"
        
        print(f"{ticker_display} | {score_display} | {item['relative_rank']:<5} | {signal_display} | {price_str:<8} | {ma_str:<8} | {ratio_str:<8} | {rsi_str:<6} | {macd_str:<8} | {macd_sig_str:<8} | {consensus:<10} | {truncated_thesis}")
    print("="*175 + "\n")


async def run_sentiment_analysis_pipeline(dataset_id: str = "portfolio_analytics") -> tuple[list, list]:
    """Ingests market news/metrics, runs sentiment analysis agent, ranks assets,
    and logs decisions to BigQuery.
    """
    from datetime import datetime, timezone
    from google.adk.sessions import InMemorySessionService
    from google.adk.runners import Runner
    from google.genai import types
    from app.agent import sentiment_agent
    from app.tools.ranking import process_sentiment_rankings
    from app.tools.ticker_universe import determine_active_watchlist

    # 1. Dynamically determine the watchlist and get details for all universe assets
    print(f"\n{CLR_BOLD}{CLR_CYAN}📥 [PHASE: 2. Ingestion & Watchlist Screening]{CLR_RESET}")
    print("   Determining active watchlist from 40-asset universe...")
    active_tickers, all_tickers_details = await determine_active_watchlist(dataset_id=dataset_id, return_details=True)
    print(f"   Active watchlist generated: {active_tickers}")
    print(f"   Ingesting news & metrics from Yahoo Finance for watchlist tickers...")

    # 2. Ingest latest market news and metrics only for the active watchlist
    market_data = ingest_market_data(tickers=active_tickers)
    print(f"   {CLR_GREEN}Yahoo Finance ingestion complete for {len(market_data)} tickers.{CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_CYAN}📥 [PHASE: 2. Exit]{CLR_RESET}")

    # 3. Run sentiment agent sub-session
    print(f"\n{CLR_BOLD}{CLR_MAGENTA}🧠 [PHASE: 3. Sentiment Analysis via Gemini]{CLR_RESET}")
    print(f"   Invoking {CLR_BOLD}{CLR_MAGENTA}SENTIMENT_AGENT{CLR_RESET} (Gemini) to evaluate news sentiment...")
    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="cron_job", app_name="sentiment")
    runner = Runner(agent=sentiment_agent, session_service=session_service, app_name="sentiment")

    news_dict = {ticker: data.get("news", []) for ticker, data in market_data.items()}

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Analyze these news articles:\n{news_dict}")]
    )

    async for _ in runner.run_async(
        new_message=message,
        user_id="cron_job",
        session_id=session.id,
    ):
        pass

    session = await session_service.get_session(user_id="cron_job", session_id=session.id, app_name="sentiment")
    sentiment_result = session.state.get("sentiment_result")
    if not sentiment_result:
        raise RuntimeError("Failed to retrieve sentiment analysis output from the LLM agent.")

    from app.tools.ranking import SentimentAnalysisResponse
    # Print the specific outputs returned by the Sentiment Agent
    print(f"   🤖 {CLR_BOLD}{CLR_MAGENTA}SENTIMENT_AGENT{CLR_RESET}: Completed news sentiment analysis:")
    analyses_list = []
    if isinstance(sentiment_result, SentimentAnalysisResponse):
        analyses_list = sentiment_result.analyses
    elif isinstance(sentiment_result, dict) and "analyses" in sentiment_result:
        analyses_list = sentiment_result["analyses"]
    else:
        analyses_list = sentiment_result
        
    for item in analyses_list:
        ticker = getattr(item, "ticker") if not isinstance(item, dict) else item.get("ticker")
        score = getattr(item, "raw_score") if not isinstance(item, dict) else item.get("raw_score")
        score_val = float(score)
        if score_val > 0:
            score_str = f"{CLR_GREEN}{score_val:+.2f}{CLR_RESET}"
        elif score_val < 0:
            score_str = f"{CLR_RED}{score_val:+.2f}{CLR_RESET}"
        else:
            score_str = f"{score_val:+.2f}"
        print(f"      - {ticker}: conviction score = {score_str}")

    # 4. Sort, rank and assign signals
    ranked_portfolio = process_sentiment_rankings(sentiment_result)
    print(f"{CLR_BOLD}{CLR_MAGENTA}🧠 [PHASE: 3. Exit]{CLR_RESET}")

    # 4. Attach raw news and technical metrics for auditing
    current_time_str = datetime.now(timezone.utc).isoformat()
    for item in ranked_portfolio:
        ticker = item["ticker"]
        item["timestamp"] = current_time_str
        ticker_data = market_data.get(ticker, {})
        item["raw_news"] = ticker_data.get("news", [])
        item["analyst_consensus"] = ticker_data.get("analyst_consensus")
        item["target_price"] = ticker_data.get("target_price")
        item["current_price"] = ticker_data.get("current_price")
        item["moving_average_20d"] = ticker_data.get("moving_average_20d")
        item["price_to_ma_ratio"] = ticker_data.get("price_to_ma_ratio")
        item["rsi"] = ticker_data.get("rsi")
        item["macd"] = ticker_data.get("macd")
        item["macd_signal"] = ticker_data.get("macd_signal")

    # 5. Build placeholder rows for the filtered graveyard assets to prove LLM token savings
    graveyard_rows = []
    for ticker, detail in all_tickers_details.items():
        if detail.get("status") == "FILTERED":
            graveyard_rows.append({
                "ticker": ticker,
                "raw_score": 0.0,
                "thesis": f"Filtered: {detail.get('reason', 'Excluded by pre-screener')}",
                "relative_rank": 0,
                "signal": "FILTERED",
                "timestamp": current_time_str,
                "raw_news": "[]",
                "analyst_consensus": "N/A",
                "target_price": None,
                "current_price": detail.get("current_price"),
                "moving_average_20d": detail.get("sma_50"),
                "price_to_ma_ratio": detail.get("momentum"),
                "rsi": None,
                "macd": None,
                "macd_signal": None
            })

    # 6. Ingest and log SPY benchmark data
    try:
        spy_data = ingest_market_data(tickers=["SPY"])
        spy_price = spy_data.get("SPY", {}).get("current_price")
        if spy_price:
            print(f"   Successfully ingested SPY benchmark price: ${spy_price:.2f}")
            graveyard_rows.append({
                "ticker": "SPY",
                "raw_score": 0.0,
                "thesis": "S&P 500 Index Benchmark",
                "relative_rank": 0,
                "signal": "BENCHMARK",
                "timestamp": current_time_str,
                "raw_news": "[]",
                "analyst_consensus": "N/A",
                "target_price": None,
                "current_price": spy_price,
                "moving_average_20d": None,
                "price_to_ma_ratio": None,
                "rsi": None,
                "macd": None,
                "macd_signal": None
            })
    except Exception as e:
        print(f"   {CLR_YELLOW}Warning: Failed to ingest SPY: {e}{CLR_RESET}")

    # Return both ranked portfolio and graveyard rows to the orchestrator to log after execution
    return ranked_portfolio, graveyard_rows
