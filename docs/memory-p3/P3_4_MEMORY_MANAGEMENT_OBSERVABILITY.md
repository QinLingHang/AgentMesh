# P3.4 Memory Management + Observability/UI

## Goal

P3.4 closes the user-facing management and observability loop for the P3
User-global Long-term Memory system.

The architecture remains unchanged:

- Memory is **User-global**.
- Project Knowledge is **strictly Project-scoped**.
- Memory and Project Knowledge are different domains and different scopes.

P3.4 does not move Project Knowledge into Memory and does not add `project_id`
to `user_memories`.

## User-facing Memory Center

The React application now exposes a dedicated **长期记忆** navigation entry.

The page provides:

- active Memory summary;
- source summary for `manual`, `explicit_user`, and `inferred_user`;
- local search;
- category filter;
- source filter;
- manual create;
- manual edit;
- delete / explicit forget through the UI;
- confidence, last update time, and last retrieval time.

Manual create always uses:

- `sourceType = manual`
- `confidence = 1`

Manual edit also promotes the Memory to `manual`. This is intentional: a user
correction has higher authority than an automatically inferred Memory.

## Explicit forget

P3.4 implements explicit forget at the management layer: deleting a Memory
through the Memory Center calls the authenticated `DELETE /api/memories/:id`
contract. Once deleted, the Memory is no longer returned by the active Memory
source and therefore is no longer eligible for retrieval.

This stage does not add a new natural-language semantic delete pipeline. The UI
is the deterministic and auditable forget control for P3 completion.

## Memory observability

Run Details now contains a dedicated **Memory** tab.

It presents production Trace events for:

- `memory_retrieval`
- `memory_write`

The panel deliberately renders only privacy-safe structured fields already
present in the P3.2/P3.3 Trace contracts, such as:

- candidate count;
- selected count;
- unsafe skipped count;
- whether semantic retrieval was used;
- memory key;
- category;
- source type;
- ranking score;
- write action;
- extractor.

It does **not** display full Memory content from Trace and refuses to expand
unstructured Memory Trace detail. The normal Memory Center can display content
because it is an authenticated owner-facing management surface; Run Details is
kept metadata-only for observability.

## Scope boundary visible in UI

The Memory Center explicitly explains:

```text
Memory = User-global
Project Knowledge = Project-scoped
Project Knowledge != Memory
```

Project document chunks, RAG evidence, Tool results, MCP results and citations
are not Memory management entries.

## Backend impact

No Go or Python production code changes are required in P3.4. It consumes the
validated contracts completed in P3.1-P3.3:

- authenticated Memory CRUD API from P3.1;
- automatic Memory Write from P3.2;
- Memory Retrieval + Trace from P3.3.

This keeps P3.4 narrowly scoped to user control and observability.
