# P6 — Eval + Reliability + Cost/Latency Governance

P6 turns AgentMesh runtime output into a measurable execution product instead of a black-box answer.

## Runtime flow

```text
Task
  ↓
Scheduler / Planner (uses requested constraints)
  ↓
Agent / Tool / MCP execution
  ↓
Per-agent Evaluation
  ↓
Observability aggregation
  ↓
P6 Run Scorecard
  ├─ task success
  ├─ answer quality
  ├─ groundedness
  ├─ tool reliability
  ├─ RAG quality
  ├─ Memory contribution health
  ├─ latency / cost / quality budget compliance
  └─ failure category
  ↓
Run Details → Eval
```

## Scorecard contract

The default evaluator is `p6_deterministic_v1`. It intentionally does not make another paid LLM call. This keeps the baseline deterministic and suitable for regression testing. A future LLM Judge can implement the same scorecard contract and be compared against this baseline.

The scorecard contains metadata only. It does **not** contain raw user messages, Memory content, Tool results, RAG chunks, passwords, tokens, OTPs, or credentials.

## Governance

`TaskConstraints` remain the request/project policy contract:

- `maxLatencyMs`
- `maxCost`
- `minQuality`

Scheduler and Planner already use these constraints while selecting resources.

P6 adds:

1. **Hard cost gate before an Agent attempt** — a fallback/reschedule cannot knowingly start an attempt whose configured `avgCost` would cross the request budget.
2. **Post-run latency / cost / quality compliance** — actual runtime metrics are compared against the same constraints and surfaced as scorecard violations.
3. **No hidden task failure from Eval** — scorecard construction is isolated. If Eval itself fails, the user task remains successful and an `eval` error event is recorded.

Latency is measured end-to-end and reported post-run; P6 does not kill an already-running task solely because wall-clock latency crossed the budget. Tool/model-specific timeouts remain the execution-level protection.

## Cost telemetry

Two cost concepts are kept separate:

- `estimatedCost`: Agent capability-profile budget accounting used by scheduling/governance.
- `modelEstimatedCost`: token-price telemetry from the model provider.

For OpenAI-compatible providers, model cost is calculated only when prices are configured:

```env
MODEL_INPUT_COST_PER_MILLION=...
MODEL_OUTPUT_COST_PER_MILLION=...
```

If prices are not configured, the UI shows model cost as **未配置** rather than inventing a price.

## Offline regression

`runtime-python/evals/p6_baseline_cases.jsonl` provides capability-oriented seed cases. `app.eval.baseline.compare_scorecards` supplies the reusable comparison primitive for CI / regression datasets.

Tests should remain organized by capability, not by historical P-stage wrapper scripts.
