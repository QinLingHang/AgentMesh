# AgentMesh Development Roadmap

The public `v1.0.0-rc.2` release remains frozen. Development continues on unreleased sprint branches until the planned platform capabilities and final cloud acceptance are complete.

## Completed foundation

- Agent Runtime / Multi-Agent / DAG
- Text RAG / Hybrid Retrieval / Rerank / Citation
- Memory
- Tool / MCP / Secure Action
- Evaluation / Adaptive Routing
- Durable Queue / Worker Lease / Fencing
- Organization / Project / RBAC / BYOK / Quota
- Production migration / gateway / HTTPS topology
- Browser E2E / release hygiene

## V2 — Intelligence & Multimodal — CLOSED

- Multi-modal Knowledge
- PDF / Image ingestion
- Vision Runtime
- TEXT / VISUAL / HYBRID Retrieval
- Multi-modal Citation
- Advanced Evaluation / Judge
- Token / Cost Accounting
- Advanced Observability

V2 completed independent automated acceptance before being merged into `develop`.

## V3 — Distributed Runtime / Multi-node / HA — CLOSED

- Worker Horizontal Scaling
- Multi-node Runtime
- Node Registration / Discovery
- Worker + Node Capacity-aware Scheduling
- Dispatcher HA Lease / Epoch
- Cross-node Lease / Fencing
- Safe Worker-loss Reassignment
- Fail-closed Ambiguous Execution Boundary
- Control-plane Request HA overlay
- Distributed Runtime topology and metrics
- Multi-node failover acceptance

V3 completed independent automated acceptance before being merged into `develop`.

## V4 — Platform Ecosystem — CURRENT

- Public API / Project-scoped Service Account
- Scope / revoke / expiration / API usage
- Durable Idempotency-Key semantics
- Python + TypeScript SDK
- Agent Marketplace
- Agent Versioning / Installation
- MCP / Plugin Registry
- Manifest / Endpoint / Permission Governance
- Publisher / Import / Export
- Ecosystem Browser / SDK acceptance

## Final Production Closure

- Cloud multi-node deployment
- Public domain / HTTPS
- Load / capacity validation
- Monitoring / alerting
- Backup / restore / disaster recovery
- Stateful dependency HA validation
- Full security / privacy / release validation
- Final public Release
