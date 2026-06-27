# Autonomous Stock Trader: End-to-End Agentic Portfolio Manager

This repository contains the **Autonomous Stock Trader**, a fully automated trading and portfolio management system built as a Capstone submission for Google's **5-Day AI Agents Intensive Vibe Coding Course**. 

The system leverages Google's Gemini models, the Agent Development Kit (ADK), Model Context Protocol (MCP) servers, and BigQuery data warehousing to evaluate market signals, manage risk, execute trades with real $$ on a $100 Robinhood account, and visualize performance in near real-time.

- **Kaggle Contest**: [Google AI Agents Intensive Capstone Project](https://www.kaggle.com/competitions/5-day-ai-agents-intensive-vibecoding-course-with-google)
- **Live Deployed Dashboard**: [Streamlit Portfolio Dashboard](https://portfolio-dashboard-412197301452.us-central1.run.app)

---

## 🏗️ Project Architecture & Data Flow

Below is the end-to-end architecture showing how market data ingestion, sentiment analysis, risk limits, sandbox execution, audit logging, and the frontend dashboard are decoupled to prevent authentication blockages.

```mermaid
graph TD
    News[Yahoo Finance API] -->|News & Price Metrics| SA[Sentiment Analysis Agent - Gemini]
    SA -->|LLM Sentiment Scores| PR[Deterministic Python Ranking Logic]
    PR -->|Signal & conviction ranking| BQ1[(BigQuery: infrastructure_market_metrics)]
    
    subgraph MultiAgentLoop ["Multi-Agent Critique Loop (ADK LoopAgent)"]
        PA[Portfolio Analyst Agent - Gemini] -->|Proposes draft TargetAllocations %| SRA[Senior Risk Advisor Critic - Gemini]
        SRA -->|Returns AdvisorCritique structured review| PA
        SRA -->|Approved / Feedback| EC[Escalation Checker BaseAgent]
    end
    
    BQ1 -->|Weekly Historical Metrics| PA
    LiveBroker[Live Cash & Holdings from Robinhood] -->|Starts state inputs| PA
    
    EC -->|Final Approved target weights %| Exec[Deterministic Python Execution Controller]
    Exec -->|1. Calculates Deltas & enforces tolerance ranges| Guardrail[Double Guardrails & Dry-run Interceptor]
    Guardrail -->|2. Places sequentially sells then buys| MCP[Robinhood MCP Server]
    
    Exec -->|Logs Trades| BQ2[(BigQuery: trade_history)]
    Exec -->|Logs Holdings & Cash| BQ3[(BigQuery: portfolio_snapshot)]
    
    subgraph BQ_Warehouse ["BigQuery Data Warehouse"]
        BQ1
        BQ2
        BQ3
    end
    
    Streamlit[Streamlit Dashboard] -->|Queries| BQ_Warehouse
```

---

## 💡 Contest Writeup: Project Evaluation & Design

### 1. Overview 
* **The Problem**: Executing algorithmic trades directly based on raw LLM reasoning is highly risky (hallucinations, over-leveraging, target account confusion). Furthermore, querying brokerages in real-time on dashboards frequently fails due to session expirations or MFA blockages.
* **Our Thin Vertical Slice**: We designed a daily pipeline that automatically ingests tech news, scores sentiment using Gemini, applies deterministic risk checks, triggers a trading agent to execute queued orders via an MCP server on a $100 Robinhood account, logs states to BigQuery, and serves a decoupled, dark-themed Streamlit dashboard.
* **Target Audience**: Retail investors seeking safe, autonomous, AI-driven portfolio rebalancing with high observability.

### 2. Course Topics Demonstrated
* **Multi-Agent Coordination & ADK**: We decoupled logic into three specialized agents coordinated within a native ADK `LoopAgent` debate loop:
  - `sentiment_agent`: Analyzes market news and computes sentiment scores.
  - `portfolio_analyst`: Evaluates technical scores and conviction, proposing a target portfolio allocation (in percentages).
  - `senior_risk_advisor`: Reviews proposals as a critic, ensuring budget limits and technical entry thresholds are respected.
  - `escalation_checker`: Custom python agent that breaks the debate loop once a proposal is approved.
  - **Decoupled Execution**: Execution logic is fully separated into a deterministic Python controller (`ExecutionController`), keeping brokerage calls completely isolated from LLM agents.
* **Model Context Protocol (MCP)**: The deterministic execution layer uses an active Robinhood MCP server to run queries (`get_portfolio`, `get_equity_positions`) and order tools (`place_equity_order`).
* **Double Account Guardrails & Interceptor Callback**:
  - *Prompt Protection*: Instructs the agent to only target the account ending in `48661`.
  - *Code Interceptor*: A Python callback inspects all tool arguments in real-time, blocking unauthorized assets, enforcing account validation, and returning simulated success packets when dry-run mode (`SKIP_LIVE_TRADES=true`) is active.
* **Telemetry & Decoupled Audit Logging (BigQuery)**: All daily recommendations, executed trades, and account equity/cash snapshots are written to GCP BigQuery. The Streamlit dashboard queries BigQuery directly, completely bypassing Robinhood at render time to prevent authentication blocks.

---

## 🚦 Architectural Constraints & Asset Screener
* **Allowed Ticker Universe**: Restricts trade execution to a centralized **40-stock universe** of liquid, large-cap AI core (NVDA, AMD, AVGO), chip foundry/memory (TSM, MU, ASML), cloud providers (MSFT, GOOGL, AMZN), grid power utilities (CEG, VST, ETN), and enterprise AI software/security (PLTR, CRWD) stocks.
* **Dynamic Active Watchlist**: A python-based pre-screener dynamically constructs the daily active list of 10 tickers from the 40-stock universe:
  1. It fetches current portfolio holdings from BigQuery and forces them to be on the watchlist so they are monitored for hold/sell decisions.
  2. It downloads price history for candidates and filters out stocks trading below their **50-day Simple Moving Average (SMA)**.
  3. It ranks remaining candidates by trend momentum ($\text{price} / \text{50-day SMA}$) and selects the top performers, padding with core defaults as needed.
* **Token & Cost Efficiency**: The heavy news scraping and LLM sentiment analysis are run **only** on the dynamically generated 10 active tickers (using 0 LLM tokens during screening), keeping API costs low and predictable.
* **Sandbox Limit**: Execution budget capped at **$100** total starting equity.
* **Traceability**: All execution steps, reasoning strings, and account snapshots must be logged to BigQuery.
  
---

## 🧠 Financial Analyst Logic (How It Works)

The pipeline employs a **three-stage quantitative & qualitative funnel** to filter, narrow down, and execute trades on stocks in a cost-efficient manner.

```mermaid
graph TD
    A["Central Allow List (40 AI Tickers)"] -->|"Stage 1: Technical Screening (Free)"| B["Daily Watchlist (10 Tickers)"]
    B -->|"Stage 2: Sentiment Analysis (LLM)"| C["Conviction Ranking (1-10)"]
    C -->|"Stage 3: Timing & Crossovers (RSI/MACD)"| D["Execution Decisions (Buy/Sell/Hold)"]
```

### Stage 1: Technical Screening & Filtering
Every day, a lightweight Python pre-screener scans the 40 stocks in the centralized allowed universe. This scan uses raw price data via `yfinance` (**0 LLM tokens**):
1.  **Holdings Override**: It checks the latest BigQuery portfolio snapshot. Any stock we currently own is automatically promoted to the watchlist so it is monitored for hold/sell decisions.
2.  **SMA Trend Filter**: Non-owned candidate stocks are filtered out if they are trading below their **50-day Simple Moving Average (SMA)**, avoiding declining stocks.
3.  **Momentum Ranking**: The remaining candidates are scored by trend momentum ($\text{price} / \text{50-day SMA}$). The top performers are selected to fill the remaining slots.
4.  **Watchlist Padding**: If fewer than 10 stocks pass, core defaults (like `NVDA`, `AMD`, and the hedge `TLT`) pad the list to ensure exactly **10 active tickers** are analyzed.

### Stage 2: Sentiment Analysis
The pipeline fetches the latest 24 hours of news for the 10 active watchlist tickers and passes it to the **Sentiment Agent** (Gemini-Flash):
*   **Conviction Score**: The agent assigns a raw sentiment score from `-1.0` (highly bearish news) to `+1.0` (highly bullish news).
*   **Deterministic Sorting**: Python code sorts the assets by sentiment score and assigns a relative rank from `1` (lowest score) to `10` (highest score).
*   **Core Signals**:
    *   **LIQUIDATE**: Assigned to bottom-ranked assets (Ranks 1, 2, 3).
    *   **STRONG BUY**: Assigned to top-ranked assets (Ranks 4-10) only if the sentiment score exceeds `0.2`.
    *   **HOLD**: Assigned to top-ranked assets with flat/uncertain sentiment scores ($\le 0.2$).

### Stage 3: Multi-Agent Critique Loop & Decoupled Execution
Instead of executing trades directly from LLM prompts, the target state is debated and finalized by a multi-agent critique loop, then executed deterministically:
1. **Portfolio Analyst Agent**: Proposes target stock allocations (percentages of total equity) based on today's watchlist and weekly metrics.
2. **Senior Risk Advisor Agent (Critic)**: Enforces strict trading rules and risk mandates:
   * **Value Entries**: Approve and prioritize entries for assets experiencing a drawdown of **10% or more** from their 52-week high, provided their 5-day Exponential Moving Average (EWMA) sentiment remains bullish (`EWMA > 0.1`).
   * **Volatility Rejection**: Reject any new allocations into assets where the sentiment volatility (5-day standard deviation) is exceptionally high (`volatility > 0.4`), preventing exposure to speculative binary news events.
   * **Minimum Holding Period**: Protect existing positions by rejecting any proposal to sell or liquidate an asset if its `days_held < 21 days`, unless its weekly sentiment EWMA falls below `-0.5`.
   * **Cash and Position Sizing**: Enforces a target cash buffer of 10% of total equity (5%-15% tolerance range) and a position tolerance of +/- 3% to prevent minor portfolio churn.
3. **Escalation Checker**: Custom `BaseAgent` that terminates the LoopAgent when the proposal receives approval from the Advisor.
4. **Execution Controller**: Evaluates target weights vs current holdings and schedules trades sequentially (sells first, then buys) via the Robinhood MCP server.

---

## 🛠️ Deployed Streamlit Dashboard
The frontend runs as a containerized service deployed to **Google Cloud Run**.
- **Live URL**: [https://portfolio-dashboard-412197301452.us-central1.run.app](https://portfolio-dashboard-412197301452.us-central1.run.app)

---

## 🚀 Running the Pipeline & Deployment

This section provides all necessary setup, run, and deployment details to run the system or continue development.

### 📦 Prerequisites & Local Installation

1. **Install uv**: Install Astral's fast Python package manager and installer:
   - **macOS/Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - **Windows (PowerShell)**: `irm https://astral.sh/uv/install.ps1 | iex`
   - **Homebrew**: `brew install uv`
2. **Install Google Cloud SDK**: Required for database interactions (BigQuery) and frontend hosting (Cloud Run):
   - Follow instructions on [Google Cloud SDK installation](https://cloud.google.com/sdk/docs/install).
3. **Install Vertex AI Agent CLI (agents-cli)**: Required for backend agent deployment:
   ```bash
   uv tool install google-agents-cli
   ```
4. **Compile / Synchronize Virtual Environment**: Set up the local Python 3.12 environment, locking dependencies and checking for type/package consistency:
   ```bash
   cd agent
   uv sync
   ```
2. **Environment Variables**: Create a `.env` file in the project root or copy the template:
   ```ini
   # Vertex AI or Gemini API key configuration
   GEMINI_API_KEY=your_gemini_api_key_here
   
   # Robinhood MCP parameters
   ROBINHOOD_MCP_URL=http://localhost:8000/robinhood
   ROBINHOOD_ACCOUNT_NUMBER=XXXXX48661  # Security guardrail target account
   
   # Execution Flags
   SKIP_LIVE_TRADES=true   # Set to false to perform real trades
   SKIP_INGESTION=false    # Set to true to query today's BQ logs instead of re-scraping yfinance
   ```

### 🚦 Running the Code

* **Run pytest Suite**: Verify code health and imports.
  ```bash
  cd agent
  uv run python -m pytest
  ```
* **Run Daily Ingestion & Trading Pipeline**: Runs technical screening, news scraping, LLM sentiment ranking, LoopAgent rebalancing debate, and sequential order execution:
  ```bash
  cd agent
  uv run run_pipeline.py
  ```
* **Run Pipeline Skipping Ingestion (Dry-run Debugging)**: Bypass scraping and go straight to execution using cached today's BigQuery metrics:
  ```bash
  cd agent
  SKIP_INGESTION=true uv run run_pipeline.py
  ```
* **Run Streamlit Dashboard Locally**:
  ```bash
  cd frontend
  uv run streamlit run app.py
  ```

---

### 🌐 Cloud Deployment

#### 1. Backend Agent (Agent Runtime)
The trading agent orchestrator is built using the Vertex AI Agent Development Kit (ADK). The deployment target is **Agent Runtime** (Vertex AI Agent Engine) under region `us-east1` as specified in `agent/agents-cli-manifest.yaml`.

* **Prerequisite**: Install `agents-cli` globally:
  ```bash
  uv tool install google-agents-cli
  ```
* **Deploy Command**:
  ```bash
  cd agent
  agents-cli deploy
  ```

#### 2. Frontend Dashboard (Google Cloud Run)
The frontend Streamlit app is containerized via `frontend/Dockerfile` and serves on port `8080`.

* **Build & Deploy Command**:
  ```bash
  # Deploy directly from source directory
  gcloud run deploy portfolio-dashboard \
    --source ./frontend \
    --region us-central1 \
    --allow-unauthenticated
  ```
* **GCP Infrastructure & Data Warehouse (BigQuery)**:
  - BigQuery Dataset: `portfolio_analytics`
  - Tables:
    * `infrastructure_market_metrics`: Daily watches, technical indicators (RSI/MACD/SMA), and Gemini sentiment analysis outputs.
    * `trade_history`: Detailed execution logs of sequential orders.
    * `portfolio_snapshot`: Portfolio total equity, cash, and JSON-encoded holdings.
  - Initialized automatically on startup via `setup_bigquery()` in [bigquery_service.py](file:///Users/sagar/Documents/ML/stock-trader/agent/app/tools/bigquery_service.py).
  - IAM Permissions: Make sure the service account running the Cloud Run Streamlit dashboard has `BigQuery Admin` or `BigQuery Data Editor` + `BigQuery Job User` roles.

---

## 📋 Open TODO List 

To complete your Kaggle Capstone Project submission, you must perform the following actions:

- [ ] **Record a Demo Video**:
  Record a 5-10 minute video showing:
  1. The code structure and dual-agent prompt setups.
  2. The BigQuery tables capturing signal logs and trade history.
  3. The live Streamlit dashboard showing allocations and executed trade logs.
- [ ] **Publish Walkthrough Link**:
  Upload the demo video (to YouTube, Loom, or Drive) and replace `[Insert Link to Your Recorded Walkthrough Video Here]` at the top of this README.
- [ ] **Post Submission Writeup on Kaggle**:
  Submit your Capstone write-up under the [Kaggle Capstone Project Discussion Forum](https://www.kaggle.com/competitions/5-day-ai-agents-intensive-vibecoding-course-with-google/discussion/709721) by creating a post containing this write-up, linking to this repository and your live dashboard URL.

## 🔮 Future Improvements

- [x] **Plot Agent's Alpha Against S&P 500 (SPY)**:
  Compare the agent's overall return against the S&P 500 index.
  * *Data Ingestion*: Add `SPY` to the daily data downloads in the pipeline.
  * *Dashboard Update*: Upgrade the portfolio performance chart in `app.py`. Query the total portfolio value history from BigQuery, fetch daily closing prices of `SPY` from `yfinance` for the same date range, normalize both starting values to 100 on Day 1, and plot them on a single line chart (Streamlit/Plotly) for visual benchmark comparison.
- [ ] **Headless Cloud Function Auth Migration**:
  Migrate the Robinhood MCP authentication mechanism to work in a serverless, headless GCP Cloud Function environment.
  * *Secret Storage*: Upload the local `~/.mcp-auth/` credentials (`tokens.json` and `client_info.json`) to Google Cloud Secret Manager.
  * *Function Startup*: Configure the Cloud Function to redirect the `HOME` directory to `/tmp`, pull the credentials from Secret Manager at startup, and write them into `/tmp/.mcp-auth/` so `mcp-remote` can authenticate without interactive browser checks.
  * *Refresh Sync*: Implement a post-run sync that uploads the refreshed token file back to Secret Manager to handle single-use refresh token expiration.
- [ ] **Reconciliation & Status Sync**: Query Robinhood orders via MCP post-execution to update local database logs with true execution status (filled vs. cancelled), actual filled share amounts, and final execution prices, rather than only displaying the submitted details.
- [x] **Hysteresis & Swap Buffer**: Only swap an existing holding if the new opportunity has a significantly higher conviction score (e.g., delta > 0.3) to prevent marginal churn.
  * *Rationale*: Prevents excessive trading churn, tax drag, and transaction friction caused by swapping assets due to tiny sentiment fluctuations (e.g. minor 0.05 sentiment delta).
  * *Implementation*: Enforced via **Rule 10** in `TRADING_AGENT_INSTRUCTION` inside [agent.py](file:///Users/sagar/Documents/ML/stock-trader/agent/app/agent.py), forcing the execution agent to check that the score delta is strictly greater than 0.3 before trading.
- [ ] **Minimum Holding Period**: Enforce a minimum holding time of 3-5 trading days for newly purchased assets before they can be sold, protecting the portfolio from day-to-day news noise (except during extreme bearish signals < -0.5).

*  # Redacted target account format: select account ending in 48661
        account_number = "XXXXX48661"  # Default fallback.. is this safe?


Issues & Recommendations
AnalystProposal is defined twice — you redeclare the class at line ~148 with an added decisions field, silently shadowing the first definition. Python won't error, but this is a latent bug that will confuse anyone reading the code. Remove the first definition entirely.

Prompt templates use string interpolation with .format() implicitly but aren't actually formatted — ANALYST_INSTRUCTION contains {total_equity}, {ranked_portfolio}, etc., but these are passed as static strings to Agent(instruction=...). The actual runtime values from session.state are never injected. You need to either:

Build the instruction dynamically inside financial_analysis_pipeline() using .format(**initial_state), or

Use ADK's session state templating if supported (verify in your ADK version)

analyze_and_rank_portfolio creates a new Runner/InMemorySessionService on every call — this works but is heavyweight. If this tool is called repeatedly, consider a shared session pool or passing the parent runner's session service.

LAST_TRADING_DECISIONS = [] is declared but never used — remove dead code to reduce confusion.

sys import is mid-file — import sys appears after substantial class definitions. Move all stdlib imports to the top with the other imports.

root_agent instruction is a generic placeholder — "You are a helpful AI assistant..." doesn't describe its actual role as a trading orchestrator. This matters because the model uses the instruction to decide when/how to invoke analyze_and_rank_portfolio and the Robinhood toolset.

No retry/fallback if the loop hits max_iterations without approval — currently financial_analysis_pipeline() just returns ranked_portfolio with a critical error log but continues to ExecutionController. You should either raise an exception or short-circuit before calling execute_rebalance if proposal is None.

