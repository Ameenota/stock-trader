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

import argparse
from pathlib import Path

from dotenv import load_dotenv

from app.tools.bigquery_service import (
    backfill_account_scope,
    seed_account_registry,
    setup_bigquery,
)


def setup(dataset_id: str = "portfolio_analytics") -> None:
    """Provision BigQuery tables, seed accounts, and migrate legacy rows."""
    setup_bigquery(dataset_id=dataset_id)
    seed_account_registry(dataset_id=dataset_id)
    backfill_account_scope(dataset_id=dataset_id)


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    parser = argparse.ArgumentParser(description="Set up the stock-trader BigQuery dataset")
    parser.add_argument("--dataset-id", default="portfolio_analytics")
    args = parser.parse_args()
    setup(dataset_id=args.dataset_id)
    print(f"BigQuery dataset {args.dataset_id!r} is ready.")


if __name__ == "__main__":
    main()
