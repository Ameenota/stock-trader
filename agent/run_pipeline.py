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

from app.tools.bigquery_service import (
    setup_bigquery, 
    get_latest_market_metrics,
)
from app.tools.data_ingestion import print_portfolio_table
from app.agent import run_daily_analysis_pipeline, execute_trading_decisions

async def run_pipeline(dataset_id: str = "portfolio_analytics") -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting AI Infrastructure Analyst pipeline...")

    # Step 1: Initialize BigQuery Dataset and Tables
    print(f"\n1. Setting up BigQuery dataset '{dataset_id}' and tables...")
    setup_bigquery(dataset_id=dataset_id)
    print("   Dataset and tables verified/created successfully.")

    # Determine if we skip ingestion (from env or if BQ today has records)
    skip_ingestion = os.environ.get("SKIP_INGESTION", "false").lower() == "true"
    
    ranked_portfolio = []
    graveyard_rows = None
    
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
        # Run daily analysis pipeline helper from app.agent
        print("\nRunning daily analysis pipeline (ingestion, sentiment analysis, ranking)...")
        ranked_portfolio, graveyard_rows = await run_daily_analysis_pipeline(dataset_id=dataset_id)
        print("   Daily analysis pipeline finished (metrics gathered).")

    # Run trading agent for portfolio execution and rebalancing
    print("\nExecuting trading decisions...")
    final_portfolio = await execute_trading_decisions(
        ranked_portfolio=ranked_portfolio,
        graveyard_rows=graveyard_rows,
        dataset_id=dataset_id
    )
    print("   Portfolio execution completed and logged.")

    # Print final portfolio table (now with Trading Agent signals & theses!)
    print_portfolio_table(final_portfolio)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
