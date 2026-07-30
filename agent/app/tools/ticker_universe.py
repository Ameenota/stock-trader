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
from collections import Counter
from typing import Iterable, List
import yfinance as yf

# ==============================================================================
# DESIGN REASONING FOR THE UNIVERSE AND ACTIVE WATCHLIST:
#
# 1. TICKER_UNIVERSE (Versioned multi-sector research/trading universe):
#    - Purpose: Enforces security boundaries. This acts as a strict security "allow list"
#      that the agent is authorized to trade on Robinhood. If the agent attempts to trade
#      any ticker outside of this list, the double guardrail interceptor will block it.
#    - Target: A curated set of liquid large-cap companies across every major equity
#      sector. The catalog remains checked in and reviewed so a third-party constituent
#      change cannot silently broaden the broker allowlist.
#
# 2. ACTIVE_TICKERS (Default 11-Stock Watch List):
#    - Purpose: Minimizes API token usage and optimizes execution performance.
#      Instead of fetching news and running expensive LLM sentiment analysis on the
#      entire universe, the deterministic screener promotes at most 11 tickers (unless
#      more held positions require safety analysis). Expanding the research universe
#      therefore does not expand the normal sentiment-analysis watchlist.
# ==============================================================================

# This metadata is intentionally static and versioned. It is not fetched from a mutable
# index-membership webpage during a trading run.
UNIVERSE_VERSION = "multi-sector-large-cap-v1"
MAX_ACTIVE_WATCHLIST_SIZE = 11
MAX_CANDIDATES_PER_SECTOR = 2
MAX_CONCURRENT_PRICE_FETCHES = 12

TICKER_SECTORS = {
    # Information Technology
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "NVDA": "Information Technology", "AVGO": "Information Technology",
    "ORCL": "Information Technology", "CRM": "Information Technology",
    "AMD": "Information Technology", "ADBE": "Information Technology",
    "CSCO": "Information Technology", "ACN": "Information Technology",
    "IBM": "Information Technology", "NOW": "Information Technology",
    "INTU": "Information Technology", "QCOM": "Information Technology",
    "TXN": "Information Technology", "AMAT": "Information Technology",
    "ADI": "Information Technology", "MU": "Information Technology",
    "LRCX": "Information Technology", "KLAC": "Information Technology",
    "ANET": "Information Technology", "PANW": "Information Technology",
    "CRWD": "Information Technology", "SNPS": "Information Technology",
    "CDNS": "Information Technology", "MCHP": "Information Technology",
    "NXPI": "Information Technology", "INTC": "Information Technology",
    "DELL": "Information Technology", "HPE": "Information Technology",
    "PLTR": "Information Technology", "NET": "Information Technology",
    "DDOG": "Information Technology", "SNOW": "Information Technology",
    "SMCI": "Information Technology", "MRVL": "Information Technology",
    "SNDK": "Information Technology", "ARM": "Information Technology",
    "TSM": "Information Technology", "ASML": "Information Technology",
    "SAP": "Information Technology",
    # Communication Services
    "GOOGL": "Communication Services", "META": "Communication Services",
    "NFLX": "Communication Services", "DIS": "Communication Services",
    "TMUS": "Communication Services", "VZ": "Communication Services",
    "T": "Communication Services", "EA": "Communication Services",
    "TTWO": "Communication Services", "OMC": "Communication Services",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "LOW": "Consumer Discretionary", "BKNG": "Consumer Discretionary",
    "TJX": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "MAR": "Consumer Discretionary",
    "GM": "Consumer Discretionary", "F": "Consumer Discretionary",
    # Consumer Staples
    "WMT": "Consumer Staples", "COST": "Consumer Staples",
    "PG": "Consumer Staples", "KO": "Consumer Staples",
    "PEP": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "CL": "Consumer Staples",
    "MDLZ": "Consumer Staples", "KMB": "Consumer Staples",
    "GIS": "Consumer Staples", "KR": "Consumer Staples",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy", "MPC": "Energy",
    "PSX": "Energy", "OXY": "Energy", "KMI": "Energy",
    "WMB": "Energy", "VLO": "Energy", "HAL": "Energy",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "C": "Financials",
    "SCHW": "Financials", "AXP": "Financials", "BLK": "Financials",
    "SPGI": "Financials", "CME": "Financials", "ICE": "Financials",
    "CB": "Financials", "PGR": "Financials",
    # Health Care
    "LLY": "Health Care", "UNH": "Health Care", "JNJ": "Health Care",
    "ABBV": "Health Care", "MRK": "Health Care", "TMO": "Health Care",
    "ABT": "Health Care", "AMGN": "Health Care", "GILD": "Health Care",
    "ISRG": "Health Care", "MDT": "Health Care", "BMY": "Health Care",
    "CVS": "Health Care", "CI": "Health Care",
    # Industrials
    "GE": "Industrials", "CAT": "Industrials", "RTX": "Industrials",
    "UNP": "Industrials", "HON": "Industrials", "UPS": "Industrials",
    "BA": "Industrials", "DE": "Industrials", "LMT": "Industrials",
    "ETN": "Industrials", "WM": "Industrials", "NOC": "Industrials",
    "CSX": "Industrials", "VRT": "Industrials", "RKLB": "Industrials",
    # Materials
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials",
    "ECL": "Materials", "NEM": "Materials", "FCX": "Materials",
    "NUE": "Materials", "DOW": "Materials", "DD": "Materials",
    "MLM": "Materials", "VMC": "Materials",
    # Real Estate
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "WELL": "Real Estate", "SPG": "Real Estate", "O": "Real Estate",
    "CCI": "Real Estate", "PSA": "Real Estate", "DLR": "Real Estate",
    "CBRE": "Real Estate", "VICI": "Real Estate",
    # Utilities
    "NEE": "Utilities", "SO": "Utilities", "DUK": "Utilities",
    "CEG": "Utilities", "AEP": "Utilities", "SRE": "Utilities",
    "EXC": "Utilities", "XEL": "Utilities", "ED": "Utilities",
    "PCG": "Utilities", "PEG": "Utilities", "VST": "Utilities",
    # Diversified market and defensive fixed-income fallbacks
    "SPY": "Broad Market ETF", "TLT": "Fixed Income ETF",
}

TICKER_UNIVERSE = list(TICKER_SECTORS)

# Fallbacks are used only when too few candidates pass the cheap screen. The
# normal path remains sector-balanced and capped at MAX_ACTIVE_WATCHLIST_SIZE.
ACTIVE_TICKERS = [
    "SPY", "TLT", "JPM", "LLY", "XOM", "WMT", "GE", "NEE", "LIN", "AMT", "AAPL"
]

def get_allowed_tickers() -> List[str]:
    """Return the versioned universe used by deterministic broker guardrails."""
    return TICKER_UNIVERSE

def get_active_tickers() -> List[str]:
    """Return the capped, multi-sector fallback watchlist."""
    return ACTIVE_TICKERS


def get_ticker_sector(ticker: str) -> str:
    """Return checked-in sector metadata for an authorized ticker."""
    return TICKER_SECTORS[str(ticker).strip().upper()]


async def determine_active_watchlist(
    dataset_id: str = "portfolio_analytics",
    return_details: bool = False,
    required_tickers: Iterable[str] | None = None,
) -> List[str] | tuple:
    """Dynamically screen the universe, always retaining required held tickers.

    Logic:
    1. Force-include required account holdings and the default real-account holdings.
    2. Filter out non-owned stocks that are trading below their 50-day Simple Moving Average (SMA).
    3. Score the remaining stocks by momentum (current_price / 50-day SMA).
    4. Admit at most two non-held candidates per sector so the small sentiment
       watchlist is not consumed by one correlated industry.
    5. Pad with the multi-sector ACTIVE_TICKERS fallback if fewer than 11 pass.
       If more than 11 unique holdings are required, retain every holding and expand the list.
    """
    from app.tools.bigquery_service import get_latest_portfolio_holdings, get_recently_sold_tickers

    # 1. Retrieve owned tickers from latest BQ portfolio snapshot
    try:
        owned_tickers = get_latest_portfolio_holdings(dataset_id=dataset_id)
        # Normalize/clean symbols
        owned_tickers = [t.strip().upper() for t in owned_tickers if t]
    except Exception:
        owned_tickers = []

    required = [
        str(ticker).strip().upper()
        for ticker in (required_tickers or [])
        if ticker and str(ticker).strip()
    ]

    # Preserve order while combining account-scoped holdings with the legacy default
    # real-account lookup. Every held ticker must remain in the analysis path.
    owned_tickers = list(dict.fromkeys(required + owned_tickers))
    owned_tickers = [t for t in owned_tickers if t in TICKER_UNIVERSE]
    watchlist_limit = max(MAX_ACTIVE_WATCHLIST_SIZE, len(owned_tickers))

    # 2. Retrieve recently sold tickers from BQ trade history to prevent immediate repurchase (cooling-down)
    try:
        recently_sold = get_recently_sold_tickers(days=21, dataset_id=dataset_id)
        recently_sold = [t.strip().upper() for t in recently_sold if t]
    except Exception:
        recently_sold = []

    # 3. Determine candidate tickers (not currently owned and not recently sold)
    candidates = [t for t in TICKER_UNIVERSE if t not in owned_tickers and t not in recently_sold]

    # Helper function to fetch history and compute SMA in a thread pool
    fetch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PRICE_FETCHES)

    async def fetch_sma_and_momentum(ticker: str):
        try:
            def get_history():
                stock = yf.Ticker(ticker)
                # Fetch 3 months of history to ensure we have at least 50 trading days
                return stock.history(period="3mo")

            async with fetch_semaphore:
                df = await asyncio.to_thread(get_history)
            if df is not None and not df.empty and "Close" in df.columns:
                close_prices = df["Close"]
                if len(close_prices) >= 50:
                    sma_50 = float(close_prices.tail(50).mean())
                    current_price = float(close_prices.iloc[-1])
                    
                    # Compute RSI using pandas_ta
                    import pandas as pd
                    import pandas_ta as ta
                    rsi_val = None
                    try:
                        rsi_series = df.ta.rsi(close="Close", length=14)
                        if rsi_series is not None and not rsi_series.empty:
                            rsi_val = float(rsi_series.iloc[-1])
                    except Exception:
                        pass
                        
                    return {
                        "ticker": ticker,
                        "current_price": current_price,
                        "sma_50": sma_50,
                        "rsi": rsi_val,
                        "momentum": current_price / sma_50
                    }
        except Exception:
            pass
        return None

    # 3. Fetch price history for all candidates concurrently
    tasks = [fetch_sma_and_momentum(t) for t in candidates]
    results = await asyncio.gather(*tasks)

    # 4. Filter and score candidate stocks (must be trading above 50-day SMA OR deeply oversold)
    valid_candidates = []
    for r in results:
        if r is not None:
            is_oversold = r["rsi"] is not None and r["rsi"] < 25
            if r["current_price"] > r["sma_50"] or is_oversold:
                valid_candidates.append(r)

    # 5. Sort valid candidates by momentum descending (highest score first)
    valid_candidates.sort(key=lambda x: x["momentum"], reverse=True)
    sector_counts = Counter(TICKER_SECTORS[ticker] for ticker in owned_tickers)
    top_candidate_tickers = []
    for candidate in valid_candidates:
        ticker = candidate["ticker"]
        sector = TICKER_SECTORS[ticker]
        if sector_counts[sector] >= MAX_CANDIDATES_PER_SECTOR:
            continue
        top_candidate_tickers.append(ticker)
        sector_counts[sector] += 1

    # 6. Combine owned tickers + top candidates to build the watchlist
    watchlist_set = set()
    final_watchlist = []

    for t in owned_tickers + top_candidate_tickers:
        if t not in watchlist_set and len(final_watchlist) < watchlist_limit:
            watchlist_set.add(t)
            final_watchlist.append(t)

    # 7. Pad with the static core watch list (ACTIVE_TICKERS) if we have fewer than 11 stocks
    fallback_sector_counts = Counter(TICKER_SECTORS[ticker] for ticker in final_watchlist)
    for t in ACTIVE_TICKERS:
        sector = TICKER_SECTORS[t]
        if (
            t not in recently_sold
            and t not in watchlist_set
            and fallback_sector_counts[sector] < MAX_CANDIDATES_PER_SECTOR
            and len(final_watchlist) < watchlist_limit
        ):
            watchlist_set.add(t)
            final_watchlist.append(t)
            fallback_sector_counts[sector] += 1

    # 8. Build detailed pre-screener status log if requested
    if return_details:
        all_details = {}
        results_lookup = {r["ticker"]: r for r in results if r is not None}
        final_watchlist_set = set(final_watchlist)
        
        for t in TICKER_UNIVERSE:
            detail = {
                "ticker": t,
                "current_price": None,
                "sma_50": None,
                "momentum": None,
            }
            if t in results_lookup:
                detail["current_price"] = results_lookup[t]["current_price"]
                detail["sma_50"] = results_lookup[t]["sma_50"]
                detail["momentum"] = results_lookup[t]["momentum"]
                
            if t in final_watchlist_set:
                detail["status"] = "SELECTED"
                if t in owned_tickers:
                    detail["reason"] = "Owned position promotion"
                elif t in top_candidate_tickers:
                    detail["reason"] = "Top momentum rank"
                else:
                    detail["reason"] = "Watchlist padding fallback"
            else:
                detail["status"] = "FILTERED"
                if t in recently_sold:
                    detail["reason"] = "Recently sold (21-day cool-down)"
                elif t in owned_tickers:
                    detail["reason"] = "Owned but excluded"
                elif t in results_lookup:
                    r = results_lookup[t]
                    if r["current_price"] <= r["sma_50"]:
                        detail["reason"] = "Below 50-day SMA"
                    else:
                        detail["reason"] = "Low momentum rank"
                else:
                    detail["reason"] = "Data unavailable (yfinance)"
            all_details[t] = detail
            
        return final_watchlist, all_details

    return final_watchlist
