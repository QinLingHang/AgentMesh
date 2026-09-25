from __future__ import annotations

from app.capabilities import (
    contextualize_discovery_task,
    discover_capabilities,
    discover_mcp_tools,
    discovery_context,
)
from app.mcp.contracts import MCPServerDefinition
from app.schemas import AgentProfile
from app.tools.contracts import ToolDefinition
from app.tools.desktop import desktop_tool_definitions


def _desktop_tools():
    return desktop_tool_definitions()


def test_desktop_files_are_discovered_from_natural_language_without_tool_name():
    result = discover_capabilities(
        "桌面有什么文件？",
        tools=_desktop_tools(),
    )

    assert "local.fs.list" in result.selected_tool_names
    assert "local.fs.delete" not in result.selected_tool_names
    assert result.has_action_capability is True

    context = discovery_context(result)
    assert "local.fs.list" in context
    assert "Do not claim" in context


def test_read_only_explicit_local_file_uses_filesystem_tools_not_code_execution():
    result = discover_capabilities(
        r"帮我找到 E:\AIProject\AgentMesh_v1.0.0-rc.2_SOURCE 目录里的 README.md，读取它并告诉我前面主要讲了什么。",
        tools=_desktop_tools(),
    )

    assert "local.fs.read" in result.selected_tool_names
    assert "local.tool.run" not in result.selected_tool_names
    assert "local.terminal.run" not in result.selected_tool_names


def test_desktop_application_and_cli_are_discovered_autonomously():
    app_result = discover_capabilities(
        "帮我打开 VS Code",
        tools=_desktop_tools(),
    )
    assert "local.app.launch" in app_result.selected_tool_names
    assert "local.app.list" in app_result.selected_tool_names

    cli_result = discover_capabilities(
        "在本机运行 go test ./...",
        tools=_desktop_tools(),
    )
    assert "local.tool.run" in cli_result.selected_tool_names
    assert "local.tool.status" in cli_result.selected_tool_names
    assert "local.tool.cancel" in cli_result.selected_tool_names


def test_computer_use_selection_expands_session_dependencies():
    result = discover_capabilities(
        "帮我截图看看当前屏幕",
        tools=_desktop_tools(),
    )

    assert "local.ui.screen.capture" in result.selected_tool_names
    assert "local.ui.session.start" in result.selected_tool_names
    assert "local.ui.session.status" in result.selected_tool_names
    assert "local.ui.session.stop" in result.selected_tool_names


def test_project_knowledge_is_discovered_without_explicit_knowledge_base_phrase():
    project = discover_capabilities(
        "AgentMesh Project BYOK 是怎么设计和实现的？",
    )
    assert project.use_project_knowledge is True

    general = discover_capabilities(
        "Python 和 Java 有什么区别？",
    )
    assert general.use_project_knowledge is False




def test_explicit_no_mcp_constraint_blocks_mcp_discovery_even_when_server_matches():
    github = MCPServerDefinition(
        id=77,
        name="GitHub",
        endpoint="https://mcp.example/github",
        enabled=True,
    )

    result = discover_capabilities(
        "请分析这个 GitHub PR，但不需要 MCP，只做文字分析。",
        mcp_servers=[github],
    )

    assert result.selected_mcp_server_ids == []
    assert "prohibition" in result.reason

def test_mcp_server_and_tool_discovery_use_task_semantics():
    github = MCPServerDefinition(
        id=7,
        name="GitHub",
        endpoint="https://mcp.example/github",
        enabled=True,
    )
    jira = MCPServerDefinition(
        id=8,
        name="Jira",
        endpoint="https://mcp.example/jira",
        enabled=True,
    )

    servers = discover_capabilities(
        "帮我看看 GitHub 上这个 PR",
        mcp_servers=[github, jira],
    )
    assert servers.selected_mcp_server_ids == [7]

    weather_server = MCPServerDefinition(
        id=9,
        name="Weather Service",
        endpoint="https://mcp.example/weather",
        enabled=True,
    )
    weather = discover_capabilities(
        "沈阳现在天气怎么样？",
        mcp_servers=[weather_server, jira],
    )
    assert weather.selected_mcp_server_ids == [9]

    tools = [
        ToolDefinition(
            name="mcp.github.pull_request.get",
            description="Get details for a GitHub pull request",
            protocol="mcp",
        ),
        ToolDefinition(
            name="mcp.github.issue.create",
            description="Create a GitHub issue",
            protocol="mcp",
        ),
        ToolDefinition(
            name="mcp.github.repo.list",
            description="List GitHub repositories",
            protocol="mcp",
        ),
    ]
    selected = discover_mcp_tools(
        "查看这个 pull request 的详情",
        tools,
    )
    assert "mcp.github.pull_request.get" in selected.selected_mcp_tool_names


def test_agent_and_a2a_capabilities_are_treated_as_skills():
    agents = [
        AgentProfile(
            id=1,
            name="Code Reviewer",
            description="Reviews source code and identifies defects.",
            endpoint="internal://review",
            protocol="internal",
            capabilities=["general", "code_review"],
        ),
        AgentProfile(
            id=2,
            name="Writer",
            description="Writes marketing content.",
            endpoint="internal://writer",
            protocol="internal",
            capabilities=["general", "copywriting"],
        ),
    ]

    result = discover_capabilities(
        "帮我做一次代码审查，找出代码中的问题",
        agents=agents,
    )
    assert "code_review" in result.selected_skill_names
    assert "copywriting" not in result.selected_skill_names


def test_only_relevant_custom_tool_schemas_are_selected():
    tools = [
        ToolDefinition(
            name="orders.lookup",
            description="Query order shipping status by order id",
            protocol="http",
            endpoint="https://example.invalid/order",
        ),
        ToolDefinition(
            name="weather.current",
            description="Query current weather for a city",
            protocol="http",
            endpoint="https://example.invalid/weather",
        ),
        ToolDefinition(
            name="crm.delete",
            description="Delete a CRM record",
            protocol="http",
            endpoint="https://example.invalid/crm",
            riskLevel="high",
            requiresConfirmation=True,
        ),
    ]

    result = discover_capabilities(
        "帮我查一下订单物流状态",
        tools=tools,
    )

    assert "orders.lookup" in result.selected_tool_names
    assert "weather.current" not in result.selected_tool_names
    assert "crm.delete" not in result.selected_tool_names


def test_trace_detail_contains_metadata_not_tool_payloads():
    result = discover_capabilities(
        "桌面有什么文件",
        tools=_desktop_tools(),
    )
    detail = result.trace_detail()

    assert detail["selectedTools"]
    assert isinstance(detail["candidates"], list)
    assert all("arguments" not in item for item in detail["candidates"])
    assert all("result" not in item for item in detail["candidates"])


def test_cross_language_custom_capabilities_are_discovered_without_user_naming_tools():
    tools = [
        ToolDefinition(
            name="weather.current",
            description="Query current weather for a city",
            protocol="http",
            endpoint="https://example.invalid/weather",
        ),
        ToolDefinition(
            name="calculator.evaluate",
            description="Evaluate a mathematical expression",
            protocol="http",
            endpoint="https://example.invalid/calculator",
        ),
        ToolDefinition(
            name="email.send",
            description="Send an email message to a recipient",
            protocol="http",
            endpoint="https://example.invalid/email",
        ),
    ]

    weather = discover_capabilities("今天天气怎么样？", tools=tools)
    assert weather.selected_tool_names == ["weather.current"]

    calculator = discover_capabilities("帮我计算 382*927", tools=tools)
    assert calculator.selected_tool_names == ["calculator.evaluate"]

    email = discover_capabilities("发一封邮件给他", tools=tools)
    assert email.selected_tool_names == ["email.send"]


def test_explanatory_questions_do_not_trigger_related_action_tools():
    tools = [
        ToolDefinition(
            name="weather.current",
            description="Query current weather for a city",
            protocol="http",
            endpoint="https://example.invalid/weather",
        ),
        ToolDefinition(
            name="github.pr.get",
            description="Get GitHub pull request details",
            protocol="http",
            endpoint="https://example.invalid/github",
        ),
    ]

    assert discover_capabilities(
        "解释一下天气系统原理",
        tools=tools,
    ).selected_tool_names == []

    assert discover_capabilities(
        "GitHub 是什么？",
        tools=tools,
    ).selected_tool_names == []

    github_server = MCPServerDefinition(
        id=11,
        name="GitHub Connector",
        endpoint="https://mcp.example/github",
        enabled=True,
    )
    assert discover_capabilities(
        "GitHub 是什么？",
        mcp_servers=[github_server],
    ).selected_mcp_server_ids == []



def test_continuation_turn_reuses_recent_history_for_capability_discovery():
    from app.capabilities import contextualize_discovery_task, continuation_subject_task
    from app.schemas import InteractiveMessage

    query, used_history, turns = contextualize_discovery_task(
        "可以",
        [
            InteractiveMessage(role="user", content="帮我看看 GitHub 上这个 PR"),
            InteractiveMessage(role="assistant", content="这个操作可能需要访问 GitHub，是否继续？"),
        ],
    )

    assert used_history is True
    assert turns == 2
    assert "GitHub" in query

    github = MCPServerDefinition(
        id=7,
        name="GitHub",
        endpoint="https://mcp.example/github",
        enabled=True,
    )
    jira = MCPServerDefinition(
        id=8,
        name="Jira",
        endpoint="https://mcp.example/jira",
        enabled=True,
    )
    result = discover_capabilities(query, mcp_servers=[github, jira])
    assert result.selected_mcp_server_ids == [7]


def test_continuation_can_resume_desktop_or_project_knowledge_without_tool_name():
    from app.capabilities import contextualize_discovery_task, continuation_subject_task
    from app.schemas import InteractiveMessage

    desktop_query, used_history, _ = contextualize_discovery_task(
        "继续吧。",
        [
            InteractiveMessage(role="user", content="帮我列一下桌面上有哪些文件"),
            InteractiveMessage(role="assistant", content="需要读取桌面目录，确认后我可以继续。"),
        ],
    )
    assert used_history is True
    desktop = discover_capabilities(desktop_query, tools=_desktop_tools())
    assert "local.fs.list" in desktop.selected_tool_names

    knowledge_query, used_history, _ = contextualize_discovery_task(
        "展开讲讲",
        [
            InteractiveMessage(role="user", content="AgentMesh Project BYOK 是怎么设计的？"),
            InteractiveMessage(role="assistant", content="我可以继续从项目实现角度展开。"),
        ],
    )
    assert used_history is True
    knowledge = discover_capabilities(knowledge_query)
    assert knowledge.use_project_knowledge is True
    assert continuation_subject_task(
        "展开讲讲",
        [
            InteractiveMessage(role="user", content="AgentMesh Project BYOK 是怎么设计的？"),
            InteractiveMessage(role="assistant", content="我可以继续从项目实现角度展开。"),
        ],
    ) == "AgentMesh Project BYOK 是怎么设计的？"


def test_general_conversation_continuation_preserves_topic_without_inventing_capabilities():
    from app.capabilities import contextualize_discovery_task, is_continuation_turn
    from app.schemas import InteractiveMessage

    assert is_continuation_turn("可以。") is True
    assert is_continuation_turn("好的，继续") is True
    assert is_continuation_turn("可以介绍一下 Java 吗") is False

    query, used_history, _ = contextualize_discovery_task(
        "可以",
        [
            InteractiveMessage(role="user", content="最大子数组和没思路，这种题应该怎么才能有思路？"),
            InteractiveMessage(role="assistant", content="先从暴力枚举开始，再观察重复计算。"),
        ],
    )
    assert used_history is True
    result = discover_capabilities(query, tools=_desktop_tools())
    assert result.selected_tool_names == []
    assert result.selected_mcp_server_ids == []
    assert result.use_project_knowledge is False

def test_generic_filesystem_inspection_never_falls_through_to_mutating_tool():
    result = discover_capabilities(
        r"看看 E:\AIProject",
        tools=_desktop_tools(),
    )

    assert "local.fs.list" in result.selected_tool_names
    assert "local.fs.copy" not in result.selected_tool_names
    assert "local.fs.move" not in result.selected_tool_names
    assert "local.fs.delete" not in result.selected_tool_names
    assert "local.fs.write" not in result.selected_tool_names


def test_personal_resume_question_autonomously_selects_scoped_knowledge():
    result = discover_capabilities(
        "秦令杭的简历怎么样？",
    )

    assert result.use_project_knowledge is True
    knowledge = [item for item in result.candidates if item.kind.value == "knowledge"]
    assert knowledge
    assert knowledge[0].selected is True
    assert knowledge[0].identifier == "scoped_knowledge"

    generic = discover_capabilities("简历应该怎么写更规范？")
    assert generic.use_project_knowledge is False



def test_read_only_path_tokens_do_not_fake_cli_intent():
    samples = [
        r"read E:\work\runtime-python\README.md",
        r"读取 E:\work\tests\README.md 并告诉我内容",
        r"查看 E:\work\build\README.md 前面讲了什么",
    ]

    for task in samples:
        result = discover_capabilities(task, tools=_desktop_tools())
        assert "local.fs.read" in result.selected_tool_names, task
        assert "local.tool.run" not in result.selected_tool_names, task
        assert "local.terminal.run" not in result.selected_tool_names, task


def test_explicit_cli_with_runtime_named_workdir_still_selects_tool_run():
    result = discover_capabilities(
        r"在 E:\work\runtime-python 目录运行 go test ./...",
        tools=_desktop_tools(),
    )

    assert "local.tool.run" in result.selected_tool_names

def test_test_marker_language_does_not_fake_cli_execution_intent():
    samples = [
        "记住这个测试标记：CONVERSATION-RELIABILITY-A-001",
        "这个测试标记叫 Conversation Reliability-CONV-A-001",
        "Remember this test marker: Conversation Reliability-CONV-A-001",
    ]

    for task in samples:
        result = discover_capabilities(task, tools=_desktop_tools())
        assert "local.tool.run" not in result.selected_tool_names, task
        assert "local.terminal.run" not in result.selected_tool_names, task


def test_explicit_test_execution_still_selects_cli_tool_run():
    samples = [
        "在本机运行测试",
        "执行 go test ./...",
        "run tests with pytest",
    ]

    for task in samples:
        result = discover_capabilities(task, tools=_desktop_tools())
        assert "local.tool.run" in result.selected_tool_names, task

def test_new_marker_turn_does_not_inherit_prior_read_execution_intent():
    marker = "记住这个测试标记：CONVERSATION-RELIABILITY-A-001"
    history = [
        {
            "role": "user",
            "content": (
                r"帮我读取 E:\AIProject\AgentMesh_v1.0.0-rc.2_SOURCE\README.md，"
                "并告诉我开头主要讲什么。"
            ),
        },
        {"role": "assistant", "content": "README 已读取。"},
    ]

    discovery_task, used_history, history_turns = contextualize_discovery_task(
        marker,
        history,
    )

    assert discovery_task == marker
    assert used_history is False
    assert history_turns == 0

    result = discover_capabilities(discovery_task, tools=_desktop_tools())
    assert "local.tool.run" not in result.selected_tool_names
    assert "local.terminal.run" not in result.selected_tool_names

