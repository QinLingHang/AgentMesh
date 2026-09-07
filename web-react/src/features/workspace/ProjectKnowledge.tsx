import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  deleteProjectKnowledgeFile,
  listProjectKnowledgeFiles,
  reindexKnowledgeFile,
  uploadProjectKnowledgeFile,
} from "../../api";
import type {
  KnowledgeFile,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";
import {
  formatDate,
} from "../../utils/format";
import {
  ProjectGlobalKnowledgeBindings,
} from "./ProjectGlobalKnowledgeBindings";

const MAX_UPLOAD_BYTES =
  20 * 1024 * 1024;

const ALLOWED_EXTENSIONS =
  new Set([
    "pdf",
    "docx",
    "txt",
    "md",
    "markdown",
  ]);

export type ProjectKnowledgeStats = {
  total: number;
  ready: number;
  pending: number;
  error: number;
};

function extensionOf(
  name: string,
) {
  const index =
    name.lastIndexOf(".");

  if (
    index < 0 ||
    index === name.length - 1
  ) {
    return "";
  }

  return name
    .slice(index + 1)
    .toLowerCase();
}

function formatBytes(
  value: number,
) {
  if (
    !Number.isFinite(value) ||
    value <= 0
  ) {
    return "0 B";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  if (
    value <
    1024 * 1024
  ) {
    return `${(
      value / 1024
    ).toFixed(1)} KB`;
  }

  return `${(
    value /
    (1024 * 1024)
  ).toFixed(1)} MB`;
}

function statusLabel(
  status: string,
) {
  switch (
    status.toUpperCase()
  ) {
    case "READY":
      return "可检索";

    case "INDEXING":
      return "索引中";

    case "ERROR":
      return "失败";

    default:
      return "待索引";
  }
}

function statusClass(
  status: string,
) {
  const value =
    status.toUpperCase();

  if (value === "READY") {
    return "ready";
  }

  if (
    value === "INDEXING"
  ) {
    return "indexing";
  }

  if (value === "ERROR") {
    return "error";
  }

  return "uploaded";
}

function friendlyKnowledgeError(
  error: unknown,
) {
  if (error instanceof ApiError) {
    if (error.status === 413) {
      return "文件超过 20 MB，请选择更小的文件。";
    }

    if (error.status === 415) {
      return "暂时只支持 PDF、DOCX、TXT、Markdown。";
    }

    if (error.status === 404) {
      return "项目或文件不存在，请刷新后重试。";
    }

    if (error.status >= 500) {
      return "知识文件服务暂时不可用，请稍后重试。";
    }

    if (error.message.trim()) {
      return error.message;
    }
  }

  return error instanceof Error
    ? error.message
    : "操作失败，请稍后重试。";
}

export function ProjectKnowledge({
  projectId,
  onStatsChange,
}: {
  projectId: number;
  onStatsChange?: (
    stats: ProjectKnowledgeStats,
  ) => void;
}) {
  const fileInputRef =
    useRef<HTMLInputElement>(
      null,
    );

  const [files, setFiles] =
    useState<KnowledgeFile[]>(
      [],
    );

  const [loading, setLoading] =
    useState(true);

  const [uploading, setUploading] =
    useState<string[]>([]);

  const [deleting, setDeleting] =
    useState<KnowledgeFile | null>(
      null,
    );

  const [deleteBusy, setDeleteBusy] =
    useState(false);

  const [
    reindexingFileId,
    setReindexingFileId,
  ] = useState<number | null>(null);

  const [feedback, setFeedback] =
    useState<{
      type: "success" | "error";
      message: string;
    } | null>(null);

  const stats =
    useMemo<ProjectKnowledgeStats>(
      () => {
        let ready = 0;
        let error = 0;
        let pending = 0;

        for (const file of files) {
          const status = String(
            file.status,
          ).toUpperCase();

          if (status === "READY") {
            ready += 1;
          } else if (
            status === "ERROR"
          ) {
            error += 1;
          } else {
            pending += 1;
          }
        }

        return {
          total: files.length,
          ready,
          pending,
          error,
        };
      },
      [files],
    );

  useEffect(
    () => {
      onStatsChange?.(stats);
    },
    [onStatsChange, stats],
  );

  const load = useCallback(
    async (silent = false) => {
      try {
        if (!silent) {
          setLoading(true);
        }

        const result =
          await listProjectKnowledgeFiles(
            projectId,
          );

        setFiles(result);
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            friendlyKnowledgeError(
              error,
            ),
        });
      } finally {
        if (!silent) {
          setLoading(false);
        }
      }
    },
    [projectId],
  );

  useEffect(
    () => {
      setFiles([]);
      setFeedback(null);
      void load();
    },
    [load],
  );

  const hasPendingFiles = useMemo(
    () =>
      files.some((file) => {
        const status = String(file.status).toUpperCase();
        return status !== "READY" && status !== "ERROR";
      }),
    [files],
  );

  useEffect(
    () => {
      if (!hasPendingFiles) {
        return;
      }

      const timer = window.setInterval(
        () => {
          void load(true);
        },
        2500,
      );

      return () => window.clearInterval(timer);
    },
    [hasPendingFiles, load],
  );

  const validateLocalFile = (
    file: File,
  ) => {
    const extension = extensionOf(
      file.name,
    );

    if (
      !ALLOWED_EXTENSIONS.has(
        extension,
      )
    ) {
      return "暂时只支持 PDF、DOCX、TXT、Markdown。";
    }

    if (file.size <= 0) {
      return "不能上传空文件。";
    }

    if (
      file.size > MAX_UPLOAD_BYTES
    ) {
      return "单个文件不能超过 20 MB。";
    }

    return "";
  };

  const uploadSelected = async (
    selected: FileList | null,
  ) => {
    if (
      !selected ||
      selected.length === 0
    ) {
      return;
    }

    const candidates = Array.from(
      selected,
    );

    const validationError =
      candidates
        .map(validateLocalFile)
        .find(Boolean);

    if (validationError) {
      setFeedback({
        type: "error",
        message: validationError,
      });
      return;
    }

    setFeedback(null);
    const succeeded: string[] = [];

    try {
      for (const file of candidates) {
        setUploading((current) => [
          ...current,
          file.name,
        ]);

        try {
          await uploadProjectKnowledgeFile(
            projectId,
            file,
          );
          succeeded.push(file.name);
        } finally {
          setUploading((current) =>
            current.filter(
              (name) =>
                name !== file.name,
            ),
          );
        }
      }

      await load();

      setFeedback({
        type: "success",
        message:
          `${succeeded.length} 个文件已上传，系统正在自动解析并建立 Milvus 索引。`,
      });
    } catch (error) {
      await load();
      setFeedback({
        type: "error",
        message:
          friendlyKnowledgeError(
            error,
          ),
      });
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const reindexFile = async (file: KnowledgeFile) => {
    try {
      setReindexingFileId(file.id);
      setFeedback(null);
      await reindexKnowledgeFile(file.id);
      await load();
      setFeedback({
        type: "success",
        message: `“${file.originalName}”已提交重新索引。`,
      });
    } catch (error) {
      setFeedback({
        type: "error",
        message: friendlyKnowledgeError(error),
      });
    } finally {
      setReindexingFileId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) {
      return;
    }

    try {
      setDeleteBusy(true);
      setFeedback(null);

      await deleteProjectKnowledgeFile(
        projectId,
        deleting.id,
      );

      setFiles((current) =>
        current.filter(
          (file) =>
            file.id !== deleting.id,
        ),
      );

      setDeleting(null);
      setFeedback({
        type: "success",
        message: "知识文件已删除。",
      });
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyKnowledgeError(
            error,
          ),
      });
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <section
      id={`project-knowledge-${projectId}`}
      className="project-knowledge-section"
    >
      <header className="project-knowledge-head">
        <div>
          <div className="eyebrow">
            PROJECT KNOWLEDGE
          </div>

          <h2>项目知识</h2>

          <p>
            原始文件由 Go Control Plane 接收和持久化，Python Runtime 自动完成解析、Chunk、Embedding 与 Milvus 索引。
          </p>
        </div>

        <div className="project-knowledge-head-actions">
          <input
            ref={fileInputRef}
            className="project-file-input"
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.markdown"
            onChange={(event) =>
              void uploadSelected(
                event.target.files,
              )
            }
          />

          <button
            type="button"
            className="primary-button project-upload-button"
            disabled={uploading.length > 0}
            onClick={() =>
              fileInputRef.current?.click()
            }
          >
            <Icon name="plus" size={14} />
            {uploading.length > 0
              ? "上传中..."
              : "上传文件"}
          </button>
        </div>
      </header>

      <div className="project-knowledge-summary">
        <div>
          <span>文件</span>
          <strong>{stats.total}</strong>
        </div>
        <div>
          <span>可检索</span>
          <strong>{stats.ready}</strong>
        </div>
        <div>
          <span>待处理</span>
          <strong>{stats.pending}</strong>
        </div>
        <div>
          <span>失败</span>
          <strong>{stats.error}</strong>
        </div>
      </div>

      {feedback && (
        <div
          className={`project-knowledge-feedback ${feedback.type}`}
          role={
            feedback.type === "error"
              ? "alert"
              : "status"
          }
        >
          <span>{feedback.message}</span>
          <button
            type="button"
            onClick={() =>
              setFeedback(null)
            }
            aria-label="关闭提示"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      )}

      {uploading.length > 0 && (
        <div className="project-upload-queue">
          <span className="project-upload-spinner" />
          <div>
            <strong>正在上传</strong>
            <small>
              {uploading.join("、")}
            </small>
          </div>
        </div>
      )}

      {loading ? (
        <div className="project-knowledge-loading">
          正在读取项目知识文件...
        </div>
      ) : files.length === 0 ? (
        <div className="project-knowledge-empty">
          <div className="project-knowledge-empty-icon">
            <Icon name="file" size={21} />
          </div>
          <strong>这个项目还没有知识文件</strong>
          <p>
            支持 PDF、DOCX、TXT、Markdown，单文件最大 20 MB。
          </p>
          <button
            type="button"
            onClick={() =>
              fileInputRef.current?.click()
            }
          >
            上传第一份文件
          </button>
        </div>
      ) : (
        <div className="project-knowledge-table-shell">
          <table className="project-knowledge-table">
            <thead>
              <tr>
                <th>文件</th>
                <th>状态</th>
                <th>内容片段</th>
                <th>大小</th>
                <th>上传时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id}>
                  <td>
                    <div className="knowledge-file-cell">
                      <span className="knowledge-file-icon">
                        <Icon name="file" size={14} />
                      </span>
                      <span>
                        <strong title={file.originalName}>
                          {file.originalName}
                        </strong>
                        <small>
                          .{file.extension}
                          {" · "}
                          SHA256 {file.checksumSha256.slice(0, 10)}…
                        </small>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span
                      className={`knowledge-status ${statusClass(file.status)}`}
                    >
                      {statusLabel(file.status)}
                    </span>
                    {file.errorMessage && (
                      <small className="knowledge-error-message">
                        {file.errorMessage}
                      </small>
                    )}
                  </td>
                  <td>{file.chunkCount}</td>
                  <td>{formatBytes(file.sizeBytes)}</td>
                  <td>{formatDate(file.createdAt)}</td>
                  <td>
                    <div className="knowledge-row-actions">
                      {String(file.status).toUpperCase() !== "INDEXING" && (
                        <button
                          type="button"
                          className="knowledge-reindex-action"
                          disabled={reindexingFileId === file.id}
                          onClick={() =>
                            void reindexFile(file)
                          }
                        >
                          {reindexingFileId === file.id
                            ? "提交中..."
                            : String(file.status).toUpperCase() === "ERROR"
                              ? "重试索引"
                              : "重新索引"}
                        </button>
                      )}

                      <button
                        type="button"
                        className="knowledge-delete-button"
                        onClick={() =>
                          setDeleting(file)
                        }
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ProjectGlobalKnowledgeBindings
        projectId={projectId}
      />

      <div className="project-knowledge-boundary">
        <strong>当前阶段边界</strong>
        <span>
          项目知识已经进入真实 RAG 范围：PROJECT Knowledge + 当前项目显式启用的 GLOBAL Knowledge Base，并按用户与知识库双边界隔离。
        </span>
      </div>

      {deleting && (
        <div
          className="workspace-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget &&
              !deleteBusy
            ) {
              setDeleting(null);
            }
          }}
        >
          <div
            className="workspace-management-dialog"
            role="dialog"
            aria-modal="true"
          >
            <div className="workspace-danger-icon">
              <Icon name="trash" size={18} />
            </div>
            <h2>删除知识文件？</h2>
            <p className="workspace-delete-target">
              {deleting.originalName}
            </p>
            <div className="workspace-delete-note">
              文件元数据和当前对象存储中的原始文件都会删除，删除后不可撤销。
            </div>
            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={deleteBusy}
                onClick={() =>
                  setDeleting(null)
                }
              >
                取消
              </button>
              <button
                type="button"
                className="workspace-danger-button"
                disabled={deleteBusy}
                onClick={() =>
                  void confirmDelete()
                }
              >
                {deleteBusy
                  ? "删除中..."
                  : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
