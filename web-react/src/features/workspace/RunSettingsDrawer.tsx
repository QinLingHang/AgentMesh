import type {
  DeliveryMode,
  ExecutionMode,
  KnowledgeBase,
  Planner,
  RagMode,
  RagScope,
  Scheduler,
  SynthesisMode,
} from "../../types";
import { Icon } from "../../components/common/Icon";
import { RunConfiguration } from "./RunConfiguration";

export function RunSettingsDrawer({
  open,
  onClose,
  scheduler,
  setScheduler,
  planner,
  setPlanner,
  executionMode,
  setExecutionMode,
  synthesisMode,
  setSynthesisMode,
  deliveryMode,
  setDeliveryMode,
  ragMode,
  setRagMode,
  ragScopes,
  setRagScopes,
  knowledgeBases,
  selectedKnowledgeBaseIds,
  setSelectedKnowledgeBaseIds,
  knowledgeCatalogError,
  latency,
  setLatency,
  cost,
  setCost,
  quality,
  setQuality,
  retryOnWorkerLoss,
  setRetryOnWorkerLoss,
}: {
  open: boolean;
  onClose: () => void;
  scheduler: Scheduler;
  setScheduler: (value: Scheduler) => void;
  planner: Planner;
  setPlanner: (value: Planner) => void;
  executionMode: ExecutionMode;
  setExecutionMode: (value: ExecutionMode) => void;
  synthesisMode: SynthesisMode;
  setSynthesisMode: (value: SynthesisMode) => void;
  deliveryMode: DeliveryMode;
  setDeliveryMode: (value: DeliveryMode) => void;
  ragMode: RagMode;
  setRagMode: (value: RagMode) => void;
  ragScopes: RagScope[];
  setRagScopes: (value: RagScope[]) => void;
  knowledgeBases: KnowledgeBase[];
  selectedKnowledgeBaseIds: number[];
  setSelectedKnowledgeBaseIds: (value: number[]) => void;
  knowledgeCatalogError: string;
  latency: number;
  setLatency: (value: number) => void;
  cost: number;
  setCost: (value: number) => void;
  quality: number;
  setQuality: (value: number) => void;
  retryOnWorkerLoss: boolean;
  setRetryOnWorkerLoss: (value: boolean) => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="workspace-settings-layer">
      <button
        aria-label="关闭运行设置"
        className="workspace-drawer-backdrop"
        onClick={onClose}
        type="button"
      />

      <aside
        aria-label="运行设置"
        className="run-settings-drawer"
      >
        <header className="run-settings-head">
          <div>
            <span className="eyebrow">
              运行策略
            </span>

            <h2>
              运行设置
            </h2>

            <p>
              调整调度、协作规划、执行方式与本次任务约束。
            </p>
          </div>

          <button
            aria-label="关闭运行设置"
            className="icon-button"
            onClick={onClose}
            type="button"
          >
            <Icon
              name="close"
              size={17}
            />
          </button>
        </header>

        <div className="run-settings-summary">
          <span>
            {scheduler}
          </span>

          <span>
            {planner}
          </span>

          <span>
            {executionMode}
          </span>
        </div>

        <RunConfiguration
          scheduler={scheduler}
          setScheduler={setScheduler}
          planner={planner}
          setPlanner={setPlanner}
          executionMode={executionMode}
          setExecutionMode={setExecutionMode}
          synthesisMode={synthesisMode}
          setSynthesisMode={setSynthesisMode}
          deliveryMode={deliveryMode}
          setDeliveryMode={setDeliveryMode}
          ragMode={ragMode}
          setRagMode={setRagMode}
          ragScopes={ragScopes}
          setRagScopes={setRagScopes}
          knowledgeBases={knowledgeBases}
          selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
          setSelectedKnowledgeBaseIds={setSelectedKnowledgeBaseIds}
          knowledgeCatalogError={knowledgeCatalogError}
          latency={latency}
          setLatency={setLatency}
          cost={cost}
          setCost={setCost}
          quality={quality}
          setQuality={setQuality}
          retryOnWorkerLoss={retryOnWorkerLoss}
          setRetryOnWorkerLoss={setRetryOnWorkerLoss}
        />

        <footer className="run-settings-foot">
          <div>
            <strong>
              智能策略
            </strong>

            <small>
              当前设置仅作用于下一次任务，不影响历史运行。
            </small>
          </div>

          <button
            className="primary-button compact-button"
            data-testid="run-settings-done"
            onClick={onClose}
            type="button"
          >
            完成
          </button>
        </footer>
      </aside>
    </div>
  );
}
