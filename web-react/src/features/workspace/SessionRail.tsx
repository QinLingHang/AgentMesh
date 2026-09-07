import {
  useMemo,
  useState,
} from "react";
import type {
  Conversation,
  Project,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";
import {
  formatDate,
} from "../../utils/format";

type EditorState =
  | {
      kind: "conversation";
      conversation: Conversation;
      title: string;
    }
  | {
      kind: "project-create";
      name: string;
      description: string;
    }
  | {
      kind: "project-edit";
      project: Project;
      name: string;
      description: string;
    }
  | null;

type DeleteState =
  | {
      kind: "conversation";
      conversation: Conversation;
    }
  | {
      kind: "project";
      project: Project;
    }
  | null;

function projectOfConversation(
  projects: Project[],
  conversationId: number,
) {
  return (
    projects.find(
      (project) =>
        project.conversationIds.includes(
          conversationId,
        ),
    ) ?? null
  );
}

function ConversationRow({
  conversation,
  current,
  projects,
  onOpen,
  onRename,
  onDelete,
  onMove,
}: {
  conversation: Conversation;
  current: boolean;
  projects: Project[];
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
  onMove: (
    projectId: number | null,
  ) => Promise<void>;
}) {
  const [
    menuOpen,
    setMenuOpen,
  ] =
    useState(false);

  const currentProject =
    projectOfConversation(
      projects,
      conversation.id,
    );

  return (
    <div
      className={
        `session-item-shell ${
          current
            ? "active"
            : ""
        }`
      }
      onBlur={(event) => {
        if (
          !event.currentTarget.contains(
            event.relatedTarget as Node | null,
          )
        ) {
          setMenuOpen(false);
        }
      }}
    >
      <button
        className="session-item"
        onClick={onOpen}
        type="button"
      >
        <span className="session-dot" />

        <span className="session-info">
          <strong>
            {conversation.title}
          </strong>

          <small>
            {formatDate(
              conversation.updatedAt,
            )}
          </small>
        </span>
      </button>

      <div className="session-item-actions">
        <button
          type="button"
          className="session-more-button"
          aria-label={`管理会话 ${conversation.title}`}
          title="更多"
          onClick={(event) => {
            event.stopPropagation();

            setMenuOpen(
              (value) =>
                !value,
            );
          }}
        >
          ···
        </button>

        {menuOpen && (
          <div
            className="session-popover"
            onClick={(event) =>
              event.stopPropagation()
            }
          >
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                onRename();
              }}
            >
              重命名
            </button>

            <div className="session-popover-label">
              移动到项目
            </div>

            {projects.map(
              (project) => (
                <button
                  type="button"
                  className={
                    currentProject?.id ===
                    project.id
                      ? "selected"
                      : ""
                  }
                  key={project.id}
                  onClick={() => {
                    setMenuOpen(false);

                    void onMove(
                      project.id,
                    );
                  }}
                >
                  {project.name}

                  {currentProject?.id ===
                    project.id && (
                    <span>
                      ✓
                    </span>
                  )}
                </button>
              ),
            )}

            {currentProject && (
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);

                  void onMove(
                    null,
                  );
                }}
              >
                移出项目
              </button>
            )}

            <div className="session-popover-divider" />

            <button
              type="button"
              className="danger"
              onClick={() => {
                setMenuOpen(false);
                onDelete();
              }}
            >
              删除会话
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectGroup({
  project,
  conversations,
  current,
  projects,
  create,
  setCurrent,
  onRenameConversation,
  onDeleteConversation,
  onMoveConversation,
  onOpenProject,
  selectedProjectId,
  onEditProject,
  onDeleteProject,
}: {
  project: Project;
  conversations: Conversation[];
  current: Conversation | null;
  projects: Project[];
  create: (
    projectId?: number,
  ) => Promise<void>;
  setCurrent: (
    conversation: Conversation,
  ) => void;
  onRenameConversation: (
    conversation: Conversation,
  ) => void;
  onDeleteConversation: (
    conversation: Conversation,
  ) => void;
  onMoveConversation: (
    conversationId: number,
    projectId: number | null,
  ) => Promise<void>;
  onOpenProject: (
    project: Project,
  ) => void;
  selectedProjectId: number | null;
  onEditProject: () => void;
  onDeleteProject: () => void;
}) {
  const [
    expanded,
    setExpanded,
  ] =
    useState(true);

  const [
    menuOpen,
    setMenuOpen,
  ] =
    useState(false);

  return (
    <div className="session-project">
      <div
        className="session-project-row"
        onBlur={(event) => {
          if (
            !event.currentTarget.contains(
              event.relatedTarget as Node | null,
            )
          ) {
            setMenuOpen(false);
          }
        }}
      >
        <button
          type="button"
          className="session-project-toggle"
          aria-label={
            expanded
              ? "收起项目会话"
              : "展开项目会话"
          }
          onClick={() =>
            setExpanded(
              (value) =>
                !value,
            )
          }
        >
          <span
            className={
              `session-project-chevron ${
                expanded
                  ? "open"
                  : ""
              }`
            }
          >
            <Icon
              name="chevron"
              size={13}
            />
          </span>
        </button>

        <button
          type="button"
          className={
            `session-project-main ${
              selectedProjectId ===
              project.id
                ? "selected"
                : ""
            }`
          }
          onClick={() =>
            onOpenProject(
              project,
            )
          }
        >
          <span className="session-project-name">
            {project.name}
          </span>

          <span className="session-project-count">
            {conversations.length}
          </span>
        </button>

        <button
          type="button"
          className="session-project-add"
          title="在此项目中新建会话"
          onClick={() =>
            void create(
              project.id,
            )
          }
        >
          <Icon
            name="plus"
            size={13}
          />
        </button>

        <div className="session-project-actions">
          <button
            type="button"
            className="session-more-button"
            title="项目设置"
            onClick={() =>
              setMenuOpen(
                (value) =>
                  !value,
              )
            }
          >
            ···
          </button>

          {menuOpen && (
            <div className="session-popover project-popover">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  onEditProject();
                }}
              >
                重命名项目
              </button>

              <button
                type="button"
                className="danger"
                onClick={() => {
                  setMenuOpen(false);
                  onDeleteProject();
                }}
              >
                删除项目
              </button>
            </div>
          )}
        </div>
      </div>

      {expanded && (
        <div className="session-project-conversations">
          {conversations.length ===
          0 ? (
            <button
              type="button"
              className="session-project-empty"
              onClick={() =>
                void create(
                  project.id,
                )
              }
            >
              ＋ 在项目中新建会话
            </button>
          ) : (
            conversations.map(
              (conversation) => (
                <ConversationRow
                  key={
                    conversation.id
                  }
                  conversation={
                    conversation
                  }
                  current={
                    selectedProjectId ==
                      null &&
                    current?.id ===
                      conversation.id
                  }
                  projects={
                    projects
                  }
                  onOpen={() =>
                    setCurrent(
                      conversation,
                    )
                  }
                  onRename={() =>
                    onRenameConversation(
                      conversation,
                    )
                  }
                  onDelete={() =>
                    onDeleteConversation(
                      conversation,
                    )
                  }
                  onMove={(
                    projectId,
                  ) =>
                    onMoveConversation(
                      conversation.id,
                      projectId,
                    )
                  }
                />
              ),
            )
          )}
        </div>
      )}
    </div>
  );
}

export function SessionRail({
  conversations,
  projects,
  current,
  setCurrent,
  create,
  renameConversation,
  deleteConversation,
  createProject,
  updateProject,
  deleteProject,
  moveConversation,
  selectedProjectId,
  onOpenProject,
}: {
  conversations: Conversation[];
  projects: Project[];
  current: Conversation | null;
  setCurrent: (
    conversation: Conversation,
  ) => void;
  create: (
    projectId?: number,
  ) => Promise<void>;
  renameConversation: (
    conversationId: number,
    title: string,
  ) => Promise<Conversation>;
  deleteConversation: (
    conversationId: number,
  ) => Promise<void>;
  createProject: (
    name: string,
    description: string,
  ) => Promise<Project>;
  updateProject: (
    projectId: number,
    name: string,
    description: string,
  ) => Promise<Project>;
  deleteProject: (
    projectId: number,
  ) => Promise<void>;
  moveConversation: (
    conversationId: number,
    projectId: number | null,
  ) => Promise<void>;
  selectedProjectId: number | null;
  onOpenProject: (
    project: Project,
  ) => void;
}) {
  const [
    editor,
    setEditor,
  ] =
    useState<EditorState>(
      null,
    );

  const [
    deleting,
    setDeleting,
  ] =
    useState<DeleteState>(
      null,
    );

  const [
    busy,
    setBusy,
  ] =
    useState(false);

  const [
    feedback,
    setFeedback,
  ] =
    useState("");

  const assignedIds =
    useMemo(
      () =>
        new Set(
          projects.flatMap(
            (project) =>
              project.conversationIds,
          ),
        ),
      [projects],
    );

  const unassigned =
    useMemo(
      () =>
        conversations.filter(
          (conversation) =>
            !assignedIds.has(
              conversation.id,
            ),
        ),
      [
        conversations,
        assignedIds,
      ],
    );

  const saveEditor =
    async () => {
      if (!editor) {
        return;
      }

      try {
        setBusy(true);
        setFeedback("");

        if (
          editor.kind ===
          "conversation"
        ) {
          const title =
            editor.title.trim();

          if (!title) {
            setFeedback(
              "会话名称不能为空。",
            );

            return;
          }

          await renameConversation(
            editor.conversation.id,
            title,
          );
        }

        if (
          editor.kind ===
          "project-create"
        ) {
          const name =
            editor.name.trim();

          if (!name) {
            setFeedback(
              "项目名称不能为空。",
            );

            return;
          }

          await createProject(
            name,
            editor.description.trim(),
          );
        }

        if (
          editor.kind ===
          "project-edit"
        ) {
          const name =
            editor.name.trim();

          if (!name) {
            setFeedback(
              "项目名称不能为空。",
            );

            return;
          }

          await updateProject(
            editor.project.id,
            name,
            editor.description.trim(),
          );
        }

        setEditor(null);
      } catch (error) {
        setFeedback(
          error instanceof Error
            ? error.message
            : "保存失败，请稍后重试。",
        );
      } finally {
        setBusy(false);
      }
    };

  const confirmDelete =
    async () => {
      if (!deleting) {
        return;
      }

      try {
        setBusy(true);
        setFeedback("");

        if (
          deleting.kind ===
          "conversation"
        ) {
          await deleteConversation(
            deleting.conversation.id,
          );
        } else {
          await deleteProject(
            deleting.project.id,
          );
        }

        setDeleting(null);
      } catch (error) {
        setFeedback(
          error instanceof Error
            ? error.message
            : "删除失败，请稍后重试。",
        );
      } finally {
        setBusy(false);
      }
    };

  return (
    <aside className="session-rail">
      <div className="session-head">
        <div>
          <span className="eyebrow">
            最近
          </span>

          <h3>
            任务与项目
          </h3>
        </div>
      </div>

      <button
        className="session-create-button"
        onClick={() =>
          void create()
        }
        type="button"
      >
        <span className="session-create-icon">
          <Icon
            name="plus"
            size={15}
          />
        </span>

        <span>
          新建任务
        </span>
      </button>

      {feedback && (
        <div className="session-feedback">
          {feedback}
        </div>
      )}

      <div className="session-section-heading">
        <span>
          项目
        </span>

        <button
          type="button"
          className="session-section-add"
          title="新建项目"
          data-testid="project-create-open"
          onClick={() => {
            setFeedback("");

            setEditor({
              kind: "project-create",
              name: "",
              description: "",
            });
          }}
        >
          <Icon
            name="plus"
            size={13}
          />
        </button>
      </div>

      <div className="session-project-list">
        {projects.length ===
        0 ? (
          <button
            type="button"
            className="session-project-empty-root"
            data-testid="project-create-empty"
            onClick={() =>
              setEditor({
                kind: "project-create",
                name: "",
                description: "",
              })
            }
          >
            ＋ 创建第一个项目
          </button>
        ) : (
          projects.map(
            (project) => {
              const projectConversations =
                project.conversationIds
                  .map(
                    (id) =>
                      conversations.find(
                        (conversation) =>
                          conversation.id ===
                          id,
                      ),
                  )
                  .filter(
                    (
                      value,
                    ): value is Conversation =>
                      value != null,
                  );

              return (
                <ProjectGroup
                  key={
                    project.id
                  }
                  project={
                    project
                  }
                  conversations={
                    projectConversations
                  }
                  current={
                    current
                  }
                  projects={
                    projects
                  }
                  create={create}
                  setCurrent={
                    setCurrent
                  }
                  onRenameConversation={(
                    conversation,
                  ) =>
                    setEditor({
                      kind: "conversation",
                      conversation,
                      title:
                        conversation.title,
                    })
                  }
                  onDeleteConversation={(
                    conversation,
                  ) =>
                    setDeleting({
                      kind: "conversation",
                      conversation,
                    })
                  }
                  onMoveConversation={
                    moveConversation
                  }
                  onOpenProject={
                    onOpenProject
                  }
                  selectedProjectId={
                    selectedProjectId
                  }
                  onEditProject={() =>
                    setEditor({
                      kind: "project-edit",
                      project,
                      name:
                        project.name,
                      description:
                        project.description,
                    })
                  }
                  onDeleteProject={() =>
                    setDeleting({
                      kind: "project",
                      project,
                    })
                  }
                />
              );
            },
          )
        )}
      </div>

      <div className="session-section-heading recent-heading">
        <span>
          最近会话
        </span>

        <span className="session-section-count">
          {unassigned.length}
        </span>
      </div>

      <div className="session-scroll">
        {unassigned.length ===
        0 ? (
          <div className="session-empty">
            暂无未归类会话。
          </div>
        ) : (
          unassigned.map(
            (conversation) => (
              <ConversationRow
                key={
                  conversation.id
                }
                conversation={
                  conversation
                }
                current={
                  selectedProjectId ==
                    null &&
                  current?.id ===
                    conversation.id
                }
                projects={
                  projects
                }
                onOpen={() =>
                  setCurrent(
                    conversation,
                  )
                }
                onRename={() =>
                  setEditor({
                    kind: "conversation",
                    conversation,
                    title:
                      conversation.title,
                  })
                }
                onDelete={() =>
                  setDeleting({
                    kind: "conversation",
                    conversation,
                  })
                }
                onMove={(
                  projectId,
                ) =>
                  moveConversation(
                    conversation.id,
                    projectId,
                  )
                }
              />
            ),
          )
        )}
      </div>

      {editor && (
        <div className="workspace-dialog-backdrop">
          <form
            className="workspace-management-dialog"
            onSubmit={(event) => {
              event.preventDefault();

              void saveEditor();
            }}
          >
            <h2>
              {editor.kind ===
              "conversation"
                ? "重命名会话"
                : editor.kind ===
                    "project-create"
                  ? "创建项目"
                  : "编辑项目"}
            </h2>

            {editor.kind ===
            "conversation" ? (
              <label className="field">
                <span>
                  会话名称
                </span>

                <input
                  autoFocus
                  value={
                    editor.title
                  }
                  maxLength={120}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      title:
                        event.target.value,
                    })
                  }
                />
              </label>
            ) : (
              <>
                <label className="field">
                  <span>
                    项目名称
                  </span>

                  <input
                    autoFocus
                    value={
                      editor.name
                    }
                    maxLength={80}
                    placeholder="例如：AgentMesh 开发"
                    data-testid="project-name-input"
                    onChange={(event) =>
                      setEditor({
                        ...editor,
                        name:
                          event.target.value,
                      })
                    }
                  />
                </label>

                <label className="field">
                  <span>
                    描述（可选）
                  </span>

                  <textarea
                    value={
                      editor.description
                    }
                    maxLength={240}
                    rows={3}
                    placeholder="这个项目主要用来做什么？"
                    onChange={(event) =>
                      setEditor({
                        ...editor,
                        description:
                          event.target.value,
                      })
                    }
                  />
                </label>
              </>
            )}

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() =>
                  setEditor(
                    null,
                  )
                }
              >
                取消
              </button>

              <button
                type="submit"
                className="primary-button"
                data-testid="project-editor-submit"
                disabled={busy}
              >
                {busy
                  ? "保存中..."
                  : "保存"}
              </button>
            </div>
          </form>
        </div>
      )}

      {deleting && (
        <div className="workspace-dialog-backdrop">
          <div className="workspace-management-dialog">
            <div className="workspace-danger-icon">
              <Icon
                name="trash"
                size={18}
              />
            </div>

            <h2>
              {deleting.kind ===
              "conversation"
                ? "删除会话？"
                : "删除项目？"}
            </h2>

            <p className="workspace-delete-target">
              {deleting.kind ===
              "conversation"
                ? deleting
                    .conversation
                    .title
                : deleting
                    .project
                    .name}
            </p>

            <div className="workspace-delete-note">
              {deleting.kind ===
              "conversation"
                ? "删除后，会话中的消息与回答会一并删除；任务历史仍按后端数据关系保留。此操作不可撤销。"
                : "删除项目不会删除其中的会话；这些会话会回到“最近会话”。项目知识文件属于项目资源，会随项目一并删除。"}
            </div>

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy}
                onClick={() =>
                  setDeleting(
                    null,
                  )
                }
              >
                取消
              </button>

              <button
                type="button"
                className="workspace-danger-button"
                disabled={busy}
                onClick={() =>
                  void confirmDelete()
                }
              >
                {busy
                  ? "删除中..."
                  : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
