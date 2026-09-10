import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  createEcosystemPackage,
  createServiceAccount,
  deleteProjectInstallation,
  exportEcosystemPackage,
  friendlyApiError,
  getEcosystemOverview,
  importEcosystemPackage,
  installEcosystemPackage,
  listProjectInstallations,
  listServiceAccounts,
  revokeServiceAccount,
  searchEcosystemPackages,
  setProjectInstallationEnabled,
  validateEcosystemPackage,
} from "../../api";
import { Icon } from "../../components/common/Icon";
import type {
  EcosystemOverview,
  EcosystemPackage,
  EcosystemPackageBundle,
  EcosystemPackageManifest,
  Project,
  ProjectPackageInstallation,
  ServiceAccount,
  ServiceAccountCredential,
} from "../../types";

type EcosystemTab =
  | "marketplace"
  | "installed"
  | "api"
  | "publisher";

type PackageKind =
  | "AGENT"
  | "MCP"
  | "PLUGIN";

const ECOSYSTEM_TABS: readonly EcosystemTab[] = [
  "marketplace",
  "installed",
  "api",
  "publisher",
];

function isEcosystemTab(
  value: string | null,
): value is EcosystemTab {
  return (
    value != null &&
    ECOSYSTEM_TABS.includes(
      value as EcosystemTab,
    )
  );
}

function readEcosystemTabFromLocation(): EcosystemTab {
  const params =
    new URLSearchParams(
      window.location.search,
    );

  const section =
    params.get("section");

  return isEcosystemTab(
    section,
  )
    ? section
    : "marketplace";
}

function writeEcosystemTabToLocation(
  tab: EcosystemTab,
) {
  const url =
    new URL(
      window.location.href,
    );

  url.searchParams.set(
    "page",
    "ecosystem",
  );

  if (
    tab === "marketplace"
  ) {
    url.searchParams.delete(
      "section",
    );
  } else {
    url.searchParams.set(
      "section",
      tab,
    );
  }

  window.history.pushState(
    {
      page: "ecosystem",
      section: tab,
    },
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

const KIND_COPY: Record<
  PackageKind,
  {
    label: string;
    description: string;
  }
> = {
  AGENT: {
    label: "Agent 模板",
    description:
      "可安装到项目资源池的智能体模板。",
  },
  MCP: {
    label: "MCP 连接器",
    description:
      "经过权限声明与端点校验的 MCP Server。",
  },
  PLUGIN: {
    label: "插件",
    description:
      "声明式平台扩展、权限和配置 Schema。",
  },
};

const SERVICE_SCOPES = [
  ["tasks:read", "读取任务"],
  ["tasks:write", "提交任务"],
  ["marketplace:read", "读取生态市场"],
  ["ecosystem:read", "读取生态信息"],
] as const;

function defaultManifest(
  kind: PackageKind,
): EcosystemPackageManifest {
  if (kind === "AGENT") {
    return {
      schemaVersion: "agentmesh.dev/v1",
      kind,
      permissions: [],
      agent: {
        name: "Research Agent",
        description:
          "通过 A2A 接入的研究智能体",
        endpoint:
          "https://agent.example.com/a2a",
        protocol: "a2a",
        capabilities: [
          "general",
          "research",
        ],
        provider: "external",
      },
    };
  }

  if (kind === "MCP") {
    return {
      schemaVersion: "agentmesh.dev/v1",
      kind,
      permissions: [
        "network:outbound",
        "mcp:connect",
      ],
      mcp: {
        name: "Knowledge MCP",
        transport:
          "streamable_http",
        endpoint:
          "https://mcp.example.com/mcp",
        connectTimeoutMs: 5000,
        callTimeoutMs: 10000,
      },
    };
  }

  return {
    schemaVersion: "agentmesh.dev/v1",
    kind,
    permissions: [
      "tools:invoke",
    ],
    plugin: {
      name: "Workflow Plugin",
      description:
        "声明式工作流扩展",
      runtime: "registry",
      entrypoint:
        "workflow.main",
      capabilities: [
        "workflow",
      ],
      configSchema: {
        type: "object",
        properties: {},
      },
    },
  };
}

function packageKindLabel(
  kind: string,
) {
  return (
    KIND_COPY[
      kind as PackageKind
    ]?.label ?? kind
  );
}

function formatDate(
  value?: string | null,
) {
  if (!value) {
    return "—";
  }

  const date =
    new Date(value);

  return Number.isNaN(
    date.getTime(),
  )
    ? value
    : date.toLocaleString(
        "zh-CN",
      );
}

export function Ecosystem({
  projects,
}: {
  projects: Project[];
}) {
  const [
    active,
    setActive,
  ] =
    useState<EcosystemTab>(
      () =>
        readEcosystemTabFromLocation(),
    );

  const [
    selectedProjectId,
    setSelectedProjectId,
  ] = useState<
    number | null
  >(
    projects[0]?.id ??
      null,
  );

  const [
    overview,
    setOverview,
  ] =
    useState<EcosystemOverview | null>(
      null,
    );

  const [
    packages,
    setPackages,
  ] = useState<
    EcosystemPackage[]
  >([]);

  const [
    installations,
    setInstallations,
  ] = useState<
    ProjectPackageInstallation[]
  >([]);

  const [
    serviceAccounts,
    setServiceAccounts,
  ] = useState<
    ServiceAccount[]
  >([]);

  const [
    query,
    setQuery,
  ] =
    useState("");

  const [
    kindFilter,
    setKindFilter,
  ] =
    useState("");

  const [
    busy,
    setBusy,
  ] =
    useState("");

  const [
    notice,
    setNotice,
  ] =
    useState("");

  const [
    error,
    setError,
  ] =
    useState("");

  const importRef =
    useRef<HTMLInputElement>(
      null,
    );

  const [
    accountName,
    setAccountName,
  ] = useState(
    "生产 API",
  );

  const [
    scopes,
    setScopes,
  ] = useState<string[]>([
    "tasks:read",
    "tasks:write",
    "marketplace:read",
  ]);

  const [
    credential,
    setCredential,
  ] =
    useState<ServiceAccountCredential | null>(
      null,
    );

  const [
    publisherKind,
    setPublisherKind,
  ] =
    useState<PackageKind>(
      "AGENT",
    );

  const [
    publisherSlug,
    setPublisherSlug,
  ] = useState(
    "my-agent-template",
  );

  const [
    publisherName,
    setPublisherName,
  ] = useState(
    "我的 Agent 模板",
  );

  const [
    publisherSummary,
    setPublisherSummary,
  ] = useState(
    "一个可复用的 AgentMesh 生态模板",
  );

  const [
    publisherVersion,
    setPublisherVersion,
  ] =
    useState("1.0.0");

  const [
    publisherManifest,
    setPublisherManifest,
  ] = useState(
    JSON.stringify(
      defaultManifest(
        "AGENT",
      ),
      null,
      2,
    ),
  );

  const [
    validationChecksum,
    setValidationChecksum,
  ] =
    useState("");
  useEffect(() => {
    const handlePopState =
      () => {
        setActive(
          readEcosystemTabFromLocation(),
        );
      };

    window.addEventListener(
      "popstate",
      handlePopState,
    );

    return () => {
      window.removeEventListener(
        "popstate",
        handlePopState,
      );
    };
  }, []);

  const navigateToSection = (
    next: EcosystemTab,
  ) => {
    if (
      next === active
    ) {
      return;
    }

    writeEcosystemTabToLocation(
      next,
    );

    setActive(
      next,
    );
  };

  useEffect(() => {
    if (
      projects.length === 0
    ) {
      setSelectedProjectId(
        null,
      );
      return;
    }

    if (
      !selectedProjectId ||
      !projects.some(
        (project) =>
          project.id ===
          selectedProjectId,
      )
    ) {
      setSelectedProjectId(
        projects[0].id,
      );
    }
  }, [
    projects,
    selectedProjectId,
  ]);

  const selectedProject =
    useMemo(
      () =>
        projects.find(
          (project) =>
            project.id ===
            selectedProjectId,
        ) ?? null,
      [
        projects,
        selectedProjectId,
      ],
    );

  const loadMarketplace =
    async () => {
      const [
        nextOverview,
        nextPackages,
      ] =
        await Promise.all([
          getEcosystemOverview(),
          searchEcosystemPackages(
            query,
            kindFilter,
          ),
        ]);

      setOverview(
        nextOverview,
      );

      setPackages(
        nextPackages,
      );
    };

  const loadProject =
    async (
      projectId =
        selectedProjectId,
    ) => {
      if (!projectId) {
        setInstallations(
          [],
        );

        setServiceAccounts(
          [],
        );

        return;
      }

      const [
        nextInstallations,
        nextAccounts,
      ] =
        await Promise.all([
          listProjectInstallations(
            projectId,
          ),
          listServiceAccounts(
            projectId,
          ).catch(
            () =>
              [] as ServiceAccount[],
          ),
        ]);

      setInstallations(
        nextInstallations,
      );

      setServiceAccounts(
        nextAccounts,
      );
    };

  useEffect(() => {
    void loadMarketplace().catch(
      (cause) =>
        setError(
          friendlyApiError(
            cause,
            "加载生态市场失败。",
          ),
        ),
    );

    // Initial marketplace snapshot intentionally does not react to the search form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadProject().catch(
      (cause) =>
        setError(
          friendlyApiError(
            cause,
            "加载项目生态配置失败。",
          ),
        ),
    );

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedProjectId,
  ]);

  const run = async (
    key: string,
    action: () =>
      Promise<void>,
  ) => {
    setBusy(key);
    setError("");
    setNotice("");

    try {
      await action();
    } catch (cause) {
      setError(
        friendlyApiError(
          cause,
          "操作失败，请稍后重试。",
        ),
      );
    } finally {
      setBusy("");
    }
  };

  const handleInstall = (
    item: EcosystemPackage,
  ) => {
    if (
      !selectedProjectId
    ) {
      setError(
        "请先创建或选择一个项目。",
      );
      return;
    }

    void run(
      `install-${item.id}`,
      async () => {
        await installEcosystemPackage(
          selectedProjectId,
          item.slug,
          item.latestVersion ??
            "",
        );

        await Promise.all([
          loadProject(
            selectedProjectId,
          ),
          loadMarketplace(),
        ]);

        setNotice(
          `${item.name} 已安装到「${
            selectedProject?.name ??
            "当前项目"
          }」。`,
        );
      },
    );
  };

  const handleCreateAccount =
    () => {
      if (
        !selectedProjectId
      ) {
        setError(
          "请先选择项目。",
        );
        return;
      }

      void run(
        "create-account",
        async () => {
          const result =
            await createServiceAccount(
              selectedProjectId,
              accountName,
              scopes,
            );

          setCredential(
            result,
          );

          await loadProject(
            selectedProjectId,
          );

          setNotice(
            "服务账号已创建。API Key 只展示这一次，请立即保存。",
          );
        },
      );
    };

  const parsePublisherManifest =
    (): EcosystemPackageManifest => {
      return JSON.parse(
        publisherManifest,
      ) as EcosystemPackageManifest;
    };

  const handleValidate =
    () => {
      void run(
        "validate-package",
        async () => {
          const result =
            await validateEcosystemPackage(
              publisherKind,
              parsePublisherManifest(),
            );

          setValidationChecksum(
            result.checksum,
          );

          setNotice(
            `Manifest 校验通过 · ${result.checksum.slice(
              0,
              16,
            )}…`,
          );
        },
      );
    };

  const handlePublish =
    () => {
      void run(
        "publish-package",
        async () => {
          const manifest =
            parsePublisherManifest();

          await validateEcosystemPackage(
            publisherKind,
            manifest,
          );

          await createEcosystemPackage(
            {
              slug: publisherSlug,
              name: publisherName,
              kind: publisherKind,
              summary:
                publisherSummary,
              description:
                publisherSummary,
              visibility:
                "PUBLIC",
              version:
                publisherVersion,
              manifest,
              publish: true,
            },
          );

          await loadMarketplace();

          setNotice(
            "生态包已通过校验并发布到生态市场。",
          );

          navigateToSection(
            "marketplace",
          );
        },
      );
    };

  const handleExport = (
    item: EcosystemPackage,
  ) => {
    void run(
      `export-${item.id}`,
      async () => {
        const bundle =
          await exportEcosystemPackage(
            item.slug,
            item.latestVersion ??
              "",
          );

        const blob =
          new Blob(
            [
              JSON.stringify(
                bundle,
                null,
                2,
              ),
            ],
            {
              type: "application/json",
            },
          );

        const href =
          URL.createObjectURL(
            blob,
          );

        const anchor =
          document.createElement(
            "a",
          );

        anchor.href =
          href;

        anchor.download = `${
          item.slug
        }-${
          item.latestVersion ||
          "bundle"
        }.agentmesh.json`;

        anchor.click();

        URL.revokeObjectURL(
          href,
        );

        setNotice(
          "可移植生态包已导出。",
        );
      },
    );
  };

  const handleImportFile = (
    file?: File,
  ) => {
    if (!file) {
      return;
    }

    void run(
      "import-package",
      async () => {
        const bundle =
          JSON.parse(
            await file.text(),
          ) as EcosystemPackageBundle;

        await importEcosystemPackage(
          bundle,
        );

        await loadMarketplace();

        setNotice(
          "生态包已导入为你的私有草稿。",
        );

        if (
          importRef.current
        ) {
          importRef.current.value =
            "";
        }
      },
    );
  };

  const projectSelector = (
    <label className="ecosystem-project-select">
      <span>
        目标项目
      </span>

      <select
        aria-label="生态目标项目"
        value={
          selectedProjectId ??
          ""
        }
        onChange={(
          event,
        ) =>
          setSelectedProjectId(
            Number(
              event.target
                .value,
            ) || null,
          )
        }
      >
        {projects.length ===
          0 && (
          <option value="">
            暂无项目
          </option>
        )}

        {projects.map(
          (project) => (
            <option
              key={
                project.id
              }
              value={
                project.id
              }
            >
              {
                project.name
              }
            </option>
          ),
        )}
      </select>
    </label>
  );

  return (
    <div
      className="page calm-page ecosystem-page"
      data-testid="v4-ecosystem-page"
    >
      <header className="calm-page-head ecosystem-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">
            V4 平台生态
          </span>

          <h1>
            生态中心
          </h1>

          <p>
            发布、发现和安装 Agent、MCP
            与插件；同时使用项目级服务账号和官方
            SDK，将 AgentMesh
            接入你的业务系统。
          </p>
        </div>

        {projectSelector}
      </header>

      {error && (
        <div
          className="ecosystem-notice error"
          role="alert"
        >
          {error}
        </div>
      )}

      {notice && (
        <div
          className="ecosystem-notice success"
          role="status"
        >
          {notice}
        </div>
      )}

      <section
        className="ecosystem-metrics"
        aria-label="生态概览"
      >
        <div>
          <span>
            已发布
          </span>

          <strong>
            {overview
              ?.publishedPackages ??
              0}
          </strong>

          <small>
            生态包
          </small>
        </div>

        <div>
          <span>
            Agent
          </span>

          <strong>
            {overview
              ?.agentPackages ??
              0}
          </strong>

          <small>
            可复用智能体
          </small>
        </div>

        <div>
          <span>
            MCP
          </span>

          <strong>
            {overview
              ?.mcpPackages ??
              0}
          </strong>

          <small>
            外部连接器
          </small>
        </div>

        <div>
          <span>
            插件
          </span>

          <strong>
            {overview
              ?.pluginPackages ??
              0}
          </strong>

          <small>
            平台扩展
          </small>
        </div>

        <div>
          <span>
            安装
          </span>

          <strong>
            {overview
              ?.totalInstalls ??
              0}
          </strong>

          <small>
            累计安装次数
          </small>
        </div>
      </section>

      <nav
        className="ecosystem-tabs"
        aria-label="生态中心功能"
      >
        {([
          [
            "marketplace",
            "生态市场",
            "search",
          ],
          [
            "installed",
            "项目已安装",
            "check",
          ],
          [
            "api",
            "API 与 SDK",
            "code",
          ],
          [
            "publisher",
            "发布者中心",
            "sparkles",
          ],
        ] as const).map(
          ([
            id,
            label,
            icon,
          ]) => (
            <button
              key={id}
              className={
                active ===
                id
                  ? "active"
                  : ""
              }
                onClick={() =>
                  navigateToSection(
                    id,
                  )
                }
              type="button"
            >
              <Icon
                name={
                  icon
                }
                size={17}
              />

              <span>
                {label}
              </span>
            </button>
          ),
        )}
      </nav>

      {active ===
        "marketplace" && (
        <section
          className="ecosystem-section"
          data-testid="v4-marketplace"
        >
          <div className="ecosystem-toolbar">
            <div className="ecosystem-search">
              <Icon
                name="search"
                size={16}
              />

              <input
                value={query}
                onChange={(
                  event,
                ) =>
                  setQuery(
                    event
                      .target
                      .value,
                  )
                }
                placeholder="搜索 Agent、MCP、插件..."
              />
            </div>

            <select
              value={
                kindFilter
              }
              onChange={(
                event,
              ) =>
                setKindFilter(
                  event
                    .target
                    .value,
                )
              }
              aria-label="生态包类型"
            >
              <option value="">
                全部类型
              </option>

              <option value="AGENT">
                Agent
              </option>

              <option value="MCP">
                MCP
              </option>

              <option value="PLUGIN">
                插件
              </option>
            </select>

            <button
              type="button"
              className="calm-button"
              onClick={() =>
                void run(
                  "search",
                  loadMarketplace,
                )
              }
              disabled={
                busy ===
                "search"
              }
            >
              搜索
            </button>
          </div>

          <div className="ecosystem-package-grid">
            {packages.length ===
              0 && (
              <div className="ecosystem-empty">
                <Icon
                  name="extensions"
                  size={22}
                />

                <strong>
                  暂无匹配生态包
                </strong>

                <span>
                  你可以在发布者中心创建第一个生态包。
                </span>
              </div>
            )}

            {packages.map(
              (item) => (
                <article
                  className="ecosystem-package-card"
                  key={
                    item.id
                  }
                  data-testid={`marketplace-package-${item.slug}`}
                >
                  <div className="ecosystem-package-top">
                    <span
                      className={`ecosystem-kind kind-${item.kind.toLowerCase()}`}
                    >
                      {packageKindLabel(
                        item.kind,
                      )}
                    </span>

                    <span className="ecosystem-version">
                      {item.latestVersion
                        ? `v${item.latestVersion}`
                        : "草稿"}
                    </span>
                  </div>

                  <h3>
                    {
                      item.name
                    }
                  </h3>

                  <p>
                    {item.summary ||
                      "暂无简介"}
                  </p>

                  <div className="ecosystem-package-meta">
                    <span>
                      {
                        item.slug
                      }
                    </span>

                    <span>
                      {
                        item.installCount
                      }{" "}
                      次安装
                    </span>
                  </div>

                  <div className="ecosystem-card-actions">
                    <button
                      className="calm-button primary"
                      type="button"
                      disabled={
                        !selectedProjectId ||
                        busy ===
                          `install-${item.id}`
                      }
                      onClick={() =>
                        handleInstall(
                          item,
                        )
                      }
                    >
                      安装到项目
                    </button>

                    <button
                      className="calm-button ghost"
                      type="button"
                      onClick={() =>
                        handleExport(
                          item,
                        )
                      }
                      disabled={
                        busy ===
                        `export-${item.id}`
                      }
                    >
                      导出生态包
                    </button>
                  </div>
                </article>
              ),
            )}
          </div>
        </section>
      )}

      {active ===
        "installed" && (
        <section
          className="ecosystem-section"
          data-testid="v4-installations"
        >
          <div className="ecosystem-section-head">
            <div>
              <span className="calm-kicker">
                项目已安装
              </span>

              <h2>
                {selectedProject
                  ?.name ??
                  "当前项目"}
                {" · "}
                已安装生态能力
              </h2>
            </div>

            <span className="calm-status ok">
              <i />

              {
                installations.length
              }{" "}
              项
            </span>
          </div>

          <div className="ecosystem-list">
            {installations.length ===
              0 && (
              <div className="ecosystem-empty">
                <Icon
                  name="extensions"
                  size={22}
                />

                <strong>
                  这个项目还没有安装生态包
                </strong>

                <span>
                  前往生态市场选择一个能力。
                </span>
              </div>
            )}

            {installations.map(
              (item) => (
                <article
                  className="ecosystem-install-row"
                  key={
                    item.id
                  }
                >
                  <div className="ecosystem-install-main">
                    <span
                      className={`ecosystem-kind kind-${item.kind.toLowerCase()}`}
                    >
                      {packageKindLabel(
                        item.kind,
                      )}
                    </span>

                    <div>
                      <strong>
                        {
                          item.packageName
                        }
                      </strong>

                      <small>
                        {
                          item.packageSlug
                        }{" "}
                        · v
                        {
                          item.version
                        }
                      </small>
                    </div>
                  </div>

                  <div className="ecosystem-install-resource">
                    <span>
                      运行资源
                    </span>

                    <strong>
                      {item.resourceType ||
                        "Registry"}

                      {item.resourceId
                        ? ` #${item.resourceId}`
                        : ""}
                    </strong>
                  </div>

                  <span
                    className={`calm-status ${
                      item.enabled
                        ? "ok"
                        : ""
                    }`}
                  >
                    <i />

                    {item.enabled
                      ? "已启用"
                      : "已停用"}
                  </span>

                  <div className="ecosystem-row-actions">
                    <button
                      type="button"
                      className="calm-button"
                      onClick={() =>
                        selectedProjectId &&
                        void run(
                          `toggle-${item.id}`,
                          async () => {
                            await setProjectInstallationEnabled(
                              selectedProjectId,
                              item.id,
                              !item.enabled,
                            );

                            await loadProject(
                              selectedProjectId,
                            );
                          },
                        )
                      }
                    >
                      {item.enabled
                        ? "停用"
                        : "启用"}
                    </button>

                    <button
                      type="button"
                      className="calm-button danger-soft"
                      onClick={() =>
                        selectedProjectId &&
                        void run(
                          `delete-${item.id}`,
                          async () => {
                            await deleteProjectInstallation(
                              selectedProjectId,
                              item.id,
                            );

                            await loadProject(
                              selectedProjectId,
                            );
                          },
                        )
                      }
                    >
                      卸载
                    </button>
                  </div>
                </article>
              ),
            )}
          </div>
        </section>
      )}

      {active ===
        "api" && (
        <section
          className="ecosystem-section ecosystem-api-section"
          data-testid="v4-public-api"
        >
          <div className="ecosystem-section-head">
            <div>
              <span className="calm-kicker">
                公共 API / SDK
              </span>

              <h2>
                项目级机器身份
              </h2>

              <p>
                API Key
                使用哈希存储、项目隔离、Scope
                权限和幂等执行。原始 Key
                只在创建时返回一次。
              </p>
            </div>
          </div>

          <div className="ecosystem-api-grid">
            <div className="ecosystem-form-card">
              <h3>
                创建服务账号
              </h3>

              <label>
                <span>
                  名称
                </span>

                <input
                  value={
                    accountName
                  }
                  onChange={(
                    event,
                  ) =>
                    setAccountName(
                      event
                        .target
                        .value,
                    )
                  }
                />
              </label>

              <fieldset className="ecosystem-scope-grid">
                <legend>
                  API 权限范围
                </legend>

                {SERVICE_SCOPES.map(
                  ([
                    scope,
                    label,
                  ]) => (
                    <label
                      key={
                        scope
                      }
                    >
                      <input
                        type="checkbox"
                        checked={scopes.includes(
                          scope,
                        )}
                        onChange={(
                          event,
                        ) =>
                          setScopes(
                            (
                              items,
                            ) =>
                              event
                                .target
                                .checked
                                ? [
                                    ...new Set(
                                      [
                                        ...items,
                                        scope,
                                      ],
                                    ),
                                  ]
                                : items.filter(
                                    (
                                      item,
                                    ) =>
                                      item !==
                                      scope,
                                  ),
                          )
                        }
                      />

                      <span>
                        <strong>
                          {
                            label
                          }
                        </strong>

                        <small>
                          {
                            scope
                          }
                        </small>
                      </span>
                    </label>
                  ),
                )}
              </fieldset>

              <button
                type="button"
                className="calm-button primary"
                disabled={
                  !selectedProjectId ||
                  busy ===
                    "create-account"
                }
                onClick={
                  handleCreateAccount
                }
              >
                创建 API Key
              </button>
            </div>

            <div className="ecosystem-sdk-card">
              <div className="ecosystem-sdk-head">
                <span className="calm-kicker">
                  官方 SDK
                </span>

                <h3>
                  三行代码提交任务
                </h3>
              </div>

              <pre>
                <code>
                  {`from agentmesh import AgentMeshClient\n\nclient = AgentMeshClient("https://agentmesh.example.com", "${credential?.apiKey ?? "<SERVICE_ACCOUNT_API_KEY>"}")\nrun = client.run_task("分析今天的业务数据")\nprint(run["answer"])`}
                </code>
              </pre>

              <pre>
                <code>
                  {`const client = new AgentMeshClient({ baseUrl: "https://agentmesh.example.com", apiKey: "${credential?.apiKey ?? "<SERVICE_ACCOUNT_API_KEY>"}" });\nconst run = await client.runTask({ task: "分析今天的业务数据" });`}
                </code>
              </pre>
            </div>
          </div>

          {credential && (
            <div
              className="ecosystem-key-reveal"
              role="status"
              data-testid="v4-api-key-reveal"
            >
              <div>
                <strong>
                  请立即保存 API Key
                </strong>

                <span>
                  关闭或刷新页面后，AgentMesh
                  不会再次返回这个明文 Key。
                </span>
              </div>

              <code>
                {
                  credential.apiKey
                }
              </code>
            </div>
          )}

          <div className="ecosystem-list">
            {serviceAccounts.map(
              (account) => (
                <article
                  className="ecosystem-account-row"
                  key={
                    account.id
                  }
                >
                  <div>
                    <strong>
                      {
                        account.name
                      }
                    </strong>

                    <small>
                      {
                        account.keyPrefix
                      }
                      … ·{" "}
                      {account.scopes.join(
                        " · ",
                      )}
                    </small>
                  </div>

                  <div>
                    <span>
                      请求
                    </span>

                    <strong>
                      {
                        account.requestCount
                      }
                    </strong>
                  </div>

                  <div>
                    <span>
                      错误
                    </span>

                    <strong>
                      {
                        account.errorCount
                      }
                    </strong>
                  </div>

                  <div>
                    <span>
                      最近使用
                    </span>

                    <strong>
                      {formatDate(
                        account.lastUsedAt,
                      )}
                    </strong>
                  </div>

                  <span
                    className={`calm-status ${
                      account.status ===
                      "ACTIVE"
                        ? "ok"
                        : ""
                    }`}
                  >
                    <i />

                    {account.status ===
                    "ACTIVE"
                      ? "有效"
                      : "已撤销"}
                  </span>

                  {account.status ===
                    "ACTIVE" && (
                    <button
                      type="button"
                      className="calm-button danger-soft"
                      onClick={() =>
                        selectedProjectId &&
                        void run(
                          `revoke-${account.id}`,
                          async () => {
                            await revokeServiceAccount(
                              selectedProjectId,
                              account.id,
                            );

                            await loadProject(
                              selectedProjectId,
                            );
                          },
                        )
                      }
                    >
                      撤销
                    </button>
                  )}
                </article>
              ),
            )}
          </div>
        </section>
      )}

      {active ===
        "publisher" && (
        <section
          className="ecosystem-section"
          data-testid="v4-publisher"
        >
          <div className="ecosystem-section-head">
            <div>
              <span className="calm-kicker">
                发布者中心
              </span>

              <h2>
                发布 AgentMesh 生态包
              </h2>

              <p>
                每个版本都会经过 Manifest
                规范、权限、端点与敏感字段校验，
                再进入生态市场。
              </p>
            </div>

            <div className="ecosystem-import-action">
              <input
                ref={
                  importRef
                }
                type="file"
                accept="application/json,.json"
                onChange={(
                  event,
                ) =>
                  handleImportFile(
                    event
                      .target
                      .files?.[0],
                  )
                }
              />

              <button
                type="button"
                className="calm-button"
                onClick={() =>
                  importRef.current?.click()
                }
              >
                导入生态包
              </button>
            </div>
          </div>

          <div className="ecosystem-publisher-grid">
            <div className="ecosystem-form-card">
              <label>
                <span>
                  类型
                </span>

                <select
                  value={
                    publisherKind
                  }
                  onChange={(
                    event,
                  ) => {
                    const next =
                      event
                        .target
                        .value as PackageKind;

                    setPublisherKind(
                      next,
                    );

                    setPublisherManifest(
                      JSON.stringify(
                        defaultManifest(
                          next,
                        ),
                        null,
                        2,
                      ),
                    );

                    setValidationChecksum(
                      "",
                    );
                  }}
                >
                  <option value="AGENT">
                    Agent 模板
                  </option>

                  <option value="MCP">
                    MCP 连接器
                  </option>

                  <option value="PLUGIN">
                    插件
                  </option>
                </select>
              </label>

              <label>
                <span>
                  唯一标识（Slug）
                </span>

                <input
                  value={
                    publisherSlug
                  }
                  onChange={(
                    event,
                  ) =>
                    setPublisherSlug(
                      event
                        .target
                        .value,
                    )
                  }
                />
              </label>

              <label>
                <span>
                  名称
                </span>

                <input
                  value={
                    publisherName
                  }
                  onChange={(
                    event,
                  ) =>
                    setPublisherName(
                      event
                        .target
                        .value,
                    )
                  }
                />
              </label>

              <label>
                <span>
                  版本
                </span>

                <input
                  value={
                    publisherVersion
                  }
                  onChange={(
                    event,
                  ) =>
                    setPublisherVersion(
                      event
                        .target
                        .value,
                    )
                  }
                />
              </label>

              <label>
                <span>
                  简介
                </span>

                <textarea
                  rows={3}
                  value={
                    publisherSummary
                  }
                  onChange={(
                    event,
                  ) =>
                    setPublisherSummary(
                      event
                        .target
                        .value,
                    )
                  }
                />
              </label>
            </div>

            <div className="ecosystem-manifest-card">
              <div className="ecosystem-manifest-head">
                <div>
                  <strong>
                    清单（Manifest）
                  </strong>

                  <small>
                    {
                      KIND_COPY[
                        publisherKind
                      ]
                        .description
                    }
                  </small>
                </div>

                {validationChecksum && (
                  <span className="calm-status ok">
                    <i />
                    已校验
                  </span>
                )}
              </div>

              <textarea
                spellCheck={
                  false
                }
                value={
                  publisherManifest
                }
                onChange={(
                  event,
                ) => {
                  setPublisherManifest(
                    event
                      .target
                      .value,
                  );

                  setValidationChecksum(
                    "",
                  );
                }}
              />

              <div className="ecosystem-card-actions">
                <button
                  type="button"
                  className="calm-button"
                  onClick={
                    handleValidate
                  }
                  disabled={
                    busy ===
                    "validate-package"
                  }
                >
                  校验清单
                </button>

                <button
                  type="button"
                  className="calm-button primary"
                  onClick={
                    handlePublish
                  }
                  disabled={
                    busy ===
                    "publish-package"
                  }
                >
                  校验并发布
                </button>
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}