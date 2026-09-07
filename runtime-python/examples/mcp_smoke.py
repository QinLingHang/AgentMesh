import asyncio
import os
from mcp import Client
from app.mcp.mapper import convert_call_result

async def main():
    async with Client(os.getenv("MCP_DEMO_URL","http://127.0.0.1:9583/mcp"),mode=os.getenv("MCP_CLIENT_MODE","auto")) as client:
        tools=await client.list_tools()
        result=await client.call_tool("lookup_weather",{"city":"Shenyang"})
        print({"mode":os.getenv("MCP_CLIENT_MODE","auto"),"protocol":client.protocol_version,"tools":[tool.name for tool in tools.tools],"weather":convert_call_result(result)})

if __name__=="__main__": asyncio.run(main())
