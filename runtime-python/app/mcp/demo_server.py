from __future__ import annotations

import os

from mcp.server import MCPServer


mcp = MCPServer("AgentMesh Local Demo MCP")


@mcp.tool()
def lookup_weather(city: str) -> dict:
    """Return deterministic demo weather for local MCP integration testing."""
    return {
        "city": city,
        "condition": "sunny",
        "temperatureC": 23,
        "source": "agentmesh-local-mcp",
    }


@mcp.tool()
def calculate_shipping_eta(order_id: str) -> dict:
    """Return deterministic shipping ETA for local MCP integration testing."""
    return {
        "orderId": order_id,
        "eta": "2026-09-08",
        "status": "in_transit",
        "source": "agentmesh-local-mcp",
    }


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Return deterministic order status for local MCP integration testing."""
    return {
        "orderId": order_id,
        "status": "PAID",
        "refundable": True,
        "source": "agentmesh-local-mcp",
    }


@mcp.tool()
def cancel_order(order_id: str, reason: str = "user_requested") -> dict:
    """Cancel an order. This is a mutating demo action and must require approval."""
    return {
        "orderId": order_id,
        "status": "CANCELED",
        "reason": reason,
        "source": "agentmesh-local-mcp",
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_DEMO_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_DEMO_PORT", "9583")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
