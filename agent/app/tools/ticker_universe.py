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

import asyncio
from typing import List
import yfinance as yf

# ==============================================================================
# DESIGN REASONING FOR THE TWO TICKER LISTS:
#
# 1. TICKER_UNIVERSE (Allowed 40-Stock Universe):
#    - Purpose: Enforces security boundaries. This acts as a strict security "allow list"
#      that the agent is authorized to trade on Robinhood. If the agent attempts to trade
#      any ticker outside of this list, the double guardrail interceptor will block it.
#    - Target: High-quality, large-cap, liquid stocks inside the AI and power grid sector.
#
# 2. ACTIVE_TICKERS (Default 10-Stock Watch List):
#    - Purpose: Minimizes API token usage and optimizes execution performance.
#      Instead of fetching news and running expensive LLM sentiment analysis on all 40
#      stocks every single day, we default to running sentiment analysis only on a active watch list
#      of 10 stocks.
#    - Link between the two: The Dynamic Asset Screener (determine_active_watchlist) scans the
#      40-stock TICKER_UNIVERSE using cheap/free price calculations and promotes the top 10
#      performing tickers to become the active watch list for today's run.
# ==============================================================================

# Centralized allowed universe of 40 AI sector and grid infrastructure stocks
TICKER_UNIVERSE = [
    # 1. Original 10 Core Assets (AI core/infrastructure + hedge ETF fallback)
    "NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT",
    # 2. Big Tech Cloud & LLM Providers
    "MSFT", "GOOGL", "AMZN", "META", "ORCL",
    # 3. Custom ASICs, Networking & Design Tools
    "AVGO", "ANET", "ARM", "SNPS", "CDNS",
    # 4. Semiconductor Manufacturing Equipment
    "ASML", "AMAT", "LRCX", "KLAC", "INTC",
    # 5. Datacenter Utilities & Infrastructure
    "VST", "GE", "PSTG", "HPE",
    # 6. AI Software & Integration Services
    "PLTR", "IBM", "NOW", "ADBE", "SAP",
    # 7. Edge Inference & Monitoring
    "NET", "DDOG", "ANSS",
    # 8. AI-driven Security & Edge Devices
    "CRWD", "PANW", "QCOM"
]

# Currently active subset for daily ingestion and sentiment analysis to optimize token usage
ACTIVE_TICKERS = [
    "NVDA", "AMD", "TSM", "MU", "SMCI", "DELL", "VRT", "ETN", "CEG", "TLT"
]

def get_allowed_tickers() -> List[str]:
    """Returns the centralized list of 40 allowed ticker symbols for trading security guardrails."""
    return TICKER_UNIVERSE

def get_active_tickers() -> List[str]:
    """Returns the static subset of 10 ticker symbols currently active in the daily analysis pipeline."""
    return ACTIVE_TICKERS


async def determine_active_watchlist(dataset_id: str = "portfolio_analytics") -> List[str]:
    """Dynamically screens the 40-stock TICKER_UNIVERSE to build a refined 10-stock active watchlist.

    Logic:
    1. Force-include any stock that we currently hold positions in (queried from BigQuery).
    2. Filter out non-owned stocks that are trading below their 50-day Simple Moving Average (SMA).
    3. Score the remaining stocks by momentum (current_price / 50-day SMA) and take the top performers.
    4. Pad the watchlist with the original ACTIVE_TICKERS list if it contains fewer than 10 stocks.
    """
    from app.tools.bigquery_service import get_latest_portfolio_holdings

    # 1. Retrieve owned tickers from latest BQ portfolio snapshot
    try:
        owned_tickers = get_latest_portfolio_holdings(dataset_id=dataset_id)
        # Normalize/clean symbols
        owned_tickers = [t.strip().upper() for t in owned_tickers if t]
    except Exception:
        owned_tickers = []

    # Filter owned tickers to make sure they are within our allowed universe
    owned_tickers = [t for t in owned_tickers if t in TICKER_UNIVERSE]

    # 2. Determine candidate tickers (not currently owned)
    candidates = [t for t in TICKER_UNIVERSE if t not in owned_tickers]

    # Helper function to fetch history and compute SMA in a thread pool
    async def fetch_sma_and_momentum(ticker: str):
        try:
            def get_history():
                stock = yf.Ticker(ticker)
                # Fetch 3 months of history to ensure we have at least 50 trading days
                return stock.history(period="3mo")

            df = await asyncio.to_thread(get_history)
            if df is not None and not df.empty and "Close" in df.columns:
                close_prices = df["Close"]
                if len(close_prices) >= 50:
                    sma_50 = float(close_prices.tail(50).mean())
                    current_price = float(close_prices.iloc[-1])
                    return {
                        "ticker": ticker,
                        "current_price": current_price,
                        "sma_50": sma_50,
                        "momentum": current_price / sma_50
                    }
        except Exception:
            pass
        return None

    # 3. Fetch price history for all candidates concurrently
    tasks = [fetch_sma_and_momentum(t) for t in candidates]
    results = await asyncio.gather(*tasks)

    # 4. Filter and score candidate stocks (must be trading above 50-day SMA)
    valid_candidates = []
    for r in results:
        if r is not None and r["current_price"] > r["sma_50"]:
            valid_candidates.append(r)

    # 5. Sort valid candidates by momentum descending (highest score first)
    valid_candidates.sort(key=lambda x: x["momentum"], reverse=True)
    top_candidate_tickers = [c["ticker"] for c in valid_candidates]

    # 6. Combine owned tickers + top candidates to build the watchlist
    watchlist_set = set()
    final_watchlist = []

    for t in owned_tickers + top_candidate_tickers:
        if t not in watchlist_set and len(final_watchlist) < 10:
            watchlist_set.add(t)
            final_watchlist.append(t)

    # 7. Pad with the static core watch list (ACTIVE_TICKERS) if we have fewer than 10 stocks
    for t in ACTIVE_TICKERS:
        if t not in watchlist_set and len(final_watchlist) < 10:
            watchlist_set.add(t)
            final_watchlist.append(t)

    return final_watchlist
