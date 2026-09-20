export type User = {
  id: number;
  email: string;
  displayName: string;
  status: string;
};

export type Conversation = {
  id: number;
  userId: number;
  title: string;
  lastMessageAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type Project = {
  id: number;
  userId: number;
  name: string;
  description: string;
  conversationIds: number[];
  createdAt: string;
  updatedAt: string;
};


export type ProjectResourceMode =
  | "all"
  | "selected";

export type ProjectRuntimePolicyMode =
  | "inherit"
  | "project";

export type ProjectRuntimePolicy = {
  mode: ProjectRuntimePolicyMode;
  scheduler: Scheduler;
  planner: Planner;
  executionMode: ExecutionMode;
  synthesisMode: SynthesisMode;
  constraints: TaskConstraints;
};

export type ProjectRuntimeConfig = {
  projectId: number;

  agentMode: ProjectResourceMode;
  agentIds: number[];

  toolMode: ProjectResourceMode;
  toolIds: number[];

  mcpMode: ProjectResourceMode;
  mcpServerIds: number[];

  policy: ProjectRuntimePolicy;

  createdAt: string;
  updatedAt: string;
};


export type MemoryCategory =
  | "preference"
  | "profile"
  | "goal"
  | "workflow"
  | "fact"
  | "other";

export type MemorySourceType =
  | "manual"
  | "explicit_user"
  | "inferred_user";

export type UserMemory = {
  id: number;
  userId: number;
  category: MemoryCategory;
  memoryKey: string;
  content: string;
  sourceType: MemorySourceType;
  confidence: number;
  status: string;
  lastAccessedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeBaseScope =
  | "GLOBAL"
  | "PROJECT";

export type KnowledgeBase = {
  id: number;
  userId: number;
  name: string;
  description: string;
  scope: KnowledgeBaseScope;
  projectId: number | null;
  projectName?: string;
  isDefault: boolean;
  fileCount: number;
  readyFileCount: number;
  pendingFileCount: number;
  errorFileCount: number;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeFileStatus =
  | "UPLOADED"
  | "INDEXING"
  | "READY"
  | "ERROR";

export type KnowledgeFile = {
  id: number;
  knowledgeBaseId: number;
  knowledgeBaseName: string;
  scope: KnowledgeBaseScope;
  projectId: number | null;
  projectName?: string;
  userId: number;
  originalName: string;
  mediaType: string;
  extension: string;
  sizeBytes: number;
  checksumSha256: string;
  storageKey: string;
  status: KnowledgeFileStatus | string;
  chunkCount: number;
  textChunkCount: number;
  visualEvidenceCount: number;
  pageCount: number;
  visualStatus: string;
  visualErrorMessage?: string | null;
  errorMessage: string | null;
  indexedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

// =========================================================
// Runtime Citation
//
// Python RuntimeCitation
//        ↓
// Go RuntimeCitation
//        ↓
// React RuntimeCitation
//
// citationId / label are request-local display identities.
// documentId is the stable knowledge/chunk identity.
// =========================================================

export type RuntimeCitation = {
  citationId: number;
  label: string;
  documentId: string;
  source: string;
  score: number;
  documentType: string | null;
  chunkIndex: number | null;
  start: number | null;
  end: number | null;
  pageNumber: number | null;
  assetId: string | null;
  modality: string | null;
  visualType: string | null;
};

export type MessageAttachmentMetadata = {
  id: number;
  name: string;
  mediaType: string;
  extension: string;
  sizeBytes: number;
};

export type ConversationAttachment = {
  id: number;
  userId: number;
  conversationId: number;
  originalName: string;
  mediaType: string;
  extension: string;
  sizeBytes: number;
  checksumSha256: string;
  createdAt: string;
};

export type MessageMetadata =
  Record<string, unknown> & {
    citations?: RuntimeCitation[];
    attachments?: MessageAttachmentMetadata[];
  };

export type Message = {
  id: number;
  conversationId: number;
  role: string;
  content: string;
  status: string;
  requestId: string | null;
  metadata?: MessageMetadata;
  createdAt: string;
};

export type MessagePage = {
  items: Message[];
  hasMore: boolean;
  nextBeforeId: number | null;
};

// =========================================================
// Agent Capability Profile
// =========================================================

export type AgentCapabilityProfile = {
  capability: string;
  qualityScore: number;
  avgLatencyMs: number;
  avgCost: number;
  successRate: number;
  failureRate: number;
  sampleCount: number;
};

// =========================================================
// Agent
// =========================================================

export type Agent = {
  id: number;
  userId: number;
  name: string;
  description: string;
  endpoint: string;
  protocol: string;

  // P37 OpenJiuwen adapter: "native" (default) keeps the existing executors;
  // "openjiuwen" is only valid on the internal protocol boundary.
  executorType?: "native" | "openjiuwen";

  capabilities: string[];

  provider: string;
  modelName: string;

  qualityScore: number;
  avgLatencyMs: number;
  avgCost: number;

  successRate: number;
  failureRate: number;

  currentLoad: number;

  status: string;

  capabilityProfiles?: AgentCapabilityProfile[];
};

// =========================================================
// Runtime Trace
// =========================================================

export type TraceStatus =
  | "running"
  | "completed"
  | "error"
  | "skipped";

export type TraceEvent = {
  kind: string;
  title: string;
  status: TraceStatus;
  detail: string;
  elapsedMs: number;
};

// =========================================================
// Dynamic DAG
// =========================================================

export type DAGNode = {
  id: string;
  label: string;
  kind: string;
  status: string;
};

export type DAGEdge = {
  source: string;
  target: string;
};

export type DynamicDAG = {
  nodes: DAGNode[];
  edges: DAGEdge[];
};

// =========================================================
// Runtime Policy
// =========================================================

export type Scheduler =
  | "fixed"
  | "capability"
  | "greedy"
  | "adaptive";

export type Planner =
  | "heuristic"
  | "multi_objective";

export type ExecutionMode =
  | "auto"
  | "parallel"
  | "sequential";

export type SynthesisMode =
  | "auto"
  | "always"
  | "never";

export type DeliveryMode =
  | "direct"
  | "durable";

// =========================================================
// Runtime Lifecycle
//
// React 只理解平台级状态。
//
// continuation 不存在于前端 Contract。
// =========================================================

export type RuntimeStatus =
  | "QUEUED"
  | "RUNNING"
  | "INPUT_REQUIRED"
  | "AUTH_REQUIRED"
  | "COMPLETED"
  | "ERROR"
  | "CANCELED";

// =========================================================
// Constraints
// =========================================================

export type TaskConstraints = {
  maxLatencyMs: number;
  maxCost: number;
  minQuality: number;
  retryOnWorkerLoss?: boolean;
};

// =========================================================
// Task
// =========================================================

export type TaskApproval = {
  approvalId: string;
  toolName: string;
  toolProtocol: string;
  riskLevel: string;
  requiresConfirmation: boolean;
  summary: string;
  argumentsPreview?: Record<string, unknown>;
};

export type ModelSelection = {
  mode: "auto" | "manual";
  serviceId?: number | null;
};

export type Task = {
  id: number;
  userId?: number;

  conversationId?: number | null;

  requestId: string;

  taskText: string;

  scheduler: string;

  planner?: string;

  executionMode?: string;

  synthesisMode?: string;

  modelSelection?: ModelSelection;

  deliveryMode?: DeliveryMode | string;

  constraints?: TaskConstraints;

  status: RuntimeStatus | string;

  resultText?: string | null;

  selectedAgents?: string[];

  trace?: TraceEvent[];

  dag?: DynamicDAG;

  latencyMs?: number | null;

  estimatedCost?: number | null;

  errorMessage?: string | null;

  approval?: TaskApproval | null;

  createdAt?: string;

  updatedAt?: string;
};

// =========================================================
// Agent Feedback
// =========================================================

export type AgentFeedback = {
  agentId: number;
  capability: string;
  success: boolean;
  latencyMs: number;
  cost: number;
  qualityScore: number | null;
  errorType: string;
};

// =========================================================
// Observability
// =========================================================

export type ObservabilitySummary = {
  modelCalls: number;
  modelProvider: string;
  modelName: string;

  modelInputTokens: number;
  modelOutputTokens: number;
  modelTotalTokens: number;

  modelLatencyMs: number;

  toolCalls: number;

  mcpEvents: number;

  agentAttempts: number;
  agentSuccesses: number;
  agentFailures: number;

  reschedules: number;

  dagCompletedNodes: number;
  dagSkippedNodes: number;

  qualityEvaluations: number;

  averageQuality: number;

  modelEstimatedCost: number;
  modelCostKnown: boolean;
  toolSuccesses: number;
  toolFailures: number;

  retrievalMode: string;
  ragLatencyMs: number;
  ragRawHits: number;
  ragHits: number;
  ragContextHits: number;
  ragTextCandidates: number;
  ragVisualCandidates: number;
};

export type RunScorecard = {
  evaluator: string;
  status: "pass" | "warning" | "fail" | "unavailable";
  overallScore: number;
  taskSuccess: number;
  answerQuality: number;
  groundedness: number;
  correctness: number;
  citationQuality: number;
  taskCompletion: number;
  toolReliability: number;
  ragQuality: number;
  memoryContribution: number;
  budgetCompliance: number;
  latencyMs: number;
  estimatedCost: number;
  modelEstimatedCost: number;
  modelTokens: number;
  failureCategory: string;
  judgeReason: string;
  violations: string[];
  signals: Record<string, unknown>;
};

// =========================================================
// P37 Agent Harness
//
// 与 Python Runtime / Go Control Plane 的 Harness 契约保持一致。
// 旧任务没有 harness 数据：harnessSummary / harnessReport 均可缺失，
// UI 据此隐藏页签而不是伪造空报告。
// =========================================================

export type HarnessMode = "OFF" | "OBSERVE" | "ENFORCE" | "AUTO_REPAIR";

export type HarnessConfig = {
  mode: HarnessMode;
  maxSteps?: number;
  maxRepairs?: number;
  maxRetriesPerTool?: number;
  maxReschedules?: number;
  loopRepeatThreshold?: number;
  resultSchema?: Record<string, unknown> | null;
  policyVersion?: string;
};

export type HarnessValidationStatus = "PASS" | "FAIL" | "NOT_CONFIGURED";

export type HarnessValidationResult = {
  validator: string;
  status: HarnessValidationStatus;
  code?: string;
  message?: string;
  fieldPaths?: string[];
  evidence?: Record<string, unknown>;
};

export type HarnessDiagnosis = {
  category:
    | "INPUT"
    | "OUTPUT"
    | "TOOL"
    | "STEP"
    | "RESULT"
    | "LOOP"
    | "TIMEOUT"
    | "AUTHORIZATION"
    | "UNKNOWN";
  rootCauseCode: string;
  evidence?: Record<string, unknown>;
  retryable?: boolean;
  sideEffectRisk?: "READ_ONLY" | "IDEMPOTENT_WRITE" | "NON_IDEMPOTENT_WRITE" | "UNKNOWN";
  confidence?: "EXACT" | "HEURISTIC";
  recommendedAction?:
    | "NONE"
    | "REPAIR_ARGS"
    | "RETRY"
    | "FALLBACK"
    | "REPLAN"
    | "TERMINATE";
};

export type HarnessRecovery = {
  action: "REPAIR_ARGS" | "RETRY" | "FALLBACK" | "REPLAN" | "TERMINATE";
  reason?: string;
  tool?: string;
  attempt?: number;
  success?: boolean;
  detail?: Record<string, unknown>;
};

export type HarnessEvent = {
  eventId: string;
  sequence: number;
  timestamp: string;
  state: string;
  type: string;
  severity?: "info" | "warning" | "error";
  subject?: string;
  validation?: HarnessValidationResult | null;
  diagnosis?: HarnessDiagnosis | null;
  recovery?: HarnessRecovery | null;
  elapsedMs?: number;
};

export type HarnessSummary = {
  mode: string;
  outcome: "COMPLETED" | "TERMINATED" | "OBSERVED_ISSUES";
  validationFailures?: number;
  repairs?: number;
  retries?: number;
  reschedules?: number;
  terminationReason?: string;
  overheadMs?: number;
};

export type HarnessBudgetSnapshot = {
  maxSteps?: number;
  maxRepairs?: number;
  maxRetriesPerTool?: number;
  maxReschedules?: number;
  loopRepeatThreshold?: number;
  usedSteps?: number;
  usedRepairs?: number;
  usedToolRetries?: number;
  usedReschedules?: number;
};

export type HarnessReport = {
  configSnapshot?: Record<string, unknown>;
  stateTimeline?: { state: string; elapsedMs: number; timestamp: string }[];
  events?: HarnessEvent[];
  diagnoses?: HarnessDiagnosis[];
  recoveries?: HarnessRecovery[];
  finalValidation?: HarnessValidationResult | null;
  metrics?: {
    validationTotal?: number;
    validationFailures?: number;
    validationsNotConfigured?: number;
    diagnoses?: number;
    recoveries?: number;
    loopDetections?: number;
    budget?: HarnessBudgetSnapshot | null;
  };
};

// =========================================================
// Run / Resume Result
//
// /api/tasks/run
//
// 和
//
// /api/tasks/:id/resume
//
// 都返回同一个结构。
// =========================================================

export type RunResult = {
  task: Task;

  status: RuntimeStatus;

  answer: string;

  citations: RuntimeCitation[];

  scheduler: string;

  planner: string;

  executionMode: string;

  synthesisMode: string;

  taskProfile: Record<string, unknown>;

  selectedAgents: string[];

  estimatedCost: number;

  elapsedMs: number;

  trace: TraceEvent[];

  dag: DynamicDAG;

  agentFeedback: AgentFeedback[];

  observability: ObservabilitySummary;

  scorecard: RunScorecard | null;

  harnessSummary?: HarnessSummary | null;

  harnessReport?: HarnessReport | null;
};

export type RuntimeReliabilitySnapshot = {
  enabled: boolean;
  queueDepth: number;
  leased: number;
  accepted: number;
  failed: number;
  canceled: number;
  workers: number;
  availableWorkers: number;
  drainingWorkers: number;
  circuitOpenWorkers: number;
  nodes?: number;
  availableNodes?: number;
  staleNodes?: number;
  totalCapacity?: number;
  activeExecutions?: number;
  utilizationPercent?: number;
  dispatcherLeader?: boolean;
  dispatcherEpoch?: number;
  dispatcherLeaseRemainingMs?: number;
  oldestQueuedMs: number;
};

export type RuntimeNodeSummary = {
  nodeId: string;
  zone?: string;
  version?: string;
  capacity: number;
  activeExecutions: number;
  workerCount: number;
  draining: boolean;
  status: string;
  lastHeartbeatAt: string;
};

export type RuntimeWorkerSummary = {
  workerId: string;
  nodeId: string;
  zone?: string;
  version?: string;
  capacity: number;
  activeExecutions: number;
  authoritativeActive: number;
  nodeCapacity: number;
  nodeActiveExecutions: number;
  schedulingScore: number;
  draining: boolean;
  status: string;
  consecutiveFailures: number;
  lastHeartbeatAt: string;
};

export type RuntimeTopologySnapshot = {
  reliability: RuntimeReliabilitySnapshot;
  nodes: RuntimeNodeSummary[];
  workers: RuntimeWorkerSummary[];
};

// =========================================================
// Plugin
// =========================================================

export type PluginInfo = {
  id: string;
  name: string;
  version: string;
  kind: string;
  status: string;
  provider?: string;
  model?: string;
};

// =========================================================
// Tool
// =========================================================

export type Tool = {
  id: number;
  userId: number;
  name: string;
  description: string;
  protocol: string;
  endpoint?: string;

  inputSchema: Record<string, unknown>;

  riskLevel: string;

  requiresConfirmation: boolean;

  enabled: boolean;
};

// =========================================================
// MCP
// =========================================================

export type MCPServer = {
  id: number;
  userId: number;

  name: string;

  transport: "streamable_http";

  endpoint: string;

  enabled: boolean;

  connectTimeoutMs: number;

  callTimeoutMs: number;
};

export type MCPDiscoveredTool = {
  name: string;
  description: string;

  input_schema: Record<string, unknown>;

  mcp_server_id: number;

  original_tool_name: string;
};
// =========================================================
// P9 Enterprise Governance
// =========================================================
export type ProjectRole = "OWNER" | "ADMIN" | "DEVELOPER" | "VIEWER";
export type ProjectMember = {
  projectId: number;
  userId: number;
  email?: string;
  displayName?: string;
  role: ProjectRole;
  createdAt: string;
  updatedAt: string;
};
export type ProjectQuota = {
  projectId: number;
  requestsPerMinute: number;
  concurrentTasks: number;
  monthlyTokenLimit: number;
  monthlyCostLimit: number;
  dailyToolActionLimit: number;
};
export type ProjectUsage = {
  projectId: number;
  monthKey: string;
  requestCount: number;
  tokenCount: number;
  estimatedCost: number;
  toolActionCount: number;
  concurrentTasks: number;
};
export type ProjectSecret = {
  id: number;
  projectId: number;
  name: string;
  kind: string;
  maskedHint: string;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
  lastUsedAt?: string | null;
};
export type ProjectModelProvider = {
  projectId: number;
  provider: string;
  baseUrl: string;
  modelName: string;
  secretId?: number | null;
  enabled: boolean;
  createdAt?: string;
  updatedAt?: string;
};
export type UserModelProvider = {
  userId: number;
  provider: string;
  baseUrl: string;
  modelName: string;
  visionModelName: string;
  maskedHint: string;
  enabled: boolean;
  createdAt?: string;
  updatedAt?: string;
};

export type UserModelProviderInput = {
  provider: string;
  baseUrl: string;
  modelName: string;
  visionModelName: string;
  apiKey: string;
  enabled: boolean;
};

export type UserModelService = {
  id: number;
  userId: number;
  name: string;
  provider: string;
  baseUrl: string;
  modelName: string;
  visionModelName: string;
  maskedHint: string;
  enabled: boolean;
  autoRoute: boolean;
  isDefault: boolean;
  createdAt?: string;
  updatedAt?: string;
};

export type UserModelServiceInput = {
  name: string;
  provider: string;
  baseUrl: string;
  modelName: string;
  visionModelName: string;
  apiKey: string;
  enabled: boolean;
  autoRoute: boolean;
  isDefault: boolean;
};
export type AuditEvent = {
  id: number;
  projectId?: number | null;
  actorUserId: number;
  action: string;
  resourceType: string;
  resourceId: string;
  result: string;
  metadata?: Record<string, unknown>;
  createdAt: string;
};
export type RunCostRecord = {
  taskId: number;
  userId: number;
  projectId?: number | null;
  provider: string;
  modelName: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCost: number;
  costStatus: "actual" | "estimated" | "unavailable" | string;
  createdAt: string;
  updatedAt?: string | null;
};

export type CostBreakdown = {
  provider: string;
  modelName: string;
  runs: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCost: number;
};

export type CostSummary = {
  runCount: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  estimatedCost: number;
  knownCostRuns: number;
  unknownCostRuns: number;
  breakdown: CostBreakdown[];
};

export type GovernanceOverview = {
  role: ProjectRole;
  members: ProjectMember[];
  quota: ProjectQuota;
  usage: ProjectUsage;
  secrets: ProjectSecret[];
  modelProvider?: ProjectModelProvider | null;
  audit: AuditEvent[];
};
export type Organization = {
  id: number;
  ownerId: number;
  name: string;
  createdAt: string;
  updatedAt: string;
};

// =========================================================
// V4 Platform Ecosystem
// =========================================================

export type ServiceAccount = {
  id: number;
  projectId: number;
  name: string;
  keyPrefix: string;
  scopes: string[];
  status: string;
  createdBy: number;
  expiresAt?: string | null;
  lastUsedAt?: string | null;
  requestCount: number;
  errorCount: number;
  createdAt: string;
  updatedAt: string;
};

export type ServiceAccountCredential = {
  serviceAccount: ServiceAccount;
  apiKey: string;
};

export type EcosystemAgentTemplate = {
  name: string;
  description?: string;
  endpoint: string;
  protocol?: string;
  capabilities: string[];
  provider?: string;
  modelName?: string;
};

export type EcosystemMCPTemplate = {
  name: string;
  transport?: string;
  endpoint: string;
  connectTimeoutMs?: number;
  callTimeoutMs?: number;
};

export type EcosystemPluginTemplate = {
  name: string;
  description?: string;
  runtime?: string;
  entrypoint?: string;
  capabilities?: string[];
  configSchema?: Record<string, unknown>;
};

export type EcosystemPackageManifest = {
  schemaVersion: string;
  kind: "AGENT" | "MCP" | "PLUGIN";
  permissions: string[];
  agent?: EcosystemAgentTemplate;
  mcp?: EcosystemMCPTemplate;
  plugin?: EcosystemPluginTemplate;
};

export type EcosystemPackage = {
  id: number;
  ownerUserId: number;
  slug: string;
  name: string;
  kind: "AGENT" | "MCP" | "PLUGIN";
  summary: string;
  description: string;
  visibility: string;
  status: string;
  latestVersion?: string;
  installCount: number;
  createdAt: string;
  updatedAt: string;
};

export type EcosystemPackageVersion = {
  id: number;
  packageId: number;
  version: string;
  manifest: EcosystemPackageManifest;
  checksum: string;
  status: string;
  createdBy: number;
  createdAt: string;
};

export type EcosystemPackageDetail = {
  package: EcosystemPackage;
  versions: EcosystemPackageVersion[];
};

export type EcosystemPackageBundle = {
  formatVersion: string;
  package: EcosystemPackage;
  version: EcosystemPackageVersion;
};

export type ProjectPackageInstallation = {
  id: number;
  projectId: number;
  packageId: number;
  versionId: number;
  packageSlug: string;
  packageName: string;
  kind: "AGENT" | "MCP" | "PLUGIN";
  version: string;
  enabled: boolean;
  config?: Record<string, unknown>;
  resourceType?: string;
  resourceId?: number | null;
  installedBy: number;
  createdAt: string;
  updatedAt: string;
};

export type EcosystemOverview = {
  publishedPackages: number;
  agentPackages: number;
  mcpPackages: number;
  pluginPackages: number;
  totalInstalls: number;
};
