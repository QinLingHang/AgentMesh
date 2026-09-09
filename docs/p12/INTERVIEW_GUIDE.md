# AgentMesh v1.0 Interview Guide

This document is the interview-facing companion to the P12 release artifacts.
It describes the validated v1.0 platform baseline. Later development branches
(V2/V3/V4 and beyond) should be introduced separately and must not be presented
as if they were already part of the original v1.0 release.

## 1. One-minute project introduction

AgentMesh is a multi-stack Agent platform rather than a single chatbot.

Core stack:

```text
React / TypeScript Product UI
        ↓
Go Control Plane
        ↓
Python Agent Runtime
        ↓
MySQL / Redis / Milvus
```

The platform provides project-scoped Agent execution, Knowledge/RAG, user-global
Memory, Tool/MCP integration, secure actions, adaptive routing, enterprise
governance, distributed runtime reliability, production operations and real
browser end-to-end validation.

A concise interview description:

> I built AgentMesh as an Agent execution platform. Go owns identity, projects,
> governance, durable task control and operational boundaries; Python owns Agent
> planning, retrieval, model/tool execution and runtime intelligence; React
> provides the user-facing workspace and observability experience.

## 2. Why split Go and Python?

Use this distinction:

- **Go Control Plane**: authentication, user/project control, governance, quota,
  durable task lifecycle, API boundary, operational reliability.
- **Python Runtime**: Agent orchestration, RAG, Memory context, Tool/MCP
  execution, evaluation and routing intelligence.
- **React UI**: clean final-answer workspace plus separate Run Details for DAG,
  Trace, reliability, cost and evaluation evidence.

The split keeps product/business control independent from rapidly evolving AI
runtime logic.

## 3. Project, Knowledge and Memory boundaries

Important boundary:

```text
Project
→ shared execution / governance boundary

Project Knowledge
→ shareable inside the Project

GLOBAL Knowledge
→ private to the owning user

Long-term Memory
→ user-global, not silently shared through a Project
```

Do not claim that Project membership makes another user's private Memory or
GLOBAL Knowledge visible.

## 4. Tool, MCP and secure-action boundary

AgentMesh distinguishes deciding to call a tool from being allowed to execute a
side effect.

Key points:

- Tool/MCP resources are governed before execution.
- Higher-risk operations require approval.
- Approval is tied to the authoritative continuation state rather than trusting
  a browser-provided result.
- Audit/Trace should expose useful metadata without leaking credentials or
  sensitive payloads.

Interview question: **Why not let the LLM directly call any tool?**

Answer:

> Because model output is not an authorization decision. The runtime can propose
> an action, but the platform still applies permissions, risk level, approval and
> audit controls before the side effect is allowed.

## 5. Durable runtime and reliability

The v1.0 platform includes a durable execution path for long-running work.

Explain these concepts:

- durable queue;
- worker registration and heartbeat;
- lease and fencing;
- idempotent execution;
- capacity / backpressure;
- deadline and cancel;
- safe retry boundary;
- ambiguous failure fail-closed;
- worker/dispatcher recovery;
- circuit breaker;
- graceful shutdown.

Interview question: **What problem does fencing solve?**

Answer:

> A lease alone is not enough if an old worker continues running after losing
> ownership. Fencing makes stale ownership unable to commit an authoritative
> result after a newer lease holder has taken over.

## 6. Governance and multi-tenancy

Enterprise governance includes:

- Organization / Workspace / Project;
- OWNER / ADMIN / DEVELOPER / VIEWER boundaries;
- RBAC and object-level isolation checks;
- Project Knowledge sharing with private user scopes preserved;
- BYOK model-provider configuration;
- quota and usage accounting;
- audit with redaction.

Key sentence:

> Shared Project members can collaborate on Project resources, but user identity,
> private Memory and private knowledge boundaries remain independent.

## 7. BYOK security

Do not say only "the key is hidden on the page".

Explain the full boundary:

- plaintext key is accepted only when configuring a provider;
- persistence uses encrypted secret storage;
- normal APIs return masked metadata rather than the plaintext key;
- runtime receives only the scoped credential needed for the authorized
  execution;
- logs, audit and browser responses must not expose the raw secret.

## 8. Adaptive routing

The platform can choose Agents/models using runtime policy and historical
feedback rather than a fixed hard-coded target.

Discuss:

- capability matching;
- quality and success history;
- latency/cost signals;
- cold-start exploration;
- feedback-driven adaptation.

Avoid claiming mathematically optimal routing. It is a governed adaptive policy.

## 9. Observability

Keep the final answer separate from engineering evidence.

Run Details can be used to explain:

- DAG / Trace;
- retrieval evidence;
- reliability events;
- latency;
- token/cost usage;
- evaluation;
- routing decisions.

This separation keeps the workspace usable for normal users while retaining
engineering/debug evidence.

## 10. Production-readiness work

P10/P11/P12 focus on turning the platform into a deployable product:

- database migration lifecycle;
- `/livez` and `/readyz`;
- single public Gateway;
- same-origin API behavior;
- TLS fail-closed mode;
- log rotation;
- backup/restore documentation;
- production configuration preflight;
- browser E2E;
- bundle gate;
- release staging, archive hygiene and privacy scanning.

Interview question: **Why have both liveness and readiness?**

Answer:

> Liveness answers whether the process should be restarted. Readiness answers
> whether it is currently safe to receive traffic. A process may be alive while
> a required dependency is unavailable, so the two checks must not be collapsed.

## 11. Testing strategy

The project uses layered validation:

```text
targeted unit / contract tests
→ Go / Python / React full regression
→ TypeScript + production build
→ real-browser E2E
→ release / source / privacy validation
→ final human acceptance
```

A useful engineering point:

> I intentionally separate automated acceptance from final human acceptance.
> Automation protects contracts and regressions; the final manual pass validates
> real product usability and presentation.

## 12. Honest scope boundaries

For the original v1.0 release, do not claim:

- Kubernetes / Helm / Terraform delivery;
- enterprise SSO / SCIM;
- billing-provider integration;
- cloud-vendor-specific deployment;
- mobile client;
- arbitrary desktop computer control.

Those belong to later roadmap or development branches.

## 13. Suggested interview demo order

Use the P12 demo script and keep the demonstration around 8–12 minutes:

1. Workspace and Project.
2. Run one Agent task.
3. Open Run Details.
4. Show Project Knowledge and user Memory boundary.
5. Show Tool/MCP and approval.
6. Show Governance & Security.
7. Explain durable runtime and production operations.
8. End with architecture evolution and testing evidence.

## 14. Resume-ready summary

A compact description:

> Designed and implemented AgentMesh, a Go + Python + React Agent platform with
> project-scoped execution, RAG/Memory, Tool/MCP, HITL secure actions, adaptive
> routing, durable distributed runtime, enterprise governance, BYOK, quota/audit,
> production deployment gates and real-browser E2E validation.

Keep interview claims aligned with the exact branch being demonstrated.
