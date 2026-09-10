import { useMemo, useState } from "react";
import {
  createTool,
  deleteTool,
  seedDemoTools,
  seedDesktopTools,
  updateTool,
} from "../../api";
import type { Tool } from "../../types";
import { Icon } from "../../components/common/Icon";

const DESKTOP_TOOL_PREFIX = "local.";

type DesktopCopy = { title: string; description: string };

const DESKTOP_TOOL_COPY: Record<string, DesktopCopy> = {
  "local.fs.list": { title: "浏览本机文件", description: "列出已授权目录中的文件和文件夹。" },
  "local.fs.stat": { title: "查看文件信息", description: "读取已授权文件或文件夹的元数据。" },
  "local.fs.read": { title: "读取本机文件", description: "读取已授权目录中的文本文件内容。" },
  "local.fs.search": { title: "搜索本机文件", description: "按文件名或文本内容搜索已授权目录。" },
  "local.fs.write": { title: "写入本机文件", description: "创建或修改文件；执行前需要确认。" },
  "local.fs.mkdir": { title: "创建本机文件夹", description: "在授权目录中创建文件夹；执行前需要确认。" },
  "local.fs.copy": { title: "复制本机文件", description: "在授权位置之间复制文件或文件夹。" },
  "local.fs.move": { title: "移动或重命名", description: "移动或重命名文件；高风险操作，必须确认。" },
  "local.fs.delete": { title: "删除本机文件", description: "删除文件或文件夹；高风险操作，必须确认。" },

  "local.app.list": { title: "查看本地应用", description: "查看 Desktop Bridge 已识别的本地应用。" },
  "local.app.discover": { title: "扫描本地应用", description: "重新扫描常见 Windows 应用。" },
  "local.app.launch": { title: "启动本地应用", description: "启动已注册应用；执行前需要确认。" },
  "local.app.open": { title: "用应用打开文件", description: "用已注册应用打开授权目录中的文件或文件夹。" },
  "local.app.status": { title: "查看应用状态", description: "查看已注册应用当前是否正在运行。" },
  "local.app.focus": { title: "切换到应用", description: "把指定应用窗口切换到前台。" },
  "local.app.close": { title: "关闭本地应用", description: "关闭应用可能丢失未保存内容，必须确认。" },

  "local.tool.list": { title: "查看命令行工具", description: "查看 Python、Git、Go、Node、FFmpeg 等已注册工具。" },
  "local.tool.discover": { title: "扫描命令行工具", description: "重新扫描 PATH 中的受支持工具。" },
  "local.tool.run": { title: "运行命令行工具", description: "使用 argv 运行已注册工具；属于代码执行，必须确认。" },
  "local.tool.status": { title: "查看工具运行状态", description: "查看进程状态以及受限长度的 stdout / stderr。" },
  "local.tool.cancel": { title: "停止工具任务", description: "停止由 AgentMesh 启动的本机工具进程。" },

  "local.terminal.run": { title: "高级终端", description: "执行任意终端命令；默认关闭，开启后每次仍必须确认。" },
  "local.terminal.status": { title: "查看终端任务", description: "查看高级终端进程状态与受限输出。" },
  "local.terminal.cancel": { title: "停止终端任务", description: "停止高级终端进程；属于高风险操作。" },

  "local.ui.session.start": { title: "开始本机控制", description: "开启有时限的 Computer Use 会话；必须先由你批准。" },
  "local.ui.session.status": { title: "查看本机控制状态", description: "确认当前 Computer Use 会话是否仍有效。" },
  "local.ui.session.stop": { title: "停止本机控制", description: "立即结束当前 Computer Use 会话。" },
  "local.ui.screen.capture": { title: "查看当前屏幕", description: "截取当前桌面供视觉模型理解；截图内容不写入 Trace。" },
  "local.ui.window.list": { title: "查看窗口", description: "列出当前可见的 Windows 窗口。" },
  "local.ui.window.info": { title: "查看窗口信息", description: "读取指定窗口的标题、位置和进程信息。" },
  "local.ui.window.focus": { title: "切换窗口", description: "把指定窗口切换到前台。" },
  "local.ui.window.close": { title: "关闭窗口", description: "关闭窗口可能丢失未保存内容，必须确认。" },
  "local.ui.mouse.move": { title: "移动鼠标", description: "在已批准的本机控制会话中移动鼠标。" },
  "local.ui.mouse.click": { title: "鼠标点击", description: "在已批准的本机控制会话中点击。" },
  "local.ui.mouse.double_click": { title: "鼠标双击", description: "执行左键双击。" },
  "local.ui.mouse.right_click": { title: "鼠标右键", description: "执行右键点击。" },
  "local.ui.mouse.drag": { title: "鼠标拖动", description: "在两个桌面坐标之间拖动。" },
  "local.ui.mouse.scroll": { title: "鼠标滚动", description: "滚动当前窗口或页面。" },
  "local.ui.keyboard.type": { title: "键盘输入", description: "向当前焦点输入文本，不读取或复用系统剪贴板。" },
  "local.ui.keyboard.press": { title: "按下按键", description: "发送单个键盘按键。" },
  "local.ui.keyboard.hotkey": { title: "键盘快捷键", description: "发送受限快捷键；危险系统快捷键由 Bridge 拦截。" },
  "local.ui.wait": { title: "等待界面更新", description: "短暂等待应用完成加载或界面变化。" },
  "local.ui.element.find": { title: "查找界面元素", description: "通过 Windows UI Automation 查找按钮、输入框等元素。" },
  "local.ui.element.click": { title: "点击界面元素", description: "优先通过 UI Automation 点击界面元素。" },
  "local.ui.element.set_text": { title: "填写界面文本", description: "通过 UI Automation 设置输入框文本。" },
  "local.ui.element.invoke": { title: "执行界面操作", description: "调用 Windows UI Automation 元素动作。" },
  "local.ui.element.select": { title: "选择界面选项", description: "通过 UI Automation 选择列表或控件选项。" },
};

const DESKTOP_GROUPS = [
  { prefix: "local.fs.", title: "本机文件", description: "读取、搜索、写入和管理你明确授权的本机目录。" },
  { prefix: "local.app.", title: "本地应用", description: "发现、启动、聚焦和关闭已注册的 Windows 应用。" },
  { prefix: "local.tool.", title: "命令行工具", description: "运行 Python、Git、Go、Node、FFmpeg 等受控 CLI。" },
  { prefix: "local.terminal.", title: "高级终端", description: "可选的任意命令模式；默认关闭并始终按高风险审批。" },
  { prefix: "local.ui.", title: "桌面控制", description: "屏幕、窗口、鼠标、键盘与 Windows UI Automation。" },
] as const;

function isDesktopTool(tool: Tool) {
  return tool.name.startsWith(DESKTOP_TOOL_PREFIX);
}

function desktopToolTitle(tool: Tool) {
  return DESKTOP_TOOL_COPY[tool.name]?.title ?? tool.name;
}

function desktopToolDescription(tool: Tool) {
  return DESKTOP_TOOL_COPY[tool.name]?.description ?? tool.description ?? "暂无描述";
}

function riskCopy(tool: Tool) {
  return tool.riskLevel === "high" ? "高风险" : tool.riskLevel === "medium" ? "中风险" : "低风险";
}

// P4 validation contract: 添加 HTTP Tool / app.tools.http_demo_server
export function ToolsPanel({ tools, reload }: { tools: Tool[]; reload: () => Promise<void> }) {
  const [name, setName] = useState("local_http_echo");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:9584/tool/echo");
  const [riskLevel, setRiskLevel] = useState<"low" | "medium" | "high">("low");
  const [requiresConfirmation, setRequiresConfirmation] = useState(false);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [desktopBusy, setDesktopBusy] = useState(false);
  const [toolBusyId, setToolBusyId] = useState<number | null>(null);

  const desktopTools = useMemo(() => tools.filter(isDesktopTool), [tools]);
  const ordinaryTools = useMemo(() => tools.filter((tool) => !isDesktopTool(tool)), [tools]);
  const desktopInstalled = desktopTools.length > 0;
  const desktopExpectedCount = Object.keys(DESKTOP_TOOL_COPY).length;
  const desktopComplete = desktopTools.length === desktopExpectedCount;
  const desktopEnabledCount = desktopTools.filter((tool) => tool.enabled).length;

  const syncDesktopTools = async () => {
    try {
      setError("");
      setDesktopBusy(true);
      await seedDesktopTools();
      await reload();
    } catch {
      setError("本机能力接入失败，请确认 Control Plane 正常运行后重试。");
    } finally {
      setDesktopBusy(false);
    }
  };

  const toggleDesktopTool = async (tool: Tool) => {
    try {
      setError("");
      setToolBusyId(tool.id);
      await updateTool(tool.id, { enabled: !tool.enabled });
      await reload();
    } catch {
      setError(`${desktopToolTitle(tool)}状态更新失败，请稍后重试。`);
    } finally {
      setToolBusyId(null);
    }
  };

  return (
    <div className="extension-product-panel">
      <div className="subpage-head calm-subpage-head">
        <div>
          <h2>工具</h2>
          <p>让智能体执行确定性动作，也可以通过 Desktop Agent 在你的明确授权下操作本机。</p>
        </div>
        <div className="calm-head-actions">
          <button
            className="calm-button ghost"
            onClick={async () => {
              try {
                setError("");
                await seedDemoTools();
                await reload();
              } catch {
                setError("演示工具添加失败，请稍后重试。");
              }
            }}
          >
            添加演示工具
          </button>
          <button className="calm-button primary" type="button" onClick={() => setShowAdd((value) => !value)}>
            <Icon name="plus" size={14} />
            添加工具
          </button>
        </div>
      </div>

      <article className="desktop-agent-summary">
        <span className="desktop-agent-summary-icon"><Icon name="tool" size={18} /></span>
        <div className="desktop-agent-summary-copy">
          <strong>Desktop Agent · 本机能力</strong>
          <small>
            文件、本地应用、CLI 与桌面操作均通过 loopback-only Desktop Bridge 执行。浏览器不会获得 Bridge Token。
          </small>
        </div>
        <span className={`calm-status ${desktopInstalled ? "ok" : "idle"}`}>
          <i />
          {desktopInstalled ? `已内置 · ${desktopEnabledCount}/${desktopTools.length} 项启用` : "初始化异常"}
        </span>
        <button className="calm-button subtle" type="button" disabled={desktopBusy} onClick={syncDesktopTools}>
          {desktopBusy ? "正在同步…" : desktopInstalled ? "重新同步" : "重试初始化"}
        </button>
      </article>

      <div className="desktop-agent-security-note">
        <Icon name="shield" size={15} />
        <div>
          <strong>内置能力 · 按动作授权</strong>
          <span>
            官方本机能力会随登录自动初始化，无需手动“接入”；文件只访问授权目录，CLI 代码执行必须审批，高级终端默认关闭，桌面控制仍需批准有时限的 Computer Use 会话。
          </span>
        </div>
      </div>

      {desktopInstalled && (
        <div className="desktop-capability-groups">
          {DESKTOP_GROUPS.map((group) => {
            const groupTools = desktopTools.filter((tool) => tool.name.startsWith(group.prefix));
            const enabled = groupTools.filter((tool) => tool.enabled).length;
            return (
              <details className="desktop-capability-group" key={group.prefix}>
                <summary>
                  <span>
                    <strong>{group.title}</strong>
                    <small>{group.description}</small>
                  </span>
                  <em>{enabled}/{groupTools.length} 项启用</em>
                </summary>
                <div className="desktop-capability-tool-list">
                  {groupTools.map((tool) => (
                    <div className="desktop-capability-tool" key={tool.id}>
                      <div>
                        <strong>{desktopToolTitle(tool)}</strong>
                        <small>{desktopToolDescription(tool)}</small>
                      </div>
                      <span className={`tool-risk-chip risk-${tool.riskLevel}`}>{riskCopy(tool)}</span>
                      <button
                        className="calm-icon-button"
                        type="button"
                        disabled={toolBusyId === tool.id}
                        onClick={() => toggleDesktopTool(tool)}
                      >
                        {toolBusyId === tool.id ? "处理中" : tool.enabled ? "停用" : "启用"}
                      </button>
                    </div>
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      )}

      {!desktopComplete && desktopInstalled && (
        <div className="calm-feedback warning">
          当前仅初始化了 {desktopTools.length}/{desktopExpectedCount} 项官方本机能力，请点击“重新同步”修复。
        </div>
      )}

      {showAdd && (
        <div className="extension-add-card tool-add-card">
          <label>
            <span>工具名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="wide">
            <span>服务地址</span>
            <input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} />
          </label>
          <label>
            <span>风险等级</span>
            <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value as "low" | "medium" | "high")}>
              <option value="low">低风险 · 可自动执行</option>
              <option value="medium">中风险 · 建议确认</option>
              <option value="high">高风险 · 必须确认</option>
            </select>
          </label>
          <label className="tool-confirm-calm">
            <span>执行前确认</span>
            <input
              type="checkbox"
              checked={requiresConfirmation}
              onChange={(event) => setRequiresConfirmation(event.target.checked)}
            />
          </label>
          <div className="extension-add-actions">
            <button className="calm-button subtle" type="button" onClick={() => setShowAdd(false)}>取消</button>
            <button
              className="calm-button primary"
              type="button"
              onClick={async () => {
                try {
                  setError("");
                  await createTool({
                    name,
                    description: "Local HTTP JSON POST tool",
                    protocol: "http",
                    endpoint,
                    inputSchema: {
                      type: "object",
                      properties: { text: { type: "string" } },
                      additionalProperties: true,
                    },
                    riskLevel,
                    requiresConfirmation: requiresConfirmation || riskLevel === "high",
                    enabled: true,
                  });
                  setShowAdd(false);
                  await reload();
                } catch {
                  setError("工具保存失败，请检查服务地址或稍后重试。");
                }
              }}
            >
              保存工具
            </button>
          </div>
          <details className="developer-note">
            <summary>开发者接入说明</summary>
            <p>本地演示服务：<code>python -m app.tools.http_demo_server</code></p>
          </details>
        </div>
      )}

      {error && <div className="calm-feedback error">{error}</div>}

      <div className="tool-calm-list">
        {ordinaryTools.length === 0 && !desktopInstalled && (
          <div className="calm-empty-card">
            <Icon name="tool" size={20} />
            <strong>还没有可用工具</strong>
            <span>添加工具或同步本机能力后，智能体可以在需要时自动调用。</span>
          </div>
        )}

        {ordinaryTools.map((tool) => (
          <article className="tool-calm-row" key={tool.id}>
            <span className="extension-calm-icon"><Icon name="tool" size={16} /></span>
            <div className="tool-calm-copy">
              <strong>{tool.name}</strong>
              <small>{tool.description || "暂无描述"}</small>
            </div>
            <span className={`tool-risk-chip risk-${tool.riskLevel}`}>{riskCopy(tool)}</span>
            <span className={`calm-status ${tool.enabled ? "ok" : "idle"}`}><i />{tool.enabled ? "可用" : "停用"}</span>
            <details className="connection-technical-detail compact">
              <summary>详情</summary>
              <span>{tool.protocol}</span>
            </details>
            <button
              className="calm-icon-button danger"
              type="button"
              onClick={async () => {
                try {
                  setError("");
                  await deleteTool(tool.id);
                  await reload();
                } catch {
                  setError("工具删除失败，请稍后重试。");
                }
              }}
            >
              删除
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
