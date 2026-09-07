import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getProjectRuntimeConfig,
  updateProjectRuntimeConfig,
} from "../../api";
import type {
  Agent,
  MCPServer,
  ProjectRuntimeConfig,
  Tool,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";

export type ProjectRuntimeSummary = {
  agentMode: string;
  agentCount: number;
  toolMode: string;
  toolCount: number;
  mcpMode: string;
  mcpCount: number;
  policyMode: string;
  scheduler: string;
  planner: string;
  executionMode: string;
};

function defaultConfig(
  projectId: number,
): ProjectRuntimeConfig {
  return {
    projectId,

    agentMode: "all",
    agentIds: [],

    toolMode: "all",
    toolIds: [],

    mcpMode: "all",
    mcpServerIds: [],

    policy: {
      mode: "inherit",
      scheduler: "adaptive",
      planner: "multi_objective",
      executionMode: "auto",
      synthesisMode: "auto",
      constraints: {
        maxLatencyMs: 8000,
        maxCost: 0.15,
        minQuality: 0.8,
      },
    },

    createdAt: "",
    updatedAt: "",
  };
}

function toggleID(
  current: number[],
  id: number,
) {
  return current.includes(id)
    ? current.filter(
        (value) =>
          value !== id,
      )
    : [
        ...current,
        id,
      ];
}

export function ProjectRuntimePanel({
  projectId,
  agents,
  tools,
  mcpServers,
  onSummaryChange,
}: {
  projectId: number;
  agents: Agent[];
  tools: Tool[];
  mcpServers: MCPServer[];
  onSummaryChange?: (
    summary: ProjectRuntimeSummary,
  ) => void;
}) {
  const [config, setConfig] =
    useState<ProjectRuntimeConfig>(
      defaultConfig(
        projectId,
      ),
    );

  const [loading, setLoading] =
    useState(true);

  const [saving, setSaving] =
    useState(false);

  const [feedback, setFeedback] =
    useState<{
      type: "success" | "error";
      message: string;
    } | null>(null);

  useEffect(
    () => {
      let canceled = false;

      setLoading(true);
      setFeedback(null);

      getProjectRuntimeConfig(
        projectId,
      )
        .then(
          (value) => {
            if (!canceled) {
              setConfig(value);
            }
          },
        )
        .catch(
          (error) => {
            if (!canceled) {
              setFeedback({
                type: "error",
                message:
                  error instanceof Error
                    ? error.message
                    : "加载项目 Runtime 配置失败。",
              });
            }
          },
        )
        .finally(
          () => {
            if (!canceled) {
              setLoading(false);
            }
          },
        );

      return () => {
        canceled = true;
      };
    },
    [projectId],
  );

  const summary =
    useMemo<ProjectRuntimeSummary>(
      () => ({
        agentMode:
          config.agentMode,
        agentCount:
          config.agentMode ===
          "all"
            ? agents.length
            : config.agentIds.filter(
                (id) =>
                  agents.some(
                    (agent) =>
                      agent.id === id,
                  ),
              ).length,
        toolMode:
          config.toolMode,
        toolCount:
          config.toolMode ===
          "all"
            ? tools.filter(
                (tool) =>
                  tool.enabled,
              ).length
            : config.toolIds.filter(
                (id) =>
                  tools.some(
                    (tool) =>
                      tool.id === id &&
                      tool.enabled,
                  ),
              ).length,
        mcpMode:
          config.mcpMode,
        mcpCount:
          config.mcpMode ===
          "all"
            ? mcpServers.filter(
                (server) =>
                  server.enabled,
              ).length
            : config.mcpServerIds.filter(
                (id) =>
                  mcpServers.some(
                    (server) =>
                      server.id === id &&
                      server.enabled,
                  ),
              ).length,
        policyMode:
          config.policy.mode,
        scheduler:
          config.policy.scheduler,
        planner:
          config.policy.planner,
        executionMode:
          config.policy.executionMode,
      }),
      [
        agents,
        config,
        mcpServers,
        tools,
      ],
    );

  useEffect(
    () => {
      onSummaryChange?.(
        summary,
      );
    },
    [
      onSummaryChange,
      summary,
    ],
  );

  const save = async () => {
    if (
      config.agentMode ===
        "selected" &&
      config.agentIds.length ===
        0
    ) {
      setFeedback({
        type: "error",
        message:
          "Agent 使用“仅已选择”模式时，至少选择一个 Agent。",
      });
      return;
    }

    try {
      setSaving(true);
      setFeedback(null);

      const updated =
        await updateProjectRuntimeConfig(
          projectId,
          config,
        );

      setConfig(updated);

      setFeedback({
        type: "success",
        message:
          "项目 Runtime 配置已保存。后续项目会话会由 Go Control Plane 强制执行这些资源边界。",
      });
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : "保存失败，请稍后重试。",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <section
        id={`project-runtime-${projectId}`}
        className="project-runtime-panel"
      >
        <div className="project-runtime-loading">
          正在加载项目 Runtime 配置...
        </div>
      </section>
    );
  }

  return (
    <section
      id={`project-runtime-${projectId}`}
      className="project-runtime-panel"
    >
      <header className="project-runtime-head">
        <div>
          <div className="eyebrow">
            PROJECT RUNTIME CONTEXT
          </div>

          <h2>
            项目 Runtime
          </h2>

          <p>
            在这里决定当前 Project 真正允许 Runtime 使用哪些 Agent、Tool、MCP，以及是否锁定项目级调度策略。
          </p>
        </div>

        <button
          type="button"
          className="primary-button"
          disabled={saving}
          onClick={() =>
            void save()
          }
        >
          {saving
            ? "保存中..."
            : "保存配置"}
        </button>
      </header>

      {feedback && (
        <div
          className={`project-runtime-feedback ${feedback.type}`}
          role={
            feedback.type ===
            "error"
              ? "alert"
              : "status"
          }
        >
          <span>
            {feedback.message}
          </span>

          <button
            type="button"
            onClick={() =>
              setFeedback(null)
            }
          >
            <Icon
              name="close"
              size={13}
            />
          </button>
        </div>
      )}

      <div className="project-runtime-resource-grid">
        <ResourceSection
          title="智能体"
          description="项目会话只会把这里允许的智能体发送给运行服务。"
          mode={config.agentMode}
          onModeChange={(mode) =>
            setConfig(
              (current) => ({
                ...current,
                agentMode: mode,
              }),
            )
          }
          allLabel={`${agents.length} 个账户级 Agent`}
        >
          {agents.map(
            (agent) => (
              <BindingItem
                key={agent.id}
                checked={
                  config.agentIds.includes(
                    agent.id,
                  )
                }
                disabled={
                  config.agentMode !==
                  "selected"
                }
                title={agent.name}
                meta={`${agent.protocol} · ${agent.capabilities.join(", ") || "no capability"}`}
                onChange={() =>
                  setConfig(
                    (current) => ({
                      ...current,
                      agentIds:
                        toggleID(
                          current.agentIds,
                          agent.id,
                        ),
                    }),
                  )
                }
              />
            ),
          )}
        </ResourceSection>

        <ResourceSection
          title="工具"
          description="只会下发当前账户中 enabled 的 Tool；Selected 模式进一步收窄。"
          mode={config.toolMode}
          onModeChange={(mode) =>
            setConfig(
              (current) => ({
                ...current,
                toolMode: mode,
              }),
            )
          }
          allLabel={`${tools.filter((tool) => tool.enabled).length} 个 enabled Tool`}
        >
          {tools.map(
            (tool) => (
              <BindingItem
                key={tool.id}
                checked={
                  config.toolIds.includes(
                    tool.id,
                  )
                }
                disabled={
                  config.toolMode !==
                    "selected" ||
                  !tool.enabled
                }
                title={tool.name}
                meta={`${tool.protocol} · ${tool.riskLevel} risk${tool.enabled ? "" : " · disabled"}`}
                onChange={() =>
                  setConfig(
                    (current) => ({
                      ...current,
                      toolIds:
                        toggleID(
                          current.toolIds,
                          tool.id,
                        ),
                    }),
                  )
                }
              />
            ),
          )}
        </ResourceSection>

        <ResourceSection
          title="外部服务"
          description="项目只能访问绑定范围内且当前已启用的外部服务。"
          mode={config.mcpMode}
          onModeChange={(mode) =>
            setConfig(
              (current) => ({
                ...current,
                mcpMode: mode,
              }),
            )
          }
          allLabel={`${mcpServers.filter((server) => server.enabled).length} 个 enabled MCP`}
        >
          {mcpServers.map(
            (server) => (
              <BindingItem
                key={server.id}
                checked={
                  config.mcpServerIds.includes(
                    server.id,
                  )
                }
                disabled={
                  config.mcpMode !==
                    "selected" ||
                  !server.enabled
                }
                title={server.name}
                meta={`${server.transport}${server.enabled ? "" : " · disabled"}`}
                onChange={() =>
                  setConfig(
                    (current) => ({
                      ...current,
                      mcpServerIds:
                        toggleID(
                          current.mcpServerIds,
                          server.id,
                        ),
                    }),
                  )
                }
              />
            ),
          )}
        </ResourceSection>
      </div>

      <div className="project-runtime-policy-block">
        <div className="project-runtime-policy-title">
          <div>
            <h3>
              Runtime Policy
            </h3>

            <p>
              inherit：继续使用会话右下角的运行设置；project：由 Go 强制覆盖为项目策略。
            </p>
          </div>

          <div className="project-runtime-mode-switch">
            <button
              type="button"
              className={
                config.policy.mode ===
                "inherit"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      mode: "inherit",
                    },
                  }),
                )
              }
            >
              跟随会话
            </button>

            <button
              type="button"
              className={
                config.policy.mode ===
                "project"
                  ? "active"
                  : ""
              }
              onClick={() =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      mode: "project",
                    },
                  }),
                )
              }
            >
              项目锁定
            </button>
          </div>
        </div>

        <div
          className={`project-runtime-policy-fields ${
            config.policy.mode ===
            "inherit"
              ? "disabled"
              : ""
          }`}
        >
          <label>
            <span>
              Scheduler
            </span>

            <select
              value={
                config.policy.scheduler
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      scheduler:
                        event.target.value as ProjectRuntimeConfig["policy"]["scheduler"],
                    },
                  }),
                )
              }
            >
              <option value="adaptive">
                adaptive
              </option>
              <option value="greedy">
                greedy
              </option>
              <option value="capability">
                capability
              </option>
              <option value="fixed">
                fixed
              </option>
            </select>
          </label>

          <label>
            <span>
              Planner
            </span>

            <select
              value={
                config.policy.planner
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      planner:
                        event.target.value as ProjectRuntimeConfig["policy"]["planner"],
                    },
                  }),
                )
              }
            >
              <option value="multi_objective">
                multi_objective
              </option>
              <option value="heuristic">
                heuristic
              </option>
            </select>
          </label>

          <label>
            <span>
              Execution
            </span>

            <select
              value={
                config.policy.executionMode
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      executionMode:
                        event.target.value as ProjectRuntimeConfig["policy"]["executionMode"],
                    },
                  }),
                )
              }
            >
              <option value="auto">
                auto
              </option>
              <option value="parallel">
                parallel
              </option>
              <option value="sequential">
                sequential
              </option>
            </select>
          </label>

          <label>
            <span>
              Synthesis
            </span>

            <select
              value={
                config.policy.synthesisMode
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      synthesisMode:
                        event.target.value as ProjectRuntimeConfig["policy"]["synthesisMode"],
                    },
                  }),
                )
              }
            >
              <option value="auto">
                auto
              </option>
              <option value="always">
                always
              </option>
              <option value="never">
                never
              </option>
            </select>
          </label>

          <label>
            <span>
              Max latency (ms)
            </span>

            <input
              type="number"
              min={1}
              value={
                config.policy.constraints.maxLatencyMs
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      constraints: {
                        ...current.policy.constraints,
                        maxLatencyMs:
                          Number(
                            event.target.value,
                          ),
                      },
                    },
                  }),
                )
              }
            />
          </label>

          <label>
            <span>
              Max cost
            </span>

            <input
              type="number"
              min={0.001}
              step={0.001}
              value={
                config.policy.constraints.maxCost
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      constraints: {
                        ...current.policy.constraints,
                        maxCost:
                          Number(
                            event.target.value,
                          ),
                      },
                    },
                  }),
                )
              }
            />
          </label>

          <label>
            <span>
              Min quality
            </span>

            <input
              type="number"
              min={0.01}
              max={1}
              step={0.01}
              value={
                config.policy.constraints.minQuality
              }
              disabled={
                config.policy.mode ===
                "inherit"
              }
              onChange={(event) =>
                setConfig(
                  (current) => ({
                    ...current,
                    policy: {
                      ...current.policy,
                      constraints: {
                        ...current.policy.constraints,
                        minQuality:
                          Number(
                            event.target.value,
                          ),
                      },
                    },
                  }),
                )
              }
            />
          </label>
        </div>
      </div>

      <div className="project-runtime-boundary-note">
        <strong>
          Memory / Knowledge 边界
        </strong>

        <span>
          项目资源绑定只限制 Agent、Tool、MCP 和 Project Knowledge。项目文档与检索证据不会自动变成你的个人偏好或跨项目信息。
        </span>
      </div>
    </section>
  );
}

function ResourceSection({
  title,
  description,
  mode,
  onModeChange,
  allLabel,
  children,
}: {
  title: string;
  description: string;
  mode: "all" | "selected";
  onModeChange: (
    mode: "all" | "selected",
  ) => void;
  allLabel: string;
  children: ReactNode;
}) {
  return (
    <article className="project-runtime-resource-card">
      <div className="project-runtime-resource-head">
        <div>
          <h3>
            {title}
          </h3>

          <p>
            {description}
          </p>
        </div>

        <div className="project-runtime-mode-switch">
          <button
            type="button"
            className={
              mode === "all"
                ? "active"
                : ""
            }
            onClick={() =>
              onModeChange(
                "all",
              )
            }
          >
            全部
          </button>

          <button
            type="button"
            className={
              mode === "selected"
                ? "active"
                : ""
            }
            onClick={() =>
              onModeChange(
                "selected",
              )
            }
          >
            仅已选择
          </button>
        </div>
      </div>

      <div className="project-runtime-all-note">
        {mode === "all"
          ? `当前使用：${allLabel}`
          : "当前只会下发下面勾选的资源。"}
      </div>

      <div className="project-runtime-binding-list">
        {children}
      </div>
    </article>
  );
}

function BindingItem({
  checked,
  disabled,
  title,
  meta,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  title: string;
  meta: string;
  onChange: () => void;
}) {
  return (
    <label
      className={`project-runtime-binding-item ${
        disabled
          ? "disabled"
          : ""
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
      />

      <span>
        <strong>
          {title}
        </strong>

        <small>
          {meta}
        </small>
      </span>
    </label>
  );
}
