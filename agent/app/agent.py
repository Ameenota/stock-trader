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
    # 1. Ingest news
    news_dict = ingest_market_news()

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
)

app = App(
    root_agent=root_agent,
    name="app",
)
