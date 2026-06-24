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
    setup_bigquery(dataset_id="test_dataset")

    # Assert dataset was created
    mock_bq_client.create_dataset.assert_called_once()
    created_dataset = mock_bq_client.create_dataset.call_args[0][0]
    assert created_dataset.dataset_id == "test_dataset"
    assert created_dataset.location == "US"

    # Assert tables were created (2 tables)
    assert mock_bq_client.create_table.call_count == 2
    
    # Verify first table (infrastructure_sentiment)
    sentiment_table = mock_bq_client.create_table.call_args_list[0][0][0]
    assert sentiment_table.table_id == "infrastructure_sentiment"
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


def test_insert_sentiment(mock_bq_client):
    """Verifies that insert_sentiment processes and submits rows correctly."""
    ranked_portfolio = [
        {"ticker": "NVDA", "raw_score": 0.8, "thesis": "Strong AI growth", "relative_rank": 10, "signal": "STRONG BUY"},
        {"ticker": "SMCI", "raw_score": -0.5, "thesis": "Cash flow issues", "relative_rank": 1, "signal": "LIQUIDATE"}
    ]
    
    mock_bq_client.insert_rows_json.return_value = []  # No errors

    # Run function specifying timestamp to ensure consistency
    timestamp_str = "2026-06-24T18:00:00Z"
    for item in ranked_portfolio:
        item["timestamp"] = timestamp_str

    insert_sentiment(ranked_portfolio, dataset_id="test_dataset")

    expected_table_id = "test-project.test_dataset.infrastructure_sentiment"
    expected_rows = [
        {
            "ticker": "NVDA",
            "raw_score": 0.8,
            "thesis": "Strong AI growth",
            "relative_rank": 10,
            "signal": "STRONG BUY",
            "timestamp": timestamp_str
        },
        {
            "ticker": "SMCI",
            "raw_score": -0.5,
            "thesis": "Cash flow issues",
            "relative_rank": 1,
            "signal": "LIQUIDATE",
            "timestamp": timestamp_str
        }
    ]

    mock_bq_client.insert_rows_json.assert_called_once_with(expected_table_id, expected_rows)


def test_insert_sentiment_error(mock_bq_client):
    """Verifies that insert_sentiment raises a RuntimeError if the client returns insertion errors."""
    mock_bq_client.insert_rows_json.return_value = [{"error": "some bigquery issue"}]

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

    row2 = MagicMock()
    row2.ticker = "SMCI"
    row2.raw_score = -0.6
    row2.thesis = "Bearish"
    row2.relative_rank = 1
    row2.signal = "LIQUIDATE"
    row2.timestamp = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)

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
    assert "`test-project.test_dataset.infrastructure_sentiment`" in query_str
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

    assert signals[1]["ticker"] == "SMCI"
    assert signals[1]["signal"] == "LIQUIDATE"
    assert signals[1]["timestamp"] == "2026-06-24T18:00:00+00:00"


def test_insert_trade_record(mock_bq_client):
    """Verifies that insert_trade_record formats and logs trade transactions correctly."""
    mock_bq_client.insert_rows_json.return_value = [] # No errors

    # 1700000000 unix timestamp represents 2023-11-14T22:13:20+00:00
    insert_trade_record(
        ticker="TSM",
        action="STRONG BUY",
        amount_usd=50.0,
        timestamp=1700000000.0,
        dataset_id="test_dataset"
    )

    expected_table_id = "test-project.test_dataset.trade_history"
    expected_rows = [
        {
            "ticker": "TSM",
            "action": "STRONG BUY",
            "amount_usd": 50.0,
            "timestamp": "2023-11-14T22:13:20+00:00"
        }
    ]

    mock_bq_client.insert_rows_json.assert_called_once_with(expected_table_id, expected_rows)


def test_insert_trade_record_error(mock_bq_client):
    """Verifies that insert_trade_record raises a RuntimeError if client insertion fails."""
    mock_bq_client.insert_rows_json.return_value = [{"error": "bigquery insertion failure"}]

    with pytest.raises(RuntimeError, match="Failed to insert trade record into BigQuery"):
        insert_trade_record(ticker="NVDA", action="STRONG BUY", amount_usd=100.0)
