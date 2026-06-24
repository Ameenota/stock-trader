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
import os
import sys
from datetime import datetime, timezone

# Add current directory to python path to allow importing app module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def load_env_file() -> None:
    """Resiliently loads variables from local .env into os.environ."""
    # Search in current directory and parent directory
    for base_dir in [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")]:
        env_path = os.path.join(base_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip()
            break

# Load environment configuration on load
load_env_file()

# Ensure MCP servers and OAuth auth flows are bypassed since we are running 
# in batch mode for news sentiment analysis.
os.environ["INTEGRATION_TEST"] = "TRUE"

from app.tools.data_ingestion import ingest_market_data
from app.tools.ranking import process_sentiment_rankings
from app.tools.bigquery_service import (
    setup_bigquery, 
    insert_sentiment,
    get_historical_metrics,
    get_latest_market_metrics,
    insert_trade_record
)
from app.agent import sentiment_agent, trading_agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

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

async def run_pipeline(dataset_id: str = "portfolio_analytics") -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting AI Infrastructure Analyst pipeline...")

    # Step 1: Initialize BigQuery Dataset and Tables
    print(f"\n1. Setting up BigQuery dataset '{dataset_id}' and tables...")
    setup_bigquery(dataset_id=dataset_id)
    print("   Dataset and tables verified/created successfully.")

    # Determine if we skip ingestion (from env or if BQ today has records)
    skip_ingestion = os.environ.get("SKIP_INGESTION", "false").lower() == "true"
    
    ranked_portfolio = []
    
    if skip_ingestion:
        print("\n[SKIP_INGESTION] Checking BigQuery for today's market metrics...")
        today_metrics = get_latest_market_metrics(dataset_id=dataset_id)
        if today_metrics:
            print(f"   Bypassing ingestion. Found {len(today_metrics)} existing metrics for today.")
            ranked_portfolio = today_metrics
        else:
            print("   Warning: SKIP_INGESTION was true but no daily metrics found in BigQuery. Running ingestion...")
            skip_ingestion = False

    if not skip_ingestion:
        # Step 2: Ingest Latest Market News and Metrics
        print("\n2. Ingesting latest 24h market news and metrics from yfinance...")
        market_data = ingest_market_data()
        print(f"   Successfully fetched market data for {len(market_data)} tickers.")

        # Step 3: Run structured sentiment agent (Part 1 - LLM call)
        print("\n3. Triggering Gemini 1.5 Flash sentiment analysis...")
        session_service = InMemorySessionService()
        session = await session_service.create_session(user_id="cron_job", app_name="sentiment")
        runner = Runner(agent=sentiment_agent, session_service=session_service, app_name="sentiment")

        # Extract only news list for the LLM agent
        news_dict = {ticker: data.get("news", []) for ticker, data in market_data.items()}

        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Analyze these news articles:\n{news_dict}")]
        )

        # Execute agent run
        async for _ in runner.run_async(
            new_message=message,
            user_id="cron_job",
            session_id=session.id,
        ):
            pass

        # Retrieve updated session containing Pydantic output schema
        session = await session_service.get_session(user_id="cron_job", session_id=session.id, app_name="sentiment")
        sentiment_result = session.state.get("sentiment_result")
        if not sentiment_result:
            raise RuntimeError("Failed to retrieve sentiment analysis output from the LLM agent.")
        
        print("   Structured sentiment scores generated by Gemini.")

        # Step 4: Run deterministic Python ranking logic (Part 2)
        print("\n4. Running deterministic ranking and signal assignment...")
        ranked_portfolio = process_sentiment_rankings(sentiment_result)

        # Attach raw news stories and technical metrics to each portfolio item for BigQuery auditing
        for item in ranked_portfolio:
            ticker = item["ticker"]
            ticker_data = market_data.get(ticker, {})
            item["raw_news"] = ticker_data.get("news", [])
            item["analyst_consensus"] = ticker_data.get("analyst_consensus")
            item["target_price"] = ticker_data.get("target_price")
            item["current_price"] = ticker_data.get("current_price")
            item["moving_average_20d"] = ticker_data.get("moving_average_20d")
            item["price_to_ma_ratio"] = ticker_data.get("price_to_ma_ratio")

        # Step 5: Log decisions into Google Cloud BigQuery
        print(f"\n5. Logging analysis results to BigQuery dataset '{dataset_id}'...")
        insert_sentiment(ranked_portfolio, dataset_id=dataset_id)
        print("   Decisions written to 'infrastructure_market_metrics' table.")

    # Step 6: Print daily metrics table
    print_portfolio_table(ranked_portfolio)

    # Step 7: Run trading agent for portfolio execution and rebalancing
    print("\n7. Fetching historical signals and executing trading agent...")
    weekly_metrics = get_historical_metrics(days=7, dataset_id=dataset_id)
    
    # Enable trading agent session connections
    # We clear INTEGRATION_TEST to allow the McpToolset standard stdio parameters to boot the connection
    if "INTEGRATION_TEST" in os.environ:
        del os.environ["INTEGRATION_TEST"]

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="cron_job", app_name="trading")
    runner = Runner(agent=trading_agent, session_service=session_service, app_name="trading")

    prompt_text = f"""Please perform today's trading execution and portfolio rebalancing.
Here is the historical metrics log for all 10 assets over the past week:
{weekly_metrics}"""

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)]
    )

    # Execute and stream reasoning to the terminal
    print("\n=== Trading Agent Execution & Reasoning Stream ===")
    async for event in runner.run_async(
        new_message=message,
        user_id="cron_job",
        session_id=session.id,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
    print("\n==================================================\n")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
