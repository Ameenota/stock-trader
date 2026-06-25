# ruff: noqa
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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

# Set to True to use Vertex AI (GCP), or False to use Google AI Studio (GEMINI_API_KEY)
USE_VERTEX_AI = True

if USE_VERTEX_AI:
    import google.auth
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"


from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# We delegate remote connection/auth to `mcp-remote` via standard stdio transport.
# Why this approach:
# 1. Robinhood MCP server uses Public OAuth 2.0 PKCE with dynamic client registration (no client_secret).
# 2. ADK's built-in ExtendedOAuth2 scheme requires a static client_secret in raw_auth_credential
#    and will raise a validation ValueError if it's missing.
# 3. `mcp-remote` runs as a Node.js background process, handles public client registration,
#    launches the browser, completes token exchanges, and securely saves the credentials to `~/.mcp-auth/`.
# 4. Timeout is set to 300 seconds (5 mins) to give the user enough time to complete
#    browser login and MFA verification without the ADK aborting and restarting the session.
robinhood_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=["-y", "mcp-remote", "https://agent.robinhood.com/mcp/trading"]
        ),
        timeout=300.0  # 5-minute timeout to allow interactive OAuth sign-in
    )
)

from app.tools.data_ingestion import ingest_market_news
from app.tools.ranking import SentimentAnalysisResponse, process_sentiment_rankings
from app.tools.bigquery_service import insert_trade_record
from app.tools.ticker_universe import get_allowed_tickers
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext

sentiment_agent = Agent(
    name="sentiment_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a professional stock market sentiment analyst.
Analyze the sentiment of the target assets based strictly on the provided news dictionary.
For each ticker present as a key in the news dictionary, check the news headlines and summaries.
Assign a raw_score (float from -1.0 to 1.0) and write a concise thesis explaining your score.
If the news list for a ticker is empty or has no recent news, you MUST return a raw_score of 0.0 and a thesis explaining that no recent news was found for this ticker.
You MUST output exactly one analysis entry for each and every ticker present in the keys of the provided news dictionary.""",
    output_schema=SentimentAnalysisResponse,
    output_key="sentiment_result",
)

async def analyze_and_rank_portfolio(tool_context: ToolContext) -> dict:
    """Ingests latest 24h market news, runs sentiment analysis via the Gemini sentiment agent,
    and runs deterministic Python logic to sort, rank, and assign trade signals to the portfolio.

    Returns:
        A dictionary containing the ranked portfolio results with relative ranks and trade signals.
    """
    # 1. Dynamically determine the watchlist
    from app.tools.ticker_universe import determine_active_watchlist
    active_tickers = await determine_active_watchlist()

    # 2. Ingest news only for the active watchlist
    news_dict = ingest_market_news(tickers=active_tickers)

    # 2. Run sentiment_agent using a separate sub-session
    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="system", app_name="sentiment")
    runner = Runner(agent=sentiment_agent, session_service=session_service, app_name="sentiment")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Please analyze these news articles:\n{news_dict}")]
    )

    async for _ in runner.run_async(
        new_message=message,
        user_id="system",
        session_id=session.id,
    ):
        pass

    response_obj = session.state.get("sentiment_result")
    if not response_obj:
        return {"error": "Failed to retrieve structured sentiment analysis from Gemini."}

    # 3. Process with deterministic Python ranking logic
    ranked_results = process_sentiment_rankings(response_obj)

    return {"ranked_portfolio": ranked_results}

import sys

# System prompt for trading execution agent
TRADING_AGENT_INSTRUCTION = """(limit all queries or actions to the agentic account ending in 48661)
You are a professional financial execution expert. Your goal is to review the current Robinhood portfolio holdings and cash balance, analyze the historical rolling metrics provided, and execute trades to keep our portfolio aligned with our target state.

Our rules:
1. Limit actions to the agentic account ending in 48661.
2. We hold a maximum of 3 assets at any time.
3. Our total target budget is $100.
4. You can dynamically allocate weights as you see fit. If one stock has a super high signal, you can allocate up to 100% of the $100 to it, or split the cash among 2 or 3 stocks.
5. Identify which stocks/assets to hold, buy, or liquidate based on the signals (Sentiment, Momentum, Analyst recommendation, and Technical Indicators like RSI and MACD) over the weekly historical range.
6. TLT is our treasury option (safe-haven / fallback asset). If tech/AI signals are generally weak, crashing, or there are fewer than 3 strong AI positions, allocate the defensive portion (or all) of the budget to TLT to protect capital.
7. Liquidate positions (sell 100%) for any asset that is no longer recommended to hold.
8. Log the reasoning for every executed transaction (BUY, SELL, or LIQUIDATE) you perform by calling insert_trade_record. Use exactly "BUY", "SELL", or "LIQUIDATE" for the action parameter. Do NOT log or call insert_trade_record for HOLD decisions, as they are not active trades.
9. Utilize Technical Indicators (rsi, macd, macd_signal) to improve trade execution timing:
   - Be cautious of buying/increasing positions in assets with RSI > 70 (overbought condition).
   - Look for entry/buying signals when RSI is near or below 30 (oversold condition).
   - Use MACD crossovers (e.g., macd crossing above macd_signal is a bullish signal; macd crossing below macd_signal is a bearish signal) to confirm trend momentum shifts.
10. **Hysteresis & Swap Buffer**: To prevent marginal churn (frequent, inefficient trading of assets for minor conviction gains), you must strictly enforce a swap threshold. You are only allowed to sell/liquidate an existing holding to buy a new candidate asset if the new candidate's conviction score (`raw_score` in today's metrics log) is at least **0.3 higher** than the score of the asset you are replacing (i.e. `new_candidate.raw_score - existing_holding.raw_score > 0.3`). If the delta is 0.3 or less, keep holding the existing asset instead of swapping. This hysteresis rule does not apply when liquidating an asset that has a direct negative sentiment or liquidation signal, or when deploying idle cash."""


async def validate_and_intercept_trades(tool, args, tool_context) -> dict | None:
    """Interceptor callback (Double Guardrail + Dry Run) for trading execution."""
    # 1. Enforce Robinhood Account Restriction
    # Inspect arguments for account number key (e.g. 'account_number', 'account')
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

    # 2. Enforce Predefined 10-Asset Universe
    # Inspect arguments for ticker symbol keys (e.g. 'symbol', 'ticker')
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
    if os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true":
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


trading_agent = Agent(
    name="trading_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=TRADING_AGENT_INSTRUCTION,
    tools=[robinhood_toolset, insert_trade_record],
    before_tool_callback=validate_and_intercept_trades,
)


async def run_daily_analysis_pipeline(dataset_id: str = "portfolio_analytics") -> list:
    """Ingests market news/metrics, runs sentiment analysis agent, ranks assets,
    and logs decisions to BigQuery.
    """
    from datetime import datetime, timezone
    from app.tools.data_ingestion import ingest_market_data
    from app.tools.ranking import process_sentiment_rankings
    from app.tools.bigquery_service import insert_sentiment
    from app.tools.ticker_universe import determine_active_watchlist

    # 1. Dynamically determine the watchlist and get details for all universe assets
    active_tickers, all_tickers_details = await determine_active_watchlist(dataset_id=dataset_id, return_details=True)

    # 2. Ingest latest market news and metrics only for the active watchlist
    market_data = ingest_market_data(tickers=active_tickers)

    # 2. Run sentiment agent sub-session
    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="cron_job", app_name="sentiment")
    runner = Runner(agent=sentiment_agent, session_service=session_service, app_name="sentiment")

    news_dict = {ticker: data.get("news", []) for ticker, data in market_data.items()}

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Analyze these news articles:\n{news_dict}")]
    )

    async for _ in runner.run_async(
        new_message=message,
        user_id="cron_job",
        session_id=session.id,
    ):
        pass

    session = await session_service.get_session(user_id="cron_job", session_id=session.id, app_name="sentiment")
    sentiment_result = session.state.get("sentiment_result")
    if not sentiment_result:
        raise RuntimeError("Failed to retrieve sentiment analysis output from the LLM agent.")

    # 3. Sort, rank and assign signals
    ranked_portfolio = process_sentiment_rankings(sentiment_result)

    # 4. Attach raw news and technical metrics for auditing
    current_time_str = datetime.now(timezone.utc).isoformat()
    for item in ranked_portfolio:
        ticker = item["ticker"]
        item["timestamp"] = current_time_str
        ticker_data = market_data.get(ticker, {})
        item["raw_news"] = ticker_data.get("news", [])
        item["analyst_consensus"] = ticker_data.get("analyst_consensus")
        item["target_price"] = ticker_data.get("target_price")
        item["current_price"] = ticker_data.get("current_price")
        item["moving_average_20d"] = ticker_data.get("moving_average_20d")
        item["price_to_ma_ratio"] = ticker_data.get("price_to_ma_ratio")
        item["rsi"] = ticker_data.get("rsi")
        item["macd"] = ticker_data.get("macd")
        item["macd_signal"] = ticker_data.get("macd_signal")

    # 5. Build placeholder rows for the filtered graveyard assets to prove LLM token savings
    graveyard_rows = []
    for ticker, detail in all_tickers_details.items():
        if detail.get("status") == "FILTERED":
            graveyard_rows.append({
                "ticker": ticker,
                "raw_score": 0.0,
                "thesis": f"Filtered: {detail.get('reason', 'Excluded by pre-screener')}",
                "relative_rank": 0,
                "signal": "FILTERED",
                "timestamp": current_time_str,
                "raw_news": "[]",
                "analyst_consensus": "N/A",
                "target_price": None,
                "current_price": detail.get("current_price"),
                "moving_average_20d": detail.get("sma_50"),
                "price_to_ma_ratio": detail.get("momentum"),
                "rsi": None,
                "macd": None,
                "macd_signal": None
            })

    # 6. Ingest and log SPY benchmark data
    try:
        spy_data = ingest_market_data(tickers=["SPY"])
        spy_price = spy_data.get("SPY", {}).get("current_price")
        if spy_price:
            print(f"   Successfully ingested SPY benchmark price: ${spy_price:.2f}")
            graveyard_rows.append({
                "ticker": "SPY",
                "raw_score": 0.0,
                "thesis": "S&P 500 Index Benchmark",
                "relative_rank": 0,
                "signal": "BENCHMARK",
                "timestamp": current_time_str,
                "raw_news": "[]",
                "analyst_consensus": "N/A",
                "target_price": None,
                "current_price": spy_price,
                "moving_average_20d": None,
                "price_to_ma_ratio": None,
                "rsi": None,
                "macd": None,
                "macd_signal": None
            })
    except Exception as e:
        print(f"   Warning: Failed to ingest SPY: {e}")

    # 7. Log all decisions (10 active + 30 graveyard + 1 benchmark) to BigQuery
    all_rows_to_log = list(ranked_portfolio) + graveyard_rows
    insert_sentiment(all_rows_to_log, dataset_id=dataset_id)

    return ranked_portfolio


async def execute_trading_decisions(ranked_portfolio: list, dataset_id: str = "portfolio_analytics") -> None:
    """Queries weekly metrics history and triggers trading_agent to execute trades on Robinhood."""
    from app.tools.bigquery_service import get_historical_metrics

    # 1. Fetch weekly historical signals log
    weekly_metrics = get_historical_metrics(days=7, dataset_id=dataset_id)
    
    # 2. Run trading agent session
    # Clear INTEGRATION_TEST to allow the McpToolset to connect
    if "INTEGRATION_TEST" in os.environ:
        del os.environ["INTEGRATION_TEST"]

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="cron_job", app_name="trading")
    runner = Runner(agent=trading_agent, session_service=session_service, app_name="trading")

    prompt_text = f"""Please perform today's trading execution and portfolio rebalancing.
Here is the historical metrics log for all 10 assets over the past week:
{weekly_metrics}"""

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)]
    )

    # Execute and stream reasoning to standard output
    print("\n=== Trading Agent Execution & Reasoning Stream ===")
    async for event in runner.run_async(
        new_message=message,
        user_id="cron_job",
        session_id=session.id,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, end="", flush=True)
    print("\n==================================================\n")

    # 3. Log post-trade portfolio snapshot
    print("\nLogging portfolio snapshot to BigQuery...")
    try:
        await log_portfolio_snapshot(dataset_id=dataset_id)
        print("   Portfolio snapshot logged successfully.")
    except Exception as e:
        print(f"   Warning: Failed to log portfolio snapshot: {e}")


async def log_portfolio_snapshot(dataset_id: str = "portfolio_analytics") -> None:
    """Queries Robinhood MCP tools for current equity, cash, and holdings,
    and inserts a snapshot record into BigQuery."""
    import json
    from datetime import datetime, timezone
    from app.tools.bigquery_service import insert_portfolio_snapshot

    # 1. Fetch available tools from remote server
    try:
        tools = await robinhood_toolset.get_tools()
        tools_dict = {t.name: t for t in tools}
    except Exception as e:
        print(f"   Warning: Could not fetch MCP tools: {e}")
        return

    # Redacted target account format: select account ending in 48661
    account_number = "ROBINHOOD_ACCOUNT_NUMBER"  # Default fallback, will search list
    if "get_accounts" in tools_dict:
        try:
            accounts_res = await tools_dict["get_accounts"].run_async(args={}, tool_context=None)
            results = accounts_res.get("structuredContent", {}).get("data", {}).get("results", [])
            for acc in results:
                acc_num = acc.get("account_number")
                if acc_num and str(acc_num).endswith("48661"):
                    account_number = str(acc_num)
                    break
        except Exception:
            pass

    # 2. Query portfolio metrics
    total_equity = 100.0
    total_cash = 100.0
    
    if "get_portfolio" in tools_dict:
        try:
            port_res = await tools_dict["get_portfolio"].run_async(args={"account_number": account_number}, tool_context=None)
            data = port_res.get("structuredContent", {}).get("data", {})
            total_equity = float(data.get("total_value", 100.0))
            total_cash = float(data.get("cash", 100.0))
        except Exception:
            pass

    # Calculate gain/loss from the base $100 budget
    unrealized_gain_loss = total_equity - 100.0
    unrealized_gain_loss_percent = (unrealized_gain_loss / 100.0) * 100.0

    # 3. Query positions and quotes
    holdings = []
    if "get_equity_positions" in tools_dict:
        try:
            pos_res = await tools_dict["get_equity_positions"].run_async(args={"account_number": account_number}, tool_context=None)
            positions = pos_res.get("structuredContent", {}).get("data", {}).get("positions", [])
            
            active_symbols = []
            symbol_shares = {}
            symbol_cost = {}
            
            for pos in positions:
                qty = float(pos.get("quantity", 0))
                if qty > 0:
                    sym = pos["symbol"]
                    active_symbols.append(sym)
                    symbol_shares[sym] = qty
                    symbol_cost[sym] = float(pos.get("average_buy_price", 0))

            # Fetch live prices for active holdings
            if active_symbols and "get_equity_quotes" in tools_dict:
                quotes_res = await tools_dict["get_equity_quotes"].run_async(args={"symbols": active_symbols}, tool_context=None)
                results = quotes_res.get("structuredContent", {}).get("data", {}).get("results", [])
                for res in results:
                    quote = res.get("quote", {})
                    sym = quote.get("symbol")
                    if sym in symbol_shares:
                        # Find price, checking both trade and non-reg trade prices
                        price = float(quote.get("last_non_reg_trade_price") or quote.get("last_trade_price") or 0.0)
                        qty = symbol_shares[sym]
                        equity_val = qty * price
                        holdings.append({
                            "symbol": sym,
                            "shares": qty,
                            "average_buy_price": symbol_cost[sym],
                            "current_price": price,
                            "equity": equity_val
                        })
        except Exception:
            pass

    snapshot = {
        "account_number": f"••••{account_number[-5:]}" if len(account_number) >= 5 else account_number,
        "total_equity": total_equity,
        "total_cash": total_cash,
        "unrealized_gain_loss": unrealized_gain_loss,
        "unrealized_gain_loss_percent": unrealized_gain_loss_percent,
        "holdings": json.dumps(holdings)
    }

    insert_portfolio_snapshot(snapshot, dataset_id=dataset_id)


# Define tools list, conditionally adding robinhood_toolset if not in a test environment
agent_tools = [analyze_and_rank_portfolio]
if not os.environ.get("INTEGRATION_TEST") and "pytest" not in sys.modules:
    agent_tools.append(robinhood_toolset)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are a helpful AI assistant designed to provide accurate and useful information.",
    tools=agent_tools,
    before_tool_callback=validate_and_intercept_trades,
)

app = App(
    root_agent=root_agent,
    name="app",
)
