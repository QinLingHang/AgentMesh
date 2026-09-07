# AgentMesh V2 Intelligence Architecture

## Scope

V2 extends the existing AgentMesh control-plane/runtime split without replacing the stable v1 boundaries.

- Go remains the authentication, tenant/project governance, knowledge lifecycle, persistence, and cost aggregation control plane.
- Python remains the Agent/RAG/model/evaluation runtime.
- React remains the product and observability UI.
- Existing Text RAG, Memory, Tool, MCP, BYOK, Governance, Session Restore, and Distributed Runtime contracts stay backward compatible.

## V2 execution path

```text
Knowledge file
  -> Go object storage + lifecycle
  -> request-local BYOK resolution (when configured)
  -> Python knowledge ingestion
       -> text evidence
       -> visual evidence
  -> existing retrieval backend / Milvus

User task
  -> Query Intelligence
  -> TEXT / VISUAL / HYBRID mode
  -> retrieval + modality filter + diversity
  -> context + provenance
  -> model/runtime
  -> grounded answer + citations
  -> scorecard/evaluation metadata
  -> token/cost/observability
  -> Go task persistence and cost accounting
  -> React Run Details
```

## Backward compatibility

Visual processing is additive. Text-only files and text-only questions do not require a Vision Provider. PDF visual failure does not invalidate an already parsed text layer. Cost/evaluation telemetry is non-critical metadata and must not turn a successful Agent run into an HTTP 500 solely because telemetry persistence is unavailable.

## Privacy boundary

V2 trace metadata may contain evidence identifiers, page numbers, modality, scores, token counts, model/provider identifiers, and costs. It must not contain raw API keys, authorization headers, private keys, full base64 image bodies, or full uploaded document bodies.

Knowledge files remain runtime data and must never be tracked by Git.
