# User-global Memory Retrieval + Context Assembly
## Scope

The Python Runtime supports **read-time long-term memory retrieval**.

The invariant remains:

- `Memory = User-global`
- `Project Knowledge = strictly Project-scoped`

The memory retrieval path receives `user_id + current task` and deliberately has no `project_id` input.
Project Knowledge continues to use its existing RAG scope path and citation contract.

## Runtime flow

```text
Current user task
    |
    +--> User-global Memory Retrieval
    |       |
    |       +--> Go internal memory API
    |       +--> active user memories only
    |       +--> safety filter
    |       +--> hybrid relevance ranking
    |       +--> top-k / threshold
    |
    +--> Automatic Memory Write
    |
    +--> Conversation Memory
    |
    +--> Project/Global Knowledge Retrieval
    |
    +--> Context Assembly
            |
            +-- [Current Task]
            +-- [Conversation Memory]
            +-- [User Long-term Memory]
            +-- [User Memory Policy]
            +-- [RAG Grounding Status]
            +-- [Retrieved Knowledge]
            +-- [Citation Policy]
```

Retrieval intentionally happens **before automatic write**. The current message is already present in `[Current Task]`; it should not be persisted and immediately retrieved back into the same request.

## Retrieval contract

Python reads memories only through:

```text
GET /internal/v1/users/:userId/memories?limit=N
X-Internal-Token: ...
```

Python does not read MySQL directly.

The default retriever combines:

- semantic similarity (`hash` embedding by default; `openai_compatible` is opt-in),
- lexical overlap,
- stored confidence,
- source authority (`manual > explicit_user > inferred_user`),
- domain/key relevance.

Only memories above `memory_retrieval_min_score` enter the top-k result.

## Fail-open behavior

Long-term memory is auxiliary context.

If the Go memory API or semantic embedding layer fails:

- the main Agent task continues,
- semantic failure falls back to lexical/authority scoring,
- control-plane read failure creates an observable `memory_retrieval` error event,
- no memory content is copied into the error trace.

## Safety

Before ranking, the retriever excludes memories that look like:

- credentials / OTP / passwords / secrets,
- project-local statements,
- temporary statements,
- reserved project/RAG/tool/MCP/secret key namespaces.

This protects against manually-created bad memory rows as well as automatic-write regressions.

## Observability

Trace kind:

```text
memory_retrieval
```

Trace includes metadata only:

- reason,
- candidate count,
- selected count,
- unsafe skipped count,
- whether semantic scoring was used,
- selected memory id/key/category/source/score.

It intentionally does not include full memory content.
