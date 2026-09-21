# Multi-modal RAG

## Supported ingestion

Multi-modal ingestion accepts the existing text-first knowledge formats plus:

- PNG
- JPEG/JPG
- WEBP
- PDF visual pages

PDF uses two independent layers:

```text
PDF
├─ text layer -> pypdf -> chunks -> text evidence
└─ visual layer -> PyMuPDF page render -> VisionAnalyzer -> visual evidence
```

The visual layer is bounded to a configured ingestion limit (`max_visual_pages`, currently 24 at the indexer call site). When a PDF has more pages than the visual limit, the file reports `visualStatus=partial`; the full PDF page count is still retained.

## Visual evidence

Visual assets are converted to structured `VisionObservation` data:

- summary
- visual_type
- visible_text
- entities
- relationships
- key_facts
- metadata

The searchable representation is semantic text generated from this structure. This intentionally reuses the existing embedding/vector infrastructure rather than introducing a second vector database for multimodal retrieval.

Supported evidence modalities are:

- `text`
- `image`
- `page`
- `chart`
- `table`

The ingestion pipeline normally emits `image` for standalone images and `page` for rendered PDF pages; `chart` and `table` remain valid evidence contracts for future specialized extractors.

## Vision Provider

`DeterministicVisionAnalyzer` is offline-safe and used with the mock model runtime. It supports fixed semantic fixtures for tests.

`ModelVisionAnalyzer` uses the existing Model Gateway and sends an image attachment to an explicitly configured vision model. A real text-only runtime is rejected instead of silently receiving image bytes.

For authenticated knowledge ingestion, Go resolves the same request-local personal/project BYOK model contract used by normal task execution and carries it only through the trusted internal Go -> Python multipart request. The browser never receives the plaintext key. Multi-modal knowledge ingestion requires an explicit `visionModelName` before it sends image bytes to a real BYOK provider; if one multimodal model serves both text and vision, configure that same model name explicitly in the vision field. Text-only knowledge ingestion does not carry BYOK plaintext through the Vision path. When no request-local model is available, the deployment-level mock/default analyzer behavior remains the fallback according to runtime configuration.

Runtime configuration uses `MODEL_VISION_NAME`; production compose already exposes the same setting.

## Retrieval mode

Query Intelligence includes with a deterministic multimodal decision:

- `TEXT`
- `VISUAL`
- `HYBRID`

The classifier combines visual/page/text lexical signals with the existing query intent and complexity. Retrieval still uses the existing RAG backend. Multi-modal retrieval requests a wider candidate set, filters by requested modality, then applies evidence diversity before the normal context path.

Run trace records:

- retrievalMode
- retrievalModeReason
- rawHits
- hits
- contextHits
- textCandidates
- visualCandidates
- modality/page/visualType/assetId for selected evidence

## Citation provenance

The provenance and citation projection include with:

- `pageNumber`
- `assetId`
- `modality`
- `visualType`

Citation validation continues to accept only evidence selected for the current run. A model cannot create an authoritative citation merely by inventing a page number or source label.

## Vision model safety

Knowledge-image ingestion uses an explicit vision-model gate. A personal BYOK provider may leave `visionModelName` empty, but in that state image/PDF visual analysis is disabled rather than silently sending image bytes to the text model. Shared project providers remain text-first in the current governance schema and therefore do not implicitly opt into knowledge-image analysis. Normal task execution keeps the existing multimodal fallback for backward compatibility.

## Failure semantics

- PDF visual rendering/model failure -> preserve PDF text evidence and mark visual status failed; persisted visual error text is bounded and secret-redacted.
- PDF visual page limit -> mark visual status partial.
- Deployment without a real vision model -> text knowledge remains usable; image-only ingestion reports an explicit ingestion failure.
- Mock deployment -> deterministic visual evidence is available without external network access.
