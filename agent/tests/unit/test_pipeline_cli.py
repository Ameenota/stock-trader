from types import SimpleNamespace
from unittest.mock import patch

import pytest

from run_pipeline import (
    _required_account_tickers,
    _resolve_available_accounts,
    _validate_args,
    build_parser,
    ping_uptime_kuma,
)


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
        "exp-broad-atr-confirmation-v1": ["META"],
        "exp-broad-atr-immediate-v1": ["meta"],
    }[account_id]
    accounts = [
        SimpleNamespace(account_id="real-48661"),
        SimpleNamespace(account_id="exp-broad-atr-confirmation-v1"),
        SimpleNamespace(account_id="exp-broad-atr-immediate-v1"),
    ]

    assert _required_account_tickers(accounts, "test_dataset") == ["META", "MU"]


@patch("run_pipeline.list_accounts")
def test_resolve_available_accounts_uses_only_active_registry_rows(mock_list_accounts):
    real = SimpleNamespace(account_id="real-48661")
    paper = SimpleNamespace(account_id="paper-active")
    mock_list_accounts.return_value = [real, paper]

    assert _resolve_available_accounts(
        selected_account_id=None, all_accounts=True, dataset_id="test_dataset"
    ) == [real, paper]
    assert _resolve_available_accounts(
        selected_account_id="paper-active",
        all_accounts=False,
        dataset_id="test_dataset",
    ) == [paper]
    with pytest.raises(LookupError, match="active account row"):
        _resolve_available_accounts(
            selected_account_id="archived",
            all_accounts=False,
            dataset_id="test_dataset",
        )
    assert all(
        call.kwargs == {"active_only": True, "dataset_id": "test_dataset"}
        for call in mock_list_accounts.call_args_list
    )


@patch.dict("os.environ", {"UPTIME_KUMA": "http://uptime-kuma.test/push"}, clear=False)
@patch("run_pipeline.urlopen")
def test_ping_uptime_kuma_after_success(mock_urlopen):
    assert ping_uptime_kuma() is True
    mock_urlopen.assert_called_once_with(
        "http://uptime-kuma.test/push",
        timeout=10,
    )


@patch.dict("os.environ", {}, clear=True)
@patch("run_pipeline.urlopen")
def test_ping_uptime_kuma_requires_configuration(mock_urlopen):
    assert ping_uptime_kuma() is False
    mock_urlopen.assert_not_called()


@patch.dict("os.environ", {"UPTIME_KUMA": "http://uptime-kuma.test/push"}, clear=False)
@patch("run_pipeline.urlopen", side_effect=OSError("offline"))
def test_ping_uptime_kuma_reports_network_failure(mock_urlopen):
    assert ping_uptime_kuma() is False
