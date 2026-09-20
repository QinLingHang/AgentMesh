# Automatic Memory Write

Selected direct user statements can be converted into durable User-global memories.

## Runtime flow

```text
Direct user message (`req.task`) only
  -> MemoryCandidateDetector
  -> safety/scope rejection
  -> explicit rule extractor OR model-backed inferred extractor
  -> candidate validation
  -> Go internal upsert API
  -> `user_memories` keyed by `user_id + memory_key`
  -> `memory_write` Trace
```

No retrieval or prompt injection is added in this stage.

## Source contract

The extractor receives only the direct user message. The following are never passed to it:

- Project Knowledge chunks
- RAG evidence
- citations
- Tool observations
- MCP observations
- assistant answers

This is stronger than trying to remove project evidence after extraction: the prohibited sources never enter the write pipeline.

## Upsert authority

`manual` and `explicit_user` have stronger authority than `inferred_user`.

An incoming inferred candidate with the same `(user_id, memory_key)` cannot silently overwrite a stronger memory. The Go service returns one of:

- `created`
- `updated`
- `unchanged`
- `preserved`

## Runtime failure policy

Long-term-memory persistence is auxiliary. If the control-plane memory write fails, the main Agent task continues and the failure is recorded as an error `memory_write` Trace event.

## Resume policy

Continuation/resume input is excluded from automatic memory writes because it may contain OTP, auth material, approval responses, or other ephemeral task state.
