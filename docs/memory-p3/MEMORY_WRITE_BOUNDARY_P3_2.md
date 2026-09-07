# P3.2 Memory Write Boundary

The architecture remains:

- **Memory = User-global**
- **Project Knowledge = strictly Project-scoped**

## Allowed automatic source

Only direct user-authored task text may produce an automatic memory candidate.

## Rejected automatic sources

Project Knowledge, document chunks, RAG evidence, citations, Tool results, MCP results, assistant output, and continuation/auth input must not be converted into User-global memory.

## Project-local statements

Because the target store is User-global, statements explicitly scoped to the current project are rejected by the automatic writer unless the user clearly makes them global (for example, "以后所有项目...").

## Credentials and secrets

Obvious passwords, API keys, access tokens, private keys and secret-like values are rejected from automatic memory writes.

## Important distinction

A Project conversation may still create a User-global memory when the user states a genuinely global preference or long-term fact. The conversation being inside a Project does not make Memory project-scoped; the *content scope* determines whether the automatic write is safe.
