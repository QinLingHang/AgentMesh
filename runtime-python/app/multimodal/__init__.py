"""AgentMesh V2 multimodal primitives.

The package intentionally keeps imports light so RAG/knowledge modules can use
individual submodules without creating initialization cycles.
"""

from app.multimodal.contracts import (
    MultimodalIngestionStats,
    RetrievalMode,
    VisionAnalyzer,
    VisionObservation,
    VisualType,
)

__all__ = [
    "MultimodalIngestionStats",
    "RetrievalMode",
    "VisionAnalyzer",
    "VisionObservation",
    "VisualType",
]
