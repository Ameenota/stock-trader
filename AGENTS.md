# AGENTS.md — Project Context for AI Coding Assistants

## What This Project Is

An **autonomous AI-powered stock trading system** that manages a real-money $100 Robinhood account. It uses Google's Gemini LLMs, the Agent Development Kit (ADK), an MCP server for Robinhood, and BigQuery for data warehousing.

**Live Dashboard**: https://portfolio-dashboard-412197301452.us-central1.run.app

## Two Apps

| App | Path | What It Does |
|-----|------|-------------|
| **Agent** | `agent/` | Daily pipeline: screens stocks → scores sentiment → multi-agent debate → executes trades via Robinhood MCP → logs to BigQuery |
| **Frontend** | `frontend/` | Streamlit dashboard on Cloud Run, queries BigQuery directly (decoupled from Robinhood to avoid auth/MFA issues) |

## Key Files to Read First

| File | Purpose |
|------|---------|
| `agent/app/agent.py` | **Core**: Defines all agents (sentiment, portfolio_analyst, senior_risk_advisor, escalation_checker), the LoopAgent debate loop, Pydantic schemas, and the main `financial_analysis_pipeline()` |
| `agent/run_pipeline.py` | Entry point for running the full daily pipeline |
| `agent/app/tools/` | All tool implementations (data ingestion, ranking, BigQuery, Robinhood MCP, ticker universe) |
| `agent/app/broker_executor.py` | Deterministic trade executor — NOT an LLM agent, pure Python math |
| `frontend/app.py` | Streamlit dashboard entry point |
| `frontend/pages/` | Additional dashboard pages |
| `docs/backlog.md` | Canonical impact-sorted backlog, acceptance criteria, and implementation evidence |
| `docs/p0_live_readiness_implementation_plan.md` | Step-by-step implementation and verification plan for P0 backlog items 1–4 |
| `TODO.md` | Legacy backlog and completed historical items pending migration |
| `README.md` | Full architecture docs with Mermaid diagrams |

## Architecture (5-Phase Daily Pipeline)

```
Phase 1: Pre-screening (Python, 0 LLM tokens)
  40-stock universe → SMA/RSI filter → 10-ticker watchlist

Phase 2: Sentiment Analysis (Gemini Flash)
  Yahoo Finance news → Sentiment Agent scores -1.0 to +1.0 → EWMA decay

Phase 3: Multi-Agent Debate (ADK LoopAgent, max 5 iterations)
  Portfolio Analyst → proposes target allocations %
  Senior Risk Advisor → critiques (approves/rejects with feedback)
  Escalation Checker → breaks loop when approved

Phase 4: Execution (Python, deterministic)
  BrokerExecutor calculates deltas → sells first, then buys via Robinhood MCP

Phase 5: Audit Logging
  All trades, holdings, cash snapshots → BigQuery
```

## Tech Stack

- **Language**: Python 3.12
- **Package Manager**: `uv` (Astral)
- **LLM**: Gemini Flash via Vertex AI
- **Agent Framework**: Google ADK (`LoopAgent`, `BaseAgent`, `Runner`, `InMemorySessionService`)
- **Brokerage**: Robinhood via MCP server (`robinhood_toolset`)
- **Data**: BigQuery (dataset: `portfolio_analytics`, tables: `infrastructure_market_metrics`, `trade_history`, `portfolio_snapshot`)
- **Frontend**: Streamlit + Plotly on Google Cloud Run
- **Deployment**: Agent Runtime (Vertex AI Agent Engine, `us-east1`) via `agents-cli deploy`

## Safety Guardrails

- **Account lock**: Only trades on Robinhood account ending in `48661` (prompt + code-level interceptor callback)
- **`SKIP_LIVE_TRADES=true`**: Dry-run mode, simulates success without real orders
- **Max 3 positions**: ~30% equity each with ±3% tolerance band
- **21-day minimum hold**: Unless 5-day EWMA sentiment < -0.5, a monotonic 3x ATR stop breaches, or the SPY 200-session regime is risk-off
- **Deterministic execution authorization**: Final advisor approval plus the `p0-v1` Python policy is required; sell dates are sell-only and broker/data failures cancel the run
- **Allowed universe**: Only 40 large-cap AI-sector stocks
- **Dual-path entry**: Path A (Value/Dip, ≥10% drawdown) or Path B (Momentum Breakout, 20d high + MACD cross)

## How to Run

```bash
# Setup
cd agent && uv sync

# Run tests
cd agent && PYTHONPATH=. uv run pytest

# Run full pipeline
cd agent && uv run run_pipeline.py

# Run pipeline skipping ingestion (use cached BigQuery data)
cd agent && SKIP_INGESTION=true uv run run_pipeline.py

# Run dashboard locally
cd frontend && uv run streamlit run app.py

# Deploy agent
cd agent && agents-cli deploy
```

## Key Environment Variables

- `GEMINI_API_KEY` — Gemini API key (when not using Vertex AI)
- `ROBINHOOD_MCP_URL` — MCP server URL for Robinhood
- `ROBINHOOD_ACCOUNT_NUMBER` — Must end in `48661`
- `SKIP_LIVE_TRADES` — `true` for dry-run, `false` for real trades
- `SKIP_INGESTION` — `true` to bypass news scraping (use cached BQ data)
- `GOOGLE_CLOUD_PROJECT` — GCP project ID

## Daily Run Reviews

- For questions such as “How did today's run do?”, read and follow `skills/review-stock-trader-run/SKILL.md` completely before reviewing the run.
- Treat scheduler logs in `/tmp/stock-trader` as the sole source for routine run recaps. Do not query BigQuery, Robinhood, or the dashboard unless the user explicitly requests corroboration.
- Keep reviews read-only and distinguish proposed or planned trades from confirmed execution. `REAL_DRY_RUN` never implies a live order was placed.

## Backlog Maintenance

- Treat `docs/backlog.md` as the canonical backlog and read it before planning material trading, risk, execution, evaluation, or operational changes.
- Keep the backlog current in the same change that implements an item: update status, verification evidence, dependencies, and the `Last reviewed` date.
- When investigation or implementation reveals additional work, add it to `docs/backlog.md` at the appropriate impact rank before finishing the task.
- Do not mark an item `Done` until its acceptance criteria are met. Use deterministic tests for code contracts, ADK evals for agent behavior, and walk-forward/backtest evidence for trading-strategy claims.
- Keep `SKIP_LIVE_TRADES=true` while any P0 backlog item is incomplete. Enabling live trades or deploying remains an explicit human-approval action.
