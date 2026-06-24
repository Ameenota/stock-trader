# AI Infrastructure Analyst

This repository contains the **AI Infrastructure Analyst**, an autonomous trading system built for a **Kaggle Capstone** project. The system integrates Google's Gemini models with deterministic Python logic to evaluate market news, rank key technology/AI assets, log trading decisions, execute transactions in a sandbox environment, and visualize performance.

```mermaid
graph TD
    News[Market News API / Feeds] -->|Raw News| Agent[AI Infrastructure Analyst Agent]
    subgraph Agent Backend
        Agent -->|1. LLM Analysis| Gemini[Gemini API]
        Agent -->|2. Ranking Logic| Python[Deterministic Python Logic]
    end
    Agent -->|3. Log Decisions| BQ[(BigQuery)]
    Agent -->|4. Execute Trades| MCP[Robinhood MCP Server]
    MCP -->|Transactions| RH[Robinhood $100 Sandbox]
    BQ -->|Metrics & Decisions| Streamlit[Streamlit Dashboard]
```

---

## 🏗️ Project Architecture

The system consists of the following decoupled components:

1. **Market News Ingestion**: Automatically fetches real-time financial news and market updates.
2. **AI Infrastructure Analyst (Agent Backend)**:
   * **Gemini LLM**: Performs semantic analysis, sentiment evaluation, and hypothesis generation from the ingested news.
   * **Deterministic Python Logic**: Implements rigid risk management, constraints, and deterministic rules to rank and select trades.
3. **Target Assets**: The portfolio is strictly constrained to **10 specific assets**:
   * **9 AI/Tech Stocks**: Key drivers of the AI hardware and software infrastructure stack (e.g., NVDA, MSFT, GOOGL, AMZN, META, AVGO, TSLA, ASML, AMD).
   * **1 Treasury Hedge**: A safe-haven hedge asset (e.g., TLT or SHY) to manage system-wide market risk.
4. **Execution Layer**: Executes market decisions on a **$100 Robinhood sandbox** via a Model Context Protocol (MCP) server.
5. **Observability & Logging**: Persists all analytical outputs, agent prompts, and executed trades to **Google Cloud BigQuery** for auditing and model evaluation.
6. **Visualization**: A **Streamlit Dashboard** that reads historical trade logs and decisions from BigQuery to render real-time performance, portfolio allocations, and analytics.

---

## 🚦 Architectural Constraints & Agent Instructions

> [!IMPORTANT]
> **CRITICAL INSTRUCTIONS FOR ALL FUTURE AI AGENTS:**
> You must strictly adhere to the architectural constraints outlined in this document. Any modification to the core architecture (e.g., changing the asset universe, bypassing BigQuery, or altering the execution sandbox) requires an update to this section.

* **Asset Universe Constraint**: The agent must *only* trade or rank the 10 selected assets (9 AI stocks + 1 Treasury hedge). Do not add other equities or cryptocurrencies.
* **Sandbox Limit**: The execution layer must target the simulated Robinhood MCP sandbox, capped at a virtual starting capital of **$100**. Never route live funds or exceed this sandbox budget.
* **Deterministic Fallbacks**: Trading decisions must be filtered through deterministic Python logic after Gemini's analysis. An LLM must never have direct, unconstrained access to execute trades without validation rules.
* **Traceability**: Every transaction and ranking decision must be logged to BigQuery. Silent executions or bypasses are not permitted.
* **Documentation Rule**: If any core architectural decisions change during development, you **MUST** update this README to reflect the new state.

---

## 🛠️ Getting Started

### Prerequisites
* Python 3.10+
* `uv` package manager installed
* Google Cloud CLI (`gcloud`) authenticated (for BigQuery access)

### Installation
1. Clone the repository and navigate to the project directory.
2. Create your `.env` file at the root:
   ```bash
   cp .env.example .env
   ```
3. Populate `.env` with your API keys:
   * `GEMINI_API_KEY`: Google AI Studio / Gemini API key.
   * `ROBINHOOD_MCP_URL`: Endpoint for your active Robinhood MCP server.

4. Install the agent dependencies:
   ```bash
   cd agent
   agents-cli install
   ```

5. Run the local agent playground:
   ```bash
   agents-cli playground
   ```
