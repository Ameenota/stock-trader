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
import pytest
from unittest.mock import MagicMock, patch
from google.cloud import bigquery
from app.tools.bigquery_service import (
    setup_bigquery,
    insert_sentiment,
    get_latest_signals,
    insert_trade_record,
)

@pytest.fixture
def mock_bq_client(mocker):
    """Fixture to mock BigQuery Client and its return values."""
    mock_client = MagicMock()
    mock_client.project = "test-project"
    
    # Mock get_bigquery_client to return our mock_client
    mocker.patch("app.tools.bigquery_service.get_bigquery_client", return_value=mock_client)
    return mock_client


def test_setup_bigquery(mock_bq_client):
    """Verifies that setup_bigquery creates the dataset and tables with the correct schema."""
    mock_bq_client.get_table.side_effect = Exception("not found")
    setup_bigquery(dataset_id="test_dataset")

    # Assert dataset was created
    mock_bq_client.create_dataset.assert_called_once()
    created_dataset = mock_bq_client.create_dataset.call_args[0][0]
    assert created_dataset.dataset_id == "test_dataset"
    assert created_dataset.location == "US"

    # Assert tables were created (3 tables)
    assert mock_bq_client.create_table.call_count == 3
    
    # Verify first table (infrastructure_market_metrics)
    sentiment_table = mock_bq_client.create_table.call_args_list[0][0][0]
    assert sentiment_table.table_id == "infrastructure_market_metrics"
    assert sentiment_table.dataset_id == "test_dataset"
    assert sentiment_table.project == "test-project"
    assert sentiment_table.schema[0].name == "ticker"
    assert sentiment_table.schema[0].field_type == "STRING"
    assert sentiment_table.schema[1].name == "raw_score"
    assert sentiment_table.schema[1].field_type == "FLOAT"
    assert sentiment_table.schema[4].name == "signal"
    assert sentiment_table.schema[4].field_type == "STRING"
    assert sentiment_table.schema[5].name == "timestamp"
    assert sentiment_table.schema[5].field_type == "TIMESTAMP"
    assert sentiment_table.schema[6].name == "raw_news"
    assert sentiment_table.schema[6].field_type == "STRING"
    assert sentiment_table.schema[7].name == "analyst_consensus"
    assert sentiment_table.schema[7].field_type == "STRING"
    assert sentiment_table.schema[8].name == "target_price"
    assert sentiment_table.schema[8].field_type == "FLOAT"
    assert sentiment_table.schema[9].name == "current_price"
    assert sentiment_table.schema[9].field_type == "FLOAT"
    assert sentiment_table.schema[10].name == "moving_average_20d"
    assert sentiment_table.schema[10].field_type == "FLOAT"
    assert sentiment_table.schema[11].name == "price_to_ma_ratio"
    assert sentiment_table.schema[11].field_type == "FLOAT"

    # Verify second table (trade_history)
    trade_table = mock_bq_client.create_table.call_args_list[1][0][0]
    assert trade_table.table_id == "trade_history"
    assert trade_table.dataset_id == "test_dataset"
    assert trade_table.project == "test-project"
    assert trade_table.schema[0].name == "ticker"
    assert trade_table.schema[0].field_type == "STRING"
    assert trade_table.schema[1].name == "action"
    assert trade_table.schema[1].field_type == "STRING"
    assert trade_table.schema[2].name == "amount_usd"
    assert trade_table.schema[2].field_type == "FLOAT"
    assert trade_table.schema[3].name == "timestamp"
    assert trade_table.schema[3].field_type == "TIMESTAMP"
    assert trade_table.schema[4].name == "reasoning"
    assert trade_table.schema[4].field_type == "STRING"
    assert trade_table.schema[5].name == "dry_run"
    assert trade_table.schema[5].field_type == "BOOLEAN"

    # Verify third table (portfolio_snapshot)
    snapshot_table = mock_bq_client.create_table.call_args_list[2][0][0]
    assert snapshot_table.table_id == "portfolio_snapshot"
    assert snapshot_table.dataset_id == "test_dataset"
    assert snapshot_table.project == "test-project"
    assert snapshot_table.schema[0].name == "timestamp"
    assert snapshot_table.schema[0].field_type == "TIMESTAMP"
    assert snapshot_table.schema[1].name == "account_number"
    assert snapshot_table.schema[1].field_type == "STRING"
    assert snapshot_table.schema[2].name == "total_equity"
    assert snapshot_table.schema[2].field_type == "FLOAT"
    assert snapshot_table.schema[3].name == "total_cash"
    assert snapshot_table.schema[3].field_type == "FLOAT"
    assert snapshot_table.schema[4].name == "unrealized_gain_loss"
    assert snapshot_table.schema[4].field_type == "FLOAT"
    assert snapshot_table.schema[5].name == "unrealized_gain_loss_percent"
    assert snapshot_table.schema[5].field_type == "FLOAT"
    assert snapshot_table.schema[6].name == "holdings"
    assert snapshot_table.schema[6].field_type == "STRING"


def test_insert_sentiment(mock_bq_client):
    """Verifies that insert_sentiment processes and submits rows correctly."""
    ranked_portfolio = [
        {
            "ticker": "NVDA",
            "raw_score": 0.8,
            "thesis": "Strong AI growth",
            "relative_rank": 10,
            "signal": "STRONG BUY",
            "raw_news": [{"title": "News 1", "summary": "Summary 1"}],
            "analyst_consensus": "buy",
            "target_price": 150.0,
            "current_price": 140.0,
            "moving_average_20d": 135.0,
            "price_to_ma_ratio": 1.037
        },
        {
            "ticker": "SMCI",
            "raw_score": -0.5,
            "thesis": "Cash flow issues",
            "relative_rank": 1,
            "signal": "LIQUIDATE",
            "raw_news": []
        }
    ]
    
    mock_job = MagicMock()
    mock_bq_client.load_table_from_json.return_value = mock_job

    # Run function specifying timestamp to ensure consistency
    timestamp_str = "2026-06-24T18:00:00Z"
    for item in ranked_portfolio:
        item["timestamp"] = timestamp_str

    insert_sentiment(ranked_portfolio, dataset_id="test_dataset")

    expected_table_id = "test-project.test_dataset.infrastructure_market_metrics"
    expected_rows = [
        {
            "ticker": "NVDA",
            "raw_score": 0.8,
            "thesis": "Strong AI growth",
            "relative_rank": 10,
            "signal": "STRONG BUY",
            "timestamp": timestamp_str,
            "raw_news": '[{"title": "News 1", "summary": "Summary 1"}]',
            "analyst_consensus": "buy",
            "target_price": 150.0,
            "current_price": 140.0,
            "moving_average_20d": 135.0,
            "price_to_ma_ratio": 1.037
        },
        {
            "ticker": "SMCI",
            "raw_score": -0.5,
            "thesis": "Cash flow issues",
            "relative_rank": 1,
            "signal": "LIQUIDATE",
            "timestamp": timestamp_str,
            "raw_news": "[]",
            "analyst_consensus": None,
            "target_price": None,
            "current_price": None,
            "moving_average_20d": None,
            "price_to_ma_ratio": None
        }
    ]

    mock_bq_client.load_table_from_json.assert_called_once()
    call_args = mock_bq_client.load_table_from_json.call_args
    assert call_args[0][0] == expected_rows
    assert call_args[0][1] == expected_table_id


def test_insert_sentiment_error(mock_bq_client):
    """Verifies that insert_sentiment raises a RuntimeError if the client returns insertion errors."""
    mock_bq_client.load_table_from_json.side_effect = Exception("some bigquery issue")

    with pytest.raises(RuntimeError, match="Failed to insert sentiment rows into BigQuery"):
        insert_sentiment([{"ticker": "NVDA", "raw_score": 0.8, "relative_rank": 10, "signal": "STRONG BUY"}])


def test_get_latest_signals(mock_bq_client):
    """Verifies that get_latest_signals formats the correct query job and parses results."""
    # Mocking rows returned from BigQuery
    row1 = MagicMock()
    row1.ticker = "NVDA"
    row1.raw_score = 0.8
    row1.thesis = "Bullish"
    row1.relative_rank = 10
    row1.signal = "STRONG BUY"
    row1.timestamp = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    row1.analyst_consensus = "buy"
    row1.target_price = 150.0
    row1.current_price = 140.0
    row1.moving_average_20d = 135.0
    row1.price_to_ma_ratio = 1.037

    row2 = MagicMock()
    row2.ticker = "SMCI"
    row2.raw_score = -0.6
    row2.thesis = "Bearish"
    row2.relative_rank = 1
    row2.signal = "LIQUIDATE"
    row2.timestamp = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    row2.analyst_consensus = None
    row2.target_price = None
    row2.current_price = None
    row2.moving_average_20d = None
    row2.price_to_ma_ratio = None

    mock_results = [row1, row2]
    
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = mock_results
    mock_bq_client.query.return_value = mock_query_job

    # Execute signals retrieval
    signals = get_latest_signals(dataset_id="test_dataset", date_str="2026-06-24")

    # Assert query execution and parameters
    mock_bq_client.query.assert_called_once()
    query_str = mock_bq_client.query.call_args[0][0]
    
    # Check that query targets the correct table and filters correctly
    assert "`test-project.test_dataset.infrastructure_market_metrics`" in query_str
    assert "WHERE DATE(timestamp) = @target_date" in query_str
    assert "signal IN ('STRONG BUY', 'LIQUIDATE')" in query_str

    job_config = mock_bq_client.query.call_args[1]["job_config"]
    assert job_config.query_parameters[0].name == "target_date"
    assert job_config.query_parameters[0].value == "2026-06-24"

    # Assert return structures
    assert len(signals) == 2
    assert signals[0]["ticker"] == "NVDA"
    assert signals[0]["signal"] == "STRONG BUY"
    assert signals[0]["timestamp"] == "2026-06-24T18:00:00+00:00"
    assert signals[0]["analyst_consensus"] == "buy"
    assert signals[0]["target_price"] == 150.0

    assert signals[1]["ticker"] == "SMCI"
    assert signals[1]["signal"] == "LIQUIDATE"
    assert signals[1]["timestamp"] == "2026-06-24T18:00:00+00:00"
    assert signals[1]["analyst_consensus"] is None
    assert signals[1]["target_price"] is None


def test_insert_trade_record(mock_bq_client):
    """Verifies that insert_trade_record formats and logs trade transactions correctly."""
    mock_job = MagicMock()
    mock_bq_client.load_table_from_json.return_value = mock_job

    # 1700000000 unix timestamp represents 2023-11-14T22:13:20+00:00
    insert_trade_record(
        ticker="TSM",
        action="STRONG BUY",
        amount_usd=50.0,
        timestamp=1700000000.0,
        dry_run=False,
        dataset_id="test_dataset"
    )

    expected_table_id = "test-project.test_dataset.trade_history"
    expected_rows = [
        {
            "ticker": "TSM",
            "action": "STRONG BUY",
            "amount_usd": 50.0,
            "timestamp": "2023-11-14T22:13:20+00:00",
            "reasoning": None,
            "dry_run": False
        }
    ]

    mock_bq_client.load_table_from_json.assert_called_once()
    call_args = mock_bq_client.load_table_from_json.call_args
    assert call_args[0][0] == expected_rows
    assert call_args[0][1] == expected_table_id


def test_insert_trade_record_with_reasoning(mock_bq_client):
    """Verifies that insert_trade_record formats and logs trade transactions with reasoning correctly."""
    mock_job = MagicMock()
    mock_bq_client.load_table_from_json.return_value = mock_job

    # 1700000000 unix timestamp represents 2023-11-14T22:13:20+00:00
    insert_trade_record(
        ticker="TSM",
        action="STRONG BUY",
        amount_usd=50.0,
        timestamp=1700000000.0,
        reasoning="Market demands buy",
        dry_run=False,
        dataset_id="test_dataset"
    )

    expected_table_id = "test-project.test_dataset.trade_history"
    expected_rows = [
        {
            "ticker": "TSM",
            "action": "STRONG BUY",
            "amount_usd": 50.0,
            "timestamp": "2023-11-14T22:13:20+00:00",
            "reasoning": "Market demands buy",
            "dry_run": False
        }
    ]

    mock_bq_client.load_table_from_json.assert_called_once()
    call_args = mock_bq_client.load_table_from_json.call_args
    assert call_args[0][0] == expected_rows
    assert call_args[0][1] == expected_table_id


def test_insert_trade_record_error(mock_bq_client):
    """Verifies that insert_trade_record raises a RuntimeError if client insertion fails."""
    mock_bq_client.load_table_from_json.side_effect = Exception("bigquery insertion failure")

    with pytest.raises(RuntimeError, match="Failed to insert trade record into BigQuery"):
        insert_trade_record(ticker="NVDA", action="STRONG BUY", amount_usd=100.0)


def test_setup_bigquery_updates_schema(mock_bq_client):
    """Verifies that setup_bigquery updates the schema if columns are missing."""
    # Simulate table existing, but missing 'analyst_consensus'
    mock_table = MagicMock()
    mock_table.schema = [
        bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("raw_score", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("thesis", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("relative_rank", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("signal", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("raw_news", "STRING", mode="NULLABLE"),
    ]
    mock_bq_client.get_table.return_value = mock_table

    setup_bigquery(dataset_id="test_dataset")

    # Assert update_table was called to append the new columns
    assert mock_bq_client.update_table.call_count >= 1
    updated_table = mock_bq_client.update_table.call_args[0][0]
    assert any(field.name == "analyst_consensus" for field in updated_table.schema)
    assert any(field.name == "target_price" for field in updated_table.schema)
