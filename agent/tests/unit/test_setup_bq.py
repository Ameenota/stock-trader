from unittest.mock import call, patch

from setup_bq import setup


@patch("setup_bq.backfill_account_scope")
@patch("setup_bq.seed_account_registry")
@patch("setup_bq.setup_bigquery")
def test_setup_runs_provisioning_in_order(mock_setup, mock_seed, mock_backfill):
    manager = type(mock_setup)()
    manager.attach_mock(mock_setup, "setup")
    manager.attach_mock(mock_seed, "seed")
    manager.attach_mock(mock_backfill, "backfill")

    setup(dataset_id="test_dataset")

    assert manager.mock_calls == [
        call.setup(dataset_id="test_dataset"),
        call.seed(dataset_id="test_dataset"),
        call.backfill(dataset_id="test_dataset"),
    ]
