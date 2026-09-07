# AgentMesh Runtime v0.2 Architecture

## Frozen boundary

- React/TypeScript: product UI only.
- Go Control Plane: Auth, user boundary, Conversation/Message, Agent Registry, Task Control, Redis rate limit, persistence.
- Python Runtime Plane: Plugin Kernel, Task Profiler, Scheduler, Dynamic DAG, parallel Agent execution, fallback/rescheduling, model invocation.

## Public request chain

```text
React
  -> Go /api/tasks/run
  -> JWT + user_id + rate limit
  -> MySQL create task/message
  -> Go Runtime Client
  -> Python /internal/v1/runtime/execute
  -> Task Profiler
  -> Scheduler Plugin
  -> Dynamic DAG
  -> Parallel Agent Plugins
  -> Runtime Rescheduler when failure
  -> Model Plugin synthesis
  -> Go records task/trace/metrics/message
  -> React renders result + DAG + trace
```

## PI / DSH-inspired idea

The MVP deliberately implements only a small plugin kernel:

- Plugin Manifest
- Registry
- Runtime Context / Service Registry
- Event Bus
- setup/start/stop lifecycle

Current plugin kinds:

- Model plugin
- Agent adapter plugin
- Scheduler plugin

This is inspired by plugin-native harness architecture, but AgentMesh does not depend on DSH or copy its TypeScript runtime.

## Scheduler baselines

- `scheduler.fixed`
- `scheduler.capability`
- `scheduler.greedy`

The Greedy score is a baseline, not the final claimed innovation:

```text
0.38 * quality
+ 0.30 * success_rate
- 0.12 * load
- 0.10 * latency_ratio
- 0.10 * cost_ratio
```

Future Adaptive/Multi-objective scheduler must be compared on the same benchmark before any performance claim.
