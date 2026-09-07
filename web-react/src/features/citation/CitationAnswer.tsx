import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import type { Message, RuntimeCitation } from "../../types";
import { Icon } from "../../components/common/Icon";

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function normalizeCitation(
  value: unknown,
): RuntimeCitation | null {
  if (!isRecord(value)) {
    return null;
  }

  const citationId = value.citationId;
  const label = value.label;
  const documentId = value.documentId;
  const source = value.source;
  const score = value.score;

  if (
    typeof citationId !== "number" ||
    typeof label !== "string" ||
    typeof documentId !== "string" ||
    typeof source !== "string" ||
    typeof score !== "number"
  ) {
    return null;
  }

  const documentType =
    typeof value.documentType ===
    "string"
      ? value.documentType
      : null;

  const chunkIndex =
    typeof value.chunkIndex ===
    "number"
      ? value.chunkIndex
      : null;

  const start =
    typeof value.start === "number"
      ? value.start
      : null;

  const end =
    typeof value.end === "number"
      ? value.end
      : null;

  return {
    citationId,
    label,
    documentId,
    source,
    score,
    documentType,
    chunkIndex,
    start,
    end,
  };
}

export function extractMessageCitations(
  message: Message,
): RuntimeCitation[] {
  const raw =
    message.metadata?.citations;

  if (!Array.isArray(raw)) {
    return [];
  }

  return raw
    .map(normalizeCitation)
    .filter(
      (item): item is RuntimeCitation =>
        item !== null,
    );
}

function citationMetaText(
  citation: RuntimeCitation,
) {
  const parts: string[] = [];

  if (citation.documentType) {
    parts.push(
      citation.documentType,
    );
  }

  if (
    citation.chunkIndex !== null
  ) {
    parts.push(
      `Chunk ${citation.chunkIndex}`,
    );
  }

  parts.push(
    `Score ${(
      citation.score * 100
    ).toFixed(1)}%`,
  );

  return parts.join(" · ");
}

type MarkdownTreeNode = {
  type?: string;
  value?: unknown;
  children?: unknown[];
};

function rewriteCitationTextNode(
  value: string,
  citationByLabel: Map<
    string,
    RuntimeCitation
  >,
): unknown[] {
  const parts = value.split(
    /(\[\d+\])/g,
  );

  if (parts.length === 1) {
    return [
      {
        type: "text",
        value,
      },
    ];
  }

  return parts
    .filter((part) => part !== "")
    .map((part) => {
      const citation =
        citationByLabel.get(
          part,
        );

      if (!citation) {
        return {
          type: "text",
          value: part,
        };
      }

      return {
        type: "link",
        url: `citation:${citation.citationId}`,
        children: [
          {
            type: "text",
            value: citation.label,
          },
        ],
      };
    });
}

function injectCitationLinks(
  tree: unknown,
  citationByLabel: Map<
    string,
    RuntimeCitation
  >,
) {
  if (!isRecord(tree)) {
    return;
  }

  const node =
    tree as MarkdownTreeNode;

  if (
    node.type === "link" ||
    node.type === "image"
  ) {
    return;
  }

  if (!Array.isArray(node.children)) {
    return;
  }

  const nextChildren: unknown[] = [];

  for (const child of node.children) {
    if (
      isRecord(child) &&
      child.type === "text" &&
      typeof child.value === "string"
    ) {
      nextChildren.push(
        ...rewriteCitationTextNode(
          child.value,
          citationByLabel,
        ),
      );

      continue;
    }

    injectCitationLinks(
      child,
      citationByLabel,
    );

    nextChildren.push(
      child,
    );
  }

  node.children = nextChildren;
}

function createCitationRemarkPlugin(
  citationByLabel: Map<
    string,
    RuntimeCitation
  >,
) {
  return function citationRemarkPlugin() {
    return function transform(
      tree: unknown,
    ) {
      injectCitationLinks(
        tree,
        citationByLabel,
      );
    };
  };
}

export function CitationAnswer({
  content,
  citations,
}: {
  content: string;
  citations: RuntimeCitation[];
}) {
  const [selectedId, setSelectedId] =
    useState<number | null>(
      null,
    );

  const [sourcesExpanded, setSourcesExpanded] =
    useState(false);

  const activeCitationId =
    citations.length === 0
      ? null
      : citations.some(
            (citation) =>
              citation.citationId ===
              selectedId,
          )
        ? selectedId
        : citations[0].citationId;

  const activeCitation =
    citations.find(
      (citation) =>
        citation.citationId ===
        activeCitationId,
    ) ?? citations[0];

  const citationByLabel = useMemo(
    () =>
      new Map(
        citations.map(
          (citation) => [
            citation.label,
            citation,
          ],
        ),
      ),
    [citations],
  );

  const citationById = useMemo(
    () =>
      new Map(
        citations.map(
          (citation) => [
            citation.citationId,
            citation,
          ],
        ),
      ),
    [citations],
  );

  const citationRemarkPlugin =
    useMemo(
      () =>
        createCitationRemarkPlugin(
          citationByLabel,
        ),
      [citationByLabel],
    );

  const markdownComponents =
    useMemo<Components>(
      () => ({
        a({
          href,
          children,
        }) {
          if (
            href?.startsWith(
              "citation:",
            )
          ) {
            const rawId = href.slice(
              "citation:".length,
            );

            const citationId =
              Number(rawId);

            const citation =
              citationById.get(
                citationId,
              );

            if (!citation) {
              return (
                <span>
                  {children}
                </span>
              );
            }

            return (
              <button
                aria-label={`查看引用 ${citation.label}：${citation.source}`}
                aria-pressed={
                  activeCitationId ===
                  citation.citationId
                }
                className={`citation-marker ${
                  activeCitationId ===
                  citation.citationId
                    ? "active"
                    : ""
                }`}
                onClick={() => {
                  setSelectedId(
                    citation.citationId,
                  );

                  setSourcesExpanded(
                    true,
                  );
                }}
                type="button"
              >
                {citation.label}
              </button>
            );
          }

          return (
            <a
              className="markdown-link"
              href={href}
              rel="noreferrer noopener"
              target="_blank"
            >
              {children}
            </a>
          );
        },
      }),
      [
        activeCitationId,
        citationById,
      ],
    );

  const normalizedContent = content.replace(/<br\s*\/?\s*>/gi, "\n");

  return (
    <div className="citation-answer">
      <div className="result-content citation-answer-content markdown-answer">
        <ReactMarkdown
          components={
            markdownComponents
          }
          remarkPlugins={[
            remarkGfm,
            citationRemarkPlugin,
          ]}
          skipHtml
        >
          {normalizedContent}
        </ReactMarkdown>
      </div>

      {citations.length > 0 &&
        activeCitation && (
          <section
            className={`citation-sources citation-sources-compact ${
              sourcesExpanded
                ? "expanded"
                : ""
            }`}
          >
            <button
              aria-expanded={
                sourcesExpanded
              }
              className="citation-source-summary"
              onClick={() =>
                setSourcesExpanded(
                  (value) => !value,
                )
              }
              type="button"
            >
              <span className="citation-summary-label">
                SOURCES
              </span>

              <span className="citation-summary-index">
                {activeCitation.label}
              </span>

              <strong>
                {activeCitation.source}
              </strong>

              <small>
                {(activeCitation.score * 100).toFixed(1)}%
              </small>

              {citations.length > 1 && (
                <span className="citation-summary-count">
                  +{citations.length - 1}
                </span>
              )}

              <span
                className={`citation-summary-chevron ${
                  sourcesExpanded
                    ? "open"
                    : ""
                }`}
              >
                <Icon
                  name="chevron"
                  size={14}
                />
              </span>
            </button>

            {sourcesExpanded && (
              <div className="citation-source-details">
                <div className="citation-source-list">
                  {citations.map(
                    (citation) => (
                      <button
                        className={`citation-source-card ${
                          activeCitationId ===
                          citation.citationId
                            ? "active"
                            : ""
                        }`}
                        key={`${citation.citationId}-${citation.documentId}`}
                        onClick={() =>
                          setSelectedId(
                            citation.citationId,
                          )
                        }
                        type="button"
                      >
                        <span className="citation-source-index">
                          {citation.label}
                        </span>

                        <span className="citation-source-main">
                          <strong>
                            {citation.source}
                          </strong>

                          <small>
                            {citationMetaText(
                              citation,
                            )}
                          </small>

                          <code>
                            {citation.documentId}
                          </code>
                        </span>

                        <span className="citation-source-range">
                          {citation.start !== null &&
                          citation.end !== null
                            ? `${citation.start}–${citation.end}`
                            : ""}
                        </span>
                      </button>
                    ),
                  )}
                </div>

                <p className="citation-note">
                  当前仅展示答案实际使用的来源；完整检索、重排与 Trace 请在运行详情中查看。
                </p>
              </div>
            )}
          </section>
        )}
    </div>
  );
}
