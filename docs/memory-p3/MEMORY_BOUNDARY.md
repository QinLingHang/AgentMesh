# Memory / Knowledge Boundary

## Fixed invariant

```text
User-global Memory
        !=
Project-scoped Knowledge
```

They must not share a scope model.

## Allowed future Memory sources

A later P3 stage may persist information that comes directly from the user and is safe and useful as long-term memory, for example an explicit preference or long-lived goal.

## Forbidden automatic Memory sources

These must not be copied into User-global Memory merely because the Runtime observed them:

- Project documents
- Project Knowledge chunks
- RAG evidence
- citations
- Tool results
- MCP results
- Project secrets

P3.1 enforces this structurally by keeping Memory as an independent service that is not injected into Knowledge ingestion, Project upload, RAG retrieval, Tool, or MCP flows.

## Cross-Project behavior

For the same user:

```text
Normal Conversation -----\
Project A Conversation ----> one User-global Memory store
Project B Conversation -----/
```

Knowledge remains separate:

```text
Project A Knowledge -X-> Project B
Project B Knowledge -X-> Project A
```
