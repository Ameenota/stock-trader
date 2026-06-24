import asyncio
import logging
import sys
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

# Enable debug logging to see full details of the connection attempt
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
logger = logging.getLogger("robinhood_test")

async def test_connection():
    url = "https://agent.robinhood.com/mcp/trading"
    logger.info(f"Connecting to Robinhood MCP via Streamable HTTP: {url}")
    
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=url)
    )
    
    try:
        tools = await toolset.get_tools()
        logger.info(f"Successfully retrieved tools: {len(tools)} tools found.")
        for tool in tools:
            logger.info(f"Tool name: {tool.name}, description: {tool.description}")
    except Exception as e:
        logger.exception(f"Connection failed: {e}")
    finally:
        await toolset.close()

if __name__ == "__main__":
    asyncio.run(test_connection())
