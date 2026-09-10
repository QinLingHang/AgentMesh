from types import SimpleNamespace

from app.services.platform_capability_grounding import (
    build_platform_capability_context,
    guard_platform_capability_answer,
    is_platform_capability_query,
)


def _tools():
    return [
        SimpleNamespace(
            name="local.fs.read",
            description="Read a local text file",
            protocol="internal",
            risk_level="low",
            enabled=True,
        ),
        SimpleNamespace(
            name="orders.lookup",
            description="Query an order",
            protocol="http",
            risk_level="low",
            enabled=True,
        ),
    ]


def test_platform_questions_are_classified_without_relying_on_agentmesh_name():
    assert is_platform_capability_query("我怎么在你这个系统上进行插件化") is True
    assert is_platform_capability_query("当前界面有工作流吗") is True
    assert is_platform_capability_query("Python 的插件机制是什么") is False
    assert is_platform_capability_query("解释 Transformer 注意力机制") is False


def test_platform_context_lists_real_snapshot_and_forbids_invented_workflow_ui():
    context = build_platform_capability_context(
        task="你这个系统插件化怎么做？",
        tools=_tools(),
        agents=[SimpleNamespace(name="GeneralAgent", capabilities=["general"])],
        mcp_servers=[SimpleNamespace(name="GitHub MCP", enabled=True)],
        selected_tool_names=["local.fs.read"],
    )

    assert "local.fs.read" in context
    assert "GitHub MCP" in context
    assert "GeneralAgent" in context
    assert "Workflow/YAML-import UI is NOT verified" in context
    assert "Never invent AgentMesh menus/pages" in context
    assert "call it" in context


def test_platform_guard_replaces_fake_workflow_yaml_and_unknown_plugins():
    fake = """
AgentMesh v2.3+ 原生支持工作流。请打开 https://your-org.agentmesh.ai/workflows，
进入工作流管理页，选择从 YAML 导入，并确保拥有 workflow:write 权限。
```yaml
steps:
  - plugin: xlsx-parser
  - plugin: email-sender
```
"""
    result = guard_platform_capability_answer(
        task="可是在当前界面并没有工作流啊",
        answer=fake,
        tools=_tools(),
        selected_tool_names=["local.fs.read"],
    )

    assert result.passed is False
    assert result.action == "safe_fallback"
    assert "xlsx-parser" not in result.answer
    assert "email-sender" not in result.answer
    assert "workflow:write" not in result.answer
    assert "your-org.agentmesh.ai" not in result.answer
    assert "没有提供可验证的独立 Workflow/YAML 导入模块" in result.answer


def test_platform_guard_blocks_false_cannot_operate_disclaimer_when_local_tool_exists():
    result = guard_platform_capability_answer(
        task="你能直接给我操作吗",
        answer="我无法直接操作您的电脑，所有操作必须由您本人在浏览器中完成。",
        tools=_tools(),
        selected_tool_names=["local.fs.read"],
    )

    assert result.passed is False
    assert "false_direct_operation_denial" in result.violations
    assert "local.fs.read" in result.answer
    assert "应该直接调用" in result.answer


def test_platform_guard_allows_honest_snapshot_grounded_answer():
    answer = (
        "当前可确认的本机读取能力是 local.fs.read。"
        "当前 Runtime 快照没有提供可验证的独立 Workflow/YAML 导入模块，"
        "所以我不会给你编一个导入入口。"
    )
    result = guard_platform_capability_answer(
        task="当前界面工作流怎么用？",
        answer=answer,
        tools=_tools(),
        selected_tool_names=["local.fs.read"],
    )

    assert result.passed is True
    assert result.action == "allow"
    assert result.answer == answer
