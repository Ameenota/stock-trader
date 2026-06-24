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

from datetime import datetime, timezone
import time
from typing import List, Dict, Any
from google.cloud import bigquery
from google.api_core.exceptions import Conflict

def get_bigquery_client() -> bigquery.Client:
    """Initializes the BigQuery client using Application Default Credentials (ADC)."""
    return bigquery.Client()

def setup_bigquery(dataset_id: str = "portfolio_analytics") -> None:
    """Checks if the dataset exists and creates it along with required tables if they do not exist.

    Tables created:
    - infrastructure_sentiment: stores sentiment analysis outputs and trade signals.
    - trade_history: stores trade transaction receipts.
    """
    client = get_bigquery_client()
    project = client.project
    dataset_ref = bigquery.DatasetReference(project, dataset_id)

    # 1. Create Dataset if it does not exist
    try:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"  # Default location
        client.create_dataset(dataset, exists_ok=True)
    except Exception as e:
        # Fallback or log if create_dataset fails
        pass

    # 2. Define infrastructure_sentiment table schema
    sentiment_table_id = f"{project}.{dataset_id}.infrastructure_sentiment"
    sentiment_schema = [
        bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("raw_score", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("thesis", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("relative_rank", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("signal", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("raw_news", "STRING", mode="NULLABLE"),
    ]
    sentiment_table = bigquery.Table(sentiment_table_id, schema=sentiment_schema)
    try:
        existing_table = client.get_table(sentiment_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in sentiment_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(sentiment_table, exists_ok=True)

    # 3. Define trade_history table schema
    trade_table_id = f"{project}.{dataset_id}.trade_history"
    trade_schema = [
        bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("action", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("amount_usd", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
    ]
    trade_table = bigquery.Table(trade_table_id, schema=trade_schema)
    try:
        existing_table = client.get_table(trade_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in trade_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(trade_table, exists_ok=True)


def insert_sentiment(
    ranked_portfolio: List[Dict[str, Any]], 
    dataset_id: str = "portfolio_analytics"
) -> None:
    """Inserts the ranked list from Phase 2 into the infrastructure_sentiment table.

    Args:
        ranked_portfolio: List of dictionaries containing ticker, raw_score, thesis, relative_rank, signal, and raw_news.
        dataset_id: The BigQuery dataset ID.
    """
    if not ranked_portfolio:
        return

    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_sentiment"
    
    current_time_str = datetime.now(timezone.utc).isoformat()
    
    rows_to_insert = []
    for item in ranked_portfolio:
        raw_news_val = item.get("raw_news")
        if isinstance(raw_news_val, (list, dict)):
            import json
            raw_news_val = json.dumps(raw_news_val)

        rows_to_insert.append({
            "ticker": item["ticker"],
            "raw_score": float(item["raw_score"]),
            "thesis": item.get("thesis"),
            "relative_rank": int(item["relative_rank"]),
            "signal": item["signal"],
            "timestamp": item.get("timestamp") or current_time_str,
            "raw_news": raw_news_val
        })
        
    errors = client.insert_rows_json(table_id, rows_to_insert)
    if errors:
        raise RuntimeError(f"Failed to insert sentiment rows into BigQuery: {errors}")


def get_latest_signals(
    dataset_id: str = "portfolio_analytics", 
    date_str: str | None = None
) -> List[Dict[str, Any]]:
    """Queries BigQuery and returns the most recent 'STRONG BUY' and 'LIQUIDATE' signals for today's date.

    Args:
        dataset_id: The BigQuery dataset ID.
        date_str: Target date string formatted as 'YYYY-MM-DD'. Defaults to today's date in UTC.

    Returns:
        A list of dictionaries containing signals.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_sentiment"

    # Query latest signals matching STRONG BUY or LIQUIDATE for the given date, ordered by timestamp desc
    query = f"""
        SELECT ticker, raw_score, thesis, relative_rank, signal, timestamp
        FROM `{table_id}`
        WHERE DATE(timestamp) = @target_date
          AND signal IN ('STRONG BUY', 'LIQUIDATE')
        ORDER BY timestamp DESC
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "STRING", date_str)
        ]
    )
    
    query_job = client.query(query, job_config=job_config)
    results = query_job.result()
    
    signals = []
    for row in results:
        signals.append({
            "ticker": row.ticker,
            "raw_score": row.raw_score,
            "thesis": row.thesis,
            "relative_rank": row.relative_rank,
            "signal": row.signal,
            "timestamp": row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp)
        })
        
    return signals


def insert_trade_record(
    ticker: str, 
    action: str, 
    amount_usd: float, 
    timestamp: float | None = None, 
    dataset_id: str = "portfolio_analytics"
) -> None:
    """Inserts a trade receipt (ticker, action, amount_usd, timestamp) into the trade_history table.

    Args:
        ticker: The stock ticker symbol.
        action: The trading action (e.g. STRONG BUY, LIQUIDATE, HOLD).
        amount_usd: Total dollar amount of the transaction.
        timestamp: Unix timestamp. Defaults to time.time().
        dataset_id: The BigQuery dataset ID.
    """
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    if timestamp is None:
        timestamp = time.time()
        
    timestamp_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    row_to_insert = {
        "ticker": ticker,
        "action": action,
        "amount_usd": float(amount_usd),
        "timestamp": timestamp_str
    }
    
    errors = client.insert_rows_json(table_id, [row_to_insert])
    if errors:
        raise RuntimeError(f"Failed to insert trade record into BigQuery: {errors}")
