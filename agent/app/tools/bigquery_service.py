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

    # Tables created:
    # - infrastructure_market_metrics: stores sentiment analysis, momentum and analyst ratings.
    # - trade_history: stores trade transaction receipts.
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

    # 2. Define infrastructure_market_metrics table schema
    sentiment_table_id = f"{project}.{dataset_id}.infrastructure_market_metrics"
    sentiment_schema = [
        bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("raw_score", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("thesis", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("relative_rank", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("signal", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("raw_news", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("analyst_consensus", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("target_price", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("current_price", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("moving_average_20d", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("price_to_ma_ratio", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("rsi", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("macd", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("macd_signal", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("drawdown_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("sustained_rsi_drop", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("sentiment_ewma", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("sentiment_volatility", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("target_weight", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("is_20d_high", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("macd_bullish_cross", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("forward_pe", "FLOAT", mode="NULLABLE"),
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
        bigquery.SchemaField("reasoning", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("dry_run", "BOOLEAN", mode="NULLABLE"),
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

    # 4. Define portfolio_snapshot table schema
    snapshot_table_id = f"{project}.{dataset_id}.portfolio_snapshot"
    snapshot_schema = [
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("account_number", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("total_equity", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("total_cash", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("unrealized_gain_loss", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("unrealized_gain_loss_percent", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("holdings", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("buying_power", "FLOAT", mode="NULLABLE"),
    ]
    snapshot_table = bigquery.Table(snapshot_table_id, schema=snapshot_schema)
    try:
        existing_table = client.get_table(snapshot_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in snapshot_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(snapshot_table, exists_ok=True)


def _sanitize_string(s: str | None) -> str | None:
    if s is None:
        return None
    # Filter out control characters (ASCII < 32) except tab, newline, carriage return
    # and remove null bytes
    cleaned = "".join(ch for ch in s if ord(ch) >= 32 or ch in "\n\r\t")
    cleaned = cleaned.replace("\x00", "")
    # Remove trailing backslashes to avoid escaping closing quotes in JSON loading
    while cleaned.endswith("\\"):
        cleaned = cleaned[:-1]
    return cleaned


def _sanitize_news(news: Any) -> Any:
    if isinstance(news, list):
        return [_sanitize_news(x) for x in news]
    elif isinstance(news, dict):
        return {k: _sanitize_news(v) for k, v in news.items()}
    elif isinstance(news, str):
        cleaned = "".join(ch for ch in news if ord(ch) >= 32 or ch in "\n\r\t")
        cleaned = cleaned.replace("\x00", "")
        # Remove trailing backslashes
        while cleaned.endswith("\\"):
            cleaned = cleaned[:-1]
        return cleaned
    return news


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        import math
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def insert_sentiment(
    ranked_portfolio: List[Dict[str, Any]], 
    dataset_id: str = "portfolio_analytics"
) -> None:
    """Inserts the ranked list from Phase 2 into the infrastructure_market_metrics table.

    Args:
        ranked_portfolio: List of dictionaries containing ticker, raw_score, thesis, relative_rank, signal, raw_news, and market metrics.
        dataset_id: The BigQuery dataset ID.
    """
    if not ranked_portfolio:
        return

    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_market_metrics"
    
    current_time_str = datetime.now(timezone.utc).isoformat()
    
    rows_to_insert = []
    for item in ranked_portfolio:
        thesis_val = _sanitize_string(item.get("thesis"))
        raw_news_val = item.get("raw_news")
        if isinstance(raw_news_val, (list, dict)):
            raw_news_val = _sanitize_news(raw_news_val)
            import json
            raw_news_val = json.dumps(raw_news_val)
        raw_news_val = _sanitize_string(raw_news_val)
        analyst_consensus_val = _sanitize_string(item.get("analyst_consensus"))

        # Cast to float/int if present to prevent any serialization type mismatch
        target_price_val = _safe_float(item.get("target_price"))
        current_price_val = _safe_float(item.get("current_price"))
        ma_20_val = _safe_float(item.get("moving_average_20d"))
        ratio_val = _safe_float(item.get("price_to_ma_ratio"))
        rsi_val = _safe_float(item.get("rsi"))
        macd_val = _safe_float(item.get("macd"))
        macd_sig_val = _safe_float(item.get("macd_signal"))
        drawdown_pct_val = _safe_float(item.get("drawdown_pct"))
        sustained_rsi_drop_val = item.get("sustained_rsi_drop")
        if sustained_rsi_drop_val is not None:
            sustained_rsi_drop_val = bool(sustained_rsi_drop_val)
        sentiment_ewma_val = _safe_float(item.get("sentiment_ewma"))
        sentiment_volatility_val = _safe_float(item.get("sentiment_volatility"))
        target_weight_val = _safe_float(item.get("target_weight"))
        is_20d_high_val = item.get("is_20d_high")
        if is_20d_high_val is not None:
            is_20d_high_val = bool(is_20d_high_val)
        macd_bullish_cross_val = item.get("macd_bullish_cross")
        if macd_bullish_cross_val is not None:
            macd_bullish_cross_val = bool(macd_bullish_cross_val)
        forward_pe_val = _safe_float(item.get("forward_pe"))

        rows_to_insert.append({
            "ticker": item["ticker"],
            "raw_score": float(item["raw_score"]),
            "thesis": thesis_val,
            "relative_rank": int(item["relative_rank"]),
            "signal": item["signal"],
            "timestamp": item.get("timestamp") or current_time_str,
            "raw_news": raw_news_val,
            "analyst_consensus": analyst_consensus_val,
            "target_price": target_price_val,
            "current_price": current_price_val,
            "moving_average_20d": ma_20_val,
            "price_to_ma_ratio": ratio_val,
            "rsi": rsi_val,
            "macd": macd_val,
            "macd_signal": macd_sig_val,
            "drawdown_pct": drawdown_pct_val,
            "sustained_rsi_drop": sustained_rsi_drop_val,
            "sentiment_ewma": sentiment_ewma_val,
            "sentiment_volatility": sentiment_volatility_val,
            "target_weight": target_weight_val,
            "is_20d_high": is_20d_high_val,
            "macd_bullish_cross": macd_bullish_cross_val,
            "forward_pe": forward_pe_val
        })
        
    try:
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
        )
        job = client.load_table_from_json(rows_to_insert, table_id, job_config=job_config)
        job.result()
    except Exception as e:
        raise RuntimeError(f"Failed to insert sentiment rows into BigQuery: {e}")


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
    table_id = f"{client.project}.{dataset_id}.infrastructure_market_metrics"

    # Query latest signals matching STRONG BUY or LIQUIDATE for the given date, ordered by timestamp desc
    query = f"""
        SELECT ticker, raw_score, thesis, relative_rank, signal, timestamp, analyst_consensus, target_price, current_price, moving_average_20d, price_to_ma_ratio, rsi, macd, macd_signal, target_weight, forward_pe
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
            "timestamp": row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp),
            "analyst_consensus": getattr(row, "analyst_consensus", None),
            "target_price": getattr(row, "target_price", None),
            "current_price": getattr(row, "current_price", None),
            "moving_average_20d": getattr(row, "moving_average_20d", None),
            "price_to_ma_ratio": getattr(row, "price_to_ma_ratio", None),
            "rsi": getattr(row, "rsi", None),
            "macd": getattr(row, "macd", None),
            "macd_signal": getattr(row, "macd_signal", None),
            "target_weight": getattr(row, "target_weight", None),
            "forward_pe": getattr(row, "forward_pe", None)
        })
        
    return signals


def insert_trade_record(
    ticker: str, 
    action: str, 
    amount_usd: float, 
    timestamp: float | None = None, 
    reasoning: str | None = None,
    dry_run: bool | None = None,
    dataset_id: str = "portfolio_analytics"
) -> None:
    """Inserts a trade receipt (ticker, action, amount_usd, timestamp, reasoning, dry_run) into the trade_history table.

    Args:
        ticker: The stock ticker symbol.
        action: The trading action (e.g. STRONG BUY, LIQUIDATE, HOLD).
        amount_usd: Total dollar amount of the transaction.
        timestamp: Unix timestamp. Defaults to time.time().
        reasoning: Text explaining the trade logic.
        dry_run: Whether this was a simulated/dry-run trade. Defaults to checking SKIP_LIVE_TRADES env.
        dataset_id: The BigQuery dataset ID.
    """
    import os
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    if timestamp is None:
        timestamp = time.time()
        
    timestamp_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    if dry_run is None:
        dry_run = os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true"

    row_to_insert = {
        "ticker": ticker,
        "action": action,
        "amount_usd": float(amount_usd),
        "timestamp": timestamp_str,
        "reasoning": reasoning,
        "dry_run": bool(dry_run)
    }
    
    try:
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
        )
        job = client.load_table_from_json([row_to_insert], table_id, job_config=job_config)
        job.result()
    except Exception as e:
        raise RuntimeError(f"Failed to insert trade record into BigQuery: {e}")


def insert_portfolio_snapshot(
    snapshot: dict,
    dataset_id: str = "portfolio_analytics"
) -> None:
    """Inserts a portfolio value and holdings snapshot into the portfolio_snapshot table.

    Args:
        snapshot: Dictionary containing total_equity, total_cash, unrealized_gain_loss, 
                  unrealized_gain_loss_percent, account_number, holdings, and optional timestamp.
        dataset_id: The BigQuery dataset ID.
    """
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.portfolio_snapshot"

    current_time_str = datetime.now(timezone.utc).isoformat()
    
    row_to_insert = {
        "timestamp": snapshot.get("timestamp") or current_time_str,
        "account_number": snapshot["account_number"],
        "total_equity": float(snapshot["total_equity"]),
        "total_cash": float(snapshot["total_cash"]),
        "unrealized_gain_loss": float(snapshot["unrealized_gain_loss"]),
        "unrealized_gain_loss_percent": float(snapshot["unrealized_gain_loss_percent"]),
        "holdings": snapshot["holdings"],  # JSON-formatted string
        "buying_power": float(snapshot["buying_power"]) if snapshot.get("buying_power") is not None else None
    }

    try:
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
        )
        job = client.load_table_from_json([row_to_insert], table_id, job_config=job_config)
        job.result()
    except Exception as e:
        raise RuntimeError(f"Failed to insert portfolio snapshot into BigQuery: {e}")


def get_historical_metrics(
    days: int = 7,
    dataset_id: str = "portfolio_analytics"
) -> List[Dict[str, Any]]:
    """Queries BigQuery and returns historical Daily Market Metrics over the specified lookback window.

    Args:
        days: Historical lookback window in days.
        dataset_id: The BigQuery dataset ID.

    Returns:
        A list of dictionaries containing daily metrics for assets.
    """
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_market_metrics"

    query = f"""
        SELECT ticker, raw_score, thesis, relative_rank, signal, timestamp, analyst_consensus, target_price, current_price, moving_average_20d, price_to_ma_ratio, rsi, macd, macd_signal, drawdown_pct, sustained_rsi_drop, sentiment_ewma, sentiment_volatility, target_weight, is_20d_high, macd_bullish_cross, forward_pe
        FROM `{table_id}`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
          AND signal != 'FILTERED'
          AND ticker != 'SPY'
        ORDER BY ticker, timestamp ASC
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days)
        ]
    )
    
    query_job = client.query(query, job_config=job_config)
    results = query_job.result()
    
    metrics = []
    for row in results:
        metrics.append({
            "ticker": row.ticker,
            "raw_score": row.raw_score,
            "thesis": row.thesis,
            "relative_rank": row.relative_rank,
            "signal": row.signal,
            "timestamp": row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp),
            "analyst_consensus": getattr(row, "analyst_consensus", None),
            "target_price": getattr(row, "target_price", None),
            "current_price": getattr(row, "current_price", None),
            "moving_average_20d": getattr(row, "moving_average_20d", None),
            "price_to_ma_ratio": getattr(row, "price_to_ma_ratio", None),
            "rsi": getattr(row, "rsi", None),
            "macd": getattr(row, "macd", None),
            "macd_signal": getattr(row, "macd_signal", None),
            "drawdown_pct": getattr(row, "drawdown_pct", None),
            "sustained_rsi_drop": getattr(row, "sustained_rsi_drop", None),
            "sentiment_ewma": getattr(row, "sentiment_ewma", None),
            "sentiment_volatility": getattr(row, "sentiment_volatility", None),
            "target_weight": getattr(row, "target_weight", None),
            "is_20d_high": getattr(row, "is_20d_high", None),
            "macd_bullish_cross": getattr(row, "macd_bullish_cross", None),
            "forward_pe": getattr(row, "forward_pe", None)
        })
        
    return metrics


def get_latest_market_metrics(
    dataset_id: str = "portfolio_analytics",
    date_str: str | None = None
) -> List[Dict[str, Any]]:
    """Queries BigQuery and returns all asset records for today's date (or the specified target date).

    Args:
        dataset_id: The BigQuery dataset ID.
        date_str: Target date string formatted as 'YYYY-MM-DD'. Defaults to today's date in UTC.

    Returns:
        A list of dictionaries containing daily metrics for all assets.
    """
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_market_metrics"

    query = f"""
        SELECT ticker, raw_score, thesis, relative_rank, signal, timestamp, analyst_consensus, target_price, current_price, moving_average_20d, price_to_ma_ratio, rsi, macd, macd_signal, drawdown_pct, sustained_rsi_drop, sentiment_ewma, sentiment_volatility, target_weight, is_20d_high, macd_bullish_cross, forward_pe
        FROM `{table_id}`
        WHERE DATE(timestamp) = @target_date
        ORDER BY relative_rank DESC
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "STRING", date_str)
        ]
    )
    
    query_job = client.query(query, job_config=job_config)
    results = query_job.result()
    
    metrics = []
    for row in results:
        metrics.append({
            "ticker": row.ticker,
            "raw_score": row.raw_score,
            "thesis": row.thesis,
            "relative_rank": row.relative_rank,
            "signal": row.signal,
            "timestamp": row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp),
            "analyst_consensus": getattr(row, "analyst_consensus", None),
            "target_price": getattr(row, "target_price", None),
            "current_price": getattr(row, "current_price", None),
            "moving_average_20d": getattr(row, "moving_average_20d", None),
            "price_to_ma_ratio": getattr(row, "price_to_ma_ratio", None),
            "rsi": getattr(row, "rsi", None),
            "macd": getattr(row, "macd", None),
            "macd_signal": getattr(row, "macd_signal", None),
            "drawdown_pct": getattr(row, "drawdown_pct", None),
            "sustained_rsi_drop": getattr(row, "sustained_rsi_drop", None),
            "sentiment_ewma": getattr(row, "sentiment_ewma", None),
            "sentiment_volatility": getattr(row, "sentiment_volatility", None),
            "target_weight": getattr(row, "target_weight", None),
            "is_20d_high": getattr(row, "is_20d_high", None),
            "macd_bullish_cross": getattr(row, "macd_bullish_cross", None),
            "forward_pe": getattr(row, "forward_pe", None)
        })
        
    return metrics


def get_latest_portfolio_holdings(dataset_id: str = "portfolio_analytics") -> List[str]:
    """Queries BigQuery and returns the list of stock symbols currently owned.

    Queries the most recent portfolio snapshot and parses the holdings JSON.
    """
    import json
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.portfolio_snapshot"

    query = f"""
        SELECT holdings
        FROM `{table_id}`
        ORDER BY timestamp DESC
        LIMIT 1
    """
    try:
        query_job = client.query(query)
        results = list(query_job.result())
        if results:
            row = results[0]
            holdings_str = row.get("holdings")
            if holdings_str:
                holdings = json.loads(holdings_str)
                return [h.get("symbol") for h in holdings if h.get("shares", 0) > 0]
    except Exception:
        # Fallback to empty list if dataset/table does not exist or query fails
        pass

    return []


def get_recent_trades(
    limit: int = 10,
    dry_run: bool = True,
    dataset_id: str = "portfolio_analytics"
) -> List[Dict[str, Any]]:
    """Queries BigQuery and returns the most recent trades for the given execution mode."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT ticker, action, amount_usd, timestamp, reasoning
        FROM `{table_id}`
        WHERE dry_run = @dry_run
        ORDER BY timestamp DESC
        LIMIT @limit
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run),
            bigquery.ScalarQueryParameter("limit", "INT64", limit)
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result()
        trades = []
        for row in results:
            trades.append({
                "ticker": row.ticker,
                "action": row.action,
                "amount_usd": row.amount_usd,
                "timestamp": row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp),
                "reasoning": row.reasoning
            })
        return trades
    except Exception:
        return []


def get_last_buy_timestamp(
    ticker: str,
    dry_run: bool = True,
    dataset_id: str = "portfolio_analytics"
) -> datetime | None:
    """Queries the timestamp of the last BUY action for the given ticker and execution mode."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT timestamp
        FROM `{table_id}`
        WHERE ticker = @ticker AND action IN ('BUY', 'STRONG BUY') AND dry_run = @dry_run
        ORDER BY timestamp DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ticker", "STRING", ticker),
            bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run)
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        results = list(query_job.result())
        if results:
            return results[0].timestamp
    except Exception:
        pass
    return None


def get_recent_sentiment_scores(
    tickers: List[str], 
    limit: int = 4, 
    dataset_id: str = "portfolio_analytics"
) -> Dict[str, List[float]]:
    """Queries BigQuery and returns the historical average daily sentiment scores for tickers over the last N days."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.infrastructure_market_metrics"
    
    if not tickers:
        return {}

    # Select the daily average scores for the last N calendar days
    query = f"""
        WITH daily_scores AS (
            SELECT ticker, raw_score, DATE(timestamp) as date
            FROM `{table_id}`
            WHERE ticker IN UNNEST(@tickers)
        )
        SELECT ticker, avg_score, date
        FROM (
            SELECT ticker, AVG(raw_score) as avg_score, date,
                   ROW_NUMBER() OVER(PARTITION BY ticker ORDER BY date DESC) as rn
            FROM daily_scores
            GROUP BY ticker, date
        )
        WHERE rn <= @limit
        ORDER BY ticker, date ASC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("tickers", "STRING", tickers),
            bigquery.ScalarQueryParameter("limit", "INT64", limit)
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result()
        scores = {}
        for row in results:
            ticker = row.ticker
            if ticker not in scores:
                scores[ticker] = []
            scores[ticker].append(float(row.avg_score))
        return scores
    except Exception:
        return {}


def get_recently_sold_tickers(
    days: int = 21,
    dataset_id: str = "portfolio_analytics"
) -> List[str]:
    """Queries BigQuery and returns the list of stock symbols sold (dry_run = FALSE) in the last N days."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT DISTINCT ticker
        FROM `{table_id}`
        WHERE action IN ('SELL', 'LIQUIDATE')
          AND dry_run = FALSE
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days)
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result()
        return [row.ticker for row in results if row.ticker]
    except Exception:
        return []


