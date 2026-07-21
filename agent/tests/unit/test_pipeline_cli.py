import pytest

from run_pipeline import _validate_args, build_parser


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
