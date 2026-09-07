# P7 Adaptive Scheduler + Model Router + Runtime Optimization

P7 closes the feedback loop created by P6 without changing the user-facing
execution contract.

## Runtime loop

```text
P6 historical Agent capability metrics (Go/MySQL)
                   +
P7 process-local Model runtime metrics
                   +
Task Profile / Project constraints
                   ↓
         Multi-objective Routing
       quality / reliability / latency
       cost / load / exploration
                   ↓
       Agent Route + Model Route
                   ↓
              Runtime
                   ↓
      Evaluation + Agent Feedback
                   ↓
       next request adapts again
```

## Agent history

Agent capability profiles are authoritative historical metrics persisted by the
Go control plane. P7 does not create a second Agent history database. The
adaptive scheduler consumes quality, success rate, latency, cost, load and
sample count from those profiles.

## Model history

Model runtime telemetry is EWMA process-local in P7. This intentionally avoids
adding another persistence subsystem during the routing phase. The contract can
later be persisted by the control plane without changing the router API.

## Activation

- `fixed`, `capability`, `greedy`: retain their P1-P6 model resolution behaviour.
- `adaptive`: uses the P7 Agent router and, when `MODEL_ROUTER_ENABLED=true`, the
  P7 Model router for internal/langgraph Agents.
- with only one Model runtime registered, adaptive routing safely resolves that
  single runtime.

## Optional model pool

`MODEL_RUNTIME_POOL_JSON` registers additional Runtime candidates. Example:

```json
[
  {
    "runtimeId": "fast",
    "provider": "mock",
    "model": "mock-fast",
    "qualityScore": 0.76,
    "avgLatencyMs": 300,
    "avgCost": 0.001,
    "successRate": 0.99
  }
]
```

OpenAI-compatible candidates may provide their own base URL/pricing metadata.
In production prefer environment-injected credentials rather than embedding
secrets in the JSON.

## Safety / correctness

Routing Trace contains only candidate IDs/names, scores and performance
metadata. It never contains user prompts, Memory contents, RAG chunks, Tool
results or credentials.

Constraint handling prefers the feasible candidate set. If every candidate
violates at least one soft routing constraint, the decision is marked
`degraded=true`; P6 hard cost governance remains the final execution guard.
