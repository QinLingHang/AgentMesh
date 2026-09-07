import {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type MouseEvent,
} from "react";
import {
  ApiError,
  createMemory,
  deleteMemory,
  listMemories,
  updateMemory,
} from "../../api";
import type {
  MemoryCategory,
  UserMemory,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";
import {
  formatDate,
} from "../../utils/format";

const CATEGORY_OPTIONS: {
  value: MemoryCategory | "all";
  label: string;
}[] = [
  {
    value: "all",
    label: "全部类别",
  },
  {
    value: "preference",
    label: "偏好",
  },
  {
    value: "profile",
    label: "个人信息",
  },
  {
    value: "goal",
    label: "目标",
  },
  {
    value: "workflow",
    label: "工作方式",
  },
  {
    value: "fact",
    label: "稳定事实",
  },
  {
    value: "other",
    label: "其他",
  },
];

const SOURCE_OPTIONS = [
  {
    value: "all",
    label: "全部来源",
  },
  {
    value: "manual",
    label: "手动维护",
  },
  {
    value: "explicit_user",
    label: "用户明确表达",
  },
  {
    value: "inferred_user",
    label: "自动推断",
  },
] as const;

type SourceFilter =
  (typeof SOURCE_OPTIONS)[number]["value"];

type Feedback =
  | {
      type: "success" | "error";
      message: string;
    }
  | null;

type EditorState =
  | {
      mode: "create";
      category: MemoryCategory;
      memoryKey: string;
      content: string;
    }
  | {
      mode: "edit";
      memory: UserMemory;
      category: MemoryCategory;
      memoryKey: string;
      content: string;
    }
  | null;

function categoryLabel(
  category: string,
) {
  return (
    CATEGORY_OPTIONS.find(
      (item) =>
        item.value ===
        category,
    )?.label ?? category
  );
}

function sourceLabel(
  sourceType: string,
) {
  switch (sourceType) {
    case "manual":
      return "手动维护";
    case "explicit_user":
      return "用户明确表达";
    case "inferred_user":
      return "自动推断";
    default:
      return sourceType;
  }
}

function sourceClass(
  sourceType: string,
) {
  switch (sourceType) {
    case "manual":
      return "manual";
    case "explicit_user":
      return "explicit";
    case "inferred_user":
      return "inferred";
    default:
      return "default";
  }
}

function friendlyError(
  error: unknown,
) {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "这个 memory_key 已存在，请修改现有记忆或使用新的 key。";
    }

    if (error.status >= 500) {
      return "长期记忆服务暂时不可用，请稍后重试。";
    }

    if (error.message.trim()) {
      return error.message;
    }
  }

  return error instanceof Error
    ? error.message
    : "操作失败，请稍后重试。";
}

function normalizeKeyInput(
  value: string,
) {
  return value
    .toLowerCase()
    .replace(/\s+/g, ".")
    .replace(/[^a-z0-9._-]/g, "");
}

function MemoryEditor({
  editor,
  busy,
  onChange,
  onClose,
  onSubmit,
}: {
  editor: Exclude<EditorState, null>;
  busy: boolean;
  onChange: (
    next: Exclude<EditorState, null>,
  ) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const isEdit =
    editor.mode === "edit";

  return (
    <div
      className="memory-editor-backdrop"
      role="presentation"
      onMouseDown={(event: MouseEvent<HTMLDivElement>) => {
        if (
          event.target ===
          event.currentTarget
        ) {
          onClose();
        }
      }}
    >
      <section
        className="memory-editor"
        role="dialog"
        aria-modal="true"
        aria-label={
          isEdit
            ? "编辑长期记忆"
            : "新增长期记忆"
        }
      >
        <header>
          <div>
            <span className="eyebrow">
              USER-GLOBAL MEMORY
            </span>

            <h2>
              {isEdit
                ? "编辑长期记忆"
                : "新增长期记忆"}
            </h2>

            <p>
              {isEdit
                ? "手动修改后，这条记忆会提升为 manual 来源，优先于自动推断。"
                : "手动创建的记忆属于当前用户，可跨普通会话和 项目使用。"}
            </p>
          </div>

          <button
            className="icon-button"
            title="关闭"
            onClick={onClose}
          >
            <Icon
              name="close"
              size={17}
            />
          </button>
        </header>

        <div className="memory-editor-body">
          <label className="field">
            <span>类别</span>

            <select
              value={editor.category}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                onChange({
                  ...editor,
                  category:
                    event.target
                      .value as MemoryCategory,
                })
              }
            >
              {CATEGORY_OPTIONS.filter(
                (item) =>
                  item.value !==
                  "all",
              ).map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>记忆标识</span>

            <input
              value={editor.memoryKey}
              placeholder="例如 coding.explanation_style"
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                onChange({
                  ...editor,
                  memoryKey:
                    normalizeKeyInput(
                      event.target.value,
                    ),
                })
              }
            />

            <small className="memory-field-hint">
              使用稳定的英文 key，支持小写字母、数字、点、短横线和下划线。
            </small>
          </label>

          <label className="field memory-content-field">
            <span>记忆内容</span>

            <textarea
              rows={7}
              value={editor.content}
              placeholder="写下希望 AgentMesh 长期记住的信息……"
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                onChange({
                  ...editor,
                  content:
                    event.target.value,
                })
              }
            />
          </label>

          <div className="memory-editor-boundary">
            <strong>
              Memory / Knowledge 边界
            </strong>
            <span>
              这里仅管理 用户长期记忆。项目文档、检索证据、工具与外部服务结果不属于长期记忆。
            </span>
          </div>
        </div>

        <footer>
          <button
            className="secondary-button"
            onClick={onClose}
            disabled={busy}
          >
            取消
          </button>

          <button
            className="primary-button"
            onClick={onSubmit}
            disabled={
              busy ||
              !editor.memoryKey.trim() ||
              !editor.content.trim()
            }
          >
            {busy
              ? "保存中..."
              : isEdit
                ? "保存修改"
                : "创建记忆"}
          </button>
        </footer>
      </section>
    </div>
  );
}

export function MemoryCenter() {
  const [memories, setMemories] =
    useState<UserMemory[]>([]);

  const [loading, setLoading] =
    useState(true);

  const [busy, setBusy] =
    useState(false);

  const [feedback, setFeedback] =
    useState<Feedback>(null);

  const [search, setSearch] =
    useState("");

  const [category, setCategory] =
    useState<MemoryCategory | "all">(
      "all",
    );

  const [source, setSource] =
    useState<SourceFilter>("all");

  const [editor, setEditor] =
    useState<EditorState>(null);

  const load = async () => {
    setLoading(true);

    try {
      const result =
        await listMemories({
          status: "active",
          limit: 200,
        });

      setMemories(result);
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(error),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(
    () => {
      const keyword =
        search
          .trim()
          .toLowerCase();

      return memories.filter(
        (memory) => {
          if (
            category !== "all" &&
            memory.category !==
              category
          ) {
            return false;
          }

          if (
            source !== "all" &&
            memory.sourceType !==
              source
          ) {
            return false;
          }

          if (!keyword) {
            return true;
          }

          return [
            memory.memoryKey,
            memory.content,
            memory.category,
          ].some((value) =>
            value
              .toLowerCase()
              .includes(keyword),
          );
        },
      );
    },
    [
      memories,
      search,
      category,
      source,
    ],
  );

  const manualCount =
    memories.filter(
      (item) =>
        item.sourceType ===
        "manual",
    ).length;

  const explicitCount =
    memories.filter(
      (item) =>
        item.sourceType ===
        "explicit_user",
    ).length;

  const inferredCount =
    memories.filter(
      (item) =>
        item.sourceType ===
        "inferred_user",
    ).length;

  const openCreate = () => {
    setFeedback(null);
    setEditor({
      mode: "create",
      category: "preference",
      memoryKey: "",
      content: "",
    });
  };

  const openEdit = (
    memory: UserMemory,
  ) => {
    setFeedback(null);
    setEditor({
      mode: "edit",
      memory,
      category:
        memory.category,
      memoryKey:
        memory.memoryKey,
      content:
        memory.content,
    });
  };

  const submitEditor = async () => {
    if (!editor) {
      return;
    }

    setBusy(true);
    setFeedback(null);

    try {
      if (
        editor.mode === "create"
      ) {
        await createMemory({
          category:
            editor.category,
          memoryKey:
            editor.memoryKey,
          content:
            editor.content,
          sourceType: "manual",
          confidence: 1,
          status: "active",
        });

        setFeedback({
          type: "success",
          message:
            "长期记忆已创建。它属于当前用户，可跨 项目使用。",
        });
      } else {
        await updateMemory(
          editor.memory.id,
          {
            category:
              editor.category,
            memoryKey:
              editor.memoryKey,
            content:
              editor.content,
            sourceType: "manual",
            confidence: 1,
          },
        );

        setFeedback({
          type: "success",
          message:
            "长期记忆已更新，并提升为手动维护来源。",
        });
      }

      setEditor(null);
      await load();
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(error),
      });
    } finally {
      setBusy(false);
    }
  };

  const removeMemory = async (
    memory: UserMemory,
  ) => {
    const confirmed =
      window.confirm(
        `确定删除长期记忆“${memory.memoryKey}”吗？\n\n删除后 AgentMesh 将不再召回这条记忆。`,
      );

    if (!confirmed) {
      return;
    }

    setBusy(true);
    setFeedback(null);

    try {
      await deleteMemory(
        memory.id,
      );

      setMemories(
        (items) =>
          items.filter(
            (item) =>
              item.id !==
              memory.id,
          ),
      );

      setFeedback({
        type: "success",
        message:
          "长期记忆已删除。",
      });
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(error),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page memory-center">
      <header className="page-head memory-page-head">
        <div>
          <div className="eyebrow">
            USER-GLOBAL MEMORY
          </div>

          <h1>
            长期记忆
          </h1>

          <p>
            查看和维护 AgentMesh 对当前用户长期保留的信息。Memory 跨项目 生效，但不会把 项目知识库 混入这里。
          </p>
        </div>

        <div className="page-actions">
          <button
            className="secondary-button"
            onClick={() =>
              void load()
            }
            disabled={loading}
          >
            刷新
          </button>

          <button
            className="primary-button memory-primary-action"
            onClick={openCreate}
          >
            <Icon
              name="plus"
              size={15}
            />
            新增记忆
          </button>
        </div>
      </header>

      <section className="memory-boundary-banner">
        <div className="memory-boundary-icon">
          <Icon
            name="memory"
            size={20}
          />
        </div>

        <div>
          <strong>
            Memory = User-global
          </strong>
          <p>
            普通会话、不同项目 共享同一套用户长期记忆；项目文档与 检索证据仍严格留在各自 项目知识库 中。
          </p>
        </div>

        <span>
          项目知识库 ≠ Memory
        </span>
      </section>

      {feedback && (
        <div
          className={`memory-feedback ${feedback.type}`}
        >
          <span>
            {feedback.message}
          </span>

          <button
            onClick={() =>
              setFeedback(null)
            }
          >
            <Icon
              name="close"
              size={14}
            />
          </button>
        </div>
      )}

      <section className="memory-summary-grid">
        <article>
          <span>有效记忆</span>
          <strong>
            {memories.length}
          </strong>
          <small>
            当前用户长期记忆总数
          </small>
        </article>

        <article>
          <span>手动添加</span>
          <strong>
            {manualCount}
          </strong>
          <small>
            用户手动维护，最高优先级
          </small>
        </article>

        <article>
          <span>用户明确提供</span>
          <strong>
            {explicitCount}
          </strong>
          <small>
            来自用户明确表达
          </small>
        </article>

        <article>
          <span>自动推断</span>
          <strong>
            {inferredCount}
          </strong>
          <small>
            自动提取的稳定信息
          </small>
        </article>
      </section>

      <section className="memory-library-section">
        <header className="memory-library-head">
          <div>
            <h2>
              Memory Store
            </h2>
            <p>
              当前仅展示 active Memory。手动修改会覆盖自动推断的 authority。
            </p>
          </div>

          <span>
            {filtered.length} / {memories.length}
          </span>
        </header>

        <div className="memory-toolbar">
          <label className="memory-search">
            <Icon
              name="search"
              size={15}
            />

            <input
              value={search}
              placeholder="搜索 key 或记忆内容"
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setSearch(
                  event.target.value,
                )
              }
            />
          </label>

          <select
            value={category}
            onChange={(event: ChangeEvent<HTMLSelectElement>) =>
              setCategory(
                event.target
                  .value as
                  | MemoryCategory
                  | "all",
              )
            }
          >
            {CATEGORY_OPTIONS.map(
              (item) => (
                <option
                  key={item.value}
                  value={item.value}
                >
                  {item.label}
                </option>
              ),
            )}
          </select>

          <select
            value={source}
            onChange={(event: ChangeEvent<HTMLSelectElement>) =>
              setSource(
                event.target
                  .value as SourceFilter,
              )
            }
          >
            {SOURCE_OPTIONS.map(
              (item) => (
                <option
                  key={item.value}
                  value={item.value}
                >
                  {item.label}
                </option>
              ),
            )}
          </select>
        </div>

        {loading ? (
          <div className="memory-empty-state">
            <div>
              <Icon
                name="memory"
                size={22}
              />
            </div>
            <strong>
              正在读取长期记忆…
            </strong>
          </div>
        ) : filtered.length === 0 ? (
          <div className="memory-empty-state">
            <div>
              <Icon
                name="memory"
                size={22}
              />
            </div>

            <strong>
              {memories.length === 0
                ? "还没有长期记忆"
                : "没有匹配的记忆"}
            </strong>

            <p>
              {memories.length === 0
                ? "你可以手动新增，或者让 AgentMesh 在后续对话中自动提取稳定偏好与长期信息。"
                : "试试清空搜索词或调整类别、来源筛选。"}
            </p>

            {memories.length === 0 && (
              <button
                className="primary-button compact-button"
                onClick={openCreate}
              >
                新增第一条记忆
              </button>
            )}
          </div>
        ) : (
          <div className="memory-card-list">
            {filtered.map(
              (memory) => (
                <article
                  key={memory.id}
                  className="memory-card"
                >
                  <header>
                    <div className="memory-card-title">
                      <span
                        className={`memory-source-badge ${sourceClass(
                          memory.sourceType,
                        )}`}
                      >
                        {sourceLabel(
                          memory.sourceType,
                        )}
                      </span>

                      <span className="memory-category-badge">
                        {categoryLabel(
                          memory.category,
                        )}
                      </span>
                    </div>

                    <div className="memory-card-actions">
                      <button
                        className="memory-text-button"
                        onClick={() =>
                          openEdit(
                            memory,
                          )
                        }
                        disabled={busy}
                      >
                        编辑
                      </button>

                      <button
                        className="danger-link"
                        onClick={() =>
                          void removeMemory(
                            memory,
                          )
                        }
                        disabled={busy}
                      >
                        删除
                      </button>
                    </div>
                  </header>

                  <code className="memory-key">
                    {memory.memoryKey}
                  </code>

                  <p className="memory-content">
                    {memory.content}
                  </p>

                  <footer>
                    <span>
                      Confidence {Math.round(
                        memory.confidence *
                          100,
                      )}%
                    </span>

                    <span>
                      更新于 {formatDate(
                        memory.updatedAt,
                      )}
                    </span>

                    <span>
                      最近召回 {memory.lastAccessedAt
                        ? formatDate(
                            memory.lastAccessedAt,
                          )
                        : "暂无"}
                    </span>
                  </footer>
                </article>
              ),
            )}
          </div>
        )}
      </section>

      {editor && (
        <MemoryEditor
          editor={editor}
          busy={busy}
          onChange={setEditor}
          onClose={() =>
            !busy &&
            setEditor(null)
          }
          onSubmit={() =>
            void submitEditor()
          }
        />
      )}
    </div>
  );
}
