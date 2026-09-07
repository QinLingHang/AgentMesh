import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  bindProjectGlobalKnowledgeBase,
  listKnowledgeBases,
  listProjectGlobalKnowledgeBindings,
  unbindProjectGlobalKnowledgeBase,
} from "../../api";
import type {
  KnowledgeBase,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";

export function ProjectGlobalKnowledgeBindings({
  projectId,
}: {
  projectId: number;
}) {
  const [
    bases,
    setBases,
  ] =
    useState<KnowledgeBase[]>(
      [],
    );

  const [
    bound,
    setBound,
  ] =
    useState<KnowledgeBase[]>(
      [],
    );

  const [
    loading,
    setLoading,
  ] =
    useState(true);

  const [
    changingId,
    setChangingId,
  ] =
    useState<number | null>(
      null,
    );

  const [
    error,
    setError,
  ] =
    useState("");

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

  const boundIds =
    useMemo(
      () =>
        new Set(
          bound.map(
            (base) =>
              base.id,
          ),
        ),
      [bound],
    );

  const load = async () => {
    try {
      setLoading(true);
      setError("");

      const [
        allBases,
        bindings,
      ] =
        await Promise.all([
          listKnowledgeBases(),
          listProjectGlobalKnowledgeBindings(
            projectId,
          ),
        ]);

      setBases(
        allBases,
      );
      setBound(
        bindings,
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "全局知识绑定加载失败。",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(
    () => {
      void load();
    },
    [projectId],
  );

  const toggle =
    async (
      base: KnowledgeBase,
    ) => {
      const enabled =
        boundIds.has(
          base.id,
        );

      try {
        setChangingId(
          base.id,
        );
        setError("");

        if (enabled) {
          await unbindProjectGlobalKnowledgeBase(
            projectId,
            base.id,
          );
        } else {
          await bindProjectGlobalKnowledgeBase(
            projectId,
            base.id,
          );
        }

        await load();
      } catch (error) {
        setError(
          error instanceof Error
            ? error.message
            : "更新全局知识引用失败。",
        );
      } finally {
        setChangingId(
          null,
        );
      }
    };

  return (
    <section className="project-global-kb-section">
      <header className="project-global-kb-head">
        <div>
          <div className="eyebrow">
            GLOBAL KNOWLEDGE
          </div>

          <h3>
            引用全局知识库
          </h3>

          <p>
            项目专属知识始终只在当前项目使用；
            这里选择额外允许当前项目引用哪些全局知识库。
          </p>
        </div>
      </header>

      {error && (
        <div className="session-feedback">
          {error}
        </div>
      )}

      {loading ? (
        <div className="project-global-kb-loading">
          正在读取全局知识库...
        </div>
      ) : globalBases.length ===
        0 ? (
        <div className="project-global-kb-empty">
          还没有全局知识库。
        </div>
      ) : (
        <div className="project-global-kb-list">
          {globalBases.map(
            (base) => {
              const enabled =
                boundIds.has(
                  base.id,
                );

              return (
                <button
                  type="button"
                  className={
                    `project-global-kb-row ${
                      enabled
                        ? "enabled"
                        : ""
                    }`
                  }
                  key={base.id}
                  disabled={
                    changingId ===
                    base.id
                  }
                  onClick={() =>
                    void toggle(
                      base,
                    )
                  }
                >
                  <span className="project-global-kb-icon">
                    <Icon
                      name="file"
                      size={14}
                    />
                  </span>

                  <span className="project-global-kb-copy">
                    <strong>
                      {base.name}
                    </strong>

                    <small>
                      {base.fileCount}
                      {" "}
                      个文件 ·
                      {" "}
                      {base.readyFileCount}
                      {" "}
                      可检索
                    </small>
                  </span>

                  <span
                    className={
                      `project-global-kb-toggle ${
                        enabled
                          ? "on"
                          : ""
                      }`
                    }
                    aria-hidden="true"
                  >
                    <span />
                  </span>

                  <span className="project-global-kb-state">
                    {changingId ===
                    base.id
                      ? "更新中..."
                      : enabled
                        ? "已启用"
                        : "未启用"}
                  </span>
                </button>
              );
            },
          )}
        </div>
      )}

      <div className="project-global-kb-note">
        <strong>
          最终检索范围
        </strong>

        <span>
          当前项目知识 + 已启用的全局知识库。
          下一阶段 RAG 中，普通非项目会话将默认使用全局知识库。
        </span>
      </div>
    </section>
  );
}
