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

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os

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


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        city: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


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

import sys

# Define tools list, conditionally adding robinhood_toolset if not in a test environment
agent_tools = [get_weather, get_current_time]
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
