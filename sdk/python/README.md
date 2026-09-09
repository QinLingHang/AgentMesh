# AgentMesh Python SDK

V4 官方 Public API Python 客户端。客户端仅依赖 Python 标准库，不保存 API Key 到磁盘。

```python
from agentmesh import AgentMeshClient

client = AgentMeshClient("https://agentmesh.example.com", "<SERVICE_ACCOUNT_API_KEY>")
run = client.run_task("总结今天的项目风险", idempotency_key="run-2026-09-07-001")
print(run["answer"])
```

Service Account 与 Scope 在 AgentMesh「生态中心 → API 与 SDK」中创建和治理。

测试：

```powershell
cd sdk/python
python -m unittest discover -s tests -p "test_*.py" -v
```
