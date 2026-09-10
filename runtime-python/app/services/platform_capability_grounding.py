from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


_PLATFORM_STRONG_SIGNALS = (
    "agentmesh",
    "这个系统",
    "你这个系统",
    "当前系统",
    "这个平台",
    "当前平台",
    "当前界面",
    "能力中心",
    "生态中心",
    "直接操作",
    "直接给我操作",
    "你能操作",
    "你能直接",
)

_PLATFORM_DOMAIN_SIGNALS = (
    "插件",
    "插件化",
    "工作流",
    "plugin",
    "workflow",
    "marketplace",
    "registry",
    "capability",
)

_PLATFORM_REFERENTS = (
    "你", "这个", "当前", "平台", "系统", "界面", "agentmesh",
)


_FAKE_PLATFORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "unverified_agentmesh_domain",
        re.compile(r"https?://[^\s`<>()]*agentmesh\.ai(?:/[^\s`<>()]*)?", re.IGNORECASE),
    ),
    (
        "unverified_agentmesh_version",
        re.compile(r"\bagentmesh\s+v\d+(?:\.\d+){0,3}\+?\b", re.IGNORECASE),
    ),
    (
        "unverified_workflow_permission",
        re.compile(r"\bworkflow:[a-z][a-z0-9_.-]*\b", re.IGNORECASE),
    ),
    (
        "unverified_workflow_engine",
        re.compile(r"\bworkflow[-_]?engine\b", re.IGNORECASE),
    ),
)

_UNVERIFIED_UI_PHRASES = (
    "从 yaml 导入",
    "工作流管理页",
    "工作流页",
    "新建工作流",
    "保存并启用",
    "系统设置 > 邮件服务",
    "系统设置→邮件服务",
    "联系技术支持开通",
    "企业客户开放",
)

_DIRECT_OPERATION_DENIALS = (
    "我无法直接操作您的 agentmesh",
    "我无法直接操作你的 agentmesh",
    "我无法直接操作您的电脑",
    "我无法直接操作你的电脑",
    "所有操作必须由您本人",
    "所有操作必须由你本人",
    "必须由您本人在浏览器中完成",
    "必须由你本人在浏览器中完成",
)

_PLUGIN_YAML = re.compile(
    r"(?im)^\s*plugin\s*:\s*[\"']?([a-z0-9][a-z0-9_.-]*)[\"']?\s*$"
)


@dataclass(slots=True, frozen=True)
class PlatformCapabilityGuardResult:
    passed: bool
    action: str
    answer: str
    violations: tuple[str, ...] = ()


def is_platform_capability_query(task: str, history: Iterable[Any] = ()) -> bool:
    """Return True for questions about the current AgentMesh product/instance.

    This classifier is deliberately narrow. General software-engineering questions
    about plugins/workflows can still be answered normally when they do not refer
    to the current platform. Recent history is consulted only to preserve a short
    follow-up such as "你能直接给我操作吗" after an AgentMesh capability turn.
    """

    current = " ".join(str(task or "").casefold().split())
    if any(signal in current for signal in _PLATFORM_STRONG_SIGNALS):
        return True

    has_domain = any(signal in current for signal in _PLATFORM_DOMAIN_SIGNALS)
    if has_domain and any(referent in current for referent in _PLATFORM_REFERENTS):
        return True

    history_has_platform = False
    for raw in reversed(list(history)[-4:]):
        if isinstance(raw, dict):
            content = str(raw.get("content", ""))
        else:
            content = str(getattr(raw, "content", ""))
        normalized = " ".join(content.casefold().split())
        if any(signal in normalized for signal in _PLATFORM_STRONG_SIGNALS):
            history_has_platform = True
            break
        if (
            any(signal in normalized for signal in _PLATFORM_DOMAIN_SIGNALS)
            and any(referent in normalized for referent in _PLATFORM_REFERENTS)
        ):
            history_has_platform = True
            break

    if has_domain and history_has_platform:
        return True

    follow_up = current.strip(" ，。！？!?；;：:、")
    if (
        history_has_platform
        and follow_up
        in {"可以吗", "能吗", "怎么做", "怎么用", "怎么弄", "能直接做吗"}
    ):
        return True

    return False


def _bounded_name(value: Any, *, limit: int = 100) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _tool_rows(tools: Iterable[Any], *, limit: int = 48) -> list[str]:
    rows: list[str] = []
    for tool in tools:
        if getattr(tool, "enabled", True) is False:
            continue
        name = _bounded_name(getattr(tool, "name", ""))
        if not name:
            continue
        description = _bounded_name(getattr(tool, "description", ""), limit=140)
        risk = _bounded_name(getattr(tool, "risk_level", getattr(tool, "riskLevel", "")), limit=16)
        suffix = ""
        if description:
            suffix += f" — {description}"
        if risk:
            suffix += f" [risk={risk}]"
        rows.append(name + suffix)
        if len(rows) >= limit:
            break
    return rows


def _agent_rows(agents: Iterable[Any], *, limit: int = 24) -> list[str]:
    rows: list[str] = []
    for agent in agents:
        name = _bounded_name(getattr(agent, "name", ""))
        if not name:
            continue
        capabilities = getattr(agent, "capabilities", ()) or ()
        caps = [
            _bounded_name(item, limit=48)
            for item in list(capabilities)[:8]
            if _bounded_name(item, limit=48)
        ]
        rows.append(name + (f" ({', '.join(caps)})" if caps else ""))
        if len(rows) >= limit:
            break
    return rows


def _mcp_rows(servers: Iterable[Any], *, limit: int = 24) -> list[str]:
    rows: list[str] = []
    for server in servers:
        enabled = getattr(server, "enabled", True)
        if enabled is False:
            continue
        name = _bounded_name(
            getattr(server, "name", "")
            or getattr(server, "server_name", "")
            or getattr(server, "id", "")
        )
        if name:
            rows.append(name)
        if len(rows) >= limit:
            break
    return rows


def _names(values: Iterable[Any]) -> set[str]:
    result: set[str] = set()
    for value in values:
        name = _bounded_name(getattr(value, "name", ""))
        if name:
            result.add(name.casefold())
    return result


def build_platform_capability_context(
    *,
    task: str,
    history: Iterable[Any] = (),
    tools: Iterable[Any] = (),
    mcp_servers: Iterable[Any] = (),
    agents: Iterable[Any] = (),
    selected_tool_names: Iterable[str] = (),
    selected_mcp_tool_names: Iterable[str] = (),
) -> str:
    """Build an authoritative request-local product capability snapshot.

    The snapshot intentionally says what Runtime *can verify* rather than trying
    to mirror every control-plane screen. That makes stale model priors harmless:
    UI routes, versions, permission names and plugin/workflow schemas are never
    treated as facts unless the execution request actually exposes them.
    """

    if not is_platform_capability_query(task, history):
        return ""

    tool_rows = _tool_rows(tools)
    agent_rows = _agent_rows(agents)
    mcp_rows = _mcp_rows(mcp_servers)
    selected_tools = [_bounded_name(item) for item in selected_tool_names if _bounded_name(item)]
    selected_mcp = [_bounded_name(item) for item in selected_mcp_tool_names if _bounded_name(item)]

    lines = [
        "[AgentMesh Current-Instance Capability Grounding — AUTHORITATIVE]",
        "The following snapshot is the only authoritative source for claims about what this current AgentMesh instance can execute in this request.",
        "Do not use model priors to invent AgentMesh product features.",
        "",
        "Registered runtime tools:",
    ]
    lines.extend(f"- {item}" for item in tool_rows)
    if not tool_rows:
        lines.append("- (none exposed in this request)")

    lines.append("Registered MCP servers:")
    lines.extend(f"- {item}" for item in mcp_rows)
    if not mcp_rows:
        lines.append("- (none exposed in this request)")

    lines.append("Registered agents:")
    lines.extend(f"- {item}" for item in agent_rows)
    if not agent_rows:
        lines.append("- (none exposed in this request)")

    lines.append("Selected capabilities for this turn:")
    selected = [*selected_tools, *selected_mcp]
    lines.extend(f"- {item}" for item in selected)
    if not selected:
        lines.append("- (none selected)")

    lines.extend(
        [
            "",
            "Strict platform-grounding rules:",
            "1. Never invent AgentMesh menus/pages, hosted domains, version numbers, permission names, YAML schemas, plugin names, workflow modules, installation paths, enterprise gating or support-contact instructions.",
            "2. A dedicated Workflow/YAML-import UI is NOT verified by this Runtime snapshot. Never tell the user to navigate to '工作流 -> YAML 导入' unless an actually registered capability in this snapshot explicitly provides that operation.",
            "3. Control-plane Plugin Registry/Marketplace state is not represented in this Runtime request. If the user asks about plugin installation/creation and no concrete registered Tool/MCP capability proves it, say that the current execution context cannot verify the exact plugin-management operation instead of fabricating one.",
            "4. When a registered/selected Tool or MCP capability can directly observe or perform the user's request, call it. Do not answer with a generic 'I cannot access/operate your computer/platform' disclaimer while an applicable capability is available.",
            "5. Distinguish clearly between VERIFIED CURRENT CAPABILITY, NOT VERIFIED IN CURRENT SNAPSHOT, and POSSIBLE FUTURE EXTENSION.",
            "6. When asked 'can you do it directly?', prefer execution through a real registered capability; if approval is required, invoke it normally and let Runtime request confirmation.",
        ]
    )
    return "\n".join(lines)


def guard_platform_capability_answer(
    *,
    task: str,
    answer: str,
    history: Iterable[Any] = (),
    tools: Iterable[Any] = (),
    mcp_servers: Iterable[Any] = (),
    agents: Iterable[Any] = (),
    selected_tool_names: Iterable[str] = (),
    selected_mcp_tool_names: Iterable[str] = (),
) -> PlatformCapabilityGuardResult:
    """Fail closed on common ungrounded claims about the current platform."""

    if not is_platform_capability_query(task, history):
        return PlatformCapabilityGuardResult(True, "not_applicable", answer)

    text = str(answer or "")
    lowered = text.casefold()
    violations: list[str] = []

    for label, pattern in _FAKE_PLATFORM_PATTERNS:
        if pattern.search(text):
            violations.append(label)

    for phrase in _UNVERIFIED_UI_PHRASES:
        if phrase in lowered:
            violations.append("unverified_ui_or_workflow_claim")
            break

    known_names = _names(tools)
    known_names.update(_names(agents))
    known_names.update(_names(mcp_servers))
    known_names.update(_bounded_name(item).casefold() for item in selected_tool_names if _bounded_name(item))
    known_names.update(_bounded_name(item).casefold() for item in selected_mcp_tool_names if _bounded_name(item))

    for plugin_name in _PLUGIN_YAML.findall(text):
        if plugin_name.casefold() not in known_names:
            violations.append("unverified_plugin_name")
            break

    has_local_execution = any(name.startswith("local.") for name in known_names)
    if has_local_execution and any(phrase in lowered for phrase in _DIRECT_OPERATION_DENIALS):
        violations.append("false_direct_operation_denial")

    if not violations:
        return PlatformCapabilityGuardResult(True, "allow", answer)

    selected = [
        _bounded_name(item)
        for item in [*selected_tool_names, *selected_mcp_tool_names]
        if _bounded_name(item)
    ]
    all_tools = [
        _bounded_name(getattr(tool, "name", ""))
        for tool in tools
        if getattr(tool, "enabled", True) is not False
        and _bounded_name(getattr(tool, "name", ""))
    ]
    local_tools = [item for item in all_tools if item.casefold().startswith("local.")]

    if "工作流" in task or "workflow" in task.casefold():
        subject = (
            "当前 Runtime 能确认的是 Agent / Tool / MCP 的注册与执行能力；"
            "当前能力快照没有提供可验证的独立 Workflow/YAML 导入模块，因此我不能告诉你去一个未确认存在的“工作流导入”页面。"
        )
    elif "插件" in task or "plugin" in task.casefold():
        subject = (
            "当前执行上下文能确认真实注册的 Tool / MCP / Agent；"
            "Plugin Registry/Marketplace 的控制面操作没有作为本轮 Runtime 权威快照提供，所以我不会编造插件安装入口、Schema 或插件名。"
        )
    else:
        subject = "我需要按当前 AgentMesh 实例的真实能力重新回答，而不是根据模型先验猜测产品功能。"

    parts = [subject]
    if selected:
        parts.append("本轮已经选择的真实能力：" + "、".join(selected[:12]) + "。")
    elif local_tools:
        parts.append("当前已注册的本机能力包括：" + "、".join(local_tools[:12]) + "。")
    elif all_tools:
        parts.append("当前已注册的工具包括：" + "、".join(all_tools[:12]) + "。")

    if local_tools:
        parts.append(
            "如果你的目标能由这些已注册工具完成，我应该直接调用它；需要确认的操作会进入审批，而不是笼统地说我无法操作你的电脑。"
        )

    parts.append(
        "对于当前快照没有证明存在的菜单、版本、域名、权限、Workflow YAML 或插件，我会明确说“当前无法从实例能力快照确认”，不会把假设当成已实现功能。"
    )

    return PlatformCapabilityGuardResult(
        False,
        "safe_fallback",
        "\n\n".join(parts),
        tuple(dict.fromkeys(violations)),
    )
