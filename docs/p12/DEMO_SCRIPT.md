# AgentMesh v1.0 Demo Script

Target duration: 8–12 minutes.

## 1. Opening — 30 seconds

Introduce AgentMesh as a multi-stack Agent platform:

```text
Go Control Plane
+ Python Agent Runtime
+ React/TypeScript Product UI
+ MySQL / Redis / Milvus
```

State the design goal: not a single chatbot, but a Project-scoped Agent execution
platform with Knowledge, Memory, Tool/MCP, governance, distributed runtime and
production operations.

## 2. Workspace and Project — 1 minute

- sign in;
- open a Project;
- show Project Runtime bindings;
- explain Project as the execution/governance boundary.

Key sentence:

> Project controls Runtime/Agent/Tool/MCP/Knowledge, while long-term Memory remains user-global.

## 3. Agent execution and Run Details — 2 minutes

- run a representative task;
- show final answer separately from Run Details;
- open DAG/Trace/observability;
- point out latency/cost/token/tool evidence;
- show that execution details do not pollute the clean answer workspace.

## 4. Knowledge + Memory — 1.5 minutes

- show Project Knowledge;
- show user-global Memory Center;
- explain retrieval/context boundaries;
- demonstrate that Project Knowledge can be shared without leaking another user's
  GLOBAL Knowledge or Memory.

## 5. Tool / MCP / HITL — 1 minute

- show Tool/MCP registry;
- explain secure action / approval boundary;
- highlight runtime governance before side-effecting actions.

## 6. Enterprise Governance — 2 minutes

Show Governance & Security:

- OWNER / ADMIN / DEVELOPER / VIEWER;
- Organization / Workspace;
- Quota / Usage;
- masked BYOK Secret;
- Project Model Provider;
- Audit Who / What / Result.

Key sentence:

> Shared Project members use the Project owner's configured execution resources, but retain their own user identity and Memory boundary.

## 7. Distributed runtime + production operations — 1 minute

Explain:

- durable queue;
- worker heartbeat;
- lease/fencing;
- idempotency;
- backpressure/recovery;
- `/livez` vs `/readyz`;
- single public Gateway;
- migration job and backup/restore.

## 8. Closing — 30 seconds

Close with the engineering progression:

```text
Agent application
→ Agent platform
→ distributed runtime
→ multi-tenant governance
→ production operations
→ real-browser product E2E
```

Avoid claiming unimplemented Kubernetes/cloud-provider features.
