# P3.1 User-global Memory Foundation

## Implemented

- `user_memories` MySQL schema for fresh and existing databases
- User-global model with no `project_id`
- MySQL repository
- Memory service validation and ownership semantics
- JWT-protected CRUD HTTP API
- Internal-token-protected active-memory read contract for future Runtime integration
- Stable per-user `memory_key` uniqueness
- category/status/keyword lexical list filters
- `last_accessed_at` tracking on direct reads

## Not implemented in P3.1

- automatic Memory candidate detection
- LLM Memory extraction
- automatic Memory writes
- inferred memory
- Memory merge/supersede logic
- semantic/vector Memory retrieval
- Memory injection into prompts
- Memory retrieval Trace events
- Memory management UI

Those belong to P3.2-P3.4.
