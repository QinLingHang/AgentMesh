from app.schemas import TaskProfile
from app.semantics.analyzer import infer_abstract_capabilities


def profile_task(text: str) -> TaskProfile:
    """Profile execution shape without creating a second semantic classifier.

    P24 owns abstract capability recognition in the Unified Semantic Core. This
    profile only derives scheduling attributes from that shared classification.
    """
    lower = str(text or "").lower()
    inferred = infer_abstract_capabilities(text)
    required = inferred or ["general"]

    complexity = "low"
    if len(required) >= 2 or len(text) > 300:
        complexity = "medium"
    if len(required) >= 4 or len(text) > 1200:
        complexity = "high"

    risk = (
        "high"
        if any(
            item in lower
            for item in ("删除", "退款", "支付", "生产", "execute", "delete")
        )
        else "low"
    )

    modality = ["text"]
    if "vision" in required:
        modality.append("image")
    if "document" in required:
        modality.append("file")

    return TaskProfile(
        required_capabilities=required,
        complexity=complexity,
        risk_level=risk,
        modality=modality,
        parallelizable=len(required) > 1,
    )
