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
import json
import time
import uuid
from typing import List, Dict, Any
from google.cloud import bigquery
from google.api_core.exceptions import Conflict

from app.accounts import AtrPolicyConfig, TradingAccount, policy_config_hash

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
        bigquery.SchemaField("record_scope", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("decision_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("market_batch_id", "STRING", mode="NULLABLE"),
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
        bigquery.SchemaField("decision_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("broker_order_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("order_status", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("requested_quantity", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("filled_quantity", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("trade_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("execution_mode", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("fill_price", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("fees_usd", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("slippage_usd", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("market_batch_id", "STRING", mode="NULLABLE"),
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
        bigquery.SchemaField("summary", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("snapshot_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("snapshot_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("decision_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("market_batch_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("policy_config_hash", "STRING", mode="NULLABLE"),
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

    execution_table_id = f"{project}.{dataset_id}.execution_runs"
    execution_schema = [
        bigquery.SchemaField("decision_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("dry_run", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("policy_version", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("policy_allowed", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("violations", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("proposal", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("execution_result", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("run_kind", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("market_date", "DATE", mode="NULLABLE"),
        bigquery.SchemaField("execution_window", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("market_batch_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("execution_mode", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("requested_live", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("policy_name", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("policy_config", "JSON", mode="NULLABLE"),
        bigquery.SchemaField("policy_config_hash", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("claim_token", "STRING", mode="NULLABLE"),
    ]
    execution_table = bigquery.Table(execution_table_id, schema=execution_schema)
    try:
        existing_table = client.get_table(execution_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in execution_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(execution_table, exists_ok=True)

    risk_table_id = f"{project}.{dataset_id}.position_risk_state"
    risk_schema = [
        bigquery.SchemaField("account_suffix", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("entry_timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("last_session", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("highest_high", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("stop_price", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("atr", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("breached", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("position_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("confirmation_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("stop_state", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("policy_config_hash", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("position_closed_at", "TIMESTAMP", mode="NULLABLE"),
    ]
    risk_table = bigquery.Table(risk_table_id, schema=risk_schema)
    try:
        existing_table = client.get_table(risk_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in risk_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(risk_table, exists_ok=True)

    accounts_table_id = f"{project}.{dataset_id}.accounts"
    accounts_schema = [
        bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("display_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("is_dashboard_default", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("broker_provider", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("broker_account_ref", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("broker_account_suffix", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("live_execution_allowed", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("initial_cash", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("base_currency", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("policy_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("policy_version", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("policy_config", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("policy_config_hash", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    ]
    accounts_table = bigquery.Table(accounts_table_id, schema=accounts_schema)
    try:
        existing_table = client.get_table(accounts_table_id)
        existing_fields = {field.name for field in existing_table.schema}
        fields_to_add = [field for field in accounts_schema if field.name not in existing_fields]
        if fields_to_add:
            existing_table.schema = list(existing_table.schema) + fields_to_add
            client.update_table(existing_table, ["schema"])
    except Exception:
        client.create_table(accounts_table, exists_ok=True)


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
            "forward_pe": forward_pe_val,
            "record_scope": item.get("record_scope") or (
                "ACCOUNT_DECISION" if item.get("account_id") else "MARKET_INPUT"
            ),
            "account_id": item.get("account_id"),
            "decision_id": item.get("decision_id"),
            "market_batch_id": item.get("market_batch_id"),
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
    dataset_id: str = "portfolio_analytics",
    decision_id: str | None = None,
    broker_order_id: str | None = None,
    order_status: str | None = None,
    requested_quantity: float | None = None,
    filled_quantity: float | None = None,
    account_id: str | None = None,
    trade_id: str | None = None,
    execution_mode: str | None = None,
    fill_price: float | None = None,
    fees_usd: float | None = None,
    slippage_usd: float | None = None,
    market_batch_id: str | None = None,
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
        "dry_run": bool(dry_run),
    }
    optional_fields = {
        "decision_id": decision_id,
        "broker_order_id": broker_order_id,
        "order_status": order_status,
        "requested_quantity": requested_quantity,
        "filled_quantity": filled_quantity,
        "account_id": account_id,
        "trade_id": trade_id,
        "execution_mode": execution_mode,
        "fill_price": fill_price,
        "fees_usd": fees_usd,
        "slippage_usd": slippage_usd,
        "market_batch_id": market_batch_id,
    }
    row_to_insert.update({key: value for key, value in optional_fields.items() if value is not None})
    
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
        "buying_power": float(snapshot["buying_power"]) if snapshot.get("buying_power") is not None else None,
        "summary": _sanitize_string(snapshot.get("summary"))
    }
    for key in (
        "account_id", "snapshot_id", "snapshot_type", "decision_id",
        "market_batch_id", "policy_config_hash",
    ):
        if snapshot.get(key) is not None:
            row_to_insert[key] = snapshot[key]

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
          AND (record_scope IS NULL OR record_scope IN ('MARKET_INPUT', 'LEGACY_COMBINED'))
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
        WHERE timestamp = (
            SELECT MAX(timestamp) 
            FROM `{table_id}` 
            WHERE DATE(timestamp) = @target_date
              AND (record_scope IS NULL OR record_scope IN ('MARKET_INPUT', 'LEGACY_COMBINED'))
        )
          AND (record_scope IS NULL OR record_scope IN ('MARKET_INPUT', 'LEGACY_COMBINED'))
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
    seen_tickers = set()
    for row in results:
        ticker = row.ticker
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        metrics.append({
            "ticker": ticker,
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


def get_latest_portfolio_holdings(
    dataset_id: str = "portfolio_analytics",
    account_id: str = "real-48661",
) -> List[str]:
    """Queries BigQuery and returns the list of stock symbols currently owned.

    Queries the most recent portfolio snapshot and parses the holdings JSON.
    """
    import json
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.portfolio_snapshot"

    query = f"""
        SELECT holdings
        FROM `{table_id}`
        WHERE account_id=@account_id
        ORDER BY timestamp DESC
        LIMIT 1
    """
    try:
        query_job = client.query(
            query,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
            ]),
        )
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
    dataset_id: str = "portfolio_analytics",
    account_id: str | None = None,
) -> List[Dict[str, Any]]:
    """Queries BigQuery and returns the most recent trades for the given execution mode."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT ticker, action, amount_usd, timestamp, reasoning
        FROM `{table_id}`
        WHERE dry_run = @dry_run
          AND (@account_id IS NULL OR account_id = @account_id)
        ORDER BY timestamp DESC
        LIMIT @limit
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run),
            bigquery.ScalarQueryParameter("limit", "INT64", limit)
            ,bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
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
    dataset_id: str = "portfolio_analytics",
    account_id: str | None = None,
) -> datetime | None:
    """Queries the timestamp of the last BUY action for the given ticker and execution mode."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT timestamp
        FROM `{table_id}`
        WHERE ticker = @ticker AND action IN ('BUY', 'STRONG BUY') AND dry_run = @dry_run
          AND (@account_id IS NULL OR account_id = @account_id)
        ORDER BY timestamp DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ticker", "STRING", ticker),
            bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run),
            bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
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
    dataset_id: str = "portfolio_analytics",
    account_id: str = "real-48661",
) -> List[str]:
    """Queries BigQuery and returns the list of stock symbols sold (dry_run = FALSE) in the last N days."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.trade_history"

    query = f"""
        SELECT DISTINCT ticker
        FROM `{table_id}`
        WHERE action IN ('SELL', 'LIQUIDATE')
          AND dry_run = FALSE
          AND account_id = @account_id
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days),
            bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result()
        return [row.ticker for row in results if row.ticker]
    except Exception:
        return []


EXECUTION_RUN_STATUSES = {
    "POLICY_REJECTED",
    "VALIDATED",
    "EXECUTING",
    "COMPLETED",
    "ABORTED",
    "RECONCILIATION_FAILED",
}


def execution_run_exists(decision_id: str, dry_run: bool, dataset_id: str = "portfolio_analytics", account_id: str | None = None) -> bool:
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.execution_runs"
    query = f"SELECT 1 FROM `{table_id}` WHERE decision_id = @decision_id AND dry_run = @dry_run AND status NOT IN ('ABORTED', 'RECONCILIATION_FAILED') AND (@account_id IS NULL OR account_id=@account_id) LIMIT 1"
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("decision_id", "STRING", decision_id),
        bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run),
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
    ])
    try:
        return bool(list(client.query(query, job_config=config).result()))
    except Exception as exc:
        raise RuntimeError(f"Failed to check execution run: {exc}") from exc


def insert_execution_run(
    *,
    decision_id: str,
    dry_run: bool,
    policy_version: str,
    policy_allowed: bool,
    status: str,
    violations: object = None,
    proposal: object = None,
    execution_result: object = None,
    dataset_id: str = "portfolio_analytics",
    account_id: str | None = None,
    run_kind: str | None = None,
    market_date: str | None = None,
    execution_window: str | None = None,
    market_batch_id: str | None = None,
    execution_mode: str | None = None,
    requested_live: bool | None = None,
    policy_name: str | None = None,
    policy_config: object = None,
    policy_config_hash: str | None = None,
) -> None:
    if status not in EXECUTION_RUN_STATUSES:
        raise ValueError(f"Invalid execution run status: {status}")
    client = get_bigquery_client()
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "decision_id": decision_id,
        "created_at": now,
        "updated_at": now,
        "dry_run": dry_run,
        "policy_version": policy_version,
        "policy_allowed": policy_allowed,
        "status": status,
        "violations": json.dumps(violations, default=str) if violations is not None else None,
        "proposal": json.dumps(proposal, default=str) if proposal is not None else None,
        "execution_result": json.dumps(execution_result, default=str) if execution_result is not None else None,
        "account_id": account_id,
        "run_kind": run_kind,
        "market_date": market_date,
        "execution_window": execution_window,
        "market_batch_id": market_batch_id,
        "execution_mode": execution_mode,
        "requested_live": requested_live,
        "policy_name": policy_name,
        "policy_config": policy_config,
        "policy_config_hash": policy_config_hash,
    }
    table_id = f"{client.project}.{dataset_id}.execution_runs"
    job = client.load_table_from_json([row], table_id, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"))
    job.result()


def claim_execution_run(
    *,
    decision_id: str,
    dry_run: bool,
    policy_version: str,
    policy_allowed: bool,
    status: str,
    account_id: str,
    run_kind: str,
    market_date: str,
    execution_window: str,
    market_batch_id: str,
    execution_mode: str,
    requested_live: bool,
    policy_name: str,
    policy_config: object,
    policy_config_hash: str,
    violations: object = None,
    proposal: object = None,
    dataset_id: str = "portfolio_analytics",
) -> bool:
    """Atomically claim one account/market-date execution identity."""
    if status not in EXECUTION_RUN_STATUSES:
        raise ValueError(f"Invalid execution run status: {status}")
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.execution_runs"
    claim_token = uuid.uuid4().hex
    query = f"""
      MERGE `{table_id}` target
      USING (SELECT @account_id account_id, @market_date market_date,
                    @execution_window execution_window, @run_kind run_kind) source
      ON target.account_id=source.account_id
         AND target.market_date=CAST(source.market_date AS DATE)
         AND target.execution_window=source.execution_window
         AND target.run_kind=source.run_kind
      WHEN MATCHED AND target.status IN ('ABORTED', 'RECONCILIATION_FAILED')
        THEN UPDATE SET claim_token=@claim_token, updated_at=CURRENT_TIMESTAMP(),
          status=@status, policy_allowed=@policy_allowed, violations=@violations,
          proposal=@proposal, market_batch_id=@market_batch_id,
          execution_mode=@execution_mode, requested_live=@requested_live,
          policy_name=@policy_name, policy_config=PARSE_JSON(@policy_config),
          policy_config_hash=@policy_config_hash
      WHEN NOT MATCHED THEN INSERT
        (decision_id, created_at, updated_at, dry_run, policy_version,
         policy_allowed, status, violations, proposal, account_id, run_kind,
         market_date, execution_window, market_batch_id, execution_mode,
         requested_live, policy_name, policy_config, policy_config_hash, claim_token)
      VALUES
        (@decision_id, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), @dry_run,
         @policy_version, @policy_allowed, @status, @violations, @proposal,
         @account_id, @run_kind, CAST(@market_date AS DATE), @execution_window,
         @market_batch_id, @execution_mode, @requested_live, @policy_name,
         PARSE_JSON(@policy_config), @policy_config_hash, @claim_token);
      SELECT claim_token FROM `{table_id}`
      WHERE account_id=@account_id AND market_date=CAST(@market_date AS DATE)
        AND execution_window=@execution_window AND run_kind=@run_kind
      LIMIT 1
    """
    values = {
        "decision_id": ("STRING", decision_id),
        "dry_run": ("BOOL", dry_run),
        "policy_version": ("STRING", policy_version),
        "policy_allowed": ("BOOL", policy_allowed),
        "status": ("STRING", status),
        "violations": ("STRING", json.dumps(violations, default=str) if violations is not None else None),
        "proposal": ("STRING", json.dumps(proposal, default=str) if proposal is not None else None),
        "account_id": ("STRING", account_id),
        "run_kind": ("STRING", run_kind),
        "market_date": ("STRING", market_date),
        "execution_window": ("STRING", execution_window),
        "market_batch_id": ("STRING", market_batch_id),
        "execution_mode": ("STRING", execution_mode),
        "requested_live": ("BOOL", requested_live),
        "policy_name": ("STRING", policy_name),
        "policy_config": ("STRING", json.dumps(policy_config, sort_keys=True)),
        "policy_config_hash": ("STRING", policy_config_hash),
        "claim_token": ("STRING", claim_token),
    }
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, type_name, value)
            for name, (type_name, value) in values.items()
        ]
    )
    rows = list(client.query(query, job_config=config).result())
    return len(rows) == 1 and rows[0].claim_token == claim_token


def update_execution_run(
    decision_id: str,
    dry_run: bool,
    status: str,
    *,
    execution_result: object = None,
    dataset_id: str = "portfolio_analytics",
    account_id: str | None = None,
) -> None:
    if status not in EXECUTION_RUN_STATUSES:
        raise ValueError(f"Invalid execution run status: {status}")
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.execution_runs"
    query = f"""
        UPDATE `{table_id}`
        SET updated_at = CURRENT_TIMESTAMP(), status = @status, execution_result = @execution_result
        WHERE decision_id = @decision_id AND dry_run = @dry_run
          AND (@account_id IS NULL OR account_id=@account_id)
    """
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("execution_result", "STRING", json.dumps(execution_result, default=str) if execution_result is not None else None),
        bigquery.ScalarQueryParameter("decision_id", "STRING", decision_id),
        bigquery.ScalarQueryParameter("dry_run", "BOOL", dry_run),
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
    ])
    client.query(query, job_config=config).result()


def upsert_position_risk_state(
    *,
    account_suffix: str,
    ticker: str,
    entry_timestamp: datetime,
    last_session,
    highest_high: float,
    stop_price: float,
    atr: float,
    breached: bool,
    source: str,
    dataset_id: str = "portfolio_analytics",
    account_id: str | None = None,
    position_id: str | None = None,
    confirmation_count: int = 0,
    stop_state: str = "ACTIVE",
    policy_config_hash: str | None = None,
) -> None:
    """Persist a monotonic stop. A lower replacement is rejected by the MERGE."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.position_risk_state"
    existing_query = f"SELECT stop_price FROM `{table_id}` WHERE (@account_id IS NULL AND account_suffix=@account_suffix AND ticker=@ticker) OR (account_id=@account_id AND position_id=@position_id) LIMIT 1"
    lookup_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("account_suffix", "STRING", account_suffix),
        bigquery.ScalarQueryParameter("ticker", "STRING", ticker.upper()),
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
        bigquery.ScalarQueryParameter("position_id", "STRING", position_id),
    ])
    existing_rows = list(client.query(existing_query, job_config=lookup_config).result())
    if existing_rows and float(existing_rows[0].stop_price) > float(stop_price):
        raise ValueError("Persisted trailing stop cannot be lowered")
    query = f"""
        MERGE `{table_id}` target
        USING (SELECT @account_suffix account_suffix, @ticker ticker, @account_id account_id, @position_id position_id) source
        ON ((source.account_id IS NULL AND target.account_suffix = source.account_suffix AND target.ticker = source.ticker)
            OR (target.account_id = source.account_id AND target.position_id = source.position_id))
        WHEN MATCHED AND @stop_price >= target.stop_price THEN UPDATE SET
          last_session=@last_session, highest_high=GREATEST(target.highest_high, @highest_high),
          stop_price=@stop_price, atr=@atr, breached=@breached, updated_at=CURRENT_TIMESTAMP(), source=@source_name,
          confirmation_count=@confirmation_count, stop_state=@stop_state, policy_config_hash=@policy_config_hash
        WHEN NOT MATCHED THEN INSERT
          (account_suffix,ticker,entry_timestamp,last_session,highest_high,stop_price,atr,breached,updated_at,source,
           account_id,position_id,confirmation_count,stop_state,policy_config_hash)
        VALUES
          (@account_suffix,@ticker,@entry_timestamp,@last_session,@highest_high,@stop_price,@atr,@breached,CURRENT_TIMESTAMP(),@source_name,
           @account_id,@position_id,@confirmation_count,@stop_state,@policy_config_hash)
    """
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("account_suffix", "STRING", account_suffix),
        bigquery.ScalarQueryParameter("ticker", "STRING", ticker.upper()),
        bigquery.ScalarQueryParameter("entry_timestamp", "TIMESTAMP", entry_timestamp),
        bigquery.ScalarQueryParameter("last_session", "DATE", last_session),
        bigquery.ScalarQueryParameter("highest_high", "FLOAT", highest_high),
        bigquery.ScalarQueryParameter("stop_price", "FLOAT", stop_price),
        bigquery.ScalarQueryParameter("atr", "FLOAT", atr),
        bigquery.ScalarQueryParameter("breached", "BOOL", breached),
        bigquery.ScalarQueryParameter("source_name", "STRING", source),
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
        bigquery.ScalarQueryParameter("position_id", "STRING", position_id),
        bigquery.ScalarQueryParameter("confirmation_count", "INT64", confirmation_count),
        bigquery.ScalarQueryParameter("stop_state", "STRING", stop_state),
        bigquery.ScalarQueryParameter("policy_config_hash", "STRING", policy_config_hash),
    ])
    client.query(query, job_config=config).result()


def seed_account_registry(dataset_id: str = "portfolio_analytics") -> None:
    """Idempotently seed the real account and versioned ATR experiment cohorts."""
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.accounts"
    immediate = AtrPolicyConfig()
    confirmation = AtrPolicyConfig(
        atr_confirmation_closes=2,
        cancel_pending_exit_on_recovery=True,
    )
    rows = [
        {
            "account_id": "real-48661",
            "display_name": "Robinhood $100",
            "account_type": "REAL",
            "status": "ACTIVE",
            "is_dashboard_default": True,
            "broker_provider": "ROBINHOOD",
            "broker_account_ref": "ROBINHOOD_ACCOUNT_NUMBER",
            "broker_account_suffix": "48661",
            "live_execution_allowed": False,
            "initial_cash": 100.0,
            "base_currency": "USD",
            "policy_name": "atr-immediate-exit",
            "policy_version": "atr-v1",
            "policy_config": immediate.as_dict(),
            "policy_config_hash": policy_config_hash(immediate),
        },
        {
            "account_id": "exp-atr-immediate",
            "display_name": "ATR Immediate Exit",
            "account_type": "PAPER",
            "status": "ARCHIVED",
            "is_dashboard_default": False,
            "broker_provider": None,
            "broker_account_ref": None,
            "broker_account_suffix": None,
            "live_execution_allowed": False,
            "initial_cash": 10_000.0,
            "base_currency": "USD",
            "policy_name": "atr-immediate-exit",
            "policy_version": "atr-v1",
            "policy_config": immediate.as_dict(),
            "policy_config_hash": policy_config_hash(immediate),
        },
        {
            "account_id": "exp-atr-confirmation",
            "display_name": "ATR Two-Close Confirmation",
            "account_type": "PAPER",
            "status": "ARCHIVED",
            "is_dashboard_default": False,
            "broker_provider": None,
            "broker_account_ref": None,
            "broker_account_suffix": None,
            "live_execution_allowed": False,
            "initial_cash": 10_000.0,
            "base_currency": "USD",
            "policy_name": "atr-confirmed-exit",
            "policy_version": "atr-v1",
            "policy_config": confirmation.as_dict(),
            "policy_config_hash": policy_config_hash(confirmation),
        },
        {
            "account_id": "exp-broad-atr-immediate-v1",
            "display_name": "Broad Universe ATR Immediate v1",
            "account_type": "PAPER",
            "status": "ACTIVE",
            "is_dashboard_default": False,
            "broker_provider": None,
            "broker_account_ref": None,
            "broker_account_suffix": None,
            "live_execution_allowed": False,
            "initial_cash": 10_000.0,
            "base_currency": "USD",
            "policy_name": "broad-universe-atr-immediate-v1",
            "policy_version": "atr-v1",
            "policy_config": immediate.as_dict(),
            "policy_config_hash": policy_config_hash(immediate),
        },
        {
            "account_id": "exp-broad-atr-confirmation-v1",
            "display_name": "Broad Universe ATR Two-Close v1",
            "account_type": "PAPER",
            "status": "ACTIVE",
            "is_dashboard_default": False,
            "broker_provider": None,
            "broker_account_ref": None,
            "broker_account_suffix": None,
            "live_execution_allowed": False,
            "initial_cash": 10_000.0,
            "base_currency": "USD",
            "policy_name": "broad-universe-atr-confirmed-v1",
            "policy_version": "atr-v1",
            "policy_config": confirmation.as_dict(),
            "policy_config_hash": policy_config_hash(confirmation),
        },
    ]
    query = f"""
        MERGE `{table_id}` target
        USING (SELECT @account_id account_id) source
        ON target.account_id = source.account_id
        WHEN NOT MATCHED THEN INSERT (
          account_id, display_name, account_type, status, is_dashboard_default,
          broker_provider, broker_account_ref, broker_account_suffix,
          live_execution_allowed, initial_cash, base_currency, policy_name,
          policy_version, policy_config, policy_config_hash, created_at, updated_at
        ) VALUES (
          @account_id, @display_name, @account_type, @status,
          @is_dashboard_default, @broker_provider, @broker_account_ref,
          @broker_account_suffix, @live_execution_allowed, @initial_cash,
          @base_currency, @policy_name, @policy_version, PARSE_JSON(@policy_config),
          @policy_config_hash, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
        )
    """
    for row in rows:
        value = dict(row)
        value["policy_config"] = json.dumps(value["policy_config"], sort_keys=True)
        types = {
            "is_dashboard_default": "BOOL",
            "live_execution_allowed": "BOOL",
            "initial_cash": "FLOAT64",
        }
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    key, types.get(key, "STRING"), item
                )
                for key, item in value.items()
            ]
        )
        client.query(query, job_config=config).result()


def backfill_account_scope(dataset_id: str = "portfolio_analytics") -> None:
    """Idempotently attribute legacy rows without changing their historical meaning."""
    client = get_bigquery_client()
    project = client.project
    statements = [
        f"UPDATE `{project}.{dataset_id}.trade_history` SET account_id='real-48661', execution_mode=IF(COALESCE(dry_run, TRUE), 'REAL_DRY_RUN', 'LIVE') WHERE account_id IS NULL",
        f"UPDATE `{project}.{dataset_id}.portfolio_snapshot` SET account_id='real-48661', snapshot_type='BROKER_CONFIRMED' WHERE account_id IS NULL",
        f"UPDATE `{project}.{dataset_id}.execution_runs` SET account_id='real-48661', run_kind='EXECUTION', execution_window='close', execution_mode=IF(dry_run, 'REAL_DRY_RUN', 'LIVE'), requested_live=NOT dry_run WHERE account_id IS NULL",
        f"UPDATE `{project}.{dataset_id}.position_risk_state` SET account_id='real-48661', position_id=CONCAT('legacy-', LOWER(ticker)), confirmation_count=IF(breached, 1, 0), stop_state=IF(breached, 'EXIT_CONFIRMED', 'ACTIVE') WHERE account_id IS NULL",
        f"UPDATE `{project}.{dataset_id}.infrastructure_market_metrics` SET record_scope='LEGACY_COMBINED' WHERE record_scope IS NULL",
    ]
    for statement in statements:
        client.query(statement).result()


def list_accounts(
    *, active_only: bool = False, dataset_id: str = "portfolio_analytics"
) -> list[TradingAccount]:
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.accounts"
    where = "WHERE status = 'ACTIVE'" if active_only else ""
    rows = list(
        client.query(
            f"SELECT * FROM `{table_id}` {where} ORDER BY account_id"
        ).result()
    )
    accounts = [TradingAccount.from_row(row) for row in rows]
    defaults = [
        account
        for account in accounts
        if account.status.value == "ACTIVE"
        and account.account_type.value == "REAL"
        and account.is_dashboard_default
    ]
    if len(defaults) != 1:
        raise RuntimeError("Account registry must contain exactly one active default real account")
    return accounts


def get_account(account_id: str, dataset_id: str = "portfolio_analytics") -> TradingAccount:
    matches = [
        account
        for account in list_accounts(dataset_id=dataset_id)
        if account.account_id == account_id
    ]
    if len(matches) != 1:
        raise LookupError(f"Expected exactly one account row for {account_id!r}")
    return matches[0]


def get_latest_account_snapshot(
    account_id: str, dataset_id: str = "portfolio_analytics"
) -> dict[str, Any] | None:
    client = get_bigquery_client()
    table_id = f"{client.project}.{dataset_id}.portfolio_snapshot"
    query = f"""
        SELECT * FROM `{table_id}`
        WHERE account_id=@account_id
        ORDER BY timestamp DESC LIMIT 1
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("account_id", "STRING", account_id)]
    )
    rows = list(client.query(query, job_config=config).result())
    return dict(rows[0].items()) if rows else None


def get_latest_account_activity(
    account_id: str, dataset_id: str = "portfolio_analytics"
) -> dict[str, Any] | None:
    """Return the latest audited recommendation and its account-scoped fills."""
    client = get_bigquery_client()
    project = client.project
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
    ])
    runs = list(client.query(
        f"""
        SELECT decision_id, status, proposal, execution_mode, run_kind,
               created_at, updated_at
        FROM `{project}.{dataset_id}.execution_runs`
        WHERE account_id=@account_id
        ORDER BY updated_at DESC LIMIT 1
        """,
        job_config=config,
    ).result())
    if not runs:
        return None
    activity = dict(runs[0].items())
    proposal = activity.get("proposal") or "[]"
    if isinstance(proposal, str):
        proposal = json.loads(proposal)
    activity["recommendation"] = proposal if isinstance(proposal, list) else []
    trade_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("account_id", "STRING", account_id),
        bigquery.ScalarQueryParameter(
            "decision_id", "STRING", activity["decision_id"]
        ),
    ])
    activity["trades"] = [
        dict(row.items())
        for row in client.query(
            f"""
            SELECT ticker, action, amount_usd, requested_quantity,
                   filled_quantity, fill_price, order_status, execution_mode
            FROM `{project}.{dataset_id}.trade_history`
            WHERE account_id=@account_id AND decision_id=@decision_id
            ORDER BY timestamp, ticker
            """,
            job_config=trade_config,
        ).result()
    ]
    return activity


def recapitalize_paper_account(
    account: TradingAccount,
    *,
    target_equity: float,
    dataset_id: str = "portfolio_analytics",
) -> dict[str, Any]:
    """Add an auditable cash-capital snapshot without fabricating a market trade."""
    from app.paper_executor import (
        PaperHolding,
        PaperPortfolio,
        recapitalize_paper_portfolio,
    )

    if account.account_type.value != "PAPER":
        raise ValueError("Only paper accounts can be recapitalized")
    snapshot = get_latest_account_snapshot(account.account_id, dataset_id)
    if snapshot:
        raw_holdings = snapshot.get("holdings") or "[]"
        if isinstance(raw_holdings, str):
            raw_holdings = json.loads(raw_holdings)
        holdings = tuple(
            PaperHolding(
                str(item["symbol"]).upper(),
                float(item["shares"]),
                float(item["average_buy_price"]),
                float(item["current_price"]),
            )
            for item in raw_holdings
        )
        current = PaperPortfolio(float(snapshot["total_cash"]), holdings)
    else:
        current = PaperPortfolio(float(account.initial_cash), ())
    adjusted = recapitalize_paper_portfolio(current, target_equity)
    holdings_json = json.dumps(
        [
            {
                "symbol": item.symbol,
                "shares": item.shares,
                "average_buy_price": item.average_buy_price,
                "current_price": item.current_price,
                "equity": item.equity,
            }
            for item in adjusted.holdings
        ]
    )
    cost_basis = sum(
        item.shares * item.average_buy_price for item in adjusted.holdings
    )
    holdings_value = sum(item.equity for item in adjusted.holdings)
    unrealized = holdings_value - cost_basis
    unrealized_pct = unrealized / cost_basis * 100 if cost_basis else 0.0
    snapshot_id = f"{account.account_id}:capital:{float(target_equity):.2f}"
    client = get_bigquery_client()
    project = client.project
    query = f"""
      BEGIN TRANSACTION;
      UPDATE `{project}.{dataset_id}.accounts`
      SET initial_cash=@target_equity, updated_at=CURRENT_TIMESTAMP()
      WHERE account_id=@account_id AND account_type='PAPER';
      ASSERT @@row_count = 1 AS 'Expected exactly one paper account';
      INSERT INTO `{project}.{dataset_id}.portfolio_snapshot`
        (timestamp, account_number, total_equity, total_cash,
         unrealized_gain_loss, unrealized_gain_loss_percent, holdings,
         buying_power, summary, account_id, snapshot_id, snapshot_type,
         decision_id, market_batch_id, policy_config_hash)
      SELECT CURRENT_TIMESTAMP(), 'PAPER', @target_equity, @total_cash,
        @unrealized, @unrealized_pct, @holdings_json, @total_cash,
        'Paper capital contribution; trade history preserved', @account_id,
        @snapshot_id, 'PAPER_CAPITAL_ADJUSTMENT', NULL, NULL,
        @policy_config_hash
      FROM (SELECT 1)
      WHERE NOT EXISTS (
        SELECT 1 FROM `{project}.{dataset_id}.portfolio_snapshot`
        WHERE snapshot_id=@snapshot_id
      );
      COMMIT TRANSACTION;
    """
    config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("account_id", "STRING", account.account_id),
        bigquery.ScalarQueryParameter("target_equity", "FLOAT64", float(target_equity)),
        bigquery.ScalarQueryParameter("total_cash", "FLOAT64", adjusted.cash),
        bigquery.ScalarQueryParameter("unrealized", "FLOAT64", unrealized),
        bigquery.ScalarQueryParameter("unrealized_pct", "FLOAT64", unrealized_pct),
        bigquery.ScalarQueryParameter("holdings_json", "STRING", holdings_json),
        bigquery.ScalarQueryParameter("snapshot_id", "STRING", snapshot_id),
        bigquery.ScalarQueryParameter(
            "policy_config_hash", "STRING", account.policy_config_hash
        ),
    ])
    client.query(query, job_config=config).result()
    return {
        "account_id": account.account_id,
        "snapshot_id": snapshot_id,
        "total_equity": float(target_equity),
        "total_cash": adjusted.cash,
        "holdings_value": holdings_value,
    }


def commit_paper_execution(
    *,
    account: TradingAccount,
    decision_id: str,
    market_batch_id: str,
    result,
    summary: str | None = None,
    dataset_id: str = "portfolio_analytics",
) -> None:
    """Atomically commit idempotent paper fills, snapshot, and run completion."""
    if account.account_type.value != "PAPER":
        raise ValueError("commit_paper_execution accepts only paper accounts")
    client = get_bigquery_client()
    project = client.project
    fills = [
        {
            "trade_id": fill.trade_id,
            "ticker": fill.ticker,
            "side": fill.side,
            "shares": fill.shares,
            "fill_price": fill.fill_price,
            "amount_usd": fill.amount_usd,
            "fees_usd": fill.fees_usd,
            "slippage_usd": fill.slippage_usd,
            "action": "BUY" if fill.side == "buy" else "SELL",
            "policy_action": fill.action.value,
        }
        for fill in result.fills
    ]
    holdings = [
        {
            "symbol": holding.symbol,
            "shares": holding.shares,
            "average_buy_price": holding.average_buy_price,
            "current_price": holding.current_price,
            "equity": holding.equity,
        }
        for holding in result.portfolio.holdings
    ]
    holdings_value = sum(item["equity"] for item in holdings)
    cost_basis = sum(
        item["shares"] * item["average_buy_price"] for item in holdings
    )
    unrealized = holdings_value - cost_basis
    unrealized_pct = unrealized / cost_basis * 100 if cost_basis else 0.0
    query = f"""
      BEGIN TRANSACTION;
      INSERT INTO `{project}.{dataset_id}.trade_history`
        (ticker, action, amount_usd, timestamp, reasoning, dry_run, decision_id,
         order_status, requested_quantity, filled_quantity, account_id, trade_id,
         execution_mode, fill_price, fees_usd, slippage_usd, market_batch_id)
      SELECT
        JSON_VALUE(fill, '$.ticker'), JSON_VALUE(fill, '$.action'),
        CAST(JSON_VALUE(fill, '$.amount_usd') AS FLOAT64), CURRENT_TIMESTAMP(),
        'Deterministic persistent paper fill', TRUE, @decision_id, 'PAPER_FILLED',
        CAST(JSON_VALUE(fill, '$.shares') AS FLOAT64),
        CAST(JSON_VALUE(fill, '$.shares') AS FLOAT64), @account_id,
        JSON_VALUE(fill, '$.trade_id'), 'PAPER',
        CAST(JSON_VALUE(fill, '$.fill_price') AS FLOAT64),
        CAST(JSON_VALUE(fill, '$.fees_usd') AS FLOAT64),
        CAST(JSON_VALUE(fill, '$.slippage_usd') AS FLOAT64), @market_batch_id
      FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@fills_json))) fill
      WHERE NOT EXISTS (
        SELECT 1 FROM `{project}.{dataset_id}.trade_history` existing
        WHERE existing.trade_id = JSON_VALUE(fill, '$.trade_id')
      );
      INSERT INTO `{project}.{dataset_id}.portfolio_snapshot`
        (timestamp, account_number, total_equity, total_cash,
         unrealized_gain_loss, unrealized_gain_loss_percent, holdings,
         buying_power, summary, account_id, snapshot_id, snapshot_type,
         decision_id, market_batch_id, policy_config_hash)
      SELECT CURRENT_TIMESTAMP(), 'PAPER', @total_equity, @total_cash,
        @unrealized, @unrealized_pct, @holdings_json, @total_cash, @summary,
        @account_id, @snapshot_id, 'PAPER_COMMITTED', @decision_id,
        @market_batch_id, @policy_config_hash
      FROM (SELECT 1)
      WHERE NOT EXISTS (
        SELECT 1 FROM `{project}.{dataset_id}.portfolio_snapshot`
        WHERE snapshot_id=@snapshot_id
      );
      UPDATE `{project}.{dataset_id}.execution_runs`
      SET status='COMPLETED', updated_at=CURRENT_TIMESTAMP(),
          execution_result=@execution_result
      WHERE account_id=@account_id AND decision_id=@decision_id;
      UPDATE `{project}.{dataset_id}.position_risk_state`
      SET stop_state='POSITION_CLOSED', position_closed_at=CURRENT_TIMESTAMP(),
          updated_at=CURRENT_TIMESTAMP()
      WHERE account_id=@account_id AND ticker IN (
        SELECT JSON_VALUE(fill, '$.ticker')
        FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@fills_json))) fill
        WHERE JSON_VALUE(fill, '$.policy_action')='EXIT'
      ) AND stop_state != 'POSITION_CLOSED';
      COMMIT TRANSACTION;
    """
    params = [
        bigquery.ScalarQueryParameter("decision_id", "STRING", decision_id),
        bigquery.ScalarQueryParameter("account_id", "STRING", account.account_id),
        bigquery.ScalarQueryParameter("market_batch_id", "STRING", market_batch_id),
        bigquery.ScalarQueryParameter("fills_json", "STRING", json.dumps(fills)),
        bigquery.ScalarQueryParameter("holdings_json", "STRING", json.dumps(holdings)),
        bigquery.ScalarQueryParameter("total_equity", "FLOAT64", result.portfolio.total_equity),
        bigquery.ScalarQueryParameter("total_cash", "FLOAT64", result.portfolio.cash),
        bigquery.ScalarQueryParameter("unrealized", "FLOAT64", unrealized),
        bigquery.ScalarQueryParameter("unrealized_pct", "FLOAT64", unrealized_pct),
        bigquery.ScalarQueryParameter("summary", "STRING", _sanitize_string(summary)),
        bigquery.ScalarQueryParameter("snapshot_id", "STRING", result.snapshot_id),
        bigquery.ScalarQueryParameter("policy_config_hash", "STRING", account.policy_config_hash),
        bigquery.ScalarQueryParameter(
            "execution_result",
            "STRING",
            json.dumps({"paper_fills": fills, "snapshot_id": result.snapshot_id}),
        ),
    ]
    client.query(
        query, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result()
