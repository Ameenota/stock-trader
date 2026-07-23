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
import argparse
import copy
import hashlib
import os
import sys
from datetime import datetime, timezone

# Terminal colors for beautiful outputs
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_MAGENTA = "\033[95m"
CLR_CYAN = "\033[96m"

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
                        key = key.strip()
                        if key not in os.environ:
                            os.environ[key] = val.strip()
            break

# Load environment configuration on load
load_env_file()

# Ensure MCP servers and OAuth auth flows are bypassed since we are running 
# in batch mode for news sentiment analysis.
os.environ["INTEGRATION_TEST"] = "TRUE"

from app.tools.bigquery_service import (
    backfill_account_scope,
    get_account,
    get_latest_account_activity,
    get_latest_account_snapshot,
    get_latest_market_metrics,
    get_latest_portfolio_holdings,
    list_accounts,
    seed_account_registry,
    setup_bigquery,
)
from app.accounts import AccountRunContext, RunKind, preflight_accounts
from app.tools.data_ingestion import print_portfolio_table, run_sentiment_analysis_pipeline
from app.agent import financial_analysis_pipeline

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run account-scoped trading pipeline")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--account", help="Stable account ID from BigQuery")
    selectors.add_argument("--all-accounts", action="store_true", help="Run every active account")
    parser.add_argument("--list-accounts", action="store_true", help="List registry rows and exit")
    parser.add_argument(
        "--run-kind", choices=("advisory", "execution"), default="execution"
    )
    parser.add_argument("--dataset-id", default="portfolio_analytics")
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.list_accounts:
        if args.account or args.all_accounts:
            parser.error("--list-accounts cannot be combined with an account selector")
        return
    if not args.account and not args.all_accounts:
        parser.error("one of --account or --all-accounts is required")


def _market_batch_id(rows: list[dict]) -> str:
    material = "|".join(
        sorted(
            f"{row.get('ticker')}:{row.get('timestamp')}:{row.get('current_price')}"
            for row in rows
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _required_account_tickers(accounts: list, dataset_id: str) -> list[str]:
    """Return every held ticker that must survive the shared pre-screen."""
    required = {
        ticker.strip().upper()
        for account in accounts
        for ticker in get_latest_portfolio_holdings(
            dataset_id=dataset_id,
            account_id=account.account_id,
        )
        if ticker and ticker.strip()
    }
    return sorted(required)


async def run_pipeline(
    *,
    selected_account_id: str | None = None,
    all_accounts: bool = False,
    run_kind: str = "execution",
    dataset_id: str = "portfolio_analytics",
) -> int:
    print(f"{CLR_BOLD}{CLR_BLUE}[{datetime.now(timezone.utc).isoformat()}] Starting AI Infrastructure Analyst pipeline...{CLR_RESET}")

    # Step 1: Initialize BigQuery Dataset and Tables
    print(f"\n{CLR_BOLD}{CLR_CYAN}🗄️ [PHASE: 1. Setup BigQuery Database]{CLR_RESET}")
    print(f"   Initializing BigQuery dataset '{dataset_id}' and validating schemas...")
    setup_bigquery(dataset_id=dataset_id)
    seed_account_registry(dataset_id=dataset_id)
    backfill_account_scope(dataset_id=dataset_id)
    print(f"   {CLR_GREEN}BigQuery verification complete.{CLR_RESET}")

    selected = (
        list_accounts(active_only=True, dataset_id=dataset_id)
        if all_accounts
        else [get_account(selected_account_id or "", dataset_id=dataset_id)]
    )
    skip_live_trades = os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true"
    modes = preflight_accounts(selected, skip_live_trades=skip_live_trades)
    print("   Account preflight:")
    for account in selected:
        print(
            f"     - {account.display_name} ({account.account_id}, {account.account_type.value}) "
            f"=> {modes[account.account_id].value}"
        )
    required_tickers = _required_account_tickers(selected, dataset_id)
    if required_tickers:
        print(f"   Held tickers required in today's analysis: {required_tickers}")

    # Determine if we skip ingestion (from env or if BQ today has records)
    skip_ingestion = os.environ.get("SKIP_INGESTION", "false").lower() == "true"
    
    ranked_portfolio = []
    graveyard_rows = None
    
    if skip_ingestion:
        print(f"\n{CLR_YELLOW}[SKIP_INGESTION] Checking BigQuery for today's market metrics...{CLR_RESET}")
        today_metrics = get_latest_market_metrics(dataset_id=dataset_id)
        if today_metrics:
            print(f"   {CLR_GREEN}Bypassing ingestion. Found {len(today_metrics)} existing metrics for today.{CLR_RESET}")
            ranked_portfolio = today_metrics
        else:
            print(f"   {CLR_YELLOW}Warning: SKIP_INGESTION was true but no daily metrics found in BigQuery. Running ingestion...{CLR_RESET}")
            skip_ingestion = False

    if not skip_ingestion:
        # Run daily analysis pipeline helper from data_ingestion tool
        ranked_portfolio, graveyard_rows = await run_sentiment_analysis_pipeline(
            dataset_id=dataset_id,
            required_tickers=required_tickers,
        )

    market_batch_id = _market_batch_id(ranked_portfolio)
    failures: list[tuple[str, str]] = []
    for account in selected:
        print(
            f"\n{CLR_BOLD}{CLR_BLUE}=== ACCOUNT: {account.display_name} "
            f"[{account.account_id}] ({account.account_type.value}) ==={CLR_RESET}"
        )
        context = AccountRunContext(
            account=account,
            run_kind=RunKind(run_kind.upper()),
            execution_mode=modes[account.account_id],
            requested_live=not skip_live_trades,
            market_batch_id=market_batch_id,
            suppress_account_notification=all_accounts,
        )
        try:
            final_portfolio = await financial_analysis_pipeline(
                ranked_portfolio=copy.deepcopy(ranked_portfolio),
                graveyard_rows=copy.deepcopy(graveyard_rows),
                dataset_id=dataset_id,
                run_context=context,
            )
            print_portfolio_table(final_portfolio)
        except Exception as exc:
            failures.append((account.account_id, str(exc)))
            print(f"{CLR_RED}[ACCOUNT FAILED] {account.account_id}: {exc}{CLR_RESET}")
    if all_accounts:
        try:
            import json
            from app.app_utils.discord_notifier import send_accounts_summary_webhook

            failure_reasons = dict(failures)
            failure_ids = set(failure_reasons)
            selected_ids = {account.account_id for account in selected}
            summary_rows = []
            for account in list_accounts(dataset_id=dataset_id):
                snapshot = get_latest_account_snapshot(account.account_id, dataset_id)
                activity = get_latest_account_activity(account.account_id, dataset_id)
                raw_holdings = (snapshot or {}).get("holdings") or "[]"
                if isinstance(raw_holdings, str):
                    raw_holdings = json.loads(raw_holdings)
                summary_rows.append({
                    "account_id": account.account_id,
                    "display_name": account.display_name,
                    "account_type": account.account_type.value,
                    "status": account.status.value,
                    "initial_cash": account.initial_cash,
                    "policy_name": account.policy_name,
                    "total_equity": (snapshot or {}).get("total_equity"),
                    "total_cash": (snapshot or {}).get("total_cash"),
                    "holdings": raw_holdings,
                    "decision_id": (activity or {}).get("decision_id"),
                    "decision_status": (activity or {}).get("status"),
                    "recommendation": (activity or {}).get("recommendation", []),
                    "trades": (activity or {}).get("trades", []),
                    "run_status": (
                        "FAILED" if account.account_id in failure_ids
                        else "PROCESSED" if account.account_id in selected_ids
                        else "NOT RUN"
                    ),
                    "run_error": failure_reasons.get(account.account_id),
                })
            send_accounts_summary_webhook(
                summary_rows,
                run_kind=run_kind,
                is_dry_run=skip_live_trades,
            )
        except Exception as exc:
            print(f"{CLR_YELLOW}Warning: consolidated Discord summary failed: {exc}{CLR_RESET}")
    if failures:
        print(f"\n{CLR_RED}{len(failures)} account run(s) failed:{CLR_RESET}")
        for account_id, reason in failures:
            print(f"  - {account_id}: {reason}")
        return 1
    print(f"\n{CLR_BOLD}{CLR_GREEN}🚀 [PHASE: Complete] All selected accounts finalized.{CLR_RESET}")
    return 0

if __name__ == "__main__":
    cli_parser = build_parser()
    cli_args = cli_parser.parse_args()
    _validate_args(cli_parser, cli_args)
    if cli_args.list_accounts:
        setup_bigquery(dataset_id=cli_args.dataset_id)
        seed_account_registry(dataset_id=cli_args.dataset_id)
        for item in list_accounts(dataset_id=cli_args.dataset_id):
            print(
                f"{item.account_id}\t{item.display_name}\t{item.account_type.value}\t"
                f"{item.status.value}\t{item.policy_name}/{item.policy_version}\t"
                f"live_eligible={item.live_execution_allowed}"
            )
        raise SystemExit(0)
    raise SystemExit(
        asyncio.run(
            run_pipeline(
                selected_account_id=cli_args.account,
                all_accounts=cli_args.all_accounts,
                run_kind=cli_args.run_kind,
                dataset_id=cli_args.dataset_id,
            )
        )
    )
