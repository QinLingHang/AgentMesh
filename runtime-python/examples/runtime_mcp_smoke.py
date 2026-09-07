from fastapi.testclient import TestClient
from app.main import app

payload={"user_id":1,"request_id":"mcp-smoke","task":"Use the MCP weather tool to check weather for Shenyang",
    "agents":[{"id":1,"name":"General","endpoint":"internal://general","protocol":"internal","capabilities":["general"]}],
    "mcp_servers":[{"id":2,"name":"Local MCP","transport":"streamable_http","endpoint":"http://127.0.0.1:9583/mcp","enabled":True,"connect_timeout_ms":5000,"call_timeout_ms":10000}]}

with TestClient(app) as client:
    response=client.post("/internal/v1/runtime/execute",json=payload,headers={"X-Internal-Token":"change-me-runtime-internal-token"})
    response.raise_for_status();data=response.json()
    print(data["answer"])
    print([(event["kind"],event["title"]) for event in data["trace"] if event["kind"] in {"mcp","model","tool"}])
