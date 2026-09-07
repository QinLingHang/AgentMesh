import { useEffect, useMemo, useState } from "react";
import type { Message, MessageAttachmentMetadata, RunResult, Task } from "../../types";
import { isWaitingStatus } from "../../components/common/RuntimeStatusBadge";
import { CitationAnswer, extractMessageCitations } from "../citation/CitationAnswer";
import { LatestRunMeta } from "./LatestRunMeta";
import { reconstructHistoricalRun } from "./historicalRun";
import { WorkspaceWelcome } from "./WorkspaceWelcome";
import { formatAttachmentSize, messageAttachmentList } from "./AttachmentStrip";

function WorkingAnswer({ label }: { label: string }) {
  const steps = useMemo(() => ["正在理解你的目标", "正在整理所需信息", "正在协调相关能力", "正在生成回答"], []);
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const stepTimer = window.setInterval(() => setIndex((value) => (value + 1) % steps.length), 1600);
    const elapsedTimer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => {
      window.clearInterval(stepTimer);
      window.clearInterval(elapsedTimer);
    };
  }, [steps]);

  return (
    <article className="agent-result agent-result-working" data-testid="assistant-working-state">
      <header>
        <div>
          <span className="result-mark">AM</span>
          <div>
            <strong>AgentMesh</strong>
            <small>{label}</small>
          </div>
        </div>
        <span className="result-state-pill running"><i />处理中 · {elapsed}s</span>
      </header>
      <div className="working-answer-body">
        <div className="working-dots"><i /><i /><i /></div>
        <span>{steps[index]}…</span>
        <small>你可以继续停留在当前页面，结果会自动出现。</small>
      </div>
    </article>
  );
}

function AttachmentChips({ items }: { items: MessageAttachmentMetadata[] }) {
  if (!items.length) return null;
  return (
    <div className="message-attachment-list">
      {items.map((item) => (
        <span className="message-attachment-chip" key={item.id}>
          <span className={item.mediaType?.startsWith("image/") ? "attachment-kind image" : "attachment-kind file"}>
            {item.mediaType?.startsWith("image/") ? "IMG" : "FILE"}
          </span>
          <span className="message-attachment-name" title={item.name}>{item.name}</span>
          <small>{formatAttachmentSize(item.sizeBytes ?? 0)}</small>
        </span>
      ))}
    </div>
  );
}

export function MessageHistory({
  messages,
  tasks,
  latestRun,
  openDetails,
  onSelectPrompt,
  working = false,
  pendingPrompt = "",
  pendingAttachments = [],
  streamingAnswer = "",
  streamingPhase = "",
}: {
  messages: Message[];
  tasks: Task[];
  latestRun: RunResult | null;
  openDetails: (result: RunResult) => void;
  onSelectPrompt: (prompt: string) => void;
  working?: boolean;
  pendingPrompt?: string;
  pendingAttachments?: MessageAttachmentMetadata[];
  streamingAnswer?: string;
  streamingPhase?: string;
}) {
  const lastAssistantId = [...messages].reverse().find((message) => message.role === "assistant")?.id;

  if (messages.length === 0 && !working && !pendingPrompt) {
    return <WorkspaceWelcome onSelect={onSelectPrompt} />;
  }

  return (
    <div className="conversation-flow">
      {messages.slice(-20).map((message) => {
        if (message.role === "user") {
          return (
            <div className="user-message-row" key={message.id}>
              <div>
                <span className="message-label">你</span>
                <div className="user-message">{message.content}</div>
                <AttachmentChips items={messageAttachmentList(message.metadata)} />
              </div>
            </div>
          );
        }

        const isLatest = message.id === lastAssistantId && latestRun !== null;
        const historicalRun = reconstructHistoricalRun(message, tasks);
        const displayRun = isLatest && latestRun ? latestRun : historicalRun;
        const persistedCitations = extractMessageCitations(message);
        const liveCitations = isLatest && latestRun ? latestRun.citations ?? [] : [];
        const citations = liveCitations.length > 0 ? liveCitations : persistedCitations;

        return (
          <article className="agent-result" key={message.id}>
            <header>
              <div>
                <span className="result-mark">AM</span>
                <div>
                  <strong>AgentMesh</strong>
                  <small>{isWaitingStatus(message.status) ? "等待你的确认" : "回答"}</small>
                </div>
              </div>
              <span className={`result-state-pill ${isWaitingStatus(message.status) ? "waiting" : "done"}`}>
                {isWaitingStatus(message.status) ? "待确认" : "完成"}
              </span>
            </header>

            <CitationAnswer content={message.content} citations={citations} />

            {displayRun && (
              <LatestRunMeta result={displayRun} historical={!isLatest} openDetails={() => openDetails(displayRun)} />
            )}
          </article>
        );
      })}

      {pendingPrompt && !messages.some((message) => message.role === "user" && message.content === pendingPrompt) && (
        <div className="user-message-row optimistic-message">
          <div>
            <span className="message-label">你</span>
            <div className="user-message">{pendingPrompt}</div>
            <AttachmentChips items={pendingAttachments} />
          </div>
        </div>
      )}

      {working && streamingAnswer ? (
        <article className="agent-result agent-result-streaming" data-testid="assistant-streaming-answer">
          <header>
            <div>
              <span className="result-mark">AM</span>
              <div>
                <strong>AgentMesh</strong>
                <small>{streamingPhase || "正在生成回答"}</small>
              </div>
            </div>
            <span className="result-state-pill running"><i />流式生成中</span>
          </header>
          <CitationAnswer content={streamingAnswer} citations={[]} />
        </article>
      ) : working ? (
        <WorkingAnswer label={streamingPhase || "正在处理你的任务"} />
      ) : null}
    </div>
  );
}
