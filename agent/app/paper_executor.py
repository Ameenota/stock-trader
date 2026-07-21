"""Pure persistent-paper portfolio math; this module has no broker dependency."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from app.trading_policy import TradeAction, ValidatedExecutionPlan


@dataclass(frozen=True)
class PaperHolding:
    symbol: str
    shares: float
    average_buy_price: float
    current_price: float

    @property
    def equity(self) -> float:
        return self.shares * self.current_price


@dataclass(frozen=True)
class PaperPortfolio:
    cash: float
    holdings: tuple[PaperHolding, ...]

    @property
    def total_equity(self) -> float:
        return self.cash + sum(item.equity for item in self.holdings)


@dataclass(frozen=True)
class PaperFill:
    trade_id: str
    ticker: str
    side: str
    shares: float
    fill_price: float
    amount_usd: float
    fees_usd: float
    slippage_usd: float
    action: TradeAction


@dataclass(frozen=True)
class PaperExecutionResult:
    portfolio: PaperPortfolio
    fills: tuple[PaperFill, ...]
    snapshot_id: str


def _finite_positive(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def execute_paper_rebalance(
    *,
    plan: ValidatedExecutionPlan,
    portfolio: PaperPortfolio,
    prices: Mapping[str, float],
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> PaperExecutionResult:
    if plan.execution_mode != "PAPER" or not plan.account_id:
        raise ValueError("PaperExecutor requires an account-scoped PAPER plan")
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("Paper execution costs must be non-negative")
    holdings = {item.symbol.upper(): item for item in portfolio.holdings}
    required = set(plan.allocations) | set(holdings)
    normalized_prices = {
        ticker.upper(): _finite_positive(price, f"{ticker}.price")
        for ticker, price in prices.items()
    }
    missing = required - set(normalized_prices)
    if missing:
        raise ValueError(f"Missing paper prices for: {', '.join(sorted(missing))}")
    total_equity = portfolio.cash + sum(
        item.shares * normalized_prices[ticker] for ticker, item in holdings.items()
    )
    if total_equity <= 0:
        raise ValueError("Paper portfolio equity must be positive")

    requests: list[tuple[str, str, float, TradeAction]] = []
    for ticker in sorted(required):
        current = holdings[ticker].shares * normalized_prices[ticker] if ticker in holdings else 0.0
        target = plan.allocations.get(ticker, 0.0) * total_equity
        delta = target - current
        if current and target and abs(delta / total_equity) <= 0.03:
            continue
        if delta < -0.01:
            action = TradeAction.EXIT if target <= 0 else TradeAction.REDUCE
            requests.append((ticker, "sell", min(-delta, current), action))
        elif delta > 0.01:
            action = TradeAction.ENTER if current == 0 else TradeAction.ADD
            requests.append((ticker, "buy", delta, action))
    if any(side == "sell" for _, side, _, _ in requests):
        requests = [request for request in requests if request[1] == "sell"]

    cash = float(portfolio.cash)
    mutable = {
        ticker: [item.shares, item.average_buy_price]
        for ticker, item in holdings.items()
    }
    fills: list[PaperFill] = []
    for sequence, (ticker, side, notional, action) in enumerate(requests):
        reference_price = normalized_prices[ticker]
        direction = 1.0 if side == "buy" else -1.0
        fill_price = reference_price * (1 + direction * slippage_bps / 10_000)
        shares = notional / fill_price
        if side == "sell":
            shares = min(shares, mutable[ticker][0])
        gross = shares * fill_price
        fees = gross * fee_bps / 10_000
        slippage = abs(fill_price - reference_price) * shares
        if side == "buy":
            if gross + fees > cash + 1e-9:
                raise ValueError("Insufficient paper cash")
            old_shares, old_average = mutable.get(ticker, [0.0, 0.0])
            new_shares = old_shares + shares
            average = (
                (old_shares * old_average + gross + fees) / new_shares
                if new_shares
                else 0.0
            )
            mutable[ticker] = [new_shares, average]
            cash -= gross + fees
        else:
            old_shares, average = mutable[ticker]
            remaining = max(0.0, old_shares - shares)
            cash += gross - fees
            if remaining <= 1e-10:
                mutable.pop(ticker)
            else:
                mutable[ticker] = [remaining, average]
        trade_seed = f"{plan.decision_id}:{ticker}:{side}:{sequence}"
        fills.append(
            PaperFill(
                hashlib.sha256(trade_seed.encode()).hexdigest(),
                ticker,
                side,
                shares,
                fill_price,
                gross,
                fees,
                slippage,
                action,
            )
        )
    result_holdings = tuple(
        PaperHolding(ticker, values[0], values[1], normalized_prices[ticker])
        for ticker, values in sorted(mutable.items())
    )
    snapshot_id = hashlib.sha256(
        f"{plan.account_id}:{plan.decision_id}:snapshot".encode()
    ).hexdigest()
    return PaperExecutionResult(PaperPortfolio(cash, result_holdings), tuple(fills), snapshot_id)


def seed_paper_portfolio(initial_cash: float) -> PaperPortfolio:
    return PaperPortfolio(_finite_positive(initial_cash, "initial_cash"), ())


def recapitalize_paper_portfolio(
    portfolio: PaperPortfolio, target_equity: float
) -> PaperPortfolio:
    """Return the same positions with cash adjusted to an exact equity baseline."""
    target = _finite_positive(target_equity, "target_equity")
    holdings_value = sum(item.equity for item in portfolio.holdings)
    if holdings_value > target + 1e-9:
        raise ValueError("target_equity cannot be below current holdings value")
    return PaperPortfolio(target - holdings_value, portfolio.holdings)
