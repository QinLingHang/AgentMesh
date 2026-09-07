# P3.3 Memory Context Policy

Long-term memory is user context, not project evidence.

The downstream Agent receives an explicit policy with these precedence rules:

1. **Current Task / current direct user instruction** wins over conflicting long-term memory.
2. **Recent explicit Conversation Memory** wins over stale long-term memory.
3. If long-term memories conflict, `manual` / `explicit_user` has higher authority than `inferred_user`.
4. Long-term memory must not establish project-specific implementation facts.
5. Project-specific facts must come from `Retrieved Knowledge` and retain the RAG citation rules.
6. User Memory must never be cited with `[1]`, `[2]`, etc. because those labels belong to retrieved evidence only.
7. Irrelevant or conflicting memory should be ignored.

This keeps three different context domains separate:

```text
Conversation Memory = conversation-scoped recent interaction
User Long-term Memory = user-global durable context/preferences
Project Knowledge = project-scoped factual evidence
```
