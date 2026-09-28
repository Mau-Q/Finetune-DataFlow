"""Check the local MCP handshake and a real read-only operator-category call."""
import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(t.name == "list_operator_categories" for t in tools.tools)
            result = await session.call_tool("list_operator_categories", {})
            assert not result.isError, result
            print(json.dumps({"tools": len(tools.tools), "categories": result.model_dump(), "status": "PASS"}, ensure_ascii=False, indent=2))


asyncio.run(main())
