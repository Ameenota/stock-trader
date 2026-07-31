"""Server-side data access for the public portfolio dashboard.

Cloud Run supplies Application Default Credentials for the service account attached
to the dashboard service. Nothing in this module exposes credentials to the browser.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, TypeVar, cast

import pandas as pd
import yfinance as yf
from google.cloud import bigquery

os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

DATASET_ID = "portfolio_analytics"
CACHE_TTL_SECONDS = 3600

F = TypeVar("F", bound=Callable[..., Any])
_cache_lock = threading.RLock()
_cache: dict[tuple[str, tuple[Any, ...]], tuple[float, Any]] = {}


def ttl_cache(ttl_seconds: int = CACHE_TTL_SECONDS) -> Callable[[F], F]:
    """Small process-local TTL cache suitable for Cloud Run dashboard reads."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any) -> Any:
            key = (func.__name__, args)
            now = time.monotonic()
            with _cache_lock:
                cached = _cache.get(key)
                if cached and now - cached[0] < ttl_seconds:
                    return cached[1]
            value = func(*args)
            with _cache_lock:
                _cache[key] = (now, value)
            return value

        return cast(F, wrapper)

    return decorator


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


@ttl_cache()
def get_bq_client() -> bigquery.Client:
    return bigquery.Client()


def _client_context() -> tuple[bigquery.Client, str, str]:
    client = get_bq_client()
    return client, client.project, DATASET_ID


@ttl_cache()
def load_dashboard_account_id() -> str:
    client, project, dataset = _client_context()
    rows = list(
        client.query(
            f"""
            SELECT account_id FROM `{project}.{dataset}.accounts`
            WHERE account_type='REAL' AND status='ACTIVE'
              AND is_dashboard_default=TRUE
            """
        ).result()
    )
    if len(rows) != 1:
        raise RuntimeError(
            "Expected exactly one active default real account; refusing a global fallback"
        )
    return rows[0].account_id


def _account_parameter(account_id: str) -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", account_id)
        ]
    )


@ttl_cache()
def load_latest_snapshot(account_id: str) -> dict[str, Any]:
    client, project, dataset = _client_context()
    rows = list(
        client.query(
            f"""
            SELECT timestamp, account_number, total_equity, total_cash,
                   buying_power, unrealized_gain_loss,
                   unrealized_gain_loss_percent, holdings, summary
            FROM `{project}.{dataset}.portfolio_snapshot`
            WHERE account_id = @account_id
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            job_config=_account_parameter(account_id),
        ).result()
    )
    if not rows:
        return {
            "timestamp": datetime.now(timezone.utc),
            "account_number": "••••N/A",
            "total_equity": 100.0,
            "total_cash": 100.0,
            "buying_power": 100.0,
            "unrealized_gain_loss": 0.0,
            "unrealized_gain_loss_percent": 0.0,
            "holdings": [],
            "summary": None,
        }

    row = rows[0]
    buying_power = getattr(row, "buying_power", None)
    return {
        "timestamp": row.timestamp,
        "account_number": row.account_number,
        "total_equity": float(row.total_equity),
        "total_cash": float(row.total_cash),
        "buying_power": float(
            buying_power if buying_power is not None else row.total_cash
        ),
        "unrealized_gain_loss": float(row.unrealized_gain_loss),
        "unrealized_gain_loss_percent": float(row.unrealized_gain_loss_percent),
        "holdings": json.loads(row.holdings) if row.holdings else [],
        "summary": getattr(row, "summary", None),
    }


@ttl_cache()
def load_latest_recommendations(account_id: str) -> pd.DataFrame:
    client, project, dataset = _client_context()
    return client.query(
        f"""
        SELECT ticker, raw_score, relative_rank, signal, current_price,
               moving_average_20d, analyst_consensus, thesis, timestamp,
               target_weight, rsi, macd, macd_signal, drawdown_pct,
               sentiment_ewma, sentiment_volatility, forward_pe
        FROM `{project}.{dataset}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp)
            FROM `{project}.{dataset}.infrastructure_market_metrics`
            WHERE account_id = @account_id AND record_scope='ACCOUNT_DECISION'
        )
          AND account_id = @account_id
          AND record_scope='ACCOUNT_DECISION'
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
          AND signal != 'FILTERED'
        ORDER BY relative_rank DESC
        """,
        job_config=_account_parameter(account_id),
    ).to_dataframe()


@ttl_cache()
def load_latest_graveyard(account_id: str) -> pd.DataFrame:
    client, project, dataset = _client_context()
    return client.query(
        f"""
        SELECT ticker, current_price, moving_average_20d AS sma_50,
               price_to_ma_ratio AS momentum, thesis, timestamp
        FROM `{project}.{dataset}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp)
            FROM `{project}.{dataset}.infrastructure_market_metrics`
            WHERE account_id = @account_id AND record_scope='ACCOUNT_DECISION'
        )
          AND account_id = @account_id
          AND record_scope='ACCOUNT_DECISION'
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
          AND signal = 'FILTERED'
        ORDER BY ticker ASC
        """,
        job_config=_account_parameter(account_id),
    ).to_dataframe()


@ttl_cache()
def load_latest_news_headlines() -> list[str]:
    client, project, dataset = _client_context()
    rows = client.query(
        f"""
        SELECT raw_news
        FROM `{project}.{dataset}.infrastructure_market_metrics`
        WHERE timestamp = (
            SELECT MAX(timestamp)
            FROM `{project}.{dataset}.infrastructure_market_metrics`
            WHERE record_scope IN ('MARKET_INPUT', 'LEGACY_COMBINED')
        )
          AND record_scope IN ('MARKET_INPUT', 'LEGACY_COMBINED')
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
          AND signal != 'FILTERED'
          AND raw_news IS NOT NULL
        """
    ).result()
    headlines: list[str] = []
    for row in rows:
        try:
            news_items = json.loads(row.raw_news)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(news_items, list):
            headlines.extend(
                str(item["title"]).strip()
                for item in news_items
                if isinstance(item, dict) and item.get("title")
            )
    return headlines


@ttl_cache()
def load_trade_history(account_id: str) -> pd.DataFrame:
    client, project, dataset = _client_context()
    return client.query(
        f"""
        SELECT timestamp, ticker, action, amount_usd, reasoning,
               COALESCE(dry_run, TRUE) AS dry_run
        FROM `{project}.{dataset}.trade_history`
        WHERE account_id = @account_id
        ORDER BY timestamp DESC
        """,
        job_config=_account_parameter(account_id),
    ).to_dataframe()


@ttl_cache()
def load_portfolio_history(account_id: str) -> pd.DataFrame:
    client, project, dataset = _client_context()
    frame = client.query(
        f"""
        SELECT DATE(timestamp) AS date, total_equity
        FROM `{project}.{dataset}.portfolio_snapshot`
        WHERE account_id = @account_id
        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY DATE(timestamp) ORDER BY timestamp DESC
        ) = 1
        ORDER BY date ASC
        """,
        job_config=_account_parameter(account_id),
    ).to_dataframe()
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


@ttl_cache()
def fetch_spy_history(start_str: str, end_str: str) -> pd.DataFrame:
    try:
        history = yf.Ticker("SPY").history(start=start_str, end=end_str)
        if not history.empty:
            history = history.reset_index()
            history["date"] = pd.to_datetime(history["Date"]).dt.date
            return history[["date", "Close"]].rename(columns={"Close": "SPY"})
    except Exception:
        pass
    return pd.DataFrame()


@dataclass
class DashboardData:
    snapshot: dict[str, Any]
    portfolio_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    recommendations: pd.DataFrame = field(default_factory=pd.DataFrame)
    graveyard: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    headlines: list[str] = field(default_factory=list)


def load_dashboard_data(*, force_refresh: bool = False) -> DashboardData:
    if force_refresh:
        clear_cache()
    account_id = load_dashboard_account_id()
    return DashboardData(
        snapshot=load_latest_snapshot(account_id),
        portfolio_history=load_portfolio_history(account_id),
        recommendations=load_latest_recommendations(account_id),
        graveyard=load_latest_graveyard(account_id),
        trades=load_trade_history(account_id),
        headlines=load_latest_news_headlines(),
    )
