import asyncio
import logging
import sys
import os
import json
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("check_buying_power")

async def main():
    # Resolve account number from environment or fallback
    account_number = os.environ.get("ROBINHOOD_ACCOUNT_NUMBER", "YOUR_ACCOUNT_NUMBER")
    logger.info(f"Target Account: {account_number}")

    # Connect to Robinhood remote MCP server
    toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mcp-remote", "https://agent.robinhood.com/mcp/trading"]
            ),
            timeout=30.0
        )
    )

    try:
        tools = await toolset.get_tools()
        tools_dict = {t.name: t for t in tools}

        if "get_portfolio" in tools_dict:
            logger.info("Calling get_portfolio...")
            res = await tools_dict["get_portfolio"].run_async(args={"account_number": account_number}, tool_context=None)
            logger.info("Raw response:")
            print(json.dumps(res, indent=2))
        else:
            logger.error("get_portfolio tool not found in MCP server!")
    except Exception as e:
        logger.exception(f"Failed to check buying power: {e}")
    finally:
        await toolset.close()

if __name__ == "__main__":
    asyncio.run(main())
