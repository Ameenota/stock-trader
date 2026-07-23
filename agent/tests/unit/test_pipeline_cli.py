from types import SimpleNamespace
from unittest.mock import patch

import pytest

from run_pipeline import _required_account_tickers, _validate_args, build_parser


def test_cli_requires_exactly_one_account_selector():
    parser = build_parser()
    args = parser.parse_args([])
    with pytest.raises(SystemExit):
        _validate_args(parser, args)
    with pytest.raises(SystemExit):
        parser.parse_args(["--account", "one", "--all-accounts"])


def test_installed_cron_shape_parses():
    parser = build_parser()
    args = parser.parse_args(["--all-accounts", "--run-kind", "execution"])
    _validate_args(parser, args)
    assert args.all_accounts is True
    assert args.run_kind == "execution"


def test_list_accounts_rejects_selector():
    parser = build_parser()
    args = parser.parse_args(["--list-accounts", "--account", "real-48661"])
    with pytest.raises(SystemExit):
        _validate_args(parser, args)


@patch("run_pipeline.get_latest_portfolio_holdings")
def test_required_account_tickers_unions_selected_account_holdings(mock_holdings):
    mock_holdings.side_effect = lambda *, account_id, dataset_id: {
        "real-48661": ["MU"],
        "exp-atr-confirmation": ["META"],
        "exp-atr-immediate": ["meta"],
    }[account_id]
    accounts = [
        SimpleNamespace(account_id="real-48661"),
        SimpleNamespace(account_id="exp-atr-confirmation"),
        SimpleNamespace(account_id="exp-atr-immediate"),
    ]

    assert _required_account_tickers(accounts, "test_dataset") == ["META", "MU"]
