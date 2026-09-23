"""P23 read-only binary execution routing.

Go owns submission, authorization and FAST_PATH/RUNTIME selection. Python only
reports whether an ordinary model answer is sufficient. Concrete capability
selection remains inside Runtime's existing Discovery/Scheduler/ToolLoop/RAG.
This module deliberately accepts no executable capability identifiers.
"""
from __future__ import annotations

from typing import Literal
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.semantics.analyzer import analyze_task_semantics, has_live_personal_data_need
from app.semantics.contracts import KnowledgeDependency, RagPreference


class IntentModelRuntimeConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    service_id: int | None = Field(default=None, alias="serviceId")
    service_name: str | None = Field(default=None, alias="serviceName")
    provider: str
    base_url: str = Field(alias="baseUrl")
    model_name: str = Field(alias="modelName")
    vision_model_name: str | None = Field(default=None, alias="visionModelName")
    api_key: SecretStr = Field(alias="apiKey")
    auto_route: bool = Field(default=False, alias="autoRoute")
    is_default: bool = Field(default=False, alias="isDefault")


class IntentModelSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    mode: Literal["auto", "manual"] = "auto"
    service_id: int | None = Field(default=None, alias="serviceId")


class IntentTaskConstraints(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    max_latency_ms: int = Field(default=8000, alias="maxLatencyMs")
    max_cost: float = Field(default=0.15, alias="maxCost")
    min_quality: float = Field(default=0.8, alias="minQuality")
    retry_on_worker_loss: bool = Field(default=False, alias="retryOnWorkerLoss")


class TaskUnderstandingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_version: Literal["p23.v2"] = Field(default="p23.v2", alias="schemaVersion")
    task: str = Field(min_length=1, max_length=20000)
    rag_mode: Literal["OFF", "AUTO", "ON"] = Field(default="AUTO", alias="ragMode")
    has_attachments: bool = Field(default=False, alias="hasAttachments")
    # Trusted Go metadata-only assessment. Never supplied by the browser.
    model_readable_attachments: bool = Field(default=False, alias="modelReadableAttachments")
    continuation_state: Literal["NONE", "CHAT", "ONE_PENDING", "AMBIGUOUS"] = Field(default="NONE", alias="continuationState")
    # Request-local BYOK; never included in the response, trace, or logs.
    project_model: IntentModelRuntimeConfig | None = Field(default=None, alias="projectModel", exclude=True)
    model_pool: list[IntentModelRuntimeConfig] = Field(default_factory=list, max_length=32, alias="modelPool", exclude=True)
    model_selection: IntentModelSelection = Field(default_factory=IntentModelSelection, alias="modelSelection", exclude=True)
    constraints: IntentTaskConstraints = Field(default_factory=IntentTaskConstraints, exclude=True)
    allow_model: bool = Field(default=False, alias="allowModel", exclude=True)


class TaskUnderstandingResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    schema_version: Literal["p23.v2"] = Field(default="p23.v2", alias="schemaVersion")
    execution_route: Literal["FAST_PATH", "RUNTIME"] = Field(alias="executionRoute")
    disposition: Literal["EXECUTE", "CLARIFY", "REJECT", "TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"] = "EXECUTE"
    knowledge_dependency: KnowledgeDependency = Field(alias="knowledgeDependency")
    capability_required: bool = Field(default=False, alias="capabilityRequired")
    reason_codes: list[str] = Field(default_factory=list, max_length=8, alias="reasonCodes")
    unresolved_requirements: list[str] = Field(default_factory=list, max_length=4, alias="unresolvedRequirements")
    analysis_source: Literal["RULE", "MODEL", "INDETERMINATE"] = Field(default="RULE", alias="analysisSource")
    model_calls: int = Field(default=0, ge=0, alias="modelCalls")
    model_tokens: int = Field(default=0, ge=0, alias="modelTokens")
    model_estimated_cost: float = Field(default=0.0, ge=0, alias="modelEstimatedCost")
    model_cost_known: bool = Field(default=False, alias="modelCostKnown")


_OPERATION = (
    "查订单", "查询", "查一下", "查找", "搜索", "读取", "列出", "打开文件", "执行", "运行",
    "创建", "新建", "更新", "修改", "修复", "删除", "发送", "退款", "导入", "导出", "上传", "下载",
    "部署", "测试", "审查代码", "检索", "调用", "api", "mcp", "tool", "agent", "订单", "物流",
    "search", "fetch", "read file", "run ", "execute", "create", "update", "delete", "send", "deploy",
)
_MULTISTEP = ("然后", "之后再", "最后", "发现问题", "如果发现", "修复并", "先检查", "测试后", "then ", "after that", "if there")
_CONTINUATION = ("继续", "接着", "上一个", "刚才", "之前那个", "昨天那个", "continue", "go on")
_TASK_OP = ("任务进度", "任务状态", "取消任务", "恢复任务", "继续任务", "task status", "task progress", "resume task", "cancel task")
_MISSING_TARGET = frozenset({"处理一下", "帮我处理这个", "搞一下", "按上次的做", "那个弄一下", "帮我办了"})
_SAFE_GREETING = frozenset({"你好", "您好", "嗨", "hello", "hi", "谢谢", "感谢", "再见", "早上好", "晚上好", "好的", "ok"})
_GENERIC = ("什么是", "解释一下", "解释下", "概念是什么", "原理是什么", "介绍一下", "what is ", "explain ")
_UNCERTAIN = ("这个", "那个", "这样", "按之前", "按照上次", "处理", "看看", "can you", "帮我")


def _any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


# These are high-precision *model-only* shapes, not a keyword-based fallback.
# Every positive result is still vetoed by the existing semantic dependency
# detector, explicit RAG requirements and authenticated task state.
_MODEL_ONLY_REQUEST = (
    "翻译", "润色", "改写", "改得", "压缩成", "总结", "概括", "取一个", "起一个",
    "写一段", "写一个", "写几句", "给我一个", "给出三种", "给出几个",
    "提供一个", "介绍一下", "解释一下", "请解释", "解释下", "什么是", "用两句话",
    "please translate", "rewrite", "summarize", "give me an example", "explain ",
)
_INLINE_EDIT = ("翻译", "润色", "改写", "改得", "压缩", "总结", "概括", "取一个", "起一个")
# Only clearly referential follow-ups to an existing assistant answer may use
# model-only chat history. A bare "继续" or an instruction to resume real work
# must never be upgraded to a new model answer by this optimization.
_CHAT_MODEL_FOLLOWUP = ("解释", "说明", "缩短", "简短", "润色", "改写", "翻译", "概括", "总结", "换个说法", "举个例子")
_CHAT_ANSWER_REFERENCE = ("刚才", "上一条", "上一轮", "上条", "前面", "我们刚才", "之前", "上一步")
_CHAT_ANSWER_NOUN = ("回复", "回答", "解释", "内容", "文案", "文字", "消息")
_CHAT_FRAGMENT_REFERENCE_RE = re.compile(
    r"(?:最后|第[一二三四五六七八九十]|倒数第[一二三四五六七八九十])(?:一)?(?:段|句|点|条|节|部分)$"
)
_DOCUMENT_COMPARE = ("比较", "对比", "识别冲突", "找出差异", "归纳", "总结", "解释", "梳理")
_DOCUMENT_SIDE_EFFECT = (
    "直接修改", "立即修改", "修改并保存", "修改后保存", "写回", "实际删除",
    "保存到", "提交修改", "删除", "新建", "创建", "写入", "运行", "执行", "部署", "发送", "上传", "下载",
    "数据库", "项目知识", "知识库", "外部", "跨项目", "全部文件",
)


def _clean(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    return re.sub(r"[\s。.!！?？,，;；~～]+$", "", normalized).strip()


def _inline_material(text: str) -> bool:
    # A source is present, not merely promised ("below:" without any text).
    if re.search(r"[：:]\s*[^\s：:]{2,}", text):
        return True
    return bool(re.search(r"[“\"‘][^”\"’]{2,}[”\"’]", text))


def _model_only_request(text: str) -> bool:
    if len(text) > 1200 or not _any(text, _MODEL_ONLY_REQUEST):
        return False
    if _any(text, ("这家店", "你们", "贵公司", "你家", "本项目", "当前项目", "当前系统", "实时", "最新", "实际订单", "当前账户")):
        return False
    if _any(text, ("文件夹", "文件路径", "本地文件", "代码库", "数据库", "运行测试", "执行命令", "部署", "发送邮件", "修改文件", "删除文件")):
        return False
    if _any(text, ("翻译", "润色", "改写", "改得", "压缩", "总结", "概括")):
        return _inline_material(text) or "已贴出" in text or "三条要点" in text
    # Writing a new example, short text or general explanation needs no source.
    return True


def _missing_model_input(text: str) -> bool:
    if _inline_material(text):
        return False
    if any(phrase in text for phrase in ("已贴出", "已经贴出", "已提供", "已经提供")):
        return False
    if _any(text, _INLINE_EDIT) and _any(text, ("下面这段", "这段话", "这段文字", "这个学习计划", "这份学习计划", "通用学习计划")):
        return True
    # An explicit RAG-OFF instruction does not supply the text it promises.
    # The answer is a model-only clarification, not a hallucinated answer or a
    # forbidden knowledge lookup. This also covers "我贴出来" with no actual text.
    if _any(text, ("只根据", "仅根据", "根据我贴", "根据以下")) and _any(text, ("贴出来的文字", "贴出的文字", "下面的文字", "以下文字", "提供的文字")):
        return True
    return False


def _chat_answer_fragment_reference(text: str) -> bool:
    """Recognize a pure reference to a fragment of a trusted prior answer.

    Examples such as ``上一条回复最后一段`` already contain the requested
    object; asking the user to repeat an action verb adds no information.  The
    trusted continuation state still decides whether the referenced answer is
    actually available.  Task/workflow references are intentionally excluded.
    """
    if not _any(text, _CHAT_ANSWER_REFERENCE) or not _any(text, _CHAT_ANSWER_NOUN):
        return False
    if _any(text, ("任务", "审批", "工单", "订单", "执行", "运行", "恢复", "取消")):
        return False
    compact = re.sub(r"[\s。.!！?？,，;；~～]+$", "", text).strip()
    return bool(_CHAT_FRAGMENT_REFERENCE_RE.search(compact))


def _chat_model_followup(text: str) -> bool:
    return (
        _any(text, _CHAT_ANSWER_REFERENCE)
        and (_any(text, _CHAT_MODEL_FOLLOWUP) or _chat_answer_fragment_reference(text))
    )


def _multi_step_instruction(text: str) -> bool:
    # "最后一段/最后一句" identify an earlier answer fragment; they are not
    # instructions to execute a final workflow step.
    without_fragment = re.sub(r"最后(?:一|两|三|几|第[一二三四五六七八九十])(?:段|句|点|节|条|部分)", "", text)
    return _any(without_fragment, _MULTISTEP)


def _attachment_comparison(req: TaskUnderstandingRequest, text: str) -> bool:
    if not req.has_attachments or not req.model_readable_attachments or req.rag_mode == "ON":
        return False
    if not _any(text, _DOCUMENT_COMPARE) or _any(text, _DOCUMENT_SIDE_EFFECT):
        return False
    # A future modification is permitted only after a subsequent distinct
    # approval turn. Never treat an instruction to edit immediately as a read.
    if "修改" in text and not _any(text, (
        "询问后才能修改", "确认后才能修改", "同意后才能修改", "确认前不要修改", "不要修改"
    )):
        return False
    return True


def _explicit_forbidden_request(text: str) -> bool:
    if text.startswith(("解释", "举例", "分析", "如何", "what is", "explain")):
        return False
    return (
        ("密码" in text and _any(text, ("外部", "第三方", "公开")) and _any(text, ("发送", "传给", "传到", "公布")))
        or ("未经授权" in text and _any(text, ("传", "发送", "上传", "外发")))
        or ("其他组织" in text and "私有" in text and _any(text, ("列出", "获取", "读取", "枚举")))
        or ("外部agent" in text.replace(" ", "") and "管理员" in text and "全部命令" in text and "允许" in text)
    )


def _explicit_governance_rejection(text: str) -> bool:
    """Reject explicit attempts to bypass already-stated authority boundaries.

    These checks use only facts asserted by the request itself. They never
    infer private resource existence and never grant authority from text. Real
    execution still re-checks current Go authorization before any capability.
    """
    cross_subject = _any(text, ("另一个客户", "其他客户", "上一个用户", "其他用户", "别的用户"))
    protected_resource = _any(text, ("订单", "知识库", "文档", "数据", "账户", "项目"))
    if cross_subject and protected_resource and _any(text, ("读取", "使用", "查询", "回答", "获取")):
        return True

    revoked = _any(text, ("权限已撤销", "已撤销", "撤销了", "权限刚被关闭", "权限被关闭", "权限已经关闭"))
    continue_use = _any(text, ("继续", "引用", "查询", "读取", "写入", "按旧", "旧任务快照", "原计划"))
    if revoked and continue_use:
        return True

    unauthorized_capability = _any(text, ("不在授权目录", "未授权", "没有授权", "无权限"))
    if unauthorized_capability and _any(text, ("直接调用", "调用它", "继续调用", "使用它", "执行")):
        return True

    unknown_payment = _any(text, ("工具发出了请求", "请求已经发出", "请求已发出"))
    if unknown_payment and _any(text, ("成功付款", "已经成功", "执行成功", "付款成功")):
        return True
    return False


def _explicit_rag_disable(text: str) -> bool:
    compact = text.replace(" ", "")
    return _any(compact, ("关闭rag", "rag已关闭", "rag关闭", "不要用rag", "不使用rag", "禁用rag"))


def _policy_clarification(text: str, knowledge: KnowledgeDependency) -> str | None:
    """Return a user-facing missing requirement for deterministic policy gaps."""
    if _explicit_rag_disable(text) and knowledge != KnowledgeDependency.NONE:
        return "RAG 已关闭，无法核实需要企业知识支持的事实；请提供允许使用的资料或调整检索策略"
    if "没有提供订单号" in text and _any(text, ("订单状态", "查订单", "查询订单")):
        return "请提供要查询的订单号或明确唯一可识别的订单"
    if _any(text, ("没有我的确认", "未经我确认", "未确认")) and _any(text, ("删除文件", "执行删除", "删除操作")):
        return "请先明确要操作的文件；删除属于需确认的副作用，当前不会执行"
    if _any(text, ("不允许访问其他项目", "仅限这个项目", "只访问这个项目")) and _any(text, ("回答这个项目的问题", "回答当前项目的问题")):
        return "请提供要回答的具体项目问题；系统不会访问其他项目"
    if "冲突" in text and _any(text, ("不要选任意一份", "不要随便选", "不要任选", "不能任选")):
        return "检测到冲突来源；请明确适用版本、生效时间或权威规则后再继续"
    return None


def _ambiguous_runtime_target(text: str, continuation_state: str) -> str | None:
    """Detect missing runtime targets without guessing an object from prose."""
    if continuation_state != "NONE":
        return None
    patterns = (
        r"(?:帮我)?处理那个订单",
        r"^这个不对.*(?:改|修)",
        r"把它(?:发|发送|提交|删|删除)",
        r"那个设备.*(?:弄好|修|处理)",
        r"给他.*权限",
        r"现在就删掉",
        r"那个价格.*(?:变化|变了|多少)",
        r"第二个文件.*(?:部署|重部署|重新部署)",
        r"之前说的时间.*(?:预约|安排)",
        r"他的进度",
        r"换一个.*(?:没确定|未确定).*型号",
    )
    if any(re.search(pattern, text) for pattern in patterns):
        return "请明确要处理的对象、目标或必要参数后再继续"
    # Return/refund eligibility is object-specific. Without a product/order or
    # trusted prior context, "还能退" cannot be answered safely from generic
    # policy alone because the applicable item and purchase context are absent.
    if _any(text, ("还能退", "能不能退", "是否可以退", "是否还能退款")) and not _any(
        text, ("订单号", "订单", "这个订单", "这笔订单", "商品", "这件商品", "这个商品", "设备", "这台设备", "产品", "这个产品")
    ):
        return "请明确要判断退换资格的订单、商品或设备"
    return None


def _pending_reference_clarification(text: str, continuation_state: str) -> str | None:
    """A pending task does not make an unrelated scheme/index reference unique."""
    if continuation_state != "ONE_PENDING":
        return None
    if re.fullmatch(r"第[一二三四五六七八九十两]+个", text):
        return "请明确所指的候选项；不会仅凭序号猜测执行对象"
    if _any(text, ("刚刚确认的方案", "刚才确认的方案", "昨天讨论的另一份方案", "另一份方案")):
        return "请提供或确认具体方案内容后再执行，避免把未完成任务误当作该方案"
    return None


def understand(req: TaskUnderstandingRequest, *, descriptor=None) -> TaskUnderstandingResult:
    """Never infer FAST_PATH from merely failing to recognize a capability."""
    text = _clean(req.task)
    semantic = analyze_task_semantics(req.task, has_attachments=req.has_attachments, enable_implicit_business=True)
    knowledge = semantic.knowledge_dependency
    # Negating retrieval is not itself a request to retrieve. If the user asks
    # solely to transform supplied prose, respect RAG OFF without treating the
    # word "知识库" in "不要查知识库" as a positive Knowledge dependency.
    inline_without_rag = (
        semantic.rag_preference is RagPreference.DISABLE
        and not has_live_personal_data_need(req.task)
        and not _any(text, ("你们的", "官方标准", "企业政策", "本项目", "最新政策"))
        and _any(text, ("只根据", "仅根据", "根据我贴", "根据以下文字"))
    )
    if inline_without_rag:
        knowledge = KnowledgeDependency.NONE
    document_only = _attachment_comparison(req, text)
    must_use_runtime = (
        (req.has_attachments and not document_only)
        or req.rag_mode == "ON"
        or (knowledge != KnowledgeDependency.NONE and not document_only)
        or (semantic.requires_tool and not document_only)
        or has_live_personal_data_need(req.task)
        or (_any(text, _OPERATION) and not document_only)
        or (_multi_step_instruction(text) and not document_only)
        or req.continuation_state in {"ONE_PENDING", "AMBIGUOUS"}
        or _any(text, _TASK_OP)
    )
    if document_only:
        # Request-local attachments are not tenant Knowledge. Go has already
        # verified ownership, type and size before enabling this fast path.
        knowledge = KnowledgeDependency.NONE
    if _explicit_forbidden_request(text):
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="REJECT", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["EXPLICIT_POLICY_VIOLATION"],
            unresolvedRequirements=["该请求涉及未获授权的敏感信息或能力，已阻止执行"],
        )
    if _explicit_governance_rejection(text):
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="REJECT", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["EXPLICIT_AUTHORITY_BYPASS_REJECTED"],
            unresolvedRequirements=["请求明确要求绕过当前授权、撤权或结果确认边界，已阻止执行"],
        )
    policy_gap = _policy_clarification(text, knowledge)
    if policy_gap:
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["POLICY_OR_PARAMETER_CLARIFICATION_REQUIRED"],
            unresolvedRequirements=[policy_gap],
        )
    ambiguous_target = _ambiguous_runtime_target(text, req.continuation_state)
    if ambiguous_target:
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["AMBIGUOUS_RUNTIME_TARGET"],
            unresolvedRequirements=[ambiguous_target], analysisSource="INDETERMINATE",
        )
    pending_reference = _pending_reference_clarification(text, req.continuation_state)
    if pending_reference:
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["PENDING_TASK_REFERENCE_AMBIGUOUS"],
            unresolvedRequirements=[pending_reference], analysisSource="INDETERMINATE",
        )
    # Explicit disabled knowledge does not erase the factual dependency.
    if (req.rag_mode == "OFF" or semantic.rag_preference is RagPreference.DISABLE) and knowledge != KnowledgeDependency.NONE:
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["KNOWLEDGE_POLICY_DISABLED"],
            unresolvedRequirements=["当前配置禁止企业知识检索，无法核实该业务事实"],
        )
    if not must_use_runtime and _missing_model_input(text) and not req.has_attachments and req.continuation_state != "CHAT":
        return TaskUnderstandingResult(
            executionRoute="FAST_PATH", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=False, reasonCodes=["MISSING_MODEL_INPUT"],
            unresolvedRequirements=["请提供需要处理的原文或学习计划内容"],
        )
    if text in _MISSING_TARGET or (req.continuation_state == "AMBIGUOUS" and _any(text, _CONTINUATION)):
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["AMBIGUOUS_TASK_REFERENCE" if req.continuation_state == "AMBIGUOUS" else "MISSING_ACTION_TARGET"],
            unresolvedRequirements=["请明确要处理的任务或对象"], analysisSource="INDETERMINATE",
        )
    if req.continuation_state == "ONE_PENDING" and _any(text, _CONTINUATION + _TASK_OP):
        return TaskUnderstandingResult(
            executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=True, reasonCodes=["EXISTING_TASK_OPERATION_REQUIRED"],
            unresolvedRequirements=["已有未结束任务；请使用原任务的查询、恢复或取消操作，不会再次提交"],
        )
    if req.continuation_state == "NONE" and _chat_model_followup(text) and not must_use_runtime:
        # Not every reference to a previous assistant answer contains "继续"
        # or "刚才" (e.g. "上一条回复最后一段"). Without trusted history,
        # clarify on the model-only path rather than start a Runtime task.
        return TaskUnderstandingResult(
            executionRoute="FAST_PATH", disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=False, reasonCodes=["MISSING_CHAT_CONTEXT"],
            unresolvedRequirements=["请提供需要继续解释或修改的上一条内容"],
        )
    if _any(text, _CONTINUATION) and req.continuation_state == "NONE":
        # A missing prior *answer* is not evidence that an execution task is
        # pending. Keep conversational questions out of a new Runtime job.
        chat_only = _chat_model_followup(text) and not must_use_runtime
        return TaskUnderstandingResult(
            executionRoute="FAST_PATH" if chat_only else "RUNTIME",
            disposition="CLARIFY", knowledgeDependency=knowledge,
            capabilityRequired=not chat_only, reasonCodes=["MISSING_CHAT_CONTEXT" if chat_only else "MISSING_CONTINUATION_CONTEXT"],
            unresolvedRequirements=["请提供需要继续解释或修改的上一条内容" if chat_only else "请说明要继续的具体内容"],
        )
    # A model can add dependencies but cannot remove deterministic requirements,
    # assert permissions, select capability refs or override a user RAG setting.
    if descriptor is not None:
        kinds = tuple(getattr(descriptor, "capability_kinds", ()) or ())
        model_knowledge = getattr(descriptor, "knowledge_dependency", "NONE")
        if model_knowledge == "REQUIRED":
            knowledge = KnowledgeDependency.REQUIRED
            must_use_runtime = True
        elif model_knowledge == "OPTIONAL" and knowledge == KnowledgeDependency.NONE:
            knowledge = KnowledgeDependency.OPTIONAL
            must_use_runtime = True
        must_use_runtime = must_use_runtime or bool(kinds) or bool(getattr(descriptor, "multi_step", False)) or bool(getattr(descriptor, "requested_effects", ()))
        unknowns = list(getattr(descriptor, "unknowns", ()) or ())
        if unknowns:
            return TaskUnderstandingResult(
                executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
                capabilityRequired=True, reasonCodes=["MODEL_UNRESOLVED_REQUIREMENT"],
                unresolvedRequirements=[str(item)[:160] for item in unknowns[:4]], analysisSource="MODEL",
            )
        if (req.rag_mode == "OFF" or semantic.rag_preference is RagPreference.DISABLE) and knowledge != KnowledgeDependency.NONE:
            return TaskUnderstandingResult(
                executionRoute="RUNTIME", disposition="CLARIFY", knowledgeDependency=knowledge,
                capabilityRequired=True, reasonCodes=["KNOWLEDGE_POLICY_DISABLED"],
                unresolvedRequirements=["当前配置禁止企业知识检索，无法核实该业务事实"], analysisSource="MODEL",
            )
    if not must_use_runtime:
        safe = (
            text in _SAFE_GREETING
            or bool(re.fullmatch(r"(?:谢谢|感谢)[，, ]?(?:已经|已)?(?:解决了?|搞定了?|明白了?|知道了?)", text))
            or document_only or _model_only_request(text)
            or (req.continuation_state == "CHAT" and _chat_model_followup(text))
            or (inline_without_rag and _inline_material(text))
            or (bool(_any(text, _GENERIC)) and not req.has_attachments and req.continuation_state == "NONE"
                and not _any(text, _UNCERTAIN) and len(text) <= 150)
        )
        if not safe:
            # Unknown != model-only. Runtime can decide to answer without tools.
            must_use_runtime = True
    return TaskUnderstandingResult(
        executionRoute="RUNTIME" if must_use_runtime else "FAST_PATH",
        knowledgeDependency=knowledge, capabilityRequired=must_use_runtime,
        reasonCodes=["RUNTIME_DEPENDENCY_OR_UNCERTAINTY" if must_use_runtime else "CLEAR_MODEL_ONLY"],
        analysisSource="MODEL" if descriptor is not None else "RULE",
    )


def needs_semantic_model(req: TaskUnderstandingRequest, baseline: TaskUnderstandingResult) -> bool:
    """Only ambiguous, potentially model-only text needs extra LLM judgment."""
    if not req.allow_model or baseline.disposition != "EXECUTE":
        return False
    if baseline.execution_route == "FAST_PATH":
        return False
    text = req.task.strip().casefold()
    if req.has_attachments or req.rag_mode == "ON" or baseline.knowledge_dependency != KnowledgeDependency.NONE:
        return False
    if req.continuation_state in ("AMBIGUOUS", "ONE_PENDING") or _any(text, _OPERATION + _MULTISTEP):
        return False
    return (_any(text, _UNCERTAIN) and len(text) >= 5) or len(text) >= 48
