import asyncio
import os
from app.mcp import MCPManager, MCPServerDefinition

async def main():
    server=MCPServerDefinition(id=1,name="Local MCP",endpoint=os.getenv("MCP_DEMO_URL","http://127.0.0.1:9583/mcp"))
    async with MCPManager([server]) as manager:
        tools=await manager.discover(server)
        weather=next(tool for tool in tools if tool.original_tool_name=="lookup_weather")
        print({"tools":[tool.original_tool_name for tool in tools],"weather":await manager.call_tool(weather,{"city":"Shenyang"})})

if __name__=="__main__": asyncio.run(main())
