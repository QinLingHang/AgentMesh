from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import FastAPI


app = FastAPI(title="AgentMesh Local HTTP Tool Demo")


@app.post("/tool/echo")
async def echo(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "echo": payload,
        "source": "agentmesh-local-http-tool",
    }


@app.post("/tool/order-status")
async def order_status(payload: dict[str, Any]) -> dict[str, Any]:
    order_id = str(payload.get("order_id") or payload.get("orderId") or "ORD-1001")
    return {
        "orderId": order_id,
        "status": "PAID",
        "refundable": True,
        "source": "agentmesh-local-http-tool",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HTTP_TOOL_DEMO_HOST", "127.0.0.1"),
        port=int(os.getenv("HTTP_TOOL_DEMO_PORT", "9584")),
    )
