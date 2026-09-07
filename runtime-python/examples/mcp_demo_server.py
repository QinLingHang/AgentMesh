from mcp.server import MCPServer
import os

mcp = MCPServer("AgentMesh Demo MCP")


@mcp.tool()
def lookup_weather(city: str) -> dict:
    """Return deterministic demo weather."""
    return {
        "city": city,
        "condition": "sunny",
        "temperatureC": 23,
    }


@mcp.tool()
def calculate_shipping_eta(order_id: str) -> dict:
    """Return deterministic demo shipping ETA."""
    return {
        "orderId": order_id,
        "eta": "2026-09-03",
        "status": "in_transit",
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=int(os.getenv("MCP_DEMO_PORT", "9583")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
