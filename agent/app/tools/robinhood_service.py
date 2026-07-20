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

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from app.tools.ticker_universe import get_allowed_tickers


class BrokerConnectionError(RuntimeError):
    pass


class BrokerPayloadError(RuntimeError):
    pass


class BrokerToolUnavailableError(RuntimeError):
    pass


class QuoteValidationError(RuntimeError):
    pass


class OrderRejectedError(RuntimeError):
    pass


class OrderStateUnknownError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerHolding:
    symbol: str
    shares: float
    average_buy_price: float
    current_price: float

    @property
    def equity(self) -> float:
        return self.shares * self.current_price


@dataclass(frozen=True)
class BrokerPortfolioState:
    account_number: str
    observed_at: datetime
    cash: float
    buying_power: float
    holdings: tuple[BrokerHolding, ...]


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    price: float
    observed_at: datetime


def _finite_non_negative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BrokerPayloadError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise BrokerPayloadError(f"{field} must be finite and non-negative")
    return number


def validate_account_number(account_number: str) -> str:
    value = str(account_number).strip()
    if not value.endswith("48661"):
        raise ValueError(f"Unauthorized Robinhood account '{value}'.")
    return value


def validate_order_ticker(ticker: str) -> str:
    value = str(ticker).strip().upper()
    if value not in set(get_allowed_tickers()):
        raise ValueError(f"Ticker '{value}' is outside the authorized asset universe.")
    return value


def _data_payload(response: Any, tool_name: str) -> dict:
    if not isinstance(response, dict):
        raise BrokerPayloadError(f"{tool_name} returned a non-object payload")
    structured = response.get("structuredContent")
    if not isinstance(structured, dict) or not isinstance(structured.get("data"), dict):
        raise BrokerPayloadError(f"{tool_name} response is missing structuredContent.data")
    return structured["data"]


def parse_quotes(response: Any, required_tickers: set[str], *, received_at: datetime | None = None) -> dict[str, QuoteSnapshot]:
    received_at = received_at or datetime.now(timezone.utc)
    data = _data_payload(response, "get_equity_quotes")
    results = data.get("results")
    if not isinstance(results, list):
        raise QuoteValidationError("get_equity_quotes response is missing results")
    parsed: dict[str, QuoteSnapshot] = {}
    for result in results:
        quote = result.get("quote") if isinstance(result, dict) else None
        if not isinstance(quote, dict):
            raise QuoteValidationError("quote result is malformed")
        symbol = str(quote.get("symbol", "")).strip().upper()
        if not symbol or symbol in parsed:
            raise QuoteValidationError(f"duplicate or missing quote symbol: {symbol!r}")
        raw_price = quote.get("last_non_reg_trade_price") or quote.get("last_trade_price")
        try:
            price = float(raw_price)
        except (TypeError, ValueError) as exc:
            raise QuoteValidationError(f"invalid quote price for {symbol}") from exc
        if not math.isfinite(price) or price <= 0 or price > 1_000_000:
            raise QuoteValidationError(f"invalid quote price for {symbol}")
        bid_raw, ask_raw = quote.get("bid_price"), quote.get("ask_price")
        if bid_raw is not None and ask_raw is not None:
            try:
                bid, ask = float(bid_raw), float(ask_raw)
            except (TypeError, ValueError) as exc:
                raise QuoteValidationError(f"invalid bid/ask for {symbol}") from exc
            if not all(math.isfinite(value) and value > 0 for value in (bid, ask)) or bid > ask:
                raise QuoteValidationError(f"crossed or invalid market for {symbol}")
        observed_at = received_at
        raw_timestamp = quote.get("timestamp") or quote.get("updated_at") or quote.get("last_trade_at")
        if raw_timestamp is not None:
            try:
                if isinstance(raw_timestamp, (int, float)):
                    observed_at = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
                else:
                    observed_at = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OSError) as exc:
                raise QuoteValidationError(f"invalid quote timestamp for {symbol}") from exc
            if observed_at > received_at + timedelta(seconds=5) or received_at - observed_at > timedelta(seconds=120):
                raise QuoteValidationError(f"stale quote for {symbol}")
        parsed[symbol] = QuoteSnapshot(symbol, price, observed_at)
    missing = {ticker.upper() for ticker in required_tickers} - set(parsed)
    extra_duplicates = set(parsed) - {ticker.upper() for ticker in required_tickers}
    if missing:
        raise QuoteValidationError(f"missing quotes for: {', '.join(sorted(missing))}")
    if extra_duplicates:
        parsed = {ticker: quote for ticker, quote in parsed.items() if ticker in required_tickers}
    return parsed

async def validate_and_intercept_trades(tool, args, tool_context) -> dict | None:
    """Interceptor callback (Double Guardrail + Dry Run) for trading execution."""
    print(f"   [DEBUG INTERCEPT] Tool '{tool.name}' called with args: {args}")
    
    # 1. Enforce Robinhood Account Restriction
    account_keys = [k for k in args.keys() if "account" in k.lower()]
    for key in account_keys:
        val = args.get(key)
        if val:
            val_str = str(val).strip()
            if not val_str.endswith("48661"):
                raise ValueError(
                    f"Security Exception: Operation rejected. Tool '{tool.name}' attempted to access "
                    f"unauthorized account '{val_str}'. All actions are restricted to account ending in 48661."
                )

    # 2. Enforce Predefined 40-Asset Universe
    ticker_keys = [k for k in args.keys() if "symbol" in k.lower() or "ticker" in k.lower()]
    ALLOWED_TICKERS = set(get_allowed_tickers())
    for key in ticker_keys:
        val = args.get(key)
        if val:
            if isinstance(val, (list, tuple)):
                tickers_to_check = val
            elif isinstance(val, str):
                if "," in val:
                    tickers_to_check = [t.strip() for t in val.split(",")]
                else:
                    tickers_to_check = [val]
            else:
                tickers_to_check = [str(val)]
                
            for ticker in tickers_to_check:
                ticker_str = str(ticker).strip().upper()
                if ticker_str and ticker_str not in ALLOWED_TICKERS:
                    raise ValueError(
                        f"Security Exception: Operation rejected. Ticker '{ticker_str}' is outside the authorized asset universe."
                    )

    # 3. Dry-Run Interceptor: block order modifications and return simulated success
    if os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true":
        tool_name = tool.name.lower()
        if "insert_trade_record" not in tool_name:
            if any(action in tool_name for action in ["order", "buy", "sell", "trade", "execute", "cancel"]):
                print(f"[DRY_RUN] Intercepted trade order tool '{tool.name}' with args: {args}")
                return {
                    "status": "success",
                    "message": f"[DRY_RUN] Simulated execution successfully for {tool.name}",
                    "order_id": "dry-run-mock-order-id-12345",
                    "simulated": True
                }

    return None


# Initialize the MCP toolset with mcp-remote for authenticated trading tools
robinhood_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "mcp-remote", "https://agent.robinhood.com/mcp/trading"]
        ),
        timeout=300.0  # 5-minute timeout to allow interactive OAuth sign-in
    )
)


async def fetch_robinhood_portfolio_state(account_number: str, *, toolset=None) -> BrokerPortfolioState:
    """Fetch authoritative broker state or raise; never return tradable fallbacks."""
    account_number = validate_account_number(account_number)
    selected_toolset = toolset or robinhood_toolset
    try:
        tools = await selected_toolset.get_tools()
    except Exception as exc:
        raise BrokerConnectionError("Failed to connect to Robinhood tools") from exc
    tools_dict = {tool.name: tool for tool in tools}
    for required in ("get_portfolio", "get_equity_positions"):
        if required not in tools_dict:
            raise BrokerToolUnavailableError(f"Required broker tool is unavailable: {required}")
    try:
        portfolio_response = await tools_dict["get_portfolio"].run_async(
            args={"account_number": account_number}, tool_context=None
        )
        positions_response = await tools_dict["get_equity_positions"].run_async(
            args={"account_number": account_number}, tool_context=None
        )
    except Exception as exc:
        raise BrokerConnectionError("Broker state request failed") from exc
    portfolio_data = _data_payload(portfolio_response, "get_portfolio")
    positions_data = _data_payload(positions_response, "get_equity_positions")
    cash = _finite_non_negative(portfolio_data.get("cash"), "cash")
    buying_power_data = portfolio_data.get("buying_power")
    if not isinstance(buying_power_data, dict) or "buying_power" not in buying_power_data:
        raise BrokerPayloadError("get_portfolio response is missing buying_power.buying_power")
    buying_power = _finite_non_negative(buying_power_data["buying_power"], "buying_power")
    raw_positions = positions_data.get("positions")
    if not isinstance(raw_positions, list):
        raise BrokerPayloadError("get_equity_positions response is missing positions")
    raw_holdings: list[tuple[str, float, float]] = []
    for position in raw_positions:
        if not isinstance(position, dict):
            raise BrokerPayloadError("position is malformed")
        symbol = validate_order_ticker(position.get("symbol", ""))
        shares = _finite_non_negative(position.get("quantity"), f"{symbol}.quantity")
        average_price = _finite_non_negative(position.get("average_buy_price", 0), f"{symbol}.average_buy_price")
        if shares > 0:
            raw_holdings.append((symbol, shares, average_price))
    symbols = {item[0] for item in raw_holdings}
    if symbols and "get_equity_quotes" not in tools_dict:
        raise BrokerToolUnavailableError("Required broker tool is unavailable: get_equity_quotes")
    quote_map = {}
    if symbols:
        try:
            quote_response = await tools_dict["get_equity_quotes"].run_async(
                args={"symbols": sorted(symbols)}, tool_context=None
            )
        except Exception as exc:
            raise BrokerConnectionError("Broker quote request failed") from exc
        quote_map = parse_quotes(quote_response, symbols)
    holdings = tuple(
        BrokerHolding(symbol, shares, average_price, quote_map[symbol].price)
        for symbol, shares, average_price in raw_holdings
    )
    return BrokerPortfolioState(account_number, datetime.now(timezone.utc), cash, buying_power, holdings)


async def log_portfolio_snapshot(summary: str | None = None, dataset_id: str = "portfolio_analytics") -> None:
    """Queries Robinhood portfolio cash and positions, and logs a snapshot to BigQuery."""
    import json
    from app.tools.bigquery_service import insert_portfolio_snapshot

    # Resolve target account ending in 48661
    account_number = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER")
    if not account_number:
        if os.environ.get("SKIP_LIVE_TRADES", "true").lower() == "true":
            account_number = "MOCK_ACCOUNT_48661"
        else:
            raise RuntimeError("Security Guardrail: ROBINHOOD_ACCOUNT_NUMBER environment variable is not set.")

    if not account_number or not str(account_number).endswith("48661"):
        raise RuntimeError(f"Security Guardrail: Unauthorized Robinhood account '{account_number}'. All operations restricted to accounts ending in 48661.")

    state = await fetch_robinhood_portfolio_state(account_number)
    holdings = [
        {
            "symbol": holding.symbol,
            "shares": holding.shares,
            "average_buy_price": holding.average_buy_price,
            "current_price": holding.current_price,
            "equity": holding.equity,
        }
        for holding in state.holdings
    ]
    holdings_value = sum(h["equity"] for h in holdings)
    total_equity = state.cash + holdings_value
    
    # Calculate actual position-level unrealized gain/loss
    total_cost_basis = sum(h["shares"] * h["average_buy_price"] for h in holdings)
    unrealized_gain_loss = holdings_value - total_cost_basis
    unrealized_gain_loss_percent = (unrealized_gain_loss / total_cost_basis * 100.0) if total_cost_basis > 0.0 else 0.0

    snapshot = {
        "account_number": f"••••{account_number[-5:]}" if len(account_number) >= 5 else account_number,
        "total_equity": total_equity,
        "total_cash": state.cash,
        "buying_power": state.buying_power,
        "unrealized_gain_loss": unrealized_gain_loss,
        "unrealized_gain_loss_percent": unrealized_gain_loss_percent,
        "holdings": json.dumps(holdings),
        "summary": summary
    }

    insert_portfolio_snapshot(snapshot, dataset_id=dataset_id)
