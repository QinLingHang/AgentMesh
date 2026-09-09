from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from app.mcp.contracts import MCPServerDefinition
    from app.schemas import AgentProfile
    from app.tools.contracts import ToolDefinition


class CapabilityKind(str, Enum):
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True, slots=True)
class CapabilityCandidate:
    kind: CapabilityKind
    identifier: str
    name: str
    description: str
    score: float
    selected: bool
    reason: str
    source: str = ""
    risk_level: str = "low"

    def trace_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "id": self.identifier,
            "name": self.name,
            "score": round(float(self.score), 4),
            "selected": bool(self.selected),
            "reason": self.reason,
            "source": self.source,
            "riskLevel": self.risk_level,
        }


@dataclass(slots=True)
class CapabilityDiscoveryResult:
    selected_tool_names: list[str] = field(default_factory=list)
    selected_mcp_server_ids: list[int] = field(default_factory=list)
    selected_mcp_tool_names: list[str] = field(default_factory=list)
    selected_skill_names: list[str] = field(default_factory=list)
    use_project_knowledge: bool = False
    candidates: list[CapabilityCandidate] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    @property
    def has_action_capability(self) -> bool:
        return bool(
            self.selected_tool_names
            or self.selected_mcp_server_ids
            or self.selected_mcp_tool_names
        )

    def trace_detail(self, *, limit: int = 24) -> dict[str, object]:
        ordered = sorted(
            self.candidates,
            key=lambda item: (
                not item.selected,
                -float(item.score),
                item.kind.value,
                item.name.casefold(),
            ),
        )
        return {
            "selectedTools": list(self.selected_tool_names),
            "selectedMCPServers": list(self.selected_mcp_server_ids),
            "selectedMCPTools": list(self.selected_mcp_tool_names),
            "selectedSkills": list(self.selected_skill_names),
            # Keep the legacy key for compatibility while exposing the
            # capability's real scope-neutral meaning to newer clients.
            "projectKnowledge": bool(self.use_project_knowledge),
            "knowledgeSelected": bool(self.use_project_knowledge),
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "candidates": [item.trace_dict() for item in ordered[: max(0, limit)]],
        }


_ASCII_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:/\\-]*", re.IGNORECASE)
_CHINESE_RUN = re.compile(r"[\u3400-\u9fff]+")
_PROJECT_CODE = re.compile(r"\b(?:p\d+|v\d+(?:\.\d+)*|[a-z]{2,}(?:[-_][a-z0-9]+)+)\b", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"\b[a-z]:[\\/]", re.IGNORECASE)
_UNIX_PATH = re.compile(r"(?:^|\s)/(?:home|users|tmp|var|opt|mnt|workspace)(?:/|\b)", re.IGNORECASE)


_CONTINUATION_EXACT = {
    "继续", "继续吧", "继续讲", "接着", "接着说", "可以", "好的", "好", "行",
    "没问题", "然后呢", "下一步", "下一步呢", "展开", "展开讲讲", "详细点",
    "再说说", "再来", "对", "对的", "是", "是的", "continue", "go on", "yes",
    "ok", "okay",
}

_CONTINUATION_PREFIXES = (
    "继续", "那继续", "好继续", "好的继续", "可以继续", "接着", "那接着",
    "然后", "下一步", "展开", "再说", "再来",
    "continue", "go on",
)

_CONTINUATION_TRIM = " \t\r\n，。！？!?；;：:、,.~～…"


def is_continuation_turn(text: str) -> bool:
    """Return True when the current turn mainly delegates to recent context.

    This deliberately stays conservative: a substantive request such as
    "可以介绍一下 Java 吗" must not be treated as a context-only continuation.
    """

    normalized = " ".join(str(text or "").casefold().split()).strip(_CONTINUATION_TRIM)
    if not normalized:
        return False
    compact = re.sub(r"[\s，。！？!?；;：:、,.~～…]+", "", normalized)
    if len(compact) == 1 and (compact.isdigit() or compact in {"a", "b", "c", "d"}):
        return True
    if compact in {re.sub(r"\s+", "", item) for item in _CONTINUATION_EXACT}:
        return True
    if len(compact) > 14:
        return False
    return any(compact.startswith(prefix.replace(" ", "")) for prefix in _CONTINUATION_PREFIXES)


def contextualize_discovery_task(
    task: str,
    history: Iterable[Any] = (),
    *,
    max_turns: int = 4,
    max_chars: int = 3200,
) -> tuple[str, bool, int]:
    """Use recent conversation only when a short follow-up cannot stand alone.

    Capability discovery must follow the same conversation as the answer model.
    Otherwise a turn such as "可以" could correctly preserve conversational
    context while losing the Tool/MCP/Skill/Knowledge capabilities needed to
    continue the previous operation. The returned text is request-local and is
    never persisted or emitted into trace.
    """

    current = str(task or "").strip()
    if not is_continuation_turn(current):
        return current, False, 0

    selected_reversed: list[tuple[str, str]] = []
    remaining = max(0, int(max_chars))

    items = list(history)
    for raw in reversed(items):
        if len(selected_reversed) >= max(1, int(max_turns)) or remaining <= 0:
            break

        if isinstance(raw, dict):
            role = str(raw.get("role", ""))
            content = str(raw.get("content", ""))
        else:
            role = str(getattr(raw, "role", ""))
            content = str(getattr(raw, "content", ""))

        role = role.casefold().strip()
        content = " ".join(content.split()).strip()
        if role not in {"user", "assistant"} or not content:
            continue

        bounded = content[: min(1200, remaining)]
        if not bounded:
            continue
        selected_reversed.append((role, bounded))
        remaining -= len(bounded)

    if not selected_reversed:
        return current, False, 0

    selected = list(reversed(selected_reversed))
    context_lines = [f"{role}: {content}" for role, content in selected]
    contextual = (
        "[Recent conversation for capability discovery]\n"
        + "\n".join(context_lines)
        + "\n[Current continuation]\n"
        + current
    )
    return contextual, True, len(selected)



def continuation_subject_task(
    task: str,
    history: Iterable[Any] = (),
) -> str:
    """Resolve a short follow-up back to the newest substantive user topic.

    Capability discovery can use a richer combined conversation query, but
    downstream retrieval should not search for a bare "继续/可以" or for a
    transcript containing assistant prose. For a continuation turn, return the
    newest non-continuation user message. Otherwise return the current task.
    """

    current = str(task or "").strip()
    if not is_continuation_turn(current):
        return current

    for raw in reversed(list(history)):
        if isinstance(raw, dict):
            role = str(raw.get("role", ""))
            content = str(raw.get("content", ""))
        else:
            role = str(getattr(raw, "role", ""))
            content = str(getattr(raw, "content", ""))

        content = " ".join(content.split()).strip()
        if role.casefold().strip() != "user" or not content:
            continue
        if is_continuation_turn(content):
            continue
        return content

    return current

def _features(text: str) -> set[str]:
    normalized = " ".join(str(text or "").casefold().split())
    result: set[str] = set(_ASCII_TOKEN.findall(normalized))

    for run in _CHINESE_RUN.findall(normalized):
        if len(run) <= 4:
            result.add(run)
        for width in (2, 3, 4):
            if len(run) < width:
                continue
            for index in range(0, len(run) - width + 1):
                result.add(run[index : index + width])

    return result


def _contains_any(text: str, values: Iterable[str]) -> bool:
    normalized = str(text or "").casefold()
    return any(value.casefold() in normalized for value in values)


def _overlap_score(task: str, descriptor: str) -> float:
    task_features = _features(task)
    candidate_features = _features(descriptor)
    if not task_features or not candidate_features:
        return 0.0

    overlap = task_features & candidate_features
    if not overlap:
        return 0.0

    coverage = len(overlap) / max(1.0, math.sqrt(len(task_features) * 2.0))
    bonus = min(0.30, math.log2(len(overlap) + 1) * 0.08)
    return min(1.0, coverage * 0.72 + bonus)


_DESKTOP_FAMILY_ALIASES: dict[str, str] = {
    "local.fs.": (
        "本机 本地 电脑 文件 文件夹 目录 路径 磁盘 桌面 下载 文档 文件系统 "
        "local computer file folder directory path filesystem desktop download"
    ),
    "local.app.": (
        "本机 本地 应用 软件 程序 启动 打开 聚焦 关闭 vscode chrome edge 浏览器 "
        "记事本 word excel powerpoint pycharm idea 剪映 微信开发者工具 "
        "local application app software program launch open focus close"
    ),
    "local.tool.": (
        "本机 命令行 cli 工具 运行 执行 编译 构建 测试 python pip git go java javac "
        "maven mvn gradle node npm pnpm yarn ffmpeg docker command line tool run build test"
    ),
    "local.terminal.": (
        "高级终端 终端 shell powershell pwsh cmd 命令 脚本 terminal console command"
    ),
    "local.ui.screen.": (
        "屏幕 截图 看桌面 画面 视觉 屏幕内容 screenshot screen desktop visual capture"
    ),
    "local.ui.window.": (
        "窗口 前台 聚焦 切换窗口 关闭窗口 window focus foreground switch close"
    ),
    "local.ui.mouse.": (
        "鼠标 点击 双击 右键 拖拽 滚动 移动 mouse click double right drag scroll move"
    ),
    "local.ui.keyboard.": (
        "键盘 输入 打字 按键 快捷键 keyboard type text press hotkey shortcut"
    ),
    "local.ui.element.": (
        "界面 控件 按钮 输入框 选项 ui uia automation element control button field select invoke"
    ),
    "local.ui.session.": (
        "桌面控制 computer use 会话 授权 session permission approval computer control"
    ),
    "local.ui.wait": "等待 界面刷新 wait ui update",
}


_DESKTOP_OPERATION_ALIASES: dict[str, str] = {
    "local.fs.list": "列出 有什么 有哪些 文件列表 目录内容 看看目录 查看目录 看看 查看 浏览 browse inspect list enumerate",
    "local.fs.stat": "属性 元数据 大小 修改时间 stat metadata size",
    "local.fs.read": "读取 打开 看内容 read content text",
    "local.fs.search": "搜索 查找 找文件 搜内容 search find grep",
    "local.fs.write": "写入 保存 新建文件 修改文件 write save create file",
    "local.fs.mkdir": "新建目录 创建文件夹 mkdir create folder directory",
    "local.fs.copy": "复制 拷贝 copy duplicate",
    "local.fs.move": "移动 重命名 move rename",
    "local.fs.delete": "删除 移除 delete remove",
    "local.app.list": "应用列表 软件列表有哪些 list apps",
    "local.app.discover": "发现软件 扫描应用 discover applications",
    "local.app.launch": "启动 打开 启动应用 打开软件 launch start app",
    "local.app.open": "用软件打开文件 open file with app",
    "local.app.status": "运行状态 进程状态 status running app",
    "local.app.focus": "聚焦 切到前台 focus foreground",
    "local.app.close": "关闭软件 结束应用 close terminate app",
    "local.tool.list": "命令行工具列表 cli list tools",
    "local.tool.discover": "扫描命令行工具 discover cli path",
    "local.tool.run": "运行 执行 运行命令 执行工具 构建 测试 run execute build test",
    "local.tool.status": "进程结果 输出 状态 stdout stderr status output",
    "local.tool.cancel": "取消 停止进程 cancel stop process",
    "local.terminal.run": "运行任意终端命令 shell command terminal run",
    "local.terminal.status": "终端输出 状态 terminal status output",
    "local.terminal.cancel": "取消终端 停止命令 terminal cancel stop",
    "local.ui.screen.capture": "截图 屏幕 看屏幕 屏幕截图 capture screenshot",
    "local.ui.window.list": "窗口列表 有哪些窗口 list windows",
    "local.ui.window.info": "窗口信息 window info",
    "local.ui.window.focus": "聚焦窗口 切窗口 focus window",
    "local.ui.window.close": "关闭窗口 close window",
    "local.ui.mouse.move": "移动鼠标 move mouse",
    "local.ui.mouse.click": "点击 click mouse",
    "local.ui.mouse.double_click": "双击 double click",
    "local.ui.mouse.right_click": "右键 right click",
    "local.ui.mouse.drag": "拖拽 drag",
    "local.ui.mouse.scroll": "滚动 scroll",
    "local.ui.keyboard.type": "键盘输入 打字 type text",
    "local.ui.keyboard.press": "按键 press key",
    "local.ui.keyboard.hotkey": "快捷键 hotkey shortcut",
    "local.ui.element.find": "找控件 查找按钮 输入框 find element control",
    "local.ui.element.click": "点击控件 click element button",
    "local.ui.element.set_text": "填写输入框 设置文本 set text input field",
    "local.ui.element.invoke": "触发按钮 执行动作 invoke action",
    "local.ui.element.select": "选择选项 select option",
    "local.ui.wait": "等待界面 wait ui",
}



_DOMAIN_ALIASES: dict[str, str] = {
    "calculator": "计算 算一下 求值 算术 数学 表达式 arithmetic calculate compute math",
    "current_time": "当前时间 现在几点 日期 时间 时区 date time timezone",
    "text_stats": "文本统计 字数 字符数 行数 单词数 text statistics words lines characters",
    "order": "订单 订单状态 查询订单 物流 发货 order status shipping",
    "shipping": "物流 配送 发货 快递 shipping delivery logistics",
    "weather": "天气 气温 温度 城市 weather temperature city",
    "email": "邮件 邮箱 发邮件 发送邮件 email mail send",
    "mail": "邮件 邮箱 发邮件 发送邮件 email mail send",
    "github": "github pull request pr issue 仓库 代码仓库 repo",
    "gitlab": "gitlab merge request mr issue 仓库 代码仓库 repo",
    "jira": "jira 工单 issue ticket 项目管理",
    "slack": "slack 消息 频道 channel message",
    "notion": "notion 页面 page database 文档",
    "calendar": "日历 会议 日程 预约 calendar meeting schedule",
    "search": "搜索 查找 查询 search find lookup",
    "lookup": "查询 查找 lookup search",
    "database": "数据库 数据 查询 database sql",
    "sql": "数据库 sql 查询 数据",
    "file": "文件 文档 file document",
    "document": "文档 文件 document file",
    "code_review": "代码审查 代码评审 review code defect bug",
}


def _domain_aliases(descriptor: str) -> str:
    normalized = descriptor.casefold()
    aliases: list[str] = []
    for marker, value in _DOMAIN_ALIASES.items():
        if marker in normalized:
            aliases.append(value)
    return " ".join(aliases)


_PROJECT_KNOWLEDGE_ALIASES = (
    "知识库 全局知识 个人知识 上传资料 已上传资料 内部资料 项目 项目资料 项目文档 项目文件 "
    "当前项目 本项目 这个项目 我们项目 文档 文件 资料 简历 履历 个人资料 教育经历 工作经历 项目经历 "
    "架构 设计 实现 需求 规范 方案 里程碑 版本 roadmap 代码库 repository repo "
    "knowledge base global knowledge personal knowledge uploaded document resume cv profile "
    "project knowledge internal docs documentation architecture design implementation requirement source"
)

_PROJECT_SIGNALS = (
    "知识库",
    "项目资料",
    "项目文档",
    "项目文件",
    "当前项目",
    "本项目",
    "这个项目",
    "我们项目",
    "根据资料",
    "根据文档",
    "从文档",
    "agentmesh",
    "roadmap",
    "repository",
    "repo",
    "代码库",
    "全局知识",
    "全局知识库",
    "个人知识",
    "个人资料",
    "上传的资料",
    "上传资料",
    "已上传",
    "我的简历",
    "这份简历",
    "那份简历",
)

_PERSONAL_KNOWLEDGE_SIGNALS = (
    "我的简历", "我简历", "这份简历", "那份简历", "上传的简历", "简历文件",
    "我的资料", "个人资料", "我上传的", "之前上传", "知识库里的", "知识库中",
    "简历怎么样", "简历如何", "评价简历", "分析简历", "看看简历",
    "resume", "curriculum vitae", "uploaded document", "my document",
)

_EXTERNAL_ACTION_SIGNALS = (
    "github",
    "gitlab",
    "jira",
    "slack",
    "notion",
    "gmail",
    "outlook",
    "飞书",
    "钉钉",
    "企业微信",
    "邮件",
    "邮箱",
    "天气",
    "订单",
    "物流",
    "退款",
    "支付",
    "外部服务",
    "第三方",
    "mcp",
    "api",
    "pull request",
    "issue",
    "pr",
)

_EXPLANATION_SIGNALS = (
    "什么是",
    "是什么",
    "区别",
    "差别",
    "原理",
    "概念",
    "介绍一下",
    "解释一下",
    "为什么",
    "优缺点",
    "what is",
    "difference",
    "compare",
    "explain",
    "concept",
    "why",
)

_OBSERVATION_OR_ACTION_SIGNALS = (
    "今天",
    "现在",
    "当前",
    "最新",
    "实时",
    "多少",
    "有没有",
    "状态",
    "详情",
    "内容",
    "列出",
    "查看",
    "看看",
    "查询",
    "查一下",
    "查找",
    "获取",
    "搜索",
    "打开",
    "启动",
    "运行",
    "执行",
    "创建",
    "新建",
    "发送",
    "更新",
    "修改",
    "删除",
    "同步",
    "current",
    "latest",
    "status",
    "details",
    "list",
    "get",
    "fetch",
    "search",
    "open",
    "launch",
    "run",
    "execute",
    "create",
    "send",
    "update",
    "delete",
    "sync",
)


def _is_explanatory_only(task: str) -> bool:
    return (
        _contains_any(task, _EXPLANATION_SIGNALS)
        and not _contains_any(task, _OBSERVATION_OR_ACTION_SIGNALS)
    )

_ACTION_SIGNALS = (
    "打开",
    "启动",
    "运行",
    "执行",
    "创建",
    "新建",
    "写入",
    "修改",
    "删除",
    "复制",
    "移动",
    "搜索",
    "查找",
    "截图",
    "点击",
    "输入",
    "发送",
    "查询",
    "检查",
    "帮我看",
    "帮我查",
    "帮我运行",
    "帮我打开",
    "open",
    "launch",
    "run",
    "execute",
    "create",
    "write",
    "delete",
    "search",
    "click",
    "send",
    "check",
)


def _descriptor_for_tool(tool: ToolDefinition) -> str:
    name = str(tool.name or "").strip()
    parts = [name, str(tool.description or "")]

    lowered = name.casefold()
    operation_aliases = _DESKTOP_OPERATION_ALIASES.get(lowered)
    if operation_aliases:
        parts.append(operation_aliases)

    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if isinstance(properties, dict):
        parts.extend(str(key) for key in properties.keys())
        for value in properties.values():
            if isinstance(value, dict) and value.get("description"):
                parts.append(str(value.get("description")))

    base = " ".join(part for part in parts if part)
    translated = _domain_aliases(base)
    return (base + " " + translated).strip()



def _tool_family_boost(task: str, name: str) -> tuple[float, str]:
    lower_name = name.casefold()
    normalized = task.casefold()

    groups: list[tuple[str, tuple[str, ...], float]] = [
        ("local.fs.", ("桌面", "文件", "文件夹", "目录", "路径", "本机", "本地", "desktop", "file", "folder", "directory", "path"), 0.18),
        ("local.app.", ("应用", "软件", "程序", "vscode", "vs code", "chrome", "edge", "浏览器", "记事本", "app", "application", "software"), 0.18),
        ("local.tool.", ("python", "git", "golang", " go ", "node", "npm", "pnpm", "yarn", "ffmpeg", "docker", "编译", "构建", "测试", "命令行", "cli"), 0.18),
        ("local.terminal.", ("powershell", "pwsh", "cmd", "shell", "终端", "terminal"), 0.22),
        ("local.ui.screen.", ("屏幕", "截图", "画面", "screenshot", "screen"), 0.24),
        ("local.ui.window.", ("窗口", "window"), 0.18),
        ("local.ui.mouse.", ("鼠标", "点击", "双击", "右键", "拖拽", "滚动", "mouse", "click", "drag", "scroll"), 0.18),
        ("local.ui.keyboard.", ("键盘", "输入", "打字", "快捷键", "keyboard", "type", "hotkey"), 0.18),
        ("local.ui.element.", ("控件", "按钮", "输入框", "界面元素", "uia", "button", "field", "element"), 0.18),
    ]

    for prefix, signals, boost in groups:
        if not lower_name.startswith(prefix):
            continue
        if not any(signal in normalized for signal in signals):
            continue

        # Mentioning a programming language is not by itself a request to run
        # local code. "Python 和 Java 有什么区别" must remain ordinary chat.
        if prefix == "local.tool.":
            explicit_cli = any(
                signal in normalized
                for signal in ("命令行", "cli", "构建", "编译", "测试", "npm", "pnpm", "yarn", "ffmpeg", "docker")
            )
            if not explicit_cli and not _contains_any(task, _ACTION_SIGNALS):
                return 0.0, ""

        # Application names alone may occur in an explanatory question. Require
        # an action cue unless the user explicitly asks about running status.
        if prefix == "local.app.":
            if not _contains_any(task, _ACTION_SIGNALS) and not any(
                signal in normalized
                for signal in ("运行状态", "是否运行", "running", "status")
            ):
                return 0.0, ""

        return boost, f"task matches {prefix.rstrip('.')} capability family"

    if _WINDOWS_PATH.search(task) or _UNIX_PATH.search(task):
        if lower_name.startswith("local.fs."):
            return 0.44, "task contains an explicit local filesystem path"
        if lower_name.startswith("local.tool."):
            return 0.18, "task contains a local working path"

    return 0.0, ""


def _operation_boost(task: str, name: str) -> tuple[float, str]:
    normalized = task.casefold()
    aliases = _DESKTOP_OPERATION_ALIASES.get(name.casefold(), "")
    if not aliases:
        return 0.0, ""

    alias_tokens = [item for item in aliases.split() if len(item) >= 2]
    matched = [item for item in alias_tokens if item.casefold() in normalized]
    if not matched:
        return 0.0, ""

    return min(0.34, 0.16 + len(matched) * 0.06), "operation intent: " + ", ".join(matched[:3])


def _rank_tool(task: str, tool: ToolDefinition, *, kind: CapabilityKind) -> CapabilityCandidate:
    descriptor = _descriptor_for_tool(tool)
    score = _overlap_score(task, descriptor)
    reasons: list[str] = []

    # Capability descriptions are often English even when the user's task is
    # Chinese. Domain aliases are intentionally scored a second time as a
    # bounded cross-language semantic bridge. This is not a hard-coded route to
    # one concrete tool: the alias set is derived from the tool's own
    # name/description/schema, and Top-K ranking still decides which capability
    # is injected.
    domain_descriptor = _domain_aliases(
        " ".join(
            part
            for part in (
                str(tool.name or ""),
                str(tool.description or ""),
            )
            if part
        )
    )
    domain_overlap = _overlap_score(task, domain_descriptor)
    if domain_overlap > 0:
        score += min(0.22, 0.08 + domain_overlap * 0.45)
        reasons.append("cross-language capability-domain match")

    family_boost, family_reason = _tool_family_boost(task, tool.name)
    if family_boost:
        score += family_boost
        reasons.append(family_reason)

    operation_boost, operation_reason = _operation_boost(task, tool.name)
    if operation_boost:
        score += operation_boost
        reasons.append(operation_reason)

    if (
        tool.name.casefold().startswith("local.")
        and not tool.name.casefold().startswith("local.ui.session.")
        and tool.name.casefold() not in task.casefold()
    ):
        # Local operation words such as “打开” are ambiguous across families.
        # Require a matching local family (file/app/CLI/UI) before allowing the
        # operation score to cross the selection threshold.
        if family_boost <= 0 and not (_WINDOWS_PATH.search(task) or _UNIX_PATH.search(task)):
            score = min(score, 0.22)
        elif not operation_boost:
            # A family cue such as “本机文件” should discover the right
            # operation, not every write/delete/close primitive.
            score = min(score, 0.27)

    lower_tool_name = tool.name.casefold()
    if lower_tool_name.startswith("local.fs."):
        mutating_fs = {
            "local.fs.write", "local.fs.mkdir", "local.fs.copy",
            "local.fs.move", "local.fs.delete",
        }
        mutation_cues = (
            "写入", "保存", "新建", "创建", "复制", "拷贝", "移动",
            "重命名", "删除", "移除", "修改", "覆盖",
            "write", "save", "create", "copy", "move", "rename", "delete", "remove",
        )
        if lower_tool_name in mutating_fs and not _contains_any(task, mutation_cues):
            # An explicit path or a generic “看看/查看” request must never
            # fall through a tied filesystem score to a mutating primitive.
            score = min(score, 0.18)
            reasons.append("read-only filesystem intent; mutating primitive suppressed")

    if tool.name.casefold() in task.casefold():
        score += 0.55
        reasons.append("tool explicitly referenced")

    if kind in {CapabilityKind.TOOL, CapabilityKind.MCP_TOOL} and _contains_any(task, _ACTION_SIGNALS):
        if _overlap_score(task, str(tool.description or "")) > 0:
            score += 0.08

    if _is_explanatory_only(task):
        # A capability can be topically related without being needed. Questions
        # such as “GitHub 是什么” or “解释天气系统原理” should remain ordinary
        # model reasoning rather than causing side-effect/data tools to run.
        score = min(score, 0.22)
        reasons.append("explanatory-only request; capability execution not required")

    score = min(1.0, score)
    return CapabilityCandidate(
        kind=kind,
        identifier=str(tool.name),
        name=str(tool.name),
        description=str(tool.description or ""),
        score=score,
        selected=False,
        reason="; ".join(reasons) or "lexical/semantic descriptor overlap",
        source=("mcp" if kind == CapabilityKind.MCP_TOOL else str(tool.protocol or "tool")),
        risk_level=str(tool.risk_level or "low"),
    )


def _knowledge_candidate(task: str, *, has_attachments: bool) -> CapabilityCandidate:
    if has_attachments:
        return CapabilityCandidate(
            kind=CapabilityKind.KNOWLEDGE,
            identifier="scoped_knowledge",
            name="Scoped Knowledge",
            description=_PROJECT_KNOWLEDGE_ALIASES,
            score=0.0,
            selected=False,
            reason="request-local attachment is authoritative for this turn",
            source="knowledge",
        )

    score = _overlap_score(task, _PROJECT_KNOWLEDGE_ALIASES)
    reasons: list[str] = []

    if _contains_any(task, _PROJECT_SIGNALS):
        score += 0.48
        reasons.append("user/project knowledge cue")

    if _contains_any(task, _PERSONAL_KNOWLEDGE_SIGNALS):
        score += 0.52
        reasons.append("personal or uploaded knowledge cue")

    # A request to assess a concrete resume/document is normally about the
    # user's scoped knowledge rather than generic resume-writing advice.
    # Retrieval remains safely limited by the authoritative Go knowledge scope.
    lowered = task.casefold()
    if ("简历" in lowered or "resume" in lowered or "cv" in lowered) and _contains_any(
        task,
        ("怎么样", "如何", "评价", "分析", "看看", "内容", "经历", "是谁", "介绍"),
    ):
        score += 0.34
        reasons.append("concrete resume/document assessment cue")

    if _PROJECT_CODE.search(task):
        score += 0.24
        reasons.append("project/version identifier cue")

    uppercase_terms = re.findall(r"\b[A-Z][A-Z0-9_-]{2,}\b", task)
    if uppercase_terms and _contains_any(
        task,
        ("设计", "实现", "架构", "方案", "怎么做", "怎么写", "配置", "机制", "design", "implementation", "architecture"),
    ):
        score += 0.28
        reasons.append("project-specific technical identifier")

    score = min(1.0, score)
    return CapabilityCandidate(
        kind=CapabilityKind.KNOWLEDGE,
        identifier="scoped_knowledge",
        name="Scoped Knowledge",
        description=_PROJECT_KNOWLEDGE_ALIASES,
        score=score,
        selected=False,
        reason="; ".join(reasons) or "project knowledge descriptor overlap",
        source="knowledge",
    )


def _skill_candidates(task: str, agents: Iterable[AgentProfile]) -> list[CapabilityCandidate]:
    result: list[CapabilityCandidate] = []
    for agent in agents:
        for raw_capability in agent.capabilities:
            capability = str(raw_capability or "").strip()
            if not capability or capability.casefold() == "general":
                continue
            descriptor = " ".join(
                part
                for part in (
                    capability.replace("_", " ").replace("-", " "),
                    agent.name,
                    agent.description,
                    _domain_aliases(
                        " ".join(
                            part
                            for part in (capability, agent.name, agent.description)
                            if part
                        )
                    ),
                    "skill 技能 agent capability 智能体能力",
                )
                if part
            )
            score = _overlap_score(task, descriptor)
            if capability.casefold() in task.casefold():
                score += 0.40
            score = min(1.0, score)
            result.append(
                CapabilityCandidate(
                    kind=CapabilityKind.SKILL,
                    identifier=f"agent:{agent.id}:{capability}",
                    name=capability,
                    description=agent.description,
                    score=score,
                    selected=False,
                    reason=f"Agent/A2A skill advertised by {agent.name}",
                    source=agent.name,
                )
            )
    return result


def _mcp_server_candidate(task: str, server: MCPServerDefinition) -> CapabilityCandidate:
    descriptor = (
        f"{server.name} {server.endpoint} MCP external service connector integration "
        "外部服务 第三方 连接器 工具"
    )
    score = _overlap_score(task, descriptor)
    reasons: list[str] = []

    # MCP server metadata is frequently English while the user's task is
    # Chinese. Reuse the same bounded domain bridge used for custom tools so a
    # server named "Weather Service" or "GitHub Connector" can be
    # discovered without requiring the user to say the server name or "MCP".
    domain_descriptor = _domain_aliases(f"{server.name} {server.endpoint}")
    domain_overlap = _overlap_score(task, domain_descriptor)
    if domain_overlap > 0:
        score += min(0.28, 0.10 + domain_overlap * 0.50)
        reasons.append("cross-language MCP domain match")

    if server.name and server.name.casefold() in task.casefold():
        score += 0.55
        reasons.append("MCP server explicitly referenced by name")

    server_tokens = _features(server.name)
    task_tokens = _features(task)
    if server_tokens & task_tokens:
        score += 0.26
        reasons.append("task matches MCP server identity")

    if _contains_any(task, _EXTERNAL_ACTION_SIGNALS):
        score += 0.12
        reasons.append("external-service intent")

    if _is_explanatory_only(task):
        score = min(score, 0.22)
        reasons.append("explanatory-only request; external connector not required")

    score = min(1.0, score)
    return CapabilityCandidate(
        kind=CapabilityKind.MCP_SERVER,
        identifier=str(server.id),
        name=server.name,
        description=descriptor,
        score=score,
        selected=False,
        reason="; ".join(reasons) or "MCP server descriptor overlap",
        source="mcp",
    )


def _mark(candidate: CapabilityCandidate, selected: bool) -> CapabilityCandidate:
    return CapabilityCandidate(
        kind=candidate.kind,
        identifier=candidate.identifier,
        name=candidate.name,
        description=candidate.description,
        score=candidate.score,
        selected=selected,
        reason=candidate.reason,
        source=candidate.source,
        risk_level=candidate.risk_level,
    )


def _expand_desktop_dependencies(selected: set[str], available: set[str]) -> None:
    if any(name.startswith("local.ui.") and not name.startswith("local.ui.session.") for name in selected):
        for dependency in (
            "local.ui.session.start",
            "local.ui.session.status",
            "local.ui.session.stop",
        ):
            if dependency in available:
                selected.add(dependency)

    if "local.tool.run" in selected:
        for dependency in (
            "local.tool.list",
            "local.tool.discover",
            "local.tool.status",
            "local.tool.cancel",
        ):
            if dependency in available:
                selected.add(dependency)

    if "local.terminal.run" in selected:
        for dependency in (
            "local.terminal.status",
            "local.terminal.cancel",
        ):
            if dependency in available:
                selected.add(dependency)

    if selected & {"local.app.launch", "local.app.open"}:
        for dependency in (
            "local.app.list",
            "local.app.discover",
            "local.app.status",
            "local.app.focus",
        ):
            if dependency in available:
                selected.add(dependency)


def discover_capabilities(
    task: str,
    *,
    tools: Iterable[ToolDefinition] = (),
    mcp_servers: Iterable[MCPServerDefinition] = (),
    agents: Iterable[AgentProfile] = (),
    has_attachments: bool = False,
    max_tools: int = 8,
    max_mcp_servers: int = 3,
    max_skills: int = 4,
) -> CapabilityDiscoveryResult:
    enabled_tools = [tool for tool in tools if bool(tool.enabled)]
    enabled_mcp = [server for server in mcp_servers if bool(server.enabled)]

    tool_candidates = [
        _rank_tool(task, tool, kind=CapabilityKind.TOOL)
        for tool in enabled_tools
    ]
    tool_candidates.sort(key=lambda item: (-item.score, item.name.casefold()))

    selected_tool_names: set[str] = {
        item.name
        for item in tool_candidates[: max(1, max_tools)]
        if item.score >= 0.30
    }

    if not selected_tool_names and tool_candidates:
        best = tool_candidates[0]
        if best.name.startswith("local.") and best.score >= 0.24:
            selected_tool_names.add(best.name)

    available_names = {tool.name for tool in enabled_tools}
    _expand_desktop_dependencies(selected_tool_names, available_names)

    mcp_candidates = [_mcp_server_candidate(task, server) for server in enabled_mcp]
    mcp_candidates.sort(key=lambda item: (-item.score, item.name.casefold()))
    selected_mcp_ids = [
        int(item.identifier)
        for item in mcp_candidates[: max(1, max_mcp_servers)]
        if item.score >= 0.28
    ]

    if (
        not selected_mcp_ids
        and len(enabled_mcp) == 1
        and _contains_any(task, _EXTERNAL_ACTION_SIGNALS)
        and not _is_explanatory_only(task)
    ):
        # When exactly one governed connector is available, an explicit
        # external-data/action intent may use it as a bounded fallback. Never
        # fan out to multiple unrelated MCP servers merely because the user
        # asked for an external action.
        selected_mcp_ids = [enabled_mcp[0].id]

    skill_candidates = _skill_candidates(task, agents)
    skill_candidates.sort(key=lambda item: (-item.score, item.name.casefold(), item.source.casefold()))
    selected_skill_names: list[str] = []
    seen_skills: set[str] = set()
    for candidate in skill_candidates:
        if candidate.score < 0.34:
            continue
        normalized = candidate.name.casefold()
        if normalized in seen_skills:
            continue
        selected_skill_names.append(candidate.name)
        seen_skills.add(normalized)
        if len(selected_skill_names) >= max(1, max_skills):
            break

    knowledge = _knowledge_candidate(task, has_attachments=has_attachments)
    use_project_knowledge = knowledge.score >= 0.38

    selected_tool_lookup = {name.casefold() for name in selected_tool_names}
    selected_mcp_lookup = {str(value) for value in selected_mcp_ids}
    selected_skill_lookup = {name.casefold() for name in selected_skill_names}

    candidates: list[CapabilityCandidate] = []
    candidates.extend(
        _mark(item, item.name.casefold() in selected_tool_lookup)
        for item in tool_candidates
    )
    candidates.extend(
        _mark(item, item.identifier in selected_mcp_lookup)
        for item in mcp_candidates
    )
    candidates.extend(
        _mark(item, item.name.casefold() in selected_skill_lookup)
        for item in skill_candidates
    )
    candidates.append(_mark(knowledge, use_project_knowledge))

    selected_scores = [item.score for item in candidates if item.selected]
    confidence = max(selected_scores, default=0.0)
    if selected_tool_names or selected_mcp_ids or selected_skill_names or use_project_knowledge:
        reason = "relevant capabilities were discovered from the request-scoped catalog"
    else:
        reason = "no request-scoped capability exceeded the relevance threshold; use base model"

    return CapabilityDiscoveryResult(
        selected_tool_names=sorted(selected_tool_names),
        selected_mcp_server_ids=selected_mcp_ids,
        selected_skill_names=selected_skill_names,
        use_project_knowledge=use_project_knowledge,
        candidates=candidates,
        confidence=confidence,
        reason=reason,
    )


def discover_mcp_tools(
    task: str,
    tools: Iterable[ToolDefinition],
    *,
    max_tools: int = 6,
) -> CapabilityDiscoveryResult:
    candidates = [
        _rank_tool(task, tool, kind=CapabilityKind.MCP_TOOL)
        for tool in tools
        if bool(tool.enabled)
    ]
    candidates.sort(key=lambda item: (-item.score, item.name.casefold()))

    selected = [
        item.name
        for item in candidates[: max(1, max_tools)]
        if item.score >= 0.25
    ]

    if not selected and 0 < len(candidates) <= 3:
        selected = [item.name for item in candidates]

    selected_lookup = {name.casefold() for name in selected}
    marked = [_mark(item, item.name.casefold() in selected_lookup) for item in candidates]
    return CapabilityDiscoveryResult(
        selected_mcp_tool_names=selected,
        candidates=marked,
        confidence=max((item.score for item in marked if item.selected), default=0.0),
        reason=(
            "relevant MCP tools selected after remote discovery"
            if selected
            else "MCP server connected but no tool matched the task"
        ),
    )


def discovery_context(result: CapabilityDiscoveryResult) -> str:
    lines: list[str] = []
    if result.selected_tool_names:
        lines.append("tools=" + ", ".join(result.selected_tool_names))
    if result.selected_mcp_tool_names:
        lines.append("mcp_tools=" + ", ".join(result.selected_mcp_tool_names))
    if result.selected_skill_names:
        lines.append("skills=" + ", ".join(result.selected_skill_names))
    if result.use_project_knowledge:
        lines.append("scoped_knowledge=selected")

    if not lines:
        return ""

    return (
        "[Autonomous Capability Discovery]\n"
        + "\n".join(lines)
        + "\n\n"
        + "AgentMesh selected these capabilities because they are relevant to the current task. "
        + "Use an available tool when it can directly observe or perform what the user requested. "
        + "Do not claim that a selected capability is unavailable before attempting the appropriate tool. "
        + "If execution requires approval or authorization, call the capability normally so Runtime can request it."
    )
