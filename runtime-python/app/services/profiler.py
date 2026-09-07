from app.schemas import TaskProfile


KEYWORDS: dict[
    str,
    tuple[str, ...],
] = {
    "vision": (
        "图片",
        "截图",
        "图像",
        "照片",
        "image",
        "screenshot",
    ),
    "document": (
        "文档",
        "pdf",
        "论文",
        "合同",
        "说明书",
        "document",
    ),
    "data": (
        "csv",
        "data",
        "数据",
        "统计",
        "sql",
        "表格",
        "database",
        "excel",
    ),
    "diagnostic": (
        "报错",
        "异常",
        "错误",
        "500",
        "502",
        "timeout",
        "故障",
        "日志",
    ),
    "business": (
        "订单",
        "退款",
        "物流",
        "支付",
        "order",
        "refund",
        "logistics",
    ),
}


def profile_task(
    text: str,
) -> TaskProfile:
    lower = text.lower()

    required: list[str] = []

    for capability, words in (
        KEYWORDS.items()
    ):
        if any(
            word.lower() in lower
            for word in words
        ):
            required.append(
                capability
            )

    if not required:
        required = [
            "general"
        ]

    complexity = "low"

    if (
        len(required) >= 2
        or len(text) > 300
    ):
        complexity = "medium"

    if (
        len(required) >= 4
        or len(text) > 1200
    ):
        complexity = "high"

    risk = (
        "high"
        if any(
            item in lower
            for item in (
                "删除",
                "退款",
                "支付",
                "生产",
                "execute",
                "delete",
            )
        )
        else "low"
    )

    modality = [
        "text"
    ]

    if "vision" in required:
        modality.append(
            "image"
        )

    if "document" in required:
        modality.append(
            "file"
        )

    return TaskProfile(
        required_capabilities=required,
        complexity=complexity,
        risk_level=risk,
        modality=modality,
        parallelizable=(
            len(required) > 1
        ),
    )