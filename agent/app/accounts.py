"""Account registry models and fail-closed execution-mode selection."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


ACCOUNT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SUPPORTED_POLICY_VERSION = "atr-v1"


class AccountType(StrEnum):
    REAL = "REAL"
    PAPER = "PAPER"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class ExecutionMode(StrEnum):
    LIVE = "LIVE"
    REAL_DRY_RUN = "REAL_DRY_RUN"
    PAPER = "PAPER"


class RunKind(StrEnum):
    ADVISORY = "ADVISORY"
    EXECUTION = "EXECUTION"


@dataclass(frozen=True)
class AtrPolicyConfig:
    atr_period: int = 14
    atr_multiplier: float = 3.0
    atr_confirmation_closes: int = 1
    cancel_pending_exit_on_recovery: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "AtrPolicyConfig":
        expected = {
            "atr_period",
            "atr_multiplier",
            "atr_confirmation_closes",
            "cancel_pending_exit_on_recovery",
        }
        unknown = set(raw) - expected
        missing = expected - set(raw)
        if unknown or missing:
            detail = []
            if unknown:
                detail.append(f"unknown keys: {', '.join(sorted(unknown))}")
            if missing:
                detail.append(f"missing keys: {', '.join(sorted(missing))}")
            raise ValueError("Invalid policy_config (" + "; ".join(detail) + ")")
        period = raw["atr_period"]
        closes = raw["atr_confirmation_closes"]
        multiplier = raw["atr_multiplier"]
        recovery = raw["cancel_pending_exit_on_recovery"]
        if isinstance(period, bool) or not isinstance(period, int) or not 5 <= period <= 100:
            raise ValueError("atr_period must be an integer between 5 and 100")
        if isinstance(closes, bool) or not isinstance(closes, int) or not 1 <= closes <= 5:
            raise ValueError("atr_confirmation_closes must be an integer between 1 and 5")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
            raise ValueError("atr_multiplier must be numeric")
        multiplier = float(multiplier)
        if not math.isfinite(multiplier) or not 0.5 <= multiplier <= 10.0:
            raise ValueError("atr_multiplier must be finite and between 0.5 and 10.0")
        if type(recovery) is not bool:
            raise ValueError("cancel_pending_exit_on_recovery must be boolean")
        return cls(period, multiplier, closes, recovery)

    def as_dict(self) -> dict[str, Any]:
        return {
            "atr_period": self.atr_period,
            "atr_multiplier": self.atr_multiplier,
            "atr_confirmation_closes": self.atr_confirmation_closes,
            "cancel_pending_exit_on_recovery": self.cancel_pending_exit_on_recovery,
        }


def canonical_policy_json(config: Mapping[str, Any] | AtrPolicyConfig) -> str:
    value = config.as_dict() if isinstance(config, AtrPolicyConfig) else dict(config)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def policy_config_hash(config: Mapping[str, Any] | AtrPolicyConfig) -> str:
    return hashlib.sha256(canonical_policy_json(config).encode()).hexdigest()


@dataclass(frozen=True)
class TradingAccount:
    account_id: str
    display_name: str
    account_type: AccountType
    status: AccountStatus
    is_dashboard_default: bool
    broker_provider: str | None
    broker_account_ref: str | None
    broker_account_suffix: str | None
    live_execution_allowed: bool
    initial_cash: float
    base_currency: str
    policy_name: str
    policy_version: str
    policy_config: AtrPolicyConfig
    policy_config_hash: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Any) -> "TradingAccount":
        def value(name: str) -> Any:
            if isinstance(row, Mapping):
                return row.get(name)
            return getattr(row, name, None)

        account_id = str(value("account_id") or "").strip()
        if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
            raise ValueError("Invalid account_id")
        display_name = str(value("display_name") or "").strip()
        if not display_name:
            raise ValueError("display_name must not be empty")
        try:
            account_type = AccountType(str(value("account_type") or "").upper())
            status = AccountStatus(str(value("status") or "").upper())
        except ValueError as exc:
            raise ValueError("Unknown account type or status") from exc
        policy_version = str(value("policy_version") or "").strip()
        if policy_version != SUPPORTED_POLICY_VERSION:
            raise ValueError(f"Unsupported policy_version: {policy_version}")
        raw_config = value("policy_config")
        if isinstance(raw_config, str):
            raw_config = json.loads(raw_config)
        if not isinstance(raw_config, Mapping):
            raise ValueError("policy_config must be a JSON object")
        config = AtrPolicyConfig.from_mapping(raw_config)
        expected_hash = policy_config_hash(config)
        supplied_hash = str(value("policy_config_hash") or "").strip().lower()
        if supplied_hash != expected_hash:
            raise ValueError("policy_config_hash does not match policy_config")
        initial_cash = float(value("initial_cash"))
        if not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("initial_cash must be finite and positive")
        broker_provider = value("broker_provider") or None
        broker_ref = value("broker_account_ref") or None
        broker_suffix = value("broker_account_suffix") or None
        live_allowed = bool(value("live_execution_allowed"))
        if account_type is AccountType.PAPER:
            if any((broker_provider, broker_ref, broker_suffix)):
                raise ValueError("Paper accounts cannot have broker bindings")
            if live_allowed:
                raise ValueError("Paper accounts cannot allow live execution")
        elif not all((broker_provider, broker_ref, broker_suffix)):
            raise ValueError("Real accounts require broker metadata")
        base_currency = str(value("base_currency") or "").upper()
        if base_currency != "USD":
            raise ValueError("Only USD accounts are supported")
        policy_name = str(value("policy_name") or "").strip()
        if not policy_name:
            raise ValueError("policy_name must not be empty")
        dashboard_default = bool(value("is_dashboard_default"))
        if dashboard_default and account_type is not AccountType.REAL:
            raise ValueError("Only real accounts may be the dashboard default")
        if account_type is AccountType.REAL and str(broker_provider).upper() != "ROBINHOOD":
            raise ValueError("Unsupported broker provider")
        return cls(
            account_id=account_id,
            display_name=display_name,
            account_type=account_type,
            status=status,
            is_dashboard_default=dashboard_default,
            broker_provider=str(broker_provider) if broker_provider else None,
            broker_account_ref=str(broker_ref) if broker_ref else None,
            broker_account_suffix=str(broker_suffix) if broker_suffix else None,
            live_execution_allowed=live_allowed,
            initial_cash=initial_cash,
            base_currency=base_currency,
            policy_name=policy_name,
            policy_version=policy_version,
            policy_config=config,
            policy_config_hash=expected_hash,
        )


@dataclass(frozen=True)
class AccountRunContext:
    account: TradingAccount
    run_kind: RunKind
    execution_mode: ExecutionMode
    requested_live: bool
    market_batch_id: str
    suppress_account_notification: bool = False


def derive_execution_mode(account: TradingAccount, *, skip_live_trades: bool) -> ExecutionMode:
    if account.status is not AccountStatus.ACTIVE:
        raise ValueError(f"Account {account.account_id} is not active")
    if account.account_type is AccountType.PAPER:
        if not skip_live_trades:
            raise RuntimeError(
                f"Safety preflight rejected paper account {account.account_id} while live trades were requested"
            )
        return ExecutionMode.PAPER
    if skip_live_trades:
        return ExecutionMode.REAL_DRY_RUN
    if not account.live_execution_allowed:
        raise RuntimeError(f"Live execution is disabled for account {account.account_id}")
    return ExecutionMode.LIVE


def preflight_accounts(accounts: list[TradingAccount], *, skip_live_trades: bool) -> Mapping[str, ExecutionMode]:
    if not accounts:
        raise ValueError("No active accounts selected")
    if len({account.account_id for account in accounts}) != len(accounts):
        raise ValueError("Duplicate account_id in selected account set")
    if not skip_live_trades:
        paper = next(
            (account for account in accounts if account.account_type is AccountType.PAPER),
            None,
        )
        if paper:
            raise RuntimeError(
                f"Safety preflight rejected paper account {paper.account_id} while live trades were requested"
            )
    modes = {
        account.account_id: derive_execution_mode(
            account, skip_live_trades=skip_live_trades
        )
        for account in accounts
    }
    return MappingProxyType(modes)
