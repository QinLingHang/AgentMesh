import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeBaseFile,
  deleteProjectKnowledgeFile,
  listKnowledgeBases,
  listKnowledgeFiles,
  reindexKnowledgeFile,
  updateKnowledgeBase,
  uploadKnowledgeBaseFile,
  uploadProjectKnowledgeFile,
} from "../../api";
import type {
  KnowledgeBase,
  KnowledgeFile,
  Project,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";
import {
  lightDialogControlStyle,
} from "../../components/common/lightDialogControlStyle";
import {
  formatDate,
} from "../../utils/format";

const MAX_UPLOAD_BYTES =
  20 * 1024 * 1024;

const ALLOWED_EXTENSIONS =
  new Set([
    "pdf",
    "docx",
    "txt",
    "md",
    "markdown",
    "png",
    "jpg",
    "jpeg",
    "webp",
  ]);

type KnowledgeTab =
  | "global"
  | "project"
  | "all";

type StatusFilter =
  | "ALL"
  | "READY"
  | "PENDING"
  | "ERROR";

type Feedback =
  | {
      type:
        | "success"
        | "error";
      message: string;
    }
  | null;

type BaseEditor =
  | {
      mode: "create";
      name: string;
      description: string;
    }
  | {
      mode: "edit";
      base: KnowledgeBase;
      name: string;
      description: string;
    }
  | null;

type UploadTargetType =
  | "GLOBAL"
  | "PROJECT";

function normalizedStatus(
  value: string,
) {
  return String(
    value,
  ).toUpperCase();
}

function isPending(
  file: KnowledgeFile,
) {
  const status =
    normalizedStatus(
      file.status,
    );

  return (
    status !== "READY" &&
    status !== "ERROR"
  );
}

function visualStatusLabel(
  status?: string,
) {
  switch (
    String(status ?? "")
      .trim()
      .toLowerCase()
  ) {
    case "completed":
      return "视觉完成";
    case "partial":
      return "视觉部分完成";
    case "failed":
      return "视觉降级";
    case "disabled":
      return "视觉未启用";
    case "empty":
      return "无视觉证据";
    case "not_applicable":
    case "":
      return "";
    default:
      return `视觉${status}`;
  }
}

function statusLabel(
  value: string,
) {
  switch (
    normalizedStatus(
      value,
    )
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
  value: string,
) {
  switch (
    normalizedStatus(
      value,
    )
  ) {
    case "READY":
      return "ready";

    case "INDEXING":
      return "indexing";

    case "ERROR":
      return "error";

    default:
      return "uploaded";
  }
}

function extensionOf(
  name: string,
) {
  const dot =
    name.lastIndexOf(".");

  if (
    dot < 0 ||
    dot === name.length - 1
  ) {
    return "";
  }

  return name
    .slice(dot + 1)
    .toLowerCase();
}

function validateFile(
  file: File,
) {
  if (
    !ALLOWED_EXTENSIONS.has(
      extensionOf(
        file.name,
      ),
    )
  ) {
    return "暂时只支持 PDF、DOCX、TXT、Markdown、PNG、JPEG、WEBP。";
  }

  if (file.size <= 0) {
    return "不能上传空文件。";
  }

  if (
    file.size >
    MAX_UPLOAD_BYTES
  ) {
    return "单个文件不能超过 20 MB。";
  }

  return "";
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

function friendlyError(
  error: unknown,
) {
  if (
    error instanceof ApiError
  ) {
    if (
      error.status === 413
    ) {
      return "文件超过 20 MB，请选择更小的文件。";
    }

    if (
      error.status === 415
    ) {
      return "暂时只支持 PDF、DOCX、TXT、Markdown、PNG、JPEG、WEBP。";
    }

    if (
      error.status === 409 &&
      error.code === 40921
    ) {
      return "默认知识库不能删除。";
    }

    if (
      error.status >= 500
    ) {
      return "知识库服务暂时不可用，请稍后重试。";
    }

    if (
      error.message.trim()
    ) {
      return error.message;
    }
  }

  return error instanceof Error
    ? error.message
    : "操作失败，请稍后重试。";
}

export function KnowledgeCenter({
  projects,
  onCreateProject,
}: {
  projects: Project[];
  onCreateProject: (
    name: string,
    description: string,
  ) => Promise<Project>;
}) {
  const fileInputRef =
    useRef<HTMLInputElement>(
      null,
    );

  const [tab, setTab] =
    useState<KnowledgeTab>(
      "global",
    );

  const [bases, setBases] =
    useState<KnowledgeBase[]>(
      [],
    );

  const [files, setFiles] =
    useState<KnowledgeFile[]>(
      [],
    );

  const [loading, setLoading] =
    useState(true);

  const [feedback, setFeedback] =
    useState<Feedback>(
      null,
    );

  const [search, setSearch] =
    useState("");

  const [statusFilter, setStatusFilter] =
    useState<StatusFilter>(
      "ALL",
    );

  const [
    selectedGlobalBaseId,
    setSelectedGlobalBaseId,
  ] =
    useState<number | null>(
      null,
    );

  const [
    selectedProjectId,
    setSelectedProjectId,
  ] =
    useState<number | null>(
      null,
    );

  const [baseEditor, setBaseEditor] =
    useState<BaseEditor>(
      null,
    );

  const [baseBusy, setBaseBusy] =
    useState(false);

  const [
    deletingBase,
    setDeletingBase,
  ] =
    useState<KnowledgeBase | null>(
      null,
    );

  const [uploadOpen, setUploadOpen] =
    useState(false);

  const [
    uploadTargetType,
    setUploadTargetType,
  ] =
    useState<UploadTargetType>(
      "GLOBAL",
    );

  const [
    uploadBaseId,
    setUploadBaseId,
  ] =
    useState<number | null>(
      null,
    );

  const [
    uploadProjectId,
    setUploadProjectId,
  ] =
    useState<number | null>(
      null,
    );

  const [
    stagedFiles,
    setStagedFiles,
  ] =
    useState<File[]>([]);

  const [uploading, setUploading] =
    useState(false);

  const [uploadIndex, setUploadIndex] =
    useState(0);

  const [
    deletingFile,
    setDeletingFile,
  ] =
    useState<KnowledgeFile | null>(
      null,
    );

  const [deleteBusy, setDeleteBusy] =
    useState(false);

  const [
    reindexingFileId,
    setReindexingFileId,
  ] = useState<number | null>(null);

  const [
    projectEditorOpen,
    setProjectEditorOpen,
  ] =
    useState(false);

  const [projectName, setProjectName] =
    useState("");

  const [
    projectDescription,
    setProjectDescription,
  ] =
    useState("");

  const [projectBusy, setProjectBusy] =
    useState(false);

  const globalBases =
    useMemo(
      () =>
        bases.filter(
          (base) =>
            base.scope ===
            "GLOBAL",
        ),
      [bases],
    );

  const selectedGlobalBase =
    useMemo(
      () =>
        globalBases.find(
          (base) =>
            base.id ===
            selectedGlobalBaseId,
        ) ??
        globalBases[0] ??
        null,
      [
        globalBases,
        selectedGlobalBaseId,
      ],
    );

  useEffect(
    () => {
      if (
        selectedGlobalBase &&
        selectedGlobalBase.id !==
          selectedGlobalBaseId
      ) {
        setSelectedGlobalBaseId(
          selectedGlobalBase.id,
        );
      }
    },
    [
      selectedGlobalBase,
      selectedGlobalBaseId,
    ],
  );

  useEffect(
    () => {
      if (
        selectedProjectId != null &&
        projects.some(
          (project) =>
            project.id ===
            selectedProjectId,
        )
      ) {
        return;
      }

      setSelectedProjectId(
        projects[0]?.id ??
          null,
      );
    },
    [
      projects,
      selectedProjectId,
    ],
  );

  const load = async (silent = false) => {
    try {
      if (!silent) {
        setLoading(true);
      }

      const [
        nextBases,
        nextFiles,
      ] =
        await Promise.all([
          listKnowledgeBases(),
          listKnowledgeFiles(),
        ]);

      setBases(
        nextBases,
      );
      setFiles(
        nextFiles,
      );
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(
            error,
          ),
      });
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(
    () => {
      void load();
    },
    [],
  );

  const hasPendingFiles = useMemo(
    () => files.some(isPending),
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

      return () =>
        window.clearInterval(timer);
    },
    [hasPendingFiles],
  );

  const summary =
    useMemo(
      () => {
        let global = 0;
        let project = 0;
        let ready = 0;
        let pending = 0;

        for (
          const file
          of files
        ) {
          if (
            file.scope ===
            "GLOBAL"
          ) {
            global += 1;
          } else {
            project += 1;
          }

          if (
            normalizedStatus(
              file.status,
            ) === "READY"
          ) {
            ready += 1;
          } else if (
            normalizedStatus(
              file.status,
            ) !== "ERROR"
          ) {
            pending += 1;
          }
        }

        return {
          total: files.length,
          global,
          project,
          ready,
          pending,
        };
      },
      [files],
    );

  const visibleFiles =
    useMemo(
      () => {
        const query =
          search
            .trim()
            .toLowerCase();

        return files.filter(
          (file) => {
            if (tab === "global") {
              if (!selectedGlobalBase) {
                return false;
              }

              if (
                file.knowledgeBaseId !==
                selectedGlobalBase.id
              ) {
                return false;
              }
            }

            if (tab === "project") {
              if (
                selectedProjectId == null
              ) {
                return false;
              }

              if (
                file.scope !==
                  "PROJECT" ||
                file.projectId !==
                  selectedProjectId
              ) {
                return false;
              }
            }

            if (
              statusFilter ===
                "READY" &&
              normalizedStatus(
                file.status,
              ) !== "READY"
            ) {
              return false;
            }

            if (
              statusFilter ===
                "ERROR" &&
              normalizedStatus(
                file.status,
              ) !== "ERROR"
            ) {
              return false;
            }

            if (
              statusFilter ===
                "PENDING" &&
              !isPending(
                file,
              )
            ) {
              return false;
            }

            if (!query) {
              return true;
            }

            return [
              file.originalName,
              file.knowledgeBaseName,
              file.projectName ?? "",
            ].some(
              (value) =>
                value
                  .toLowerCase()
                  .includes(
                    query,
                  ),
            );
          },
        );
      },
      [
        files,
        search,
        selectedGlobalBase,
        selectedProjectId,
        statusFilter,
        tab,
      ],
    );

  const projectStats =
    useMemo(
      () =>
        projects.map(
          (project) => {
            const projectFiles =
              files.filter(
                (file) =>
                  file.scope ===
                    "PROJECT" &&
                  file.projectId ===
                    project.id,
              );

            return {
              project,
              fileCount:
                projectFiles.length,
              readyCount:
                projectFiles.filter(
                  (file) =>
                    normalizedStatus(
                      file.status,
                    ) ===
                    "READY",
                ).length,
              pendingCount:
                projectFiles.filter(
                  isPending,
                ).length,
            };
          },
        ),
      [
        files,
        projects,
      ],
    );

  const openUpload = () => {
    setFeedback(null);
    setStagedFiles([]);
    setUploadIndex(0);

    if (
      tab === "project"
    ) {
      if (
        projects.length === 0
      ) {
        setProjectEditorOpen(
          true,
        );
        return;
      }

      setUploadTargetType(
        "PROJECT",
      );
      setUploadProjectId(
        selectedProjectId ??
          projects[0].id,
      );
    } else {
      setUploadTargetType(
        "GLOBAL",
      );
      setUploadBaseId(
        selectedGlobalBase?.id ??
          globalBases[0]?.id ??
          null,
      );
    }

    setUploadOpen(
      true,
    );
  };

  const chooseFiles = (
    selected: FileList | null,
  ) => {
    if (
      !selected ||
      selected.length === 0
    ) {
      return;
    }

    const candidates =
      Array.from(
        selected,
      );

    const error =
      candidates
        .map(
          validateFile,
        )
        .find(Boolean);

    if (error) {
      setFeedback({
        type: "error",
        message: error,
      });
      return;
    }

    setStagedFiles(
      candidates,
    );
  };

  const upload = async () => {
    if (
      stagedFiles.length === 0
    ) {
      setFeedback({
        type: "error",
        message:
          "请选择要上传的文件。",
      });
      return;
    }

    if (
      uploadTargetType ===
        "GLOBAL" &&
      uploadBaseId == null
    ) {
      setFeedback({
        type: "error",
        message:
          "请选择全局知识库。",
      });
      return;
    }

    if (
      uploadTargetType ===
        "PROJECT" &&
      uploadProjectId == null
    ) {
      setFeedback({
        type: "error",
        message:
          "请选择项目。",
      });
      return;
    }

    try {
      setUploading(true);
      setFeedback(null);

      for (
        let index = 0;
        index <
        stagedFiles.length;
        index += 1
      ) {
        setUploadIndex(
          index + 1,
        );

        const file =
          stagedFiles[index];

        if (
          uploadTargetType ===
          "GLOBAL"
        ) {
          await uploadKnowledgeBaseFile(
            uploadBaseId as number,
            file,
          );
        } else {
          await uploadProjectKnowledgeFile(
            uploadProjectId as number,
            file,
          );
        }
      }

      await load();

      setUploadOpen(false);
      setStagedFiles([]);

      setFeedback({
        type: "success",
        message:
          `${stagedFiles.length} 个文件已上传，系统正在自动解析并建立索引。`,
      });
    } catch (error) {
      await load();

      setFeedback({
        type: "error",
        message:
          friendlyError(
            error,
          ),
      });
    } finally {
      setUploading(false);
      setUploadIndex(0);

      if (
        fileInputRef.current
      ) {
        fileInputRef.current.value =
          "";
      }
    }
  };

  const saveBase = async () => {
    if (!baseEditor) {
      return;
    }

    const name =
      baseEditor.name.trim();

    if (!name) {
      setFeedback({
        type: "error",
        message:
          "知识库名称不能为空。",
      });
      return;
    }

    try {
      setBaseBusy(true);
      setFeedback(null);

      const saved =
        baseEditor.mode ===
        "create"
          ? await createKnowledgeBase(
              name,
              baseEditor.description.trim(),
              "GLOBAL",
            )
          : await updateKnowledgeBase(
              baseEditor.base.id,
              name,
              baseEditor.description.trim(),
            );

      await load();

      setSelectedGlobalBaseId(
        saved.id,
      );
      setTab("global");
      setBaseEditor(null);

      setFeedback({
        type: "success",
        message:
          baseEditor.mode ===
          "create"
            ? "全局知识库已创建。"
            : "知识库信息已更新。",
      });
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(
            error,
          ),
      });
    } finally {
      setBaseBusy(false);
    }
  };

  const confirmDeleteBase =
    async () => {
      if (!deletingBase) {
        return;
      }

      try {
        setDeleteBusy(true);
        setFeedback(null);

        await deleteKnowledgeBase(
          deletingBase.id,
        );

        await load();

        setDeletingBase(null);
        setSelectedGlobalBaseId(
          null,
        );

        setFeedback({
          type: "success",
          message:
            "全局知识库及其中的文件已删除。",
        });
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            friendlyError(
              error,
            ),
        });
      } finally {
        setDeleteBusy(false);
      }
    };

  const reindexFile = async (
    file: KnowledgeFile,
  ) => {
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
        message: friendlyError(error),
      });
    } finally {
      setReindexingFileId(null);
    }
  };

  const confirmDeleteFile =
    async () => {
      if (!deletingFile) {
        return;
      }

      try {
        setDeleteBusy(true);
        setFeedback(null);

        if (
          deletingFile.scope ===
          "GLOBAL"
        ) {
          await deleteKnowledgeBaseFile(
            deletingFile.knowledgeBaseId,
            deletingFile.id,
          );
        } else if (
          deletingFile.projectId !=
          null
        ) {
          await deleteProjectKnowledgeFile(
            deletingFile.projectId,
            deletingFile.id,
          );
        }

        await load();
        setDeletingFile(null);

        setFeedback({
          type: "success",
          message:
            "知识文件已删除。",
        });
      } catch (error) {
        setFeedback({
          type: "error",
          message:
            friendlyError(
              error,
            ),
        });
      } finally {
        setDeleteBusy(false);
      }
    };

  const createProject = async () => {
    const name =
      projectName.trim();

    if (!name) {
      setFeedback({
        type: "error",
        message:
          "项目名称不能为空。",
      });
      return;
    }

    try {
      setProjectBusy(true);
      setFeedback(null);

      const project =
        await onCreateProject(
          name,
          projectDescription.trim(),
        );

      setProjectEditorOpen(false);
      setProjectName("");
      setProjectDescription("");
      setSelectedProjectId(
        project.id,
      );
      setTab("project");
      setUploadTargetType(
        "PROJECT",
      );
      setUploadProjectId(
        project.id,
      );
      setUploadOpen(true);
    } catch (error) {
      setFeedback({
        type: "error",
        message:
          friendlyError(
            error,
          ),
      });
    } finally {
      setProjectBusy(false);
    }
  };

  const tableTitle =
    tab === "global"
      ? selectedGlobalBase?.name ??
        "全局知识库"
      : tab === "project"
        ? projects.find(
            (project) =>
              project.id ===
              selectedProjectId,
          )?.name ??
          "项目知识"
        : "全部文件";

  return (
    <div className="page knowledge-center calm-page knowledge-calm-page">
      <header className="page-head knowledge-page-head">
        <div>
          <div className="calm-kicker">知识中心</div>

          <h1>知识库</h1>

          <p>把常用资料交给 AgentMesh。全局知识可跨会话使用，项目知识只服务当前项目。</p>
        </div>

        <button
          type="button"
          className="primary-button knowledge-primary-action"
          onClick={openUpload}
        >
          <Icon
            name="plus"
            size={14}
          />

          上传知识
        </button>
      </header>

      {feedback && (
        <div
          className={
            `knowledge-feedback ${feedback.type}`
          }
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
              size={14}
            />
          </button>
        </div>
      )}

      <section className="knowledge-summary-grid">
        <article>
          <span>
            全部文件
          </span>
          <strong>
            {summary.total}
          </strong>
          <small>已加入的资料</small>
        </article>

        <article>
          <span>
            全局知识
          </span>
          <strong>
            {summary.global}
          </strong>
          <small>可在普通会话使用</small>
        </article>

        <article>
          <span>
            项目知识
          </span>
          <strong>
            {summary.project}
          </strong>
          <small>仅当前项目可用</small>
        </article>

        <article>
          <span>
            待索引
          </span>
          <strong>
            {summary.pending}
          </strong>
          <small>正在准备可检索内容</small>
        </article>
      </section>

      <div className="knowledge-scope-tabs">
        <button
          type="button"
          className={
            tab === "global"
              ? "active"
              : ""
          }
          onClick={() =>
            setTab("global")
          }
        >
          全局知识库
        </button>

        <button
          type="button"
          className={
            tab === "project"
              ? "active"
              : ""
          }
          onClick={() =>
            setTab("project")
          }
        >
          项目知识
        </button>

        <button
          type="button"
          className={
            tab === "all"
              ? "active"
              : ""
          }
          onClick={() =>
            setTab("all")
          }
        >
          全部文件
        </button>
      </div>

      {tab === "global" && (
        <section className="knowledge-scope-section">
          <header className="knowledge-scope-head">
            <div>
              <h2>
                全局知识库
              </h2>

              <p>普通会话可以直接使用；项目也可以按需引用这些资料。</p>
            </div>

            <button
              type="button"
              className="knowledge-text-action"
              onClick={() =>
                setBaseEditor({
                  mode: "create",
                  name: "",
                  description: "",
                })
              }
            >
              <Icon
                name="plus"
                size={13}
              />

              新建全局知识库
            </button>
          </header>

          <div className="knowledge-base-grid">
            {globalBases.map(
              (base) => (
                <div
                  className={
                    `knowledge-base-card ${
                      selectedGlobalBase?.id ===
                      base.id
                        ? "selected"
                        : ""
                    }`
                  }
                  key={base.id}
                >
                  <button
                    type="button"
                    className="knowledge-base-main"
                    onClick={() =>
                      setSelectedGlobalBaseId(
                        base.id,
                      )
                    }
                  >
                    <span className="knowledge-base-icon">
                      <Icon
                        name="file"
                        size={16}
                      />
                    </span>

                    <span className="knowledge-base-copy">
                      <span>
                        {base.name}

                        {base.isDefault && (
                          <em>
                            默认
                          </em>
                        )}
                      </span>

                      <strong>
                        {base.fileCount}
                        {" "}
                        个文件
                      </strong>

                      <small>
                        {base.readyFileCount}
                        {" "}
                        可检索 ·
                        {" "}
                        {base.pendingFileCount}
                        {" "}
                        待处理
                      </small>
                    </span>
                  </button>

                  <div className="knowledge-base-actions">
                    <button
                      type="button"
                      onClick={() =>
                        setBaseEditor({
                          mode: "edit",
                          base,
                          name: base.name,
                          description:
                            base.description,
                        })
                      }
                    >
                      编辑
                    </button>

                    {!base.isDefault && (
                      <button
                        type="button"
                        className="danger"
                        onClick={() =>
                          setDeletingBase(
                            base,
                          )
                        }
                      >
                        删除
                      </button>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        </section>
      )}

      {tab === "project" && (
        <section className="knowledge-scope-section">
          <header className="knowledge-scope-head">
            <div>
              <h2>
                项目知识
              </h2>

              <p>只服务当前项目，不会自动进入其他项目或普通会话。</p>
            </div>

            <button
              type="button"
              className="knowledge-text-action"
              onClick={() =>
                setProjectEditorOpen(
                  true,
                )
              }
            >
              <Icon
                name="plus"
                size={13}
              />

              新建项目
            </button>
          </header>

          {projects.length === 0 ? (
            <div className="knowledge-no-project">
              <div>
                <Icon
                  name="workspace"
                  size={21}
                />
              </div>

              <strong>
                还没有项目
              </strong>

              <p>
                创建项目后即可上传项目专属知识。
              </p>

              <button
                type="button"
                onClick={() =>
                  setProjectEditorOpen(
                    true,
                  )
                }
              >
                创建第一个项目
              </button>
            </div>
          ) : (
            <div className="knowledge-project-grid">
              {projectStats.map(
                (item) => (
                  <button
                    type="button"
                    className={
                      `knowledge-project-card ${
                        selectedProjectId ===
                        item.project.id
                          ? "selected"
                          : ""
                      }`
                    }
                    key={
                      item.project.id
                    }
                    onClick={() =>
                      setSelectedProjectId(
                        item.project.id,
                      )
                    }
                  >
                    <span className="knowledge-project-icon">
                      <Icon
                        name="workspace"
                        size={15}
                      />
                    </span>

                    <span className="knowledge-project-copy">
                      <strong>
                        {item.project.name}
                      </strong>

                      <small>
                        {item.fileCount}
                        {" "}
                        个文件 ·
                        {" "}
                        {item.readyCount}
                        {" "}
                        可检索
                      </small>
                    </span>

                    <span className="knowledge-project-pending">
                      {item.pendingCount > 0
                        ? `${item.pendingCount} 待处理`
                        : "已同步"}
                    </span>
                  </button>
                ),
              )}
            </div>
          )}
        </section>
      )}

      <section className="knowledge-library-section">
        <header className="knowledge-library-head">
          <div>
            <h2>
              {tableTitle}
            </h2>

            <p>
              {tab === "global"
                ? "当前全局知识库中的文件。"
                : tab === "project"
                  ? "当前项目专属知识文件。"
                  : "跨全局与项目范围查看全部知识文件。"}
            </p>
          </div>

          <div className="knowledge-library-count">
            {visibleFiles.length}
            {" / "}
            {files.length}
          </div>
        </header>

        <div className="knowledge-toolbar compact">
          <label className="knowledge-search">
            <Icon
              name="search"
              size={15}
            />

            <input
              value={search}
              placeholder="搜索文件、知识库或项目..."
              onChange={(event) =>
                setSearch(
                  event.target.value,
                )
              }
            />
          </label>

          <select
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(
                event.target
                  .value as StatusFilter,
              )
            }
          >
            <option value="ALL">
              全部状态
            </option>
            <option value="READY">
              可检索
            </option>
            <option value="PENDING">
              待处理
            </option>
            <option value="ERROR">
              失败
            </option>
          </select>
        </div>

        {loading ? (
          <div className="knowledge-center-loading">
            正在读取知识资产...
          </div>
        ) : visibleFiles.length === 0 ? (
          <div className="knowledge-center-empty compact">
            <strong>
              当前范围还没有知识文件
            </strong>

            <p>
              上传文件后，它会保存在对应的全局知识库或项目知识库中。
            </p>

            <button
              type="button"
              onClick={openUpload}
            >
              上传知识
            </button>
          </div>
        ) : (
          <div className="knowledge-center-table-shell">
            <table className="knowledge-center-table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>范围</th>
                  <th>知识库 / 项目</th>
                  <th>状态</th>
                  <th>大小</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>

              <tbody>
                {visibleFiles.map(
                  (file) => (
                    <tr key={file.id}>
                      <td>
                        <div className="knowledge-center-file">
                          <span>
                            <Icon
                              name="file"
                              size={14}
                            />
                          </span>

                          <div>
                            <strong
                              title={
                                file.originalName
                              }
                            >
                              {file.originalName}
                            </strong>

                            <small>.{file.extension}</small>

                              <small className="knowledge-v2-evidence-summary">
                                {`文本 ${file.textChunkCount ?? file.chunkCount ?? 0} 段`}
                                {` · 图片 ${file.visualEvidenceCount ?? 0} 张`}
                                {(file.pageCount ?? 0) > 0
                                  ? ` · ${file.pageCount} 页`
                                  : ""}
                                {visualStatusLabel(file.visualStatus)
                                  ? ` · ${visualStatusLabel(file.visualStatus)}`
                                  : ""}
                                {file.visualErrorMessage
                                  ? " · 图片内容暂未解析"
                                  : ""}
                              </small>
                          </div>
                        </div>
                      </td>

                      <td>
                        <span
                          className={
                            `knowledge-scope-badge ${
                              file.scope ===
                              "GLOBAL"
                                ? "global"
                                : "project"
                            }`
                          }
                        >
                          {file.scope ===
                          "GLOBAL"
                            ? "全局"
                            : "项目"}
                        </span>
                      </td>

                      <td>
                        <strong className="knowledge-location-title">
                          {file.knowledgeBaseName}
                        </strong>

                        {file.projectName && (
                          <small className="knowledge-location-subtitle">
                            {file.projectName}
                          </small>
                        )}
                      </td>

                      <td>
                        <span
                          className={
                            `knowledge-status ${statusClass(
                              file.status,
                            )}`
                          }
                        >
                          {statusLabel(
                            file.status,
                          )}
                        </span>

                        {file.errorMessage && (
                          <small className="knowledge-center-error">
                            {file.errorMessage}
                          </small>
                        )}
                      </td>

                      <td>
                        {formatBytes(
                          file.sizeBytes,
                        )}
                      </td>

                      <td>
                        {formatDate(
                          file.updatedAt,
                        )}
                      </td>

                      <td>
                        <div className="knowledge-row-actions">
                          {normalizedStatus(file.status) !== "INDEXING" && (
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
                                : normalizedStatus(file.status) === "ERROR"
                                  ? "重试索引"
                                  : "重新索引"}
                            </button>
                          )}

                          <button
                            type="button"
                            className="knowledge-delete-action"
                            onClick={() =>
                              setDeletingFile(
                                file,
                              )
                            }
                          >
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="knowledge-roadmap-note calm-privacy-note">
        <Icon name="shield" size={14} />
        <span>知识范围会自动按会话与项目边界隔离，你无需手动处理检索细节。</span>
      </div>

      {uploadOpen && (
        <div className="workspace-dialog-backdrop">
          <div className="workspace-management-dialog knowledge-upload-dialog">
            <h2>
              上传知识
            </h2>

            <p className="knowledge-dialog-intro">
              选择知识范围和目标容器。
            </p>

            <div className="knowledge-upload-target-tabs">
              <button
                type="button"
                className={
                  uploadTargetType ===
                  "GLOBAL"
                    ? "active"
                    : ""
                }
                onClick={() =>
                  setUploadTargetType(
                    "GLOBAL",
                  )
                }
              >
                全局知识
              </button>

              <button
                type="button"
                className={
                  uploadTargetType ===
                  "PROJECT"
                    ? "active"
                    : ""
                }
                disabled={
                  projects.length === 0
                }
                onClick={() =>
                  setUploadTargetType(
                    "PROJECT",
                  )
                }
              >
                项目知识
              </button>
            </div>

            {uploadTargetType ===
            "GLOBAL" ? (
              <label className="field">
                <span>
                  全局知识库
                </span>

                <select
                  value={
                    uploadBaseId ??
                    ""
                  }
                  disabled={uploading}
                  onChange={(event) =>
                    setUploadBaseId(
                      Number(
                        event.target.value,
                      ),
                    )
                  }
                >
                  {globalBases.map(
                    (base) => (
                      <option
                        key={base.id}
                        value={base.id}
                      >
                        {base.name}
                      </option>
                    ),
                  )}
                </select>
              </label>
            ) : (
              <label className="field">
                <span>
                  所属项目
                </span>

                <select
                  value={
                    uploadProjectId ??
                    ""
                  }
                  disabled={uploading}
                  onChange={(event) =>
                    setUploadProjectId(
                      Number(
                        event.target.value,
                      ),
                    )
                  }
                >
                  {projects.map(
                    (project) => (
                      <option
                        key={project.id}
                        value={project.id}
                      >
                        {project.name}
                      </option>
                    ),
                  )}
                </select>
              </label>
            )}

            <input
              ref={fileInputRef}
              className="project-file-input"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp"
              disabled={uploading}
              onChange={(event) =>
                chooseFiles(
                  event.target.files,
                )
              }
            />

            <button
              type="button"
              className="knowledge-file-picker"
              disabled={uploading}
              onClick={() =>
                fileInputRef.current?.click()
              }
            >
              <span>
                <Icon
                  name="file"
                  size={19}
                />
              </span>

              <strong>
                {stagedFiles.length > 0
                  ? `已选择 ${stagedFiles.length} 个文件`
                  : "选择文件"}
              </strong>

              <small>
                PDF / DOCX / TXT / Markdown · 单文件最大 20 MB
              </small>
            </button>

            {stagedFiles.length > 0 && (
              <div className="knowledge-staged-files">
                {stagedFiles.map(
                  (file) => (
                    <div
                      key={`${file.name}-${file.size}-${file.lastModified}`}
                    >
                      <span>
                        {file.name}
                      </span>
                      <small>
                        {formatBytes(
                          file.size,
                        )}
                      </small>
                    </div>
                  ),
                )}
              </div>
            )}

            {uploading && (
              <div className="knowledge-upload-progress">
                <span className="project-upload-spinner" />
                正在上传 {uploadIndex} / {stagedFiles.length}
              </div>
            )}

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={uploading}
                onClick={() =>
                  setUploadOpen(false)
                }
              >
                取消
              </button>

              <button
                type="button"
                className="primary-button"
                disabled={
                  uploading ||
                  stagedFiles.length === 0 ||
                  (uploadTargetType ===
                    "GLOBAL"
                    ? uploadBaseId == null
                    : uploadProjectId == null)
                }
                onClick={() =>
                  void upload()
                }
              >
                {uploading
                  ? "上传中..."
                  : "开始上传"}
              </button>
            </div>
          </div>
        </div>
      )}

      {baseEditor && (
        <div className="workspace-dialog-backdrop">
          <form
            className="workspace-management-dialog"
            onSubmit={(event) => {
              event.preventDefault();
              void saveBase();
            }}
          >
            <h2>
              {baseEditor.mode ===
              "create"
                ? "新建全局知识库"
                : "编辑全局知识库"}
            </h2>

            <label className="field">
              <span>
                名称
              </span>

              <input
                autoFocus
                style={lightDialogControlStyle}
                value={baseEditor.name}
                maxLength={80}
                disabled={baseBusy}
                placeholder="例如：通用研发知识"
                onChange={(event) =>
                  setBaseEditor({
                    ...baseEditor,
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
                style={lightDialogControlStyle}
                value={
                  baseEditor.description
                }
                maxLength={240}
                rows={3}
                disabled={baseBusy}
                onChange={(event) =>
                  setBaseEditor({
                    ...baseEditor,
                    description:
                      event.target.value,
                  })
                }
              />
            </label>

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={baseBusy}
                onClick={() =>
                  setBaseEditor(null)
                }
              >
                取消
              </button>

              <button
                type="submit"
                className="primary-button"
                disabled={
                  baseBusy ||
                  !baseEditor.name.trim()
                }
              >
                {baseBusy
                  ? "保存中..."
                  : "保存"}
              </button>
            </div>
          </form>
        </div>
      )}

      {projectEditorOpen && (
        <div className="workspace-dialog-backdrop">
          <form
            className="workspace-management-dialog"
            onSubmit={(event) => {
              event.preventDefault();
              void createProject();
            }}
          >
            <h2>
              新建项目
            </h2>

            <p className="knowledge-dialog-intro">
              项目知识只属于这个 Project；之后可以再引用全局知识库。
            </p>

            <label className="field">
              <span>
                项目名称
              </span>

              <input
                autoFocus
                style={lightDialogControlStyle}
                value={projectName}
                maxLength={80}
                disabled={projectBusy}
                placeholder="例如：AgentMesh 开发"
                onChange={(event) =>
                  setProjectName(
                    event.target.value,
                  )
                }
              />
            </label>

            <label className="field">
              <span>
                描述（可选）
              </span>

              <textarea
                style={lightDialogControlStyle}
                value={projectDescription}
                maxLength={240}
                rows={3}
                disabled={projectBusy}
                onChange={(event) =>
                  setProjectDescription(
                    event.target.value,
                  )
                }
              />
            </label>

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={projectBusy}
                onClick={() =>
                  setProjectEditorOpen(
                    false,
                  )
                }
              >
                取消
              </button>

              <button
                type="submit"
                className="primary-button"
                disabled={
                  projectBusy ||
                  !projectName.trim()
                }
              >
                {projectBusy
                  ? "创建中..."
                  : "创建并上传"}
              </button>
            </div>
          </form>
        </div>
      )}

      {deletingBase && (
        <div className="workspace-dialog-backdrop">
          <div className="workspace-management-dialog">
            <div className="workspace-danger-icon">
              <Icon
                name="trash"
                size={18}
              />
            </div>

            <h2>
              删除全局知识库？
            </h2>

            <p className="workspace-delete-target">
              {deletingBase.name}
            </p>

            <div className="workspace-delete-note">
              其中的原始文件也会一并删除，所有 Project 对它的引用都会失效。此操作不可撤销。
            </div>

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={deleteBusy}
                onClick={() =>
                  setDeletingBase(null)
                }
              >
                取消
              </button>

              <button
                type="button"
                className="workspace-danger-button"
                disabled={deleteBusy}
                onClick={() =>
                  void confirmDeleteBase()
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

      {deletingFile && (
        <div className="workspace-dialog-backdrop">
          <div className="workspace-management-dialog">
            <div className="workspace-danger-icon">
              <Icon
                name="trash"
                size={18}
              />
            </div>

            <h2>
              删除知识文件？
            </h2>

            <p className="workspace-delete-target">
              {deletingFile.originalName}
            </p>

            <div className="workspace-delete-note">
              文件元数据和对象存储中的原始文件都会删除。删除后不可撤销。
            </div>

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={deleteBusy}
                onClick={() =>
                  setDeletingFile(null)
                }
              >
                取消
              </button>

              <button
                type="button"
                className="workspace-danger-button"
                disabled={deleteBusy}
                onClick={() =>
                  void confirmDeleteFile()
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
    </div>
  );
}
