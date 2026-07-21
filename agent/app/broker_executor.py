"""Deterministic, fail-closed broker order planning and submission."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from app.tools.bigquery_service import insert_trade_record
from app.tools.robinhood_service import (
    BrokerPortfolioState,
    BrokerToolUnavailableError,
    OrderRejectedError,
    OrderStateUnknownError,
    QuoteSnapshot,
    fetch_robinhood_portfolio_state,
    parse_quotes,
    validate_account_number,
    validate_order_ticker,
)
from app.trading_policy import TradeAction, ValidatedExecutionPlan


class ExecutionStatus(StrEnum):
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


@dataclass(frozen=True)
class OrderRequest:
    ticker: str
    side: str
    shares: float
    amount_usd: float
    liquidate: bool
    action: TradeAction


@dataclass(frozen=True)
class OrderBatch:
    sells: tuple[OrderRequest, ...]
    buys: tuple[OrderRequest, ...]
    total_equity: float
    starting_cash: float
    buying_power: float


@dataclass(frozen=True)
class OrderReceipt:
    ticker: str
    side: str
    status: str
    broker_order_id: str | None
    requested_quantity: float
    filled_quantity: float | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    receipts: tuple[OrderReceipt, ...]
    deferred_buys: tuple[OrderRequest, ...] = ()
    reason: str | None = None


def build_orders(
    plan: ValidatedExecutionPlan,
    broker_state: BrokerPortfolioState,
    quotes: Mapping[str, QuoteSnapshot],
) -> OrderBatch:
    """Purely calculate an all-or-nothing order batch from authoritative inputs."""
    current_values = {
        holding.symbol: holding.shares * quotes[holding.symbol].price
        for holding in broker_state.holdings
    }
    total_equity = broker_state.cash + sum(current_values.values())
    if total_equity <= 0:
        raise ValueError("Broker total equity must be positive")
    current_shares = {
        holding.symbol: holding.shares for holding in broker_state.holdings
    }
    tickers = set(plan.allocations) | set(current_values)
    sells: list[OrderRequest] = []
    buys: list[OrderRequest] = []
    for ticker in sorted(tickers):
        price = quotes[ticker].price
        current_weight = current_values.get(ticker, 0.0) / total_equity
        target_weight = plan.allocations.get(ticker, 0.0)
        if (
            target_weight > 0
            and current_weight > 0
            and abs(target_weight - current_weight) <= 0.03
        ):
            continue
        delta_usd = (target_weight - current_weight) * total_equity
        if delta_usd < -0.01:
            liquidate = target_weight <= 0
            shares = (
                current_shares[ticker]
                if liquidate
                else min(current_shares[ticker], abs(delta_usd) / price)
            )
            sells.append(
                OrderRequest(
                    ticker,
                    "sell",
                    shares,
                    shares * price,
                    liquidate,
                    TradeAction.EXIT if liquidate else TradeAction.REDUCE,
                )
            )
        elif delta_usd > 0.01:
            buys.append(
                OrderRequest(
                    ticker,
                    "buy",
                    delta_usd / price,
                    delta_usd,
                    False,
                    TradeAction.ENTER if current_weight == 0 else TradeAction.ADD,
                )
            )
    return OrderBatch(
        tuple(sells),
        tuple(buys),
        total_equity,
        broker_state.cash,
        broker_state.buying_power,
    )


def parse_order_receipt(response: object, order: OrderRequest) -> OrderReceipt:
    if not isinstance(response, dict):
        raise OrderStateUnknownError("Order response is not an object")
    data = (
        response.get("structuredContent", {}).get("data")
        if isinstance(response.get("structuredContent"), dict)
        else None
    )
    payload = data if isinstance(data, dict) else response
    status = str(payload.get("status", "")).strip().lower()
    order_id = payload.get("order_id") or payload.get("id")
    if status in {"rejected", "failed", "cancelled", "canceled"}:
        raise OrderRejectedError(
            f"Broker rejected {order.side} order for {order.ticker}"
        )
    if (
        status not in {"success", "accepted", "submitted", "filled"}
        or not str(order_id or "").strip()
    ):
        raise OrderStateUnknownError(
            f"Broker returned an ambiguous state for {order.ticker}"
        )
    filled = order.shares if status == "filled" else None
    return OrderReceipt(
        order.ticker, order.side, status.upper(), str(order_id), order.shares, filled
    )


class BrokerExecutor:
    def __init__(
        self, toolset, account_number: str, dataset_id: str = "portfolio_analytics"
    ):
        self.toolset = toolset
        self.account_number = validate_account_number(account_number)
        self.dataset_id = dataset_id

    async def execute_rebalance(self, plan: ValidatedExecutionPlan) -> ExecutionResult:
        if not isinstance(plan, ValidatedExecutionPlan):
            raise TypeError("BrokerExecutor accepts only a ValidatedExecutionPlan")
        if plan.account_number != self.account_number:
            raise ValueError("Execution plan account does not match executor account")
        if plan.execution_mode == "PAPER":
            raise ValueError("Paper execution plans can never reach BrokerExecutor")
        if datetime.now(UTC) > plan.expires_at:
            return ExecutionResult(
                ExecutionStatus.ABORTED, (), reason="Execution plan expired"
            )
        if os.environ.get("TRADING_KILL_SWITCH", "false").lower() == "true":
            return ExecutionResult(
                ExecutionStatus.ABORTED, (), reason="Run-level kill switch is active"
            )

        tools = await self.toolset.get_tools()
        tools_dict = {tool.name: tool for tool in tools}
        state = await fetch_robinhood_portfolio_state(
            self.account_number, toolset=self.toolset
        )
        required_tickers = set(plan.allocations) | {
            holding.symbol for holding in state.holdings
        }
        if required_tickers and "get_equity_quotes" not in tools_dict:
            raise BrokerToolUnavailableError(
                "Required broker tool is unavailable: get_equity_quotes"
            )
        quotes = {}
        if required_tickers:
            response = await tools_dict["get_equity_quotes"].run_async(
                args={"symbols": sorted(required_tickers)}, tool_context=None
            )
            quotes = parse_quotes(response, required_tickers)
        batch = build_orders(plan, state, quotes)
        runtime_order_cap = min(
            0.35 * batch.total_equity,
            float(os.environ.get("MAX_ORDER_NOTIONAL_USD", "35.00")),
        )
        if any(
            order.amount_usd > runtime_order_cap + 0.01
            for order in batch.sells + batch.buys
        ):
            return ExecutionResult(
                ExecutionStatus.ABORTED,
                (),
                reason="Authoritative order notional exceeds configured cap",
            )

        dry_run = os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true"
        if (
            not dry_run
            and (batch.sells or batch.buys)
            and "place_equity_order" not in tools_dict
        ):
            raise BrokerToolUnavailableError(
                "Required broker tool is unavailable: place_equity_order"
            )

        receipts: list[OrderReceipt] = []
        deferred = batch.buys if batch.sells else ()
        orders = batch.sells if batch.sells else batch.buys
        if batch.buys and not batch.sells:
            reserve = 0.05 * batch.total_equity
            required = sum(order.amount_usd for order in batch.buys)
            if required > max(0.0, batch.buying_power - reserve) + 0.01:
                return ExecutionResult(
                    ExecutionStatus.ABORTED,
                    (),
                    reason="Insufficient authoritative buying power",
                )

        for order in orders:
            validate_account_number(self.account_number)
            validate_order_ticker(order.ticker)
            if dry_run:
                receipt = OrderReceipt(
                    order.ticker,
                    order.side,
                    "SIMULATED",
                    None,
                    order.shares,
                    order.shares,
                )
            else:
                ref_seed = f"{plan.decision_id}:{order.ticker}:{order.side}".encode()
                response = await tools_dict["place_equity_order"].run_async(
                    args={
                        "account_number": self.account_number,
                        "symbol": order.ticker,
                        "side": order.side,
                        "type": "market",
                        "quantity": f"{order.shares:.6f}",
                        "ref_id": hashlib.sha256(ref_seed).hexdigest()[:32],
                    },
                    tool_context=None,
                )
                try:
                    receipt = parse_order_receipt(response, order)
                except (OrderRejectedError, OrderStateUnknownError) as exc:
                    return ExecutionResult(
                        ExecutionStatus.ABORTED, tuple(receipts), deferred, str(exc)
                    )
            receipts.append(receipt)
            insert_trade_record(
                ticker=order.ticker,
                action="LIQUIDATE" if order.liquidate else order.side.upper(),
                amount_usd=order.amount_usd,
                reasoning=f"{plan.policy_version}:{order.action.value}",
                dry_run=dry_run,
                dataset_id=self.dataset_id,
                decision_id=plan.decision_id,
                broker_order_id=receipt.broker_order_id,
                order_status=receipt.status,
                requested_quantity=order.shares,
                filled_quantity=receipt.filled_quantity,
                account_id=plan.account_id,
                trade_id=hashlib.sha256(
                    f"{plan.decision_id}:{order.ticker}:{order.side}".encode()
                ).hexdigest(),
                execution_mode=plan.execution_mode,
                fill_price=quotes[order.ticker].price,
                fees_usd=0.0,
                slippage_usd=0.0,
                market_batch_id=plan.market_batch_id,
            )

        filled_receipts = [
            receipt for receipt in receipts if receipt.status == "FILLED"
        ]
        if filled_receipts and not dry_run:
            before = {holding.symbol: holding.shares for holding in state.holdings}
            mismatch = None
            for attempt in range(3):
                reconciled = await fetch_robinhood_portfolio_state(
                    self.account_number, toolset=self.toolset
                )
                after = {
                    holding.symbol: holding.shares for holding in reconciled.holdings
                }
                mismatch = None
                for receipt in filled_receipts:
                    old_quantity = before.get(receipt.ticker, 0.0)
                    new_quantity = after.get(receipt.ticker, 0.0)
                    expected = (
                        old_quantity + receipt.requested_quantity
                        if receipt.side == "buy"
                        else max(0.0, old_quantity - receipt.requested_quantity)
                    )
                    if not math.isclose(
                        new_quantity, expected, rel_tol=1e-4, abs_tol=1e-5
                    ):
                        mismatch = receipt.ticker
                        break
                if mismatch is None:
                    break
                if attempt < 2:
                    await asyncio.sleep(1)
            if mismatch is not None:
                return ExecutionResult(
                    ExecutionStatus.RECONCILIATION_FAILED,
                    tuple(receipts),
                    deferred,
                    f"Broker position mismatch for {mismatch}",
                )
        return ExecutionResult(ExecutionStatus.COMPLETED, tuple(receipts), deferred)
