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

from google.adk.agents import Agent, BaseAgent, LoopAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional, AsyncGenerator
from google.adk.events import Event, EventActions
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.callback_context import CallbackContext

# Terminal colors for beautiful outputs
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_MAGENTA = "\033[95m"
CLR_CYAN = "\033[96m"

# Set to True to use Vertex AI (GCP), or False to use Google AI Studio (GEMINI_API_KEY)
USE_VERTEX_AI = True

if USE_VERTEX_AI:
    import google.auth
    try:
        _, project_id = google.auth.default()
    except Exception:
        project_id = None
    project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT") or "conspiracy-493120"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"


from app.tools.robinhood_service import robinhood_toolset, validate_and_intercept_trades
from app.tools.data_ingestion import ingest_market_news
from app.tools.ranking import SentimentAnalysisResponse, process_sentiment_rankings
from app.tools.bigquery_service import insert_trade_record
from app.tools.ticker_universe import get_allowed_tickers
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext


class TargetAllocation(BaseModel):
    ticker: str = Field(description="The stock ticker symbol. Must be from the allowed universe.")
    weight_pct: float = Field(description="The target weight as a fraction of total equity (e.g. 0.30 for 30%).")

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

# Prompts for Multi-Agent Critique Loop
ANALYST_INSTRUCTION = """You are a portfolio analyst agent. Your goal is to analyze the market metrics and news sentiment for our watchlist and propose a draft portfolio of stock allocations.

Starting Portfolio State:
- Total Equity: ${total_equity}
- Current Cash: ${current_cash} ({current_cash_pct}% of total equity)
- Current Holdings (with days_held): {current_holdings}

Recent Trade History:
{recent_trades}

Today's Watch List & Weekly Metrics:
{ranked_portfolio}

Advisor Critique from Previous Iteration:
{advisor_critique}

Propose target allocations for stocks as percentages of total equity (e.g. 0.30 for 30%). You can select up to 3 active holdings (targeting 30% each, summing to 90% of total equity, leaving 10% for cash). If you want to allocate to a defensive treasury bond option, choose TLT. Do not include CASH or USD in the allocations list. The cash buffer is managed implicitly by leaving the remaining percentage of total equity unallocated.

Trading Rules to follow:
1. Focus on the Trend: Base your conviction on the '5-day EWMA Sentiment' rather than volatile daily spikes.
2. Technical Entry: Prioritize entries where the 'sustained_rsi_drop' flag is TRUE (RSI < 30 for 3+ consecutive days) to confirm structural drawdowns.
3. Minimum Holding Period: Do NOT propose to sell, reduce weight of, or liquidate any stock in "Current Holdings" if its `days_held` is less than 21 days, UNLESS its EWMA sentiment score is extremely negative (below -0.5).

Your proposal must output a list of TargetAllocation objects under the `allocations` key. You must also output the final signals and theses for all watchlist assets under the `decisions` key.
"""

SENIOR_ADVISOR_INSTRUCTION = """You are a senior financial advisor and risk critic. Your goal is to review the draft portfolio proposal generated by the portfolio analyst and ensure it strictly follows our technical trading rules, while allowing for concentrated, high-risk sector or asset picks.

Starting Portfolio State:
- Total Equity: ${total_equity}
- Current Cash: ${current_cash} ({current_cash_pct}% of total equity)
- Current Holdings (with days_held): {current_holdings}
- Active Watchlist (with EWMA Sentiment, Drawdown, and Volatility): {watchlist_data}

Analyst's Draft Proposal:
{analyst_proposal}

Our strict rules:
1. Target Cash Buffer: A target cash buffer of 10% of total equity must be respected. If current cash is between 5% and 15%, do not force an adjustment.
2. Position Sizing: The baseline target for a holding is 30% of total equity. Do not rebalance an existing holding if its current weight is within a +/- 3% tolerance of its target.
3. Value Entries: Approve and prioritize entries for assets experiencing a drawdown of 10% or more from their 52-week high, provided their 5-day EWMA sentiment remains bullish (EWMA sentiment > 0.1).
4. Volatility Rejection: REJECT any new allocations into assets where the 'sentiment volatility' (standard deviation) is exceptionally high (standard deviation > 0.4), indicating erratic news or pending binary events.
5. Minimum Holding Period: REJECT any proposal to sell, reduce weight of, or liquidate an existing holding if its days_held < 21, UNLESS the ticker's EWMA sentiment score is extremely negative (below -0.5).

Output format:
You must output a structured review matching the AdvisorCritique schema. If you reject the proposal, you must provide explicit, mathematically sound feedback so the analyst can correct the weights in the next iteration.
"""

class AssetDecision(BaseModel):
    ticker: str = Field(description="The stock ticker symbol.")
    signal: str = Field(description="The final action signal. Must be 'STRONG BUY', 'HOLD', or 'LIQUIDATE'.")
    thesis: str = Field(description="A concise thesis (max 2 sentences) justifying the signal based on news rank, sentiment, and technical metrics.")

class AnalystProposal(BaseModel):
    allocations: List[TargetAllocation] = Field(description="The list of target stock allocations.")
    decisions: List[AssetDecision] = Field(description="Signal and thesis decisions for all assets in today's active watchlist.")
    thesis: str = Field(description="Detailed explanation of your choices, incorporating news sentiment and technical overlays.")

class AdvisorCritique(BaseModel):
    approved: bool = Field(description="True if the analyst's proposal satisfies all strict rules. False if any rule is violated.")
    feedback: str = Field(description="Detailed critique explaining which rules were satisfied and which were violated.")
    suggested_allocations: Optional[List[TargetAllocation]] = Field(default=None, description="A revised target allocation proposal if rejected.")


class EscalationChecker(BaseAgent):
    """Checks the advisor's critique. If approved, escalates to break the loop."""
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        critique = ctx.session.state.get("advisor_critique")
        approved = False
        feedback = "No feedback yet."
        if critique:
            if isinstance(critique, dict):
                approved = critique.get("approved", False)
                feedback = critique.get("feedback", "No feedback yet.")
            else:
                approved = getattr(critique, "approved", False)
                feedback = getattr(critique, "feedback", "No feedback yet.")

        if approved:
            print(f"🚨 {CLR_BOLD}{CLR_RED}########################## ESCALATION_CHECKER ##########################{CLR_RESET}")
            print(f"Critique {CLR_BOLD}{CLR_GREEN}APPROVED{CLR_RESET}. Feedback: {feedback}")
            print("Escalating to break loop...")
            print(f"{CLR_RED}###########################################################################{CLR_RESET}\n")
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            print(f"🚨 {CLR_BOLD}{CLR_RED}########################## ESCALATION_CHECKER ##########################{CLR_RESET}")
            print(f"Critique {CLR_BOLD}{CLR_RED}REJECTED{CLR_RESET}. Continuing loop. Feedback: {feedback}")
            print(f"{CLR_RED}###########################################################################{CLR_RESET}\n")
            yield Event(author=self.name)


portfolio_analyst = Agent(
    name="portfolio_analyst",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=ANALYST_INSTRUCTION,
    output_schema=AnalystProposal,
    output_key="analyst_proposal",
)

senior_risk_advisor = Agent(
    name="senior_risk_advisor",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SENIOR_ADVISOR_INSTRUCTION,
    output_schema=AdvisorCritique,
    output_key="advisor_critique",
)

escalation_checker = EscalationChecker(name="escalation_checker")

portfolio_stabilizer_loop = LoopAgent(
    name="portfolio_stabilizer_loop",
    sub_agents=[portfolio_analyst, senior_risk_advisor, escalation_checker],
    max_iterations=5,
)

async def financial_analysis_pipeline(
    ranked_portfolio: list, 
    graveyard_rows: list | None = None, 
    dataset_id: str = "portfolio_analytics"
) -> list:
    """Runs a multi-agent critique debate loop to finalize stock allocations,
    then executes trades using ExecutionController and logs snapshot/trades to BigQuery."""
    from app.tools.bigquery_service import get_historical_metrics
    from app.execution import ExecutionController
    from app.tools.robinhood_service import fetch_robinhood_portfolio_state

    # 1. Fetch weekly historical signals log
    weekly_metrics = get_historical_metrics(days=7, dataset_id=dataset_id)
    
    # Clear INTEGRATION_TEST to allow the Robinhood MCP toolset to connect
    if "INTEGRATION_TEST" in os.environ:
        del os.environ["INTEGRATION_TEST"]

    # Resolve target account ending in 48661 from environment variables
    account_number = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER")
    if not account_number:
        if os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true":
            account_number = "MOCK_ACCOUNT_48661"
        else:
            raise RuntimeError("Security Guardrail: ROBINHOOD_ACCOUNT_NUMBER environment variable is not set.")

    if not account_number or not str(account_number).endswith("48661"):
        raise RuntimeError(f"Security Guardrail: Unauthorized Robinhood account '{account_number}'. All operations restricted to accounts ending in 48661.")

    # 2. Fetch current holdings and cash from Robinhood to initialize loop state
    print("\nFetching current portfolio state from Robinhood...")
    total_cash, buying_power, holdings = await fetch_robinhood_portfolio_state(account_number)

    # Compute starting Total Equity and weights
    holdings_value = sum(h["equity"] for h in holdings)
    total_equity = total_cash + holdings_value
    current_cash_pct = (total_cash / total_equity) * 100 if total_equity > 0 else 0.0

    is_dry_run = os.environ.get("SKIP_LIVE_TRADES", "false").lower() == "true"
    
    # Calculate days_held for each holding from trade history
    from app.tools.bigquery_service import get_last_buy_timestamp, get_recent_trades
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    holdings_with_days = []
    for h in holdings:
        last_buy = get_last_buy_timestamp(h["symbol"], dry_run=is_dry_run, dataset_id=dataset_id)
        if last_buy:
            if last_buy.tzinfo is None:
                last_buy = last_buy.replace(tzinfo=timezone.utc)
            days_held = (now - last_buy).days
        else:
            days_held = 999  # Long term or no history
        
        holdings_with_days.append({
            "symbol": h["symbol"],
            "shares": h["shares"],
            "current_price": h["current_price"],
            "equity": h["equity"],
            "weight_pct": f"{(h['equity']/total_equity)*100:.1f}%" if total_equity > 0 else "0.0%",
            "days_held": days_held
        })
    current_holdings_str = str(holdings_with_days)

    # Fetch recent trades history
    recent_trades = get_recent_trades(limit=10, dry_run=is_dry_run, dataset_id=dataset_id)
    recent_trades_str = str(recent_trades) if recent_trades else "No recent trade history found."

    # Build active watchlist summary containing EWMA, drawdown, volatility, and technicals
    watchlist_summary = str([{
        "ticker": item["ticker"],
        "conviction_score": item["raw_score"],
        "sentiment_ewma_5d": item.get("sentiment_ewma"),
        "sentiment_volatility_5d": item.get("sentiment_volatility"),
        "drawdown_pct": item.get("drawdown_pct"),
        "sustained_rsi_drop": item.get("sustained_rsi_drop"),
        "rsi": item.get("rsi"),
        "macd": item.get("macd"),
        "macd_signal": item.get("macd_signal")
    } for item in ranked_portfolio])

    print(f"   Current Cash: {CLR_GREEN}${total_cash:.2f}{CLR_RESET}")
    print(f"   Current Holdings: {CLR_BOLD}{current_holdings_str}{CLR_RESET}")
    print(f"   Recent Trades: {recent_trades_str}")
    print(f"   Total Equity: {CLR_BOLD}{CLR_GREEN}${total_equity:.2f}{CLR_RESET}")

    # 3. Initialize loop session state and run the Multi-Agent Loop
    print(f"\n{CLR_BOLD}{CLR_CYAN}🔄 [PHASE: 4. Entering Multi-Agent Portfolio Debate Loop]{CLR_RESET}")
    print(f"   Initializing debate loop with {CLR_BOLD}{CLR_MAGENTA}PORTFOLIO_ANALYST{CLR_RESET}, {CLR_BOLD}{CLR_YELLOW}SENIOR_RISK_ADVISOR{CLR_RESET}, and {CLR_BOLD}{CLR_RED}ESCALATION_CHECKER{CLR_RESET}...")

    print(f"\n📊 {CLR_BOLD}{CLR_CYAN}" + "#" * 26 + " INPUT_CONTEXT " + "#" * 26 + f"{CLR_RESET}")
    print(f"   - Total Equity: {CLR_BOLD}{CLR_GREEN}${total_equity:.2f}{CLR_RESET}")
    print(f"   - Current Cash: {CLR_GREEN}${total_cash:.2f}{CLR_RESET} ({current_cash_pct:.1f}% of total equity)")
    print(f"   - Current Holdings (with days_held): {current_holdings_str}")
    print(f"   - Recent Trades: {recent_trades_str}")
    print(f"   - Watchlist Metrics: {watchlist_summary}")
    print(f"{CLR_BOLD}{CLR_CYAN}" + "#" * 69 + f"{CLR_RESET}\n")

    session_service = InMemorySessionService()
    initial_state = {
        "total_equity": f"{total_equity:.2f}",
        "current_cash": f"{total_cash:.2f}",
        "current_cash_pct": f"{current_cash_pct:.1f}",
        "current_holdings": current_holdings_str,
        "recent_trades": recent_trades_str,
        "watchlist_data": watchlist_summary,
        "ranked_portfolio": str(ranked_portfolio),
        "weekly_metrics": str(weekly_metrics),
        "advisor_critique": "No previous critique. This is your first proposal."
    }
    session = await session_service.create_session(
        user_id="cron_job",
        app_name="trading",
        state=initial_state
    )

    runner = Runner(agent=portfolio_stabilizer_loop, session_service=session_service, app_name="trading")

    async for event in runner.run_async(
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="Please start the debate loop to finalize today's target allocations.")]),
        user_id="cron_job",
        session_id=session.id,
    ):
        if event.content and event.content.parts:
            content_str = "".join([part.text for part in event.content.parts if part.text]).strip()
            if content_str:
                author_name = event.author.upper() if event.author else "SYSTEM"
                if author_name != "ESCALATION_CHECKER":
                    emoji_map = {
                        "PORTFOLIO_ANALYST": "🧐 ",
                        "SENIOR_RISK_ADVISOR": "🛡️ ",
                        "SYSTEM": "⚙️ "
                    }
                    color_map = {
                        "PORTFOLIO_ANALYST": CLR_MAGENTA,
                        "SENIOR_RISK_ADVISOR": CLR_YELLOW,
                        "SYSTEM": CLR_CYAN
                    }
                    emoji = emoji_map.get(author_name, "")
                    color = color_map.get(author_name, CLR_RESET)
                    
                    print(f"{color}########################## {emoji}{author_name} ##########################{CLR_RESET}")
                    print(content_str)
                    print(f"{color}" + "#" * (len(author_name) + len(emoji) + 54) + f"{CLR_RESET}\n")
    print(f"\n{CLR_BOLD}{CLR_CYAN}🔄 [PHASE: 4. Exit (Multi-Agent Loop Finished)]{CLR_RESET}")

    # Retrieve final approved target allocations from the latest session state
    session = await session_service.get_session(user_id="cron_job", session_id=session.id, app_name="trading")
    proposal = session.state.get("analyst_proposal")
    if not proposal:
        print(f"\n{CLR_BOLD}{CLR_RED}[CRITICAL ERROR] Failed to obtain approved portfolio target allocations from the loop agent.{CLR_RESET}")
        return ranked_portfolio

    # Extract allocations and decisions supporting both dictionary and Pydantic formats
    approved_allocations = []
    decisions = []

    if isinstance(proposal, dict):
        allocations_raw = proposal.get("allocations", [])
        for a in allocations_raw:
            if isinstance(a, dict):
                approved_allocations.append({
                    "ticker": a.get("ticker"),
                    "weight_pct": a.get("weight_pct")
                })
            else:
                approved_allocations.append({
                    "ticker": getattr(a, "ticker"),
                    "weight_pct": getattr(a, "weight_pct")
                })
        decisions = proposal.get("decisions", [])
    else:
        allocations_raw = getattr(proposal, "allocations", [])
        for a in allocations_raw:
            approved_allocations.append({
                "ticker": a.ticker,
                "weight_pct": a.weight_pct
            })
        decisions = getattr(proposal, "decisions", [])

    print(f"\n{CLR_BOLD}{CLR_GREEN}Approved target allocations: {approved_allocations}{CLR_RESET}")

    if is_dry_run:
        import json
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dry_run_filename = f"dry_run_results_{timestamp}.json"
        critique = session.state.get("advisor_critique")
        
        proposal_dict = {}
        if proposal:
            if isinstance(proposal, dict):
                proposal_dict = proposal
            else:
                proposal_dict = {
                    "allocations": [
                        {"ticker": a.ticker, "weight_pct": a.weight_pct} for a in getattr(proposal, "allocations", [])
                    ],
                    "decisions": [
                        {"ticker": d.ticker, "signal": d.signal, "thesis": d.thesis} for d in getattr(proposal, "decisions", [])
                    ],
                    "thesis": getattr(proposal, "thesis", "")
                }
        
        critique_dict = {}
        if critique:
            if isinstance(critique, dict):
                critique_dict = critique
            else:
                critique_dict = {
                    "approved": getattr(critique, "approved", False),
                    "feedback": getattr(critique, "feedback", ""),
                    "suggested_allocations": [
                        {"ticker": a.ticker, "weight_pct": a.weight_pct} for a in getattr(critique, "suggested_allocations", []) or []
                    ]
                }
                
        dry_run_data = {
            "timestamp": datetime.now().isoformat(),
            "target_allocations": approved_allocations,
            "analyst_proposal": proposal_dict,
            "advisor_critique": critique_dict
        }
        
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", dry_run_filename)
            with open(filepath, "w") as f:
                json.dump(dry_run_data, f, indent=2)
            print(f"   {CLR_GREEN}[DRY_RUN] Successfully dumped dry run results to {filepath}{CLR_RESET}")
        except Exception as e:
            print(f"   {CLR_YELLOW}Warning: Failed to dump dry run results: {e}{CLR_RESET}")

    # Map decisions (signal/thesis) and target weight allocations back to ranked_portfolio
    decision_map = {}
    for d in decisions:
        if isinstance(d, dict):
            ticker = d.get("ticker", "").strip().upper()
            signal = d.get("signal", "").strip().upper()
            thesis = d.get("thesis", "")
        else:
            ticker = getattr(d, "ticker", "").strip().upper()
            signal = getattr(d, "signal", "").strip().upper()
            thesis = getattr(d, "thesis", "")
        if ticker:
            decision_map[ticker] = {"signal": signal, "thesis": thesis}

    allocation_map = {a["ticker"].strip().upper(): a["weight_pct"] for a in approved_allocations}

    for item in ranked_portfolio:
        ticker = item["ticker"].strip().upper()
        if ticker in decision_map:
            item["signal"] = decision_map[ticker]["signal"]
            item["thesis"] = decision_map[ticker]["thesis"]
        item["target_weight"] = allocation_map.get(ticker, 0.0)

    # 4. Instantiate ExecutionController and run broker execution
    print(f"\n{CLR_BOLD}{CLR_GREEN}💸 [PHASE: 5. Execution & Portfolio Rebalancing]{CLR_RESET}")
    print(f"   Connecting to Robinhood MCP tools for target account ending in 48661...")
    controller = ExecutionController(toolset=robinhood_toolset, account_number=account_number, dataset_id=dataset_id)
    await controller.execute_rebalance(approved_allocations=approved_allocations)
    print(f"{CLR_BOLD}{CLR_GREEN}💸 [PHASE: 5. Exit]{CLR_RESET}")

    # 5. Log post-trade portfolio snapshot to BigQuery
    print(f"\n{CLR_CYAN}Logging portfolio snapshot to BigQuery...{CLR_RESET}")
    try:
        from app.tools.robinhood_service import log_portfolio_snapshot
        await log_portfolio_snapshot(dataset_id=dataset_id)
        print(f"   {CLR_GREEN}Portfolio snapshot logged successfully.{CLR_RESET}")
    except Exception as e:
        print(f"   {CLR_YELLOW}Warning: Failed to log portfolio snapshot: {e}{CLR_RESET}")

    # 6. Log final unified results to BigQuery
    if graveyard_rows is not None:
        print(f"\n{CLR_CYAN}Logging final signals and unified theses to BigQuery...{CLR_RESET}")
        try:
            from app.tools.bigquery_service import insert_sentiment
            all_rows_to_log = list(ranked_portfolio) + list(graveyard_rows)
            insert_sentiment(all_rows_to_log, dataset_id=dataset_id)
            print(f"   {CLR_GREEN}Unified market metrics and execution logs written to BigQuery successfully.{CLR_RESET}")
        except Exception as e:
            print(f"   {CLR_YELLOW}Warning: Failed to write unified metrics to BigQuery: {e}{CLR_RESET}")

    return ranked_portfolio


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
