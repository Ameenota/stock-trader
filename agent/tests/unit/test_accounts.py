import pytest

from app.accounts import (
    AccountType,
    AtrPolicyConfig,
    ExecutionMode,
    TradingAccount,
    derive_execution_mode,
    policy_config_hash,
    preflight_accounts,
)


def row(*, account_id="paper-one", account_type="PAPER", config=None, **changes):
    config = config or AtrPolicyConfig()
    values = {
        "account_id": account_id,
        "display_name": "Paper One",
        "account_type": account_type,
        "status": "ACTIVE",
        "is_dashboard_default": False,
        "broker_provider": None,
        "broker_account_ref": None,
        "broker_account_suffix": None,
        "live_execution_allowed": False,
        "initial_cash": 100.0,
        "base_currency": "USD",
        "policy_name": "atr",
        "policy_version": "atr-v1",
        "policy_config": config.as_dict(),
        "policy_config_hash": policy_config_hash(config),
    }
    values.update(changes)
    return values


def test_paper_account_parses_and_derives_paper_mode():
    account = TradingAccount.from_row(row())
    assert account.account_type is AccountType.PAPER
    assert derive_execution_mode(account, skip_live_trades=True) is ExecutionMode.PAPER


def test_paper_live_request_fails_closed():
    account = TradingAccount.from_row(row())
    with pytest.raises(RuntimeError, match="Safety preflight"):
        derive_execution_mode(account, skip_live_trades=False)


def test_paper_broker_binding_and_hash_mismatch_are_rejected():
    with pytest.raises(ValueError, match="broker bindings"):
        TradingAccount.from_row(row(broker_provider="ROBINHOOD"))
    with pytest.raises(ValueError, match="hash"):
        TradingAccount.from_row(row(policy_config_hash="0" * 64))


def test_policy_config_rejects_unknown_keys_and_bad_bounds():
    with pytest.raises(ValueError, match="unknown keys"):
        AtrPolicyConfig.from_mapping({**AtrPolicyConfig().as_dict(), "x": 1})
    with pytest.raises(ValueError, match="between 1 and 5"):
        AtrPolicyConfig.from_mapping(
            {**AtrPolicyConfig().as_dict(), "atr_confirmation_closes": 6}
        )


def test_all_account_preflight_rejects_set_before_processing():
    paper = TradingAccount.from_row(row())
    real = TradingAccount.from_row(
        row(
            account_id="real-48661",
            account_type="REAL",
            display_name="Real",
            broker_provider="ROBINHOOD",
            broker_account_ref="ROBINHOOD_ACCOUNT_NUMBER",
            broker_account_suffix="48661",
        )
    )
    with pytest.raises(RuntimeError, match="paper account"):
        preflight_accounts([real, paper], skip_live_trades=False)
