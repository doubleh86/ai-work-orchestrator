import {
  Activity,
  AlertCircle,
  ArrowUp,
  Archive,
  Bell,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  CircleDot,
  Clock3,
  Copy,
  Database,
  FolderKanban,
  FolderOpen,
  GitMerge,
  ListChecks,
  LockKeyhole,
  MessageSquare,
  PanelRight,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  RotateCcw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Square,
  Trash2,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import { providerFailurePresentation } from "./providerFailure";
import {
  CSSProperties,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  RefObject,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";

import { RecoveryDialog } from "./RecoveryDialog";
import { TaskRepairPanel } from "./TaskRepairPanel";
import { failurePresentation } from "./failurePresentation";
import { FailedTaskQuestionDrafts, failedTaskQuestionKey } from "./failedTaskQuestionDrafts";
import { WorkOverview } from "./WorkOverview";
import { PlanningMessageDialog, type FullPlanningMessage } from "./PlanningMessageDialog";
import { NavigationSidebar } from "./NavigationSidebar";
import { AiConnectionDialog } from "./AiConnectionDialog";
import { McpConnectionGuide } from "./McpConnectionGuide";
import { CodexApiKeyConnection } from "./CodexApiKeyConnection";
import { ChatProjectNavigation } from "./ChatProjectNavigation";
import { ChatHome } from "./ChatHome";
import { ChatWorkActivity, ChatWorkStatus } from "./ChatWorkActivity";
import type { ChatControlView } from "../../shared/chatControls";
import type { PlanningRequestsSnapshot } from "../../shared/planningRequests";
import { PLANNING_REQUEST_METHODS, planningRequestFor } from "../../shared/planningRequests";
import { composerIsComposing } from "./composerInput";
import { QueuedChatMessages } from "./QueuedChatMessages";
import type { PlanningMessageQueueSnapshot, QueuedMessageChange, QueuedPlanningMessage } from "../../shared/planningMessageQueue";
import { chatExecutionIntent } from "./chatTaskRecovery";
import { chatControlParams } from "../../shared/chatExecution";
import { chatExecutionErrorReported, controlExecutionFromChat, type ChatExecutionPhase } from "./chatExecutionControl";
import { PlanningSidebar } from "./PlanningSidebar";
import { WorkDialog } from "./WorkDialog";
import { executionOnTaskCards, TaskFlow } from "./TaskFlow";
import { RunPreparation } from "./RunPreparation";
import { selectedTaskForDetails, taskPlanningQuestion, taskPlanningQuestionBody, taskPlanningQuestionDraft, taskDetailUsesChat, TaskDetailSummary, TaskStatusOverview } from "./TaskStatusOverview";
import { ChatTaskSettings } from "./ChatTaskSettings";
import { canContinueTaskRetry } from "./taskContinuation";
import { EffortModePanel, effortModeLabels } from "./EffortModePanel";
import { UsagePanel } from "./UsagePanel";
import { AiBadge } from "./AiBadge";
import { resultRevisionDiscussion } from "./resultReviewPresentation";
import { PlanningEffortPicker, PlanningPolicySummary } from "./PlanningEffortPicker";
import {
  PlanningRequestDrafts, initialPlanningProfileParams, planningMessageProfileParams, planningRepositoryIntent, type PlanningRequestDraft,
} from "./planningRequestDrafts";
import { PlanningApplyDialog } from "./PlanningApplyDialog";
import { PlanningMessageDisclosure, planningMessageKey, scrollPlanningContentIntoView } from "./PlanningMessageDisclosure";
import { ApplySummarySession, applySummaryAction, applySummaryStatus, applySummaryTitle, includedApplyTasks, sendApplySummaryCommand, type ApplySummaryAction, type ApplySummaryMethod } from "./applySummaryFlow";
import { ProjectToolsMenu } from "./ProjectToolsMenu";
import { installDetailsDismissal } from "./dismissibleDetails";
import { NextStepWaitingBanner } from "./NextStepWaitingBanner";
import { NotificationRefreshStatus } from "./NotificationRefreshStatus";
import { readWaitingPromptAction, waitingPromptAction } from "./waitingPrompt";
import { initialTaskPlanningAvailable, openPlanningPreviewForMessage, planningApplyEntryBlocked, planningPreviewSurface, taskPlanningInProgress, type TaskPlanningTarget } from "./planningPreviewRequest";
import { DirectionChangePanel } from "./DirectionChangePanel";
import { DirectionChangeDrafts } from "./directionChangeDrafts";
import { AttentionInbox, AttentionInboxTrigger } from "./AttentionInbox";
import { attentionNavigation, reconcileAttentionItems, uncertainAttentionSnapshot } from "./attentionInboxPresentation";
import { useAttentionNavigationFocus, type AttentionFocusRequest } from "./useAttentionNavigationFocus";
import { ResultReview, type ResultRevisionDraft } from "./ResultReview";
import { ResultRevisionRequests, resultRevisionRequestKey } from "./resultRevisionRequests";
import { MainChangesDialog } from "./MainChangesDialog";
import { ConflictResolutionPanel } from "./ConflictResolutionPanel";
import { activeConflictPhase } from "./recoveryTaskPresentation";
import { defaultLogView, ExecutionLogViewer, ExecutionOverview, TaskActivityLine, type LogViewState } from "./ExecutionMonitor";
import { InspectorContent, InspectorToggle, type InspectorScrollMemory } from "./InspectorControls";
import { monitorTasks, taskActivityTiming, taskIsActive } from "./executionActivity";
import { progressPhaseLabels } from "./progressLog";
import { providerRetryWait } from "./providerRetry";
import { taskProfileComparison, taskProfileOptionLabel, taskProfileRequiresReselection } from "./taskProfileComparison";
import { taskDependencySections } from "./taskDependencyPresentation";
import { repositoryEvidenceGroups } from "./repositoryMaturityPresentation";
import { TechStackDecisionPanel } from "./TechStackDecisionPanel";
import { BootstrapSpecPanel } from "./BootstrapSpecPanel";
import { CodeStyleProfilePanel } from "./CodeStyleProfilePanel";
import {
  codeStyleRuleSummary,
  codeStyleSnapshotSummary,
  styleCheckPurpose,
  taskCodeStyleCheckDetail,
  taskCodeStyleCheckSummary,
  taskCodeStyleEvidenceSummary,
} from "./codeStyleProfile";
import { activeTechStackDecision } from "./techStackDecision";
import { GreenfieldFlowPanel } from "./GreenfieldFlowPanel";
import { greenfieldConsentOption, greenfieldPlaceholder, greenfieldRetry } from "./greenfieldFlow";
import { confirmGreenfieldExecution, confirmGreenfieldOption, requestGreenfieldPlan } from "./greenfieldActions";
import {
  findPendingTechnologyPlanning,
  planningProgressContext,
  planningPurposeActivity,
  planningSourceSummary,
  planningStartReadiness,
} from "./planningStart";
import { runDeletionBlockMessage, runDeletionMissingMessage, runDeletionNeedsBackendRestart, runMissingMessage } from "./runDeletion";
import { notificationDismissFocusIndex, type NotificationDismissFocusRequest } from "./notificationDismissFocus";
import { archiveCompletionView, selectedRunView } from "./runArchiveNavigation";
import { filterRuns, runFilterCounts, runStatusFilterLabels, type RunStatusFilter } from "./runFilters";
import { activeGroupActivityLabel, confirmedActiveGroupCount, reconcileActiveGroups, visibleActiveGroups } from "./activeGroups";
import {
  applyRunSummary,
  reconcileRunScope,
  type RunListScope,
  type RunSummaryCache,
} from "./runArchiveCache";
import {
  isRunStageMismatchError,
  projectRunContext,
  readRunExecutionAction,
  runContextMatches,
  runExecutionPresentation,
  runRequestKey,
  shouldPollRunExecution,
  unknownIntegrationControl,
  unknownRunExecutionControl,
} from "./runExecutionControl";
import { runNextAction, type RunNextAction } from "./runNextAction";
import { runRecoveryAllowed, runRecoveryGuidance, type RunRecoveryGuidance } from "./runRecoveryGuidance";
import { RunLockNotice } from "./RunLockNotice";
import { recoveryTaskPresentation } from "./recoveryTaskPresentation";
import { blockedTaskFailureAction, pendingTaskActionIsAllowed, taskQueueHold, taskRetryIsAllowed } from "./taskQueuePresentation";
import { shouldSelectTaskRow, taskRowInteractiveSelector } from "./taskRowInteraction";
import { inspectorPanelId, resolveWorkbenchLayout, taskSelectionOpensDetail, type TaskContentView, type WorkbenchLayout } from "./workbenchLayout";
import { runWorkspacePresentation, type RunWorkspacePresentation } from "./workspaceLocation";
import {
  archiveCleanupReason, canRetryMainPush, formatDurationLimit, mainAlreadyApplied, operationsSnapshotMatches, readConsistentOperations,
  runLockLabel, workspaceCleanupFailure, workspaceReasonLabel, workspaceStateLabel, type OperationsSnapshot,
} from "./integrationCompletion";
import { useTaskLog, type TaskLogState } from "./useTaskLog";
import { usePlanDrafts } from "./usePlanDrafts";
import {
  canDiscardUntouchedTaskDraft, parseDraftCommands, planDraftConflict, planDraftDirty, planDraftErrors, taskDependencyOptions,
  taskEditorInput, taskDraftErrorIsAdvanced, taskDraftErrorSummary, taskPlanFailure, toggleDraftDependency, unresolvedDraftDependencies,
  type TaskDraftError, type TaskEditorInput, type TaskProfileSelection,
} from "./planDrafts";
import { ApprovedRpcMethod, RpcMethod } from "../../shared/rpc";
import { CodexAuthMethod, CodexAuthState, codexAccountDetails, codexAuthIsPending } from "../../shared/codexAuth";
import {
  defaultWorkNotificationSettings,
  StoredWorkNotification,
  WorkNotificationDismissScope,
  WorkNotificationSettings,
  WorkNotificationSnapshot,
  workNotificationCopy,
  notificationRefreshCopy,
  reconcileNotificationSnapshot,
} from "../../shared/workNotifications";
import { notificationNavigation } from "./workNotificationNavigation";
import {
  notificationPanelPosition,
  type NotificationPanelPosition,
} from "./notificationPanelPosition";
import {
  PlanningMode,
  PlanningApplyPreview,
  DotnetDiagnostic,
  GitInitialCommitPreview,
  GitRepositoryReadiness,
  IntegrationControl,
  PlanningSourceIndex,
  ProjectCapabilities,
  ProjectCodeStylePreference,
  ProjectCodeStyleProfile,
  ProjectWorkspaceLocation,
  ProviderProfile,
  ProviderStatus,
  RegisteredProject,
  UsageSnapshot,
  RecoveryTask,
  RunLockStatus,
  RunArchivePlan,
  RunExecutionControl,
  RunState,
  EffortMode,
  RunSummary,
  ActiveGroupSnapshot,
  ActiveGroupSummary,
  AttentionItem,
  AttentionSnapshot,
  WorkTask,
} from "./types";

const stageLabels: Record<string, string> = {
  received: "기획 수신",
  reviewed: "문서 검토",
  needs_clarification: "추가 확인",
  planned: "실행 준비",
  executing: "실행 중",
  ready_to_merge: "병합 대기",
  verified: "통합 검증 완료",
  work_branch_pushed: "작업 브랜치 Push 완료",
  merged: "Main 반영 완료",
  pushed: "Main Push 완료",
  deployed: "배포 완료",
  failed: "실패",
  stopped: "사용자 중지",
};

const taskStatusLabels: Record<string, string> = {
  pending: "대기",
  running: "실행 중",
  reviewing: "리뷰 중",
  revising: "수정 중",
  waiting: "수동 확인",
  completed: "완료",
  failed: "실패",
  merged: "Main 반영",
};

const readinessLabels: Record<string, string> = {
  ready: "실행 가능",
  blocked: "선행 작업 대기",
  active: "진행 중",
  done: "완료",
  failed: "재시도 필요",
};

const taskProgressLabels: Record<string, string> = progressPhaseLabels;

const emptyActiveGroups: ActiveGroupSnapshot = { items: [], errors: [], checked_at: "" };
type GroupListMode = "global" | "project";

function savedGroupListMode(): GroupListMode {
  try { return window.localStorage.getItem("ai-orchestrator-group-list-mode") === "project" ? "project" : "global"; }
  catch { return "global"; }
}

const verificationProgressLabels: Record<string, string> = {
  preparing: "통합 검증 준비 중",
  checking_main: "Main 상태 확인 중",
  syncing_main: "최신 Main 동기화 중",
  checking_task_branches: "작업 브랜치 확인 중",
  preparing_worktree: "검증 작업공간 생성 중",
  integrating_tasks: "작업 변경 통합 중",
  preparing_dependencies: "검증 의존성 복원 중",
  running_command: "검증 명령 실행 중",
  repairing: "검증 실패 수정 중",
  finalizing: "검증 결과 저장 중",
  completed: "통합 검증 완료",
  failed: "통합 검증 실패",
};

function taskProgressPhase(task: WorkTask): string {
  if (!task.progress_phase) return "";
  return taskProgressLabels[task.progress_phase] || task.progress_phase;
}

function taskProgressText(task: WorkTask): string {
  const phase = taskProgressPhase(task);
  if (!phase || !taskIsActive(task) || !taskActivityTiming(task, Date.now()).hasCurrentProgress) return "";
  return providerRetryWait(task.progress_phase, task.progress_detail)
    || (task.progress_detail ? `${phase} · ${task.progress_detail}` : phase);
}

function verificationProgressTitle(run: RunState): string {
  const phase = verificationProgressLabels[run.verification_progress_phase]
    || run.verification_progress_phase
    || "통합 검증 상태 확인 중";
  const hasCount = run.verification_progress_current > 0
    && run.verification_progress_total > 0;
  return hasCount
    ? `${phase} · ${run.verification_progress_current}/${run.verification_progress_total}`
    : phase;
}

const eventKindLabels: Record<string, string> = {
  step: "단계",
  stage: "상태",
  planning: "계획",
  planning_progress: "기획 진행",
  task_action: "작업 실행",
  task: "작업",
  execution: "실행",
  review: "리뷰",
  routing: "실행 프로필",
  workspace: "작업공간",
  verification: "검증",
};

const liveRunActionMethods = new Set<RpcMethod>([
  "runs.execute",
  "runs.resume",
  "tasks.execute",
  "tasks.retry",
  "tasks.complete",
  "runs.verify",
  "runs.verifyAndRepair",
]);
const RENDERER_LOG_DISPLAY_LIMIT_CHARACTERS = 64 * 1024;

type InspectorTab = "detail" | "log" | "events";
type WorkbenchView = "tasks" | "planning" | "operations" | "results";

interface PendingPlanningMessage {
  projectName?: string;
  runId: string;
  text: string;
  at: string;
  previousMessageCount: number;
  status: "sending" | "unconfirmed";
}

interface PendingExecutionRequest {
  id: number;
  method: RpcMethod;
  startedAt: number;
  chatPhase?: ChatExecutionPhase;
  chatRequestId?: string;
  chatIntent?: string;
}

type StaleLockRecovery = "recovered" | "cancelled" | "not-stale";

interface ProjectDraft {
  name: string;
  repo: string;
  configPath: string;
  planningSourceDir: string;
}

interface LoadRunsOptions {
  projectName: string;
  scope: RunListScope;
  preferredRun?: string;
  selectFirst?: boolean;
  archiveRefresh?: boolean;
}

const emptyProjectDraft: ProjectDraft = {
  name: "",
  repo: "",
  configPath: "",
  planningSourceDir: "",
};

export function App() {
  useEffect(() => installDetailsDismissal(document), []);
  const [usageSnapshots, setUsageSnapshots] = useState<Record<string, { snapshot?: UsageSnapshot; error: string }>>({});
  const [planningChatTarget, setPlanningChatTarget] = useState<HTMLDivElement | null>(null);
  const [planningChatOpenRequest, setPlanningChatOpenRequest] = useState(0);
  const [homeView, setHomeView] = useState<"overview" | "work" | "history" | "settings">("overview");
  const [workDetailsOpen, setWorkDetailsOpen] = useState(false);
  const chatScrollMemory = useRef<Record<string, { top: number; followsLatest: boolean }>>({});
  const workDetailsTrigger = useRef<HTMLButtonElement>(null);
  const workDetailsClose = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (workDetailsOpen && homeView === "work" && !document.querySelector("dialog:modal")) workDetailsClose.current?.focus({ preventScroll: true });
  }, [workDetailsOpen, homeView]);
  const [choosingNewWorkProject, setChoosingNewWorkProject] = useState(false);
  const [projects, setProjects] = useState<RegisteredProject[]>([]);
  const [selectedProjectName, setSelectedProjectName] = useState("");
  const [runSummaryCache, setRunSummaryCache] = useState<RunSummaryCache>({});
  const [groupListMode, setGroupListMode] = useState<GroupListMode>(savedGroupListMode);
  const [activeGroups, setActiveGroups] = useState<ActiveGroupSnapshot>(emptyActiveGroups);
  const [activeGroupsLoading, setActiveGroupsLoading] = useState(false);
  const [activeGroupsError, setActiveGroupsError] = useState("");
  const [attentionSnapshot, setAttentionSnapshot] = useState<AttentionSnapshot>({ items: [], errors: [], checked_at: "" });
  const [attentionLoading, setAttentionLoading] = useState(false);
  const [attentionError, setAttentionError] = useState("");
  const [attentionOpen, setAttentionOpen] = useState(false);
  const [globalSearch, setGlobalSearch] = useState("");
  const [archiveScope, setArchiveScope] = useState<RunListScope>("active");
  const [runStatusFilters, setRunStatusFilters] = useState<Record<string, RunStatusFilter>>({});
  const [selectedRun, setSelectedRun] = useState<RunState>();
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [selectedRecoveryTaskId, setSelectedRecoveryTaskId] = useState("");
  const [search, setSearch] = useState("");
  const [workbenchView, setWorkbenchView] = useState<WorkbenchView>("tasks");
  const isWorkOverview = workbenchView === "tasks" || workbenchView === "operations";
  const groupOperationsVisible = workOverviewHasOperations(selectedRun);
  useEffect(() => { setWorkDetailsOpen(workbenchView === "results"); }, [selectedProjectName, selectedRunId]);
  useEffect(() => { if (homeView === "work" && workbenchView === "results") setWorkDetailsOpen(true); }, [homeView, workbenchView]);
  const [resultFocusTaskId, setResultFocusTaskId] = useState("");
  const [resultRevisionDrafts, setResultRevisionDrafts] = useState<Record<string, ResultRevisionDraft>>({});
  const [resultRevisionRequests] = useState(() => new ResultRevisionRequests());
  const [directionChangeDrafts] = useState(() => new DirectionChangeDrafts());
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("detail");

  const [loading, setLoading] = useState(true);
  const [backendChecked, setBackendChecked] = useState(false);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [navigationOpenRequest, setNavigationOpenRequest] = useState(0);
  const [rawBusyAction, setBusyActionState] = useState("");
  const [removingProjectName, setRemovingProjectName] = useState("");
  const [executionRequests, setExecutionRequests] = useState<Record<string, PendingExecutionRequest>>({});
  const [stopRequestExecutionId, setStopRequestExecutionId] = useState("");
  const [executionClock, setExecutionClock] = useState(() => Date.now());
  const [deletingRunId, setDeletingRunId] = useState("");
  const [deletingProjectName, setDeletingProjectName] = useState("");
  const deleteRequestPendingRef = useRef(false);
  const [archivingRunId, setArchivingRunId] = useState("");
  const [archivingProjectName, setArchivingProjectName] = useState("");
  const archiveRequestPendingRef = useRef(false);
  const [planningIndexElapsed, setPlanningIndexElapsed] = useState(0);
  const [planningStartElapsed, setPlanningStartElapsed] = useState(0);
  const [executionElapsed, setExecutionElapsed] = useState(0);
  const [planningPreparationMessage, setPlanningPreparationMessage] = useState("");
  const [planningStartErrors, setPlanningStartErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [runListRefreshRetry, setRunListRefreshRetry] = useState<LoadRunsOptions>();
  const [notificationPanelOpen, setNotificationPanelOpen] = useState(false);
  const [notificationPanelPlacement, setNotificationPanelPlacement] = useState<NotificationPanelPosition>();
  const [notificationActionError, setNotificationActionError] = useState("");
  const [notificationRefreshBusy, setNotificationRefreshBusy] = useState(false);
  const notificationRefreshPending = useRef(false);
  const [notifications, replaceNotifications] = useState<WorkNotificationSnapshot>({
    items: [],
    unread_count: 0,
    settings: { ...defaultWorkNotificationSettings },
    delivery_error: "",
    read_state_notice: "",
  });
  const setNotifications = useCallback((snapshot: WorkNotificationSnapshot) => {
    replaceNotifications((current) => reconcileNotificationSnapshot(current, snapshot));
  }, []);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const notificationRefreshProblem = Boolean(notifications.delivery_error || notifications.refresh_issues?.some((issue) => !issue.recovered_at));
  const [repairTarget, setRepairTarget] = useState<{ projectName: string; runId: string; taskId: string }>();
  const failedQuestionDrafts = useRef(new FailedTaskQuestionDrafts());
  const failedQuestionTargetRef = useRef("");
  const [planningPreviewTarget, setPlanningPreviewTarget] = useState<{ projectName: string; runId: string; taskId?: string }>();
  const [taskPlanningRequests, setTaskPlanningRequests] = useState<Record<string, TaskPlanningTarget & { startedAt: number }>>({});
  const taskPlanningRequestsRef = useRef(taskPlanningRequests);
  const beginTaskPlanning = useCallback((target: TaskPlanningTarget) => {
    const requestId = crypto.randomUUID();
    taskPlanningRequestsRef.current = { ...taskPlanningRequestsRef.current, [requestId]: { ...target, startedAt: Date.now() } };
    setTaskPlanningRequests(taskPlanningRequestsRef.current);
    return () => {
      if (!taskPlanningRequestsRef.current[requestId]) return;
      const next = { ...taskPlanningRequestsRef.current };
      delete next[requestId];
      taskPlanningRequestsRef.current = next;
      setTaskPlanningRequests(next);
    };
  }, []);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectRegistrationIntent, setProjectRegistrationIntent] = useState<"" | "existing" | "new">("");
  const [projectSettingsOpen, setProjectSettingsOpen] = useState(false);
  const [mainChangesOpen, setMainChangesOpen] = useState(false);
  const [codexAuthOpen, setCodexAuthOpen] = useState(false);
  const [codexAuthState, setCodexAuthState] = useState<CodexAuthState>();
  const [codexAuthBusy, setCodexAuthBusy] = useState("");
  const [codexAuthMessage, setCodexAuthMessage] = useState("");
  const [projectDraft, setProjectDraft] = useState<ProjectDraft>(emptyProjectDraft);
  const [planningPath, setPlanningPath] = useState("");
  const [planningMode, setPlanningMode] = useState<PlanningMode>("directed");
  const [planningRequest, setPlanningRequest] = useState("");
  const [planningProfiles, setPlanningProfiles] = useState<ProviderProfile[]>([]);
  const [planningProfileKey, setPlanningProfileKey] = useState("");
  const [planningReasoning, setPlanningReasoning] = useState("");
  const [planningEffortMode, setPlanningEffortMode] = useState<EffortMode>("balanced");
  const [planningProfileManual, setPlanningProfileManual] = useState(false);
  const planningRequestDrafts = useRef(new PlanningRequestDrafts());
  const chatDrafts = useSyncExternalStore(planningRequestDrafts.current.subscribe, planningRequestDrafts.current.chatSnapshot);
  const [selectedChatDraft, setSelectedChatDraftState] = useState({ projectName: "", id: "" });
  const selectedChatDraftRef = useRef(selectedChatDraft);
  const setChatDraftSelection = useCallback((projectName: string, id = "") => {
    const target = { projectName, id };
    selectedChatDraftRef.current = target;
    setSelectedChatDraftState(target);
  }, []);
  const planningPreparationsRef = useRef(new Set<string>());
  const planningStartPendingRef = useRef(false);
  const greenfieldActionPendingRef = useRef(false);
  const techStackEntryPendingRef = useRef(false);
  const editedPlanningProfileContext = useRef("");
  const updatePlanningDraft = useCallback((patch: Partial<PlanningRequestDraft>) => {
    if (selectedProjectName && !selectedRunId) planningRequestDrafts.current.update(selectedProjectName, patch,
      selectedChatDraftRef.current.projectName === selectedProjectName ? selectedChatDraftRef.current.id : "");
  }, [selectedProjectName, selectedRunId]);
  const restorePlanningDraft = useCallback((
    projectName: string, path: string, intent: PlanningRequestDraft["repositoryIntent"] = "", fallbackProfileKey = "",
  ) => {
    const chatId = selectedChatDraftRef.current.projectName === projectName ? selectedChatDraftRef.current.id : "";
    let draft = planningRequestDrafts.current.load(projectName, path, intent, chatId);
    if (!draft.profileKey && !draft.profileManual && fallbackProfileKey) {
      draft = planningRequestDrafts.current.update(projectName, { profileKey: fallbackProfileKey }, chatId);
    }
    setPlanningPath(draft.path);
    setPlanningMode(draft.mode);
    setPlanningRequest(draft.request);
    setPlanningEffortMode(draft.effortMode);
    setPlanningProfileKey(draft.profileKey);
    setPlanningReasoning(draft.reasoning);
    setPlanningProfileManual(draft.profileManual);
    setRepositoryIntent(draft.repositoryIntent);
    editedPlanningProfileContext.current = "";
  }, []);
  const planningChatDraft = useSyncExternalStore(directionChangeDrafts.subscribe,
    () => directionChangeDrafts.read(selectedProjectName, selectedRunId));
  const planningMessage = planningChatDraft.text;
  const setPlanningMessage = useCallback((update: string | ((current: string) => string)) => {
    const current = directionChangeDrafts.read(selectedProjectName, selectedRunId).text;
    directionChangeDrafts.edit(selectedProjectName, selectedRunId, typeof update === "function" ? update(current) : update);
  }, [directionChangeDrafts, selectedProjectName, selectedRunId]);
  const [pendingPlanningMessage, setPendingPlanningMessage] = useState<
    PendingPlanningMessage | undefined
  >();
  const [planningIndex, setPlanningIndex] = useState<PlanningSourceIndex>();
  const [providerStatuses, setProviderStatuses] = useState<ProviderStatus[]>([]);
  const [projectCapabilities, setProjectCapabilities] = useState<ProjectCapabilities>();
  const [repositoryIntent, setRepositoryIntent] = useState<"" | "existing_structure" | "new_project">("");
  const [taskProfileOptions, setTaskProfileOptions] = useState<
    Record<string, ProviderProfile[]>
  >({});
  const [nextExecutionProfileDirty, setNextExecutionProfileDirty] = useState(false);
  const [selectedRunProjectName, setSelectedRunProjectName] = useState("");
  const { draft: planDraft, setField: setDraftField, acceptSaved: acceptSavedPlan, discardUntouchedTask } = usePlanDrafts(
    selectedProjectName, selectedRunId,
    selectedRunProjectName === selectedProjectName && selectedRun?.id === selectedRunId ? selectedRun : undefined,
  );
  const taskDrafts = planDraft?.tasks || [];
  const taskProfiles = planDraft?.profiles || {};
  const selectedTaskId = planDraft?.selectedTaskId || "";
  const setSelectedTaskId = useCallback((value: React.SetStateAction<string>) => setDraftField("selectedTaskId", value), [setDraftField]);
  const setTaskDrafts = useCallback((value: React.SetStateAction<WorkTask[]>) => setDraftField("tasks", value), [setDraftField]);
  const setTaskProfiles = useCallback((value: React.SetStateAction<Record<string, TaskProfileSelection>>) => setDraftField("profiles", value), [setDraftField]);
  const setTaskInput = useCallback((taskId: string, input: TaskEditorInput) => {
    setDraftField("inputs", (current) => ({ ...current, [taskId]: input }));
  }, [setDraftField]);
  const [planningPaneWidth, setPlanningPaneWidth] = useState(400);
  const [workMainWidth, setWorkMainWidth] = useState(window.innerWidth);
  const workMainRef = useRef<HTMLDivElement>(null);
  const [inspectorWidth, setInspectorWidth] = useState(360);
  const [sideInspectorOpen, setSideInspectorOpen] = useState(false);
  useEffect(() => { if (sideInspectorOpen) setWorkDetailsOpen(true); }, [sideInspectorOpen]);
  const inspectorScrollMemory = useRef<InspectorScrollMemory>({});
  const logViewsRef = useRef<Record<string, LogViewState>>({});
  const effortModeDraftsRef = useRef<Record<string, EffortMode>>({});
  const [, refreshLogView] = useState(0);
  const workspaceGridRef = useRef<HTMLDivElement>(null);
  const taskWorkbenchBodyRef = useRef<HTMLDivElement>(null);
  const [workStatusTarget, setWorkStatusTarget] = useState<HTMLDivElement | null>(null);
  const [workbenchLayout, setWorkbenchLayout] = useState<WorkbenchLayout>(() => resolveWorkbenchLayout({
    viewportWidth: window.innerWidth,
    groupPaneWidth: 0,
    inspectorWidth: 360,
  }));
  const workbenchLayoutRef = useRef(workbenchLayout);
  const [workListOpen, setWorkListOpen] = useState(false);
  const [applySummaryOpen, setApplySummaryOpen] = useState(false);
  const [applySummaryError, setApplySummaryError] = useState("");
  const [applySummaryChecking, setApplySummaryChecking] = useState(false);
  const applySummarySessionRef = useRef<ApplySummarySession | undefined>(undefined);
  const applySummaryEntryRef = useRef<{ projectName: string; runId: string } | undefined>(undefined);
  const applySummaryOpenerRef = useRef<HTMLElement | null>(null);
  const applySummaryOpenRef = useRef(false);
  const applyCommandPendingRef = useRef(false);
  const openApplySummary = useCallback(() => {
    setWorkDetailsOpen(true);
    if (!applySummaryEntryRef.current && !applySummaryOpenRef.current) {
      applySummaryOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    }
    applySummaryEntryRef.current = undefined;
    setWorkbenchView("operations");
    setApplySummaryOpen(true);
    setApplySummaryError("");
  }, []);
  const closeApplySummary = useCallback(() => {
    const wasOpen = applySummaryOpenRef.current;
    const opener = applySummaryOpenerRef.current;
    applySummaryOpenRef.current = false;
    applySummarySessionRef.current?.dispose();
    applySummarySessionRef.current = undefined;
    setApplySummaryOpen(false);
    setApplySummaryChecking(false);
    if (wasOpen) window.requestAnimationFrame(() => {
      if (document.querySelector("dialog:modal")) return;
      const target = opener?.isConnected && opener.getClientRects().length ? opener : document.querySelector<HTMLButtonElement>(".apply-summary-entry button");
      target?.focus({ preventScroll: true });
    });
  }, []);
  applySummaryOpenRef.current = applySummaryOpen && workDetailsOpen && homeView === "work" && isWorkOverview;
  useEffect(() => { closeApplySummary(); }, [selectedProjectName, selectedRunId, homeView, closeApplySummary]);
  useEffect(() => { if (!isWorkOverview) closeApplySummary(); }, [isWorkOverview, closeApplySummary]);
  useEffect(() => {
    if (!workDetailsOpen || !groupOperationsVisible) closeApplySummary();
    else if (homeView === "work" && isWorkOverview && groupOperationsVisible && selectedRun?.id === selectedRunId
      && selectedRunProjectName === selectedProjectName && !applySummaryOpen) openApplySummary();
  }, [workDetailsOpen, homeView, isWorkOverview, groupOperationsVisible, selectedRun?.id, selectedRunId, selectedRunProjectName,
    selectedProjectName, applySummaryOpen, closeApplySummary, openApplySummary]);
  const [taskContentViews, setTaskContentViews] = useState<Record<string, TaskContentView>>({});
  const [advancedEditorRequest, setAdvancedEditorRequest] = useState<{ key: string; revision: number; field?: TaskDraftError["field"] }>({ key: "", revision: 0 });
  const emptyManualTasksRef = useRef<Record<string, WorkTask>>({});
  const taskScrollPositionsRef = useRef<Record<string, number>>({});
  const taskScrollRestoreRef = useRef<{ key: string; top: number } | undefined>(undefined);
  const [guidanceExpanded, setGuidanceExpanded] = useState<Record<string, boolean>>({});
  const [postponedWaiting, setPostponedWaiting] = useState<Record<string, boolean>>({});
  const [waitingChecks, setWaitingChecks] = useState<Record<string, boolean>>({});
  const waitingInvocations = useRef(new Set<string>());
  const [operationsSnapshot, setOperationsSnapshot] = useState<OperationsSnapshot>();
  const [runLockBlocking, setRunLockBlocking] = useState({ context: "", blocking: false, progress: false });
  const operationsRequestRef = useRef(0);
  const runDetailRequestRef = useRef(0);
  const runListRequestSequenceRef = useRef(0);
  const runListRequestRef = useRef<Record<string, number>>({});
  const taskProfileRequestRef = useRef(0);
  const projectCapabilitiesRequestRef = useRef(0);
  const executionRequestSequenceRef = useRef(0);
  const chatRecoveryPendingRef = useRef(new Set<string>());
  const selectedContextRef = useRef({ projectName: "", runId: "" });
  const busyProjectRef = useRef("");
  const busyRunRef = useRef("");
  const [recoveryQueryRevision, setRecoveryQueryRevision] = useState(0);
  const [chatRecoveryContext, setChatRecoveryContext] = useState<{ key: string; recovery?: import("./types").TaskRetryContext["recovery"] }>({ key: "" });
  const [chatControlViews, setChatControlViews] = useState<ChatControlView[]>([]);
  const [planningRequests, setPlanningRequests] = useState<PlanningRequestsSnapshot>({ recent: [] });
  const [queueSubmitting, setQueueSubmitting] = useState(false);
  const queueSubmittingRef = useRef(false);
  const queuedSubmissionRef = useRef<{ signature: string; id: string } | undefined>(undefined);
  const removingProjectRef = useRef("");
  const setBusyAction = useCallback((action: string, expectedProject?: string, expectedRun?: string) => {
    if (!action && expectedProject !== undefined && (busyProjectRef.current !== expectedProject || busyRunRef.current !== expectedRun)) return;
    busyRunRef.current = action ? expectedRun ?? selectedContextRef.current.runId : "";
    busyProjectRef.current = action ? expectedProject ?? selectedContextRef.current.projectName : "";
    setBusyActionState(action);
  }, []);
  const selectedRunRef = useRef<RunState | undefined>(undefined);
  const archiveScopeRef = useRef<RunListScope>(archiveScope);
  const runSummaryCacheRef = useRef<RunSummaryCache>(runSummaryCache);
  const authoritativeArchivesRef = useRef<Record<string, RunSummary>>({});
  const archiveTransitionRef = useRef<{ projectName: string; runId: string } | undefined>(undefined);
  const archiveRefreshFailureRef = useRef<Record<string, boolean>>({});
  const projectsRef = useRef<RegisteredProject[]>([]);
  const pendingNotificationRef = useRef<StoredWorkNotification | undefined>(undefined);
  const pendingGlobalGroupRef = useRef<{ projectName: string; runId: string } | undefined>(undefined);
  const newWorkProjectRef = useRef("");
  const activeGroupsRequestRef = useRef(false);
  const attentionRequestRef = useRef(false);
  const attentionTriggerRef = useRef<HTMLButtonElement>(null);
  const pendingAttentionRef = useRef<AttentionItem | undefined>(undefined);
  const [attentionFocusRequest, setAttentionFocusRequest] = useState<AttentionFocusRequest>();
  const notificationTriggerRef = useRef<HTMLButtonElement>(null);
  const notificationPanelRef = useRef<HTMLElement>(null);
  const codexAuthOpenRef = useRef(false);
  const codexAuthRequestRef = useRef(0);
  selectedContextRef.current = { projectName: selectedProjectName, runId: selectedRunId };
  selectedRunRef.current = selectedRun;
  archiveScopeRef.current = archiveScope;
  runSummaryCacheRef.current = runSummaryCache;
  projectsRef.current = projects;
  newWorkProjectRef.current = homeView === "work" && workbenchView === "planning" && !selectedRunId ? selectedProjectName : "";

  const planningOwner = planningRequestFor(planningRequests, selectedProjectName, selectedRunId);
  const planningStartErrorKey = selectedChatDraft.id && selectedChatDraft.projectName === selectedProjectName && !selectedRunId
    ? JSON.stringify([selectedProjectName, selectedChatDraft.id]) : selectedProjectName;
  const planningStartError = planningStartErrors[planningStartErrorKey];
  const ownsPlanning = Boolean(planningOwner && planningOwner.projectName === selectedProjectName && planningOwner.runId === selectedRunId);
  const latestPlanningReceipt = [...planningRequests.recent].reverse().find(item => item.projectName === selectedProjectName && item.runId === selectedRunId);
  const planningBusy = PLANNING_REQUEST_METHODS.some(method => method === rawBusyAction) || rawBusyAction === "system.interruptPlanning";
  const localBusyAction = !planningBusy || busyProjectRef.current === selectedProjectName && busyRunRef.current === selectedRunId ? rawBusyAction : "";
  const busyAction = ownsPlanning && planningOwner ? planningOwner.phase === "stopping" ? "system.interruptPlanning"
    : planningOwner.phase === "confirmation_required" ? "system.planningConfirmationRequired" : planningOwner.method : localBusyAction;
  useEffect(() => {
    if (!window.orchestrator.planningRequests) return;
    let active = true, querying = false;
    const poll = async () => {
      if (querying) return;
      querying = true;
      try { const snapshot = await window.orchestrator.planningRequests(); if (active) setPlanningRequests(snapshot);
        if (window.orchestrator.chatControls) { const controls = await window.orchestrator.chatControls(); if (active) setChatControlViews(previous =>
          JSON.stringify(previous) === JSON.stringify(controls) ? previous : controls); } }
      catch { /* Existing backend status reports connection failures; do not guess an owner. */ }
      finally { querying = false; }
    };
    void poll(); const timer = window.setInterval(() => void poll(), 600);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const recoveryTask = selectedRun?.tasks.find(task => task.status === "failed");
  const recoveryContextKey = JSON.stringify([selectedProjectName, selectedRunId, recoveryTask?.id, recoveryTask?.last_attempt_id, recoveryTask?.error, selectedRun?.updated_at]);
  useEffect(() => {
    if (!selectedProjectName || !selectedRunId || !recoveryTask) return;
    let active = true;
    void window.orchestrator.request<import("./types").TaskRetryContext>("tasks.retryContext", {
      projectName: selectedProjectName, runId: selectedRunId, taskId: recoveryTask.id,
    }).then(context => { if (active) setChatRecoveryContext({ key: recoveryContextKey, recovery: context.recovery }); })
      .catch(() => { if (active) setChatRecoveryContext({ key: recoveryContextKey }); });
    return () => { active = false; };
  }, [recoveryContextKey, recoveryQueryRevision]);

  const selectedExecutionRequest = executionRequests[runRequestKey(selectedProjectName, selectedRunId)];
  const executionAction = selectedExecutionRequest?.method || "";
  const selectedExecutionElapsed = selectedExecutionRequest
    ? Math.max(0, Math.floor((executionClock - selectedExecutionRequest.startedAt) / 1000))
    : 0;
  const hasExecutionRequests = Object.keys(executionRequests).length > 0;

  const selectedProject = projects.find(
    (project) => project.name === selectedProjectName,
  );
  const selectedTask = selectedTaskForDetails(selectedRun, taskDrafts, selectedTaskId);
  const taskDialogOpen = Boolean(selectedRun && selectedTask && sideInspectorOpen && homeView === "work" && isWorkOverview
    && (inspectorTab !== "detail" || !taskDetailUsesChat(selectedRun, selectedTask))
    && !workListOpen && !applySummaryOpen && !recoveryOpen && !projectDialogOpen && !projectSettingsOpen && !mainChangesOpen && !codexAuthOpen);
  const previewSurface = planningPreviewSurface(planningPreviewTarget, {
    projectName: selectedProjectName, runId: selectedRun?.id || "", taskId: selectedTask?.id, taskDialogOpen,
  });
  const taskViewContext = `${selectedProjectName}\0${selectedRunId}`;
  const taskContentView = taskContentViews[taskViewContext] || "list";
  const currentScrollView = workbenchLayout === "wide" ? "list" : taskContentView;
  const visibleInspectorTab: InspectorTab = inspectorTab;
  const inspectorContextKey = JSON.stringify([selectedProjectName, selectedRunId, selectedTaskId, visibleInspectorTab]);
  const logViewKey = JSON.stringify([selectedProjectName, selectedRunId, selectedTaskId]);
  const inspectorLogView = logViewsRef.current[logViewKey] || defaultLogView;
  const changeInspectorLogView = useCallback((view: LogViewState) => {
    const previous = logViewsRef.current[logViewKey] || defaultLogView;
    logViewsRef.current[logViewKey] = view;
    if (previous.query !== view.query || previous.wrap !== view.wrap || previous.follow !== view.follow) {
      refreshLogView((version) => version + 1);
    }
  }, [logViewKey]);
  const selectedPlanningProfile = planningProfiles.find(
    (profile) => providerProfileKey(profile) === planningProfileKey,
  );
  const backendRecoveryNeeded = isBackendRecoveryError(error) || runDeletionNeedsBackendRestart(error);
  const planDirty = Boolean(planDraft && planDraftDirty(planDraft));
  const draftConflict = Boolean(planDraft && selectedRun && planDraftConflict(planDraft, selectedRun));
  const draftErrors = planDraft ? planDraftErrors(planDraft) : [];
  const selectedTaskDraftKey = `${selectedProjectName}\0${selectedRunId}\0${selectedTaskId}`;
  const emptySelectedTask = emptyManualTasksRef.current[selectedTaskDraftKey];
  const untouchedSelectedTask = Boolean(planDraft && selectedRun && emptySelectedTask
    && canDiscardUntouchedTaskDraft(planDraft, selectedRun, emptySelectedTask));
  const emptyTaskValidationError = untouchedSelectedTask && advancedEditorRequest.key === selectedTaskDraftKey
    ? draftErrors.find((failure) => failure.taskId === selectedTaskId && failure.field === advancedEditorRequest.field) : undefined;
  const emptyTaskValidationMessage = emptyTaskValidationError
    ? `${taskDraftErrorSummary(emptyTaskValidationError, taskDrafts)} 초안은 유지됩니다.` : "";
  const nextAction = selectedRun ? runNextAction(selectedRun, {
    planDirty,
    pendingAction: executionAction,
  }) : undefined;
  const recoveryGuidance = selectedRun ? runRecoveryGuidance(selectedRun) : undefined;
  const preparationView = Boolean(selectedRun?.stage === "planned" && !selectedRun.archive && isWorkOverview);
  const compactDetails = workbenchView === "results" || preparationView;
  const selectedWaiting = selectedRun && selectedRun.stage !== "ready_to_merge" && !planDirty && !executionAction && waitingPromptAction(selectedRun)
    ? selectedRun.waiting_prompt : undefined;
  const waitingKey = selectedWaiting ? `${taskViewContext}\0${selectedWaiting.source_key}` : "";

  const runStatusFilter = runStatusFilters[selectedProjectName] || "all";
  const runSummaries = useMemo(
    () => runSummaryCache[selectedProjectName]?.[archiveScope] || [],
    [archiveScope, runSummaryCache, selectedProjectName],
  );
  const searchedRunCounts = useMemo(() => runFilterCounts(runSummaries, search), [runSummaries, search]);
  const filteredRuns = useMemo(
    () => filterRuns(runSummaries, search, archiveScope === "active" ? runStatusFilter : "all"),
    [archiveScope, runStatusFilter, runSummaries, search],
  );
  const globalGroups = useMemo(() => visibleActiveGroups(activeGroups, globalSearch), [activeGroups, globalSearch]);
  const confirmedGlobalCount = confirmedActiveGroupCount(activeGroups);

  const updateNotificationPanelPlacement = useCallback(() => {
    const trigger = notificationTriggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewport = window.visualViewport;
    setNotificationPanelPlacement(notificationPanelPosition(rect, {
      width: viewport?.width ?? window.innerWidth,
      height: viewport?.height ?? window.innerHeight,
      offsetLeft: viewport?.offsetLeft ?? 0,
      offsetTop: viewport?.offsetTop ?? 0,
    }));
  }, []);

  const closeNotificationPanel = useCallback((restoreTriggerFocus: boolean) => {
    setNotificationPanelOpen(false);
    if (restoreTriggerFocus) window.requestAnimationFrame(() => notificationTriggerRef.current?.focus());
  }, []);

  const setCurrentTaskContentView = useCallback((view: TaskContentView) => {
    setTaskContentViews((current) => ({ ...current, [taskViewContext]: view }));
  }, [taskViewContext]);

  useEffect(() => {
    const node = workspaceGridRef.current;
    if (!node) return;
    const update = (viewportWidth: number) => {
      const next = resolveWorkbenchLayout({
        viewportWidth,
        groupPaneWidth: 0,
        inspectorWidth,
        previous: workbenchLayoutRef.current,
      });
      if (next === workbenchLayoutRef.current) return;
      const active = document.activeElement instanceof HTMLElement && node.contains(document.activeElement)
        ? document.activeElement.id
        : "";
      workbenchLayoutRef.current = next;
      setWorkbenchLayout(next);
      if (active) window.requestAnimationFrame(() => {
        const target = document.getElementById(active);
        if (target?.getClientRects().length) target.focus({ preventScroll: true });
        else {
          const nextId = active.replace(/^(side|task)-inspector/, inspectorPanelId(next));
          const nextTarget = document.getElementById(nextId);
          if (nextTarget?.getClientRects().length) nextTarget.focus({ preventScroll: true });
          else node.querySelector<HTMLButtonElement>('.task-flow-card[data-selected="true"]')?.focus({ preventScroll: true });
        }
      });
    };
    update(node.getBoundingClientRect().width || window.innerWidth);
    if (typeof ResizeObserver === "undefined") {
      const onResize = () => update(node.getBoundingClientRect().width || window.innerWidth);
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }
    const observer = new ResizeObserver((entries) => update(entries[0]?.contentRect.width || window.innerWidth));
    observer.observe(node);
    return () => observer.disconnect();
  }, [inspectorWidth]);

  useLayoutEffect(() => {
    const node = taskWorkbenchBodyRef.current;
    if (!node || !isWorkOverview) return;
    const key = `${taskViewContext}\0${currentScrollView}`;
    const pending = taskScrollRestoreRef.current;
    if (pending?.key === key && groupOperationsVisible && !applySummaryOpen) return;
    const position = pending?.key === key ? pending.top : workbenchLayout !== "wide" && currentScrollView !== "list"
      ? inspectorScrollMemory.current[inspectorContextKey]?.top || 0
      : taskScrollPositionsRef.current[key] || 0;
    node.scrollTop = position;
    if (pending?.key === key) {
      const frame = window.requestAnimationFrame(() => {
        node.scrollTop = pending.top;
        if (taskScrollRestoreRef.current === pending) taskScrollRestoreRef.current = undefined;
      });
      return () => window.cancelAnimationFrame(frame);
    }
  }, [applySummaryOpen, currentScrollView, groupOperationsVisible, inspectorContextKey, isWorkOverview, taskViewContext, workbenchLayout, workbenchView]);

  useLayoutEffect(() => {
    if (workbenchView === "results" && taskWorkbenchBodyRef.current) taskWorkbenchBodyRef.current.scrollTop = 0;
  }, [resultFocusTaskId, taskViewContext, workbenchView]);

  const selectProject = useCallback((projectName: string) => {
    if (pendingAttentionRef.current?.project_name !== projectName) pendingAttentionRef.current = undefined;
    const context = projectRunContext(selectedContextRef.current, projectName);
    if (context !== selectedContextRef.current) {
      setChatDraftSelection(projectName);
      selectedContextRef.current = context;
      runDetailRequestRef.current += 1;
      operationsRequestRef.current += 1;
      setSelectedRunId("");
      setSelectedRun(undefined);
      setSelectedRunProjectName("");
      setError("");
    }
    setSelectedProjectName(projectName);
  }, [setChatDraftSelection]);

  const loadProjects = useCallback(async () => {
    setBackendChecked(false);
    setLoading(true);
    setError("");
    try {
      if (!window.orchestrator) {
        throw new Error("Electron preload API를 찾을 수 없습니다.");
      }
      const hello = await window.orchestrator.request<{
        rpcVersion: number;
        application: string;
      }>("system.hello");
      if (hello.rpcVersion !== 1 || hello.application !== "ai-work-orchestrator") {
        throw new Error("지원하지 않는 실행 엔진 프로토콜입니다.");
      }
      setBackendChecked(true);
      const result = await window.orchestrator.request<RegisteredProject[]>(
        "projects.list",
      );
      setProjects(result);
      setProjectsLoaded(true);
      const currentProject = selectedContextRef.current.projectName;
      selectProject(result.some((project) => project.name === currentProject) ? currentProject : result[0]?.name || "");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [selectProject]);

  const loadActiveGroups = useCallback(async () => {
    if (!backendChecked) return;
    if (activeGroupsRequestRef.current) return;
    activeGroupsRequestRef.current = true;
    setActiveGroupsLoading(true);
    try {
      const snapshot = await window.orchestrator.request<ActiveGroupSnapshot>("runs.activeGroups");
      setActiveGroups((current) => reconcileActiveGroups(current, snapshot));
      setActiveGroupsError("");
    } catch (requestError) {
      const message = errorMessage(requestError);
      setActiveGroupsError(message);
      setActiveGroups((current) => ({
        ...current,
        items: current.items.map((item) => ({ ...item, status: "check_required" as const, activity_kinds: [], stale: true })),
      }));
    } finally {
      activeGroupsRequestRef.current = false;
      setActiveGroupsLoading(false);
    }
  }, [backendChecked]);

  const loadAttentionItems = useCallback(async () => {
    if (!backendChecked) return;
    if (attentionRequestRef.current) return;
    attentionRequestRef.current = true;
    setAttentionLoading(true);
    try {
      const incoming = await window.orchestrator.request<AttentionSnapshot>("runs.attentionItems");
      setAttentionSnapshot((current) => reconcileAttentionItems(current, incoming));
      setAttentionError("");
    } catch (requestError) {
      setAttentionError(errorMessage(requestError));
      setAttentionSnapshot(uncertainAttentionSnapshot);
    } finally {
      attentionRequestRef.current = false;
      setAttentionLoading(false);
    }
  }, [backendChecked]);

  const loadRuns = useCallback(async ({
    projectName,
    scope,
    preferredRun = "",
    selectFirst = true,
    archiveRefresh = false,
  }: LoadRunsOptions) => {
    if (!projectName) {
      setSelectedRun(undefined);
      return;
    }
    const requestKey = `${projectName}\0${scope}`;
    const requestId = ++runListRequestSequenceRef.current;
    runListRequestRef.current[requestKey] = requestId;
    const isVisible = () => selectedContextRef.current.projectName === projectName
      && archiveScopeRef.current === scope;
    if (isVisible()) {
      setLoading(true);
      if (!archiveRefresh) setError("");
    }
    try {
      const result = await window.orchestrator.request<RunSummary[]>("runs.list", {
        projectName,
        scope,
      });
      if (runListRequestRef.current[requestKey] !== requestId) return;
      const authoritativeArchives = Object.entries(authoritativeArchivesRef.current)
        .filter(([key]) => key.startsWith(`${projectName}\0`))
        .map(([, summary]) => summary);
      const nextCache = reconcileRunScope(
        runSummaryCacheRef.current,
        projectName,
        scope,
        result,
        authoritativeArchives,
      );
      runSummaryCacheRef.current = nextCache;
      setRunSummaryCache(nextCache);
      const reconciled = nextCache[projectName]?.[scope] || [];
      if (!isVisible()) return;
      if (archiveRefresh) {
        setRunListRefreshRetry(undefined);
        if (archiveRefreshFailureRef.current[requestKey]) {
          delete archiveRefreshFailureRef.current[requestKey];
          setNotice("보관 목록을 최신 상태로 확인했습니다.");
        }
      }
      if (newWorkProjectRef.current === projectName) return;
      if (preferredRun && !reconciled.some((run) => run.id === preferredRun)) {
        if (pendingAttentionRef.current?.project_name === projectName && pendingAttentionRef.current.run_id === preferredRun) {
          pendingAttentionRef.current = undefined;
          setNotice("처리할 일의 작업 그룹을 찾을 수 없습니다. 최신 목록을 다시 확인해 주세요.");
          void loadAttentionItems();
        }
        if (pendingGlobalGroupRef.current?.projectName === projectName && pendingGlobalGroupRef.current.runId === preferredRun) {
          pendingGlobalGroupRef.current = undefined;
          setNotice("선택한 작업 그룹을 현재 프로젝트에서 찾을 수 없습니다. 진행 목록을 다시 확인해 주세요.");
          void loadActiveGroups();
        }
        const pending = pendingNotificationRef.current;
        if (pending?.project_name === projectName && pending.run_id === preferredRun) {
          pendingNotificationRef.current = undefined;
          setNotice("알림 대상 작업 그룹을 찾을 수 없습니다. 삭제되었거나 프로젝트에서 제외되었습니다.");
        }
        setSelectedRunId("");
        return;
      }
      if (!selectFirst) {
        return;
      }
      setSelectedRunId((current) => {
        const preferred = preferredRun || current;
        return reconciled.some((run) => run.id === preferred)
          ? preferred
          : reconciled[0]?.id || "";
      });
      if (pendingGlobalGroupRef.current?.projectName === projectName && pendingGlobalGroupRef.current.runId === preferredRun) {
        pendingGlobalGroupRef.current = undefined;
      }
    } catch (requestError) {
      if (runListRequestRef.current[requestKey] !== requestId || !isVisible()) return;
      if (archiveRefresh) {
        archiveRefreshFailureRef.current[requestKey] = true;
        setRunListRefreshRetry({ projectName, scope, preferredRun, archiveRefresh: true });
        setNotice("기록 보관 완료 · 목록을 다시 확인하지 못했습니다.");
      } else {
        setError(errorMessage(requestError));
      }
    } finally {
      if (runListRequestRef.current[requestKey] === requestId && isVisible()) setLoading(false);
    }
  }, [loadActiveGroups, loadAttentionItems]);

  const openWorkNotification = useCallback(async (notification: StoredWorkNotification) => {
    try {
      setNotifications(await window.orchestrator.markNotificationRead(notification.event_id));
      setNotificationActionError("");
    } catch {
      setNotificationActionError("읽음 상태를 저장하지 못했습니다. 다시 시도해 주세요.");
      setNotificationPanelOpen(true);
      return;
    }
    if (notification.target_kind === "notification_refresh" || notification.target_kind === "connection") {
      try { setNotifications(await window.orchestrator.listNotifications()); }
      catch { setNotificationActionError("현재 알림 진단을 확인하지 못했습니다. 다시 확인해 주세요."); }
      updateNotificationPanelPlacement();
      setNotificationPanelOpen(true);
      return;
    }
    setNotificationPanelOpen(false);
    let availableProjects = projectsRef.current;
    if (!availableProjects.length) {
      try {
        availableProjects = await window.orchestrator.request<RegisteredProject[]>("projects.list");
        setProjects(availableProjects);
      } catch (requestError) {
        setNotice(`알림 대상을 확인할 수 없습니다. ${errorMessage(requestError)}`);
        return;
      }
    }
    if (!availableProjects.some((project) => project.name === notification.project_name)) {
      setNotice("알림 대상 프로젝트를 찾을 수 없습니다. 등록 목록에서 제외되었을 수 있습니다.");
      return;
    }
    pendingNotificationRef.current = notification;
    setHomeView("work");
    setSideInspectorOpen(false);
    archiveScopeRef.current = "active";
    setArchiveScope("active");
    if (selectedContextRef.current.projectName === notification.project_name) {
      setSelectedRun(undefined);
      setSelectedRunId("");
      await loadRuns({
        projectName: notification.project_name,
        scope: "active",
        preferredRun: notification.run_id,
      });
    } else {
      selectProject(notification.project_name);
    }
  }, [loadRuns, selectProject, setNotifications, updateNotificationPanelPlacement]);

  const loadRunDetail = useCallback(async (projectName: string, runId: string) => {
    const requestId = ++runDetailRequestRef.current;
    if (!projectName || !runId) {
      setSelectedRun(undefined);
      return;
    }
    try {
      const result = await window.orchestrator.request<RunState>("runs.get", {
        projectName,
        runId,
      });
      if (requestId === runDetailRequestRef.current && runContextMatches(
        selectedContextRef.current.projectName,
        selectedContextRef.current.runId,
        projectName,
        runId,
      )) {
        setSelectedRunProjectName(projectName);
        setSelectedRun(result);
      }
    } catch (requestError) {
      if (requestId === runDetailRequestRef.current && runContextMatches(
        selectedContextRef.current.projectName,
        selectedContextRef.current.runId,
        projectName,
        runId,
      )) {
        const message = errorMessage(requestError);
        const missingMessage = runMissingMessage(requestError);
        if (pendingAttentionRef.current?.project_name === projectName && pendingAttentionRef.current.run_id === runId) {
          pendingAttentionRef.current = undefined;
          setNotice(`처리할 일의 최신 상태를 확인하지 못했습니다. ${message}`);
          void loadAttentionItems();
        }
        if (missingMessage) {
          setSelectedRunId("");
          setSelectedRun(undefined);
          setSelectedRunProjectName("");
          setSelectedTaskId("");
          setSelectedTaskIds([]);
          setError("");
          setNotice(missingMessage);
          await loadRuns({ projectName, scope: archiveScopeRef.current, selectFirst: false });
          return;
        }
        setSelectedRun((current) => current && runContextMatches(
          selectedContextRef.current.projectName,
          selectedContextRef.current.runId,
          projectName,
          runId,
        )
          ? {
            ...current,
            execution_control: unknownRunExecutionControl(
              `실행 상태 조회에 실패했습니다. 상태를 다시 확인해 주세요. ${message}`,
            ),
            integration_control: unknownIntegrationControl(
              `Main 상태를 확인하지 못했습니다. 상태를 다시 확인해 주세요. ${message}`,
            ),
          }
          : current);
        setError(message);
      }
    }
  }, [loadAttentionItems]);

  const refreshSelectedRunStatus = useCallback(async () => {
    if (!selectedProjectName || !selectedRunId) return;
    setBusyAction("runs.get");
    try {
      await loadRunDetail(selectedProjectName, selectedRunId);
    } finally {
      setBusyAction("");
    }
  }, [loadRunDetail, selectedProjectName, selectedRunId]);

  const loadProjectCapabilities = useCallback(async (projectName: string) => {
    if (!projectName) return false;
    const requestId = ++projectCapabilitiesRequestRef.current;
    try {
      const [profiles, statuses, capabilities] = await Promise.all([
        window.orchestrator.request<ProviderProfile[]>("providers.planning", {
          projectName,
        }),
        window.orchestrator.request<ProviderStatus[]>("providers.status", {
          projectName,
        }),
        window.orchestrator.request<ProjectCapabilities>("projects.capabilities", {
          projectName,
        }),
      ]);
      if (requestId !== projectCapabilitiesRequestRef.current || selectedContextRef.current.projectName !== projectName) return false;
      setPlanningProfiles(profiles);
      setProviderStatuses(statuses);
      setProjectCapabilities(capabilities);
      const chatId = selectedChatDraftRef.current.projectName === projectName ? selectedChatDraftRef.current.id : "";
      const draft = planningRequestDrafts.current.load(projectName, "", "", chatId);
      const intent = planningRepositoryIntent(capabilities.repository_maturity.kind, draft.repositoryIntent);
      planningRequestDrafts.current.update(projectName, { repositoryIntent: intent }, chatId);
      setRepositoryIntent(intent);
      setPlanningProfileKey((current) => {
        if (profiles.some((profile) => providerProfileKey(profile) === current)) {
          return current;
        }
        if (selectedContextRef.current.runId && current) return current;
        const draft = planningRequestDrafts.current.load(projectName, "", "", chatId);
        if (!selectedContextRef.current.runId && draft.profileManual && draft.profileKey) return draft.profileKey;
        const defaultProfile = profiles.find(
          (profile) =>
            profile.is_default && profile.model === profile.configured_model,
        );
        const key = providerProfileKey(defaultProfile || profiles[0]);
        if (!selectedContextRef.current.runId) planningRequestDrafts.current.update(projectName, { profileKey: key }, chatId);
        return key;
      });
      return true;
    } catch (requestError) {
      if (requestId === projectCapabilitiesRequestRef.current && selectedContextRef.current.projectName === projectName) {
        setPlanningProfiles([]);
        setProviderStatuses([]);
        setTaskProfileOptions({});
        setError(errorMessage(requestError));
      }
      return false;
    }
  }, []);

  const refreshProviderStatuses = useCallback(async () => {
    if (!selectedProjectName) return;
    setBusyAction("providers.status");
    setError("");
    setNotice("");
    try {
      if (await loadProjectCapabilities(selectedProjectName)) setNotice("AI 제공자 인증 상태와 모델 목록을 새로고침했습니다.");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction("");
    }
  }, [loadProjectCapabilities, selectedProjectName]);

  const acceptCodexAuthState = useCallback(async (state: CodexAuthState, requestId: number) => {
    if (!codexAuthOpenRef.current || requestId !== codexAuthRequestRef.current) return;
    setCodexAuthState(state);
    if (!selectedProjectName) return;
    try {
      const updated = await loadProjectCapabilities(selectedProjectName);
      if (!updated && codexAuthOpenRef.current && requestId === codexAuthRequestRef.current
        && selectedContextRef.current.projectName === selectedProjectName) {
        setCodexAuthMessage("AI 모델 목록을 갱신하지 못했습니다. 연결을 다시 확인해 주세요.");
      }
    } catch (requestError) {
      setCodexAuthMessage(`AI 모델 목록을 갱신하지 못했습니다. ${errorMessage(requestError)}`);
    }
  }, [loadProjectCapabilities, selectedProjectName]);

  const refreshCodexAuth = useCallback(async () => {
    const requestId = ++codexAuthRequestRef.current;
    const isCurrent = () => codexAuthOpenRef.current && requestId === codexAuthRequestRef.current;
    setCodexAuthBusy("status");
    setCodexAuthMessage("");
    setCodexAuthState(undefined);
    try {
      const state = await window.orchestrator.codexAuthStatus();
      if (isCurrent()) await acceptCodexAuthState(state, requestId);
    } catch (requestError) {
      if (!isCurrent()) return;
      await acceptCodexAuthState({
        status: "status_error", attempt_id: "", method: "", started_at: "", auth_method: "none", auth_label: "",
        account_email: "", plan_type: "", user_code: "", error_code: "account_status_failed", browser_open_error: "",
        message: "현재 연결 정보를 확인하지 못했습니다. 연결 다시 확인을 눌러 주세요.",
      }, requestId);
      if (isCurrent()) setCodexAuthMessage(errorMessage(requestError));
    } finally {
      if (isCurrent()) setCodexAuthBusy("");
    }
  }, [acceptCodexAuthState]);

  const openCodexAuth = useCallback(() => {
    codexAuthOpenRef.current = true;
    setCodexAuthState(undefined);
    setCodexAuthMessage("");
    setCodexAuthOpen(true);
    void refreshCodexAuth();
  }, [refreshCodexAuth]);

  const closeCodexAuth = useCallback(() => {
    codexAuthOpenRef.current = false;
    codexAuthRequestRef.current++;
    setCodexAuthOpen(false);
    setCodexAuthState(undefined);
    setCodexAuthMessage("");
  }, []);

  const startCodexAuth = useCallback(async (method: CodexAuthMethod) => {
    const requestId = ++codexAuthRequestRef.current;
    setCodexAuthBusy("start");
    setCodexAuthMessage("");
    try {
      await acceptCodexAuthState(await window.orchestrator.startCodexAuth(method, crypto.randomUUID()), requestId);
    } catch (requestError) {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthMessage(errorMessage(requestError));
    } finally {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthBusy("");
    }
  }, [acceptCodexAuthState]);

  const connectCodexApiKey = useCallback(async (apiKey: string) => {
    const requestId = ++codexAuthRequestRef.current;
    setCodexAuthBusy("api_key");
    setCodexAuthMessage("");
    try {
      await acceptCodexAuthState(await window.orchestrator.connectCodexApiKey(apiKey, crypto.randomUUID()), requestId);
    } catch {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) {
        setCodexAuthMessage("Codex API 키 연결을 확인하지 못했습니다. 연결 상태를 다시 확인해 주세요.");
      }
    } finally {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthBusy("");
    }
  }, [acceptCodexAuthState]);

  const cancelCodexAuth = useCallback(async () => {
    if (!codexAuthState?.attempt_id) return;
    const requestId = ++codexAuthRequestRef.current;
    setCodexAuthBusy("cancel");
    setCodexAuthMessage("");
    try {
      await acceptCodexAuthState(await window.orchestrator.cancelCodexAuth(codexAuthState.attempt_id), requestId);
    } catch (requestError) {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthMessage(errorMessage(requestError));
    } finally {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthBusy("");
    }
  }, [acceptCodexAuthState, codexAuthState?.attempt_id]);

  const reopenCodexAuth = useCallback(async () => {
    if (!codexAuthState?.attempt_id) return;
    const requestId = ++codexAuthRequestRef.current;
    setCodexAuthBusy("reopen");
    setCodexAuthMessage("");
    try {
      await acceptCodexAuthState(await window.orchestrator.reopenCodexAuth(codexAuthState.attempt_id), requestId);
    } catch (requestError) {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthMessage(errorMessage(requestError));
    } finally {
      if (codexAuthOpenRef.current && requestId === codexAuthRequestRef.current) setCodexAuthBusy("");
    }
  }, [acceptCodexAuthState, codexAuthState?.attempt_id]);

  const copyCodexDeviceCode = useCallback(async () => {
    if (!codexAuthState?.attempt_id) return;
    try {
      const copied = await window.orchestrator.copyCodexDeviceCode(codexAuthState.attempt_id);
      setCodexAuthMessage(copied ? "기기 코드를 복사했습니다." : "복사할 기기 코드를 찾지 못했습니다.");
    } catch (requestError) {
      setCodexAuthMessage(errorMessage(requestError));
    }
  }, [codexAuthState?.attempt_id]);

  const loadTaskProfiles = useCallback(
    async (projectName: string, run: RunState) => {
      const requestId = ++taskProfileRequestRef.current;
      try {
        const capabilitiesByKey = new Map<string, string[]>();
        for (const task of run.tasks) {
          const key = capabilityKey(task.capabilities);
          if (!capabilitiesByKey.has(key)) {
            capabilitiesByKey.set(key, task.capabilities);
          }
        }
        const profileEntries = await Promise.all(
          [...capabilitiesByKey].map(async ([key, capabilities]) => {
            const options = await window.orchestrator.request<ProviderProfile[]>(
              "providers.execution",
              { projectName, capabilities },
            );
            return [key, options] as const;
          }),
        );
        const profilesByCapability = Object.fromEntries(profileEntries);
        const options = Object.fromEntries(
          run.tasks.map((task) => [
            task.id,
            profilesByCapability[capabilityKey(task.capabilities)] || [],
          ]),
        );
        if (requestId === taskProfileRequestRef.current && runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, run.id)) {
          setTaskProfileOptions(options);
        }
      } catch (requestError) {
        if (requestId === taskProfileRequestRef.current && runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, run.id)) {
          setTaskProfileOptions({});
          setError(errorMessage(requestError));
        }
      }
    },
    [],
  );

  const loadOperations = useCallback(async () => {
    if (!selectedProjectName || !selectedRunId) return;
    const projectName = selectedProjectName;
    const runId = selectedRunId;
    const requestId = ++operationsRequestRef.current;
    const isCurrent = () => requestId === operationsRequestRef.current && runContextMatches(
      selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId,
    );
    setOperationsSnapshot({ projectName, runId, runUpdatedAt: "", mainOperationsSignature: "", status: "loading", workspaces: [], checkedAt: "", error: "" });
    try {
      const result = await readConsistentOperations(projectName, runId, window.orchestrator.request);
      if (!isCurrent()) return;
      const current = selectedRunRef.current;
      if (current?.id === runId && Date.parse(current.updated_at) > Date.parse(result.run.updated_at)) {
        throw new Error("새 작업 그룹 상태가 도착했습니다. 운영 상태를 다시 확인해 주세요.");
      }
      runDetailRequestRef.current += 1;
      setSelectedRunProjectName(projectName);
      setSelectedRun(result.run);
      setOperationsSnapshot(result.snapshot);
    } catch (requestError) {
      if (!isCurrent()) return;
      const missingMessage = runMissingMessage(requestError);
      if (missingMessage) {
        setSelectedRunId("");
        setSelectedRun(undefined);
        setSelectedRunProjectName("");
        setSelectedTaskId("");
        setSelectedTaskIds([]);
        setError("");
        setNotice(missingMessage);
        await loadRuns({ projectName, scope: archiveScopeRef.current, selectFirst: false });
        return;
      }
      const message = errorMessage(requestError);
      setOperationsSnapshot({ projectName, runId, runUpdatedAt: "", mainOperationsSignature: "", status: "error", workspaces: [], checkedAt: "", error: message });
      setError(message);
    }
  }, [loadRuns, selectedProjectName, selectedRunId, setSelectedTaskId]);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    try { window.localStorage.setItem("ai-orchestrator-group-list-mode", groupListMode); }
    catch { /* Local storage may be unavailable in a restricted renderer. */ }
  }, [groupListMode]);

  useEffect(() => {
    if (!projects.length) return;
    void loadActiveGroups();
    const timer = window.setInterval(() => void loadActiveGroups(), 10000);
    return () => window.clearInterval(timer);
  }, [loadActiveGroups, projects]);

  const attentionRefreshKey = selectedRun ? JSON.stringify([
    selectedProjectName, selectedRun.id, selectedRun.stage, selectedRun.plan_revision, selectedRun.plan_approved_revision,
    selectedRun.tasks.map((task) => [task.id, task.status]),
    selectedRun.direction_change_requests?.map((item) => [item.request_id, item.status]), selectedRun.archive?.archived_at,
  ]) : "";
  useEffect(() => { void loadAttentionItems(); }, [loadAttentionItems, projects, attentionRefreshKey]);
  useEffect(() => {
    const timer = window.setInterval(() => void loadAttentionItems(), 10000);
    return () => window.clearInterval(timer);
  }, [loadAttentionItems]);

  useEffect(() => {
    if (!hasExecutionRequests) return;
    setExecutionClock(Date.now());
    const timer = window.setInterval(() => setExecutionClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [hasExecutionRequests]);

  useEffect(() => window.orchestrator.onOpenProjectSettings(() => {
    if (!selectedProjectName) {
      setNotice("설정을 열 프로젝트를 먼저 선택하거나 등록해 주세요.");
    } else if (busyAction || hasExecutionRequests) {
      setNotice("현재 요청이 끝난 뒤 프로젝트 설정을 열어 주세요.");
    } else {
      setProjectSettingsOpen(true);
    }
  }), [selectedProjectName, busyAction, hasExecutionRequests]);

  useEffect(() => window.orchestrator.onOpenCodexAuth(openCodexAuth), [openCodexAuth]);

  useEffect(() => {
    if (!codexAuthOpen || !codexAuthState?.attempt_id || !codexAuthIsPending(codexAuthState)) return;
    let active = true;
    const poll = async () => {
      const requestId = codexAuthRequestRef.current;
      try {
        const state = await window.orchestrator.getCodexAuth(codexAuthState.attempt_id);
        if (!active) return;
        await acceptCodexAuthState(state, requestId);
      } catch (requestError) {
        if (active) setCodexAuthMessage(errorMessage(requestError));
      }
    };
    const timer = window.setInterval(() => void poll(), 1000);
    void poll();
    return () => { active = false; window.clearInterval(timer); };
  }, [acceptCodexAuthState, codexAuthOpen, codexAuthState?.attempt_id, codexAuthState?.status]);

  useEffect(() => {
    let active = true;
    void window.orchestrator.listNotifications()
      .then((snapshot) => { if (active) setNotifications(snapshot); })
      .catch((requestError) => { if (active) setNotice(`알림함을 불러오지 못했습니다. ${errorMessage(requestError)}`); });
    const removeChanged = window.orchestrator.onNotificationsChanged((snapshot) => {
      if (active) setNotifications(snapshot);
    });
    const removeOpen = window.orchestrator.onNotificationOpen((notification) => {
      if (active) void openWorkNotification(notification);
    });
    return () => {
      active = false;
      removeChanged();
      removeOpen();
    };
  }, [openWorkNotification]);

  useEffect(() => {
    if (!notificationPanelOpen) return;
    const closeOnPointer = (event: PointerEvent) => {
      const path = event.composedPath();
      const trigger = notificationTriggerRef.current;
      const panel = notificationPanelRef.current;
      if ((trigger && path.includes(trigger)) || (panel && path.includes(panel))) return;
      setNotificationPanelOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && !event.isComposing) closeNotificationPanel(true);
    };
    const updatePlacement = () => updateNotificationPanelPlacement();
    updatePlacement();
    document.addEventListener("pointerdown", closeOnPointer, true);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", updatePlacement);
    window.visualViewport?.addEventListener("resize", updatePlacement);
    window.visualViewport?.addEventListener("scroll", updatePlacement);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointer, true);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", updatePlacement);
      window.visualViewport?.removeEventListener("resize", updatePlacement);
      window.visualViewport?.removeEventListener("scroll", updatePlacement);
    };
  }, [closeNotificationPanel, notificationPanelOpen, updateNotificationPanelPlacement]);

  useEffect(() => {
    if (recoveryOpen || planningPreviewTarget || applySummaryOpen || projectDialogOpen || projectSettingsOpen || mainChangesOpen || codexAuthOpen) {
      setNotificationPanelOpen(false);
    }
  }, [applySummaryOpen, codexAuthOpen, mainChangesOpen, planningPreviewTarget, projectDialogOpen, projectSettingsOpen, recoveryOpen]);

  useEffect(() => {
    setPlanningPreviewTarget((current) => current && current.projectName === selectedProjectName && current.runId === selectedRunId ? current : undefined);
  }, [selectedProjectName, selectedRunId]);

  useEffect(() => {
    setSelectedRunId("");
    setSelectedTaskIds([]);
    setSelectedRun(undefined);
    setTaskProfileOptions({});
    setProjectCapabilities(undefined);
    setPlanningIndex(undefined);
    setPlanningPreparationMessage("");
    setPendingPlanningMessage(undefined);
    const project = projectsRef.current.find((item) => item.name === selectedProjectName);
    restorePlanningDraft(selectedProjectName, project?.planning_source_dir || "");
  }, [restorePlanningDraft, selectedProjectName]);

  useEffect(() => { void loadProjectCapabilities(selectedProjectName); }, [loadProjectCapabilities, projects, selectedProjectName]);

  useEffect(() => {
    const transition = archiveTransitionRef.current;
    if (archiveScope === "archived" && transition?.projectName === selectedProjectName) {
      archiveTransitionRef.current = undefined;
      return;
    }
    const pending = pendingNotificationRef.current;
    const pendingGlobal = pendingGlobalGroupRef.current;
    const preferredRun = pendingGlobal?.projectName === selectedProjectName ? pendingGlobal.runId
      : pending?.project_name === selectedProjectName ? pending.run_id : selectedContextRef.current.runId;
    void loadRuns({
      projectName: selectedProjectName, scope: archiveScope, preferredRun,
      selectFirst: groupListMode === "project" || Boolean(preferredRun),
    });
  }, [archiveScope, groupListMode, loadRuns, selectedProjectName]);

  useEffect(() => {
    operationsRequestRef.current += 1;
    setOperationsSnapshot(undefined);
    setSelectedTaskIds([]);
    setTaskProfileOptions({});
    void loadRunDetail(selectedProjectName, selectedRunId);
  }, [loadRunDetail, selectedProjectName, selectedRunId]);

  useEffect(() => {
    if (selectedRun && selectedRunProjectName === selectedProjectName && selectedRun.id === selectedRunId) {
      void loadTaskProfiles(selectedProjectName, selectedRun);
      setPlanningMode(selectedRun.planning_mode || "auto");
      setPlanningRequest(selectedRun.planning_request || "");
      const matchingProfile = planningProfiles.find(
        (profile) =>
          profile.agent_id === selectedRun.planning_agent_id &&
          profile.model === selectedRun.planning_model,
      );
      if (editedPlanningProfileContext.current !== `${selectedProjectName}\0${selectedRun.id}`) {
        setPlanningProfileManual(false);
        setPlanningReasoning(selectedRun.planning_reasoning_effort || "");
        if (matchingProfile) setPlanningProfileKey(providerProfileKey(matchingProfile));
        else if (selectedRun.planning_agent_id) setPlanningProfileKey("");
      }
    }
  }, [loadTaskProfiles, planningProfiles, selectedProjectName, selectedRun, selectedRunId, selectedRunProjectName]);

  useEffect(() => {
    const pending = pendingAttentionRef.current;
    if (!pending || !selectedRun || selectedRunProjectName !== pending.project_name || selectedRun.id !== pending.run_id) return;
    const navigation = attentionNavigation(pending, selectedRun);
    setWorkbenchView(navigation.view);
    setInspectorTab("detail");
    if (navigation.taskId) {
      setSelectedTaskId(navigation.taskId);
      setSideInspectorOpen(true);
      if (workbenchLayout !== "wide") setCurrentTaskContentView("detail");
    }
    if (navigation.changed) setNotice("작업 그룹의 최신 상태를 확인했습니다. 현재 화면의 다음 행동을 확인하세요.");
    setAttentionFocusRequest({
      projectName: pending.project_name, runId: pending.run_id, view: navigation.view,
      taskId: navigation.taskId, kind: pending.kind,
      waitingSourceKey: waitingPromptAction(selectedRun) ? selectedRun.waiting_prompt?.source_key || "" : "",
    });
    pendingAttentionRef.current = undefined;
  }, [selectedRun, selectedRunProjectName, setCurrentTaskContentView, setSelectedTaskId, workbenchLayout]);

  useAttentionNavigationFocus(attentionFocusRequest, {
    projectName: selectedRunProjectName === selectedProjectName ? selectedProjectName : "",
    runId: selectedRun?.id === selectedRunId ? selectedRunId : "",
    view: workbenchView, taskId: selectedTaskId,
    waitingSourceKey: selectedWaiting && !postponedWaiting[waitingKey] ? selectedWaiting.source_key : "",
    inspectorTitleId: "task-dialog-title",
  }, workspaceGridRef);

  useEffect(() => {
    const pending = pendingNotificationRef.current;
    if (!pending || !selectedRun || selectedRunProjectName !== pending.project_name || selectedRun.id !== pending.run_id) return;
    const navigation = notificationNavigation(pending);
    setWorkbenchView(navigation.view);
    if (navigation.view === "results") setResultFocusTaskId(navigation.taskId);
    setInspectorTab(navigation.inspector);
    if (navigation.taskId) {
      if (!selectedRun.tasks.some((task) => task.id === navigation.taskId)) {
        setNotice("알림 대상 작업을 찾을 수 없습니다. 작업 그룹 상태가 변경되었을 수 있습니다.");
      } else {
        setSelectedTaskId(navigation.taskId);
        setSideInspectorOpen(true);
        if (workbenchLayout !== "wide") setCurrentTaskContentView(navigation.inspector);
      }
    }
    pendingNotificationRef.current = undefined;
  }, [selectedRun, selectedRunProjectName, setCurrentTaskContentView, setSelectedTaskId, workbenchLayout]);

  useEffect(() => {
    const entry = applySummaryEntryRef.current;
    if (!entry) return;
    if (homeView !== "work" || workbenchView !== "operations" || selectedProjectName !== entry.projectName) {
      applySummaryEntryRef.current = undefined;
      return;
    }
    if (!selectedRun || selectedRun.id !== selectedRunId || selectedRunProjectName !== entry.projectName) return;
    if (selectedRun.id === entry.runId) openApplySummary();
    else applySummaryEntryRef.current = undefined;
  }, [homeView, openApplySummary, selectedProjectName, selectedRun, selectedRunId, selectedRunProjectName, workbenchView]);

  useEffect(() => {
    if (homeView === "work" && workDetailsOpen && isWorkOverview && groupOperationsVisible) void loadOperations();
  }, [loadOperations, homeView, workDetailsOpen, isWorkOverview, groupOperationsVisible, selectedRun?.updated_at,
    selectedRun?.main_operations?.merge?.updated_at, selectedRun?.main_operations?.push?.updated_at,
    selectedRun?.main_operations?.retry_main_push?.updated_at]);

  useEffect(() => {
    if (!workDetailsOpen || !isWorkOverview || !["runs.verify", "runs.verifyAndRepair", "runs.merge", "runs.push", "runs.retryMainPush", "runs.recoverMainApply"].includes(executionAction || busyAction)) return;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void loadOperations().finally(() => { inFlight = false; });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [busyAction, executionAction, loadOperations, isWorkOverview, workDetailsOpen]);

  const loadSelectedTaskLog = useCallback(async () => {
    const log = await window.orchestrator.request<string>("tasks.log", {
      projectName: selectedProjectName, runId: selectedRunId, taskId: selectedTaskId,
    });
    return boundedLogDisplay(log);
  }, [selectedProjectName, selectedRunId, selectedTaskId]);
  const taskLogState = useTaskLog(
    JSON.stringify([selectedProjectName, selectedRunId, selectedTaskId]),
    visibleInspectorTab === "log" && Boolean(selectedProjectName && selectedRunId && selectedTaskId)
      && selectedRun?.id === selectedRunId
      && Boolean(selectedRun?.tasks.some((task) => task.id === selectedTaskId)),
    loadSelectedTaskLog,
  );
  const openTaskLog = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    setInspectorTab("log");
    setSideInspectorOpen(true);
    setCurrentTaskContentView("list");
    window.requestAnimationFrame(() => {
      const tab = document.getElementById("side-inspector-tab-log");
      tab?.focus({ preventScroll: true });
      tab?.scrollIntoView({ block: "nearest" });
    });
  }, [selectedRun, setCurrentTaskContentView, setSelectedTaskId, workbenchLayout]);

  const openTaskEvents = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    setInspectorTab("events");
    setSideInspectorOpen(true);
    setCurrentTaskContentView("list");
    window.requestAnimationFrame(() => {
      const tab = document.getElementById("side-inspector-tab-events");
      tab?.focus({ preventScroll: true });
      tab?.scrollIntoView({ block: "nearest" });
    });
  }, [setCurrentTaskContentView, setSelectedTaskId]);

  const openTaskPlanning = useCallback((taskId: string) => {
    if (!selectedRun) return;
    const task = selectedTaskForDetails(selectedRun, taskDrafts, taskId);
    if (!task) return;
    if (taskPlanningInProgress(taskPlanningRequestsRef.current, selectedProjectName, selectedRun.id, taskId)) return;
    const draft = directionChangeDrafts.read(selectedProjectName, selectedRun.id);
    const source = failedTaskQuestionKey(selectedProjectName, selectedRun, task);
    const prepared = failedQuestionDrafts.current.prepare(selectedProjectName, selectedRun.id,
      source, draft.text, taskPlanningQuestionDraft(task), failedQuestionDrafts.current.diagnostic(selectedProjectName, selectedRun.id, source));
    directionChangeDrafts.edit(selectedProjectName, selectedRun.id, prepared);
    setRepairTarget({ projectName: selectedProjectName, runId: selectedRun.id, taskId });
    setWorkDetailsOpen(false);
    setSelectedTaskId(taskId);
    setSideInspectorOpen(false);
    setHomeView("work");
    setPlanningChatOpenRequest((request) => request + 1);
  }, [directionChangeDrafts, selectedProjectName, selectedRun, setSelectedTaskId, taskDrafts]);

  const openTaskDetail = useCallback((taskId: string) => {
    const task = selectedTaskForDetails(selectedRun, taskDrafts, taskId);
    if (selectedRun && task && taskDetailUsesChat(selectedRun, task)) { openTaskPlanning(taskId); return; }
    setSelectedTaskId(taskId);
    setInspectorTab("detail");
    setSideInspectorOpen(true);
    setCurrentTaskContentView("list");
  }, [openTaskPlanning, selectedRun, taskDrafts, setCurrentTaskContentView, setSelectedTaskId, sideInspectorOpen, workbenchLayout]);

  const openLinkedTaskDetail = useCallback((taskId: string) => {
    const task = selectedTaskForDetails(selectedRun, taskDrafts, taskId);
    if (selectedRun && task && taskDetailUsesChat(selectedRun, task)) { openTaskPlanning(taskId); return; }
    setSelectedTaskId(taskId);
    setInspectorTab("detail");
    setSideInspectorOpen(true);
    setCurrentTaskContentView("list");
    window.requestAnimationFrame(() => document.getElementById("task-dialog-title")?.focus({ preventScroll: true }));
  }, [openTaskPlanning, selectedRun, taskDrafts, setCurrentTaskContentView, setSelectedTaskId, workbenchLayout]);

  const closeInspector = useCallback(() => {
    const emptyTask = emptyManualTasksRef.current[`${selectedProjectName}\0${selectedRun?.id || ""}\0${selectedTaskId}`];
    if (selectedRun && emptyTask && !busyAction && !executionAction) {
      discardUntouchedTask(selectedProjectName, selectedRun.id, emptyTask);
      if (emptyTaskValidationMessage) setError((current) => current === emptyTaskValidationMessage ? "" : current);
    }
    setSideInspectorOpen(false);
    setCurrentTaskContentView("list");
  }, [busyAction, discardUntouchedTask, emptyTaskValidationMessage, executionAction, selectedProjectName, selectedRun, selectedTaskId, setCurrentTaskContentView]);

  const changeInspectorTab = useCallback((tab: InspectorTab) => {
    setInspectorTab(tab);
    setCurrentTaskContentView("list");
  }, [setCurrentTaskContentView, workbenchLayout]);

  useEffect(() => {
    if (!selectedProjectName || !selectedRunId || busyAction || !shouldPollRunExecution(selectedRun, executionAction)) return;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void loadRunDetail(selectedProjectName, selectedRunId).finally(() => { inFlight = false; });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedProjectName, selectedRunId, selectedRun, executionAction, busyAction, loadRunDetail]);

  const replaceRun = useCallback((projectName: string, updated: RunState, select = false) => {
    const context = selectedContextRef.current;
    const projectCache = runSummaryCacheRef.current[projectName];
    const previous = projectCache?.active.find((run) => run.id === updated.id)
      || projectCache?.archived.find((run) => run.id === updated.id);
    const summary = runSummaryFromState(updated, previous);
    const scope: RunListScope = updated.archive ? "archived" : "active";
    if (updated.archive) authoritativeArchivesRef.current[`${projectName}\0${updated.id}`] = summary;
    const nextCache = applyRunSummary(runSummaryCacheRef.current, projectName, scope, summary);
    runSummaryCacheRef.current = nextCache;
    setRunSummaryCache(nextCache);
    if (context.projectName !== projectName) return;
    if (select || context.runId === updated.id) {
      runDetailRequestRef.current += 1;
      setSelectedRunProjectName(projectName);
      setSelectedRun(updated);
      if (!updated.archive && !updated.execution_control) void loadRunDetail(projectName, updated.id);
    }
  }, [loadRunDetail]);

  useEffect(() => {
    if (!chatControlViews.length) return;
    setExecutionRequests(current => {
      const next = { ...current };
      for (const view of chatControlViews) {
        const key = runRequestKey(view.projectName, view.runId);
        if (view.status === "running") {
          const phase: ChatExecutionPhase = view.intent === "project" ? view.phase === "acting" ? "working" : "thinking"
            : view.phase === "stopping" || view.phase === "accepted" ? "stopping"
            : view.phase === "verifying" ? "verifying" : "repairing";
          next[key] = { id: current[key]?.id || ++executionRequestSequenceRef.current, method: phase === "stopping" ? "runs.requestStop"
            : phase === "thinking" || phase === "working" ? "runs.controlChat"
            : phase === "verifying" ? "runs.verifyAndRepair" : "tasks.repairFromChat", startedAt: view.startedAt,
            chatPhase: phase, chatRequestId: view.requestId, chatIntent: view.intent };
        } else if (next[key]?.chatRequestId === view.requestId) delete next[key];
      }
      return next;
    });
    const relevant = chatControlViews.find(view => view.projectName === selectedContextRef.current.projectName && view.runId === selectedContextRef.current.runId);
    if (relevant) void window.orchestrator.request<RunState>("runs.get", { projectName: relevant.projectName, runId: relevant.runId })
      .then(run => replaceRun(relevant.projectName, run)).catch(() => {});
  }, [chatControlViews, replaceRun]);

  const recoverStaleRunLock = useCallback(
    async (
      projectName: string,
      runId: string,
      requestError: unknown,
    ): Promise<StaleLockRecovery> => {
      const operation = runLockConflictOperation(rawErrorMessage(requestError), runId);
      if (!operation) {
        return "not-stale";
      }
      let lock: RunLockStatus;
      try {
        lock = await window.orchestrator.request<RunLockStatus>("locks.get", {
          projectName,
          runId,
        });
      } catch {
        return "not-stale";
      }
      if (lock.state !== "stale" || lock.run_id !== runId || lock.operation !== operation) return "not-stale";
      const cleared = await window.orchestrator.approve<RunLockStatus>(
        "locks.clear",
        { projectName, runId },
      );
      return cleared ? "recovered" : "cancelled";
    },
    [],
  );

  const requestRunAction = useCallback(
    async (method: RpcMethod, taskId?: string, continueRemaining = false, approvedRun?: RunState) => {
      if (!selectedProjectName || !selectedRun) return;
      if (selectedRun.stage === "planned" && !approvedRun && ["runs.execute", "tasks.execute"].includes(method)
        && selectedRun.tasks.some(task => (!taskId || task.id === taskId)
          && taskProfileRequiresReselection(task, taskProfiles[task.id], taskProfileOptions[task.id] || []))) {
        setNotice("실행 AI를 먼저 확인해 주세요. 모델 선택과 계획 확정을 마친 뒤 시작할 수 있습니다.");
        setWorkbenchView("tasks"); setWorkDetailsOpen(true);
        return;
      }
      if (["runs.execute", "runs.resume", "tasks.execute", "tasks.retry"].includes(method)
        && taskPlanningInProgress(taskPlanningRequestsRef.current, selectedProjectName, selectedRun.id, taskId)) {
        setNotice("현재 Task 수정 중입니다. 수정이 끝난 뒤 실행해 주세요.");
        return;
      }
      if (nextExecutionProfileDirty && ["runs.execute", "runs.resume", "tasks.execute", "tasks.retry"].includes(method)) {
        setError("다음 실행 모델 변경을 저장하거나 취소한 뒤 실행해 주세요.");
        return;
      }
      const projectName = selectedProjectName;
      const runId = selectedRun.id;
      const tracksLiveState = liveRunActionMethods.has(method);
      const requestKey = runRequestKey(projectName, runId);
      const requestId = ++executionRequestSequenceRef.current;
      let pollingActive = tracksLiveState;
      let pollInFlight = false;
      let pollingTimer: number | undefined;
      const pollRunState = async () => {
        if (!pollingActive || pollInFlight) return;
        pollInFlight = true;
        try {
          const current = await window.orchestrator.request<RunState>("runs.get", {
            projectName,
            runId,
          });
          if (pollingActive) replaceRun(projectName, current);
        } catch {
          // The long-running work request remains authoritative. A transient
          // status read failure must not be presented as an execution failure.
        } finally {
          pollInFlight = false;
        }
      };
      if (tracksLiveState) {
        setExecutionRequests((current) => ({
          ...current,
          [requestKey]: { id: requestId, method, startedAt: Date.now() },
        }));
      }
      else setBusyAction(method);
      setError("");
      setNotice("");
      if (tracksLiveState) {
        pollingTimer = window.setInterval(() => {
          void pollRunState();
        }, 1500);
        void pollRunState();
      }
      try {
        if (method === "runs.execute" || method === "runs.resume") {
          const latest = await readRunExecutionAction(
            () => window.orchestrator.request<RunState>("runs.get", { projectName, runId }),
            approvedRun || selectedRun, method,
          );
          replaceRun(projectName, latest.run);
          if (!runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) return;
          if (!latest.allowed) {
            setNotice("작업 그룹의 최신 상태를 반영했습니다. 실행·재개 요청은 보내지 않았습니다. 현재 가능한 다음 행동을 확인하세요.");
            return;
          }
        }
        const profileParams = profileOverrides(
          method === "runs.execute" && approvedRun ? approvedRun : selectedRun,
          selectedRun.stage === "planned" ? taskProfiles : {},
          taskId ? [taskId] : undefined,
        );
        const requestParams = {
          projectName,
          runId,
          ...(taskId ? { taskId } : {}),
          ...(method === "runs.verifyAndRepair" ? { requestId: crypto.randomUUID() } : {}),
          ...(["runs.execute", "tasks.execute"].includes(method)
            ? profileParams
            : {}),
        };
        const performAction = () =>
          window.orchestrator.request<RunState>(method, requestParams);
        let recoveredStaleLock = false;
        let updated: RunState;
        try {
          updated = await performAction();
        } catch (requestError) {
          if (method === "runs.execute" || method === "runs.resume") throw requestError;
          const recovery = await recoverStaleRunLock(
            projectName,
            runId,
            requestError,
          );
          if (recovery === "cancelled") {
            throw new Error(
              "중단된 실행 잠금 정리를 취소했습니다. 작업 실행을 재개하지 않았습니다.",
            );
          }
          if (recovery !== "recovered") throw requestError;
          recoveredStaleLock = true;
          updated = await performAction();
        }
        pollingActive = false;
        replaceRun(projectName, updated);
        if (continueRemaining && method === "tasks.retry" && taskId) {
          const latest = await window.orchestrator.request<RunState>("runs.get", { projectName, runId });
          replaceRun(projectName, latest);
          if (canContinueTaskRetry(approvedRun || selectedRun, latest, taskId, updated)) {
            pollingActive = true;
            updated = await window.orchestrator.request<RunState>("runs.resume", { projectName, runId });
            pollingActive = false;
            replaceRun(projectName, updated);
          } else {
            if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) {
              setNotice("Task 재시도 결과를 보존했습니다. 현재 재개 조건이 충족되지 않아 남은 작업을 시작하지 않았습니다. 작업 화면에서 다음 행동을 확인하세요.");
            }
            return;
          }
        }
        if (runContextMatches(
          selectedContextRef.current.projectName,
          selectedContextRef.current.runId,
          projectName,
          runId,
        )) {
          setNotice(
            recoveredStaleLock
              ? "중단된 실행 잠금을 정리하고 요청을 다시 시작했습니다."
              : "요청을 반영했습니다.",
          );
        }
      } catch (requestError) {
        const currentContext = () => runContextMatches(
          selectedContextRef.current.projectName,
          selectedContextRef.current.runId,
          projectName,
          runId,
        );
        const changedRunLock = (method === "runs.execute" || method === "runs.resume")
          && Boolean(runLockConflictOperation(rawErrorMessage(requestError), runId));
        if (isRunStageMismatchError(rawErrorMessage(requestError)) || changedRunLock) {
          try {
            const current = await window.orchestrator.request<RunState>("runs.get", {
              projectName,
              runId,
            });
            replaceRun(projectName, current);
            if (currentContext()) {
              const guidance = runRecoveryGuidance(current);
              if (guidance?.actionKind === "planning") setWorkbenchView("planning");
              else if (guidance?.actionKind === "operations") setWorkbenchView("operations");
              else setWorkbenchView("tasks");
              setError("");
              setNotice(
                guidance
                  ? `작업 그룹의 최신 상태를 반영했습니다. ${guidance.actionLabel}에서 이어서 진행하세요.`
                  : "작업 그룹의 상태가 바뀌어 실행·재개를 진행하지 않았습니다. 최신 상태에서 가능한 작업을 확인하세요.",
              );
            }
            return;
          } catch {
            // Preserve the original state mismatch if the status refresh also fails.
          }
        }
        if (currentContext()) setError(errorMessage(requestError));
        await pollRunState();
      } finally {
        pollingActive = false;
        if (pollingTimer !== undefined) window.clearInterval(pollingTimer);
        if (tracksLiveState) {
          setExecutionRequests((current) => {
            if (current[requestKey]?.id !== requestId) return current;
            const next = { ...current };
            delete next[requestKey];
            return next;
          });
        }
        else setBusyAction("");
      }
    },
    [nextExecutionProfileDirty, recoverStaleRunLock, replaceRun, selectedProjectName, selectedRun, taskProfiles, taskProfileOptions],
  );

  const requestExecutionStop = useCallback(async (task?: WorkTask) => {
    if (!selectedProjectName || !selectedRun?.execution_control) return;
    const control = selectedRun.execution_control;
    if (!control.execution_id || !control.can_stop || stopRequestExecutionId === control.execution_id) return;
    const projectName = selectedProjectName;
    const runId = selectedRun.id;
    setStopRequestExecutionId(control.execution_id);
    setError("");
    setNotice("");
    try {
      const receipt = await window.orchestrator.request<{ phase: string }>("runs.requestStop", {
        projectName,
        runId,
        requestId: crypto.randomUUID(),
        executionId: control.execution_id,
        scope: task ? "task" : "verification",
        ...(task ? {
          taskId: task.id,
          attemptId: task.last_attempt_id || "",
          invocationId: task.active_invocation_id || "",
        } : {
          attemptId: control.active_attempt_id,
          invocationId: control.active_invocation_id,
        }),
      });
      await loadRunDetail(projectName, runId);
      if (runContextMatches(
        selectedContextRef.current.projectName,
        selectedContextRef.current.runId,
        projectName,
        runId,
      )) {
        setNotice(receipt.phase === "already_finished"
          ? "대상 작업이 중지 요청보다 먼저 끝났습니다. 최신 상태를 반영했습니다."
          : "중지 요청을 접수했습니다. 실행 종료와 작업 보존을 확인하고 있습니다.");
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
      await loadRunDetail(projectName, runId).catch(() => undefined);
    } finally {
      setStopRequestExecutionId((current) => current === control.execution_id ? "" : current);
    }
  }, [loadRunDetail, selectedProjectName, selectedRun, stopRequestExecutionId]);

  const updateTaskDraft = useCallback(
    (taskId: string, changes: Partial<WorkTask>) => {
      const nextId = changes.id;
      if (nextId && nextId !== taskId && taskDrafts.some((task) => task.id === nextId)) {
        setError("이미 사용 중인 Task ID입니다. 다른 ID를 입력해 주세요.");
        return;
      }
      setTaskDrafts((current) => current.map((task) => {
        if (task.id === taskId) {
          const capabilitiesChanged = changes.capabilities !== undefined
            && capabilityKey(changes.capabilities) !== capabilityKey(task.capabilities);
          return {
            ...task,
            ...changes,
            ...(capabilitiesChanged
              ? { agent_id: "", provider_id: "", model: "", reasoning_effort: "" }
              : {}),
          };
        }
        if (nextId && nextId !== taskId && task.dependencies.includes(taskId)) {
          return {
            ...task,
            dependencies: task.dependencies.map((dependency) => dependency === taskId ? nextId : dependency),
          };
        }
        return task;
      }));
      if (nextId && nextId !== taskId) {
        setSelectedTaskId(nextId);
        setSelectedTaskIds((current) => current.map((id) => id === taskId ? nextId : id));
        setTaskProfiles((current) => renameRecordKey(current, taskId, nextId));
        setDraftField("inputs", (current) => Object.fromEntries(Object.entries(renameRecordKey(current, taskId, nextId))
          .map(([id, input]) => [id, { ...input, dependencies: input.dependencies.split("\n")
            .map((line) => line.trim() === taskId ? line.replace(taskId, nextId) : line).join("\n") }])));
        setTaskProfileOptions((current) => renameRecordKey(current, taskId, nextId));
      } else if (changes.capabilities !== undefined) {
        setTaskProfiles((current) => {
          const next = { ...current };
          delete next[taskId];
          return next;
        });
      }
    },
    [setDraftField, setSelectedTaskId, setTaskDrafts, setTaskProfiles, taskDrafts],
  );

  const addTaskDraft = useCallback(() => {
    if (!selectedRun) return;
    const id = nextTaskId(taskDrafts);
    const task = emptyTaskDraft(id);
    emptyManualTasksRef.current[`${selectedProjectName}\0${selectedRun.id}\0${id}`] = task;
    setAdvancedEditorRequest((current) => ({ key: "", revision: current.revision }));
    setTaskDrafts((current) => [...current, task]);
    setSelectedTaskId(id);
    setSelectedTaskIds([]);
    setInspectorTab("detail");
    setSideInspectorOpen(true);
    if (workbenchLayout !== "wide") setCurrentTaskContentView("detail");
  }, [selectedProjectName, selectedRun, setCurrentTaskContentView, setSelectedTaskId, setTaskDrafts, taskDrafts, workbenchLayout]);

  const resetPlanDraft = useCallback(() => {
    if (!selectedRun) return;
    acceptSavedPlan(selectedProjectName, selectedRun);
    setSelectedTaskIds([]);
  }, [acceptSavedPlan, selectedProjectName, selectedRun]);

  const revealPlanError = useCallback((failure: TaskDraftError, prefix = "") => {
    if (!selectedRun) return;
    setWorkbenchView("tasks");
    setSelectedTaskId(failure.taskId);
    setInspectorTab("detail");
    setSideInspectorOpen(true);
    if (workbenchLayout !== "wide") setCurrentTaskContentView("detail");
    setAdvancedEditorRequest((current) => ({
      key: `${selectedProjectName}\0${selectedRun.id}\0${failure.taskId}`,
      revision: current.revision + 1, field: failure.field,
    }));
    setError(`${prefix}${taskDraftErrorSummary(failure, taskDrafts)} 초안은 유지됩니다.`);
  }, [selectedProjectName, selectedRun, setCurrentTaskContentView, setSelectedTaskId, taskDrafts, workbenchLayout]);

  const savePlan = useCallback(
    async (confirm: boolean) => {
      if (!selectedProjectName || !selectedRun) return;
      if (draftErrors.length) {
        revealPlanError(draftErrors[0]);
        return;
      }
      if (draftConflict || selectedRun.stage !== "planned") {
        setError("저장된 계획 또는 실행 단계가 변경되었습니다. 보존된 초안을 검토한 뒤 최신 계획과 다시 비교해 주세요.");
        return;
      }
      const method: RpcMethod = confirm ? "runs.confirmPlan" : "runs.updatePlan";
      setBusyAction(method);
      setError("");
      setNotice("");
      let saved = false;
      try {
        let updated = selectedRun;
        if (planDirty) {
          updated = await window.orchestrator.request<RunState>("runs.updatePlan", {
            projectName: selectedProjectName,
            runId: selectedRun.id,
            tasks: taskDrafts.map((task) => taskPlanPayload(
              task,
              taskProfiles[task.id],
              taskProfileOptions[task.id] || [],
            )),
          });
          saved = true;
          acceptSavedPlan(selectedProjectName, updated);
          replaceRun(selectedProjectName, updated);
        }
        if (confirm) {
          updated = await window.orchestrator.request<RunState>("runs.confirmPlan", {
            projectName: selectedProjectName,
            runId: updated.id,
          });
        }
        replaceRun(selectedProjectName, updated);
        setNotice(confirm ? "계획을 확정했습니다. 작업을 실행할 수 있습니다." : "계획 변경을 저장했습니다. 확인 후 확정해 주세요.");
      } catch (requestError) {
        const fieldError = taskPlanFailure(errorMessage(requestError), taskDrafts);
        if (fieldError && runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, selectedProjectName, selectedRun.id)) {
          revealPlanError(fieldError, saved ? "계획 변경은 저장됐지만 확정에 실패했습니다. " : "");
        } else setError(`${saved ? "계획 변경은 저장됐지만 확정에 실패했습니다. " : "저장·확정에 실패했습니다. 초안은 유지됩니다. "}${errorMessage(requestError)}`);
      } finally {
        setBusyAction("");
      }
    },
    [acceptSavedPlan, draftConflict, draftErrors, planDirty, replaceRun, revealPlanError, selectedProjectName, selectedRun, taskDrafts, taskProfileOptions, taskProfiles],
  );

  const openRunRecovery = useCallback(async () => {
    if (!selectedProjectName || !selectedRun) return;
    const projectName = selectedProjectName;
    const runId = selectedRun.id;
    const current = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId);
    setBusyAction("runs.get");
    setError("");
    try {
      const latest = await window.orchestrator.request<RunState>("runs.get", { projectName, runId });
      if (latest.id !== runId) throw new Error("조회 응답의 작업 그룹이 요청 대상과 다릅니다.");
      replaceRun(projectName, latest);
      if (!current()) return;
      const sameFailure = selectedRun.stage === latest.stage && selectedRun.failed_step === latest.failed_step
        && selectedRun.failure_message === latest.failure_message && selectedRun.updated_at === latest.updated_at;
      if (!runRecoveryAllowed(latest) || !sameFailure) {
        setRecoveryOpen(false);
        setNotice("현재 복구할 실패가 없거나 실행·잠금 상태가 바뀌었습니다. 최신 상태에서 다음 행동을 확인하세요.");
        return;
      }
      setRecoveryOpen(true);
    } catch (cause) {
      if (current()) setError(`현재 복구 가능 상태를 확인하지 못했습니다. ${errorMessage(cause)}`);
    } finally {
      setBusyAction("");
    }
  }, [replaceRun, selectedProjectName, selectedRun]);

  const focusWorkbenchTarget = useCallback((id: string) => {
    window.requestAnimationFrame(() => document.getElementById(id)?.focus());
  }, []);

  const invokeWaitingAction = useCallback(async (sourceKey: string) => {
    if (!selectedProjectName || !selectedRun || planDirty) return;
    const projectName = selectedProjectName;
    const runId = selectedRun.id;
    const context = `${projectName}\0${runId}`;
    if (waitingInvocations.current.has(context)) return;
    waitingInvocations.current.add(context);
    setWaitingChecks((current) => ({ ...current, [context]: true }));
    setError("");
    try {
      const latest = await readWaitingPromptAction(
        () => window.orchestrator.request<RunState>("runs.get", { projectName, runId }), sourceKey,
      );
      if (latest.run.id !== runId) throw new Error("조회 응답의 작업 그룹이 요청 대상과 다릅니다.");
      if (!runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) return;
      replaceRun(projectName, latest.run);
      if (!latest.action) {
        setNotice("대기 상태가 바뀌었습니다. 현재 가능한 다음 행동을 확인하세요.");
        return;
      }
      setWaitingChecks((current) => ({ ...current, [context]: false }));
      if (latest.action === "operations" || latest.action === "verify") {
        openApplySummary();
      } else {
        const method = latest.action === "retry" ? "tasks.retry" : "runs.resume";
        await requestRunAction(method, latest.action === "retry" ? latest.run.waiting_prompt?.task_id : undefined);
      }
    } catch (cause) {
      if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) {
        setError(`현재 대기 상태를 확인하지 못했습니다. ${errorMessage(cause)}`);
      }
    } finally {
      waitingInvocations.current.delete(context);
      setWaitingChecks((current) => ({ ...current, [context]: false }));
    }
  }, [focusWorkbenchTarget, openApplySummary, planDirty, replaceRun, requestRunAction, selectedProjectName, selectedRun]);

  const invokeNextAction = useCallback((action: RunNextAction) => {
    if (selectedRun?.waiting_prompt && waitingPromptAction(selectedRun) === action.kind) {
      void invokeWaitingAction(selectedRun.waiting_prompt.source_key);
      return;
    }
    if (action.kind === "effort") {
      setWorkbenchView("tasks");
      setCurrentTaskContentView("list");
      window.requestAnimationFrame(() => {
        const button = document.getElementById("effort-mode-change");
        if (button?.getAttribute("aria-expanded") === "false") button.click();
        button?.focus();
      });
      return;
    }
    if (action.kind === "confirm_plan") {
      void savePlan(true);
      return;
    }
    if (action.kind === "execute" || action.kind === "resume") {
      void requestRunAction(action.kind === "execute" ? "runs.execute" : "runs.resume");
      return;
    }
    if (action.kind === "refresh") {
      void refreshSelectedRunStatus();
      return;
    }
    if (action.kind === "planning") {
      setWorkbenchView("planning");
      focusWorkbenchTarget("planning-workbench-title");
      return;
    }
    if (action.kind === "result") {
      setSideInspectorOpen(false);
      setResultFocusTaskId("");
      setWorkbenchView("results");
      focusWorkbenchTarget("results-workbench-title");
      return;
    }
    if (action.kind === "operations") {
      openApplySummary();
      return;
    }
    if (action.kind === "task_log" || action.kind === "task_detail") {
      setWorkbenchView("tasks");
      setSelectedTaskId(action.taskId);
      if (action.kind === "task_log") openTaskLog(action.taskId);
      else openLinkedTaskDetail(action.taskId);
    }
  }, [focusWorkbenchTarget, invokeWaitingAction, openApplySummary, openLinkedTaskDetail, openTaskLog, refreshSelectedRunStatus, requestRunAction, savePlan, selectedRun, setCurrentTaskContentView, setSelectedTaskId]);

  const approvedRunAction = useCallback(
    async (method: ApprovedRpcMethod, extra: Record<string, unknown> = {}, targetRunId = selectedRun?.id) => {
      if (!selectedProjectName || !targetRunId) return;
      const tracksElapsed = method === "runs.merge" || method === "runs.retryMainPush" || method === "runs.recoverMainApply";
      let elapsedTimer: number | undefined;
      setBusyAction(method);
      setError("");
      setNotice("");
      setExecutionElapsed(0);
      if (tracksElapsed) {
        const elapsedStartedAt = Date.now();
        elapsedTimer = window.setInterval(() => {
          setExecutionElapsed(Math.floor((Date.now() - elapsedStartedAt) / 1000));
        }, 1000);
      }
      const operationRequestId = ["runs.merge", "runs.push", "runs.retryMainPush", "runs.recoverMainApply"].includes(method)
        ? crypto.randomUUID()
        : "";
      try {
        const performAction = () => window.orchestrator.approve<unknown>(method, {
            projectName: selectedProjectName,
            ...extra,
            runId: targetRunId,
            ...(operationRequestId ? { requestId: operationRequestId } : {}),
          });
        let recoveredStaleLock = false;
        let result: unknown;
        try {
          result = await performAction();
        } catch (requestError) {
          const recovery = method === "runs.merge" && !["main_apply_interrupted", "main_apply_recoverable"].includes(selectedRun?.integration_control?.reason_code || "")
            ? await recoverStaleRunLock(
              selectedProjectName,
              targetRunId,
              requestError,
            )
            : "not-stale";
          if (recovery === "cancelled") {
            throw new Error(
              "중단된 실행 잠금 정리를 취소했습니다. Main 반영을 다시 시작하지 않았습니다.",
            );
          }
          if (recovery !== "recovered") throw requestError;
          recoveredStaleLock = true;
          result = await performAction();
        }
        if (result === null) return;
        if (isRunState(result)) replaceRun(selectedProjectName, result);
        if (method === "runs.delete") {
          if (targetRunId === selectedRunId) {
            setSelectedRun(undefined);
            setSelectedTaskId("");
            setSelectedTaskIds([]);
          }
          await loadRuns({ projectName: selectedProjectName, scope: archiveScopeRef.current });
        }
        if (method === "workspaces.cleanup") {
          await loadOperations();
        }
        if (method === "runs.merge" || method === "runs.push" || method === "runs.retryMainPush" || method === "runs.recoverMainApply") {
          await loadOperations();
        }
        if (method === "locks.clear") {
          await Promise.all([
            loadOperations(),
            loadRunDetail(selectedProjectName, targetRunId),
          ]);
        }
        setNotice(
          recoveredStaleLock
            ? "중단된 실행 잠금을 정리하고 승인된 작업을 완료했습니다."
            : "승인된 작업을 완료했습니다.",
        );
      } catch (requestError) {
        if (method === "runs.merge" || method === "runs.push" || method === "runs.retryMainPush" || method === "runs.recoverMainApply") await loadOperations();
        setError(errorMessage(requestError));
      } finally {
        if (elapsedTimer !== undefined) window.clearInterval(elapsedTimer);
        setExecutionElapsed(0);
        setBusyAction("");
      }
    },
    [loadOperations, loadRunDetail, loadRuns, recoverStaleRunLock, replaceRun, selectedProjectName, selectedRun?.id, selectedRunId],
  );

  const requestApplySummaryCommand = useCallback(async (
    projectName: string, runId: string, method: ApplySummaryMethod, extra: Record<string, unknown>,
  ): Promise<RunState | null> => {
    if (applyCommandPendingRef.current || !runContextMatches(
      selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId,
    )) throw new Error("현재 반영 요청이나 대상을 다시 확인해 주세요.");
    applyCommandPendingRef.current = true;
    const key = runRequestKey(projectName, runId);
    const id = ++executionRequestSequenceRef.current;
    setExecutionRequests((current) => ({ ...current, [key]: { id, method, startedAt: Date.now() } }));
    let pollInFlight = false;
    let active = true;
    const timer = window.setInterval(() => {
      if (pollInFlight) return;
      pollInFlight = true;
      void window.orchestrator.request<RunState>("runs.get", { projectName, runId })
        .then((updated) => { if (active) replaceRun(projectName, updated); })
        .catch(() => { /* The command result remains authoritative; operations reads expose lookup errors. */ })
        .finally(() => { pollInFlight = false; });
    }, 1500);
    try {
      const updated = await sendApplySummaryCommand(window.orchestrator, method, {
        ...extra, projectName, runId, requestId: window.crypto.randomUUID(),
      });
      if (updated) {
        if (!isRunState(updated) || updated.id !== runId) throw new Error("반영 응답의 작업 그룹을 확인하지 못했습니다. 다시 확인하세요.");
        replaceRun(projectName, updated);
      }
      return updated;
    } catch (cause) {
      if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) {
        setError(errorMessage(cause));
      }
      throw cause;
    } finally {
      active = false;
      window.clearInterval(timer);
      applyCommandPendingRef.current = false;
      setExecutionRequests((current) => {
        if (current[key]?.id !== id) return current;
        const next = { ...current }; delete next[key]; return next;
      });
    }
  }, [replaceRun]);

  const performApplySummary = useCallback(async (action: ApplySummaryAction) => {
    if (!selectedRun || !selectedProjectName || !applySummaryOpenRef.current || applySummarySessionRef.current?.isPending()) return;
    if (planDirty) { setApplySummaryError("미저장 작업 편집을 먼저 저장하거나 취소하세요."); return; }
    const projectName = selectedProjectName;
    const runId = selectedRun.id;
    const current = () => applySummaryOpenRef.current && runContextMatches(
      selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId,
    );
    const session = applySummarySessionRef.current ?? new ApplySummarySession(projectName, {
      current,
      read: () => readConsistentOperations(projectName, runId, window.orchestrator.request),
      command: (method, extra) => requestApplySummaryCommand(projectName, runId, method, extra),
      changed: (result) => {
        if (!current()) return;
        operationsRequestRef.current += 1;
        replaceRun(projectName, result.run);
        setOperationsSnapshot(result.snapshot);
      },
    });
    applySummarySessionRef.current = session;
    setApplySummaryChecking(true);
    setApplySummaryError("");
    setError("");
    setNotice("");
    try {
      const outcome = await session.perform(action, selectedRun);
      if (current() && applySummarySessionRef.current === session && outcome === "cancelled") {
        setApplySummaryError("승인을 취소했습니다. 내용을 확인한 뒤 다시 진행할 수 있습니다.");
      }
    } catch (cause) {
      if (current() && applySummarySessionRef.current === session) setApplySummaryError(errorMessage(cause));
    } finally {
      if (current() && applySummarySessionRef.current === session) {
        setApplySummaryChecking(false);
        void loadOperations();
      }
    }
  }, [loadOperations, planDirty, replaceRun, requestApplySummaryCommand, selectedProjectName, selectedRun]);

  const deleteRun = useCallback(
    async (targetRunId: string, projectName = selectedProjectName, scope: RunListScope = archiveScopeRef.current) => {
      if (!projectName || !targetRunId || deleteRequestPendingRef.current || archiveRequestPendingRef.current) return;
      deleteRequestPendingRef.current = true;
      setDeletingProjectName(projectName);
      setDeletingRunId(targetRunId);
      setError("");
      setNotice("");
      const clearDeletedSelection = () => {
        if (selectedContextRef.current.projectName !== projectName || selectedContextRef.current.runId !== targetRunId) return;
        selectedContextRef.current = { projectName, runId: "" };
        newWorkProjectRef.current = projectName;
        archiveScopeRef.current = "active";
        setArchiveScope("active");
        runDetailRequestRef.current += 1;
        setSelectedRunId("");
        setSelectedRun(undefined);
        setSelectedRunProjectName("");
        setSelectedTaskId("");
        setSelectedTaskIds([]);
        setWorkbenchView("planning");
      };
      try {
        const lock = await window.orchestrator.request<RunLockStatus>("locks.get", {
          projectName,
          runId: targetRunId,
        });
        const blockedMessage = runDeletionBlockMessage(lock);
        if (blockedMessage) {
          setError(blockedMessage);
          return;
        }
        const result = await window.orchestrator.approve<unknown>("runs.delete", {
          projectName,
          runId: targetRunId,
        });
        if (result === null) return;
        delete authoritativeArchivesRef.current[`${projectName}\0${targetRunId}`];
        const current = runSummaryCacheRef.current;
        const projectCache = current[projectName];
        if (projectCache) {
          const next = {
            ...current,
            [projectName]: {
              ...projectCache,
              active: projectCache.active.filter((run) => run.id !== targetRunId),
              archived: projectCache.archived.filter((run) => run.id !== targetRunId),
            },
          };
          runSummaryCacheRef.current = next;
          setRunSummaryCache(next);
        }
        clearDeletedSelection();
        await loadRuns({ projectName, scope, selectFirst: false });
        setNotice("작업 그룹을 삭제했습니다.");
      } catch (requestError) {
        const missingMessage = runDeletionMissingMessage(requestError);
        if (missingMessage) clearDeletedSelection();
        if (!missingMessage) {
          try {
            const current = await window.orchestrator.request<RunState>("runs.get", {
              projectName,
              runId: targetRunId,
            });
            replaceRun(projectName, current);
          } catch {
            // The list refresh below is still useful if the selected run disappeared.
          }
        }
        await loadRuns({
          projectName,
          scope,
          selectFirst: false,
        });
        if (selectedContextRef.current.projectName === projectName) {
          setError(missingMessage || errorMessage(requestError));
        }
      } finally {
        deleteRequestPendingRef.current = false;
        setDeletingRunId("");
        setDeletingProjectName("");
      }
    },
    [loadRuns, replaceRun, selectedProjectName, setSelectedTaskId],
  );

  const archiveRun = useCallback(async (targetRunId: string, projectName = selectedProjectName) => {
    if (!projectName || !targetRunId || archiveRequestPendingRef.current || deleteRequestPendingRef.current) return;
    archiveRequestPendingRef.current = true;
    const requestContext = {
      projectName: selectedContextRef.current.projectName,
      runId: selectedContextRef.current.runId,
      scope: archiveScopeRef.current,
    };
    const targetSelected = requestContext.projectName === projectName && requestContext.runId === targetRunId;
    setArchivingProjectName(projectName);
    setArchivingRunId(targetRunId);
    setError("");
    setNotice("");
    try {
      const plan = await window.orchestrator.request<RunArchivePlan>("runs.archivePlan", {
        projectName,
        runId: targetRunId,
      });
      if (!plan.can_archive) {
        setError(plan.block_reasons.join(" ") || "현재 상태에서는 작업 그룹을 보관할 수 없습니다.");
        return;
      }
      const result = await window.orchestrator.approve<RunState>("runs.archive", {
        projectName,
        runId: targetRunId,
        expectedRevision: plan.expected_revision,
        fingerprint: plan.fingerprint,
        requestId: crypto.randomUUID(),
        cleanupTargetCount: plan.cleanup_targets.length,
      });
      if (!result) return;
      const currentContext = selectedContextRef.current;
      const completionView = targetSelected ? archiveCompletionView(requestContext, {
        projectName: currentContext.projectName,
        runId: currentContext.runId,
        scope: archiveScopeRef.current,
      }) : null;
      const shouldNavigate = completionView !== null;
      replaceRun(projectName, result, shouldNavigate);
      if (completionView) {
        archiveTransitionRef.current = { projectName, runId: targetRunId };
        archiveScopeRef.current = "archived";
        setArchiveScope("archived");
        setSelectedRunId(targetRunId);
        setWorkbenchView(completionView);
      }
      setNotice(result.archive?.cleanup_status === "completed"
        ? "완료 기록을 보관하고 작업공간을 정리했습니다."
        : `완료 기록은 보관했습니다. ${archiveCleanupReason(result.archive)}`);
      await loadRuns({
        projectName,
        scope: "archived",
        preferredRun: targetRunId,
        selectFirst: shouldNavigate,
        archiveRefresh: true,
      });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      archiveRequestPendingRef.current = false;
      setArchivingRunId("");
      setArchivingProjectName("");
    }
  }, [loadRuns, replaceRun, selectedProjectName]);

  const retryArchiveCleanup = useCallback(async () => {
    if (!selectedProjectName || !selectedRun?.archive || busyAction) return;
    setBusyAction("runs.retryArchiveCleanup");
    setError("");
    try {
      const result = await window.orchestrator.approve<RunState>("runs.retryArchiveCleanup", {
        projectName: selectedProjectName,
        runId: selectedRun.id,
        fingerprint: selectedRun.archive.fingerprint,
        requestId: crypto.randomUUID(),
      });
      if (!result) return;
      replaceRun(selectedProjectName, result);
      setNotice(result.archive?.cleanup_status === "completed"
        ? "남은 작업공간 정리를 완료했습니다."
        : archiveCleanupReason(result.archive));
      await loadRuns({
        projectName: selectedProjectName,
        scope: "archived",
        preferredRun: result.id,
        archiveRefresh: true,
      });
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction("");
    }
  }, [busyAction, loadRuns, replaceRun, selectedProjectName, selectedRun]);

  const removeProject = useCallback(async () => {
    const projectName = selectedProjectName;
    if (projectRemovalReason(projectName, executionRequests, busyAction, busyProjectRef.current, removingProjectRef.current, planningRequests)) return;
    removingProjectRef.current = projectName;
    setRemovingProjectName(projectName);
    try {
      const result = await window.orchestrator.approve<RegisteredProject>("projects.remove", { projectName });
      if (result) {
        await loadProjects();
        setNotice(`${projectName} 프로젝트를 등록 목록에서 제외했습니다.`);
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      removingProjectRef.current = "";
      setRemovingProjectName("");
    }
  }, [loadProjects, selectedProjectName, executionRequests, busyAction, planningRequests]);

  const choosePath = useCallback(
    async (kind: "repository" | "config" | "planningSource") => {
      const path = await window.orchestrator.selectPath(kind);
      if (!path) return;
      if (projectDialogOpen) {
        const field =
          kind === "repository"
            ? "repo"
            : kind === "config"
              ? "configPath"
              : "planningSourceDir";
        setProjectDraft((current) => ({ ...current, [field]: path }));
      } else if (kind === "planningSource") {
        if (selectedContextRef.current.projectName !== selectedProjectName || selectedContextRef.current.runId !== selectedRunId) return;
        setPlanningPath(path);
        updatePlanningDraft({ path });
      }
    },
    [projectDialogOpen, selectedProjectName, selectedRunId, updatePlanningDraft],
  );

  const savePlanningSource = useCallback(async () => {
    if (!selectedProjectName) return;
    setBusyAction("projects.updatePlanningSource");
    try {
      await window.orchestrator.request("projects.updatePlanningSource", {
        projectName: selectedProjectName,
        sourceRoot: planningPath,
      });
      await loadProjects();
      setNotice("기획문서 디렉터리를 저장했습니다.");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction("");
    }
  }, [loadProjects, planningPath, selectedProjectName]);

  const refreshPlanningIndex = useCallback(async () => {
    if (!selectedProjectName || !planningPath) return;
    const projectName = selectedProjectName, runId = selectedContextRef.current.runId;
    const chatId = selectedChatDraftRef.current.projectName === projectName ? selectedChatDraftRef.current.id : "";
    const isCurrent = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)
      && (Boolean(runId) || (selectedChatDraftRef.current.projectName === projectName ? selectedChatDraftRef.current.id : "") === chatId);
    const startedAt = Date.now();
    const elapsedTimer = window.setInterval(() => {
      if (isCurrent()) setPlanningIndexElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    setError("");
    setNotice("");
    setPlanningIndexElapsed(0);
    setBusyAction("planning.refreshIndex");
    try {
      const result = await window.orchestrator.request<PlanningSourceIndex>(
        "planning.refreshIndex",
        { projectName: selectedProjectName, sourceRoot: planningPath },
      );
      if (!isCurrent()) return;
      setPlanningIndex(result);
      const changes = result.added_count + result.modified_count + result.deleted_count;
      setNotice(
        changes
          ? `기획문서 색인 ${result.document_count}개를 갱신했습니다. 변경 ${changes}개(추가 ${result.added_count} · 수정 ${result.modified_count} · 삭제 ${result.deleted_count})`
          : `기획문서 색인 ${result.document_count}개를 확인했습니다. 내용 변경은 없습니다.`,
      );
    } catch (requestError) {
      if (isCurrent()) setError(errorMessage(requestError));
    } finally {
      window.clearInterval(elapsedTimer);
      if (isCurrent()) setPlanningIndexElapsed(0);
      setBusyAction("", projectName, runId);
    }
  }, [planningPath, selectedProjectName]);

  const startPlanning = useCallback(async () => {
    const planningSourcePath = planningPath.trim();
    const chatId = selectedChatDraftRef.current.projectName === selectedProjectName ? selectedChatDraftRef.current.id : "";
    const errorKey = chatId ? JSON.stringify([selectedProjectName, chatId]) : selectedProjectName;
    if (
      planningPreparationsRef.current.has(selectedProjectName) || !selectedProjectName ||
      !projectCapabilities ||
      (planningMode === "auto" && !planningSourcePath)
    ) return;
    planningPreparationsRef.current.add(selectedProjectName);
    planningRequestDrafts.current.setChatPreparing(selectedProjectName, chatId, true);
    const initialRunId = selectedContextRef.current.runId;
    let preparedRunId = "";
    let preparationReleased = false;
    const currentStart = () => selectedContextRef.current.projectName === selectedProjectName
      && (Boolean(preparedRunId) && selectedContextRef.current.runId === preparedRunId
        || selectedContextRef.current.runId === initialRunId
          && (selectedChatDraftRef.current.projectName === selectedProjectName ? selectedChatDraftRef.current.id : "") === chatId);
    let pollInFlight = false;
    let pollingTimer: number | undefined;
    const pollPlanningState = async () => {
      if (!preparedRunId || pollInFlight) return;
      pollInFlight = true;
      try {
        const current = await window.orchestrator.request<RunState>(
          "runs.get",
          { projectName: selectedProjectName, runId: preparedRunId },
        );
        replaceRun(selectedProjectName, current);
        if (currentStart()) setPlanningPreparationMessage("");
      } catch (requestError) {
        if (currentStart()) setPlanningPreparationMessage(
          `기획 AI는 실행 중이지만 상태 조회가 지연되고 있습니다. ${errorMessage(requestError)}`,
        );
      } finally {
        pollInFlight = false;
      }
    };
    setBusyAction("runs.start", selectedProjectName, initialRunId);
    setError("");
    setPlanningStartErrors((errors) => ({ ...errors, [errorKey]: "" }));
    setNotice("");
    setPlanningStartElapsed(0);
    setPlanningPreparationMessage(
      planningSourcePath
        ? "기획문서 디렉터리 설정을 저장하고 있습니다."
        : "기획문서 없이 요청과 저장소 코드를 기준으로 실행 객체를 만들고 있습니다.",
    );
    const elapsedStartedAt = Date.now();
    const elapsedTimer = window.setInterval(() => {
      if (currentStart()) setPlanningStartElapsed(
        Math.floor((Date.now() - elapsedStartedAt) / 1000),
      );
    }, 1000);
    try {
      let prepared: RunState | undefined;
      const intent = planningRepositoryIntent(projectCapabilities.repository_maturity.kind, repositoryIntent);
      if (intent === "new_project" && !chatId) {
        const summaries = await window.orchestrator.request<RunSummary[]>("runs.list", { projectName: selectedProjectName, scope: "active" });
        const existing = await findPendingTechnologyPlanning(summaries,
          (runId) => window.orchestrator.request<RunState>("runs.get", { projectName: selectedProjectName, runId }),
          { mode: planningMode, text: planningMode === "directed" ? planningRequest : "", sourcePath: planningSourcePath });
        if (existing) {
          replaceRun(selectedProjectName, existing, currentStart());
          if (currentStart()) {
            setSelectedRunId(existing.id);
            setWorkbenchView("planning");
            setNotice("같은 요청으로 준비 중인 기술 계획을 이어 열었습니다. 이 그룹에서 구성 선택을 계속해 주세요.");
          }
          if (existing.stage !== "reviewed") return;
          prepared = existing;
        }
      }
      if (!prepared) {
        let refreshedIndex: PlanningSourceIndex | undefined;
        if (planningSourcePath) {
          await window.orchestrator.request("projects.updatePlanningSource", {
            projectName: selectedProjectName,
            sourceRoot: planningSourcePath,
          });
          if (currentStart()) setPlanningPreparationMessage("기획 자료를 확인하고 있습니다.");
          refreshedIndex = await window.orchestrator.request<PlanningSourceIndex>(
            "planning.refreshIndex",
            { projectName: selectedProjectName, sourceRoot: planningSourcePath },
          );
          if (currentStart()) setPlanningIndex(refreshedIndex);
          const changedDocumentCount = refreshedIndex.added_count + refreshedIndex.modified_count + refreshedIndex.deleted_count;
          const indexResult = changedDocumentCount
            ? `변경 ${changedDocumentCount.toLocaleString("ko-KR")}개(추가 ${refreshedIndex.added_count.toLocaleString("ko-KR")} · 수정 ${refreshedIndex.modified_count.toLocaleString("ko-KR")} · 삭제 ${refreshedIndex.deleted_count.toLocaleString("ko-KR")})를 수집했습니다.`
            : refreshedIndex.updated_count
              ? `${refreshedIndex.updated_count.toLocaleString("ko-KR")}개 문서를 다시 확인했으며 내용 변경은 없습니다.`
              : "기존 문서 색인을 재사용합니다.";
          const scopeResult = planningMode === "directed"
            ? "요청과 관련된 문서만 찾는 지정 작업 실행 객체를 만들고 있습니다."
            : "미완료 작업을 발굴하는 풀 오토 실행 객체를 만들고 있습니다.";
          if (currentStart()) setPlanningPreparationMessage(
            `기획문서 ${refreshedIndex.document_count.toLocaleString("ko-KR")}개 색인을 확인했습니다. ${indexResult} ${scopeResult}`,
          );
        } else {
          if (currentStart()) setPlanningIndex(undefined);
        }
        prepared = await window.orchestrator.request<RunState>(
          "runs.preparePlanning",
          {
            projectName: selectedProjectName,
            specPath: planningSourcePath,
            ...initialPlanningProfileParams(selectedPlanningProfile, planningReasoning, planningProfileManual),
            effortMode: planningEffortMode,
            planningMode,
            planningRequest: planningMode === "directed" ? planningRequest.trim() : "",
            preparedIndexGeneratedAt: refreshedIndex?.generated_at || "",
            repositoryIntent: planningRepositoryIntent(projectCapabilities.repository_maturity.kind, repositoryIntent),
          },
        );
      }
      preparedRunId = prepared.id;
      const selectPrepared = currentStart();
      planningRequestDrafts.current.update(selectedProjectName, { request: "" }, chatId);
      if (chatId) planningRequestDrafts.current.removeChat(selectedProjectName, chatId);
      replaceRun(selectedProjectName, prepared, selectPrepared);
      if (selectPrepared) {
        setChatDraftSelection(selectedProjectName);
        selectedContextRef.current = { projectName: selectedProjectName, runId: prepared.id };
        setSelectedRunId(prepared.id);
        setWorkbenchView("planning");
        setPlanningPreparationMessage("이 그룹에서 기획 AI를 시작하고 있습니다.");
      }
      planningPreparationsRef.current.delete(selectedProjectName);
      preparationReleased = true;
      setBusyAction("runs.runPlanning", selectedProjectName, prepared.id);
      pollingTimer = window.setInterval(() => {
        void pollPlanningState();
      }, 1500);
      void pollPlanningState();
      const result = await window.orchestrator.request<RunState>(
        "runs.runPlanning",
        { projectName: selectedProjectName, runId: prepared.id },
      );
      replaceRun(selectedProjectName, result, currentStart());
      await loadProjects();
      await loadRuns({
        projectName: selectedProjectName,
        scope: archiveScopeRef.current,
        preferredRun: result.id,
        selectFirst: currentStart(),
      });
      if (currentStart()) {
        setSelectedRunId(result.id);
        setWorkbenchView("planning");
        setNotice("기획 결과를 받았습니다. 이 그룹에서 계속 진행하세요.");
      }
    } catch (requestError) {
      const message = errorMessage(requestError);
      setPlanningStartErrors((errors) => ({ ...errors, [errorKey]: message }));
      if (currentStart()) setError(message);
      await pollPlanningState();
    } finally {
      if (!preparationReleased) planningPreparationsRef.current.delete(selectedProjectName);
      planningRequestDrafts.current.setChatPreparing(selectedProjectName, chatId, false);
      window.clearInterval(elapsedTimer);
      if (pollingTimer !== undefined) window.clearInterval(pollingTimer);
      if (currentStart()) { setPlanningStartElapsed(0); setPlanningPreparationMessage(""); }
      setBusyAction("", selectedProjectName, preparedRunId || initialRunId);
    }
  }, [
    loadProjects,
    loadRuns,
    planningPath,
    planningMode,
    planningRequest,
    planningReasoning,
    planningEffortMode,
    planningProfileManual,
    projectCapabilities,
    repositoryIntent,
    replaceRun,
    selectedPlanningProfile,
    selectedProjectName,
    setChatDraftSelection,
  ]);

  const runPreparedRevisionPlanning = useCallback(async () => {
    if (planningStartPendingRef.current || !selectedProjectName || !selectedRun || selectedRun.stage !== "reviewed") return;
    planningStartPendingRef.current = true;
    setBusyAction("runs.runPlanning");
    setError("");
    try {
      const updated = await window.orchestrator.request<RunState>("runs.runPlanning", {
        projectName: selectedProjectName, runId: selectedRun.id,
      });
      replaceRun(selectedProjectName, updated);
      setNotice("기획 결과를 받았습니다. 작업 내용을 확인해 주세요.");
    } catch (requestError) {
      setError(errorMessage(requestError));
      void loadRunDetail(selectedProjectName, selectedRun.id);
    } finally {
      planningStartPendingRef.current = false;
      setBusyAction("");
    }
  }, [loadRunDetail, replaceRun, selectedProjectName, selectedRun]);

  const openRevisionRun = useCallback(async (runId: string, view: "results" | "planning", message?: string) => {
    if (!selectedProjectName) return;
    try {
      const target = await window.orchestrator.request<RunState>("runs.get", { projectName: selectedProjectName, runId });
      const scope: RunListScope = target.archive ? "archived" : "active";
      archiveScopeRef.current = scope;
      setArchiveScope(scope);
      setSelectedRun(undefined);
      setSelectedRunId(runId);
      setResultFocusTaskId("");
      setWorkbenchView(view);
      if (message) {
        const current = directionChangeDrafts.read(selectedProjectName, runId).text;
        directionChangeDrafts.edit(selectedProjectName, runId, current.trim() ? `${current}\n\n${message}` : message);
      }
      await loadRuns({ projectName: selectedProjectName, scope, preferredRun: runId });
    } catch (requestError) {
      setError(`연결된 작업으로 이동하지 못했습니다. ${errorMessage(requestError)}`);
    }
  }, [directionChangeDrafts, loadRuns, selectedProjectName]);

  const queuePlanningMessage = useCallback(async (taskId?: string) => {
    if (!selectedProjectName || !selectedRun || !selectedPlanningProfile || queueSubmittingRef.current || !planningMessage.trim()) return;
    const projectName = selectedProjectName, runId = selectedRun.id, text = planningMessage.trim();
    const task = taskId ? selectedTaskForDetails(selectedRun, taskDrafts, taskId) : undefined;
    if (taskId && !task) { setError("예약할 작업을 찾지 못했습니다. 입력은 유지됩니다."); return; }
    const profile = { planningAgentId: selectedPlanningProfile.agent_id, planningModel: selectedPlanningProfile.model,
      planningReasoningEffort: planningReasoning };
    const intent = !selectedRun.archive ? chatExecutionIntent(text, selectedRun) : undefined;
    if (intent && intent !== "stop" && (planDirty || nextExecutionProfileDirty)) {
      setError("저장하지 않은 변경을 먼저 확인해 주세요. 입력은 유지됩니다."); return;
    }
    let controlTarget: import("../../shared/planningMessageQueue").QueuedMessageInput["controlTarget"];
    try {
      if (intent) {
        const expected = chatControlParams(projectName, selectedRun, text, "", intent, taskId).expected;
        controlTarget = { planRevision: expected.planRevision, executionId: expected.executionId, scope: expected.scope,
          taskId: expected.taskId, attemptId: expected.attemptId, invocationId: expected.invocationId };
      }
    } catch (requestError) { setError(errorMessage(requestError)); return; }
    const message = task ? taskPlanningQuestion(task, selectedRun, text, planDirty) : text;
    const signature = JSON.stringify([projectName, runId, message, profile, controlTarget]);
    const id = queuedSubmissionRef.current?.signature === signature ? queuedSubmissionRef.current.id : crypto.randomUUID();
    queuedSubmissionRef.current = { signature, id };
    queueSubmittingRef.current = true; setQueueSubmitting(true);
    try {
      const snapshot = await window.orchestrator.queuePlanningMessage({ id, projectName, runId, text, message, taskId, profile,
        afterRequestId: planningRequestFor(planningRequests, projectName, runId)?.requestId, controlTarget, executionMode: intent === "project" ? "project" : undefined });
      setPlanningRequests(current => ({ ...current, messageQueue: snapshot }));
      if (directionChangeDrafts.read(projectName, runId).text.trim() === text) directionChangeDrafts.edit(projectName, runId, "");
      queuedSubmissionRef.current = undefined;
      if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) setError("");
    } catch (requestError) {
      if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) setError(errorMessage(requestError));
    } finally { queueSubmittingRef.current = false; setQueueSubmitting(false); }
  }, [selectedProjectName, selectedRun, selectedPlanningProfile, planningReasoning, planningMessage, taskDrafts, planDirty, nextExecutionProfileDirty, directionChangeDrafts, planningRequests]);

  const changeQueuedMessage = useCallback(async (change: QueuedMessageChange): Promise<boolean> => {
    try {
      const snapshot = await window.orchestrator.changeQueuedPlanningMessage(change);
      setPlanningRequests(current => ({ ...current, messageQueue: snapshot }));
      return true;
    } catch (requestError) {
      if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, change.projectName, change.runId)) setError(errorMessage(requestError));
      return false;
    }
  }, []);
  const restoreQueuedMessage = useCallback(async (item: QueuedPlanningMessage): Promise<boolean> => {
    if (!await changeQueuedMessage({ projectName: item.projectName, runId: item.runId, id: item.id, revision: item.revision, action: "cancel" })) return false;
    const draft = directionChangeDrafts.read(item.projectName, item.runId).text;
    directionChangeDrafts.edit(item.projectName, item.runId, draft.trim() ? `${draft}\n\n${item.text}` : item.text);
    if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, item.projectName, item.runId)) {
      const profile = planningProfiles.find(candidate => candidate.agent_id === item.profile.planningAgentId && candidate.model === item.profile.planningModel);
      const profileKey = profile ? providerProfileKey(profile) : `${item.profile.planningAgentId}\u001f${item.profile.planningModel}`;
      setPlanningProfileKey(profileKey); setPlanningReasoning(item.profile.planningReasoningEffort); setPlanningProfileManual(true);
      editedPlanningProfileContext.current = `${item.projectName}\0${item.runId}`;
      updatePlanningDraft({ profileKey, reasoning: item.profile.planningReasoningEffort, profileManual: true });
      if (!profile) setError("예약에 사용한 AI 설정을 찾지 못했습니다. 전송할 AI를 다시 선택해 주세요.");
      if (item.taskId) setRepairTarget({ projectName: item.projectName, runId: item.runId, taskId: item.taskId });
    }
    return true;
  }, [changeQueuedMessage, directionChangeDrafts, planningProfiles, updatePlanningDraft]);
  const queuedActivity = JSON.stringify(planningRequests.messageQueue?.items.filter(item => item.projectName === selectedProjectName
    && item.runId === selectedRunId && ["sending", "sent", "uncertain", "failed"].includes(item.status)).map(item => [item.id, item.status, item.revision]));
  useEffect(() => {
    if (!selectedProjectName || !selectedRunId || !queuedActivity || queuedActivity === "[]") return;
    void loadRunDetail(selectedProjectName, selectedRunId);
    if (!planningRequests.messageQueue?.items.some(item => item.projectName === selectedProjectName && item.runId === selectedRunId && item.status === "sending")) return;
    const timer = window.setInterval(() => void loadRunDetail(selectedProjectName, selectedRunId), 1500);
    return () => window.clearInterval(timer);
  }, [queuedActivity, selectedProjectName, selectedRunId, loadRunDetail]);

  const sendPlanningMessage = useCallback(async (messageOverride?: string, taskContextId?: string) => {
    if (!selectedProjectName || !selectedRun) return;
    const submittedText = (messageOverride ?? planningMessage).trim();
    if (!submittedText) return;
    const questionTask = taskContextId ? selectedTaskForDetails(selectedRun, taskDrafts, taskContextId) : undefined;
    if (taskContextId && !questionTask) {
      setError("질문할 작업을 찾지 못했습니다. 작업을 다시 선택해 주세요. 입력은 유지됩니다.");
      return;
    }
    const executionIntent = !selectedRun.archive && openPlanningPreviewForMessage(submittedText, selectedRun.repository_intent, () => {}, selectedRun)
      ? undefined : chatExecutionIntent(submittedText, selectedRun);
    if (!selectedRun.archive && executionIntent) {
      if (busyAction || executionIntent !== "stop" && (planDirty || nextExecutionProfileDirty
        || taskPlanningInProgress(taskPlanningRequestsRef.current, selectedProjectName, selectedRun.id))) {
        setError("진행 중인 요청이나 저장하지 않은 변경을 확인한 뒤 복구를 요청해 주세요. 입력은 유지됩니다.");
        return;
      }
      const projectName = selectedProjectName, runId = selectedRun.id;
      const key = runRequestKey(projectName, runId);
      if (chatRecoveryPendingRef.current.has(key)) return;
      chatRecoveryPendingRef.current.add(key);
      const id = ++executionRequestSequenceRef.current;
      const at = new Date().toISOString();
      const previousMessageCount = selectedRun.planning_messages.length;
      const isCurrent = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId);
      const acknowledged = (run: RunState) => run.planning_messages.slice(previousMessageCount)
        .some(item => item.role === "user" && item.text === submittedText);
      let accepted = false, polling = false, active = true;
      const update = (run: RunState) => {
        replaceRun(projectName, run);
        if (acknowledged(run)) {
          accepted = true;
          setPendingPlanningMessage(current => current?.at === at ? undefined : current);
        }
      };
      const onPhase = (phase: ChatExecutionPhase) => setExecutionRequests(current => current[key]?.id !== id ? current : ({
        ...current, [key]: { ...current[key], chatPhase: phase,
          method: phase === "thinking" || phase === "working" ? "runs.controlChat"
            : phase === "stopping" ? "runs.requestStop" : phase === "verifying" ? "runs.verifyAndRepair" : "tasks.repairFromChat" },
      }));
      const stopping = executionIntent !== "project" && (executionIntent === "stop" || selectedRun.execution_control?.can_stop
        || selectedRun.execution_control?.stop_phase === "stopping");
      setExecutionRequests(current => ({ ...current, [key]: { id, method: executionIntent === "project" ? "runs.controlChat" : stopping ? "runs.requestStop" : "tasks.repairFromChat",
        chatPhase: executionIntent === "project" ? "thinking" : stopping ? "stopping" : "repairing", startedAt: Date.now() } }));
      setPendingPlanningMessage({ projectName, runId, text: submittedText, at, previousMessageCount, status: "sending" });
      if (messageOverride === undefined) setPlanningMessage("");
      setError(""); setNotice("");
      const poll = async () => {
        if (!active || polling) return;
        polling = true;
        try {
          const run = await window.orchestrator.request<RunState>("runs.get", { projectName, runId });
          if (active) update(run);
        } catch { /* The work request reports authoritative execution errors. */ }
        finally { polling = false; }
      };
      const timer = window.setInterval(() => void poll(), 1500);
      try {
        const run = await controlExecutionFromChat({
          projectName, run: selectedRun, taskId: taskContextId, message: submittedText, requestId: crypto.randomUUID(), intent: executionIntent,
          profile: selectedPlanningProfile ? { planningAgentId: selectedPlanningProfile.agent_id,
            planningModel: selectedPlanningProfile.model, planningReasoningEffort: planningReasoning } : undefined,
          request: (method, params) => window.orchestrator.request(method, params), isCurrent,
          onRun: update, onPhase,
        });
        if (run) update(run);
      } catch (requestError) {
        const message = errorMessage(requestError);
        let reportedInChat = false;
        try {
          const latest = await window.orchestrator.request<RunState>("runs.get", { projectName, runId });
          if (latest.id === runId) {
            update(latest);
            reportedInChat = chatExecutionErrorReported(latest, previousMessageCount, submittedText, message);
          }
        } catch { /* Keep the request error visible when its conversation record cannot be confirmed. */ }
        if (isCurrent() && !reportedInChat) setError(message);
      } finally {
        active = false; window.clearInterval(timer);
        chatRecoveryPendingRef.current.delete(key);
        setExecutionRequests(current => {
          if (current[key]?.id !== id) return current;
          const next = { ...current }; delete next[key]; return next;
        });
        setPendingPlanningMessage(current => current?.at === at ? undefined : current);
        if (!accepted && messageOverride === undefined && !directionChangeDrafts.read(projectName, runId).text) {
          directionChangeDrafts.edit(projectName, runId, submittedText);
        }
        if (accepted) {
          if (questionTask) failedQuestionDrafts.current.release(projectName, runId,
            failedTaskQuestionKey(projectName, selectedRun, questionTask));
          setRepairTarget(current => current?.projectName === projectName && current.runId === runId
            && current.taskId === taskContextId ? undefined : current);
        }
      }
      return;
    }
    let previewEntryBlocked = false;
    if (!selectedRun.archive && openPlanningPreviewForMessage(submittedText, selectedRun.repository_intent, () => {
      setNotice("");
      if (["verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(selectedRun.stage)) {
        setWorkbenchView("results");
        setWorkDetailsOpen(true);
        setNotice("변경 기록에서 대화로 수정안을 만든 뒤 확인해 주세요.");
        return;
      }
      if (planningApplyEntryBlocked(selectedRun)) {
        previewEntryBlocked = true;
        setNotice("작업 실행 중입니다. 작업이 끝나면 변경안을 확인해 주세요.");
        return;
      }
      setPlanningPreviewTarget({ projectName: selectedProjectName, runId: selectedRun.id, taskId: taskContextId });
    }, selectedRun)) {
      if (!previewEntryBlocked && messageOverride === undefined) setPlanningMessage("");
      setError("");
      return;
    }
    const diagnostic = questionTask?.status === "failed" ? failedQuestionDrafts.current.diagnostic(
      selectedProjectName, selectedRun.id, failedTaskQuestionKey(selectedProjectName, selectedRun, questionTask)) : "";
    const submittedMessage = questionTask ? taskPlanningQuestion(questionTask, selectedRun, submittedText, planDirty, diagnostic) : submittedText;
    const submittedAt = new Date().toISOString();
    const runId = selectedRun.id;
    const currentChat = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, selectedProjectName, runId);
    const previousMessageCount = selectedRun.planning_messages.length;
    const activeAgentName = (
      selectedRun.planning_provider_id === "codex" ||
      selectedPlanningProfile?.provider_id === "codex"
    )
      ? "Codex"
      : "기획 AI";
    const waitingForAgentMessage =
      `메시지를 대화에 추가했습니다. ${activeAgentName}가 요청을 확인하고 있습니다.`;
    let messageAcknowledged = false;
    let pollInFlight = false;
    let pollingTimer: number | undefined;
    const messageWasAcknowledged = (run: RunState) =>
      run.planning_messages
        .slice(previousMessageCount)
        .some((item) => item.role === "user" && item.text === submittedMessage);
    const pollPlanningState = async () => {
      if (pollInFlight) return;
      pollInFlight = true;
      try {
        const current = await window.orchestrator.request<RunState>("runs.get", {
          projectName: selectedProjectName,
          runId,
        });
        messageAcknowledged = messageWasAcknowledged(current);
        if (messageAcknowledged) {
          setPendingPlanningMessage((pending) =>
            pending?.at === submittedAt ? undefined : pending,
          );
          currentChat() && setPlanningPreparationMessage("");
        } else {
          currentChat() && setPlanningPreparationMessage(waitingForAgentMessage);
        }
        replaceRun(selectedProjectName, current);
      } catch (requestError) {
        currentChat() && setPlanningPreparationMessage(
          `${activeAgentName} 작업은 진행 중이지만 상태 조회가 지연되고 있습니다. ${errorMessage(requestError)}`,
        );
      } finally {
        pollInFlight = false;
      }
    };
    if (messageOverride === undefined) setPlanningMessage("");
    setPendingPlanningMessage({
      projectName: selectedProjectName, runId,
      text: submittedMessage,
      at: submittedAt,
      previousMessageCount,
      status: "sending",
    });
    const finishTaskPlanning = beginTaskPlanning({ projectName: selectedProjectName, runId, taskId: taskContextId });
    setBusyAction("runs.sendPlanningMessage");
    setError("");
    setNotice("");
    setPlanningStartElapsed(0);
    currentChat() && setPlanningPreparationMessage(waitingForAgentMessage);
    const elapsedStartedAt = Date.now();
    const elapsedTimer = window.setInterval(() => {
      currentChat() && setPlanningStartElapsed(
        Math.floor((Date.now() - elapsedStartedAt) / 1000),
      );
    }, 1000);
    pollingTimer = window.setInterval(() => {
      void pollPlanningState();
    }, 1500);
    void pollPlanningState();
    try {
      const requestParams = {
        projectName: selectedProjectName,
        runId,
        message: submittedMessage,
        ...planningMessageProfileParams(selectedPlanningProfile, planningReasoning, planningProfileManual),
      };
      const performSend = () =>
        window.orchestrator.request<RunState>(
          "runs.sendPlanningMessage",
          requestParams,
        );
      let updated: RunState;
      try {
        updated = await performSend();
      } catch (requestError) {
        const recovery = await recoverStaleRunLock(
          selectedProjectName,
          runId,
          requestError,
        );
        if (recovery === "cancelled") {
          throw new Error(
            "중단된 실행 잠금 정리를 취소했습니다. 메시지를 다시 전송해 주세요.",
          );
        }
        if (recovery !== "recovered") throw requestError;
        updated = await performSend();
      }
      messageAcknowledged = true;
      if (questionTask) failedQuestionDrafts.current.release(selectedProjectName, runId,
        failedTaskQuestionKey(selectedProjectName, selectedRun, questionTask));
      setRepairTarget((current) => current?.projectName === selectedProjectName && current.runId === runId
        && current.taskId === taskContextId ? undefined : current);
      if (currentChat()) { editedPlanningProfileContext.current = ""; setPlanningProfileManual(false); }
      setPendingPlanningMessage((pending) =>
        pending?.at === submittedAt ? undefined : pending,
      );
      replaceRun(selectedProjectName, updated);
      if (!updated.archive && updated.repository_intent !== "new_project") {
        try {
          const candidate = await window.orchestrator.request<PlanningApplyPreview | null>(
            "runs.getPlanningPreview", { projectName: selectedProjectName, runId },
          );
          if (candidate && !candidate.stale && candidate.status === "preview"
            && candidate.conversation_revision === updated.planning_conversation_revision
            && runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, selectedProjectName, runId)) {
            setPlanningPreviewTarget({ projectName: selectedProjectName, runId, taskId: taskContextId });
          }
        } catch (previewError) {
          currentChat() && setError(`계획 변경 미리보기를 확인하지 못했습니다. ${errorMessage(previewError)}`);
        }
      }
      const applyResult = !updated.archive ? updated.planning_apply_requests?.[updated.planning_apply_requests.length - 1] : undefined;
      if (currentChat() && applyResult?.status === "queued") {
        setNotice("현재 실행이 끝난 뒤 같은 작업 그룹에 반영하도록 예약했습니다.");
      } else if (currentChat() && applyResult?.status === "succeeded") {
        setNotice(
          `작업에 반영했습니다. 추가 ${applyResult.added_tasks}개 · 수정 ${applyResult.updated_tasks}개 · 유지 ${applyResult.unchanged_tasks}개`,
        );
      }
    } catch (requestError) {
      if (currentChat()) setError(errorMessage(requestError));
      await pollPlanningState();
      if (!messageAcknowledged) {
        if (messageOverride === undefined && !directionChangeDrafts.read(selectedProjectName, runId).text) {
          directionChangeDrafts.edit(selectedProjectName, runId, submittedText);
        }
        setPendingPlanningMessage((pending) =>
          pending?.at === submittedAt
            ? { ...pending, status: "unconfirmed" }
            : pending,
        );
      }
    } finally {
      window.clearInterval(elapsedTimer);
      if (pollingTimer !== undefined) window.clearInterval(pollingTimer);
      finishTaskPlanning();
      setPlanningStartElapsed(0);
      currentChat() && setPlanningPreparationMessage("");
      setBusyAction("", selectedProjectName, runId);
    }
  }, [
    beginTaskPlanning,
    busyAction,
    directionChangeDrafts,
    executionAction,
    nextExecutionProfileDirty,
    planDirty,
    planningMessage,
    planningReasoning,
    planningProfileManual,
    recoverStaleRunLock,
    replaceRun,
    selectedPlanningProfile,
    selectedProjectName,
    selectedRun,
    taskDrafts,
  ]);

  const applyPlanningConversation = useCallback(async () => {
    if (!selectedProjectName || !selectedRun) return;
    if (initialTaskPlanningAvailable(selectedRun)) {
      if (planDirty) { setError("미저장 계획 편집을 저장하거나 취소한 뒤 Task를 만들어 주세요."); return; }
      await sendPlanningMessage("논의한 내용으로 Task 만들어줘");
      return;
    }
    if (selectedRun.repository_intent !== "new_project") {
      if (planningApplyEntryBlocked(selectedRun)) {
        setNotice("작업 실행 중입니다. 작업이 끝나면 변경안을 확인해 주세요.");
        return;
      }
      setPlanningPreviewTarget({ projectName: selectedProjectName, runId: selectedRun.id });
      return;
    }
    if (planDirty) {
      setError("미저장 작업 편집이 있습니다. 변경을 저장하거나 취소한 뒤 기획 대화를 반영해 주세요.");
      return;
    }
    const requestId = crypto.randomUUID();
    const runId = selectedRun.id;
    const isCurrent = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, selectedProjectName, runId);
    const finishTaskPlanning = beginTaskPlanning({ projectName: selectedProjectName, runId });
    setBusyAction("runs.applyPlanningConversation");
    setError("");
    setNotice("");
    try {
      const updated = await window.orchestrator.request<RunState>("runs.applyPlanningConversation", {
        projectName: selectedProjectName,
        runId,
        requestId,
        expectedRevision: selectedRun.plan_revision,
        conversationRevision: selectedRun.planning_conversation_revision || 0,
      });
      replaceRun(selectedProjectName, updated);
      if (!isCurrent()) return;
      const result = [...(updated.planning_apply_requests || [])]
        .reverse()
        .find((request) => request.request_id === requestId)
        || updated.planning_apply_requests?.[updated.planning_apply_requests.length - 1];
      if (result?.status === "queued") {
        setNotice("현재 실행이 끝난 뒤 같은 작업 그룹에 반영하도록 예약했습니다.");
      } else if (result?.status === "succeeded") {
        setNotice(
          `작업에 반영했습니다. 추가 ${result.added_tasks}개 · 수정 ${result.updated_tasks}개 · 유지 ${result.unchanged_tasks}개`,
        );
      } else {
        setNotice("현재 작업 그룹의 작업 반영 상태를 확인하세요.");
      }
    } catch (requestError) { if (isCurrent()) setError(errorMessage(requestError)); }
    finally { finishTaskPlanning(); setBusyAction("", selectedProjectName, runId); }
  }, [beginTaskPlanning, planDirty, replaceRun, selectedProjectName, selectedRun, sendPlanningMessage]);

  const runGreenfieldAction = useCallback(async (kind: "answer" | "confirm" | "plan" | "start" | "features", answer = "", optionId = "", revision = 0) => {
    if (!selectedProjectName || !selectedRun || greenfieldActionPendingRef.current) return;
    if (planDirty) { setError("미저장 계획 편집을 저장하거나 취소한 뒤 진행해 주세요."); return; }
    greenfieldActionPendingRef.current = true;
    const projectName = selectedProjectName;
    const runId = selectedRun.id;
    const submittedMessage = planningMessage;
    const isVisible = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId);
    const update = (run: RunState) => replaceRun(projectName, run);
    setBusyAction(kind === "confirm" ? "runs.confirmTechStack" : kind === "start" ? "runs.confirmPlan" : kind === "features" ? "planning.generateFeaturePlan" : "runs.applyPlanningConversation");
    setError(""); setNotice(""); setPlanningStartElapsed(0);
    const startedAt = Date.now();
    let pollInFlight = false;
    let pollingActive = true;
    const timer = window.setInterval(() => {
      if (isVisible()) setPlanningStartElapsed(Math.floor((Date.now() - startedAt) / 1000));
      if (!pollingActive || pollInFlight) return;
      pollInFlight = true;
      void window.orchestrator.request<RunState>("runs.get", { projectName, runId }).then((run) => {
        if (pollingActive) update(run);
      }).catch(() => {
        // The operation result remains authoritative when a status read fails.
      }).finally(() => { pollInFlight = false; });
    }, 1500);
    try {
      const context = {
        projectName, run: selectedRun, request: window.orchestrator.request,
        requestId: crypto.randomUUID(), onUpdate: update,
        profile: planningMessageProfileParams(selectedPlanningProfile, planningReasoning, planningProfileManual),
      };
      if (kind === "features") {
        update(await window.orchestrator.request<RunState>("planning.generateFeaturePlan", { projectName, runId }));
        if (isVisible()) setNotice("기능 계획을 준비했습니다. 내용을 확인한 뒤 작업을 시작하세요.");
      } else if (kind === "start") {
        const approved = await confirmGreenfieldExecution(context);
        pollingActive = false;
        setBusyAction("runs.execute");
        await requestRunAction("runs.execute", undefined, false, approved);
      } else {
        const retry = greenfieldRetry(selectedRun);
        const updated = kind === "confirm" ? await confirmGreenfieldOption(context, optionId, revision)
          : await requestGreenfieldPlan(context, kind === "answer" ? answer : retry?.answer_message || "");
        if (isVisible()) {
          const latest = updated.planning_apply_requests?.[updated.planning_apply_requests.length - 1];
          setNotice(latest?.status === "applying" || latest?.status === "queued" ? "저장한 요청을 처리 중입니다. 이 그룹에서 이어서 확인하세요."
            : updated.bootstrap_spec ? "구성을 저장하고 기본 구조 계획을 준비했습니다. 범위를 확인한 뒤 시작하세요." : "답변을 저장하고 추천을 갱신했습니다.");
          if (latest?.status === "succeeded") setPlanningMessage((current) => current === submittedMessage ? "" : current);
        }
      }
    } catch (requestError) {
      try { update(await window.orchestrator.request<RunState>("runs.get", { projectName, runId })); } catch { /* Preserve the last saved result and the original error. */ }
      if (isVisible()) setError(errorMessage(requestError));
    } finally {
      pollingActive = false;
      window.clearInterval(timer);
      greenfieldActionPendingRef.current = false;
      setBusyAction("", projectName, runId);
    }
  }, [planDirty, replaceRun, requestRunAction, selectedPlanningProfile, planningProfileManual, planningReasoning, planningMessage, selectedProjectName, selectedRun]);

  const configureBootstrapInstructions = useCallback(async (create: boolean, expectedRevision: number, expectedDigest: string) => {
    if (!selectedProjectName || !selectedRun) return;
    const runId = selectedRun.id;
    const isCurrent = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, selectedProjectName, runId);
    setBusyAction("runs.configureBootstrapInstructions");
    setError("");
    setNotice("");
    try {
      const updated = await window.orchestrator.request<RunState>("runs.configureBootstrapInstructions", {
        projectName: selectedProjectName,
        runId: selectedRun.id,
        create,
        expectedRevision,
        expectedDigest,
      });
      replaceRun(selectedProjectName, updated);
      if (isCurrent()) setNotice(create ? "프로젝트 작업 지침을 초기화 범위에 포함했습니다." : "이번 초기화에서 AGENTS.md 생성을 제외했습니다.");
    } catch (requestError) {
      if (isCurrent()) setError(errorMessage(requestError));
    } finally {
      setBusyAction("", selectedProjectName, runId);
    }
  }, [replaceRun, selectedProjectName, selectedRun]);

  const generateFeaturePlan = useCallback(async () => {
    await runGreenfieldAction("features");
  }, [runGreenfieldAction]);

  const interruptPlanning = useCallback(async () => {
    if (!selectedProjectName || !selectedRunId) return;
    const projectName = selectedProjectName, runId = selectedRunId;
    const target = planningRequestFor(planningRequests, projectName, runId);
    const current = () => runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId);
    try {
      const snapshot = await window.orchestrator.planningRequests();
      setPlanningRequests(snapshot);
      const owner = planningRequestFor(snapshot, projectName, runId);
      if (!target || target.projectName !== projectName || target.runId !== runId) throw new Error("중단할 대화 요청을 확인하지 못했습니다. 상태를 다시 확인해 주세요.");
      if (!owner || owner.requestId !== target.requestId || owner.projectName !== projectName || owner.runId !== runId) {
        if (snapshot.recent.some(item => item.requestId === target.requestId && ["succeeded", "interrupted"].includes(item.phase))) {
          if (current()) { setError(""); setNotice("요청이 이미 종료됐습니다."); }
          return;
        }
        throw new Error("중단할 대화 요청이 변경됐습니다. 상태를 다시 확인해 주세요.");
      }
      const updated = await window.orchestrator.interruptPlanning<RunState>(projectName, runId, target.requestId);
      setPlanningRequests(await window.orchestrator.planningRequests());
      if (updated) replaceRun(projectName, updated);
      if (current()) { setError(""); setNotice(updated ? "해당 AI 요청을 중단했습니다. 기존 작업 결과는 유지됩니다." : "요청이 이미 종료됐습니다."); }
    } catch (requestError) { if (current()) setError(errorMessage(requestError)); }
  }, [replaceRun, selectedProjectName, selectedRunId, planningRequests]);

  const restartBackend = useCallback(async () => {
    setBusyAction("system.restartBackend");
    try {
      const restarted = await window.orchestrator.restartBackend();
      if (restarted) {
        setError("");
        setNotice("");
        window.location.reload();
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyAction("");
    }
  }, []);

  const openGlobalGroup = useCallback((projectName: string, runId: string, archived = false, view?: "operations") => {
    setChatDraftSelection(projectName);
    newWorkProjectRef.current = "";
    setChoosingNewWorkProject(false);
    setHomeView("work");
    setSideInspectorOpen(false);
    if (!projectsRef.current.some((project) => project.name === projectName)) {
      setNotice("선택한 프로젝트가 등록 목록에 없습니다. 진행 목록을 다시 확인해 주세요.");
      void loadActiveGroups();
      return;
    }
    pendingGlobalGroupRef.current = { projectName, runId };
    applySummaryEntryRef.current = view === "operations" ? { projectName, runId } : undefined;
    if (view === "operations") applySummaryOpenerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    archiveScopeRef.current = archived ? "archived" : "active";
    setArchiveScope(archived ? "archived" : "active");
    setSelectedRecoveryTaskId("");
    setResultFocusTaskId("");
    setWorkbenchView(view || (archived ? "results" : "tasks"));
    setWorkListOpen(false);
    if (selectedContextRef.current.projectName === projectName) {
      setSelectedRunId(runId);
      void loadRuns({ projectName, scope: archived ? "archived" : "active", preferredRun: runId });
    } else {
      selectProject(projectName);
    }
    if (view === "operations" && selectedContextRef.current.projectName === projectName && selectedRunRef.current?.id === runId) openApplySummary();
  }, [loadActiveGroups, loadRuns, openApplySummary, selectProject, setChatDraftSelection]);

  const openProjectSelection = useCallback((forNewWork = false) => {
    setChoosingNewWorkProject(forNewWork);
    setHomeView("overview");
    setSideInspectorOpen(false);
    window.requestAnimationFrame(() => document.getElementById("chat-home-title")?.focus({ preventScroll: true }));
  }, []);

  const openChatDraft = useCallback((projectName: string, chatId: string) => {
    const project = projectsRef.current.find((item) => item.name === projectName);
    if (!project) {
      setNotice("선택한 프로젝트가 등록 목록에 없습니다. 프로젝트 목록을 다시 확인해 주세요.");
      return;
    }
    if (!planningRequestDrafts.current.chatSnapshot().some(chat => chat.projectName === projectName && chat.id === chatId)) {
      setNotice("선택한 새 채팅 초안을 찾지 못했습니다."); return;
    }
    pendingGlobalGroupRef.current = undefined;
    pendingNotificationRef.current = undefined;
    pendingAttentionRef.current = undefined;
    newWorkProjectRef.current = projectName;
    selectProject(projectName);
    setChatDraftSelection(projectName, chatId);
    selectedContextRef.current = { projectName, runId: "" };
    runDetailRequestRef.current += 1;
    setSelectedRunId("");
    setSelectedRun(undefined);
    setSelectedRunProjectName("");
    setSelectedTaskIds([]);
    archiveScopeRef.current = "active";
    setArchiveScope("active");
    setChoosingNewWorkProject(false);
    setHomeView("work");
    setSideInspectorOpen(false);
    setError("");
    setPlanningIndex(undefined);
    setPlanningIndexElapsed(0);
    setPlanningStartElapsed(0);
    setPlanningPreparationMessage("");
    restorePlanningDraft(projectName, project.planning_source_dir || "");
    setWorkbenchView("planning");
    setNotice("");
    window.requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>("#planning-sidebar textarea")?.focus({ preventScroll: true }));
  }, [restorePlanningDraft, selectProject, setChatDraftSelection]);

  const startProjectWork = useCallback((projectName: string) => {
    const project = projectsRef.current.find(item => item.name === projectName);
    if (!project) { setNotice("선택한 프로젝트가 등록 목록에 없습니다. 프로젝트 목록을 다시 확인해 주세요."); return; }
    const chatId = crypto.randomUUID();
    planningRequestDrafts.current.createChat(projectName, chatId, project.planning_source_dir || "");
    openChatDraft(projectName, chatId);
  }, [openChatDraft]);

  const deleteChatDraft = useCallback((projectName: string, chatId: string) => {
    const draft = planningRequestDrafts.current.chatSnapshot().find(chat => chat.projectName === projectName && chat.id === chatId);
    if (!draft || draft.preparing) return;
    planningRequestDrafts.current.removeChat(projectName, chatId);
    if (selectedContextRef.current.projectName !== projectName || selectedContextRef.current.runId || selectedChatDraftRef.current.id !== chatId) return;
    const next = planningRequestDrafts.current.chatSnapshot().find(chat => chat.projectName === projectName);
    if (next) openChatDraft(projectName, next.id);
    else {
      setChatDraftSelection(projectName);
      restorePlanningDraft(projectName, projectsRef.current.find(project => project.name === projectName)?.planning_source_dir || "");
    }
  }, [openChatDraft, restorePlanningDraft, setChatDraftSelection]);

  const addProject = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      setBusyAction("projects.add");
      setError("");
      try {
        const project = await window.orchestrator.request<RegisteredProject>(
          "projects.add",
          { ...projectDraft },
        );
        setProjectDialogOpen(false);
        setProjectDraft(emptyProjectDraft);
        await loadProjects();
        if (projectRegistrationIntent) startProjectWork(project.name);
        else selectProject(project.name);
        setProjectRegistrationIntent("");
        setNotice("프로젝트를 등록했습니다.");
      } catch (requestError) {
        setError(errorMessage(requestError));
      } finally {
        setBusyAction("");
      }
    },
    [loadProjects, projectDraft, selectProject, startProjectWork, projectRegistrationIntent],
  );

  useLayoutEffect(() => {
    const main = workMainRef.current;
    if (!main) return;
    const measure = () => setWorkMainWidth(main.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure); observer.observe(main);
    return () => observer.disconnect();
  }, []);

  const openTechStackPlanning = useCallback(async () => {
    if (!selectedProjectName || techStackEntryPendingRef.current) return;
    setProjectSettingsOpen(false);
    if (selectedRunProjectName === selectedProjectName && selectedRun?.id === selectedRunId
      && selectedRun?.repository_intent === "new_project") {
      setHomeView("work");
      setWorkbenchView("planning");
      setSideInspectorOpen(false);
      window.requestAnimationFrame(() => {
        const heading = document.getElementById("tech-stack-decision-title") || document.getElementById("planning-workbench-title");
        if (heading) scrollPlanningContentIntoView(heading, "start");
        heading?.focus({ preventScroll: true });
      });
    } else {
      techStackEntryPendingRef.current = true;
      try {
        const summaries = await window.orchestrator.request<RunSummary[]>("runs.list", { projectName: selectedProjectName, scope: "active" });
        const existing = await findPendingTechnologyPlanning(summaries,
          (runId) => window.orchestrator.request<RunState>("runs.get", { projectName: selectedProjectName, runId }));
        if (selectedContextRef.current.projectName !== selectedProjectName) return;
        if (existing) {
          replaceRun(selectedProjectName, existing, true);
          setSelectedRunId(existing.id);
          setHomeView("work");
          setWorkbenchView("planning");
          setSideInspectorOpen(false);
          setNotice("준비 중인 기술 계획을 이어 열었습니다.");
        } else {
          startProjectWork(selectedProjectName);
        }
      } catch (requestError) {
        setError(`기존 기술 계획을 확인하지 못했습니다. ${errorMessage(requestError)}`);
      } finally {
        techStackEntryPendingRef.current = false;
      }
    }
  }, [replaceRun, selectedProjectName, selectedRun, selectedRunId, selectedRunProjectName, startProjectWork]);

  const closeAttentionInbox = useCallback(() => {
    setAttentionOpen(false);
    window.requestAnimationFrame(() => {
      const trigger = attentionTriggerRef.current;
      if (trigger?.getClientRects().length) trigger.focus({ preventScroll: true });
      else document.querySelector<HTMLButtonElement>(".navigation-launcher")?.focus({ preventScroll: true });
    });
  }, []);

  const openAttentionItem = useCallback((item: AttentionItem) => {
    if (!projectsRef.current.some((project) => project.name === item.project_name)) {
      setAttentionError("대상 프로젝트가 등록 목록에 없습니다. 새로고침해 주세요.");
      void loadAttentionItems();
      return;
    }
    const alreadySelected = selectedContextRef.current.projectName === item.project_name && selectedContextRef.current.runId === item.run_id;
    setAttentionFocusRequest(undefined);
    pendingAttentionRef.current = item;
    pendingNotificationRef.current = undefined;
    setSelectedRun(undefined);
    openGlobalGroup(item.project_name, item.run_id);
    if (alreadySelected) void loadRunDetail(item.project_name, item.run_id);
    setAttentionOpen(false);
  }, [loadAttentionItems, loadRunDetail, openGlobalGroup]);

  const currentReasoningOptions = selectedPlanningProfile?.reasoning_efforts || [];
  const isBusy = Boolean(busyAction || hasExecutionRequests);
  const removeProjectReason = projectRemovalReason(selectedProjectName, executionRequests, busyAction, busyProjectRef.current, removingProjectName, planningRequests);
  const planningPaneMax = Math.max(320, Math.min(576, workMainWidth - 488));
  const visiblePlanningPaneWidth = clamp(planningPaneWidth, 320, planningPaneMax);
  const workspaceStyle = {
    "--inspector-width": `${inspectorWidth}px`,
  } as CSSProperties;

  const repairTask = repairTarget?.projectName === selectedProjectName && repairTarget.runId === selectedRun?.id
    ? selectedTaskForDetails(selectedRun, taskDrafts, repairTarget.taskId)
    : undefined;
  const planningTaskIds = selectedRun?.tasks.filter((task) => taskPlanningInProgress(
    taskPlanningRequests, selectedProjectName, selectedRun.id, task.id,
  )).map((task) => task.id) || [];
  const repairStartedAt = selectedRun ? Object.values(taskPlanningRequests).find((target) =>
    target.projectName === selectedProjectName && target.runId === selectedRun.id
    && selectedRun.tasks.some((task) => task.status === "failed" && (!target.taskId || target.taskId === task.id)),
  )?.startedAt : undefined;
  const repairKey = JSON.stringify([selectedProjectName, selectedRun?.id, repairTask?.id]);
  const failedQuestionKey = selectedRun && repairTask?.status === "failed" && selectedRun.tasks.some((task) => task.id === repairTask.id)
    ? failedTaskQuestionKey(selectedProjectName, selectedRun, repairTask) : "";
  failedQuestionTargetRef.current = homeView === "work" ? failedQuestionKey : "";
  const directionDraft = selectedRun ? directionChangeDrafts.read(selectedProjectName, selectedRun.id) : undefined;
  const resultDraftKey = resultRevisionRequestKey(selectedProjectName, selectedRun?.id || "",
    selectedRun?.tasks.some((task) => task.id === resultFocusTaskId) ? resultFocusTaskId : "");
  // 진행 안내가 위에 있으면 빈 슬롯을 유지해 작업 요약으로도 다시 표시하지 않는다.
  const groupNextAction = runLockBlocking.context === taskViewContext && runLockBlocking.progress
    && nextAction?.kind === "none" && nextAction.tone === "active" && !recoveryGuidance
    && !(selectedWaiting && !postponedWaiting[waitingKey]) ? <></>
    : runLockBlocking.context === taskViewContext && runLockBlocking.blocking ? null : selectedWaiting && !postponedWaiting[waitingKey] ? <NextStepWaitingBanner
    prompt={selectedWaiting} busy={Boolean(busyAction || executionAction || waitingChecks[taskViewContext])}
    onAction={() => void invokeWaitingAction(selectedWaiting.source_key)}
    onLater={() => setPostponedWaiting((current) => ({ ...current, [waitingKey]: true }))}
  /> : selectedRun && !selectedRun.archive && nextAction && !(executionOnTaskCards(selectedRun) && nextAction.kind === "none") ? <RunNextActionBanner action={nextAction}
    recovery={recoveryGuidance} busy={Boolean(busyAction || executionAction || waitingChecks[taskViewContext])}
    expanded={Boolean(guidanceExpanded[taskViewContext])}
    onToggle={() => setGuidanceExpanded((current) => ({ ...current, [taskViewContext]: !current[taskViewContext] }))}
    onInvoke={() => invokeNextAction(nextAction)} /> : null;
  const usageContextKey = JSON.stringify([selectedProjectName, selectedRun?.id || ""]);
  const currentUsage = usageSnapshots[usageContextKey];
  const chatSettingsTask = selectedRun?.tasks.find(task => task.id === selectedTaskId)
    || selectedRun?.tasks.find(task => task.status === "failed")
    || selectedRun?.tasks.find(task => task.status === "pending");
  const chatTaskSettings = selectedRun && chatSettingsTask ? <ChatTaskSettings
    key={`chat-task-settings:${selectedProjectName}:${selectedRun.id}:${chatSettingsTask.id}`}
    projectName={selectedProjectName} run={selectedRun} task={chatSettingsTask}
    options={taskProfileOptions[chatSettingsTask.id] || []} usage={currentUsage?.snapshot} usageError={currentUsage?.error}
    busy={Boolean(busyAction || planningTaskIds.includes(chatSettingsTask.id) || (executionAction && chatSettingsTask.status !== "pending"))}
    onDirtyChange={setNextExecutionProfileDirty} onRefresh={() => void loadRunDetail(selectedProjectName, selectedRun.id)}
    onSave={async (selection, expected) => {
      setBusyAction("tasks.updateExecutionProfile");
      try {
        const updated = await window.orchestrator.request<RunState>("tasks.updateExecutionProfile", {
          projectName: selectedProjectName, runId: selectedRun.id, taskId: chatSettingsTask.id,
          agentId: selection.agentId, model: selection.model, reasoningEffort: selection.reasoningEffort, expectedProfile: expected,
        });
        if (updated.id !== selectedRun.id || !updated.tasks.some(task => task.id === chatSettingsTask.id
          && task.agent_id === selection.agentId && task.model === selection.model && task.reasoning_effort === selection.reasoningEffort)) {
          throw new Error("저장된 실행 모델을 확인하지 못했습니다.");
        }
        replaceRun(selectedProjectName, updated);
        return updated;
      } finally { setBusyAction(""); }
    }} /> : null;
  const groupUsage = selectedRun ? <details className="work-group-settings"><summary>사용량·작업 기록</summary><UsagePanel key={`usage:${selectedProjectName}:${selectedRun.id}`}
    projectName={selectedProjectName} runId={selectedRun.id}
    running={Boolean(selectedRun.active_step || executionAction || selectedRun.tasks.some((task) => ["running", "reviewing", "revising"].includes(task.status)))}
    onSnapshot={(snapshot) => setUsageSnapshots((current) => ({ ...current, [usageContextKey]: { snapshot, error: "" } }))}
    onError={(error) => setUsageSnapshots((current) => ({ ...current, [usageContextKey]: { ...current[usageContextKey], error } }))}
    refreshKey={`${selectedRun.stage}:${selectedRun.effort_control?.current_policy?.policy_id || ""}:${selectedRun.active_step || ""}`} /></details> : null;
  return (
    <div className="app-shell work-centered chat-first" data-home={homeView}>
      <main className="main-area">
        <NavigationSidebar openRequest={navigationOpenRequest}>
          <nav className="work-navigation" aria-label="주 탐색">
            <button className="button button--primary work-navigation__new" type="button" data-navigation-action onClick={() => openProjectSelection(true)}><Plus aria-hidden="true" size={15} />새 작업</button>
            <button type="button" data-navigation-action aria-current={homeView === "overview" ? "page" : undefined} onClick={() => openProjectSelection()}>내 프로젝트</button>
            <AttentionInboxTrigger snapshot={attentionSnapshot} error={attentionError} open={attentionOpen} buttonRef={attentionTriggerRef}
              onClick={() => { setAttentionOpen(true); void loadAttentionItems(); }} />
            <button type="button" data-navigation-action aria-current={homeView === "history" ? "page" : undefined} onClick={() => { setHomeView("history"); setSideInspectorOpen(false); }}>완료한 작업</button>
            <ChatProjectNavigation projects={projects} cache={runSummaryCache} projectName={selectedProjectName} run={selectedRun}
              drafts={chatDrafts} selectedDraftId={!selectedRunId ? selectedChatDraft.id : undefined}
              onOpenDraft={openChatDraft} onDeleteDraft={deleteChatDraft}
              planning={planningRequests} deleting={deletingRunId ? { projectName: deletingProjectName, runId: deletingRunId } : undefined}
              archiving={archivingRunId ? { projectName: archivingProjectName, runId: archivingRunId } : undefined}
              onProject={selectProject} onOpen={openGlobalGroup} onNew={startProjectWork}
              onArchive={(projectName, runId) => void archiveRun(runId, projectName)}
              onDelete={(projectName, runId) => void deleteRun(runId, projectName, "active")}
              onHistory={(projectName) => { selectProject(projectName); setWorkDetailsOpen(true); setWorkListOpen(true); }} />
            {selectedRun && !runSummaryCache[selectedProjectName]?.active.some(item => item.id === selectedRun.id) ? <CurrentWorkNavigation projectName={selectedProjectName} run={selectedRun}
              active={homeView === "work"} onOpen={() => setHomeView("work")} /> : null}
            <div className="work-navigation__footer">
              <button type="button" data-navigation-action aria-current={homeView === "settings" ? "page" : undefined} onClick={() => { setHomeView("settings"); setSideInspectorOpen(false); }}>설정</button>
              <span className="backend-state" data-error={backendRecoveryNeeded} data-unknown={!backendChecked} role="status"><CircleDot aria-hidden="true" size={14} />{backendRecoveryNeeded ? "실행 엔진 오류" : backendChecked ? "실행 엔진 연결됨" : "실행 엔진 확인 필요"}</span>
            </div>
          </nav>
        </NavigationSidebar>
        <div className="work-main" ref={workMainRef}>
        <header className="topbar">
          <div className="work-location">
            <button className="button button--quiet navigation-launcher" type="button" aria-haspopup="dialog" aria-controls="main-navigation" onClick={() => setNavigationOpenRequest((value) => value + 1)}>주 메뉴</button>
            {homeView === "work" ? <div className="chat-location"><h2 title={selectedRun?.summary}>{selectedRun ? runDisplayName(selectedRun.summary, selectedRun.id) : "새 대화"}</h2>
              <ProjectNavigation projectName={selectedProjectName} onSelect={() => openProjectSelection()} /></div> : null}
          </div>
          <div className="topbar__actions">
            {homeView === "work" ? <button ref={workDetailsTrigger} className="button button--secondary chat-work-toggle" type="button"
              aria-expanded={workDetailsOpen} aria-controls="chat-work-details" onClick={() => {
                if (!workDetailsOpen) setWorkbenchView("tasks");
                setWorkDetailsOpen(current => !current);
              }}>
              <ListChecks aria-hidden="true" size={15} />{workDetailsOpen ? "대화로 돌아가기" : "작업 보기"}</button> : null}
            <div className="notification-center" data-open={notificationPanelOpen}>
              <button
                ref={notificationTriggerRef}
                className="icon-button notification-center__trigger"
                type="button"
                title={notificationRefreshProblem ? "알림 상태 확인 필요 · 진단 보기" : "작업 알림"}
                data-refresh-problem={notificationRefreshProblem}
                aria-label={`작업 알림${notifications.unread_count ? ` ${notifications.unread_count}개 읽지 않음` : ""}${notificationRefreshProblem ? " · 알림 상태 확인 필요" : ""}`}
                aria-expanded={notificationPanelOpen}
                onClick={() => {
                  if (!notificationPanelOpen) updateNotificationPanelPlacement();
                  setNotificationPanelOpen((current) => !current);
                }}
              >
                {notificationRefreshProblem ? <AlertCircle aria-hidden="true" size={17} /> : <Bell aria-hidden="true" size={17} />}
                {notifications.unread_count ? <span className="notification-center__badge">{Math.min(99, notifications.unread_count)}</span> : null}
              </button>
              {notificationPanelOpen && notificationPanelPlacement ? createPortal(
                <div className="notification-overlay-root">
                  <NotificationPanel
                    panelRef={notificationPanelRef}
                    placement={notificationPanelPlacement}
                    snapshot={notifications}
                    actionError={notificationActionError}
                    onClose={() => closeNotificationPanel(true)}
                    refreshBusy={notificationRefreshBusy}
                    onRefresh={(scopeKey) => {
                      if (notificationRefreshPending.current) return;
                      notificationRefreshPending.current = true;
                      setNotificationRefreshBusy(true);
                      setNotificationActionError("");
                      void window.orchestrator.listNotifications(scopeKey)
                        .then(setNotifications)
                        .catch(() => setNotificationActionError("해당 알림 조회를 다시 확인하지 못했습니다. 현재 진단을 확인하세요."))
                        .finally(() => { notificationRefreshPending.current = false; setNotificationRefreshBusy(false); });
                    }}
                    onOpen={(item) => void openWorkNotification(item)}
                    onMarkAll={() => {
                      setNotificationActionError("");
                      void window.orchestrator.markAllNotificationsRead()
                        .then((snapshot) => {
                          setNotifications(snapshot);
                          setNotificationActionError("");
                        })
                        .catch(() => setNotificationActionError("읽음 상태를 저장하지 못했습니다. 다시 시도해 주세요."));
                    }}
                    onDismissItem={async (item) => {
                      setNotificationActionError("");
                      try {
                        const snapshot = await window.orchestrator.dismissNotification(item.event_id);
                        setNotifications(snapshot);
                        return true;
                      } catch {
                        setNotificationActionError("알림을 지우지 못했습니다. 다시 시도해 주세요.");
                        return false;
                      }
                    }}
                    onDismissMany={async (scope) => {
                      setNotificationActionError("");
                      try {
                        const snapshot = await window.orchestrator.dismissNotifications(scope);
                        setNotifications(snapshot);
                        return true;
                      } catch {
                        setNotificationActionError("알림을 지우지 못했습니다. 다시 시도해 주세요.");
                        return false;
                      }
                    }}
                    onSettings={(settings) => {
                      setNotificationActionError("");
                      void window.orchestrator.updateNotificationSettings(settings)
                        .then((snapshot) => {
                          setNotifications(snapshot);
                          setNotificationActionError("");
                        })
                        .catch(() => setNotificationActionError("알림 설정을 저장하지 못했습니다. 다시 시도해 주세요."));
                    }}
                  />
                </div>,
                document.body,
              ) : null}
            </div>
            <button className="icon-button icon-button--refresh" type="button" title="새로고침" aria-label="프로젝트와 작업 그룹 새로고침" disabled={loading} onClick={() => { void loadProjects(); void loadRuns({ projectName: selectedProjectName, scope: archiveScopeRef.current }); if (selectedProjectName && selectedRunId) void loadRunDetail(selectedProjectName, selectedRunId); }}>
              <RefreshCw aria-hidden="true" size={17} />
            </button>
          </div>
        </header>

            {attentionOpen ? <AttentionInbox snapshot={attentionSnapshot} loading={attentionLoading} error={attentionError}
              onRefresh={() => void loadAttentionItems()} onOpen={openAttentionItem} onClose={closeAttentionInbox} /> : null}
        {error && (backendRecoveryNeeded || !(homeView === "work" && workbenchView === "planning" && !selectedRun && error === planningStartError)) ? (
          <ApplicationErrorBanner message={error}>
            {backendRecoveryNeeded ? <button type="button" disabled={busyAction === "system.restartBackend"} onClick={() => void restartBackend()}>{busyAction === "system.restartBackend" ? "재시작 중…" : "실행 엔진 재시작"}</button> : null}
          </ApplicationErrorBanner>
        ) : null}
        {!backendChecked && !error ? <div className="notice-banner" role="status">실행 엔진 연결을 확인하고 있습니다. 확인 전에는 작업 상태를 판단할 수 없습니다.</div> : null}
        {notice ? <div className="notice-banner" role="status"><CheckCircle2 aria-hidden="true" size={16} /><span>{notice}</span>{runListRefreshRetry?.projectName === selectedProjectName ? <button className="button button--quiet" type="button" disabled={loading} onClick={() => void loadRuns(runListRefreshRetry)}>{loading ? "확인 중…" : "목록 다시 확인"}</button> : null}</div> : null}

        <div className="work-centered-layout" data-home={homeView} data-details-open={workDetailsOpen}
          style={{ "--planning-pane-width": `${visiblePlanningPaneWidth}px` } as CSSProperties}>

          <div className="work-centered-content" id="chat-work-details" role={homeView === "work" ? "complementary" : undefined}
            aria-label={homeView === "work" ? "작업 상세" : undefined} onKeyDown={event => {
              if (homeView === "work" && event.key === "Escape" && !event.defaultPrevented
                && !(event.target as Element).closest("dialog:modal, details[data-dismiss-on-outside][open]")) {
                setWorkDetailsOpen(false); workDetailsTrigger.current?.focus();
              }
            }}>
            {homeView === "work" ? <header className="chat-details-heading" data-results={compactDetails}>
              <strong>{compactDetails ? <><PanelRight size={16} aria-hidden="true" /><span>{selectedProjectName}</span><span className="chat-details-heading__separator">/</span></> : null}{selectedRun?.archive ? "보관 기록" : "작업 상세"}</strong>
              <div className="chat-details-heading__actions">
              {compactDetails ? <ProjectToolsMenu compact projectOnly onOpenGroups={() => setWorkListOpen(true)} onMainChanges={() => setMainChangesOpen(true)}
                projectName={selectedProjectName} settingsDisabled={!selectedProject || isBusy} removeDisabled={Boolean(removeProjectReason)} removeReason={removeProjectReason}
                onAddProject={() => setProjectDialogOpen(true)} onOpenAuth={openCodexAuth} onOpenSettings={() => setProjectSettingsOpen(true)} onRemoveProject={() => void removeProject()} /> : null}
              <button ref={workDetailsClose} className="icon-button" type="button" aria-label="작업 상세 닫기" onClick={() => {
                setWorkDetailsOpen(false); workDetailsTrigger.current?.focus();
              }}><X size={17} aria-hidden="true" /></button></div></header> : null}
            <div className="work-overview-surface" hidden={homeView !== "overview"}>
              <ChatHome projects={projects} choosing={choosingNewWorkProject} onNew={startProjectWork}
                connection={loading ? "connecting" : !backendChecked || !projectsLoaded ? "unavailable" : undefined}
                onRetry={() => void loadProjects()}
                onCancel={() => setChoosingNewWorkProject(false)} onConnect={openCodexAuth}
                onRegister={() => { setProjectRegistrationIntent("existing"); setProjectDialogOpen(true); }}
                onCreate={() => { setProjectRegistrationIntent("new"); setProjectDialogOpen(true); }} />
            </div>
            <div className="work-overview-surface" hidden={homeView !== "history"}>
              <WorkOverview projects={projects} active={activeGroups} history visible={homeView === "history"}
                onSelectProject={selectProject} onNewWork={startProjectWork} onOpen={openGlobalGroup} onRegister={() => setProjectDialogOpen(true)} />
            </div>
            <section className="work-settings" hidden={homeView !== "settings"} aria-label="환경 설정">
              <h2>설정</h2>
              <div className="work-settings__actions">
                <section className="work-settings__card"><h3>AI 연결</h3>
                <button className="button button--secondary" onClick={openCodexAuth}>AI 연결 관리</button>
                <ul>{providerStatuses.map((status) => <li key={status.id}>{providerDisplayName(status.id)} · {status.auth_label || (status.available ? "사용 가능" : "연결 확인 필요")}</li>)}</ul>
                <p>Codex·Claude CLI·NVIDIA 연결을 함께 관리합니다. 연결 후 작업별 실행 모델을 선택하세요.</p>
                <details><summary>NVIDIA 코딩 설치·선택 안내</summary>
                  <p>OpenCode CLI 설치 후 AI 연결 관리 → NVIDIA에서 키를 저장하세요. 실행 전 작업 상세의 실행 AI · 모델에서 NVIDIA를 선택할 수 있습니다.</p>
                  <p>설치: <code>npm install -g opencode-ai@1.19.3</code></p>
                  <p>기본 AI 배정은 유지됩니다. NVIDIA는 직접 선택한 작업에 사용하며, 체험 API는 이용 조건을 확인하고 공개 예제로 먼저 시험하세요.</p>
                </details></section>
                <McpConnectionGuide visible={homeView === "settings"} />
                <section className="work-settings__card"><h3>프로젝트 환경</h3><p>{selectedProjectName || "프로젝트를 먼저 선택하세요"}</p>
                <button className="button button--secondary" disabled={!selectedProject || isBusy} onClick={() => setProjectSettingsOpen(true)}>프로젝트 설정</button>
                <button className="button button--secondary" onClick={() => setProjectDialogOpen(true)}>프로젝트 등록</button>
                </section>
                <section className="work-settings__card"><h3>프로젝트 관리</h3><p>{selectedProjectName || "프로젝트를 먼저 선택하세요"}</p>
                <button className="button button--secondary" disabled={!selectedProjectName || isBusy} onClick={() => setMainChangesOpen(true)}>Main 변경·동기화</button>
                <button className="button button--danger" disabled={Boolean(removeProjectReason)} title={removeProjectReason || "프로젝트 파일은 유지합니다."} onClick={() => void removeProject()}>프로젝트 삭제 · 등록 해제</button>
                {removeProjectReason ? <p role="status">{removeProjectReason}</p> : null}
                <small>프로젝트 파일은 삭제하지 않습니다.</small></section>
              </div>
            </section>
        <WorkDialog title="작업 목록" titleId="work-list-title" className="work-list-dialog" open={homeView === "work" && workListOpen}
          suspendPlanning onClose={() => setWorkListOpen(false)}>
          {error ? <ApplicationErrorBanner message={error}>
            {backendRecoveryNeeded ? <button type="button" disabled={busyAction === "system.restartBackend"} onClick={() => void restartBackend()}>{busyAction === "system.restartBackend" ? "재시작 중…" : "실행 엔진 재시작"}</button> : null}
          </ApplicationErrorBanner> : null}
          {notice ? <p className="group-filter-context" role="status">{notice}</p> : null}
          <WorkGroupPane
            visible={homeView === "work" && workListOpen}
            runs={filteredRuns}
            mode={groupListMode}
            globalGroups={globalGroups}
            globalCount={confirmedGlobalCount}
            globalErrorCount={activeGroups.errors.length}
            globalErrors={activeGroups.errors}
            globalError={activeGroupsError}
            globalLoading={activeGroupsLoading}
            globalSearch={globalSearch}
            selectedProjectName={selectedProjectName}
            scope={archiveScope}
            selectedRunId={selectedRunId}
            search={search}
            statusFilter={runStatusFilter}
            statusCounts={searchedRunCounts}
            totalRunCount={runSummaries.length}
            loading={loading}
            deletingRunId={deletingRunId}
            archivingRunId={archivingRunId}
            onScopeChange={setArchiveScope}
            onModeChange={setGroupListMode}
            onGlobalSearch={setGlobalSearch}
            onRefreshGlobal={() => void loadActiveGroups()}
            onRefreshProject={() => void loadRuns({ projectName: selectedProjectName, scope: archiveScope, selectFirst: false })}
            onSelectGlobal={openGlobalGroup}
            onSearch={setSearch}
            onStatusFilter={(filter) => setRunStatusFilters((current) => ({ ...current, [selectedProjectName]: filter }))}
            onClearConditions={() => { setSearch(""); setRunStatusFilters((current) => ({ ...current, [selectedProjectName]: "all" })); }}
            onSelectRun={(runId) => { setHomeView("work"); pendingAttentionRef.current = undefined; setSideInspectorOpen(false); setSelectedRunId(runId); setSelectedRecoveryTaskId(""); setResultFocusTaskId(""); setWorkbenchView(selectedRunView(archiveScope)); setWorkListOpen(false); }}
            onDeleteRun={(runId) => void deleteRun(runId)}
            onArchiveRun={(runId) => void archiveRun(runId)}
            onNewPlanning={() => {
              if (!selectedProjectName) return;
              setHomeView("work");
              setSideInspectorOpen(false);
              setArchiveScope("active"); setSelectedRunId("");
              restorePlanningDraft(selectedProjectName, selectedProject?.planning_source_dir || "",
                projectCapabilities?.repository_maturity.kind === "docs_only" ? "new_project" : projectCapabilities?.repository_maturity.kind === "existing_code" ? "existing_structure" : "",
                providerProfileKey(planningProfiles.find((profile) => profile.is_default && profile.model === profile.configured_model) || planningProfiles[0]));
              setWorkbenchView("planning"); setWorkListOpen(false);
            }}
          />
        </WorkDialog>
        <div hidden={homeView !== "work"} ref={workspaceGridRef} className="workspace-grid" data-preparation={preparationView} data-attention-project={selectedRunProjectName} data-attention-run={selectedRun?.id || ""} data-has-run={Boolean(selectedRun)} data-workbench-view={workbenchView} data-layout={workbenchLayout} data-inspector-open={sideInspectorOpen} style={workspaceStyle}>
          <header className="work-project-heading" hidden={compactDetails}><h2>{selectedProjectName || "프로젝트를 선택하세요"}</h2>
            <div className="work-project-heading__actions">
              <button className="button button--secondary" type="button" aria-haspopup="dialog" aria-expanded={workListOpen} onClick={() => setWorkListOpen(true)}><ListChecks aria-hidden="true" size={15} />작업 그룹 전환</button>
              <ProjectToolsMenu projectOnly onMainChanges={() => setMainChangesOpen(true)} projectName={selectedProjectName} settingsDisabled={!selectedProject || isBusy}
                removeDisabled={Boolean(removeProjectReason)} removeReason={removeProjectReason} onAddProject={() => setProjectDialogOpen(true)}
                onOpenAuth={openCodexAuth} onOpenSettings={() => setProjectSettingsOpen(true)} onRemoveProject={() => void removeProject()} />
            </div>
          </header>
          <section className="task-workbench" aria-label="작업 영역">
            <div className="task-workbench__navigation">
              <WorkDetailsNavigation view={workbenchView} run={selectedRun} onChange={(view) => {
                if (view === workbenchView || view === "tasks" && isWorkOverview) return;
                const node = taskWorkbenchBodyRef.current;
                if (isWorkOverview && node) {
                  const key = `${taskViewContext}\0${currentScrollView}`;
                  taskScrollPositionsRef.current[key] = node.scrollTop;
                  taskScrollRestoreRef.current = { key, top: node.scrollTop };
                }
                if (view === "results") setResultFocusTaskId("");
                setWorkbenchView(view);
              }} />
              <div className="task-workbench__status" ref={setWorkStatusTarget} aria-label="작업 실행 상태">
                <span className="task-workbench__status-fallback" role="status">{selectedRun ? stageLabels[selectedRun.stage] || selectedRun.stage : "작업을 선택하세요"}</span>
                {selectedRun ? <RunLockNotice compact key={taskViewContext} projectName={selectedProjectName} runId={selectedRun.id}
                  active={homeView === "work" && selectedRunProjectName === selectedProjectName && selectedRun.id === selectedRunId && !selectedRun.archive}
                  refreshKey={JSON.stringify([selectedRun.updated_at, selectedRun.execution_control?.lock_state, selectedRun.execution_control?.operation, selectedRun.main_operations])}
                  busy={Boolean(busyAction || executionAction)} activeOnCards={isWorkOverview && executionOnTaskCards(selectedRun)}
                  progressOperation={workDetailsOpen && applySummaryOpen && isWorkOverview && groupOperationsVisible
                    ? workOverviewProgressOperation(selectedRun, operationsSnapshot, selectedProjectName) : ""}
                  onUpdated={(run) => replaceRun(selectedProjectName, run)} onInspect={openApplySummary}
                  onBlocking={(blocking, progress) => setRunLockBlocking((current) => current.context === taskViewContext && current.blocking === blocking && current.progress === progress
                    ? current : { context: taskViewContext, blocking, progress })} /> : null}
              </div>
            </div>
            <div ref={taskWorkbenchBodyRef} className="task-workbench__body" onScroll={(event) => {
              if (!isWorkOverview) return;
              const key = `${taskViewContext}\0${currentScrollView}`;
              if (taskScrollRestoreRef.current?.key === key) return;
              taskScrollPositionsRef.current[key] = event.currentTarget.scrollTop;
              if (workbenchLayout !== "wide" && currentScrollView !== "list") {
                inspectorScrollMemory.current[inspectorContextKey] = { top: event.currentTarget.scrollTop, left: event.currentTarget.scrollLeft };
              }
            }}>
              {workbenchView === "planning" ? <>
                {groupNextAction}{groupUsage}
              </> : null}
              <div hidden={workbenchView !== "planning"}>
                <PlanningWorkbench
                chatFirst
                taskSettings={chatTaskSettings}
                scrollMemory={chatScrollMemory}
                executionPhase={selectedExecutionRequest?.chatPhase}
                workActivity={selectedRun ? <ChatWorkActivity run={selectedRun} action={nextAction}
                  busy={Boolean(busyAction || executionAction)} repairing={repairStartedAt !== undefined}
                  recovering={executionAction === "tasks.repairFromChat" || selectedExecutionRequest?.chatPhase === "verifying"}
                  stopping={selectedExecutionRequest?.chatPhase === "stopping"} recoveryElapsed={selectedExecutionElapsed}
                  recoveryDisabled={planDirty || nextExecutionProfileDirty}
                  recovery={chatRecoveryContext.key === recoveryContextKey ? chatRecoveryContext.recovery : undefined}
                  onRefreshRecovery={() => setRecoveryQueryRevision(value => value + 1)}
                  onCancelRecovery={selectedExecutionRequest?.chatPhase === "stopping" && selectedExecutionRequest.chatRequestId && selectedExecutionRequest.chatIntent !== "stop" ? () => {
                    const projectName = selectedProjectName, runId = selectedRunId;
                    void window.orchestrator.request<{ phase: string }>("runs.cancelChatControl", {
                      projectName, runId, requestId: selectedExecutionRequest.chatRequestId,
                    }).then(result => { if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId))
                      setNotice(result.phase === "cancelled" ? "복구 예약을 취소했습니다. 중지 요청은 유지됩니다."
                        : ["repairing", "verifying"].includes(result.phase) ? "이미 복구가 시작됐습니다. 작업 중지를 사용해 주세요."
                          : "요청이 이미 종료됐습니다. 현재 작업 상태를 확인해 주세요."); })
                      .catch(error => { if (runContextMatches(selectedContextRef.current.projectName, selectedContextRef.current.runId, projectName, runId)) setError(errorMessage(error)); });
                  } : undefined}
                  onAction={invokeNextAction} onDiscuss={openTaskPlanning}
                  onRecover={(taskId) => void sendPlanningMessage("고쳐서 계속해줘", taskId)}
                  onTasks={() => { setWorkbenchView("tasks"); setWorkDetailsOpen(true); }} /> : null}
                bodyVisible={homeView === "work" && workbenchView === "planning"}
                chatTarget={planningChatTarget}
                usageSnapshot={currentUsage?.snapshot}
                usageError={currentUsage?.error}
                taskQuestion={repairTask}
                repairStartedAt={repairStartedAt}
                contextPanel={selectedRun && (repairTask || selectedRun.stage === "executing" || selectedRun.direction_change_requests?.length || directionDraft?.pending || directionDraft?.error) ? <>{selectedRun && repairTask?.status === "failed" && selectedRun.tasks.some((task) => task.id === repairTask.id) ? <TaskRepairPanel
                  key={repairKey} projectName={selectedProjectName} run={selectedRun} task={repairTask}
                  draftRevision={planningChatDraft.editRevision}
                  onPrepared={(_message, _revision, diagnostic) => {
                    if (failedQuestionTargetRef.current !== failedQuestionKey) return;
                    failedQuestionDrafts.current.cacheDiagnostic(selectedProjectName, selectedRun.id, failedQuestionKey, diagnostic);
                  }}
                /> : null}{selectedRun && (selectedRun.stage === "executing" || selectedRun.direction_change_requests?.length || directionDraft?.pending || directionDraft?.error) ? <DirectionChangePanel
                  projectName={selectedProjectName} run={selectedRun} drafts={directionChangeDrafts}
                  previewElsewhere={selectedRun.repository_intent !== "new_project" || selectedRun.greenfield_phase === "feature_plan_ready"}
                  onAccepted={() => void loadRunDetail(selectedProjectName, selectedRun.id)}
                  onOpenPreview={() => setPlanningPreviewTarget({ projectName: selectedProjectName, runId: selectedRun.id })}
                  onDiscuss={() => setPlanningChatOpenRequest((request) => request + 1)} /> : null}</> : null}
                key={`planning:${selectedProjectName}:${selectedRun?.id || "new"}`}
                project={selectedProject}
                run={selectedRun}
                path={planningPath}
                mode={planningMode}
                request={planningRequest}
                profiles={planningProfiles}
                providerStatuses={providerStatuses}
                capabilities={projectCapabilities}
                repositoryIntent={repositoryIntent}
                selectedProfileKey={planningProfileKey}
                reasoning={planningReasoning}
                reasoningOptions={currentReasoningOptions}
                message={planningMessage}
                pendingMessage={
                  pendingPlanningMessage?.runId === selectedRun?.id && (!pendingPlanningMessage?.projectName || pendingPlanningMessage?.projectName === selectedProjectName)
                    ? pendingPlanningMessage
                    : undefined
                }
                index={planningIndex}
                indexElapsed={planningIndexElapsed}
                planningElapsed={ownsPlanning && planningOwner ? Math.max(0, Math.floor((Date.now() - planningOwner.startedAt) / 1000)) : busyAction ? planningStartElapsed : 0}
                preparationMessage={planningPreparationMessage}
                startError={planningStartError}
                preparing={busyAction === "runs.start" && busyProjectRef.current === selectedProjectName}
                busyAction={busyAction}
                messageQueue={planningRequests.messageQueue}
                queueSubmitting={queueSubmitting}
                onQueue={() => void queuePlanningMessage(repairTask?.id)}
                onChangeQueued={changeQueuedMessage}
                onRestoreQueued={restoreQueuedMessage}
                planningRequestError={!error && ownsPlanning && planningOwner?.phase === "confirmation_required" ? `중단 여부 확인 필요 · ${planningOwner.error}`
                  : !error && latestPlanningReceipt?.phase === "failed" ? latestPlanningReceipt.error : undefined}
                interruptLabel={ownsPlanning && ["chat", "archived_chat"].includes(planningOwner?.kind || "") ? "답변 중단" : "기획 중단"}
                planDirty={planDirty}
                draftConflict={draftConflict}
                interruptible={Boolean(ownsPlanning && planningOwner) || Boolean(selectedRunId) && (
                  busyAction === "runs.start" ||
                  busyAction === "runs.sendPlanningMessage" ||
                  busyAction === "runs.applyPlanningConversation" ||
                  selectedRun?.active_step === "planning"
                )}
                effortMode={planningEffortMode}
                profileManual={planningProfileManual}
                onEffortModeChange={(effortMode) => { setPlanningEffortMode(effortMode); updatePlanningDraft({ effortMode }); }}
                onPathChange={(path) => { setPlanningPath(path); updatePlanningDraft({ path }); }}
                onModeChange={(mode) => { setPlanningMode(mode); updatePlanningDraft({ mode }); }}
                onRequestChange={(request) => { setPlanningRequest(request); updatePlanningDraft({ request }); }}
                onRepositoryIntentChange={(repositoryIntent) => { setRepositoryIntent(repositoryIntent); updatePlanningDraft({ repositoryIntent }); }}
                onChoosePath={() => void choosePath("planningSource")}
                onSavePath={() => void savePlanningSource()}
                onRefreshIndex={() => void refreshPlanningIndex()}
                onRefreshProviders={() => void refreshProviderStatuses()}
                onOpenCodexAuth={openCodexAuth}
                onOpenPlanningSettings={() => { setWorkbenchView("planning"); setWorkDetailsOpen(true); }}
                onProfileChange={(profileKey) => {
                  setPlanningProfileKey(profileKey); setPlanningReasoning(""); setPlanningProfileManual(true);
                  editedPlanningProfileContext.current = `${selectedProjectName}\0${selectedRunId}`;
                  updatePlanningDraft({ profileKey, reasoning: "", profileManual: true });
                }}
                onReasoningChange={(reasoning) => {
                  setPlanningReasoning(reasoning); setPlanningProfileManual(true);
                  editedPlanningProfileContext.current = `${selectedProjectName}\0${selectedRunId}`;
                  updatePlanningDraft({ profileKey: planningProfileKey, reasoning, profileManual: true });
                }}
                onMessageChange={(message) => {
                  setPlanningMessage(message);
                  if (!message.trim()) {
                    failedQuestionTargetRef.current = ""; setRepairTarget(undefined);
                    failedQuestionDrafts.current.release(selectedProjectName, selectedRunId);
                  }
                }}
                onStart={() => void startPlanning()}
                onRunPreparedRevision={() => void runPreparedRevisionPlanning()}
                onSend={() => void sendPlanningMessage(undefined, repairTask?.id)}
                onApply={() => {
                  if (selectedRun && ["verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(selectedRun.stage)) { setWorkbenchView("results"); setWorkDetailsOpen(true); }
                  else void applyPlanningConversation();
                }}
                onConfirmTechStack={(optionId, expectedRevision) => void runGreenfieldAction("confirm", "", optionId, expectedRevision)}
                onAnswerTechnology={(answer) => void runGreenfieldAction("answer", answer)}
                onRetryGreenfield={() => void runGreenfieldAction("plan")}
                onStartGreenfield={() => void runGreenfieldAction("start")}
                onConfigureBootstrapInstructions={(create, expectedRevision, expectedDigest) => void configureBootstrapInstructions(create, expectedRevision, expectedDigest)}
                onGenerateFeaturePlan={() => void generateFeaturePlan()}
                onInterrupt={() => void interruptPlanning()}
                />
              </div>
              {workbenchView === "planning" ? null : workbenchView === "results" ? (
                selectedRun ? <ResultReview
                  key={resultDraftKey}
                  projectName={selectedProjectName}
                  run={selectedRun}
                  focusTaskId={resultFocusTaskId}
                  onDiscuss={() => { setWorkDetailsOpen(false); setPlanningChatOpenRequest((request) => request + 1); }}
                  discussionText={resultRevisionDiscussion(selectedRun.planning_messages)}
                  draft={resultRevisionDrafts[resultDraftKey]}
                  requests={resultRevisionRequests}
                  onDraftChange={(update) => setResultRevisionDrafts((current) => {
                    const next = typeof update === "function" ? update(current[resultDraftKey]) : update;
                    return next && next !== current[resultDraftKey] ? { ...current, [resultDraftKey]: next } : current;
                  })}
                  onNavigate={(runId, view, message) => void openRevisionRun(runId, view, message)}
                  onOpenTask={(taskId) => { setWorkbenchView("tasks"); openLinkedTaskDetail(taskId); }}
                  onOpenOperations={openApplySummary}
                /> : null
              ) : (
                <>
                {groupOperationsVisible && selectedRun ? <WorkDialog inline title={applySummaryTitle(selectedRun)} titleId="operations-workbench-title" context={selectedProjectName}
                  className={selectedRun?.archive ? "archive-record-dialog" : "apply-summary-dialog"}
                  open={homeView === "work" && applySummaryOpen} onClose={closeApplySummary} suspendPlanning>
                <OperationsWorkbench summaryOnly
                statusTarget={workStatusTarget}
                statusVisible={homeView === "work" && applySummaryOpen}
                key={`operations:${selectedProjectName}:${selectedRun?.id || "none"}`}
                run={selectedRun}
                projectName={selectedProjectName}
                recoveryTaskId={selectedRecoveryTaskId}
                deployConfigured={projectCapabilities?.deployment_configured === true}
                operationsSnapshot={operationsSnapshot}
                busyAction={executionAction || busyAction}
                executionElapsed={executionAction ? selectedExecutionElapsed : executionElapsed}
                stopRequestPending={stopRequestExecutionId === selectedRun?.execution_control?.execution_id}
                deleting={deletingProjectName === selectedProjectName && deletingRunId === selectedRun?.id}
                archiving={archivingProjectName === selectedProjectName && archivingRunId === selectedRun?.id}
                checking={applySummaryChecking}
                planDirty={planDirty}
                actionError={applySummaryError}
                onApplySummary={(action) => void performApplySummary(action)}
                onInspectRunLock={() => { window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".run-lock-notice button")?.focus()); }}
                onRefresh={async () => {
                  await loadOperations();
                }}
                onVerify={() => void requestRunAction("runs.verify")}
                onVerifyAndRepair={() => void requestRunAction("runs.verifyAndRepair")}
                onStop={() => void requestExecutionStop()}
                onApprovedAction={(method, extra) => void approvedRunAction(method, extra)}
                onDeleteRun={() => {
                  if (selectedRun) void deleteRun(selectedRun.id);
                }}
                onArchiveRun={() => {
                  if (selectedRun) void archiveRun(selectedRun.id);
                }}
                onRetryArchiveCleanup={() => void retryArchiveCleanup()}
                onOpenArchiveFolder={async () => {
                  if (!selectedRun) return;
                  try {
                    await window.orchestrator.openArchiveFolder(selectedProjectName, selectedRun.id);
                  } catch (requestError) {
                    setError(errorMessage(requestError));
                  }
                }}
                />
                </WorkDialog> : null}
                <div className="task-workbench__task-view">
                  <div className="task-workbench__task-pane" data-view={taskContentView}>
                    <div className="task-workbench__list-pane">
                      <TaskWorkbench cardsOnly
                        key={`tasks:${selectedProjectName}:${selectedRun?.id || "none"}`}
                        run={selectedRun ? { ...selectedRun, tasks: selectedRun.stage === "planned" ? taskDrafts : selectedRun.tasks } : undefined}
                        analysisTasks={selectedRun?.tasks}
                        selectedTaskId={selectedTaskId}
                        selectedTaskIds={selectedTaskIds}
                        planDirty={planDirty}
                        nextAction={groupOperationsVisible ? <></> : groupNextAction}
                        preparationAction={nextAction}
                        preparationBlocked={groupOperationsVisible || Boolean(runLockBlocking.context === taskViewContext && runLockBlocking.blocking)
                          || Boolean(selectedWaiting && !postponedWaiting[waitingKey])}
                        onPreparationAction={invokeNextAction}
                        onDiscuss={() => { setWorkDetailsOpen(false); setPlanningChatOpenRequest((request) => request + 1); }}
                        usageSnapshot={currentUsage?.snapshot}
                        usageError={currentUsage?.error}
                        effortControls={selectedRun ? <EffortModePanel
                          projectName={selectedProjectName} run={selectedRun} planDirty={planDirty}
                          draftMode={effortModeDraftsRef.current[`${selectedProjectName}\0${selectedRun.id}`]}
                          onDraftMode={(mode) => { effortModeDraftsRef.current[`${selectedProjectName}\0${selectedRun.id}`] = mode; }}
                          onUpdated={(updated) => replaceRun(selectedProjectName, updated)}
                        /> : null}
                        draftConflict={draftConflict}
                        draftErrorCount={draftErrors.length}
                        busyAction={busyAction}
                        executionAction={executionAction}
                        planningTaskIds={planningTaskIds}
                        profileOptions={taskProfileOptions}
                        profiles={selectedRun?.stage === "planned" ? taskProfiles : {}}
                        onSelectTask={openTaskDetail}
                        onOpenTaskLog={openTaskLog}
                        onRepairTask={openTaskPlanning}
                        onToggleTask={(taskId) => setSelectedTaskIds((current) => current.includes(taskId) ? current.filter((id) => id !== taskId) : [...current, taskId])}
                        onProfileChange={(taskId, selection) => setTaskProfiles((current) => ({ ...current, [taskId]: selection }))}
                        onRunAction={requestRunAction}
                        onStop={(task) => void requestExecutionStop(task)}
                        onExclude={() => void approvedRunAction("runs.excludeTasks", { taskIds: selectedTaskIds })}
                        onAddTask={addTaskDraft}
                        onResetPlan={resetPlanDraft}
                        onSavePlan={() => void savePlan(false)}
                        onOpenConflictRecovery={(taskId) => { setSelectedRecoveryTaskId(taskId); setWorkbenchView("operations"); }}
                        onRecovery={() => void openRunRecovery()}
                        onBack={() => { setHomeView("overview"); setSideInspectorOpen(false); }}
                      />
                    </div>
                  </div>
                </div>

                </>
              )}
            </div>
          </section>

          {selectedRun && selectedTask ? <WorkDialog
            key={`task-dialog:${selectedProjectName}:${selectedRun.id}:${selectedTask.id}:${taskDialogOpen}`}
            title={selectedRun.tasks.some((task) => task.id === selectedTask.id)
              ? `${selectedRun.tasks.findIndex((task) => task.id === selectedTask.id) + 1}. ${selectedTask.title || "제목 없는 작업"}` : "새 작업 추가"}
            titleId="task-dialog-title" context={selectedProjectName}
            open={taskDialogOpen && previewSurface !== "dialog" && inspectorTab === "detail" && !taskDetailUsesChat(selectedRun, selectedTask)} onClose={closeInspector}>
            <TaskStatusOverview task={selectedRun.tasks.find((task) => task.id === selectedTask.id) || selectedTask} run={selectedRun}
              planning={planningTaskIds.includes(selectedTask.id)}
              busy={Boolean(busyAction || executionAction || nextExecutionProfileDirty)} planDirty={planDirty} requestError={error}
              onPlanning={() => {
                openTaskPlanning(selectedTask.id);
              }}
              onResult={() => { setSideInspectorOpen(false); setResultFocusTaskId(selectedTask.id); setWorkbenchView("results"); }}
              onStop={() => void requestExecutionStop(selectedTask)} onRun={(method) => void requestRunAction(method)}
              onRefresh={() => void loadRunDetail(selectedProjectName, selectedRun.id)} onOpenTask={openLinkedTaskDetail} />
            <div className="work-task-actions">
              {selectedTask.status === "waiting" && pendingTaskActionIsAllowed(runExecutionPresentation(selectedRun, executionAction).primaryMethod, selectedRun.stage) ? <button className="button button--primary" type="button" disabled={Boolean(busyAction || executionAction || planDirty)} onClick={() => void requestRunAction("tasks.complete", selectedTask.id)}>이 결과로 완료 처리</button> : null}
            </div>
            <TaskDetailSummary task={selectedRun.tasks.find((task) => task.id === selectedTask.id) || selectedTask}
              usage={currentUsage?.snapshot} usageError={currentUsage?.error}
              showAi={selectedTask.status !== "pending"} />
            {selectedRun.stage === "planned" && selectedTask.status === "pending" ?
            <>
              <TaskRow profileOnly task={selectedTask} sequence={selectedRun.tasks.findIndex((task) => task.id === selectedTask.id) + 1}
              selected checked={selectedTaskIds.includes(selectedTask.id)} busy={Boolean(busyAction || executionAction)}
              planConfirmed={selectedRun.stage !== "planned" || planIsApproved(selectedRun) && !planDirty}
              taskActionsAllowed={pendingTaskActionIsAllowed(runExecutionPresentation(selectedRun, executionAction).primaryMethod, selectedRun.stage)}
              taskRetryAllowed={taskRetryIsAllowed(runExecutionPresentation(selectedRun, executionAction).primaryMethod, selectedRun.failed_step)}
              executionControl={selectedRun.execution_control} profileEditable={selectedRun.stage === "planned"}
              profileEditorOpen options={taskProfileOptions[selectedTask.id] || []}
              profile={taskProfiles[selectedTask.id] || { agentId: selectedTask.agent_id, model: selectedTask.model, reasoningEffort: selectedTask.reasoning_effort }}
              onSelect={() => {}} onToggle={() => setSelectedTaskIds((current) => current.includes(selectedTask.id) ? current.filter((id) => id !== selectedTask.id) : [...current, selectedTask.id])}
              onToggleProfileEditor={() => {}} onProfileChange={(selection) => setTaskProfiles((current) => ({ ...current, [selectedTask.id]: selection }))}
              onAction={(method) => void requestRunAction(method, selectedTask.id)} onStop={() => void requestExecutionStop(selectedTask)}
              onOpenLog={() => setInspectorTab("log")} onRepair={() => openTaskPlanning(selectedTask.id)} />
            <details key={`direct:${selectedProjectName}:${selectedRun.id}:${selectedTask.id}`} id="task-dialog-direct" className="work-task-controls"
              open={!selectedRun.tasks.some((task) => task.id === selectedTask.id) || undefined}><summary>작업 내용 편집</summary>
            {selectedRun.stage === "planned" || planDirty ? <TaskPlanEditor task={selectedTask}
              tasks={taskDrafts}
              input={planDraft?.inputs[selectedTask.id] || taskEditorInput(selectedTask)}
              validationErrors={untouchedSelectedTask && advancedEditorRequest.key !== selectedTaskDraftKey
                ? [] : draftErrors.filter((draftError) => draftError.taskId === selectedTask.id)}
              revealAdvancedRequest={advancedEditorRequest.key === `${selectedProjectName}\0${selectedRun.id}\0${selectedTask.id}` ? advancedEditorRequest.revision : 0}
              revealField={advancedEditorRequest.key === `${selectedProjectName}\0${selectedRun.id}\0${selectedTask.id}` ? advancedEditorRequest.field : undefined}
              dirty={planDirty} readOnly={Boolean(busyAction) || selectedRun.stage !== "planned"}
              onInput={(input) => setTaskInput(selectedTask.id, input)}
              onUpdate={(changes) => updateTaskDraft(selectedTask.id, changes)} /> : null}
            </details>
            {planDirty ? <div className="work-task-plan-actions"><button className="button button--primary" disabled={Boolean(busyAction || executionAction)} onClick={() => void savePlan(false)}>변경 저장</button><button className="button button--secondary" disabled={Boolean(busyAction || executionAction)} onClick={resetPlanDraft}>변경 취소</button></div> : null}
            </> : null}
            {previewSurface === "task" && planningPreviewTarget ? <PlanningApplyDialog
              embedded projectName={selectedProjectName} runId={selectedRun.id} planDirty={planDirty}
              onTaskEditStart={() => beginTaskPlanning(planningPreviewTarget)}
              continueTaskId={planningPreviewTarget.taskId}
              onContinue={(taskId, approved) => { setPlanningPreviewTarget(undefined); void requestRunAction("tasks.retry", taskId, true, approved); }}
              context={{ projectName: selectedProjectName, run: selectedRun }}
              onApplied={(updated) => replaceRun(selectedProjectName, updated)}
              onRetry={(taskId) => { setPlanningPreviewTarget(undefined); void requestRunAction("tasks.retry", taskId); }}
              onClose={() => setPlanningPreviewTarget(undefined)} /> : null}
          </WorkDialog> : null}
          {selectedRun && selectedTask ? <WorkDialog title={`${selectedTask.title || "선택 작업"} · 로그`} context={selectedProjectName}
            open={taskDialogOpen && previewSurface !== "dialog" && inspectorTab !== "detail"}
            onClose={() => { if (taskDetailUsesChat(selectedRun, selectedTask)) closeInspector(); else changeInspectorTab("detail"); }}>
            <Inspector recordsOnly
            key={`inspector:${selectedProjectName}:${selectedRun?.id || "none"}:${selectedTask?.id || "none"}`}
            panelId="side-inspector" visible={sideInspectorOpen} compact
            scrollKey={JSON.stringify([selectedProjectName, selectedRunId, selectedTaskId, inspectorTab])} scrollMemory={inspectorScrollMemory}
            logView={inspectorLogView} onLogViewChange={changeInspectorLogView} onCollapse={closeInspector}
            run={selectedRun}
            workspace={selectedRun ? runWorkspacePresentation(selectedRun, operationsSnapshot, selectedProjectName) : undefined}
            task={inspectorTab === "log" ? selectedRun?.tasks.find((task) => task.id === selectedTaskId) : selectedTask}
            taskLogState={taskLogState}
            activeTab={inspectorTab}
            profile={selectedTask ? taskProfiles[selectedTask.id] : undefined}
            profileOptions={selectedTask ? taskProfileOptions[selectedTask.id] || [] : []}
            dependencyTasks={taskDrafts}
            onOpenTask={openLinkedTaskDetail}
            onReviewResult={(taskId) => { setSideInspectorOpen(false); setResultFocusTaskId(taskId); setWorkbenchView("results"); }}
            onStop={(task) => void requestExecutionStop(task)}
            onChangeTab={changeInspectorTab}
          />
          </WorkDialog> : null}
        </div>
          </div>
          <PaneResizer label="Planning AI 너비" variant="planning" direction={-1} value={visiblePlanningPaneWidth} min={320} max={planningPaneMax} defaultValue={400} onChange={setPlanningPaneWidth} />
          <PlanningSidebar primary={homeView === "work"} inactive={workDetailsOpen} onTarget={setPlanningChatTarget} openRequest={planningChatOpenRequest}
            status={<ChatWorkStatus run={selectedRun} action={nextAction}
              recovering={executionAction === "tasks.repairFromChat" || selectedExecutionRequest?.chatPhase === "verifying"}
              stopping={selectedExecutionRequest?.chatPhase === "stopping"} />}
            context={selectedProjectName ? `${selectedProjectName}${selectedRun ? ` · ${runDisplayName(selectedRun.summary, selectedRun.id)}` : " · 새 작업"}` : "프로젝트를 선택하세요."} />
        </div>
        </div>
      </main>

      {recoveryOpen && selectedRun?.stage === "failed" ? <RecoveryDialog key={`${selectedProjectName}:${selectedRun.id}`} projectName={selectedProjectName} runId={selectedRun.id} runTitle={runDisplayName(selectedRun.summary, selectedRun.id)} onApplied={(updated) => { replaceRun(selectedProjectName, updated); setNotice("복구안을 적용했습니다. 작업을 확인한 뒤 그룹을 재개하세요."); }} onClose={() => { setRecoveryOpen(false); void loadRunDetail(selectedProjectName, selectedRun.id); }} /> : null}
      {previewSurface === "dialog" && planningPreviewTarget && selectedRun ? <PlanningApplyDialog
        key={`${planningPreviewTarget.projectName}:${planningPreviewTarget.runId}`}
        projectName={planningPreviewTarget.projectName}
        runId={planningPreviewTarget.runId}
        onTaskEditStart={() => beginTaskPlanning(planningPreviewTarget)}
        planDirty={planDirty}
        continueTaskId={planningPreviewTarget.taskId}
        onContinue={(taskId, approved) => { setPlanningPreviewTarget(undefined); void requestRunAction("tasks.retry", taskId, true, approved); }}
        context={{ projectName: selectedProjectName, run: selectedRun }}
        onApplied={(updated, preview) => {
          replaceRun(planningPreviewTarget.projectName, updated);
          if (preview.actual) setNotice(`실제 반영: 추가 ${preview.actual.added} · 수정 ${preview.actual.modified} · 제외 ${preview.actual.excluded} · 유지 ${preview.actual.unchanged}`);
        }}
        onRetry={(taskId) => { setPlanningPreviewTarget(undefined); setWorkbenchView("tasks"); setSelectedTaskId(taskId); void requestRunAction("tasks.retry", taskId); }}
        onClose={() => setPlanningPreviewTarget(undefined)}
      /> : null}
      {mainChangesOpen && selectedProjectName ? <MainChangesDialog
        key={selectedProjectName}
        projectName={selectedProjectName}
        onChanged={(message) => { setError(""); setNotice(message); }}
        onError={(message) => setError(message)}
        onClose={() => setMainChangesOpen(false)}
      /> : null}
      {codexAuthOpen ? <AiConnectionDialog codexState={codexAuthState} onClose={closeCodexAuth} onClaudeChanged={async () => {
        if (!selectedProjectName) return;
        await loadProjectCapabilities(selectedProjectName);
        if (selectedRun) await loadTaskProfiles(selectedProjectName, selectedRun);
      }} onNvidiaChanged={async () => {
        if (!selectedProjectName) return;
        await loadProjectCapabilities(selectedProjectName);
        if (selectedRun) await loadTaskProfiles(selectedProjectName, selectedRun);
      }}><CodexAuthContent
        state={codexAuthState}
        busy={codexAuthBusy}
        message={codexAuthMessage}
        onRefresh={() => void refreshCodexAuth()}
        onStart={(method) => void startCodexAuth(method)}
        onConnectApiKey={connectCodexApiKey}
        onReopen={() => void reopenCodexAuth()}
        onCopyCode={() => void copyCodexDeviceCode()}
        onCancel={() => void cancelCodexAuth()}
        onClose={closeCodexAuth}
      /></AiConnectionDialog> : null}
      <ProjectDialog
        open={projectDialogOpen}
        intent={projectRegistrationIntent}
        draft={projectDraft}
        busy={busyAction === "projects.add"}
        onChange={setProjectDraft}
        onChoosePath={choosePath}
        onClose={() => { setProjectDialogOpen(false); setProjectRegistrationIntent(""); }}
        onSubmit={addProject}
      />
      {projectSettingsOpen && selectedProject ? (
        <ProjectSettingsDialog
          key={selectedProject.name}
          project={selectedProject}
          runId={selectedRun?.id || ""}
          taskId={selectedTaskId}
          onOpenTechStack={openTechStackPlanning}
          onSaved={loadProjects}
          onClose={() => setProjectSettingsOpen(false)}
        />
      ) : null}
    </div>
  );
}

interface NotificationPanelProps {
  panelRef: RefObject<HTMLElement | null>;
  placement: NotificationPanelPosition;
  snapshot: WorkNotificationSnapshot;
  actionError: string;
  refreshBusy: boolean;
  onRefresh(scopeKey: string): void;
  onClose(): void;
  onOpen(item: StoredWorkNotification): void;
  onMarkAll(): void;
  onDismissItem(item: StoredWorkNotification): Promise<boolean>;
  onDismissMany(scope: WorkNotificationDismissScope): Promise<boolean>;
  onSettings(settings: WorkNotificationSettings): void;
}

function NotificationPanel({
  panelRef,
  placement,
  snapshot,
  actionError,
  refreshBusy,
  onRefresh,
  onClose,
  onOpen,
  onMarkAll,
  onDismissItem,
  onDismissMany,
  onSettings,
}: NotificationPanelProps) {
  const cleanupRef = useRef<HTMLDetailsElement>(null);
  const dismissConfirmationRef = useRef<HTMLDialogElement>(null);
  const pendingItemFocusRef = useRef<NotificationDismissFocusRequest | null>(null);
  const [dismissAllConfirmationOpen, setDismissAllConfirmationOpen] = useState(false);
  const [dismissBusy, setDismissBusy] = useState(false);
  const filterSettings: { key: keyof WorkNotificationSettings; label: string }[] = [
    { key: "completion", label: "완료" },
    { key: "failure", label: "실패" },
    { key: "attention_required", label: "확인 필요" },
  ];
  const placementStyle: CSSProperties = {
    left: placement.left,
    width: placement.width,
    maxHeight: placement.maxHeight,
    ...(placement.top === undefined ? { bottom: placement.bottom } : { top: placement.top }),
  };
  const readStateNotice = notificationReadStateNotice(snapshot.read_state_notice);
  const readCount = snapshot.items.filter((item) => Boolean(item.read_at)).length;

  useEffect(() => {
    const dialog = dismissConfirmationRef.current;
    if (!dialog) return;
    if (dismissAllConfirmationOpen && !dialog.open) dialog.showModal();
    if (!dismissAllConfirmationOpen && dialog.open) dialog.close();
  }, [dismissAllConfirmationOpen]);

  const focusDismissedItem = (deletedIndex?: number) => {
    const itemButtons = panelRef.current?.querySelectorAll<HTMLButtonElement>("[data-notification-open]");
    if (itemButtons?.length) {
      itemButtons[Math.min(deletedIndex ?? 0, itemButtons.length - 1)]?.focus();
    } else {
      panelRef.current?.querySelector<HTMLButtonElement>(".notification-panel__close")?.focus();
    }
  };

  const restoreDismissFocus = (deletedIndex?: number) => {
    window.requestAnimationFrame(() => focusDismissedItem(deletedIndex));
  };

  useLayoutEffect(() => {
    const pending = pendingItemFocusRef.current;
    if (!pending || dismissBusy) return;
    const targetIndex = notificationDismissFocusIndex(pending, snapshot.items);
    if (targetIndex === null) return;
    pendingItemFocusRef.current = null;
    focusDismissedItem(Math.max(0, targetIndex));
  }, [dismissBusy, snapshot.items]);

  const dismissOne = async (item: StoredWorkNotification, index: number) => {
    setDismissBusy(true);
    const dismissed = await onDismissItem(item);
    if (dismissed) pendingItemFocusRef.current = { eventId: item.event_id, index };
    setDismissBusy(false);
  };

  const dismissMany = async (scope: WorkNotificationDismissScope, restoreFocusAfter = true) => {
    setDismissBusy(true);
    const dismissed = await onDismissMany(scope);
    setDismissBusy(false);
    if (!dismissed) return false;
    cleanupRef.current?.removeAttribute("open");
    if (restoreFocusAfter) restoreDismissFocus();
    return true;
  };

  const closeDismissConfirmation = () => {
    setDismissAllConfirmationOpen(false);
    window.requestAnimationFrame(() => cleanupRef.current?.querySelector<HTMLElement>("summary")?.focus());
  };

  return (
    <section ref={panelRef} className="notification-panel" style={placementStyle} aria-labelledby="notification-panel-title">
      <header className="notification-panel__header">
        <div className="notification-panel__title">
          <h2 id="notification-panel-title">작업 알림</h2>
          <span>읽지 않음 {snapshot.unread_count}개</span>
        </div>
        <div className="notification-panel__actions">
          <button className="notification-panel__read-all" type="button" disabled={!snapshot.unread_count} onClick={onMarkAll}>모두 읽음</button>
          {snapshot.items.length ? (
            <details ref={cleanupRef} className="notification-panel__cleanup" data-dismiss-on-outside>
              <summary>알림 정리</summary>
              <div className="notification-panel__cleanup-menu">
                {readCount ? (
                  <button type="button" disabled={dismissBusy} onClick={() => void dismissMany("read")}>읽은 알림 {readCount}개 지우기</button>
                ) : <span>지울 읽은 알림이 없습니다.</span>}
                <button
                  type="button"
                  disabled={dismissBusy}
                  onClick={() => {
                    cleanupRef.current?.removeAttribute("open");
                    if (snapshot.unread_count) setDismissAllConfirmationOpen(true);
                    else void dismissMany("all");
                  }}
                >
                  모든 알림 {snapshot.items.length}개 지우기
                </button>
              </div>
            </details>
          ) : null}
          <button className="notification-panel__close" type="button" aria-label="알림함 닫기" onClick={onClose}><X aria-hidden="true" size={15} /></button>
        </div>
      </header>
      <div className="notification-panel__settings" aria-label="알림 설정">
        <label className="notification-panel__master-setting">
          <input
            type="checkbox"
            checked={snapshot.settings.enabled}
            onChange={(event) => onSettings({ ...snapshot.settings, enabled: event.target.checked })}
          />
          데스크톱 알림
        </label>
        <div className="notification-panel__filters">
          {filterSettings.map(({ key, label }) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={snapshot.settings[key]}
                disabled={!snapshot.settings.enabled}
                onChange={(event) => onSettings({ ...snapshot.settings, [key]: event.target.checked })}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
      {actionError ? <p className="notification-panel__save-error" role="alert">{actionError}</p> : null}
      {readStateNotice ? <p className="notification-panel__read-notice" role="status">{readStateNotice}</p> : null}
      {snapshot.delivery_error ? <details className="notification-panel__connection"><summary>알림 기록·전달 상태 확인 필요</summary><p>{snapshot.delivery_error}</p></details> : null}
      <div className="notification-panel__list">
        <NotificationRefreshStatus issues={snapshot.refresh_issues || []} busy={refreshBusy} onRefresh={onRefresh} />
        {snapshot.items.length ? snapshot.items.map((item, index) => {
          const issues = snapshot.refresh_issues?.filter((issue) => issue.event_id === item.event_id) || [];
          const currentIssue = issues.find((issue) => !issue.recovered_at) || issues[issues.length - 1];
          const copy = currentIssue ? notificationRefreshCopy(currentIssue) : workNotificationCopy(item);
          return (
            <div
              className="notification-item"
              data-unread={!item.read_at}
              data-kind={item.kind}
              key={item.event_id}
            >
              <button
                className="notification-item__open"
                data-notification-open
                type="button"
                aria-label={`${copy.title}. ${copy.body}. ${item.project_name || "알림 조회"}`}
                title={`${copy.title} · ${copy.body}`}
                onClick={() => onOpen(item)}
              >
                <span className="notification-item__marker" aria-hidden="true" />
                <span className="notification-item__copy">
                  <strong>{copy.title}{currentIssue?.recovered_at ? " · 복구됨" : ""}</strong>
                  <span>{copy.body}</span>
                  <small>{item.project_name || "알림 조회"} · {formatNotificationTime(item.occurred_at)}</small>
                </span>
              </button>
              <button
                className="notification-item__dismiss"
                type="button"
                title="알림 지우기"
                aria-label={`${copy.title} 알림 지우기`}
                disabled={dismissBusy}
                onClick={() => void dismissOne(item, index)}
              >
                <Trash2 aria-hidden="true" size={14} />
              </button>
            </div>
          );
        }) : <p className="notification-panel__empty">아직 작업 알림이 없습니다.</p>}
      </div>
      <dialog
        ref={dismissConfirmationRef}
        className="modal notification-dismiss-dialog"
        aria-labelledby="notification-dismiss-title"
        onCancel={(event) => {
          event.preventDefault();
          if (!dismissBusy) closeDismissConfirmation();
        }}
      >
        <div className="notification-dismiss-dialog__body">
          <h2 id="notification-dismiss-title">모든 알림을 지울까요?</h2>
          <p>알림함에서 {snapshot.items.length}개를 지웁니다. 작업과 로그는 삭제되지 않습니다.</p>
          <footer>
            <button className="button button--quiet" type="button" disabled={dismissBusy} onClick={closeDismissConfirmation}>취소</button>
            <button
              className="button button--danger"
              type="button"
              disabled={dismissBusy}
              onClick={() => {
                void dismissMany("all", false).then((dismissed) => {
                  if (!dismissed) return;
                  setDismissAllConfirmationOpen(false);
                  restoreDismissFocus();
                });
              }}
            >
              {dismissBusy ? "지우는 중" : `${snapshot.items.length}개 지우기`}
            </button>
          </footer>
        </div>
      </dialog>
    </section>
  );
}

function notificationReadStateNotice(notice: WorkNotificationSnapshot["read_state_notice"]): string {
  if (notice === "read_state_recovered_from_backup") return "알림 기록을 백업에서 복구했습니다.";
  if (notice === "read_state_recovered_with_baseline") return "알림 기록을 복구하지 못해 이전 항목은 읽음으로 가져왔습니다.";
  if (notice === "read_state_future_schema") return "더 최신 버전의 알림 기록입니다. 이 버전에서는 읽음 상태를 저장할 수 없습니다.";
  return "";
}

function formatNotificationTime(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "시간 정보 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(timestamp);
}

function workOverviewHasOperations(run: RunState | undefined): boolean {
  if (!run) return false;
  return Boolean(run.archive || mainAlreadyApplied(run) || run.active_step === "verify"
    || ["ready_to_merge", "verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(run.stage)
    || ["verify", "merge", "push", "deploy"].includes(run.failed_step || "")
    || ["main_apply_recoverable", "main_apply_interrupted"].includes(run.integration_control?.reason_code || "")
    || run.integration_conflict && !["applied", "stale"].includes(run.integration_conflict.resolution_status));
}

function workOverviewProgressOperation(run: RunState, snapshot: OperationsSnapshot | undefined, projectName: string): string {
  if (!operationsSnapshotMatches(snapshot, projectName, run) || snapshot?.lock?.state !== "active"
    || snapshot.lock.run_id && snapshot.lock.run_id !== run.id) return "";
  const operation = snapshot.lock.operation;
  if (["verify", "verify-and-repair"].includes(operation)) {
    return run.active_step === "verify" || run.verification_progress_phase === "repairing" ? operation : "";
  }
  return ["merge", "push", "retry-main-push", "conflict-resolution-prepare", "conflict-resolution-apply", "conflict-resolution-verify"].includes(operation)
    ? operation : "";
}

function WorkDetailsNavigation({ view, run, onChange }: { view: WorkbenchView; run?: RunState; onChange(view: WorkbenchView): void }) {
  if (view === "results") return <nav className="work-details-navigation" aria-label="작업 상세 보기">
    <button className="button button--quiet" type="button" disabled={!run} onClick={() => onChange("tasks")}>
      <ChevronLeft aria-hidden="true" size={15} />작업으로 돌아가기
    </button>
  </nav>;
  if ((view === "tasks" || view === "operations") && run?.stage === "planned" && !run.archive) return null;
  const overview = view === "tasks" || view === "operations";
  const canPrepare = !run || run.stage === "planned";
  const hasResults = Boolean(run?.archive || run?.group_result_history?.length || run?.tasks.some((task) => ["completed", "merged"].includes(task.status)));
  return (
    <nav className="work-details-navigation" aria-label="작업 상세 보기">
      <div className="work-details-navigation__views">
        <button className="button button--quiet" type="button" aria-current={overview ? "page" : undefined}
          disabled={!run} onClick={() => onChange("tasks")}>작업</button>
        <button className="button button--quiet" type="button"
          disabled={!run || !hasResults} title={!hasResults ? "완료된 작업의 변경 기록이 여기에 표시됩니다." : undefined}
          onClick={() => onChange("results")}>변경 기록</button>
      </div>
      {canPrepare ? <button className="button button--quiet work-details-navigation__settings" type="button"
        aria-current={view === "planning" ? "page" : undefined} onClick={() => onChange("planning")}>
        <Settings aria-hidden="true" size={15} />실행 전 설정</button> : null}
    </nav>
  );
}

function ApplicationErrorBanner({ message, children }: { message: string; children?: ReactNode }) {
  const backendFailure = isBackendRecoveryError(message);
  const providerFailure = providerFailurePresentation(message);
  const conflict = message.match(/최신 Main과 (\d+)개 파일이 충돌했습니다/);
  const fileLock = message.includes("실행 중인 앱이 빌드 출력 파일을 사용하고 있어");
  const planningLock = message.match(/is already locked \(operation=(planning-chat|planning-preview|effort-policy),/);
  const issue = failurePresentation(message);
  const workspaceCleanup = /작업공간이 다른 프로그램|worktree (?:residue|remove)|workspace cleanup|작업 그룹.*삭제/.test(message)
    ? workspaceCleanupFailure(message) : "";
  return <div className="error-banner" role="alert">
    <AlertCircle aria-hidden="true" size={18} />
    <div className="error-banner__content">
      <p>{backendFailure ? "실행 엔진의 응답을 확인하지 못했습니다. 연결을 다시 확인해 주세요."
        : providerFailure ? `${providerFailure.title}. ${providerFailure.description}`
        : planningLock ? planningLock[1] === "effort-policy" ? "AI 설정 저장 잠금 때문에 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요. 작업 실행 잠금과는 별개입니다."
        : `${planningLock[1] === "planning-preview" ? "변경 미리보기" : "Planning AI 대화"} 잠금 때문에 요청을 완료하지 못했습니다. 기존 기획 요청이 끝났는지 확인한 뒤 다시 시도해 주세요. 작업 실행 잠금과는 별개입니다.`
        : fileLock ? "실행 중인 앱/서버를 종료한 뒤 ‘반영·마무리’에서 다시 검증하세요."
        : conflict ? `Main 변경과 겹치는 파일 ${conflict[1]}개가 있습니다. ‘반영·마무리’에서 충돌을 해결하세요.`
        : workspaceCleanup ? workspaceCleanup
        : `${issue.title.replace(/[.!?]$/, "")}. ${issue.description}`}</p>
      <details><summary>오류 상세</summary><pre>{message}</pre></details>
    </div>
    {children}
  </div>;
}

function projectRemovalReason(projectName: string, requests: Record<string, PendingExecutionRequest>, busyAction: string, busyProjectName: string, removingProjectName: string, planning?: PlanningRequestsSnapshot): string {
  if (!projectName) return "프로젝트를 먼저 선택하세요.";
  if (removingProjectName) return `${removingProjectName} 등록 해제 결과를 확인 중입니다.`;
  const prefix = JSON.stringify([projectName]).slice(0, -1) + ",";
  if (Object.keys(requests).some((key) => key.startsWith(prefix))) return "이 프로젝트의 실행 요청이 끝난 뒤 등록을 해제할 수 있습니다.";
  if ((planning?.activeRequests ?? (planning?.active ? [planning.active] : [])).some(owner => owner.projectName === projectName)) {
    return "이 프로젝트의 AI 요청이 끝난 뒤 등록을 해제할 수 있습니다.";
  }
  if (busyAction === "system.restartBackend") return "실행 엔진 재시작이 끝난 뒤 다시 시도하세요.";
  if (busyAction && busyProjectName === projectName) return "이 프로젝트의 요청이 끝난 뒤 등록을 해제할 수 있습니다.";
  return "";
}

function ProjectNavigation({ projectName, onSelect }: { projectName: string; onSelect(): void }) {
  return <button className="button button--quiet project-navigation" type="button"
    aria-label={projectName ? `현재 프로젝트 ${projectName} · 프로젝트 변경` : "프로젝트 선택"} onClick={onSelect}>
    <FolderKanban aria-hidden="true" size={16} />
    {projectName ? <><span className="project-navigation__name" title={projectName}>{projectName}</span><ChevronDown aria-hidden="true" size={15} /></> : "프로젝트 선택"}
  </button>;
}

function CurrentWorkNavigation({ projectName, run, active, onOpen }: {
  projectName: string; run: RunState; pendingAction?: string; active: boolean; onOpen(): void;
}) {
  return <button className="current-work-navigation" type="button" aria-current={active ? "page" : undefined}
    data-navigation-action aria-label={`열어본 작업으로 돌아가기 · ${projectName} · ${runDisplayName(run.summary, run.id)}`} onClick={onOpen}>
    <Activity aria-hidden="true" size={16} />
    <span className="current-work-navigation__copy">
      <span className="current-work-navigation__label">열어본 작업</span>
      <span className="current-work-navigation__project" title={projectName}>{projectName}</span>
    </span>
  </button>;
}

function RunNextActionBanner({ action, recovery, busy, expanded, onToggle, onInvoke }: {
  action: RunNextAction;
  recovery?: RunRecoveryGuidance;
  busy: boolean;
  expanded: boolean;
  onToggle(): void;
  onInvoke(): void;
}) {
  // Task 실패는 채팅의 오류 상세와 작업 카드에서 확인한다.
  if (recovery?.taskId && action.tone === "danger") return null;
  const mutating = ["confirm_plan", "execute", "resume", "retry", "verify", "refresh"].includes(action.kind);
  const processing = busy && mutating;
  const inlineDescription = action.kind === "none" && action.tone === "active";
  const hasGuidance = Boolean(recovery || !inlineDescription && action.description.trim());
  const actionLabel = recovery && action.tone === "danger" && action.kind === "task_log" ? "실패 로그 보기"
    : recovery && action.tone === "danger" && action.kind === "task_detail" ? "실패 작업 확인" : action.label;
  const icon = action.kind === "task_log" ? <ListChecks aria-hidden="true" size={16} />
    : action.kind === "planning" ? <MessageSquare aria-hidden="true" size={16} />
      : action.kind === "operations" ? <GitMerge aria-hidden="true" size={16} />
        : action.kind === "refresh" ? <RefreshCw aria-hidden="true" size={16} />
          : action.kind === "resume" ? <RotateCcw aria-hidden="true" size={16} />
            : action.kind === "execute" ? <Play aria-hidden="true" size={16} />
              : action.kind === "confirm_plan" ? <CheckCircle2 aria-hidden="true" size={16} />
                : <Clock3 aria-hidden="true" size={16} />;
  return (
    <section className="run-next-action" data-tone={action.tone} aria-label="현재 상태와 다음 행동" data-attention-action tabIndex={-1}>
      <div className="run-next-action__copy"><span>{recovery ? action.tone === "danger" ? "실패 복구" : "상태 확인" : action.kind === "none" ? "현재 상황" : "다음 할 일"}</span>
        <strong>{recovery ? `${action.tone === "danger" ? "실패 위치" : "확인 위치"} · ${recovery.location}` : action.status}</strong>
        {inlineDescription ? <p>{action.description}</p> : null}
        {hasGuidance ? <><button className="run-next-action__toggle" type="button" aria-expanded={expanded} aria-controls="run-next-action-details" onClick={onToggle}>{expanded ? "안내 접기" : "안내 펼치기"}<ChevronDown aria-hidden="true" size={14} /></button>
        <div id="run-next-action-details" className="run-next-action__details" hidden={!expanded}>
          {recovery || action.kind !== "none" || action.tone !== "active" ? <p>{recovery ? `원인 · ${recovery.cause}` : action.description}</p> : null}
          {recovery ? <div className="run-recovery-guidance">
            <p><b>권장 행동</b>{recovery.recommendation}</p>
            <p><b>실행 효과</b>{recovery.effect}</p>
            <details><summary>상세 근거</summary><pre tabIndex={0}>{recovery.evidence}</pre></details>
          </div> : null}
        </div></> : null}
      </div>
      {action.kind !== "none" ? <button className="button button--primary" type="button" disabled={processing || action.disabled} onClick={onInvoke}>
        {processing ? <RefreshCw aria-hidden="true" className="spin" size={16} /> : icon}{processing ? "요청 처리 중" : actionLabel}
      </button> : null}
    </section>
  );
}

interface WorkGroupPaneProps {
  visible?: boolean;
  runs: RunSummary[];
  mode: GroupListMode;
  globalGroups: ActiveGroupSummary[];
  globalCount: number;
  globalErrorCount: number;
  globalErrors: ActiveGroupSnapshot["errors"];
  globalError: string;
  globalLoading: boolean;
  globalSearch: string;
  selectedProjectName: string;
  scope: "active" | "archived";
  selectedRunId: string;
  search: string;
  statusFilter: RunStatusFilter;
  statusCounts: Record<RunStatusFilter, number>;
  totalRunCount: number;
  loading: boolean;
  deletingRunId: string;
  archivingRunId: string;
  onScopeChange(scope: "active" | "archived"): void;
  onModeChange(mode: GroupListMode): void;
  onGlobalSearch(value: string): void;
  onRefreshGlobal(): void;
  onRefreshProject(): void;
  onSelectGlobal(projectName: string, runId: string): void;
  onSearch(value: string): void;
  onStatusFilter(filter: RunStatusFilter): void;
  onClearConditions(): void;
  onSelectRun(runId: string): void;
  onDeleteRun(runId: string): void;
  onArchiveRun(runId: string): void;
  onNewPlanning(): void;
}

function WorkGroupPane({
  visible = true,
  runs, mode, globalGroups, globalCount, globalErrorCount, globalErrors, globalError, globalLoading, globalSearch, selectedProjectName,
  scope, selectedRunId, search, statusFilter, statusCounts, totalRunCount, loading, deletingRunId, archivingRunId,
  onScopeChange, onModeChange, onGlobalSearch, onRefreshGlobal, onRefreshProject, onSelectGlobal, onSearch, onStatusFilter,
  onClearConditions, onSelectRun, onDeleteRun, onArchiveRun, onNewPlanning,
}: WorkGroupPaneProps) {
  const conditionsActive = Boolean(search.trim()) || (scope === "active" && statusFilter !== "all");
  const selectedOutsideFilter = Boolean(selectedRunId) && !runs.some((run) => run.id === selectedRunId);
  const selectedOutsideGlobal = Boolean(selectedRunId) && !globalGroups.some((run) => run.project_name === selectedProjectName && run.run_id === selectedRunId);
  const listRef = useRef<HTMLDivElement>(null);
  const scrollPositions = useRef<Record<string, number>>({});
  const scrollKey = mode === "global" ? "global" : `project\0${selectedProjectName}\0${scope}`;
  useLayoutEffect(() => {
    if (!visible) return;
    const frame = window.requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = scrollPositions.current[scrollKey] || 0;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [visible, scrollKey, selectedRunId]);
  return (
    <section className="group-pane" aria-label="작업 그룹 선택">
      <button className="button button--primary button--full" type="button" disabled={!selectedProjectName} onClick={onNewPlanning}><Plus aria-hidden="true" size={15} />새 계획</button>
      <span className="group-pane__project-target">새 계획 대상 · {selectedProjectName || "프로젝트 선택 필요"}</span>
      <div className="group-scope-tabs group-scope-tabs--mode" role="tablist" aria-label="작업 그룹 조회 범위">
        <button type="button" role="tab" aria-selected={mode === "global"} onClick={() => onModeChange("global")}>모든 프로젝트 진행 중 <small>{globalCount}</small></button>
        <button type="button" role="tab" aria-selected={mode === "project"} onClick={() => onModeChange("project")}>프로젝트별</button>
      </div>
      {mode === "project" ? <><div className="group-scope-tabs" role="tablist" aria-label="프로젝트별 작업 그룹 범위">
        <button type="button" role="tab" aria-selected={scope === "active"} onClick={() => onScopeChange("active")}>현재</button>
        <button type="button" role="tab" aria-selected={scope === "archived"} onClick={() => onScopeChange("archived")}>보관</button>
      </div></> : null}
      <label className="search-field">
        <Search aria-hidden="true" size={15} /><span className="sr-only">작업 그룹 검색</span>
        <input value={mode === "global" ? globalSearch : search} type="search" placeholder={mode === "global" ? "프로젝트·작업 그룹 검색" : "작업 그룹 검색"} onChange={(event) => mode === "global" ? onGlobalSearch(event.target.value) : onSearch(event.target.value)} />
      </label>
      {mode === "global" ? <div className="group-global-status" role="status">
        <span>확인된 진행 {globalCount}개{globalErrorCount ? ` · ${globalErrorCount}개 프로젝트 상태 확인 실패` : ""}</span>
        <button className="button button--quiet" type="button" disabled={globalLoading} onClick={onRefreshGlobal}>{globalLoading ? "확인 중…" : "새로고침"}</button>
      </div> : <div className="group-global-status" role="status">
        <span>{scope === "archived" ? "보관" : "현재"} {totalRunCount}개</span>
        <button className="button button--quiet" type="button" disabled={loading || !selectedProjectName} onClick={onRefreshProject}>{loading ? "확인 중…" : "새로고침"}</button>
      </div>}
      {mode === "global" && globalError ? <p className="group-global-error" role="alert">진행 상태를 확인하지 못했습니다: {globalError}</p> : null}
      {mode === "global" && globalErrors.length ? <details className="group-global-errors"><summary>확인 실패 프로젝트 {globalErrors.length}개</summary><ul>{globalErrors.map((item) => <li key={item.project_name}>{item.project_name} · {item.error}</li>)}</ul></details> : null}
      {mode === "project" && scope === "active" ? <div className="group-status-filters" aria-label="작업 그룹 상태 필터">
        {(Object.keys(runStatusFilterLabels) as RunStatusFilter[]).map((filter) => <button key={filter} type="button" aria-pressed={statusFilter === filter} onClick={() => onStatusFilter(filter)}><span>{runStatusFilterLabels[filter]}</span><small>{statusCounts[filter]}</small></button>)}
      </div> : null}
      {mode === "project" && selectedOutsideFilter && conditionsActive ? <p className="group-filter-context" role="status">현재 그룹은 필터 밖에 있습니다. 상세와 편집 내용은 유지됩니다.</p> : null}
      {mode === "global" && selectedOutsideGlobal ? <p className="group-filter-context" role="status">열어 둔 그룹은 현재 진행 목록 밖에 있습니다. 상세는 유지됩니다. <button type="button" onClick={() => onModeChange("project")}>프로젝트별 보기</button></p> : null}
      <div ref={listRef} className="group-list" aria-busy={mode === "global" ? globalLoading : loading}
        onScroll={(event) => {
          if (visible && event.currentTarget.closest("dialog")?.open !== false) scrollPositions.current[scrollKey] = event.currentTarget.scrollTop;
        }}>
        {mode === "global" ? <>
          {globalLoading && globalGroups.length === 0 ? <LoadingRows /> : null}
          {!globalLoading && globalGroups.length === 0 && !globalSearch.trim() ? <EmptyState icon={<FolderKanban aria-hidden="true" size={22} />} title="진행 중인 작업 그룹이 없습니다" detail={globalErrorCount || globalError ? "일부 상태를 확인하지 못했습니다. 새로고침으로 다시 확인하세요." : "프로젝트별 목록에서 대기·완료 그룹을 볼 수 있습니다."} /> : null}
          {!globalLoading && globalGroups.length === 0 && globalSearch.trim() ? <div className="group-filter-empty"><Search aria-hidden="true" size={22} /><strong>검색 결과가 없습니다</strong><button className="button button--secondary" type="button" onClick={() => onGlobalSearch("")}>검색 초기화</button></div> : null}
          {globalGroups.map((run) => <article key={`${run.project_name}\0${run.run_id}`} className="group-row group-row--global" data-selected={run.project_name === selectedProjectName && run.run_id === selectedRunId}>
            <button className="group-row__select" type="button" aria-label={`${run.project_name} · ${runDisplayName(run.title, run.run_id)} 작업 그룹 열기`} onClick={() => onSelectGlobal(run.project_name, run.run_id)}>
              <span className="group-row__project">{run.project_name}</span>
              <span className="group-row__topline"><span className={`status-mark status-mark--${run.status === "active" ? "active" : "warning"}`} /><strong>{runDisplayName(run.title, run.run_id)}</strong></span>
              <span className="group-row__meta"><span>{activeGroupActivityLabel(run)}</span><span>{run.completed_task_count}/{run.task_count} Task</span></span>
              <span className="group-row__time">최근 활동 {formatDate(run.last_activity_at)} · {run.stale ? "이전 확인" : "확인"} {formatDate(run.checked_at)}</span>
            </button>
          </article>)}
        </> : null}
        {mode === "project" ? <>
        {loading && totalRunCount === 0 ? <LoadingRows /> : null}
        {!loading && totalRunCount === 0 ? <EmptyState icon={scope === "archived" ? <Archive aria-hidden="true" size={22} /> : <FolderKanban aria-hidden="true" size={22} />} title={scope === "archived" ? "보관된 작업 그룹이 없습니다" : "아직 작업 그룹이 없습니다"} detail={scope === "archived" ? "완료 그룹을 보관하면 기록이 여기에 표시됩니다." : "새 계획을 만들어 시작하세요."} /> : null}
        {!loading && totalRunCount > 0 && runs.length === 0 ? <div className="group-filter-empty"><Search aria-hidden="true" size={22} /><strong>조건에 맞는 작업 그룹이 없습니다</strong><p>검색어나 상태 필터를 바꿔 다시 확인하세요.</p><button className="button button--secondary" type="button" onClick={onClearConditions}>검색·필터 초기화</button></div> : null}
        {runs.map((run) => {
          const displayName = runDisplayName(run.summary, run.id);
          return (
            <article key={run.id} className="group-row" data-selected={run.id === selectedRunId}>
              <button className="group-row__select" type="button" aria-label={`${displayName} 작업 그룹 열기`} onClick={() => onSelectRun(run.id)}>
                <span className="group-row__topline"><span className={`status-mark status-mark--${stageTone(run.stage)}`} /><strong>{displayName}</strong></span>
                <span className="group-row__meta"><span>{stageLabels[run.stage] || run.stage}</span><span>{run.completed_task_count}/{run.task_count} Task</span></span>
                <span className="progress-track" aria-hidden="true"><span className="progress-track__value" style={{ transform: `scaleX(${run.task_count ? run.completed_task_count / run.task_count : 0})` }} /></span>
                <span className="group-row__time">{formatDate(run.archived_at || run.updated_at)}</span>
              </button>
              {scope === "active" && ["pushed", "deployed"].includes(run.stage)
                ? <button className="icon-button group-row__delete" type="button" title="완료 기록 보관·작업공간 정리" aria-label={`${displayName} 작업 그룹 보관`} disabled={Boolean(archivingRunId)} onClick={() => onArchiveRun(run.id)}>{archivingRunId === run.id ? <RefreshCw aria-hidden="true" className="spin" size={14} /> : <Archive aria-hidden="true" size={14} />}</button>
                : scope === "active" ? <button className="icon-button icon-button--danger group-row__delete" type="button" title="작업 그룹 삭제" aria-label={`${displayName} 작업 그룹 삭제`} disabled={Boolean(deletingRunId)} onClick={() => onDeleteRun(run.id)}>{deletingRunId === run.id ? <RefreshCw aria-hidden="true" className="spin" size={14} /> : <Trash2 aria-hidden="true" size={14} />}</button> : null}
            </article>
          );
        })}
        </> : null}
      </div>
    </section>
  );
}

interface PaneResizerProps {
  label: string;
  value: number;
  min: number;
  max: number;
  defaultValue: number;
  direction?: 1 | -1;
  variant?: "group" | "inspector" | "planning";
  onChange(value: number): void;
}

function PaneResizer({ label, value, min, max, defaultValue, direction = 1, variant = "group", onChange }: PaneResizerProps) {
  const dragRef = useRef<{ startX: number; startValue: number } | undefined>(undefined);
  const resizeByKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Home") {
      event.preventDefault();
      onChange(min);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      onChange(max);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? -16 : 16;
    onChange(clamp(value + delta * direction, min, max));
  };
  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = { startX: event.clientX, startValue: value };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const continueResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const delta = (event.clientX - dragRef.current.startX) * direction;
    onChange(clamp(dragRef.current.startValue + delta, min, max));
  };
  const finishResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = undefined;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return <div className={`pane-resizer pane-resizer--${variant}`} role="separator" aria-label={label} aria-orientation="vertical" aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-valuetext={`${value}px`} tabIndex={0} title="드래그하여 너비 조절 · 더블 클릭하여 초기화" onDoubleClick={() => onChange(defaultValue)} onKeyDown={resizeByKeyboard} onPointerDown={startResize} onPointerMove={continueResize} onPointerUp={finishResize} onPointerCancel={finishResize} />;
}

interface PlanningWorkbenchProps {
  chatFirst?: boolean;
  scrollMemory?: RefObject<Record<string, { top: number; followsLatest: boolean }>>;
  workActivity?: ReactNode;
  executionPhase?: ChatExecutionPhase;
  repairStartedAt?: number;
  bodyVisible?: boolean;
  usageSnapshot?: UsageSnapshot;
  usageError?: string;
  contextPanel?: ReactNode;
  taskSettings?: ReactNode;
  taskQuestion?: WorkTask;
  chatTarget?: HTMLElement | null;
  project?: RegisteredProject;
  run?: RunState;
  capabilities?: ProjectCapabilities;
  repositoryIntent: "" | "existing_structure" | "new_project";
  path: string;
  mode: PlanningMode;
  request: string;
  profiles: ProviderProfile[];
  providerStatuses: ProviderStatus[];
  selectedProfileKey: string;
  reasoning: string;
  effortMode: EffortMode;
  profileManual: boolean;
  reasoningOptions: string[];
  message: string;
  pendingMessage?: PendingPlanningMessage;
  index?: PlanningSourceIndex;
  indexElapsed: number;
  planningElapsed: number;
  preparationMessage: string;
  startError?: string;
  preparing?: boolean;
  busyAction: string;
  messageQueue?: PlanningMessageQueueSnapshot;
  queueSubmitting?: boolean;
  onQueue?(): void;
  onChangeQueued?(change: QueuedMessageChange): Promise<boolean>;
  onRestoreQueued?(item: QueuedPlanningMessage): Promise<boolean>;
  planningRequestError?: string;
  interruptLabel?: string;
  planDirty: boolean;
  draftConflict: boolean;
  interruptible: boolean;
  onPathChange(value: string): void;
  onModeChange(value: PlanningMode): void;
  onRequestChange(value: string): void;
  onRepositoryIntentChange(value: "existing_structure" | "new_project"): void;
  onChoosePath(): void;
  onSavePath(): void;
  onRefreshIndex(): void;
  onRefreshProviders(): void;
  onOpenCodexAuth(): void;
  onOpenPlanningSettings?(): void;
  onProfileChange(value: string): void;
  onReasoningChange(value: string): void;
  onEffortModeChange(value: EffortMode): void;
  onMessageChange(value: string): void;
  onStart(): void;
  onRunPreparedRevision(): void;
  onSend(): void;
  onApply(): void;
  onConfirmTechStack(optionId: string, expectedRevision: number): void;
  onAnswerTechnology(answer: string): void;
  onRetryGreenfield(): void;
  onStartGreenfield(): void;
  onConfigureBootstrapInstructions(create: boolean, expectedRevision: number, expectedDigest: string): void;
  onGenerateFeaturePlan(): void;
  onInterrupt(): void;
}

function PlanningWorkbench(props: PlanningWorkbenchProps) {
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const [taskSettingsMounted, setTaskSettingsMounted] = useState(false);
  const preparing = props.preparing ?? props.busyAction === "runs.start";
  const repairActive = props.repairStartedAt !== undefined;
  const busy = Boolean(props.busyAction || repairActive);
  const sendBlocked = busy;
  const selectedProfile = props.profiles.find(
    (profile) => providerProfileKey(profile) === props.selectedProfileKey,
  );
  const selectedProviderId = selectedProfile?.provider_id;
  const selectedProviderStatus = props.providerStatuses.find(
    (status) => status.id === selectedProviderId,
  );
  const selectedProviderReady = selectedProviderStatus?.available === true;
  const excludedPlanningSelection = Boolean(!selectedProfile && (props.selectedProfileKey || props.run?.planning_provider_id));
  const otherProviderStatuses = props.providerStatuses.filter(
    (status) => status.id !== selectedProviderId,
  );
  const projectChatThinking = props.executionPhase === "thinking" || props.busyAction === "runs.decideProjectChat";
  const planningActive =
    projectChatThinking ||
    repairActive ||
    preparing ||
    props.busyAction === "runs.runPlanning" ||
    props.busyAction === "runs.sendPlanningMessage" ||
    props.busyAction === "runs.applyPlanningConversation" ||
    props.busyAction === "planning.generateFeaturePlan" ||
    (props.run?.active_step === "planning" && props.run.stage !== "reviewed");
  const latestPlanningEvent = props.run?.events[props.run.events.length - 1];
  const currentPlanningEvent = props.repairStartedAt === undefined || Date.parse(latestPlanningEvent?.at || "") >= props.repairStartedAt;
  const progressContext = planningProgressContext(props.run?.events || []);
  const localizedProgress = localizeEvent(
    latestPlanningEvent?.message || "planning document received",
    progressContext.purpose,
  );
  const retryLabel = progressContext.retryIndex > 0 &&
    !/^planning agent attempt \d+ failed:/.test(latestPlanningEvent?.message || "")
    ? ` · 자동 재시도 ${progressContext.retryIndex}회째`
    : "";
  const progressMessage = props.preparationMessage || (repairActive && !currentPlanningEvent
    ? "실패 원인을 바탕으로 복구안을 준비하고 있습니다."
    : props.run
    ? `${localizedProgress}${retryLabel}`
    : "기획 AI 실행 요청을 준비하고 있습니다.");
  const progressPurpose = projectChatThinking || props.busyAction === "runs.sendPlanningMessage" ? "chat"
    : props.busyAction === "runs.applyPlanningConversation" ? "apply"
      : preparing || ["runs.runPlanning", "planning.generateFeaturePlan"].includes(props.busyAction) ? "plan"
        : progressContext.purpose;
  const progressFailed = currentPlanningEvent && /^planning agent attempt \d+ failed:/.test(latestPlanningEvent?.message || "");
  const providerWaiting = currentPlanningEvent && (latestPlanningEvent?.message.startsWith("codex sdk progress: provider_retry_wait") || false);
  const progressTitle = providerWaiting ? localizedProgress : progressFailed ? "기획 처리에 문제가 생겼습니다"
    : projectChatThinking ? "현재 상태와 다음 행동 확인 중" : repairActive ? "복구안 작업 중입니다" : preparing ? "기획 준비 중" : progressPurpose === "chat" ? "답변 작성 중"
      : progressPurpose === "apply" ? "계획 반영 중" : "계획 작성 중";
  const pendingAcknowledged = Boolean(
    props.pendingMessage &&
    props.run?.planning_messages
      .slice(props.pendingMessage.previousMessageCount)
      .some(
        (item) =>
          item.role === "user" && item.text === props.pendingMessage?.text,
      ),
  );
  const visiblePendingMessage = pendingAcknowledged
    ? undefined
    : props.pendingMessage;
  const workbenchRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const planningMessageInputRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const followsLatestRef = useRef(true);
  const [fullMessage, setFullMessage] = useState<FullPlanningMessage | undefined>(undefined);
  const messageScope = JSON.stringify([props.project?.name || "", props.run?.id || ""]);
  const fullMessagePresent = fullMessage?.scope === messageScope && (props.run?.planning_messages.some((item, index) =>
    planningMessageKey(props.project?.name || "", props.run?.id || "", item, index) === fullMessage.key && item.text === fullMessage.text)
    || props.run?.planning_questions.includes(fullMessage.text) || visiblePendingMessage?.text === fullMessage.text);
  useEffect(() => { if (fullMessage && !fullMessagePresent) setFullMessage(undefined); }, [messageScope, fullMessagePresent]);
  const messageBody = (text: string, key: string, displayText = localizePlanningText(text), meta = "기획 AI") => <PlanningMessageDisclosure
    text={text} displayText={displayText} expanded={false} inline={props.chatFirst}
    onExpandedChange={() => { followsLatestRef.current = false; setFullMessage({scope: messageScope, key, text, meta}); }} />;
  useLayoutEffect(() => {
    if (!props.chatFirst || !props.chatTarget || !messagesRef.current) return;
    const saved = props.scrollMemory?.current[messageScope];
    followsLatestRef.current = saved?.followsLatest ?? true;
    messagesRef.current.scrollTop = saved?.top ?? messagesRef.current.scrollHeight;
  }, [messageScope, props.chatTarget]);
  const progressUpdatesReadyRef = useRef(false);
  const [requestExpanded, setRequestExpanded] = useState(false);
  const techStackDecision = activeTechStackDecision(props.run?.tech_stack_decisions);
  const [selectedTechStackOptionId, setSelectedTechStackOptionId] = useState(
    techStackDecision?.status === "confirmed" ? techStackDecision.selected_option_id : "",
  );
  const [repairClockNow, setRepairClockNow] = useState(Date.now());
  useEffect(() => {
    if (!repairActive) return;
    setRepairClockNow(Date.now());
    const timer = window.setInterval(() => setRepairClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [props.repairStartedAt]);
  const repairElapsed = Math.max(0, Math.floor((repairClockNow - (props.repairStartedAt ?? repairClockNow)) / 1000));
  const scrollToLatestMessage = () => {
    const workbench = props.chatTarget ? messagesRef.current : workbenchRef.current;
    if (workbench && workbench.scrollHeight > workbench.clientHeight) {
      workbench.scrollTop = workbench.scrollHeight;
      return;
    }
        const lastMessage = messagesRef.current?.lastElementChild;
        if (lastMessage) scrollPlanningContentIntoView(lastMessage);
  };
  useEffect(() => {
    followsLatestRef.current = props.scrollMemory?.current[messageScope]?.followsLatest ?? true;
    progressUpdatesReadyRef.current = false;
    if (workbenchRef.current) workbenchRef.current.scrollTop = 0;
  }, [props.run?.id]);
  useEffect(() => {
    setSelectedTechStackOptionId(
      techStackDecision?.status === "confirmed" ? techStackDecision.selected_option_id : "",
    );
  }, [props.run?.id, techStackDecision?.revision, techStackDecision?.status, techStackDecision?.selected_option_id]);
  useEffect(() => {
    if (!visiblePendingMessage || !messagesRef.current) return;
    scrollToLatestMessage();
    followsLatestRef.current = true;
  }, [visiblePendingMessage?.at]);
  useEffect(() => {
    if (!progressUpdatesReadyRef.current) {
      progressUpdatesReadyRef.current = true;
      return;
    }
    if (!followsLatestRef.current || !messagesRef.current) return;
    scrollToLatestMessage();
  }, [
    planningActive,
    progressMessage,
    props.run?.planning_messages.length,
    props.run?.planning_questions.length,
  ]);
  const hasConversation = Boolean(
    props.run?.planning_messages.length ||
    props.run?.planning_questions.length ||
    visiblePendingMessage ||
    planningActive,
  );
  const lastQuestionMessage = props.run?.stage === "needs_clarification"
    ? props.run.planning_messages.reduce((last, message, index) => message.role === "assistant" ? index : last, -1)
    : -1;
  const activeAgentLabel = props.run?.planning_provider_id === "codex"
    ? "Codex"
    : props.run?.planning_provider_id === "claude"
      ? "Claude"
      : "기획 AI";
  const activeElapsed = (
    props.busyAction === "runs.start" ||
    props.busyAction === "runs.sendPlanningMessage"
  )
    ? formatDuration(props.planningElapsed)
    : props.run
      ? formatElapsed(props.run.updated_at)
      : formatDuration(props.planningElapsed);
  const startReadiness = planningStartReadiness({
    projectAvailable: Boolean(props.project),
    mode: props.mode,
    request: props.request,
    sourcePath: props.path,
    profileCount: props.profiles.length,
    providerReady: selectedProviderReady,
    repositoryMaturity: props.capabilities?.repository_maturity.kind,
    repositoryIntent: planningRepositoryIntent(props.capabilities?.repository_maturity.kind, props.repositoryIntent),
    repositoryInspectionPending: !props.capabilities,
  });
  const resultDiscussion = Boolean(props.run && ["verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(props.run.stage));
  const chatAllowed = !props.run || [
    "needs_clarification",
    "planned",
    "executing",
    "failed",
    "ready_to_merge", "verified", "work_branch_pushed", "merged", "pushed", "deployed",
  ].includes(props.run.stage);
  const queuedMessages = props.messageQueue?.items.filter(item => item.projectName === props.project?.name && item.runId === props.run?.id) || [];
  const queueMode = Boolean(props.onQueue && props.run && (props.interruptible || planningActive || props.executionPhase === "working"
    || queuedMessages.some(item => item.status !== "sent")));
  const messageAllowed = chatAllowed || Boolean(props.run && props.interruptible && props.run.stage === "reviewed");
  const composerHint = props.run?.archive ? "보관된 결과는 유지됩니다" : props.planDirty
    ? `${props.draftConflict ? "외부 변경 충돌 · " : ""}${props.taskQuestion ? "초안 질문 가능 · 반영 전 편집 정리" : "미저장 편집을 저장하거나 취소하세요"}`
    : resultDiscussion ? "수정안은 변경 기록에서 확인" : props.run?.project_chat_available ? "프로젝트 안에서 조사·수정·검증까지 이어갑니다"
      : props.run?.stage === "executing" ? "변경은 현재 실행 종료 후 반영" : "";
  const guided = props.run?.repository_intent === "new_project";
  const centralQuestions = Boolean(props.run?.planning_questions.length && !props.run.tech_stack_confirmation_allowed
    && (guided ? techStackDecision?.status !== "confirmed" : techStackDecision?.status === "questions_required"));
  const chatPlaceholder = props.run?.archive ? "완료한 작업에 대해 질문하거나 다음 작업을 논의하세요" : resultDiscussion ? "바꾸고 싶은 점을 알려주세요" : props.run && guided ? greenfieldPlaceholder(props.run) : !chatAllowed
    ? "현재 단계에서는 새 기획 대화를 시작해 주세요."
    : props.run?.stage === "failed"
      ? "해결할 내용을 입력하세요"
      : props.run?.stage === "executing"
        ? "질문이나 변경할 내용을 입력하세요"
        : "질문이나 요청을 입력하세요";
  const followUpCount = props.run?.planning_follow_up_requests.length || 0;
  const followUpReviewReady = !props.run?.active_step && !props.run?.tasks.some(taskIsActive);
  const latestApply = props.run?.planning_apply_requests?.[props.run.planning_apply_requests.length - 1];
  const applyPending = latestApply?.status === "queued" || latestApply?.status === "applying";
  const conversationRevision = props.run?.planning_conversation_revision || 0;
  const appliedConversationRevision = props.run?.planning_applied_conversation_revision || 0;
  const hasUnappliedConversation = conversationRevision > appliedConversationRevision || followUpCount > 0;
  const initialTasksAvailable = initialTaskPlanningAvailable(props.run);
  const showApplyReceipt = !guided && (latestApply || followUpCount) && (latestApply?.status !== "succeeded"
    || (!planningActive && !visiblePendingMessage && !hasUnappliedConversation
      && conversationRevision <= (latestApply.conversation_revision ?? appliedConversationRevision)));
  const applyChangeSummary = latestApply ? [
    latestApply.added_tasks ? `${latestApply.added_tasks}개 추가` : "",
    latestApply.updated_tasks ? `${latestApply.updated_tasks}개 수정` : "",
    latestApply.excluded_tasks ? `${latestApply.excluded_tasks}개 제외` : "",
  ].filter(Boolean).join(" · ") || "변경 없음" : "";
  const executionRunning = Boolean(
    props.run?.tasks.some(taskIsActive) || props.run?.active_step === "agent_execution",
  );
  const applyDisabled = Boolean(
    props.run?.archive || !chatAllowed || busy || excludedPlanningSelection
    || (guided && (!hasUnappliedConversation || planningActive || applyPending || props.planDirty))
  );
  const greenfieldDecision = guided && !props.run?.bootstrap_spec;
  const showPlanningApply = !props.run?.archive && ((!props.chatFirst && resultDiscussion) || (guided && props.run?.greenfield_phase === "feature_plan_ready"));
  const techStackConfirmed = techStackDecision?.status === "confirmed";
  const inlinePlanningApply = !props.chatFirst && !props.run?.archive && !guided && !resultDiscussion;
  const lastAssistantMessage = props.run?.planning_messages.map((item) => item.role).lastIndexOf("assistant") ?? -1;
  const conversationApplied = appliedConversationRevision > 0 && !hasUnappliedConversation
    && !applyPending && latestApply?.status !== "failed";
  const inlineApplyBlockedByExecution = planningApplyEntryBlocked(props.run);
  const inlineApplyDisabled = applyDisabled || conversationApplied || inlineApplyBlockedByExecution || (planningActive && !applyPending) || Boolean(visiblePendingMessage)
    || lastAssistantMessage !== (props.run?.planning_messages.length || 0) - 1;
  const inlineApplyLabel = conversationApplied ? "반영 완료" : applyPending ? "반영 상태 확인"
    : latestApply?.status === "failed" ? "다시 반영" : "작업에 반영";
  const applyLabel = resultDiscussion ? "수정안 확인" : props.busyAction === "runs.applyPlanningConversation" || latestApply?.status === "applying"
      ? greenfieldDecision ? "초기화 계획 생성 중…" : "작업에 반영 중…"
      : executionRunning || latestApply?.status === "queued"
        ? "반영 예약"
        : techStackConfirmed && greenfieldDecision
          ? "초기화 계획 만들기"
          : greenfieldDecision
            ? props.run?.greenfield_phase === "questions_required" ? "답변으로 후보 갱신" : "기술 구성 선택 필요"
            : "기능 계획 갱신";
  const sendMessage = () => {
    if (composingRef.current || !messageAllowed || excludedPlanningSelection || !props.message.trim()) return;
    if (queueMode) { if (!props.queueSubmitting) props.onQueue?.(); return; }
    if (sendBlocked) return;
    const option = props.run ? greenfieldConsentOption(props.run, props.message, selectedTechStackOptionId) : undefined;
    if (option && techStackDecision) props.onConfirmTechStack(option.option_id, techStackDecision.revision);
    else props.onSend();
  };
  const failedAnswer = props.run ? greenfieldRetry(props.run) : undefined;
  useEffect(() => {
    if (failedAnswer?.answer_message && !props.message.trim()) props.onMessageChange(failedAnswer.answer_message);
  }, [props.run?.id, failedAnswer?.request_id]);
  const requestText = props.request.trim();
  const requestIsLong = (
    requestText.length > 240 || requestText.split(/\r?\n/).length > 5
  );
  const sourceSummary = planningSourceSummary(
    props.mode,
    props.path,
    props.index?.document_count,
  );
  const profileSummary = selectedProfile
    ? `${providerProfileLabel(selectedProfile)} · ${props.reasoning || providerDefaultReasoningLabel(selectedProviderId)}`
    : "선택된 모델 없음";
  const sourceSettings = (
    <>
      <div className="planning-source-summary">
        <span title={props.path}>{props.path.trim().split(/[\\/]/).filter(Boolean).at(-1) || "선택한 자료 폴더 없음"}</span>
        <button className="button button--quiet" type="button" disabled={busy} onClick={props.onChoosePath}><FolderOpen aria-hidden="true" size={15} />{props.path.trim() ? "폴더 변경" : "폴더 선택"}</button>
      </div>
      <details className="planning-setup__details"><summary>자료 관리</summary><div className="planning-setup__details-body">
        <label className="field"><span>자료 폴더 전체 경로</span><input value={props.path} disabled={busy} placeholder="기획 자료 폴더 경로" onChange={(event) => props.onPathChange(event.target.value)} /></label>
        <div className="planning-setup__actions">
          <button className="button button--quiet" type="button" disabled={!props.path.trim() || busy} onClick={props.onSavePath}>경로 저장</button>
          <button className="button button--quiet" type="button" disabled={!props.path.trim() || busy} onClick={props.onRefreshIndex}><RefreshCw aria-hidden="true" size={15} />{props.busyAction === "planning.refreshIndex" ? `색인 중… ${props.indexElapsed}초` : "문서 색인"}</button>
        </div>
        {props.index ? <p className="index-summary">색인 {props.index.document_count}개 · 변경 {props.index.added_count + props.index.modified_count + props.index.deleted_count}개 · {formatDate(props.index.generated_at)}</p> : null}
      </div></details>
    </>
  );
  const profileSettings = (
    <>
      <div className="planning-profile__controls">
        <label className="field"><span>기획 모델</span><select value={props.selectedProfileKey} disabled={!props.profiles.length || busy} onChange={(event) => props.onProfileChange(event.target.value)}>{!props.profiles.length ? <option value={props.selectedProfileKey} disabled>연결된 AI 없음</option> : !selectedProfile && props.selectedProfileKey ? <option value={props.selectedProfileKey} disabled>저장한 모델을 사용할 수 없습니다. 다시 선택해 주세요.</option> : excludedPlanningSelection ? <option value="" disabled>실행할 모델을 다시 선택해 주세요</option> : null}{props.profiles.map((profile) => <option key={providerProfileKey(profile)} value={providerProfileKey(profile)}>{providerProfileLabel(profile)}</option>)}</select></label>
        <label className="field"><span>추론 강도</span><select value={props.reasoning} disabled={busy} onChange={(event) => props.onReasoningChange(event.target.value)}><option value="">{providerDefaultReasoningLabel(selectedProviderId)}</option>{props.reasoningOptions.map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></label>
      </div>
      <div className="planning-profile__status">
        {selectedProviderStatus ? (
          <div className="provider-auth-status" data-state={providerStatusState(selectedProviderStatus)} aria-label={providerStatusText(selectedProviderStatus)}>
            <ShieldCheck aria-hidden="true" size={20} />
            <div className="provider-auth-status__copy" role="status">
              <span>{providerDisplayName(selectedProviderStatus.id)} 인증</span>
              <strong>{selectedProviderStatus.auth_label || (selectedProviderStatus.available ? "사용 가능" : "사용 불가")}</strong>
              <small>{providerAuthDetail(selectedProviderStatus)}</small>
            </div>
            <div className="provider-auth-status__actions">
              {selectedProviderStatus.id === "codex" && selectedProviderStatus.auth_method === "none" ? <button className="button button--secondary" type="button" disabled={busy} onClick={() => { setStartDialogOpen(false); props.onOpenCodexAuth(); }}>ChatGPT로 로그인</button> : null}
              <button className="button button--quiet provider-auth-status__refresh" type="button" disabled={busy} onClick={props.onRefreshProviders}><RefreshCw aria-hidden="true" size={14} />{props.busyAction === "providers.status" ? "확인 중" : "인증 새로고침"}</button>
            </div>
          </div>
        ) : null}
        {!selectedProviderStatus ? <div className="planning-setup__actions"><span role="status">사용 가능한 모델과 인증 상태를 확인해 주세요.</span><button className="button button--quiet" type="button" disabled={busy} onClick={props.onRefreshProviders}>AI 상태 확인</button><button className="button button--quiet" type="button" disabled={busy} onClick={() => { setStartDialogOpen(false); props.onOpenCodexAuth(); }}>ChatGPT로 로그인</button></div> : null}
        {otherProviderStatuses.length ? <div className="provider-status-list" aria-label="다른 AI 제공자 상태">
          {otherProviderStatuses.map((status) => (
            <span key={status.id} data-state={providerStatusState(status)} title={providerStatusText(status)}><CircleDot aria-hidden="true" size={12} />{providerStatusText(status)}</span>
          ))}
        </div> : null}
      </div>
    </>
  );
  const startAction = (
    <div className="planning-primary-action">
      {!startReadiness.ready ? <p id="planning-start-reason" className="planning-start-reason" role="status"><AlertCircle aria-hidden="true" size={14} />{startReadiness.reason}</p> : null}
      {props.startError ? <p className="inline-error" role="alert">{props.startError}</p> : null}
      {preparing ? <p role="status">{progressMessage}</p> : null}
      <button className="button button--primary planning-start" type="button" aria-describedby={!startReadiness.ready ? "planning-start-reason" : undefined} disabled={!startReadiness.ready || busy} onClick={props.onStart}><Play aria-hidden="true" size={16} />{preparing ? `자료 확인 중… ${props.planningElapsed}초` : planningRepositoryIntent(props.capabilities?.repository_maturity.kind, props.repositoryIntent) === "new_project" ? "기술 구성 추천받기" : props.mode === "auto" ? "분석하고 Task 만들기" : "계획 만들기"}</button>
    </div>
  );
  const maturity = props.run?.repository_maturity || props.capabilities?.repository_maturity;
  const maturityTitle = maturity?.kind === "docs_only"
    ? "사용할 기술 구성을 먼저 정합니다"
    : maturity?.kind === "ambiguous"
      ? "이 폴더에서 어떻게 시작할까요?"
      : "기존 코드를 바탕으로 계획합니다";
  const maturityDetail = maturity?.kind === "docs_only"
    ? props.run
      ? "이 계획 화면에서 기술 후보를 확인하고 결정합니다. 구성을 결정한 뒤 기본 구조를 만드는 계획으로 이어집니다."
      : "만들고 싶은 내용을 입력하면 AI가 기술 구성을 추천합니다."
    : maturity?.kind === "ambiguous"
      ? "앱이 프로젝트 구성을 확실히 판단하지 못했습니다. 현재 파일을 이어서 쓸지, 기본 구조부터 준비할지 선택해 주세요."
      : "현재 파일과 설정을 유지하고 요청에 맞는 작업을 계획합니다.";
  const evidenceGroups = maturity ? repositoryEvidenceGroups(maturity) : [];
  const repositoryChoice = maturity?.kind === "ambiguous" && !props.run ? (
    <fieldset className="repository-intent-selector"><legend>이 폴더에서 어떻게 시작할까요?</legend><label data-selected={props.repositoryIntent === "existing_structure"}><input type="radio" name="repository-intent" checked={props.repositoryIntent === "existing_structure"} disabled={busy} onChange={() => props.onRepositoryIntentChange("existing_structure")} /><span><strong>현재 코드로 계속</strong><small>폴더의 코드와 설정을 유지합니다.</small></span></label><label data-selected={props.repositoryIntent === "new_project"}><input type="radio" name="repository-intent" checked={props.repositoryIntent === "new_project"} disabled={busy} onChange={() => props.onRepositoryIntentChange("new_project")} /><span><strong>기본 구조부터 만들기</strong><small>기존 파일을 보존하고 사용할 기술부터 정합니다.</small></span></label></fieldset>
  ) : null;
  const maturityPanel = maturity ? (
    <details className="planning-inspection-details" aria-label="프로젝트 구성 확인"><summary>확인한 내용</summary>
      <p>{maturityTitle} · {maturityDetail}</p><div className="repository-maturity__evidence"><span>앱이 확인한 파일 {maturity.inspected_file_count.toLocaleString("ko-KR")}개</span>{evidenceGroups.map((group) => <section key={group.label}><strong>{group.label} · {group.count}개</strong>{group.notes.map((note) => <span key={note}>{note}</span>)}{group.paths.length ? <ul>{group.paths.map((path) => <li key={path}><code>{path}</code></li>)}</ul> : null}</section>)}</div>
    </details>
  ) : null;
  const planningActivity = planningActive ? <section className="planning-chat-activity" data-failed={progressFailed || undefined}
    data-repair-active={repairActive || undefined}
    data-inline={props.chatFirst || undefined} aria-label={props.chatFirst ? "기획 AI 응답 상태" : undefined}
    data-central-progress={guided && props.bodyVisible && !repairActive ? true : undefined} role={progressFailed ? "alert" : "status"}>
    <div className="planning-chat-activity__summary">
      {progressFailed ? <AlertCircle aria-hidden="true" size={14} /> : <RefreshCw aria-hidden="true" className="spin" size={14} />}
      <strong>{progressTitle}</strong>
      {!progressFailed && repairActive ? <span>{formatDuration(repairElapsed)}</span>
        : !progressFailed && !providerWaiting && retryLabel ? <span>다시 시도 {progressContext.retryIndex}회째</span> : null}
    </div>
    <details><summary>진행 상세</summary><p>{activeAgentLabel} · {
      repairActive ? formatDuration(repairElapsed) : ["runs.start", "runs.sendPlanningMessage"].includes(props.busyAction)
        ? activeElapsed : `상태 갱신 ${activeElapsed}`
    }</p>{!progressFailed && !providerWaiting ? <p>{progressMessage}</p> : null}</details>
    {progressFailed ? <p>{progressMessage}</p> : null}
  </section> : null;
  const planningDecisions = <>
      {props.run?.stage === "reviewed" ? <section className="revision-planning-ready" role="status"><div><strong>{props.run.revision_source_run_id ? "후속 작업 기획 초안이 저장됐습니다" : "이 그룹의 기획 준비가 저장됐습니다"}</strong><p>원본 결과는 보존됩니다. 기획을 시작하면 AI가 요청을 검토하며, 실행과 Main 반영은 별도 단계입니다.</p></div><button className="button button--primary" type="button" disabled={busy} onClick={props.onRunPreparedRevision}>{props.busyAction === "runs.runPlanning" ? "기획 중…" : props.run.revision_source_run_id ? "후속 기획 시작" : "기획 이어 시작"}</button></section> : null}
      {guided && props.run ? <GreenfieldFlowPanel
        run={props.run} selectedOptionId={selectedTechStackOptionId}
        answer={props.message} onAnswerChange={props.onMessageChange}
        busy={busy} available={!props.run?.archive && chatAllowed && !resultDiscussion && !excludedPlanningSelection && selectedProviderReady && !props.planDirty}
        active={planningActive || Boolean(props.run.active_step && props.run.stage !== "reviewed") || props.run.tasks.some(taskIsActive)}
        elapsed={props.planningElapsed} interruptible={props.interruptible && planningActive} onInterrupt={props.onInterrupt}
        onSelect={setSelectedTechStackOptionId} onAnswer={props.onAnswerTechnology} onConfirm={props.onConfirmTechStack}
        onRetry={props.onRetryGreenfield} onStart={props.onStartGreenfield} onFeaturePlan={props.onGenerateFeaturePlan}
        bootstrapDetails={props.run.bootstrap_spec ? <BootstrapSpecPanel
          spec={props.run.bootstrap_spec} phase={props.run.greenfield_phase}
          retrying={props.busyAction === "planning.generateFeaturePlan"}
          savingInstructions={props.busyAction === "runs.configureBootstrapInstructions"}
          onSetCreateInstructions={(create) => props.onConfigureBootstrapInstructions(create, props.run?.bootstrap_spec?.decision_revision || 0, props.run?.bootstrap_spec?.digest || "")}
        /> : undefined}
      /> : null}
      {!guided && techStackDecision ? (
        <TechStackDecisionPanel
          decision={techStackDecision}
          selectedOptionId={selectedTechStackOptionId}
          busy={busy || planningActive}
                  confirming={props.busyAction === "runs.confirmTechStack"}
                  confirmationAllowed={props.run?.tech_stack_confirmation_allowed === true}
          questions={props.run?.planning_questions || []}
          answeringAllowed={!props.run?.archive && chatAllowed && !excludedPlanningSelection && !planningActive}
          onSelect={setSelectedTechStackOptionId}
          onConfirm={() => props.onConfirmTechStack(selectedTechStackOptionId, techStackDecision.revision)}
          onAnswerQuestions={() => {
            if (busy || planningActive || !chatAllowed || excludedPlanningSelection) return;
            followsLatestRef.current = false;
                    if (planningMessageInputRef.current) scrollPlanningContentIntoView(planningMessageInputRef.current, "center");
            planningMessageInputRef.current?.focus({ preventScroll: true });
          }}
        />
      ) : null}
      {!guided && props.run?.bootstrap_spec ? (
        <BootstrapSpecPanel
          spec={props.run.bootstrap_spec}
          phase={props.run.greenfield_phase}
          retrying={props.busyAction === "planning.generateFeaturePlan"}
          savingInstructions={props.busyAction === "runs.configureBootstrapInstructions"}
          onSetCreateInstructions={(create) => props.onConfigureBootstrapInstructions(
            create,
            props.run?.bootstrap_spec?.decision_revision || 0,
            props.run?.bootstrap_spec?.digest || "",
          )}
          onRetry={props.onGenerateFeaturePlan}
        />
      ) : null}
  </>;
  const chatModel = <div className="chat-model-controls">
    <label><span className="sr-only">대화 AI 모델</span><select value={props.selectedProfileKey} disabled={busy || !props.profiles.length}
      onChange={event => props.onProfileChange(event.target.value)}>
      {!selectedProfile ? <option value={props.selectedProfileKey} disabled>{props.profiles.length ? "모델 선택" : "연결된 AI 없음"}</option> : null}
      {props.profiles.map(profile => <option key={providerProfileKey(profile)} value={providerProfileKey(profile)}>{providerProfileLabel(profile)}</option>)}
    </select></label>
    <details className="chat-model-settings" data-dismiss-on-outside onToggle={event => {
      if (event.currentTarget.open) setTaskSettingsMounted(true);
    }}><summary aria-label="대화·작업 설정"><Settings aria-hidden="true" size={15} /></summary>
      <div className="chat-model-settings__panel">
      <label className="field"><span>추론 강도</span><select value={props.reasoning} disabled={busy}
        onChange={event => props.onReasoningChange(event.target.value)}><option value="">{providerDefaultReasoningLabel(selectedProviderId)}</option>
        {props.reasoningOptions.map(effort => <option key={effort} value={effort}>{effort}</option>)}</select></label>
      <button className="button button--quiet" type="button" data-dismiss-menu-action onClick={props.onOpenCodexAuth}>AI 연결 관리</button>
      <button className="button button--quiet" type="button" data-dismiss-menu-action onClick={() => {
        if (props.run) props.onOpenPlanningSettings?.(); else setStartDialogOpen(true);
      }}>{props.run ? "기획 설정 보기" : "기획·자료 설정"}</button>
      {taskSettingsMounted ? props.taskSettings : null}
      </div>
    </details>
  </div>;
  const chat = (
      <section className="planning-chat" aria-label="기획 AI 대화">
        {!props.chatFirst && (props.run || selectedProviderReady) ? <AiBadge title="기획 AI" provider={props.run?.planning_provider_id || selectedProviderId || ""}
          requestedModel={props.run?.planning_model || selectedProfile?.model} requestedReasoning={props.run?.planning_reasoning_effort || props.reasoning}
          planned={!props.run} usageKnown={Boolean(props.usageSnapshot)} usageError={props.usageError}
          purposes={props.usageSnapshot?.by_purpose.filter((group) => ["planning", "chat"].includes(group.key))} /> : null}
        {excludedPlanningSelection ? <p className="provider-selection-warning" role="alert">저장한 대화 모델을 사용할 수 없습니다. 연결 상태를 확인하고 모델을 다시 선택해 주세요.</p> : null}
        {repairActive && !props.chatFirst ? planningActivity : null}
        <div
          ref={messagesRef}
          className="planning-messages"
          onScroll={(event) => {
            const pane = event.currentTarget; followsLatestRef.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 48;
            if (props.scrollMemory) props.scrollMemory.current[messageScope] = { top: pane.scrollTop, followsLatest: followsLatestRef.current };
          }}
          aria-live="polite"
        >
          {props.chatFirst && props.contextPanel ? <details className="chat-context-details"><summary>변경 예약·복구 자료</summary>{props.contextPanel}</details> : props.contextPanel}
          {props.run?.planning_messages.map((item, index) => {
            const key = planningMessageKey(props.project?.name || "", props.run?.id || "", item, index);
            return <article key={key} className={`chat-message chat-message--${item.role}`}
              data-attention-question={index === lastQuestionMessage ? true : undefined} tabIndex={index === lastQuestionMessage ? -1 : undefined}>
              <span>{item.role === "user" ? "나" : "기획 AI"}</span>
              {messageBody(item.text, key, localizePlanningText(item.role === "user" ? taskPlanningQuestionBody(item.text) : item.text), `${item.role === "user" ? "나" : "기획 AI"} · ${formatDate(item.at)}`)}<time>{formatDate(item.at)}</time>
              {inlinePlanningApply && index === lastAssistantMessage ? <div className="chat-message__actions">
                <button className="button button--secondary" type="button" disabled={inlineApplyDisabled}
                  title={conversationApplied ? "이 대화는 작업에 반영됐습니다." : inlineApplyBlockedByExecution
                    ? "현재 작업이 끝나면 반영할 수 있습니다." : "대화한 내용의 변경안을 확인합니다. 입력 중인 내용은 먼저 전송하세요."}
                  onClick={() => { if (!inlineApplyDisabled) props.onApply(); }}>{inlineApplyLabel}</button>
              </div> : null}
            </article>;
          })}
          {visiblePendingMessage ? <article className="chat-message chat-message--user chat-message--pending">
            <span>나 · {visiblePendingMessage.status === "sending" ? "전송됨" : "전송 상태 확인 필요"}</span>
            {messageBody(visiblePendingMessage.text, planningMessageKey(props.project?.name || "", props.run?.id || "",
              { role: "user", at: `pending:${visiblePendingMessage.at}` }, visiblePendingMessage.previousMessageCount), localizePlanningText(taskPlanningQuestionBody(visiblePendingMessage.text)), `나 · ${formatDate(visiblePendingMessage.at)}`)}
            <time>{formatDate(visiblePendingMessage.at)}</time>
          </article> : null}
          {!props.run?.planning_messages.length ? props.run?.planning_questions.map((question, index) => {
            const key = planningMessageKey(props.project?.name || "", props.run?.id || "", { role: "assistant", at: `question:${question}` }, index);
            const focusableQuestion = props.run?.stage === "needs_clarification" && index === 0;
            return <article key={key} className="chat-message chat-message--assistant"
              data-central-question={centralQuestions && props.bodyVisible ? true : undefined}
              data-attention-question={focusableQuestion ? true : undefined} tabIndex={focusableQuestion ? -1 : undefined}>
              <span>기획 AI 질문</span>{messageBody(question, key)}
            </article>;
          }) : null}
          {showApplyReceipt ? <div className="planning-follow-up" data-status={latestApply?.status || "queued"}
            role={latestApply?.status === "failed" ? "alert" : "status"}>
            <div className="planning-follow-up__summary">
              {latestApply?.status === "succeeded" ? <CheckCircle2 aria-hidden="true" size={14} />
                : latestApply?.status === "failed" ? <AlertCircle aria-hidden="true" size={14} />
                  : <Clock3 aria-hidden="true" size={14} />}
              <strong>{latestApply?.status === "succeeded" ? "계획 반영 완료"
                : latestApply?.status === "failed" ? "계획 반영 실패"
                  : latestApply?.status === "applying" ? "계획 반영 중" : "계획 반영 대기"}</strong>
              {latestApply?.status === "succeeded" ? <span>{applyChangeSummary}</span> : null}
            </div>
            {latestApply?.status === "succeeded" ? <details><summary>반영 내역</summary>
              <p>추가 {latestApply.added_tasks}개 · 수정 {latestApply.updated_tasks}개 · 제외 {latestApply.excluded_tasks || 0}개 · 유지 {latestApply.unchanged_tasks}개</p>
            </details> : <p>{latestApply?.status === "failed" ? latestApply.error || "기존 작업은 보존했습니다. 실패 원인을 확인해 주세요."
              : latestApply?.status === "applying" ? "계획을 업데이트하고 있습니다."
                : followUpReviewReady ? "답변 아래에서 반영 상태를 확인하세요."
                : "현재 실행이 끝난 뒤 반영합니다."}</p>}
          </div> : null}
          {props.chatFirst ? planningDecisions : null}
          {props.executionPhase !== "thinking" && (props.executionPhase || !props.chatFirst || !planningActive && !visiblePendingMessage) ? props.workActivity : null}
          {props.chatFirst ? planningActivity : null}
          {props.chatFirst && !props.run ? <section className="planning-document-entry" aria-label="기획서로 작업 시작">
            <FolderOpen aria-hidden="true" size={24} /><h3>기획서로 Task 만들기</h3>
            <p>기획서 폴더를 선택하면 AI가 문서를 분석해 작업을 나눠줍니다.</p>
            {props.path.trim() ? <span className="planning-document-entry__source" title={props.path}><FolderKanban aria-hidden="true" size={15} />{props.path.trim().split(/[\\/]/).filter(Boolean).at(-1)}</span> : null}
            <button className="button button--primary" type="button" aria-haspopup="dialog" disabled={busy || !props.project}
              onClick={() => { props.onModeChange("auto"); setStartDialogOpen(true); }}><FolderOpen aria-hidden="true" size={16} />기획서 선택·분석</button>
            <small>직접 요청하려면 아래 채팅창에 입력하세요.</small>
          </section> : initialTasksAvailable && props.chatFirst ? <section className="planning-initial-tasks" aria-label="처음 작업 만들기">
            <div><strong>논의한 내용을 Task로 만들 수 있어요</strong><p>아직 생성된 Task가 없습니다. 작업 생성 후 실행할 내용을 확인합니다.</p></div>
            <button className="button button--primary" type="button"
              disabled={applyDisabled || planningActive || applyPending || Boolean(visiblePendingMessage) || Boolean(props.planDirty)}
              onClick={props.onApply}><ListChecks aria-hidden="true" size={16} />대화 내용으로 Task 만들기</button>
          </section> : !hasConversation ? <EmptyState icon={<MessageSquare aria-hidden="true" size={22} />} title={props.chatFirst ? "무엇을 만들거나 바꿀까요?" : "기획 대화 준비"}
            detail={props.chatFirst ? "AI와 대화하며 작업을 진행하세요. 진행 상황과 필요한 확인도 이곳에서 알려드립니다." : "계획을 시작하면 준비 과정과 기획 AI의 질문이 이곳에 이어서 표시됩니다."} /> : null}
        </div>

        {!repairActive && !props.chatFirst ? planningActivity : null}

        {props.run ? (
          <div className="chat-composer">
            {props.messageQueue?.error ? <p role="alert">{props.messageQueue.error}</p> : null}
            {props.onChangeQueued && props.onRestoreQueued ? <QueuedChatMessages items={queuedMessages}
              onChange={props.onChangeQueued} onRestore={props.onRestoreQueued} /> : null}
            {props.planningRequestError ? <details role="alert"><summary>이 대화의 답변을 받지 못했습니다</summary><pre>{props.planningRequestError}</pre></details> : null}
            <div className="chat-composer__field"><label className="chat-composer__input"><span className="sr-only">기획 AI 메시지</span>
              <textarea ref={planningMessageInputRef} value={props.message} placeholder={chatPlaceholder} rows={props.chatFirst ? 1 : 3}
                disabled={!messageAllowed || excludedPlanningSelection} onChange={(event) => props.onMessageChange(event.target.value)}
                onCompositionStart={() => { composingRef.current = true; }} onCompositionEnd={() => { composingRef.current = false; }}
                onKeyDown={(event) => { if (!composerIsComposing(composingRef.current, event.nativeEvent) && messageAllowed && !excludedPlanningSelection
                  && event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); sendMessage(); } }} />
            </label>{composerHint ? <small>{composerHint}</small> : null}</div>
            {queueMode ? <small className="chat-composer__queue-hint">답변이 끝나면 예약 순서대로 보냅니다.</small> : null}
            <div className="chat-composer__actions">
              {props.chatFirst ? chatModel : null}
              {showPlanningApply ? <button className="button button--secondary" type="button" disabled={applyDisabled}
                title={!guided ? "대화한 내용의 변경안을 확인합니다. 새로 입력한 내용은 먼저 전송하세요." : !hasUnappliedConversation
                  ? "작업에 반영할 새 기획 대화가 없습니다." : props.planDirty ? "미저장 작업 편집을 먼저 정리하세요." : undefined}
                onClick={props.onApply}>{applyLabel}</button> : null}
              {props.interruptible ? <button className="button button--danger chat-composer__send" type="button"
                title={props.interruptLabel || "기획 중단"} aria-label={props.interruptLabel || "기획 중단"}
                disabled={props.busyAction === "system.interruptPlanning"} onClick={props.onInterrupt}><XCircle aria-hidden="true" size={20} /></button> : null}
              {queueMode ? <button className="button button--secondary chat-composer__queue" type="button"
                title="답변 후 전송 예약 (Ctrl/Cmd+Enter)" disabled={!props.message.trim() || !messageAllowed || excludedPlanningSelection || props.queueSubmitting || Boolean(props.messageQueue?.error)}
                onClick={sendMessage}><Clock3 size={16} aria-hidden="true" />{props.queueSubmitting ? "예약 중…" : "예약"}</button> : !props.interruptible ?
              <button className={`button button--primary${props.chatFirst ? " chat-composer__send" : ""}`} type="button"
                title="전송 (Ctrl/Cmd+Enter)" disabled={!props.message.trim() || sendBlocked || !chatAllowed || excludedPlanningSelection} onClick={sendMessage}>
                {props.chatFirst ? props.busyAction === "runs.sendPlanningMessage" ? <RefreshCw className="spin" aria-hidden="true" size={18} />
                  : <ArrowUp aria-hidden="true" size={20} /> : <Send aria-hidden="true" size={15} />}
                <span className={props.chatFirst ? "sr-only" : undefined}>{props.busyAction === "runs.sendPlanningMessage" ? "전송 중" : "전송"}</span>
              </button> : null}
            </div>
          </div>
        ) : null}
        {props.chatFirst && !props.run ? <div className="chat-composer chat-composer--new">
          <label className="chat-composer__input"><span className="sr-only">새 작업 요청</span><textarea value={props.request}
            placeholder="무엇을 만들거나 바꾸고 싶으세요?" rows={1} disabled={busy || !props.project}
            onChange={event => { props.onModeChange("directed"); props.onRequestChange(event.target.value); }}
            onCompositionStart={() => { composingRef.current = true; }} onCompositionEnd={() => { composingRef.current = false; }}
            onKeyDown={event => { if (!composerIsComposing(composingRef.current, event.nativeEvent) && (event.ctrlKey || event.metaKey) && event.key === "Enter" && !sendBlocked && props.request.trim()) {
              event.preventDefault(); if (startReadiness.ready) props.onStart(); else setStartDialogOpen(true);
            } }} /></label>
          {props.startError ? <p role="alert">{props.startError}</p> : null}
          <div className="chat-composer__actions">{chatModel}
            <button className="button button--primary chat-composer__send" type="button" title="계획 만들기 (Ctrl/Cmd+Enter)"
              disabled={sendBlocked || !props.project || !props.request.trim()}
              onClick={() => { if (composingRef.current || sendBlocked) return; if (startReadiness.ready) props.onStart(); else setStartDialogOpen(true); }}>
              <ArrowUp aria-hidden="true" size={20} /><span className="sr-only">계획 만들기</span></button></div>
        </div> : null}
      </section>
  );
  return (
    <div
      ref={workbenchRef}
      className="planning-workbench"
      onScroll={(event) => {
        const target = event.currentTarget;
        followsLatestRef.current = (
          target.scrollHeight - target.scrollTop - target.clientHeight < 48
        );
      }}
    >
      <header className="run-header compact-header">
        <div><h2 id="planning-workbench-title" tabIndex={-1}>{props.run ? runDisplayName(props.run.summary, props.run.id, "기획 대화") : "새 작업 기획"}</h2>{!props.project ? <p>프로젝트를 먼저 등록하세요.</p> : null}</div>
      </header>
      <PlanningPolicySummary control={props.run?.effort_control} />

      {!props.run ? <section className="planning-intro" aria-label="새 기획 준비">
        <p role="status">{preparing ? progressMessage : !props.capabilities ? "프로젝트 구성을 확인하고 있습니다." : maturityTitle}</p>
        {maturity?.kind === "ambiguous" && !props.repositoryIntent ? <p role="status">기획 시작에서 현재 코드를 사용할지 기본 구조부터 만들지 선택해 주세요.</p> : null}
        {!selectedProviderReady && props.capabilities ? <p role="status">기획 시작에서 AI 모델과 인증 상태를 확인해 주세요.</p> : null}
        {props.startError ? <p role="alert">{props.startError}</p> : null}
        <button className="button button--primary" type="button" aria-haspopup="dialog" onClick={() => setStartDialogOpen(true)}>기획 시작</button>
      </section> : null}
      {maturityPanel}
      {!props.chatFirst ? planningDecisions : null}
      {props.run ? <section className="planning-setup planning-setup--summary" aria-label="기획 설정">
        {props.run ? (
          <details className="planning-settings-summary">
            <summary>
              <span><strong>시작 설정</strong><small>{props.mode === "directed" ? "지정 작업" : "풀 오토 탐색"} · {sourceSummary} · {profileSummary}</small></span>
              <ChevronDown aria-hidden="true" size={16} />
            </summary>
            <div className="planning-settings-summary__body">
              <p className="planning-code-style-summary"><strong>코드 스타일</strong><span>{codeStyleSnapshotSummary(props.run.code_style_snapshot)}</span></p>
              <div className="planning-scope-summary" data-expanded={requestExpanded}>
                <div className="planning-scope-summary__heading">
                  <span>{props.mode === "directed" ? "처음 요청" : "탐색 기준"}</span>
                  {requestIsLong ? <button className="button button--quiet planning-scope-summary__toggle" type="button" aria-controls="planning-request-summary" aria-expanded={requestExpanded} onClick={() => setRequestExpanded((current) => !current)}><ChevronDown aria-hidden="true" size={14} />{requestExpanded ? "요청 접기" : "요청 전문 보기"}</button> : null}
                </div>
                {props.request ? <p id="planning-request-summary" className="planning-scope-summary__request">{props.request}</p> : <p>기획문서에서 실행 가능한 다음 작업을 탐색합니다.</p>}
              </div>
            </div>
          </details>
        ) : null}
        {props.interruptible && !guided ? <div className="planning-setup__footer"><button className="button button--danger planning-start" type="button" disabled={props.busyAction === "system.interruptPlanning"} onClick={props.onInterrupt}><XCircle aria-hidden="true" size={16} />{props.busyAction === "system.interruptPlanning" ? "중단 중…" : props.interruptLabel || "기획 중단"}</button></div> : null}
      </section> : null}
      {!props.run && startDialogOpen ? <WorkDialog portal title="작업 기획하기" context={props.project?.name} className="planning-start-dialog" suspendPlanning
        onClose={() => setStartDialogOpen(false)} footer={startAction}>
          {repositoryChoice}
            <div className="planning-setup__section planning-scope planning-scope--primary">
              <div className="planning-setup__heading"><div><h3>어떻게 계획할까요?</h3><p>요청한 작업에 집중하거나 기획 자료에서 다음 일을 찾습니다.</p></div></div>
              <fieldset className="planning-scope-selector">
                <legend className="sr-only">계획 방식</legend>
                <label data-selected={props.mode === "directed"}>
                  <input type="radio" name="planning-mode" value="directed" checked={props.mode === "directed"} disabled={busy} onChange={() => props.onModeChange("directed")} />
                  <span><strong>직접 요청하기</strong><small>만들거나 바꿀 내용을 입력합니다.</small></span>
                </label>
                <label data-selected={props.mode === "auto"}>
                  <input type="radio" name="planning-mode" value="auto" checked={props.mode === "auto"} disabled={busy} onChange={() => props.onModeChange("auto")} />
                  <span><strong>기획서에서 할 일 찾기</strong><small>자료에서 다음 미완료 작업을 찾습니다.</small></span>
                </label>
              </fieldset>
              {props.mode === "directed" ? <label className="field planning-request planning-request--primary"><span>무엇을 만들거나 바꿀까요?</span><textarea value={props.request} rows={4} autoFocus placeholder={maturity?.kind === "docs_only" ? "예: Windows에서 쓸 메모 앱을 만들고 싶어. C#/.NET을 선호해." : "예: 작업 삭제할 때 발생하는 오류를 수정해줘."} disabled={busy} onChange={(event) => props.onRequestChange(event.target.value)} /></label> : null}
            </div>
            {props.mode === "auto" ? <div className="planning-setup__section planning-source planning-source--required"><h3>확인할 기획 자료</h3>{sourceSettings}</div> : (
              <details className="planning-setup__details planning-source-details">
                <summary><span><strong>기획 자료 추가 · 선택 사항</strong><small>{props.path.trim().split(/[\\/]/).filter(Boolean).at(-1) || "요청과 현재 코드를 기준으로 계획합니다."}</small></span><ChevronDown aria-hidden="true" size={16} /></summary>
                <div className="planning-setup__details-body">{sourceSettings}</div>
              </details>
            )}
            <details className="planning-setup__details planning-profile-details" open={!props.profiles.length || !selectedProviderReady}>
              <summary><span><strong>AI 설정 · 변경</strong><small>설정 {profileSummary} · 작업 강도 {effortModeLabels[props.effortMode]}{selectedProviderStatus ? ` · ${selectedProviderStatus.available ? "인증 확인됨" : "인증 확인 필요"}` : ""}</small></span><ChevronDown aria-hidden="true" size={16} /></summary>
              <div className="planning-setup__details-body">{profileSettings}<PlanningEffortPicker mode={props.effortMode} manual={props.profileManual} disabled={busy} onChange={props.onEffortModeChange} /></div>
            </details>
      </WorkDialog> : null}
      {props.chatTarget ? createPortal(chat, props.chatTarget) : chat}
      {fullMessage && fullMessagePresent ? <PlanningMessageDialog key={fullMessage.key} message={fullMessage} onClose={() => setFullMessage(undefined)} /> : null}
    </div>
  );
}

interface TaskWorkbenchProps {
  cardsOnly?: boolean;
  planningTaskIds?: string[];
  usageSnapshot?: UsageSnapshot;
  usageError?: string;
  run?: RunState;
  analysisTasks?: WorkTask[];
  selectedTaskId: string;
  selectedTaskIds: string[];
  planDirty: boolean;
  nextAction?: ReactNode;
  preparationAction?: RunNextAction;
  preparationBlocked?: boolean;
  onPreparationAction(action: RunNextAction): void;
  onDiscuss(): void;
  usage?: ReactNode;
  effortControls?: ReactNode;
  draftConflict: boolean;
  draftErrorCount: number;
  busyAction: string;
  executionAction: string;
  profileOptions: Record<string, ProviderProfile[]>;
  profiles: Record<string, TaskProfileSelection>;
  onSelectTask(taskId: string): void;
  onOpenTaskLog(taskId: string): void;
  onRepairTask(taskId: string): void;
  onToggleTask(taskId: string): void;
  onProfileChange(taskId: string, selection: TaskProfileSelection): void;
  onRunAction(method: RpcMethod, taskId?: string): Promise<void>;
  onStop(task: WorkTask): void;
  onExclude(): void;
  onAddTask(): void;
  onResetPlan(): void;
  onSavePlan(): void;
  onOpenConflictRecovery(taskId: string): void;
  onRecovery(): void;
  onBack(): void;
}

function TaskWorkbench({ cardsOnly = false, run, analysisTasks, selectedTaskId, selectedTaskIds, planningTaskIds, planDirty, nextAction, preparationAction, preparationBlocked = false, onPreparationAction, onDiscuss, usage, usageSnapshot, usageError, effortControls, draftConflict, draftErrorCount, busyAction, executionAction, profileOptions, profiles, onSelectTask, onOpenTaskLog, onRepairTask, onToggleTask, onProfileChange, onRunAction, onStop, onExclude, onAddTask, onResetPlan, onSavePlan, onOpenConflictRecovery, onRecovery, onBack }: TaskWorkbenchProps) {
  if (!run) return <div className="task-workbench--empty"><EmptyState icon={<ListChecks aria-hidden="true" size={24} />} title="작업 그룹을 선택하세요" detail="분해된 작업과 실행 순서, 모델 추천을 이곳에서 확인합니다." /></div>;
  const busy = Boolean(busyAction || executionAction);
  const planApproved = planIsApproved(run);
  const planEditable = run.stage === "planned";
  const effortReviewRequired = Boolean(run.effort_control?.requires_plan_review);
  const excludedProfileTaskIds = run.tasks.filter((task) => (
    taskProfileRequiresReselection(task, profiles[task.id], profileOptions[task.id] || [])
  )).map((task) => task.id);
  const executionAllowed = !planEditable || (planApproved && !planDirty && !draftErrorCount && !excludedProfileTaskIds.length && !effortReviewRequired);
  const planConfirmationRequired = planEditable && !executionAllowed;
  const execution = runExecutionPresentation(run, executionAction);
  const taskActionsAllowed = pendingTaskActionIsAllowed(execution.primaryMethod, run.stage);
  const taskRetryAllowed = taskRetryIsAllowed(execution.primaryMethod, run.failed_step);
  const completedCount = run.tasks.filter((task) => ["completed", "merged"].includes(task.status)).length;
  const failedCount = run.tasks.filter((task) => task.status === "failed").length;
  const showExecutionOverview = !executionOnTaskCards(run) && (monitorTasks(run).length > 0 || Boolean(run.active_step) || run.stage === "failed"
    || ["preparing", "running", "resumable", "status_unknown", "attention_required"].includes(run.execution_control?.situation || "")
    || ["main_apply_recoverable", "main_apply_interrupted"].includes(run.integration_control?.reason_code || ""));
  const commonProviders = [...new Set((profileOptions[run.tasks[0]?.id] || []).map((option) => option.provider_id))]
    .filter((provider) => run.tasks.every((task) => (profileOptions[task.id] || []).some((option) => option.provider_id === provider)));
  const changedProfileCount = run.tasks.filter((task) => {
    const selection = profiles[task.id] || { agentId: task.agent_id, model: task.model, reasoningEffort: task.reasoning_effort };
    return selection.agentId !== task.agent_id
      || selection.model !== task.model
      || selection.reasoningEffort !== task.reasoning_effort;
  }).length;
  const applyProviderToAll = (provider: string) => {
    if (!planEditable || busy || !commonProviders.includes(provider)) return;
    for (const task of run.tasks) {
      const options = (profileOptions[task.id] || []).filter((option) => option.provider_id === provider);
      const current = profiles[task.id];
      const option = options.find((item) => item.agent_id === current?.agentId && item.model === current.model)
        || options.find((item) => Boolean(item.model) && item.model === item.configured_model)
        || options[0];
      if (option) onProfileChange(task.id, { agentId: option.agent_id, model: option.model, reasoningEffort: current?.agentId === option.agent_id && current.model === option.model ? current.reasoningEffort : "" });
    }
  };
  if (cardsOnly && planEditable && !run.archive) return <div className="task-workbench__content" data-cards-only="true">
    <RunPreparation run={run} action={preparationAction || runNextAction(run, { planDirty, pendingAction: executionAction })}
      blocked={preparationBlocked} blockingAction={nextAction} busy={busy} planDirty={planDirty}
      draftConflict={draftConflict} draftErrorCount={draftErrorCount} invalidTaskIds={excludedProfileTaskIds}
      onAction={onPreparationAction} onReset={onResetPlan} onReviewErrors={onSavePlan} onOpenTask={onSelectTask} onDiscuss={onDiscuss}
      profileSummary={(task) => {
        const selection = profiles[task.id];
        const option = (profileOptions[task.id] || []).find(item => item.agent_id === selection?.agentId && item.model === selection.model);
        return `${providerDisplayName(option?.provider_id || task.provider_id)} · ${selection ? selection.model || "자동 선택" : taskModelDisplayValue(task, task.provider_id)} · ${selection ? selection.reasoningEffort || "추론 자동" : task.reasoning_effort || "추론 자동"}`;
      }}
      profileEditor={(task) => <TaskRow profileOnly profileWarningShown task={task} sequence={run.tasks.indexOf(task) + 1} selected={false} checked={false}
        busy={busy || preparationBlocked || draftConflict} planConfirmed={false} taskActionsAllowed={false} taskRetryAllowed={false}
        profileEditable profileEditorOpen options={profileOptions[task.id] || []}
        profile={profiles[task.id] || { agentId: task.agent_id, model: task.model, reasoningEffort: task.reasoning_effort }}
        onProfileChange={(selection) => onProfileChange(task.id, selection)} onSelect={() => onSelectTask(task.id)}
        onToggle={() => onToggleTask(task.id)} onToggleProfileEditor={() => {}} onAction={() => {}}
        onStop={() => {}} onOpenLog={() => onOpenTaskLog(task.id)} onRepair={() => onRepairTask(task.id)} />}
      settings={<>
        <div className="task-profile-toolbar"><label className="field"><span>전체 작업 AI 제공자 변경</span>
          <select value="" disabled={busy || preparationBlocked || draftConflict || !commonProviders.length} onChange={(event) => applyProviderToAll(event.target.value)}>
            <option value="">AI 제공자 선택</option>{commonProviders.map(provider => <option key={provider} value={provider}>{providerDisplayName(provider)}</option>)}
          </select><small>변경 내용을 저장하고 계획을 다시 확정해야 실행에 반영됩니다.</small></label></div>
        {effortControls}
        <details className="work-group-settings"><summary>직접 계획 편집</summary>
          <button className="button button--quiet" type="button" disabled={busy || preparationBlocked || draftConflict} onClick={onAddTask}><Plus size={15} aria-hidden="true" />작업 추가</button>
          {run.tasks.map(task => <label className="run-preparation__exclude" key={task.id}><input type="checkbox" checked={selectedTaskIds.includes(task.id)}
            disabled={task.status !== "pending" || busy || preparationBlocked || planDirty} onChange={() => onToggleTask(task.id)} />{task.title} 제외 대상으로 선택</label>)}
          <button className="button button--danger" type="button" disabled={!selectedTaskIds.length || busy || preparationBlocked || planDirty} onClick={onExclude}>선택한 {selectedTaskIds.length}개 제외</button>
        </details>
      </>} />
  </div>;
  const savedAnalysisTasks = analysisTasks || run.tasks;
  const analysisById = new Map(savedAnalysisTasks.map((task) => [task.id, task]));
  const conflictGroups = [...new Map(savedAnalysisTasks.filter((task) => task.conflict_group.length).map((task) => [task.conflict_group.join("\0"), task.conflict_group])).values()];
  const planReviewTitle = draftErrorCount ? "계획 입력 확인 필요" : effortReviewRequired && !planDirty
    ? "작업 강도 반영 필요"
    : executionAllowed
    ? "계획 확정 완료"
    : planDirty
      ? "변경 내용 재확정 필요"
      : "다음 단계 · 계획 확정 필요";
  const planReviewDescription = draftErrorCount ? `입력 오류 ${draftErrorCount}건이 있습니다. 변경 저장을 눌러 해당 작업과 입력란을 확인하세요.` : effortReviewRequired && !planDirty
    ? "‘AI 설정·작업 강도’의 작업 강도에서 변경 비교를 확인하고 계획에 반영한 뒤 다시 확정하세요."
    : executionAllowed
    ? `revision ${run.plan_revision || "legacy"} · 준비된 작업 실행 버튼이 활성화되었습니다.`
    : excludedProfileTaskIds.length
      ? `사용할 수 없는 모델이 지정된 작업 ${excludedProfileTaskIds.length}개의 실행 모델을 다시 선택하고 변경을 저장해 주세요.`
    : planDirty
      ? "수정한 내용을 확인한 뒤 상단의 ‘변경 저장하고 계획 확정’을 누르세요. 저장과 확정이 이어서 처리됩니다."
      : "작업 내용과 실행 프로필을 확인한 뒤 상단의 ‘계획 확정’을 눌러야 실행할 수 있습니다.";
  return (
    <div className="task-workbench__content" data-cards-only={cardsOnly || undefined}>
      {cardsOnly ? nextAction : <div className="work-group-intro">
      <header className="run-header">
        <div className="run-header__backline"><button className="back-button" type="button" aria-label="전체 현황으로" onClick={onBack}><ChevronLeft aria-hidden="true" size={16} />내 프로젝트</button>{!nextAction ? <span className={`stage-label stage-label--${planConfirmationRequired ? stageTone(run.stage) : execution.tone}`}>{planConfirmationRequired ? stageLabels[run.stage] || run.stage : execution.statusLabel}</span> : null}</div>
        <div className="run-header__title"><h2 id="tasks-workbench-title" tabIndex={-1}>{runDisplayName(run.summary, run.id)}</h2>
          <p className="work-group-progress">완료 {completedCount}/{run.tasks.length}{failedCount ? ` · 실패 ${failedCount}` : ""}</p>
        </div>
        {run.stage === "failed" && run.workspace_mode === "shared" ? <div className="run-header__operations"><div className="run-header__operation-copy"><span>복구 작업</span><strong>실패 기록과 완료 결과를 보존한 채 복구안을 확인합니다.</strong></div><div className="run-actions"><button className="button button--secondary" disabled={busy || !runRecoveryAllowed(run)} onClick={onRecovery}>복구안 확인</button></div></div> : null}
      </header>
      {nextAction}
      </div>}
      {showExecutionOverview && !nextAction ? <ExecutionOverview run={run} progressText={taskProgressText} onOpenLog={onOpenTaskLog} onStop={onStop} /> : null}
      {run.recovery_tasks?.length ? <p className="recovery-task-progress">구현 작업 집계는 그대로 유지됩니다 · 복구 작업 {run.recovery_tasks.length}개</p> : null}
      {planDirty ? <div className="plan-review-state" role="status">
        <div><strong>미저장 변경 있음{draftErrorCount ? ` · 입력 오류 ${draftErrorCount}개` : ""}</strong>
          <span>{draftConflict ? "저장된 계획이 변경되었습니다. 초안을 보존했으며 덮어쓰기를 막았습니다. 내용을 검토·복사한 뒤 ‘변경 취소’로 최신 계획을 불러오세요."
            : !planEditable ? "실행 단계가 변경되어 저장할 수 없습니다. 작성한 내용은 보존됩니다."
            : "저장하거나 취소하면 다음 작업을 진행할 수 있습니다."}</span>
        </div>
        <div className="plan-review-actions">
          {draftErrorCount ? <button className="button button--quiet" type="button" disabled={busy} onClick={onSavePlan}>입력 오류 확인</button> : null}
          <button className="button button--quiet" type="button" disabled={busy} onClick={onResetPlan}>변경 취소</button>
          {planEditable ? <button className="button button--secondary" type="button" disabled={busy || draftConflict} onClick={onSavePlan}>{busyAction === "runs.updatePlan" ? "저장 중" : "변경 저장"}</button> : null}
        </div>
      </div> : null}
      {planEditable && !planDirty && (!nextAction || excludedProfileTaskIds.length) ? <div className={`plan-review-state plan-review-state--${executionAllowed ? "approved" : "pending"}`}><div><strong>{planReviewTitle}</strong><span>{planReviewDescription}</span></div></div> : null}
      {planEditable ? <details className="work-group-settings"><summary>여러 작업의 AI 설정 변경</summary><div className="task-profile-toolbar">
        <label className="field"><span>전체 작업 AI 제공자 변경</span><select value="" disabled={busy || !commonProviders.length} onChange={(event) => applyProviderToAll(event.target.value)}><option value="">AI 제공자를 선택해 모든 작업에 적용</option>{commonProviders.map((provider) => <option key={provider} value={provider}>{providerDisplayName(provider)}</option>)}</select><small>모든 작업이 지원하는 AI 제공자만 표시합니다. 모델과 추론은 각 작업에서 이어서 조정하세요.</small></label>
        <div className="task-profile-toolbar__comparison"><span>개별 실행 설정은 작업 카드를 눌러 확인하세요.</span><span>{changedProfileCount ? `사용자 변경 ${changedProfileCount}개 · 저장 후 재확정 필요` : "기획 AI 추천값과 현재 선택을 비교합니다."}</span></div>
      </div></details> : null}
      {excludedProfileTaskIds.length ? <p className="provider-selection-warning" role="alert">저장한 실행 모델을 사용할 수 없습니다. 표시된 작업의 연결과 모델을 확인해 주세요.</p> : null}
      {!cardsOnly || planEditable ? <div className="task-section-heading"><h3>작업 순서</h3><div className="task-bulk-actions">{(readyCount(run.tasks) > 0 || planEditable) && (executionAllowed || !nextAction) ? <span data-blocked={!executionAllowed}>{executionAllowed ? `${readyCount(run.tasks)}개 실행 가능` : planDirty ? "변경 저장·계획 확정 후 실행" : "계획 확정 후 실행 가능"}</span> : null}{planEditable ? <button className="button button--danger" type="button" disabled={!selectedTaskIds.length || busy || planDirty} onClick={onExclude}><X aria-hidden="true" size={15} />{selectedTaskIds.length ? `선택한 ${selectedTaskIds.length}개 제외` : "선택 제외"}</button> : null}</div></div> : null}
      <TaskFlow run={run} selectedTaskId={selectedTaskId} onOpen={onSelectTask} onStop={onStop} onRetry={(taskId) => void onRunAction("tasks.retry", taskId)}
        activity={(task) => taskActivityTiming(task, Date.now()).hasCurrentProgress ? taskProgressPhase(task) : ""}
        onPlanning={onRepairTask} onToggle={planEditable ? onToggleTask : undefined} selectedTaskIds={selectedTaskIds}
        planningTaskIds={planningTaskIds} busy={busy || planDirty} retryAllowed={taskRetryAllowed && !planDirty} usage={usageSnapshot} usageError={usageError} />
      <div className="task-list">
        {(run.recovery_tasks || []).map((task) => <RecoveryTaskRow key={task.id} task={task} run={run} onOpen={() => onOpenConflictRecovery(task.id)} />)}
      </div>
      <div className="work-group-support">
        {planEditable ? <details className="work-group-settings"><summary>직접 계획 편집</summary>
          <button className="button button--quiet" type="button" disabled={busy} onClick={onAddTask}><Plus aria-hidden="true" size={15} />작업 추가</button>
        </details> : null}
        {!cardsOnly || planEditable ? <details className="work-group-settings"><summary>AI 설정·작업 강도</summary>{effortControls}</details> : null}
        {!cardsOnly ? <details className="work-group-settings"><summary>기술 기록</summary>
          <dl className="detail-list"><Detail label="작업 그룹 ID" value={run.id} mono /><Detail label="기준 commit" value={run.base_commit || "기록 없음"} mono /><Detail label="원본 브랜치" value={run.main_branch} mono /></dl>
          {run.execution_control?.reason ? <p>{run.execution_control.reason}</p> : null}
          {run.failure_message ? <pre>{run.failure_message}</pre> : null}
          {conflictGroups.length ? <section className="task-path-overlap" aria-label="같은 파일을 수정할 수 있는 작업">
            <h3>같은 파일을 수정할 수 있는 작업</h3>
            <p>같은 파일을 수정할 가능성이 있어 실행 순서에 반영한 참고 정보입니다.</p>
            {planDirty ? <p>저장된 계획의 분석입니다. 변경 저장 후 다시 계산됩니다.</p> : null}
            <ul>{conflictGroups.map((group, index) => <li key={group.join("\0")}>
              <strong>작업 묶음 {index + 1}</strong>
              <ul>{group.map((id) => <li key={id}>{analysisById.has(id) ? analysisById.get(id)?.title || "제목 없는 작업" : "작업 정보를 확인할 수 없습니다"}</li>)}</ul>
              <details><summary>작업 식별 정보</summary><ul>{group.map((id) => <li key={id}><code>{id}</code></li>)}</ul></details>
            </li>)}</ul>
          </section> : null}
        </details> : null}
        {!cardsOnly ? usage : null}
      </div>
    </div>
  );
}

interface TaskRowProps {
  profileOnly?: boolean;
  profileWarningShown?: boolean;
  task: WorkTask;
  sequence: number;
  selected: boolean;
  checked: boolean;
  busy: boolean;
  planConfirmed: boolean;
  taskActionsAllowed: boolean;
  taskRetryAllowed: boolean;
  executionControl?: RunExecutionControl;
  profileEditable: boolean;
  profileEditorOpen: boolean;
  options: ProviderProfile[];
  profile: TaskProfileSelection;
  onSelect(): void;
  onToggle(): void;
  onToggleProfileEditor(): void;
  onProfileChange(selection: TaskProfileSelection): void;
  onAction(method: RpcMethod): void;
  onStop(): void;
  onOpenLog(): void;
  onRepair(): void;
}

function TaskRow({ profileOnly = false, profileWarningShown = false, task, sequence, selected, checked, busy, planConfirmed, taskActionsAllowed, taskRetryAllowed, executionControl, profileEditable: planEditable, profileEditorOpen, options, profile, onSelect, onToggle, onToggleProfileEditor, onProfileChange, onAction, onStop, onOpenLog, onRepair }: TaskRowProps) {
  const canRun = taskActionsAllowed && task.readiness === "ready" && task.status === "pending";
  const canRetry = taskRetryAllowed && task.status === "failed";
  const canComplete = taskActionsAllowed && task.status === "waiting";
  const blockedFailureAction = blockedTaskFailureAction(task.status, taskRetryAllowed);
  const actionMethod: RpcMethod = canRetry ? "tasks.retry" : canComplete ? "tasks.complete" : "tasks.execute";
  const selectedProfile = options.find((option) => option.agent_id === profile.agentId && option.model === profile.model);
  const excludedSelection = taskProfileRequiresReselection(task, profile, options);
  const profileEditable = planEditable && task.status === "pending" && !busy;
  const profileCanBeEdited = planEditable && task.status === "pending";
  const comparison = taskProfileComparison(
    task,
    profile,
    providerDisplayName(selectedProfile?.provider_id || task.provider_id),
    providerDisplayName(task.provider_id),
  );
  const executionSituation = executionControl?.situation;
  const hold = taskQueueHold(task, planConfirmed, taskActionsAllowed, executionSituation);
  const waitingForPlanConfirmation = hold === "plan_confirmation";
  const storedActiveTask = taskIsActive(task);
  const activeTask = storedActiveTask && (executionSituation === "running" || executionSituation === "preparing");
  const stoppingTask = activeTask && executionControl?.stop_phase === "stopping"
    && executionControl.active_task_id === task.id;
  const canStop = activeTask && executionControl?.can_stop === true && Boolean(executionControl.execution_id);
  const interruptedTask = storedActiveTask && executionSituation === "resumable";
  const liveProgress = taskProgressText(task);
  const progressPhase = activeTask ? taskProgressPhase(task) : "";
  const stopGuidanceId = `task-stop-guidance-${task.id}`;
  const pointerIntent = useRef<{ x: number; y: number; dragged: boolean } | undefined>(undefined);
  const handlePointerDown = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    pointerIntent.current = { x: event.clientX, y: event.clientY, dragged: false };
  };
  const handlePointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const intent = pointerIntent.current;
    if (!intent || intent.dragged) return;
    if (Math.hypot(event.clientX - intent.x, event.clientY - intent.y) >= 5) intent.dragged = true;
  };
  const handleRowClick = (event: ReactMouseEvent<HTMLElement>) => {
    const target = event.target instanceof Element ? event.target : null;
    const selection = window.getSelection();
    const textSelected = Boolean(
      selection
      && !selection.isCollapsed
      && [selection.anchorNode, selection.focusNode].some((node) => node && event.currentTarget.contains(node)),
    );
    const select = shouldSelectTaskRow({
      defaultPrevented: event.defaultPrevented,
      interactiveTarget: Boolean(target?.closest(taskRowInteractiveSelector)),
      textSelected,
      pointerDragged: pointerIntent.current?.dragged || false,
    });
    pointerIntent.current = undefined;
    if (select) onSelect();
  };
  const profileControls = (profileCanBeEdited ? <div className="task-profile-controls task-profile-controls--editable" data-expanded={profileEditorOpen || profileOnly}>
        {!profileOnly ? <div className="task-profile-comparison"><span><small>{comparison.originLabel}</small><strong>{comparison.selectedSummary}</strong>{comparison.changed ? <em>추천 · {comparison.recommendedSummary}</em> : null}</span><button className="button button--quiet" type="button" aria-expanded={profileEditorOpen} aria-controls={`task-profile-editor-${task.id}`} onClick={onToggleProfileEditor}>{profileEditorOpen ? "설정 접기" : "실행 설정 편집"}</button></div> : null}
        {excludedSelection && !profileWarningShown ? <p className="task-profile-excluded" role="alert">저장한 실행 모델을 사용할 수 없습니다. 연결 상태를 확인하고 다시 선택해 주세요.</p> : null}
        {profileEditorOpen || profileOnly ? <div id={`task-profile-editor-${task.id}`} className="task-profile-editor-fields">
          <label><span className="task-profile-label">실행 모델</span><select aria-label={`${task.title} 실행 모델`} value={selectedProfile ? profileKey(profile.agentId, profile.model) : ""} disabled={!profileEditable || !options.length} onChange={(event) => { const next = options.find((option) => providerProfileKey(option) === event.target.value); if (next) onProfileChange({ agentId: next.agent_id, model: next.model, reasoningEffort: "" }); }}>{!selectedProfile && options.length ? <option value="" disabled>{excludedSelection ? "실행할 모델을 다시 선택해 주세요" : `현재 설정 · ${task.model || "모델 미지정"} · 다시 선택 필요`}</option> : null}{options.length ? options.map((option) => <option key={providerProfileKey(option)} value={providerProfileKey(option)}>{taskProfileOptionLabel(taskProviderProfileLabel(option, task, profile), option.agent_id === task.agent_id && option.model === task.model)}</option>) : <option value="">사용 가능한 모델 없음</option>}</select></label>
          <label><span className="task-profile-label">추론 강도</span><select aria-label={`${task.title} 추론 강도`} value={profile.reasoningEffort} disabled={!profileEditable} onChange={(event) => onProfileChange({ ...profile, reasoningEffort: event.target.value })}><option value="">{taskDefaultReasoningLabel(task, selectedProfile?.provider_id || task.provider_id)}</option>{(selectedProfile?.reasoning_efforts || []).map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></label>
        </div> : null}
      </div> : <div className="task-profile-controls task-profile-readonly" role="group" aria-label={`${task.title} 실행 프로필`}><span><small>모델</small><strong>{taskModelDisplayValue(task, task.provider_id)}</strong></span><span><small>추론</small><strong>{taskReasoningDisplayValue(task, task.provider_id)}</strong></span></div>);
  if (profileOnly) return <section className="work-task-model" aria-label="작업 AI 설정"><h3>실행 AI · 모델</h3>{profileControls}</section>;
  return (
    <article className="task-row" data-selected={selected} data-active={activeTask} data-stopping={stoppingTask} data-plan-editable={profileCanBeEdited} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerCancel={() => { pointerIntent.current = undefined; }} onClick={handleRowClick}>
      {planEditable ? <label className="task-check" title="제외할 작업 선택"><input type="checkbox" checked={checked} disabled={task.status !== "pending" || busy} onChange={onToggle} /><span className="sr-only">{task.title} 제외 대상으로 선택</span></label> : null}
      <button id={`task-action-${task.id}`} className="task-row__select" type="button" aria-label={`${task.title} 상세 보기`} aria-current={selected ? "true" : undefined} onClick={(event) => { event.stopPropagation(); onSelect(); }}>
        <span className="task-sequence">{String(sequence).padStart(2, "0")}</span>
        <span className="task-copy"><span className="task-copy__title"><strong>{task.title}</strong><span className={`risk-label risk-label--${task.risk_level}`}>{riskLabel(task.risk_level)}</span></span><TaskActivityLine task={task} progressText={liveProgress} activeOverride={activeTask} statusLabel={interruptedTask ? "중단됨 · 재개 필요" : undefined} /></span>
      </button>
      {profileControls}
      <span className={`task-state task-state--${taskTone(task)}`} data-plan-blocked={waitingForPlanConfirmation} title={liveProgress || undefined}>{waitingForPlanConfirmation ? <LockKeyhole aria-hidden="true" size={15} /> : interruptedTask ? <RotateCcw aria-hidden="true" size={15} /> : taskStatusIcon(task.status)}<span>{interruptedTask ? "중단됨" : taskStatusLabels[task.status] || task.status}</span><small>{waitingForPlanConfirmation ? "계획 확정 대기" : hold === "group_turn" ? "그룹 실행 순서 대기" : hold === "group_resume" ? "그룹 재개 후 실행" : interruptedTask ? "그룹 재개 필요" : progressPhase || readinessLabels[task.readiness] || task.readiness}</small></span>
      <div className="task-row__actions">
        <div className="task-row__buttons">
          <button className="button button--quiet" type="button" aria-label={`${task.title} 로그 열기`} onClick={onOpenLog}>로그</button>
          {canRetry ? <button className="button button--secondary" type="button" disabled={busy} onClick={onRepair}>AI와 수정하기</button> : null}
          {activeTask ? <button className="task-action task-action--stop" type="button" aria-label={`${task.title} 중지`} aria-describedby={stopGuidanceId} title="작업은 보존됩니다. 다음 작업은 자동으로 시작하지 않습니다." disabled={!canStop} onClick={onStop}>{stoppingTask ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <Square aria-hidden="true" size={14} />}{stoppingTask ? "중지 중" : "중지"}</button> : <button className="task-action" type="button" title={waitingForPlanConfirmation ? "먼저 계획을 확정해야 실행할 수 있습니다." : blockedFailureAction?.reason} disabled={busy || Boolean(blockedFailureAction) || (!canRun && !canRetry && !canComplete)} onClick={() => onAction(actionMethod)}>{canRetry ? <RotateCcw aria-hidden="true" size={15} /> : canComplete ? <CheckCircle2 aria-hidden="true" size={15} /> : blockedFailureAction ? <LockKeyhole aria-hidden="true" size={15} /> : <Play aria-hidden="true" size={15} />}{canRetry ? "재시도" : canComplete ? "완료" : blockedFailureAction?.label || "실행"}</button>}
        </div>
        {activeTask ? <><span className="task-stop-guidance" aria-hidden="true">중지 시 작업 보존 · 다음 작업 대기</span><span id={stopGuidanceId} className="sr-only">작업은 보존됩니다. 다음 작업은 자동으로 시작하지 않습니다.</span></> : null}
      </div>
    </article>
  );
}

function ApplySummaryEntry({ run, projectName, operationsSnapshot, busyAction, onOpen }: {
  run?: RunState; projectName: string; operationsSnapshot?: OperationsSnapshot; busyAction: string; onOpen(): void;
}) {
  return <section className="apply-summary-entry" aria-labelledby="operations-workbench-title">
    <div><h2 id="operations-workbench-title" tabIndex={-1}>{applySummaryTitle(run)}</h2>
      <p>{run ? runDisplayName(run.summary, run.id) : "작업 그룹을 선택하세요"}</p>
      <strong role="status">{applySummaryStatus(run, operationsSnapshot, projectName, busyAction)}</strong>
    </div>
    <button className="button button--primary" type="button" aria-haspopup="dialog" disabled={!run} onClick={onOpen}>{run?.archive ? "보관 기록 보기" : "반영 내용 확인"}</button>
  </section>;
}

interface OperationsWorkbenchProps {
  summaryOnly?: boolean;
  statusTarget?: HTMLElement | null;
  statusVisible?: boolean;
  checking?: boolean;
  planDirty?: boolean;
  actionError?: string;
  onApplySummary?(action: ApplySummaryAction): void;
  onInspectRunLock?(): void;
  projectName: string;
  recoveryTaskId: string;
  deployConfigured: boolean;
  run?: RunState;
  operationsSnapshot?: OperationsSnapshot;
  busyAction: string;
  executionElapsed: number;
  stopRequestPending: boolean;
  deleting: boolean;
  archiving: boolean;
  onRefresh(): void | Promise<void>;
  onVerify(): void;
  onVerifyAndRepair(): void;
  onStop(): void;
  onApprovedAction(method: ApprovedRpcMethod, extra?: Record<string, unknown>): void;
  onDeleteRun(): void;
  onArchiveRun(): void;
  onRetryArchiveCleanup(): void;
  onOpenArchiveFolder(): void | Promise<void>;
}

const evidenceStatusLabels: Record<string, string> = { running: "진행 중", succeeded: "성공", failed: "실패", interrupted: "중단", stale: "재검증 필요" };
const evidenceActionLabels: Record<string, string> = { execute: "구현", revise: "수정", review: "리뷰", verify: "검증" };

function TaskResultHistory({ task }: { task: WorkTask }) {
  if (!task.action_results.length) return null;
  return <div className="criteria-list"><h4>실행 결과 기록</h4>{task.action_results.map((result, index) => <details key={index}>
    <summary>{index + 1}. {evidenceActionLabels[result.action] || result.action} · {evidenceStatusLabels[result.status] || result.status}</summary>
    <dl className="detail-list"><Detail label="시작 시각" value={formatDate(result.started_at)} /><Detail label="기준 commit" value={result.baseline_commit || "기록 없음"} mono /><Detail label="결과 commit" value={result.result_commit || "기록 없음"} mono /><Detail label="확인한 변경 경로" value={result.changed_paths.join(", ") || "기록 없음"} mono /><Detail label="통과한 검증 명령" value={result.passed_commands.map((command) => command.join(" ")).join(" / ") || "없음"} mono />{result.code_style_evidence ? <><Detail label="실제 적용 코드 스타일" value={taskCodeStyleEvidenceSummary(result.code_style_evidence)} />{result.code_style_evidence.applicable_rules.map((rule, ruleIndex) => <Detail key={`rule-${ruleIndex}`} label={`적용 규칙 ${ruleIndex + 1}`} value={codeStyleRuleSummary(rule)} mono />)}<Detail label="코드 스타일 검사 결과" value={taskCodeStyleCheckSummary(result.code_style_evidence)} />{result.code_style_evidence.checks.map((check, checkIndex) => <Detail key={`check-${checkIndex}`} label={`스타일 검사 ${checkIndex + 1}`} value={taskCodeStyleCheckDetail(check)} mono />)}{result.code_style_evidence.rule_changes.length ? <Detail label="규칙 차이" value={result.code_style_evidence.rule_changes.join(", ")} mono /> : null}</> : null}{result.review_verdict ? <Detail label="리뷰 판정" value={result.review_verdict} /> : null}</dl>
    {result.worker_response ? <div><strong>Worker 응답 · 자체 보고</strong><p>{result.worker_response}</p></div> : null}
    {result.review_findings.length ? <ul>{result.review_findings.map((finding, i) => <li key={i}>{finding}</li>)}</ul> : null}
    {result.error ? <p role="alert">{result.error}</p> : null}
  </details>)}</div>;
}

function VerificationAttemptRecord({ attempt, index, repairLimit }: {
  attempt: RunState["verification_attempts"][number]; index: number; repairLimit: number;
}) {
  const result = attempt.stop_reason ? "stopped" : attempt.status;
  const summaries: Record<string, { label: string; text: string }> = {
    succeeded: { label: "성공", text: "이 시도의 검증을 통과했습니다." },
    failed: { label: "실패", text: "검증을 완료하지 못했습니다. 실패 내용은 상세 기록에서 확인할 수 있습니다." },
    stopped: { label: "중지됨", text: "사용자가 검증을 중지했습니다. 통과한 결과로 인정되지 않습니다." },
    interrupted: { label: "중단됨", text: "검증이 중단되어 결과를 확인하지 못했습니다." },
    stale: { label: "재검증 필요", text: "검증 이후 변경이 있어 다시 확인해야 합니다." },
    running: { label: "진행 기록", text: "현재 실행 상태는 최종 검증 안내에서 확인하세요." },
  };
  const summary = Object.hasOwn(summaries, result) ? summaries[result] : { label: "확인 필요", text: "검증 결과를 확인할 수 없습니다." };
  const description = result === "failed" && attempt.failure_phase === "file_lock"
    ? "당시 실행 중인 앱이 파일을 사용해 검증하지 못했습니다. 앱 종료 후 다시 검증할 수 있습니다."
    : summary.text;
  const recordedAt = attempt.finished_at || attempt.started_at;
  return <article className="verification-history__record" data-result={result}>
    <div className="verification-history__heading"><strong>{index + 1}차 · {summary.label}</strong>
      <time dateTime={recordedAt}>{formatDate(recordedAt)}</time></div>
    <p>{description}</p>
    <details className="verification-history__technical">
      <summary>기술 정보 · 상세 기록</summary>
      <dl className="detail-list">
        <Detail label="기록된 상태" value={attempt.status || "기록 없음"} />
        <Detail label="Main commit" value={attempt.main_head || "기록 없음"} mono />
        <Detail label="검증 대상 commit" value={attempt.integration_head || "기록 없음"} mono />
        <Detail label="Commit Queue 순서" value={attempt.commit_queue_task_ids.join(" → ") || "기록 없음"} mono />
        <Detail label="통과한 명령" value={attempt.passed_commands.map((command) => command.join(" ")).join(" / ") || "없음"} mono />
        <Detail label="마지막 실행 명령" value={attempt.current_command.join(" ") || "없음"} mono />
        <Detail label="실패 명령" value={attempt.failed_command.join(" ") || "없음"} mono />
        <Detail label="실패 단계" value={attempt.failure_phase || "해당 없음"} />
        <Detail label="명령 제한 시간" value={formatDurationLimit(attempt.command_timeout_seconds)} />
        <Detail label="전체 제한 시간" value={formatDurationLimit(attempt.total_timeout_seconds)} />
        <Detail label="자동 수정 횟수" value={`${attempt.repair_count}/${repairLimit}`} />
        <Detail label="마지막 통합 작업 ID" value={attempt.last_integrated_task_id || "해당 없음"} mono />
        <Detail label="직접 실패한 작업" value={attempt.failed_task_id || "특정되지 않음"} mono />
        <Detail label="관련 작업 후보" value={attempt.candidate_task_ids.join(", ") || "없음"} mono />
        {attempt.attribution_reason ? <Detail label="귀속 근거" value={attempt.attribution_reason} /> : null}
        {attempt.stop_reason ? <Detail label="중지 사유" value={attempt.stop_reason} /> : null}
      </dl>
      {attempt.error ? <div><h5>오류 원문</h5><pre>{attempt.error}</pre></div> : null}
      <p>재시도는 전체 검증을 다시 실행합니다. 통합 테스트 실패만으로 원인 작업을 확정하지 않습니다.</p>
    </details>
  </article>;
}

function VerificationHistory({ run }: { run: RunState }) {
  const latestIndex = run.verification_attempts.length - 1;
  const latest = run.verification_attempts[latestIndex];
  if (!latest) return null;
  return <div className="criteria-list verification-history"><h4>최근 검증 기록</h4>
    <VerificationAttemptRecord key={latest.id || latestIndex} attempt={latest} index={latestIndex} repairLimit={run.verification_repair_limit} />
    {latestIndex > 0 ? <details className="verification-history__previous">
      <summary>이전 검증 {latestIndex}회</summary>
      {run.verification_attempts.slice(0, latestIndex).map((attempt, index) =>
        <VerificationAttemptRecord key={attempt.id || index} attempt={attempt} index={index} repairLimit={run.verification_repair_limit} />)}
    </details> : null}
  </div>;
}

function PushHistory({ run }: { run: RunState }) {
  if (!run.push_receipts.length) return null;
  return <div className="criteria-list"><h4>Push 기록</h4>{run.push_receipts.map((receipt) => <details key={`${receipt.scope}-${receipt.remote}-${receipt.branch}-${receipt.remote_commit}`}>
    <summary>{receipt.scope === "work_branch" ? "작업 Branch" : "Main"} · {receipt.remote}/{receipt.branch} · {formatDate(receipt.pushed_at)}</summary>
    <dl className="detail-list"><Detail label="로컬 commit" value={receipt.local_commit} mono /><Detail label="확인한 원격 commit" value={receipt.remote_commit} mono /><Detail label="요청 ID" value={receipt.operation_request_id || "기록 없음"} mono /></dl>
    <p>{receipt.local_commit === receipt.remote_commit ? "원격 branch가 Push 대상 commit과 일치합니다." : "저장된 Push commit이 서로 다릅니다."}</p>
  </details>)}</div>;
}

function VerificationFailureNotice({ fileLocked, message }: { fileLocked: boolean; message: string }) {
  const issue = failurePresentation(message, "verify");
  return <div className="verification-progress verification-progress--warning" role="alert">
    <div className="verification-progress__heading"><span><AlertCircle aria-hidden="true" size={16} />
      <strong>{fileLocked ? "실행 중인 앱 종료 필요" : "최종 검증에 실패했습니다"}</strong></span><time>재시도 가능</time></div>
    <p>{fileLocked ? "앱/서버가 빌드 파일을 사용하고 있습니다. 해당 앱을 종료한 뒤 ‘앱 종료 후 다시 검증’을 누르세요. 코드 자동 수정은 진행하지 않습니다."
      : `${issue.title.replace(/[.!?]$/, "")}. ${issue.description}`}</p>
  </div>;
}

function OperationsWorkbench({ summaryOnly = false, statusTarget, statusVisible = true, projectName, recoveryTaskId, deployConfigured, run, operationsSnapshot, busyAction, executionElapsed, stopRequestPending, deleting, archiving, checking, planDirty, actionError, onApplySummary, onInspectRunLock, onRefresh, onVerify, onVerifyAndRepair, onStop, onApprovedAction, onDeleteRun, onArchiveRun, onRetryArchiveCleanup, onOpenArchiveFolder }: OperationsWorkbenchProps) {
  const [, setVerificationClock] = useState(0);
  const operationsReady = operationsSnapshotMatches(operationsSnapshot, projectName, run);
  const workspaces = operationsReady ? operationsSnapshot?.workspaces || [] : [];
  const runLock = operationsReady && (!operationsSnapshot?.lock?.run_id || operationsSnapshot.lock.run_id === run?.id)
    ? operationsSnapshot?.lock : undefined;
  const conflictPhase = activeConflictPhase(run, operationsSnapshot, projectName);
  const verificationRequested = ["runs.verify", "runs.verifyAndRepair"].includes(busyAction);
  const verificationLockActive = runLock?.state === "active"
    && ["verify", "verify-and-repair"].includes(runLock.operation);
  const verificationActive = verificationLockActive
    && (run?.active_step === "verify" || run?.verification_progress_phase === "repairing");
  const verificationPending = verificationRequested && !verificationActive;
  const verificationInterrupted = operationsReady && !verificationRequested
    && run?.active_step === "verify"
    && Boolean(runLock)
    && !verificationLockActive && !conflictPhase;
  const verificationFailed = run?.stage === "failed"
    && run.failed_step === "verify" && !conflictPhase;
  const verificationFileLocked = verificationFailed && run.verification_attempts?.at(-1)?.failure_phase === "file_lock";
  const verificationStopping = run?.execution_control?.stop_scope === "verification"
    && run.execution_control.stop_phase === "stopping";
  const canStopVerification = run?.execution_control?.stop_scope === "verification"
    && run.execution_control.can_stop;
  const mainApplyRequested = busyAction === "runs.merge";
  useEffect(() => {
    if (!verificationActive && !verificationPending) return;
    const timer = window.setInterval(() => {
      setVerificationClock((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [verificationActive, verificationPending]);
  if (!run) return <div className="task-workbench--empty"><EmptyState icon={<Database aria-hidden="true" size={24} />} title="작업 그룹을 선택하세요" detail="검증, Main 반영, Push와 작업공간 정리를 관리합니다." /></div>;
  if (run.archive) {
    const completed = run.archive.cleanup_targets.filter((target) => ["removed", "already_removed"].includes(target.status)).length;
    const cleanupComplete = run.archive.cleanup_status === "completed";
    return <div className="archive-record">
      <section className="archive-record__summary">
        <p className="archive-record__description">보관된 기록은 읽기 전용입니다.</p>
        <p role="status">작업공간 정리 {cleanupComplete ? "완료" : "확인 필요"} · {completed}/{run.archive.cleanup_targets.length}</p>
        {!cleanupComplete ? <p>{archiveCleanupReason(run.archive)}</p> : null}
        <div className="operation-actions">{!cleanupComplete ? <button className="button button--primary" type="button" disabled={Boolean(busyAction)} onClick={onRetryArchiveCleanup}>{busyAction === "runs.retryArchiveCleanup" ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <RotateCcw aria-hidden="true" size={15} />}정리 다시 시도</button> : null}
          <button className={`button button--${cleanupComplete ? "primary" : "secondary"}`} type="button" onClick={() => void onOpenArchiveFolder()}><FolderOpen aria-hidden="true" size={15} />기록 폴더 열기</button></div>
      </section>
      {!summaryOnly ? <details className="apply-summary__technical"><summary>기술 기록</summary>
        <p>실행 기록은 읽기 전용으로 보존되며 결과 commit은 내부 archive ref로 보호됩니다.</p>
        <dl className="detail-list"><Detail label="보관 시각" value={formatDate(run.archive.archived_at)} /><Detail label="작업공간 정리" value={`${run.archive.cleanup_status} · ${completed}/${run.archive.cleanup_targets.length}`} /><Detail label="Snapshot" value={run.archive.snapshot_path} mono /><Detail label="Manifest" value={run.archive.manifest_path} mono /></dl>
        <PushHistory run={run} />
        <div className="workspace-list">{run.archive.cleanup_targets.map((target) => <article key={target.id}><div><strong>{target.id}</strong><span>{target.status} · {target.error || target.recorded_path}</span></div></article>)}</div>
      </details> : null}
      <details className="archive-record__delete"><summary>기록 삭제</summary>
        <p>이 작업의 보관 기록을 영구 삭제합니다. 삭제한 기록은 복구할 수 없습니다.</p>
        <button className="button button--danger" type="button" disabled={deleting} onClick={onDeleteRun}>{deleting ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <Trash2 aria-hidden="true" size={15} />}보관 기록 영구 삭제</button>
      </details>
    </div>;
  }
  const busy = Boolean(busyAction) || Boolean(checking);
  const verificationElapsed = verificationActive && run.verification_started_at
    ? formatElapsed(run.verification_started_at)
    : formatDuration(executionElapsed);
  const verificationProgress = run.verification_progress_total > 0
    ? Math.min(
      1,
      run.verification_progress_current / run.verification_progress_total,
    )
    : 0;
  const sharedWorkspace = run.workspace_mode === "shared";
  const integration = run.integration_control;
  const mainApplyInterrupted = ["main_apply_interrupted", "main_apply_recoverable"].includes(integration?.reason_code || "");
  const remoteConfigured = integration?.remote_configured ?? true;
  const canVerify = operationsReady && (integration ? integration.can_verify : verificationFailed || run.stage === "ready_to_merge");
  const mainApplyComplete = mainAlreadyApplied(run);
  const archiveAvailable = ["pushed", "deployed"].includes(run.stage) || (!remoteConfigured && run.stage === "merged");
  const conflictOwnsActions = Boolean(operationsReady && run.integration_conflict && !["applied", "stale"].includes(run.integration_conflict.resolution_status)
    && !verificationActive && !verificationPending && !verificationFailed && !verificationInterrupted);
  const flowDescription = sharedWorkspace
    ? remoteConfigured
      ? `결과를 검사한 뒤 선택한 프로젝트에 적용하고 원격 저장소에 업로드합니다.${deployConfigured ? " 배포는 별도로 확인합니다." : ""} 적용이 끝나면 임시 작업공간을 정리합니다.`
      : `결과를 검사한 뒤 로컬 프로젝트에 적용합니다. 원격 저장소가 연결되지 않아 업로드하지 않습니다.${deployConfigured ? " 배포는 별도로 확인합니다." : ""}`
    : remoteConfigured
      ? `결과를 검사한 뒤 프로젝트 적용과 업로드를 각각 확인합니다.${deployConfigured ? " 배포는 별도로 확인합니다." : ""}`
      : `결과를 검사한 뒤 로컬 프로젝트에 적용합니다. 원격 저장소가 연결되지 않아 업로드하지 않습니다.${deployConfigured ? " 배포는 별도로 확인합니다." : ""}`;
  const primaryAction = applySummaryAction(run, operationsSnapshot, projectName);
  const primaryLabel = verificationFileLocked ? "앱 종료 후 다시 검증"
    : primaryAction === "work" ? verificationFailed || verificationInterrupted ? "재검사 후 작업 브랜치 반영" : "작업 브랜치에 반영"
    : primaryAction === "main" ? "메인 브랜치에 적용"
    : primaryAction === "upload" ? "변경 내용 업로드" : verificationFailed || verificationInterrupted ? "최종 검증 재시도" : "결과 검사";
  const includedTasks = includedApplyTasks(run);
  const pushRequested = busyAction === "runs.push";
  const currentStatus = applySummaryStatus(run, operationsSnapshot, projectName, busyAction);
  const displayStatus = currentStatus.replace(/^Main Push 완료/u, "프로젝트 반영 완료")
    .replace(/^로컬 Main 반영 완료$/u, "로컬 프로젝트 반영 완료");
  const applyPrimary = () => {
    if (!primaryAction) return;
    if (onApplySummary) { onApplySummary(primaryAction); return; }
    if (primaryAction === "work" || primaryAction === "verify") {
      if (verificationFileLocked) onVerify();
      else onVerifyAndRepair();
    }
    else onApprovedAction(primaryAction === "main" ? "runs.merge" : "runs.push", {
      workspaceMode: run.workspace_mode, ...(primaryAction === "main" ? { remoteConfigured } : {}),
    });
  };
  const statusMessage = (
    verificationActive ? verificationStopping ? <p>실행 종료를 기다립니다.</p> : null
      : verificationPending ? <p>{executionElapsed >= 10
        ? "실행 시작을 아직 확인하지 못했습니다. 상태를 계속 확인합니다."
        : "실행 엔진이 검증을 시작하기를 기다리고 있습니다."}</p>
        : conflictPhase || conflictOwnsActions ? null
          : verificationInterrupted ? <p>{runLock?.state === "stale" ? "실행 잠금을 해제한 뒤 다시 검증하세요." : "최종 검증을 다시 시도할 수 있습니다."}</p>
          : verificationFailed ? <p>{verificationFileLocked
            ? "빌드 파일을 사용하는 앱/서버를 종료한 뒤 다시 검증하세요."
            : summaryOnly ? "이 오류를 채팅에서 AI와 논의할 수 있습니다." : "세부 기록·관리에서 실패 원문을 확인할 수 있습니다."}</p>
            : mainApplyRequested || pushRequested || mainApplyInterrupted ? null
              : operationsSnapshot?.status === "error" ? <p>상태를 확인하지 못했습니다. 다시 확인해 주세요.</p>
                : !operationsReady ? <p>현재 상태를 확인한 뒤 가능한 행동을 표시합니다.</p>
                  : runLock && !["unlocked", "active"].includes(runLock.state) ? <p>현재 실행 여부와 잠금 상태를 확인한 뒤 진행하세요.</p>
                  : primaryAction === "main" ? <p>{sharedWorkspace && remoteConfigured
                    ? "검사한 내용을 메인 브랜치에 적용하고 원격 저장소에 업로드합니다." : "검사한 내용을 메인 브랜치에 적용합니다."}</p>
                    : primaryAction === "upload" || integration?.status === "main_push_pending"
                      ? <p>메인 브랜치의 변경 내용을 원격 저장소에 업로드합니다.</p>
                    : mainApplyComplete ? currentStatus.startsWith("Main Push 완료")
                      ? <p>메인 브랜치 적용과 원격 저장소 업로드가 끝났습니다.</p>
                      : currentStatus === "로컬 Main 반영 완료" ? <p>{remoteConfigured ? "메인 브랜치에 적용했습니다." : "로컬 프로젝트에 적용했습니다. 원격 저장소는 연결되어 있지 않습니다."}</p> : null
                      : <p>{sharedWorkspace && remoteConfigured
                        ? "완료한 작업을 검사하고 작업 브랜치에 반영합니다." : "완료한 작업을 검사한 뒤 메인 브랜치에 적용합니다."}</p>
  );
  const status = (
    <section className="apply-summary__current" aria-label="현재 반영 상태" data-compact={conflictOwnsActions || operationsReady && mainApplyInterrupted || undefined}>
      <div className={`apply-summary__status verification-progress${verificationActive ? " verification-progress--active" : ""}`}
        role={verificationFailed && !verificationActive && !verificationPending || operationsSnapshot?.status === "error" ? "alert" : "status"} aria-live="polite">
        <div className="verification-progress__heading">
          <span>{verificationActive || verificationPending || mainApplyRequested || pushRequested || conflictPhase
            ? <RefreshCw aria-hidden="true" className="spin" size={16} />
            : verificationFailed || verificationInterrupted || operationsSnapshot?.status === "error"
              ? <AlertCircle aria-hidden="true" size={16} /> : <ShieldCheck aria-hidden="true" size={16} />}
            <strong>{verificationActive ? verificationStopping ? "검증 중지 중" : verificationProgressTitle(run)
              : verificationPending ? executionElapsed >= 10 ? "최종 검증 시작이 지연되고 있습니다" : "최종 검증 시작 요청 중"
                : verificationInterrupted ? "이전 최종 검증이 중단되었습니다"
                  : checking && !busyAction ? "반영 대상 확인 중"
                    : verificationFailed && verificationFileLocked ? "빌드 파일 사용 중" : displayStatus}</strong>
          </span>
          <div className="verification-progress__controls" hidden={conflictOwnsActions}>
            {verificationActive || verificationPending || mainApplyRequested ? <time>{verificationElapsed}</time> : null}
            <div className="apply-summary__actions"><div className="operation-actions">
              {verificationActive ? <button className="button button--danger" type="button" disabled={verificationStopping || !canStopVerification || stopRequestPending} onClick={onStop}>
                <Square aria-hidden="true" size={14} />{verificationStopping || stopRequestPending ? "검증 중지 중" : "검증 중지"}
              </button> : primaryAction ? <button className="button button--primary" type="button" disabled={busy || Boolean(planDirty)} onClick={applyPrimary}>
                {busy ? <RefreshCw aria-hidden="true" className="spin" size={16} /> : <GitMerge aria-hidden="true" size={16} />}{primaryLabel}
              </button> : !mainApplyComplete && !archiveAvailable && (verificationPending || mainApplyRequested || pushRequested || runLock?.state === "active")
                ? <button className="button button--secondary" type="button" disabled>요청 처리 중</button>
                : !mainApplyComplete && integration?.status !== "main_push_pending" && (!runLock || runLock.state === "unlocked")
                  ? <button className="button button--secondary" type="button" disabled={busy} onClick={() => void onRefresh()}>상태 다시 확인</button> : null}
              {operationsReady && integration?.status === "main_push_pending" ? <button className="button button--primary" type="button"
                disabled={busy || !canRetryMainPush(run, runLock)} onClick={() => onApprovedAction("runs.retryMainPush", { workspaceMode: run.workspace_mode })}>
                <UploadCloud aria-hidden="true" size={16} />{run.stage === "merged" ? "변경 내용 업로드" : "변경 내용 업로드 재시도"}
              </button> : null}
              {operationsReady && runLock?.state !== "unlocked" && runLock?.state !== "active" && onInspectRunLock && !mainApplyInterrupted
                ? <button className="button button--secondary" type="button" onClick={onInspectRunLock}>잠금 상태 확인</button> : null}
            </div></div>
          </div>
        </div>
        {statusTarget ? statusMessage ? <details className="task-workbench__status-detail" data-dismiss-on-outside><summary>설명</summary><div>{statusMessage}</div></details> : null
          : <div className="apply-summary__message">{statusMessage}</div>}
        <div className={statusTarget ? "sr-only" : "apply-summary__progress-slot"}>
          {verificationActive ? <div className="progress-track" role="progressbar" aria-label="최종 검증 진행률" aria-valuemin={0}
            aria-valuemax={run.verification_progress_total || 1} aria-valuenow={run.verification_progress_current}>
            <span className="progress-track__value" style={{ transform: `scaleX(${verificationProgress})` }} />
          </div> : null}
        </div>
      </div>
    </section>
  );
  return (
    <div className="operations-workbench apply-summary">
      {statusTarget ? statusVisible ? createPortal(status, statusTarget) : null : status}
      {actionError ? <p className="apply-summary__error" role="alert">{/^(?:반영 대상|검사 중 반영|지금은 결과|결과 검사|현재 상태|승인을 취소|미저장 작업)/u.test(actionError) ? actionError : summaryOnly ? "반영 요청을 완료하지 못했습니다. 오류 원문을 확인해 주세요." : "반영 요청을 완료하지 못했습니다. 기술 기록의 오류를 확인한 뒤 다시 시도하세요."}</p> : null}
      {summaryOnly && (run.failure_message || actionError || operationsSnapshot?.error) ? <details className="apply-summary__error-record"><summary>오류 원문</summary>
        {run.failure_message ? <pre>{run.failure_message}</pre> : null}
        {actionError ? <pre>{actionError}</pre> : null}
        {operationsSnapshot?.error ? <pre>{operationsSnapshot.error}</pre> : null}
      </details> : null}
      {planDirty && !actionError?.startsWith("미저장 작업") ? <p role="status">미저장 작업 편집을 먼저 저장하거나 취소하세요.</p> : null}
      {run.integration_conflict ? <ConflictResolutionPanel projectName={projectName} run={run} recoveryTaskId={recoveryTaskId}
        operationsCheckedAt={operationsReady ? operationsSnapshot?.checkedAt : ""} operationsSnapshot={operationsSnapshot}
        onVerify={onVerify} verifyDisabled={busy || Boolean(planDirty)} onUpdated={onRefresh} /> : null}
      {operationsReady && mainApplyInterrupted ? <section className="operation-section" role="status"><div className="operation-section__heading"><div><h3>중단된 Main 반영 원본 확인</h3><p>저장소의 Main ref·index·작업 폴더와 아래 commit을 직접 확인하세요. 불일치하면 자동으로 되돌리거나 다시 반영하지 않습니다.</p></div></div><dl className="detail-list"><Detail label="저장소" value={run.repo_path} mono /><Detail label="기존 Main" value={integration?.verified_main_head || "확인 불가"} mono /><Detail label="현재 Main" value={integration?.current_main_head || "확인 불가"} mono /><Detail label="검증 commit" value={integration?.verified_integration_head || "확인 불가"} mono /></dl>{integration?.can_recover_main_apply ? <div className="operation-actions"><button className="button button--primary" type="button" disabled={busy || !operationsReady} onClick={() => onApprovedAction("runs.recoverMainApply", { workspaceMode: run.workspace_mode, remoteConfigured, repoPath: run.repo_path, targetCommit: integration.verified_integration_head })}><ShieldCheck aria-hidden="true" size={16} />원본 확인 후 복구 승인</button></div> : <p className="muted-copy">현재 원본 상태가 검증 결과와 일치하지 않아 복구 승인을 진행할 수 없습니다.</p>}</section> : null}
      {archiveAvailable ? <section className="apply-summary__finish" aria-label="작업 마무리">
        <div><h3>작업 마무리 <span>선택</span></h3>
          <p>실행 기록을 보관하고 임시 작업공간을 정리합니다.</p></div>
        <button className="button button--secondary" type="button"
          disabled={archiving || !operationsReady || runLock?.state === "active"} onClick={onArchiveRun}>
          {archiving ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <Archive aria-hidden="true" size={15} />}{archiving ? "보관·정리 중" : "보관하고 정리"}
        </button>
      </section> : null}
      {summaryOnly && deployConfigured ? <div className="operation-actions"><button className="button button--secondary" type="button" disabled={busy || !operationsReady || (remoteConfigured ? run.stage !== "pushed" : run.stage !== "merged")} onClick={() => onApprovedAction("runs.deploy")}><Rocket aria-hidden="true" size={16} />배포</button></div> : null}
      {!summaryOnly ? <details className="apply-summary__records"><summary>세부 기록·관리</summary>
      <details className="apply-summary__tasks"><summary>포함된 작업 {includedTasks.length}개</summary>
        {includedTasks.length ? <ul>{includedTasks.map((task) => <li key={task.id}>{task.title.trim() || "제목 없는 작업"}</li>)}</ul>
          : <p>완료한 작업이 없습니다.</p>}
      </details>
      <details className="apply-summary__technical"><summary>기술 기록</summary>
        <details><summary>검사·적용 범위</summary><p>{flowDescription}</p>
          <small>명령당 최대 {formatDurationLimit(run.integration_verify_command_timeout_seconds)} · 전체 최대 {formatDurationLimit(run.integration_verify_total_timeout_seconds)}</small>
        </details>
        {integration && operationsReady ? <IntegrationControlStatus control={integration} repoPath={run.repo_path} onRefresh={onRefresh} /> : null}
        <VerificationHistory run={run} /><PushHistory run={run} />
        {run.verification_progress_detail ? <details><summary>현재 검사 단계 원문</summary><pre>{run.verification_progress_detail}</pre></details> : null}
        {run.failure_message ? <details><summary>실패 원문</summary><pre>{run.failure_message}</pre></details> : null}
        {operationsSnapshot?.error ? <details><summary>상태 조회 오류 원문</summary><pre>{operationsSnapshot.error}</pre></details> : null}
        {actionError ? <details><summary>반영 요청 오류 원문</summary><pre>{actionError}</pre></details> : null}
        <div className="operation-actions">
          {sharedWorkspace && remoteConfigured && integration?.status === "apply_blocked" ? <button className="button button--secondary" type="button"
            hidden={mainApplyComplete || run.stage !== "verified"} disabled={busy || !operationsReady || integration.reason_code === "branch_mismatch"}
            onClick={() => onApprovedAction("runs.push", { workspaceMode: run.workspace_mode })}><UploadCloud aria-hidden="true" size={16} />작업 브랜치 Push</button> : null}
          <button className="button button--secondary" type="button" hidden={mainApplyComplete} disabled={busy || verificationActive || !canVerify} onClick={onVerify}>
            <ShieldCheck aria-hidden="true" size={16} />{verificationFileLocked ? "앱 종료 후 다시 검증" : verificationInterrupted || verificationFailed ? "최종 검증 재시도" : "최신 Main과 최종 검증"}
          </button>
          <button className="button button--secondary" type="button" hidden={mainApplyComplete} disabled={busy || verificationActive || !canVerify || verificationFileLocked} title={verificationFileLocked ? "파일 잠금은 앱 종료 후 다시 검증하세요." : undefined} onClick={onVerifyAndRepair}>
            <RotateCcw aria-hidden="true" size={16} />검증·자동 수정
          </button>
          {deployConfigured ? <button className="button button--secondary" type="button" disabled={busy || !operationsReady || (remoteConfigured ? run.stage !== "pushed" : run.stage !== "merged")} onClick={() => onApprovedAction("runs.deploy")}>
            <Rocket aria-hidden="true" size={16} />배포
          </button> : null}
        </div>
      </details>
      <details className="apply-summary__management"><summary>작업공간·기록 관리</summary>
      <section className="operation-section"><div className="operation-section__heading"><div><h3>{sharedWorkspace ? "작업 그룹 작업공간" : "개별 작업공간"}</h3></div></div><div className="workspace-list">{!operationsReady ? <p className="muted-copy">작업공간 상태 확인 중 · 최신 확인 전에는 정리할 수 없습니다.</p> : workspaces.length ? workspaces.map((workspace) => <article key={`${workspace.run_id}-${workspace.task_id}`}><div><strong>{sharedWorkspace ? "공유 작업공간" : workspace.task_id}</strong><span>{workspaceStateLabel(workspace.state)} · {workspaceReasonLabel(workspace.reason)}</span>{workspace.reason ? <details><summary>기술 원문</summary><code>{workspace.reason}</code></details> : null}</div><button className="button button--quiet" type="button" disabled={busy || !operationsReady || !workspace.cleanup_safe} onClick={() => onApprovedAction("workspaces.cleanup", { taskId: workspace.task_id })}>정리</button></article>) : <p className="muted-copy">표시할 작업공간이 없습니다.</p>}</div></section>
      <section className="operation-section operation-section--danger"><div className="operation-section__heading"><div><h3>작업 그룹 관리</h3></div></div><div className="operation-actions"><span className={`lock-state lock-state--${runLock?.state || "unknown"}`}>{runLockLabel(runLock)}</span>{!archiveAvailable ? <button className="button button--danger" type="button" disabled={deleting || !operationsReady || runLock?.state === "active" || mainApplyInterrupted} title={mainApplyInterrupted ? "중단된 Main 반영의 원본 상태를 먼저 확인하세요." : runLock?.state === "active" ? "현재 작업이 끝난 뒤 삭제할 수 있습니다." : undefined} onClick={onDeleteRun}>{deleting ? <RefreshCw aria-hidden="true" className="spin" size={15} /> : <Trash2 aria-hidden="true" size={15} />}작업 그룹 삭제</button> : null}</div></section>
      </details>
      </details> : null}
    </div>
  );
}

interface InspectorProps {
  recordsOnly?: boolean;
  panelId: string;
  visible: boolean;
  scrollKey: string;
  scrollMemory: React.RefObject<InspectorScrollMemory>;
  logView: LogViewState;
  onLogViewChange(view: LogViewState): void;
  onCollapse?(): void;
  editor?: ReactNode;
  run?: RunState;
  workspace?: RunWorkspacePresentation;
  task?: WorkTask;
  dependencyTasks: WorkTask[];
  taskLogState: TaskLogState;
  activeTab: InspectorTab;
  profile?: TaskProfileSelection;
  profileOptions: ProviderProfile[];
  compact?: boolean;
  onBackToList?(): void;
  onStop?(task: WorkTask): void;
  onOpenTask(taskId: string): void;
  onReviewResult(taskId: string): void;
  onChangeTab(tab: InspectorTab): void;
}

function RecoveryTaskRow({ task, run, onOpen }: { task: RecoveryTask; run: RunState; onOpen(): void }) {
  const status = recoveryTaskPresentation(task, run);
  return <article className="recovery-task-row" data-tone={status.tone}>
    <button type="button" className="recovery-task-row__select" onClick={onOpen}>
      <span className="recovery-task-row__kind">복구</span>
      <span><strong>{task.title}</strong><small>{task.conflict.files.length}개 파일 · 요청 {task.operation_request_ids.length}회 · {status.detail}</small></span>
    </button>
    <span className="recovery-task-row__status"><strong>{status.label}</strong><small>{task.superseded_by ? `후속 ${task.superseded_by}` : task.id}</small></span>
    <button className="button button--secondary" type="button" onClick={onOpen}>{task.conflict.resolution_status === "candidate_ready" ? "해결안 검토" : "상세·로그"}</button>
  </article>;
}

function TaskProgressSummary({ task, run, onStop }: { task: WorkTask; run: RunState; onStop?(): void }) {
  const [now, setNow] = useState(Date.now());
  const latest = task.action_results.at(-1);
  const active = taskIsActive(task) && ["running", "preparing"].includes(run.execution_control?.situation || "");
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, task.id]);
  const started = Date.parse(latest?.started_at || task.last_attempt_started_at || "");
  const finished = Date.parse(latest?.finished_at || task.last_attempt_finished_at || "");
  const elapsed = Number.isFinite(started) ? formatDuration(Math.max(0, Math.floor(((active ? now : Number.isFinite(finished) ? finished : started) - started) / 1000))) : "기록 없음";
  const observation = task.progress_observation;
  const activity = Date.parse(observation?.last_activity_changed_at || task.progress_updated_at || "");
  const eventReceived = Date.parse(observation?.last_event_received_at || "");
  const phaseStarted = Date.parse(observation?.phase_started_at || "");
  const silentSeconds = Number.isFinite(activity) ? Math.max(0, Math.floor((now - activity) / 1000)) : 0;
  const eventSilentSeconds = Number.isFinite(eventReceived) ? Math.max(0, Math.floor((now - eventReceived) / 1000)) : undefined;
  const silentDuration = `${Math.floor(silentSeconds / 60)}분 ${silentSeconds % 60}초`;
  const phaseElapsed = Number.isFinite(phaseStarted) ? formatDuration(Math.max(0, Math.floor((now - phaseStarted) / 1000))) : "기록 없음";
  const action = task.active_action || (latest?.status === "running" ? latest.action : "");
  const verification = [...task.action_results].reverse().find((result) => result.action === "verify");
  const styleCommandCount = task.verify_commands.filter((command) => styleCheckPurpose(command, run.code_style_snapshot?.checks) === "코드 스타일").length;
  const actions = ["execute", "review", ...(task.action_results.some((result) => result.action === "revise") ? ["revise"] : []), "verify"];
  return <section className="task-progress-summary" aria-label="작업 진행 요약">
    <strong>{!active && taskIsActive(task) ? run.execution_control?.stop_phase === "stopped" ? "중지됨" : run.execution_control?.situation === "resumable" ? "중단됨 · 재개 필요" : "실행 상태 확인 필요"
      : active && action ? `${evidenceActionLabels[action] || action} 진행 중` : taskStatusLabels[task.status] || task.status}</strong>
    {active && run.execution_control?.can_stop && onStop ? <button className="button button--danger" type="button" aria-label={`${task.title} 중지`} onClick={onStop}><Square aria-hidden="true" size={13} />중지</button> : null}
    <p>{taskProgressText(task) || (active ? "다음 진행 보고를 기다리는 중" : "실행 결과는 아래 단계 기록에서 확인하세요.")}</p>
    <dl className="detail-list">
      <Detail label="현재/마지막 단계 경과" value={elapsed} />
      {active && observation ? <Detail label="현재 상태 구간" value={phaseElapsed} /> : null}
      <Detail label="최근 이벤트 수신" value={observation?.last_event_received_at ? `${formatActivityTime(observation.last_event_received_at)}${active && eventSilentSeconds !== undefined ? ` · ${eventSilentSeconds}초 전` : ""}` : "아직 관측 없음"} />
      <Detail label="마지막 활동 변화" value={observation?.last_activity_changed_at ? `${formatActivityTime(observation.last_activity_changed_at)}${active ? ` · ${silentDuration} 전` : ""}` : task.progress_updated_at ? formatActivityTime(task.progress_updated_at) : latest?.finished_at ? formatActivityTime(latest.finished_at) : "아직 보고 없음"} />
    </dl>
    <ul className="task-progress-summary__steps">{actions.map((name) => {
      const result = [...task.action_results].reverse().find((item) => item.action === name);
      const status = result ? evidenceStatusLabels[result.status] || result.status : name === "review" && task.review_status === "not_required" ? "대상 아님" : "대기";
      return <li key={name}><span>{evidenceActionLabels[name] || name}</span><strong>{status}</strong></li>;
    })}</ul>
    {verification ? <p>이번 검증 통과 명령 {verification.passed_commands.length}/{task.verify_commands.length}{task.verify_commands.length === 0 ? " · 검증 명령 미지정" : ""}</p> : null}
    <p>작업 검증 {task.verify_commands.length}개 명령{styleCommandCount ? ` · 코드 스타일 ${styleCommandCount}개` : ""} · 명령당 최대 {formatDuration(run.task_verify_command_timeout_seconds)} · 전체 최대 {formatDuration(run.task_verify_total_timeout_seconds)}</p>
    {active && task.progress_phase === "verifying_command" ? <p>명령 출력을 기다리고 있습니다. 출력은 명령 종료 후 로그에 표시됩니다.</p> : null}
    {active && silentSeconds >= 60 ? <p>{eventSilentSeconds !== undefined && eventSilentSeconds < 60
      ? `같은 단계의 응답은 계속 받고 있지만 ${silentDuration} 동안 구분 가능한 활동 변화는 없습니다.`
      : `최근 ${silentDuration} 동안 새 활동 변화가 확인되지 않았습니다.`} 이 시간만으로 작업 중단 여부를 판단할 수는 없습니다.</p> : null}
  </section>;
}

function Inspector({ recordsOnly = false, panelId, visible, scrollKey, scrollMemory, logView, onLogViewChange, onCollapse, run, workspace, task, dependencyTasks, taskLogState, activeTab, profile, profileOptions, compact = false, onBackToList, onStop, onOpenTask, onReviewResult, onChangeTab, editor }: InspectorProps) {
  const tabs: readonly (readonly [InspectorTab, string])[] = recordsOnly ? [["log", "로그"], ["events", "이벤트"]] : [["detail", "상세"], ["log", "로그"], ["events", "이벤트"]];
  return (
    <aside id={panelId} className="inspector" data-compact={compact} hidden={!visible} aria-labelledby={`${panelId}-title`}>
      <div className="pane-heading inspector__heading">{compact && onBackToList ? <button className="back-button" type="button" onClick={onBackToList}><ChevronLeft aria-hidden="true" size={16} />작업 목록으로</button> : null}<div><span className="eyebrow">작업 정보</span><h2 id={`${panelId}-title`} tabIndex={-1}>상세·로그</h2></div>{!compact && onCollapse ? <InspectorToggle open panelId={panelId} onToggle={onCollapse} /> : null}</div>
      <div className="inspector-tabs" role="tablist" aria-label="상세·로그 보기">{tabs.map(([tab, label], index) => (
        <button key={tab} id={`${panelId}-tab-${tab}`} type="button" role="tab" aria-selected={activeTab === tab}
          aria-controls={`${panelId}-content`} tabIndex={activeTab === tab ? 0 : -1} onClick={() => onChangeTab(tab)}
          onKeyDown={(event) => {
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
              : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
                : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
            if (next < 0) return;
            event.preventDefault();
            onChangeTab(tabs[next][0]);
            window.requestAnimationFrame(() => document.getElementById(`${panelId}-tab-${tabs[next][0]}`)?.focus());
          }}>{label}</button>
      ))}</div>
      <InspectorContent id={`${panelId}-content`} labelledBy={`${panelId}-tab-${activeTab}`}
        contextKey={scrollKey} visible={visible} compact={compact} memory={scrollMemory}>
        {run && activeTab === "detail" ? <button className="button button--secondary" type="button" onClick={() => onReviewResult(task?.id || "")}>{task ? "Task 결과 확인" : "그룹 결과 확인"}</button> : null}
        {run && task && activeTab === "detail" ? <TaskProgressSummary key={`${run.id}:${task.id}`} run={run} task={run.tasks.find((saved) => saved.id === task.id) || task} onStop={onStop ? () => onStop(task) : undefined} /> : null}
        {run && task && activeTab === "detail" ? <TaskDependencyLinks task={task} tasks={dependencyTasks} onOpenTask={onOpenTask} /> : null}
        {!run ? <EmptyState icon={<PanelRight aria-hidden="true" size={22} />} title="선택된 항목 없음" detail="작업 그룹과 작업을 선택하면 상세 정보가 표시됩니다." /> : null}
        {run && activeTab === "detail" ? editor || <TaskDetail run={run} workspace={workspace} task={task} profile={profile} profileOptions={profileOptions} /> : null}
        {run && activeTab === "log" ? task
          ? <ExecutionLogViewer key={`${run.id}:${task.id}`} run={run} task={task} state={taskLogState} progressText={taskProgressText(task)}
            view={logView} visible={visible} onViewChange={onLogViewChange} />
          : <p>로그를 볼 작업을 선택하세요.</p> : null}
        {run && activeTab === "events" ? <ol className="event-list">{[...run.events].reverse().map((event, index) => <li key={`${event.at}-${index}`}><span>{eventKindLabels[event.kind] || event.kind}</span><p>{localizeEvent(event.message)}</p><time>{formatDate(event.at)}</time></li>)}</ol> : null}
      </InspectorContent>
    </aside>
  );
}

function TaskDependencyLinks({ task, tasks, onOpenTask }: { task: WorkTask; tasks: WorkTask[]; onOpenTask(taskId: string): void }) {
  const sections = taskDependencySections(task, tasks);
  if (!sections.length) return null;
  const renderSection = (section: ReturnType<typeof taskDependencySections>[number]) => <div className="task-dependency-links__section" key={section.kind}>
    <h3>{section.kind === "conflict" ? "같은 파일을 수정할 수 있는 작업" : section.title} <span>{section.items.length}개</span></h3>
    {section.kind === "conflict" ? <p>같은 파일을 수정할 가능성이 있어 함께 분석한 작업입니다.</p> : null}
    <ul>{section.items.map((item) => <li key={item.id}>
      {item.available ? <button type="button" data-blocked={item.blocked} onClick={() => onOpenTask(item.id)}>
        <strong>{item.title}</strong><span>{taskStatusLabels[item.status] || item.status || "상태 확인 불가"}{item.blocked ? " · 현재 대기" : ""}</span><code>{item.id}</code><span className="sr-only">작업 상세 보기</span>
      </button> : <div className="task-dependency-links__missing"><strong>확인 불가</strong><span>{item.blocked ? "현재 대기 · " : ""}참조한 작업이 현재 그룹에 없습니다.</span><code>{item.id}</code></div>}
    </li>)}</ul>
  </div>;
  return <section className="task-dependency-links" aria-label="관련 작업">
    {sections.filter((section) => section.kind !== "conflict").map(renderSection)}
    {sections.some((section) => section.kind === "conflict") ? <details className="task-dependency-links__technical"><summary>기술 상세</summary>
      {sections.filter((section) => section.kind === "conflict").map(renderSection)}
    </details> : null}
  </section>;
}

function LogView({ value, canCopy }: { value: string; canCopy: boolean }) {
  const ref = useRef<HTMLPreElement>(null);
  const followTail = useRef(true);
  const [copying, setCopying] = useState(false);
  const [copyResult, setCopyResult] = useState<{ value: string; error: boolean; message: string } | null>(null);
  useEffect(() => { if (ref.current && followTail.current) ref.current.scrollTop = ref.current.scrollHeight; }, [value]);
  const copyLog = async () => {
    if (!canCopy || copying) return;
    setCopying(true);
    setCopyResult(null);
    try {
      await navigator.clipboard.writeText(value);
      setCopyResult({ value, error: false, message: "표시된 로그를 복사했습니다." });
    } catch (error: unknown) {
      setCopyResult({ value, error: true, message: `로그 복사에 실패했습니다. ${errorMessage(error)}` });
    } finally {
      setCopying(false);
    }
  };
  return <>
    <button className="button button--quiet" type="button" disabled={!canCopy || copying} onClick={() => void copyLog()}><Copy aria-hidden="true" size={15} />{copying ? "복사 중…" : "표시된 로그 복사"}</button>
    {copyResult?.value === value ? <p role={copyResult.error ? "alert" : "status"}>{copyResult.message}</p> : null}
    <pre ref={ref} className="log-view" tabIndex={0} onScroll={(event) => { const node = event.currentTarget; followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 40; }}>{value}</pre>
  </>;
}

function TaskDetail({ run, workspace: observedWorkspace, task, profile, profileOptions }: {
  run: RunState; workspace?: RunWorkspacePresentation; task?: WorkTask; profile?: TaskProfileSelection; profileOptions: ProviderProfile[];
}) {
  const workspace = observedWorkspace || runWorkspacePresentation(run);
  if (!task) {
    return <div className="task-detail"><dl className="detail-list"><Detail label="작업 그룹 ID" value={run.id} mono /><Detail label="상태" value={stageLabels[run.stage] || run.stage} /><Detail label="기획 모델" value={profileLabel(run)} /><Detail label="기준 commit" value={run.base_commit || "-"} mono /></dl><ReadonlyPath label="원본 프로젝트" value={run.repo_path} /><ReadonlyPath label="실제 작업공간" value={workspace.path} status={workspace.status} /></div>;
  }
  const selectedProfile = profile || { agentId: task.agent_id, model: task.model, reasoningEffort: task.reasoning_effort };
  const selectedOption = profileOptions.find((option) => option.agent_id === selectedProfile.agentId && option.model === selectedProfile.model);
  const profileChanged = task.status === "pending" && (selectedProfile.agentId !== task.agent_id || selectedProfile.model !== task.model || selectedProfile.reasoningEffort !== task.reasoning_effort);
  const providerId = selectedOption?.provider_id || task.provider_id;
  const providerName = providerDisplayName(providerId) || "AI 제공자";
  const modelValue = taskModelDisplayValue(task, providerId, selectedProfile.model);
  const reasoningValue = taskReasoningDisplayValue(task, providerId, selectedProfile.reasoningEffort);
  const agentValue = selectedProfile.agentId || task.agent_id || "-";
  const modelLabel = task.status === "pending" ? profileChanged ? "선택 모델" : "추천 모델" : "실행 모델";
  const reasoningLabel = task.status === "pending" ? profileChanged ? "선택 추론 강도" : "추천 추론 강도" : "추론 강도";
  const liveProgress = taskProgressText(task);
  return (
    <div className="task-detail">
      <div className="task-detail__title"><span className={`status-mark status-mark--${taskTone(task)}`} /><div><h3>{task.title}</h3><code>{task.id}</code></div></div>
      <p>{task.description || "작업 설명이 없습니다."}</p>
      {task.status === "pending" ? <div className="profile-origin"><CircleDot aria-hidden="true" size={16} /><div><strong>{profileChanged || task.profile_source === "manual" ? "사용자가 선택한 실행 전 프로필" : task.model_selection_reason ? "자동 선택 프로필" : "기획 AI 추천 프로필"}</strong><span>{profileChanged ? "아직 실행되지 않았으며 실행 요청 시 이 설정이 적용됩니다." : "아직 실행되지 않았습니다. 작업 목록에서 실행 전에 변경할 수 있습니다."}</span></div></div> : null}
      <dl className="detail-list"><Detail label="진행 상태" value={taskStatusLabels[task.status] || task.status} />{liveProgress ? <Detail label="현재 작업" value={liveProgress} /> : null}<Detail label="준비" value={readinessLabels[task.readiness] || task.readiness} /><Detail label="AI 제공자" value={providerName} /><Detail label={modelLabel} value={modelValue} /><Detail label={reasoningLabel} value={reasoningValue} /><Detail label="실행 프로필 ID" value={agentValue} mono /><Detail label="리뷰" value={task.review_status || "-"} /><Detail label="선행 작업" value={task.dependencies.length ? task.dependencies.join(", ") : "없음"} mono /></dl>
      <div className="task-workspace-paths"><ReadonlyPath label="원본 프로젝트" value={run.repo_path} /><ReadonlyPath label="그룹 작업공간" value={workspace.path} status={workspace.status} /></div>
      {task.acceptance_criteria.length ? <div className="criteria-list"><h4>완료 조건</h4><ul>{task.acceptance_criteria.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
      {task.conflict_group.length ? <dl className="detail-list"><Detail label="충돌 가능 그룹" value={task.conflict_group.join(", ")} mono /><Detail label="자동 선행 작업" value={task.conflict_dependencies.join(", ") || "없음"} mono /><Detail label="공용 계약 선행" value={task.is_prerequisite ? "예" : "아니오"} /></dl> : null}
      <TaskResultHistory task={task} />
      {task.error ? <div className="inline-error" role="alert"><XCircle aria-hidden="true" size={16} /><span>{task.error}</span></div> : null}
    </div>
  );
}

function TaskPlanEditor({ task, tasks, input, validationErrors, revealAdvancedRequest, revealField, dirty, readOnly, onInput, onUpdate }: {
  task: WorkTask; tasks: WorkTask[]; input: TaskEditorInput; validationErrors: TaskDraftError[];
  revealAdvancedRequest: number; revealField?: TaskDraftError["field"]; dirty: boolean; readOnly: boolean;
  onInput(input: TaskEditorInput): void; onUpdate(changes: Partial<WorkTask>): void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const contractId = useId();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const taskId = input.id;
  const commands = input.commands;
  const parsedCommands = parseDraftCommands(commands);
  const commandError = parsedCommands.error;
  const dependencyOptions = taskDependencyOptions(tasks, task.id, input.dependencies);
  const unresolvedDependencies = unresolvedDraftDependencies(tasks, input.dependencies);
  const dependencyLabels = splitLines(input.dependencies).map((dependencyId) => {
    const dependency = tasks.find((candidate) => candidate.id === dependencyId);
    return dependency ? `${dependency.title || "제목 없는 작업"} (${dependency.id})` : `${dependencyId} (확인 불가)`;
  });
  const commandSummary = commandError
    ? "입력 오류 · 마지막으로 유효했던 검증 명령을 유지합니다."
    : parsedCommands.commands?.length
      ? parsedCommands.commands.map((command) => command.join(" ")).join("\n")
      : "없음";
  const firstErrorField = revealField || validationErrors[0]?.field || "";
  const fieldError = (field: TaskDraftError["field"]) => validationErrors.find((error) => error.field === field)?.message || "";
  const fieldProps = (field: TaskDraftError["field"]) => ({
    "data-editor-field": field, "aria-invalid": Boolean(fieldError(field)),
    "aria-describedby": fieldError(field) ? `${contractId}-${field}-error` : undefined,
  });
  const fieldMessage = (field: TaskDraftError["field"]) => fieldError(field)
    ? <small id={`${contractId}-${field}-error`} className="field-error">{fieldError(field)}</small> : null;
  useEffect(() => {
    if (revealAdvancedRequest && firstErrorField && taskDraftErrorIsAdvanced(firstErrorField)) setAdvancedOpen(true);
  }, [firstErrorField, revealAdvancedRequest]);
  useEffect(() => {
    if (!revealAdvancedRequest || !firstErrorField || (taskDraftErrorIsAdvanced(firstErrorField) && !advancedOpen)) return;
    const frame = window.requestAnimationFrame(() => {
      formRef.current?.closest("details.work-task-controls")?.setAttribute("open", "");
      const field = formRef.current?.querySelector<HTMLElement>(`[data-editor-field="${firstErrorField}"]`);
      if (field?.getClientRects().length) { field.focus({ preventScroll: true }); field.scrollIntoView({ block: "nearest" }); }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [advancedOpen, firstErrorField, revealAdvancedRequest]);
  const commitTaskId = () => {
    if (readOnly) return;
    const normalized = taskId.trim();
    if (!normalized) return;
    onInput({ ...input, id: normalized });
    if (normalized === task.id) return;
    onUpdate({ id: normalized });
  };
  const updateCommands = (value: string) => {
    onInput({ ...input, commands: value });
    const parsed = parseDraftCommands(value);
    if (parsed.commands) onUpdate({ verify_commands: parsed.commands });
  };
  const updateLines = (field: "capabilities" | "acceptance_criteria" | "dependencies" | "expected_paths" | "forbidden_paths", value: string) => {
    onInput({ ...input, [field]: value });
    onUpdate({ [field]: splitLines(value) });
  };
  return (
    <form ref={formRef} className="task-plan-editor" onSubmit={(event) => event.preventDefault()}>
      <div className="task-plan-editor__heading"><div><span className="status-mark status-mark--pending" /><div><h3>작업 계획 편집</h3><p>{dirty ? "미저장 변경 있음 · 이 세션에서 초안을 보관합니다." : "저장된 계획"}</p></div></div></div>
      <label className="field"><span>제목</span><input {...fieldProps("title")} readOnly={readOnly} value={task.title} onChange={(event) => onUpdate({ title: event.target.value })} />{fieldMessage("title")}</label>
      <label className="field"><span>설명</span><textarea {...fieldProps("description")} readOnly={readOnly} rows={4} value={task.description} onChange={(event) => onUpdate({ description: event.target.value })} />{fieldMessage("description")}</label>
      <label className="field"><span>완료 조건 · 한 줄에 하나</span><textarea {...fieldProps("acceptance_criteria")} readOnly={readOnly} rows={5} value={input.acceptance_criteria} onChange={(event) => updateLines("acceptance_criteria", event.target.value)} />{fieldMessage("acceptance_criteria")}</label>
      <section className="task-plan-contract" aria-labelledby={contractId}>
        <div className="task-plan-contract__heading"><strong id={contractId}>실행 계약 요약</strong><span className={`risk-label risk-label--${task.risk_level}`}>{riskLabel(task.risk_level)}</span></div>
        <dl>
          <Detail label="선행 작업" value={dependencyLabels.length ? dependencyLabels.join(" · ") : "없음"} />
          <Detail label="예상 변경 경로" value={task.expected_paths.join(" · ") || "지정 없음"} mono />
          <Detail label="금지 경로" value={task.forbidden_paths.join(" · ") || "없음"} mono />
          <Detail label="검증 명령" value={commandSummary} mono />
        </dl>
      </section>
      <details className="task-plan-advanced" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
        <summary><span><Settings aria-hidden="true" size={15} />고급 설정</span><span className="task-plan-advanced__status">{validationErrors.length ? <strong>{validationErrors.length}개 오류</strong> : "범위·검증·위험 설정"}<ChevronDown aria-hidden="true" size={15} /></span></summary>
        <div className="task-plan-advanced__body">
          <label className="field"><span>Task ID</span><input {...fieldProps("id")} readOnly={readOnly} value={taskId} onChange={(event) => onInput({ ...input, id: event.target.value })} onBlur={commitTaskId} />{fieldMessage("id")}</label>
          <label className="field"><span>작업 역량 · 한 줄에 하나</span><textarea {...fieldProps("capabilities")} readOnly={readOnly} rows={3} value={input.capabilities} onChange={(event) => updateLines("capabilities", event.target.value)} />{fieldMessage("capabilities")}</label>
          <fieldset className="task-dependency-picker" disabled={readOnly}>
            <legend>선행 작업 선택</legend>
            {dependencyOptions.length ? <div className="task-dependency-picker__options">{dependencyOptions.map((option) => (
              <label key={option.id}><input type="checkbox" checked={option.selected} onChange={(event) => updateLines("dependencies", toggleDraftDependency(input.dependencies, option.id, event.target.checked))} /><span><strong>{option.title}</strong><code>{option.id}</code></span></label>
            ))}</div> : <p>선택할 다른 작업이 없습니다.</p>}
          </fieldset>
          <label className="field"><span>선행 작업 ID 직접 입력 · 한 줄에 하나</span><textarea readOnly={readOnly} rows={3} value={input.dependencies} onChange={(event) => updateLines("dependencies", event.target.value)} />{unresolvedDependencies.length ? <small className="field-note">확인 불가 ID도 삭제하지 않고 보존합니다: {unresolvedDependencies.join(", ")}</small> : null}</label>
          <label className="field"><span>공용 계약·스키마 선행 작업</span><select disabled={readOnly} value={task.is_prerequisite ? "yes" : "no"} onChange={(event) => onUpdate({ is_prerequisite: event.target.value === "yes" })}><option value="no">일반 구현 작업</option><option value="yes">겹치는 일반 작업보다 먼저 실행</option></select></label>
          {task.conflict_group.length ? <dl className="detail-list"><Detail label="저장된 충돌 가능 그룹" value={task.conflict_group.join(", ")} mono /><Detail label="자동 선행 작업" value={task.conflict_dependencies.join(", ") || "없음"} mono /></dl> : null}
          <label className="field"><span>예상 변경 경로 · 한 줄에 하나</span><textarea {...fieldProps("expected_paths")} readOnly={readOnly} rows={4} value={input.expected_paths} onChange={(event) => updateLines("expected_paths", event.target.value)} />{fieldMessage("expected_paths")}</label>
          <label className="field"><span>금지 경로 · 한 줄에 하나</span><textarea readOnly={readOnly} rows={3} value={input.forbidden_paths} onChange={(event) => updateLines("forbidden_paths", event.target.value)} /></label>
          <label className="field"><span>검증 명령 · argv JSON 배열</span><textarea {...fieldProps("commands")} readOnly={readOnly} className="mono" rows={6} value={commands} onChange={(event) => updateCommands(event.target.value)} />{fieldMessage("commands")}</label>
          <label className="field"><span>위험도</span><select disabled={readOnly} value={task.risk_level} onChange={(event) => onUpdate({ risk_level: event.target.value })}><option value="low">낮음</option><option value="medium">보통</option><option value="high">높음</option></select></label>
        </div>
      </details>
    </form>
  );
}

function CodexAuthContent({ state, busy, message, onRefresh, onStart, onConnectApiKey, onReopen, onCopyCode, onCancel, onClose }: {
  state?: CodexAuthState;
  busy: string;
  message: string;
  onRefresh(): void;
  onStart(method: CodexAuthMethod): void;
  onConnectApiKey(apiKey: string): Promise<void>;
  onReopen(): void;
  onCopyCode(): void;
  onCancel(): void;
  onClose(): void;
}) {
  const pending = codexAuthIsPending(state);
  const canStart = !busy && (!state || ["signed_out", "cancelled", "failed", "runtime_error", "status_error"].includes(state.status));
  const title = codexAuthTitle(state);
  const detail = codexAuthDetail(state);
  const account = codexAccountDetails(state);
  const apiKeyBlockedReason = state?.status === "cancelling" ? "로그인 취소를 확인하고 있습니다. 취소가 끝나면 API 키를 연결할 수 있습니다."
    : pending ? "브라우저 로그인이 진행 중입니다. 로그인 취소 후 API 키를 연결할 수 있습니다."
    : state?.status === "unknown" ? "이전 로그인 상태를 확인하지 못했습니다. 연결 다시 확인 후 API 키를 연결해 주세요." : "";
  return (
      <section className="codex-auth-content" aria-label="Codex 연결">
        <CodexApiKeyConnection connected={state?.status === "connected"} busy={busy} blockedReason={apiKeyBlockedReason}
          onCancelPending={state?.status === "waiting" ? onCancel : undefined} onConnect={onConnectApiKey} />
        <p>ChatGPT 구독이나 OpenAI API 키로 Codex를 연결해 기획과 작업을 실행할 수 있습니다.</p>
        <p className="field-note">이 앱의 Codex 연결은 Codex 앱·CLI와 별도로 관리합니다. 처음 분리한 뒤에는 여기서 한 번 다시 연결해 주세요.</p>
        <section className="codex-auth-state" data-state={state?.status || "checking"} aria-live="polite">
          {state?.status === "connected" ? <CheckCircle2 aria-hidden="true" size={22} /> : pending ? <Clock3 aria-hidden="true" size={22} /> : <ShieldCheck aria-hidden="true" size={22} />}
          <div><strong>{title}</strong><span>{detail}</span></div>
        </section>
        {state?.error_code ? <small className="muted">오류 코드: {state.error_code}</small> : null}
        {account ? <dl className="codex-account-details">
          <div><dt>현재 계정</dt><dd>{account.email}</dd></div>
          <div><dt>로그인 방식</dt><dd>{account.method}</dd></div>
          <div><dt>{state?.auth_method === "api_key" ? "과금 방식" : "요금제"}</dt><dd>{account.plan}</dd></div>
        </dl> : null}
        {state?.method === "device_code" && state.user_code && pending ? <div className="codex-device-code"><span>기기 코드</span><strong>{state.user_code}</strong><button className="button button--quiet" type="button" onClick={onCopyCode}><Copy aria-hidden="true" size={14} />코드 복사</button></div> : null}
        {state?.browser_open_error ? <p role="alert">{state.browser_open_error}</p> : null}
        {message ? <p role="status">{message}</p> : null}
        <footer className="codex-auth-actions">
          {pending ? <>
            <button className="button button--primary" type="button" disabled={Boolean(busy) || state?.status === "cancelling"} onClick={onReopen}>{busy === "reopen" ? "여는 중…" : "브라우저 다시 열기"}</button>
          </> : state?.status === "connected" ? <>
            <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={onRefresh}>연결 다시 확인</button>
            {state.auth_method === "api_key" ? <button className="button button--quiet" type="button" disabled={Boolean(busy)}
              onClick={() => onStart("browser")}>ChatGPT로 전환</button> : null}
            <button className="button button--primary" type="button" disabled={Boolean(busy)} onClick={onClose}>계속하기</button>
          </> : <>
            <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={onRefresh}>{busy === "status" ? "확인 중…" : "연결 다시 확인"}</button>
            <button className="button button--quiet" type="button" disabled={!canStart} onClick={() => onStart("device_code")}>기기 코드로 로그인</button>
            <button className="button button--primary" type="button" disabled={!canStart} onClick={() => onStart("browser")}>{busy === "start" ? "시작 중…" : "ChatGPT로 로그인"}</button>
          </>}
        </footer>
      </section>
  );
}

function codexAuthTitle(state: CodexAuthState | undefined): string {
  if (!state) return "Codex 연결 확인 중";
  if (state.status === "connected") return `연결 완료 · ${state.auth_label || "ChatGPT 계정"}`;
  if (state.status === "waiting") return state.method === "device_code" ? "기기 코드 입력 대기 중" : "브라우저 로그인 대기 중";
  if (state.status === "cancelling") return "로그인 취소 확인 중";
  if (state.status === "cancelled") return "로그인을 취소했습니다";
  if (state.status === "runtime_error") return "Codex 실행 구성 확인 필요";
  if (state.status === "status_error" || state.status === "unknown") return "연결 상태를 확인하지 못했습니다";
  if (state.status === "failed") return "Codex 로그인 실패";
  return "Codex 로그인이 필요합니다";
}

function codexAuthDetail(state: CodexAuthState | undefined): string {
  if (!state) return "SDK 계정 상태를 확인하고 있습니다.";
  if (state.message) return state.message;
  if (state.status === "waiting") return state.method === "device_code" ? "브라우저의 공식 인증 페이지에서 표시된 코드를 입력해 주세요." : "기본 브라우저에서 로그인을 완료해 주세요.";
  if (state.status === "signed_out") return "앱에서 로그인을 시작하면 기본 브라우저의 공식 인증 화면이 열립니다.";
  if (state.status === "unknown") return "새 로그인을 시작하지 말고 현재 시도의 상태를 다시 확인해 주세요.";
  return "연결 상태를 다시 확인하거나 로그인을 시작할 수 있습니다.";
}

function ProjectSettingsDialog({ project, runId, taskId, onOpenTechStack, onSaved, onClose }: {
  project: RegisteredProject;
  runId: string;
  taskId: string;
  onOpenTechStack(): void;
  onSaved(): Promise<void>;
  onClose(): void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [executable, setExecutable] = useState(project.dotnet_executable || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [diagnostic, setDiagnostic] = useState<DotnetDiagnostic>();
  const [workspaceLocation, setWorkspaceLocation] = useState<ProjectWorkspaceLocation>();
  const [workspaceError, setWorkspaceError] = useState("");
  const [codeStyleProfile, setCodeStyleProfile] = useState<ProjectCodeStyleProfile>();
  const [codeStyleDraft, setCodeStyleDraft] = useState<ProjectCodeStylePreference>(project.code_style_preference || {
    mode: "repository_first",
    fallback_by_language: { python: "pep8", csharp: "microsoft_dotnet" },
    custom_instruction_paths: [],
  });
  const [codeStyleLoading, setCodeStyleLoading] = useState(true);
  const [codeStyleBusy, setCodeStyleBusy] = useState(false);
  const [codeStyleError, setCodeStyleError] = useState("");
  useEffect(() => { ref.current?.showModal(); }, []);
  useEffect(() => {
    let active = true;
    void window.orchestrator.request<ProjectWorkspaceLocation>("projects.workspaceLocation", { projectName: project.name })
      .then((result) => { if (active) setWorkspaceLocation(result); })
      .catch((requestError) => { if (active) setWorkspaceError(errorMessage(requestError)); });
    return () => { active = false; };
  }, [project.name]);
  useEffect(() => {
    let active = true;
    setCodeStyleLoading(true);
    setCodeStyleError("");
    void window.orchestrator.request<ProjectCodeStyleProfile>("projects.codeStyleProfile", { projectName: project.name })
      .then((result) => {
        if (!active) return;
        setCodeStyleProfile(result);
        setCodeStyleDraft(result.preference);
      })
      .catch((requestError) => { if (active) setCodeStyleError(errorMessage(requestError)); })
      .finally(() => { if (active) setCodeStyleLoading(false); });
    return () => { active = false; };
  }, [project.name]);

  const save = async (check: boolean) => {
    setBusy(true);
    setError("");
    setMessage("");
    setDiagnostic(undefined);
    try {
      await window.orchestrator.request<RegisteredProject>("projects.updateDotnet", {
        projectName: project.name, executable,
      });
      await onSaved();
      setMessage("저장했습니다. 다음 실행과 재시도부터 적용됩니다.");
      if (check) {
        const result = await window.orchestrator.request<DotnetDiagnostic>("projects.checkDotnet", {
          projectName: project.name, runId, taskId,
        });
        setDiagnostic(result);
        setError(result.error);
        setMessage(result.error ? "경로는 저장했지만 SDK 확인에 실패했습니다." : "저장했고 SDK 선택을 확인했습니다.");
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };
  const choose = async () => {
    try {
      const path = await window.orchestrator.selectPath("dotnet");
      if (path) { setExecutable(path); setDiagnostic(undefined); setMessage(""); setError(""); }
    } catch (requestError) {
      setError(errorMessage(requestError));
    }
  };
  const previewCodeStyle = async () => {
    setCodeStyleBusy(true);
    setCodeStyleError("");
    try {
      const result = await window.orchestrator.request<ProjectCodeStyleProfile>("projects.previewCodeStylePreference", {
        projectName: project.name,
        preference: codeStyleDraft,
      });
      setCodeStyleProfile(result);
    } catch (requestError) {
      setCodeStyleError(errorMessage(requestError));
    } finally {
      setCodeStyleBusy(false);
    }
  };
  const saveCodeStyle = async () => {
    if (!codeStyleProfile) return;
    setCodeStyleBusy(true);
    setCodeStyleError("");
    try {
      const result = await window.orchestrator.approve<ProjectCodeStyleProfile>("projects.updateCodeStylePreference", {
        projectName: project.name,
        expectedRevision: codeStyleProfile.preference_revision,
        preference: codeStyleDraft,
      });
      if (!result) throw new Error("코드 스타일 설정 저장 결과를 받지 못했습니다.");
      setCodeStyleProfile(result);
      setCodeStyleDraft(result.preference);
      setMessage("코드 스타일 설정을 저장했습니다. 새 작업 그룹부터 적용됩니다.");
      await onSaved();
    } catch (requestError) {
      setCodeStyleError(errorMessage(requestError));
    } finally {
      setCodeStyleBusy(false);
    }
  };
  return (
    <dialog ref={ref} className="modal project-settings-modal" aria-labelledby="project-settings-title" onCancel={(event) => { event.preventDefault(); if (!busy && !codeStyleBusy) onClose(); }}>
      <form className="project-form" onSubmit={(event) => { event.preventDefault(); void save(false); }}>
        <header><h2 id="project-settings-title">{project.name} 설정</h2><button className="icon-button" type="button" aria-label="닫기" disabled={busy || codeStyleBusy} onClick={onClose}><X aria-hidden="true" size={17} /></button></header>
        <section className="project-tech-stack-entry" aria-labelledby="project-tech-stack-title">
          <strong id="project-tech-stack-title">기술 스택 · 언어와 프레임워크</strong>
          <p>새 프로젝트의 기술 스택은 작업의 ‘계획 수정’ 화면에서 정합니다. 만들고 싶은 기능과 원하는 언어·기술을 요청에 적으면 AI가 구성을 추천하고, 확인 후 결정할 수 있습니다.</p>
          <p>기획 자료는 지정 작업에서 선택 사항입니다. 코드 스타일과 .NET 실행 경로는 작업에 적용할 별도 설정입니다.</p>
          <button className="button button--secondary" type="button" disabled={busy || codeStyleBusy} onClick={onOpenTechStack}>기술 스택 계획 열기</button>
        </section>
        <section className="project-workspace-location" aria-labelledby="project-workspace-location-title">
          <div><strong id="project-workspace-location-title">AI 작업공간 기본 위치</strong><span>{workspaceLocation ? workspaceLocation.created ? "사용 중" : "생성 예정" : "확인 중"}</span></div>
          {workspaceLocation ? <ReadonlyPath label="원본 프로젝트" value={workspaceLocation.repo} /> : null}
          {workspaceLocation ? <ReadonlyPath label="작업공간 Root" value={workspaceLocation.root} /> : null}
          {workspaceLocation?.notice_code === "legacy_default_alias" ? <p>기존 기본 설정값을 새 프로젝트 내부 위치로 해석합니다. 설정 파일은 자동으로 다시 쓰지 않습니다.</p> : null}
          {workspaceError ? <p role="alert">{workspaceError}</p> : null}
        </section>
        <CodeStyleProfilePanel
          profile={codeStyleProfile}
          draft={codeStyleDraft}
          loading={codeStyleLoading}
          busy={codeStyleBusy}
          error={codeStyleError}
          onChange={(value) => { setCodeStyleDraft(value); setCodeStyleError(""); }}
          onPreview={() => void previewCodeStyle()}
          onSave={() => void saveCodeStyle()}
        />
        <p>.NET 실행 경로를 비워두면 자동 탐색합니다. 이 PC의 선택 프로젝트에 저장되며, 이미 실행 중인 작업에는 적용되지 않습니다.</p>
        <fieldset disabled={busy}>
          <PathField label="dotnet.exe 경로 (선택)" value={executable} onChange={(value) => { setExecutable(value); setDiagnostic(undefined); setMessage(""); setError(""); }} onChoose={() => void choose()} />
        </fieldset>
        <p>SDK 확인은 경로를 저장한 뒤 선택한 작업 또는 작업 그룹의 작업 디렉터리에서 진행합니다. 작업 디렉터리가 아직 배정되지 않았으면 프로젝트 저장소에서 확인합니다.</p>
        {message ? <p role="status">{message}</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {diagnostic ? <LogView value={diagnostic.log} canCopy={Boolean(diagnostic.log)} /> : null}
        <footer><button className="button button--quiet" type="button" disabled={busy} onClick={() => void save(true)}>{busy ? "처리 중…" : "저장 후 SDK 확인"}</button><button className="button button--primary" type="submit" disabled={busy}>저장</button></footer>
      </form>
    </dialog>
  );
}

function ProjectDialog({ open, draft, busy, intent = "", onChange, onChoosePath, onClose, onSubmit }: { open: boolean; draft: ProjectDraft; busy: boolean; intent?: "" | "existing" | "new"; onChange(draft: ProjectDraft): void; onChoosePath(kind: "repository" | "config" | "planningSource"): void; onClose(): void; onSubmit(event: FormEvent): void; }) {
  const ref = useRef<HTMLDialogElement>(null);
  const requestRevision = useRef(0);
  const [readiness, setReadiness] = useState<GitRepositoryReadiness>();
  const [initialCommit, setInitialCommit] = useState<GitInitialCommitPreview>();
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [commitMessage, setCommitMessage] = useState("Initial commit");
  const [authorName, setAuthorName] = useState("");
  const [authorEmail, setAuthorEmail] = useState("");
  const [saveAuthor, setSaveAuthor] = useState(true);
  const [allowEmpty, setAllowEmpty] = useState(false);
  const [preparationBusy, setPreparationBusy] = useState("");
  const [preparationError, setPreparationError] = useState("");

  const inspect = useCallback(async (repo: string) => {
    const revision = ++requestRevision.current;
    setPreparationBusy("inspect");
    setPreparationError("");
    try {
      const result = await window.orchestrator.request<GitRepositoryReadiness>("projects.inspectGitReadiness", { repo });
      if (revision !== requestRevision.current) return;
      setReadiness(result);
      if (result.kind !== "unborn") {
        setInitialCommit(undefined);
        setSelectedPaths([]);
        return;
      }
      const preview = await window.orchestrator.request<GitInitialCommitPreview>("projects.previewInitialCommit", { repo });
      if (revision !== requestRevision.current) return;
      setInitialCommit(preview);
      setSelectedPaths(preview.changes.filter((change) => change.selected_by_default).map((change) => change.path));
      setAuthorName(preview.author_name);
      setAuthorEmail(preview.author_email);
      setAllowEmpty(false);
    } catch (requestError) {
      if (revision !== requestRevision.current) return;
      setReadiness(undefined);
      setInitialCommit(undefined);
      setSelectedPaths([]);
      setPreparationError(errorMessage(requestError));
    } finally {
      if (revision === requestRevision.current) setPreparationBusy("");
    }
  }, []);

  useEffect(() => { const dialog = ref.current; if (!dialog) return; if (open && !dialog.open) dialog.showModal(); if (!open && dialog.open) dialog.close(); }, [open]);
  useEffect(() => {
    if (!open || !draft.repo.trim()) {
      requestRevision.current += 1;
      setReadiness(undefined);
      setInitialCommit(undefined);
      setSelectedPaths([]);
      setPreparationBusy("");
      setPreparationError("");
      return;
    }
    setReadiness(undefined);
    setInitialCommit(undefined);
    const timer = window.setTimeout(() => void inspect(draft.repo), 250);
    return () => window.clearTimeout(timer);
  }, [draft.repo, inspect, open]);

  const initializeGit = async () => {
    if (!readiness || readiness.kind !== "not_initialized" || preparationBusy) return;
    setPreparationBusy("initialize");
    setPreparationError("");
    try {
      await window.orchestrator.request("projects.previewGitInitialization", { repo: draft.repo });
      const result = await window.orchestrator.approve<GitRepositoryReadiness>("projects.initializeGit", {
        repo: draft.repo,
        expectedKind: readiness.kind,
      });
      if (result) await inspect(draft.repo);
    } catch (requestError) {
      setPreparationError(errorMessage(requestError));
    } finally {
      setPreparationBusy("");
    }
  };

  const createFirstCommit = async () => {
    if (!initialCommit || preparationBusy) return;
    setPreparationBusy("commit");
    setPreparationError("");
    try {
      const result = await window.orchestrator.approve<GitRepositoryReadiness>("projects.createInitialCommit", {
        repo: draft.repo,
        snapshotId: initialCommit.snapshot_id,
        selectedPaths,
        selectionCount: selectedPaths.length,
        message: commitMessage,
        authorName,
        authorEmail,
        saveAuthor,
        allowEmpty,
      });
      if (result) await inspect(draft.repo);
    } catch (requestError) {
      setPreparationError(errorMessage(requestError));
    } finally {
      setPreparationBusy("");
    }
  };

  const toggleInitialPath = (path: string) => {
    setSelectedPaths((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path]);
  };
  const readinessCopy: Record<string, { title: string; detail: string }> = {
    ready: { title: "Git 작업공간을 확인했습니다", detail: readiness?.remote_configured ? "첫 commit과 원격 저장소 연결을 확인했습니다." : "첫 commit을 확인했습니다. 원격 저장소는 나중에 연결해도 됩니다." },
    unborn: { title: "첫 commit이 필요합니다", detail: "포함할 파일과 commit 메시지를 확인해 로컬 기준점을 만드세요." },
    not_initialized: { title: "이 폴더에 Git 준비가 필요합니다", detail: "AI 작업은 변경을 안전하게 나누고 되돌리기 위해 Git이 필요합니다. 로컬 저장소만 만들며 기존 파일과 원격 저장소는 변경하지 않습니다." },
    inside_other_repository: { title: "상위 Git 저장소에 포함된 폴더입니다", detail: "중첩 저장소를 만들지 않고 감지한 상위 저장소를 프로젝트로 선택하세요." },
    git_unavailable: { title: "Git을 먼저 설치해 주세요", detail: "Git 실행 파일을 찾은 뒤 다시 확인하세요." },
    invalid: { title: "프로젝트 폴더로 사용할 수 없습니다", detail: "다른 폴더를 선택하거나 상세 원인을 확인하세요." },
  };
  const copy = readiness ? readinessCopy[readiness.kind] : undefined;
  const authorRequired = Boolean(initialCommit && !initialCommit.readiness.author_configured);
  const canCommit = Boolean(
    initialCommit
      && commitMessage.trim()
      && (selectedPaths.length > 0 || allowEmpty)
      && (!authorRequired || (authorName.trim() && authorEmail.trim())),
  );
  const locallyBusy = Boolean(preparationBusy);
  return (
    <dialog ref={ref} className="modal project-registration-dialog" aria-labelledby="project-registration-title" onCancel={(event) => { event.preventDefault(); onClose(); }} onClose={onClose}>
      <form className="project-form" onSubmit={onSubmit}>
        <header><div><span className="eyebrow">PROJECT REGISTRY</span><h2 id="project-registration-title">{intent === "new" ? "새 프로젝트 만들기" : intent === "existing" ? "기존 프로젝트 열기" : "프로젝트 등록"}</h2></div><button className="icon-button" type="button" aria-label="닫기" onClick={onClose}><X aria-hidden="true" size={17} /></button></header>
        <p>{intent === "new" ? "새 프로그램을 만들 폴더를 선택하세요. 등록한 뒤 만들고 싶은 내용을 입력합니다."
          : "작업할 프로젝트 폴더를 선택하세요. 이미 있는 코드와 작업 기록을 바탕으로 이어서 시작합니다."}</p>
        <label className="field"><span>프로젝트 이름</span><input autoFocus value={draft.name} placeholder="비워두면 폴더 이름 사용" onChange={(event) => onChange({ ...draft, name: event.target.value })} /></label>
        <PathField label="프로젝트 폴더" value={draft.repo} required onChange={(value) => onChange({ ...draft, repo: value })} onChoose={() => onChoosePath("repository")} />
        {draft.repo ? <section className={`git-readiness git-readiness--${readiness?.kind || "checking"}`} aria-live="polite">
          <div className="git-readiness__heading">
            <GitMerge aria-hidden="true" size={17} />
            <div><strong>{preparationBusy === "inspect" ? "Git 상태 확인 중" : copy?.title || "Git 상태를 확인합니다"}</strong>{copy ? <p>{copy.detail}</p> : null}</div>
          </div>
          {readiness?.repository_root ? <ReadonlyPath label="Git 저장소 Root" value={readiness.repository_root} /> : null}
          {readiness?.head_commit ? <p className="muted-copy">기준 commit · <code>{readiness.head_commit.slice(0, 12)}</code>{readiness.main_branch ? <> · branch <code>{readiness.main_branch}</code></> : null}</p> : null}
          {readiness?.diagnostics.map((diagnostic) => <p className="git-readiness__diagnostic" key={diagnostic}>{diagnostic}</p>)}
          {readiness?.kind === "not_initialized" ? <button className="button button--primary" type="button" disabled={locallyBusy} onClick={() => void initializeGit()}>{preparationBusy === "initialize" ? "저장소 만드는 중" : "로컬 Git 저장소 만들기"}</button> : null}
          {readiness?.kind === "inside_other_repository" && readiness.repository_root ? <button className="button button--primary" type="button" disabled={locallyBusy} onClick={() => onChange({ ...draft, repo: readiness.repository_root })}>상위 저장소를 프로젝트로 선택</button> : null}
          {readiness && ["git_unavailable", "invalid"].includes(readiness.kind) ? <button className="button button--quiet" type="button" disabled={locallyBusy} onClick={() => void inspect(draft.repo)}>다시 확인</button> : null}
          {readiness?.kind === "unborn" && initialCommit ? <div className="initial-commit-review">
            <div className="initial-commit-review__summary"><strong>첫 commit에 포함할 파일</strong><span>{selectedPaths.length}/{initialCommit.changes.length} 선택</span></div>
            {initialCommit.changes.length ? <div className="initial-commit-files">
              {initialCommit.changes.map((change) => <label key={change.path} className="initial-commit-file">
                <input type="checkbox" checked={selectedPaths.includes(change.path)} onChange={() => toggleInitialPath(change.path)} />
                <code>{change.path}</code>
                <span>{change.exclusion_reason ? "기본 제외" : change.staged ? "staged" : change.status}</span>
              </label>)}
            </div> : <p>포함할 파일이 없습니다. 빈 첫 commit을 만들려면 아래 항목을 직접 확인하세요.</p>}
            <label className="field"><span>첫 commit 메시지</span><input value={commitMessage} onChange={(event) => setCommitMessage(event.target.value)} /></label>
            {authorRequired ? <div className="initial-commit-author">
              <label className="field"><span>작성자 이름</span><input value={authorName} onChange={(event) => setAuthorName(event.target.value)} /></label>
              <label className="field"><span>작성자 이메일</span><input type="email" value={authorEmail} onChange={(event) => setAuthorEmail(event.target.value)} /></label>
              <label className="check-field"><input type="checkbox" checked={saveAuthor} onChange={(event) => setSaveAuthor(event.target.checked)} />이 프로젝트의 Git 작성자로 저장</label>
            </div> : null}
            {!initialCommit.changes.length ? <label className="check-field"><input type="checkbox" checked={allowEmpty} onChange={(event) => setAllowEmpty(event.target.checked)} />파일 없이 빈 첫 commit 만들기</label> : null}
            <button className="button button--primary" type="button" disabled={!canCommit || locallyBusy} onClick={() => void createFirstCommit()}>{preparationBusy === "commit" ? "첫 commit 만드는 중" : "첫 commit 만들기"}</button>
          </div> : null}
          {preparationError ? <p role="alert" className="git-readiness__diagnostic">{preparationError}</p> : null}
        </section> : null}
        <PathField label="설정 파일 (선택)" value={draft.configPath} onChange={(value) => onChange({ ...draft, configPath: value })} onChoose={() => onChoosePath("config")} />
        <PathField label="기획문서 디렉터리 (선택)" value={draft.planningSourceDir} onChange={(value) => onChange({ ...draft, planningSourceDir: value })} onChoose={() => onChoosePath("planningSource")} />
        <footer><button className="button button--quiet" type="button" onClick={onClose}>취소</button><button className="button button--primary" type="submit" disabled={!draft.repo || readiness?.kind !== "ready" || busy || locallyBusy}>{busy ? "등록 중" : "등록"}</button></footer>
      </form>
    </dialog>
  );
}

function PathField({ label, value, required = false, onChange, onChoose }: { label: string; value: string; required?: boolean; onChange(value: string): void; onChoose(): void; }) {
  return <label className="field"><span>{label}</span><span className="path-control"><input value={value} required={required} onChange={(event) => onChange(event.target.value)} /><button className="button button--quiet" type="button" onClick={onChoose}><FolderOpen aria-hidden="true" size={15} />선택</button></span></label>;
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div><dt>{label}</dt><dd className={mono ? "mono" : undefined}>{value}</dd></div>; }

function ReadonlyPath({ label, value, status = "" }: { label: string; value: string; status?: string }) {
  const [copyStatus, setCopyStatus] = useState("");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopyStatus("복사됨");
    } catch (copyError) {
      setCopyStatus(`복사 실패: ${errorMessage(copyError)}`);
    }
  };
  return <div className="readonly-path"><div><span>{label}</span>{status ? <small>{status}</small> : null}</div><code title={value || undefined}>{value || "-"}</code><button className="button button--quiet" type="button" disabled={!value} onClick={() => void copy()}><Copy aria-hidden="true" size={14} />경로 복사</button>{copyStatus ? <small role="status">{copyStatus}</small> : null}</div>;
}

function IntegrationControlStatus({ control, repoPath, onRefresh }: {
  control: IntegrationControl;
  repoPath: string;
  onRefresh(): void | Promise<void>;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const labels: Record<string, string> = {
    not_ready: "작업 실행 대기",
    needs_verification: control.reason_code === "branch_mismatch" ? "통합 검증 보류" : "최신 Main 통합·검증 필요",
    verifying: "통합 검증 중",
    verified: control.reason_code === "main_dirty_disjoint" ? "통합 검증 완료 · 로컬 변경 보존" : "통합 검증 완료",
    stale: control.can_verify ? "재검증 필요" : "재검증 보류",
    conflict: "통합 충돌",
    apply_blocked: "검증 완료 · Main 반영 보류",
    main_push_pending: "Main 반영 완료 · Push 확인 필요",
    applied: "Main 반영 완료",
    unknown: control.reason_code === "main_apply_recoverable" ? "Main 반영 중단 · 복구 승인 가능" : control.reason_code === "main_apply_interrupted" ? "Main 반영 중단 · 원본 확인 필요" : "Main 상태 확인 필요",
  };
  const warning = ["stale", "conflict", "apply_blocked", "main_push_pending", "unknown"].includes(control.status)
    || control.reason_code === "branch_mismatch" || Boolean(control.main_dirty);
  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try { await onRefresh(); }
    finally { setRefreshing(false); }
  };
  return <div className={`verification-progress${warning ? " verification-progress--warning" : ""}`} role="status">
    <div className="verification-progress__heading"><span><ShieldCheck aria-hidden="true" size={16} /><strong>{labels[control.status] || "통합 상태"}</strong></span></div>
    <p>{control.reason}</p>
    {control.current_main_head ? <p className="muted-copy">현재 Main · <code>{control.current_main_head.slice(0, 12)}</code>{control.verified_main_head ? <> · 검증 Main · <code>{control.verified_main_head.slice(0, 12)}</code></> : null}</p> : null}
    {control.main_dirty ? <ReadonlyPath label="Main 작업 폴더" value={repoPath} status={control.status === "main_push_pending" ? "로컬 미커밋 변경은 Push 대상에 포함되지 않습니다." : control.can_apply_main ? "겹치지 않는 로컬 변경은 유지됩니다." : "변경을 확인한 뒤 아래에서 상태를 다시 확인하세요."} /> : null}
    {["apply_blocked", "unknown"].includes(control.status) || control.reason_code === "branch_mismatch" || (control.status === "stale" && !control.can_verify) ? <div className="operation-actions">
      <button className="button button--primary" type="button" disabled={refreshing} onClick={() => void refresh()}>
        <RefreshCw aria-hidden="true" className={refreshing ? "spin" : undefined} size={16} />{refreshing ? "Main 상태 확인 중" : "Main 상태 다시 확인"}
      </button>
    </div> : null}
  </div>;
}

function EmptyState({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) { return <div className="empty-state">{icon}<strong>{title}</strong><p>{detail}</p></div>; }
function LoadingRows() { return <div className="loading-rows" aria-label="작업 그룹 불러오는 중"><span /><span /><span /></div>; }

function profileOverrides(run: RunState, profiles: Record<string, TaskProfileSelection>, taskIds?: string[]) {
  const selected = taskIds ? new Set(taskIds) : undefined;
  const agentOverrides: Record<string, string> = {};
  const modelOverrides: Record<string, string> = {};
  const reasoningEffortOverrides: Record<string, string> = {};
  for (const task of run.tasks) {
    if (selected && !selected.has(task.id)) continue;
    const profile = profiles[task.id];
    if (!profile) continue;
    if (profile.agentId !== task.agent_id) agentOverrides[task.id] = profile.agentId;
    if (profile.model !== task.model) modelOverrides[task.id] = profile.model;
    if (profile.reasoningEffort !== task.reasoning_effort) reasoningEffortOverrides[task.id] = profile.reasoningEffort;
  }
  return { agentOverrides, modelOverrides, reasoningEffortOverrides };
}

function planIsApproved(run: RunState): boolean {
  return !run.plan_revision || run.plan_approved_revision === run.plan_revision;
}

function taskPlanPayload(task: WorkTask, profile: TaskProfileSelection | undefined, options: ProviderProfile[]) {
  const selectedProfile = profile || {
    agentId: task.agent_id,
    model: task.model,
    reasoningEffort: task.reasoning_effort,
  };
  const selectedOption = options.find((option) => option.agent_id === selectedProfile.agentId && option.model === selectedProfile.model);
  return {
    id: task.id,
    title: task.title,
    description: task.description,
    capabilities: task.capabilities,
    depends_on: task.dependencies,
    is_prerequisite: task.is_prerequisite,
    acceptance_criteria: task.acceptance_criteria,
    expected_paths: task.expected_paths,
    forbidden_paths: task.forbidden_paths,
    verify_commands: task.verify_commands,
    risk_level: task.risk_level,
    provider_id: selectedOption?.provider_id || task.provider_id,
    model: selectedProfile.model,
    reasoning_effort: selectedProfile.reasoningEffort,
  };
}

function emptyTaskDraft(id: string): WorkTask {
  return {
    id,
    title: "",
    description: "",
    capabilities: [],
    acceptance_criteria: [],
    dependencies: [],
    is_prerequisite: false,
    conflict_dependencies: [],
    conflict_group: [],
    action_results: [],
    result_history: [],
    expected_paths: [],
    forbidden_paths: [],
    verify_commands: [],
    risk_level: "medium",
    status: "pending",
    readiness: "ready",
    blocked_by: [],
    agent_id: "",
    provider_id: "",
    model: "",
    reasoning_effort: "",
    effective_model: "",
    effective_reasoning_effort: "",
    review_status: "not_required",
    error: "",
    worktree: "",
    started_commit: "",
    completed_commit: "",
    progress_phase: "",
    progress_detail: "",
    progress_updated_at: "",
  };
}

function nextTaskId(tasks: WorkTask[]): string {
  const existing = new Set(tasks.map((task) => task.id));
  let index = tasks.length + 1;
  while (existing.has(`task-${index}`)) index += 1;
  return `task-${index}`;
}

function splitLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function renameRecordKey<T>(record: Record<string, T>, before: string, after: string): Record<string, T> {
  if (!(before in record)) return record;
  const next = { ...record, [after]: record[before] };
  delete next[before];
  return next;
}

function runSummaryFromState(run: RunState, previous?: RunSummary): RunSummary {
  const situation = run.execution_control?.situation || previous?.execution_situation || "unavailable";
  const attentionReasons: string[] = [];
  if (run.stage === "needs_clarification") attentionReasons.push("planning_questions");
  if (run.stage === "planned" && !planIsApproved(run)) attentionReasons.push("plan_confirmation");
  if (run.tasks.some((task) => task.status === "waiting") || run.failed_step === "manual_completion") attentionReasons.push("manual_completion");
  if (situation === "resumable") attentionReasons.push("resume");
  if (run.stage === "failed") attentionReasons.push("failure_recovery");
  if (situation === "attention_required") attentionReasons.push("execution_attention");
  if (situation === "status_unknown") attentionReasons.push("status_unknown");
  if (["ready_to_merge", "verified", "work_branch_pushed", "merged"].includes(run.stage)) attentionReasons.push("integration");
  if (run.stage === "pushed" && previous?.attention_reasons.includes("deployment")) attentionReasons.push("deployment");
  return {
    id: run.id,
    summary: run.summary,
    stage: run.stage,
    updated_at: run.updated_at,
    created_at: run.created_at,
    task_count: run.tasks.length,
    completed_task_count: run.tasks.filter((task) => ["completed", "merged"].includes(task.status)).length,
    archived: Boolean(run.archive),
    archived_at: run.archive?.archived_at || "",
    cleanup_status: run.archive?.cleanup_status || "",
    failed_task_count: run.tasks.filter((task) => task.status === "failed").length,
    waiting_task_count: run.tasks.filter((task) => task.status === "waiting").length,
    plan_is_approved: planIsApproved(run),
    attention_reasons: [...new Set(attentionReasons)],
    execution_situation: situation,
    pipeline_complete: run.stage === "deployed" || (run.stage === "pushed" && Boolean(previous?.pipeline_complete)),
    checked_at: run.execution_control?.checked_at || previous?.checked_at || run.updated_at,
  };
}

function runDisplayName(summary: string, runId: string, fallback = "이름 없는 작업 그룹"): string {
  const value = summary.trim();
  if (!value) return fallback;
  return value.includes("\uFFFD") ? `이전 작업 그룹 · ${runId.slice(-8)}` : value;
}

function providerProfileKey(profile?: ProviderProfile): string { return profile ? profileKey(profile.agent_id, profile.model) : ""; }
function profileKey(agentId: string, model: string): string { return `${agentId}\u001f${model}`; }
function capabilityKey(capabilities: string[]): string { return [...new Set(capabilities.map((value) => value.trim().toLocaleLowerCase("en-US")).filter(Boolean))].sort().join("\u001f"); }
function providerProfileLabel(profile: ProviderProfile): string { const provider = providerDisplayName(profile.provider_id); const model = profile.model || (profile.provider_id === "codex" ? "자동 · gpt-6.1-sol" : "자동 선택"); return `${model} · ${provider}${profile.is_default && Boolean(profile.model) && profile.model === profile.configured_model ? " · 기본" : ""}`; }
function taskProviderProfileLabel(option: ProviderProfile, task: WorkTask, selection: TaskProfileSelection): string { const selected = option.agent_id === selection.agentId && option.model === selection.model; if (selected && !option.model) return taskModelDisplayValue(task, option.provider_id); return providerProfileLabel(option); }
function providerDisplayName(providerId: string): string { if (providerId === "codex") return "Codex"; if (providerId === "claude") return "Claude"; if (providerId === "nvidia") return "NVIDIA · 시험"; return providerId; }
function providerDefaultReasoningLabel(providerId?: string): string { const provider = providerDisplayName(providerId || "") || "AI 제공자"; return `자동 선택 · ${provider}`; }
function taskDefaultReasoningLabel(task: WorkTask, providerId?: string): string { if (providerId === "nvidia") return providerDefaultReasoningLabel(providerId); return taskReasoningDisplayValue(task, providerId); }
function taskModelDisplayValue(task: WorkTask, providerId?: string, selectedModel = task.model): string {
  const provider = providerDisplayName(providerId || task.provider_id) || "AI 제공자";
  const automatic = task.profile_source === "mode" && Boolean(task.model_selection_reason) && selectedModel === task.model;
  if (task.status !== "pending" && task.effective_model) return `${automatic ? "자동 · " : ""}${task.effective_model}${task.model ? "" : " · 자동 선택"}`;
  if (selectedModel) return `${automatic ? "자동 · " : ""}${selectedModel}`;
  if (["completed", "merged"].includes(task.status)) return `실행 모델 기록 없음 · ${provider}`;
  return `자동 선택 · ${provider}`;
}
function taskReasoningDisplayValue(task: WorkTask, providerId?: string, selectedEffort = task.reasoning_effort): string { const provider = providerDisplayName(providerId || task.provider_id) || "AI 제공자"; if (task.status !== "pending" && task.effective_reasoning_effort) return `${task.effective_reasoning_effort}${task.reasoning_effort ? "" : " · 자동 선택"}`; if (selectedEffort) return selectedEffort; if (["completed", "merged"].includes(task.status)) return `추론 강도 기록 없음 · ${provider}`; return `자동 선택 · ${provider}`; }
function providerStatusText(status: ProviderStatus): string { return `${providerDisplayName(status.id)} · ${status.auth_label || (status.available ? "사용 가능" : "사용 불가")}`; }
function providerStatusState(status: ProviderStatus): "ready" | "attention" | "error" { if (status.available) return "ready"; if (status.auth_method === "none") return "attention"; return "error"; }
function providerAuthDetail(status: ProviderStatus): string { if (status.id === "nvidia") return status.available ? "OpenCode CLI와 키 등록을 확인했습니다. 실제 인증·모델 연결은 실행 시 확인합니다." : "OpenCode CLI를 설치하고 설정 → AI 연결에서 NVIDIA API 키를 등록하세요."; if (status.auth_method === "chatgpt") return "ChatGPT 구독 사용량으로 Codex를 실행합니다."; if (status.auth_method === "claude_subscription") return "Claude 구독 계정으로 CLI를 실행합니다."; if (status.auth_method === "api_key") return status.id === "claude" ? "Anthropic API 사용량 기준으로 과금됩니다." : "OpenAI API 사용량 기준으로 별도 과금됩니다."; if (status.auth_method === "none") return status.id === "claude" ? "터미널에서 claude auth login을 실행한 뒤 새로고침하세요." : "Codex를 실행하려면 로그인이 필요합니다."; if (status.auth_method === "external") return "외부 model provider의 인증을 사용합니다."; if (status.auth_method === "error") return status.id === "claude" ? "Claude CLI 인증 상태를 확인하지 못했습니다." : "SDK 인증 상태를 확인하지 못했습니다."; return status.available ? "AI 제공자 실행 파일을 확인했습니다." : "AI 제공자를 사용할 수 없습니다."; }
function taskStatusIcon(status: string) { if (["completed", "merged"].includes(status)) return <CheckCircle2 aria-hidden="true" size={15} />; if (status === "failed") return <XCircle aria-hidden="true" size={15} />; if (["running", "reviewing", "revising"].includes(status)) return <Activity aria-hidden="true" size={15} />; return <Clock3 aria-hidden="true" size={15} />; }
function stageTone(stage: string): string { if (["verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(stage)) return "success"; if (stage === "failed") return "danger"; if (stage === "needs_clarification") return "warning"; if (stage === "executing") return "active"; return "neutral"; }
function taskTone(task: WorkTask): string { if (["completed", "merged"].includes(task.status)) return "success"; if (task.status === "failed") return "danger"; if (["running", "reviewing", "revising"].includes(task.status)) return "active"; if (task.readiness === "blocked") return "muted"; return "neutral"; }
function readyCount(tasks: WorkTask[]): number { return tasks.filter((task) => task.readiness === "ready").length; }
function clamp(value: number, min: number, max: number): number { return Math.min(max, Math.max(min, value)); }
function riskLabel(risk: string): string { return { low: "낮음", medium: "보통", high: "높음" }[risk] || risk; }
function profileLabel(run: RunState): string { const model = run.planning_model || run.planning_provider_id || "기본 모델"; return run.planning_reasoning_effort ? `${model} · ${run.planning_reasoning_effort}` : model; }
function formatActivityTime(value: string): string { const date = new Date(value); if (Number.isNaN(date.getTime())) return value || "-"; return new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date); }
function formatDate(value: string): string { const date = new Date(value); if (Number.isNaN(date.getTime())) return value || "-"; return new Intl.DateTimeFormat("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date); }
function formatDuration(seconds: number): string { const normalized = Math.max(0, seconds); const minutes = Math.floor(normalized / 60); return minutes ? `${minutes}분 ${normalized % 60}초 경과` : `${normalized}초 경과`; }
function formatElapsed(value: string): string { const started = new Date(value).getTime(); if (Number.isNaN(started)) return "진행 중"; const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000)); const minutes = Math.floor(seconds / 60); return minutes ? `${minutes}분 ${seconds % 60}초 경과` : `${seconds}초 경과`; }
function boundedLogDisplay(value: string): string { if (value.length <= RENDERER_LOG_DISPLAY_LIMIT_CHARACTERS) return value; return `[UI 성능을 위해 최근 ${RENDERER_LOG_DISPLAY_LIMIT_CHARACTERS / 1024} KiB만 표시합니다. 전체 내용은 작업 로그 파일에 보존되어 있습니다.]\n\n…${value.slice(-RENDERER_LOG_DISPLAY_LIMIT_CHARACTERS)}`; }
function isBackendRecoveryError(message: string): boolean {
  return Boolean(message) && (
    /Python (?:(?:control|planning|work) )?backend (?:is not running|exited|stopped|communication closed)/i.test(message) ||
    message.includes("Backend 조회 요청이") ||
    message.includes("RPC request timed out")
  );
}
function rawErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
function runLockConflictOperation(message: string, runId: string): string {
  const marker = `run ${runId} is already locked (operation=`;
  const index = message.indexOf(marker);
  if (index < 0) return "";
  const operation = message.slice(index + marker.length).match(/^([^,()\s]+),/)?.[1] || "";
  if (["unknown", "planning-chat", "planning-preview", "effort-policy", "execution-control", "usage", "revision-proposal", "revision-request"].includes(operation)) return "";
  return operation;
}
function errorMessage(error: unknown): string {
  const message = rawErrorMessage(error);
  if (message.includes("directed planning requires a specific user request")) {
    return "지정 작업으로 계획하려면 요청할 작업 내용을 입력해 주세요.";
  }
  if (
    message.includes(
      "directory planning clarification requires best-effort tasks from inspected sources",
    )
  ) {
    return "기획 AI가 기획문서에서 확인한 작업 초안 없이 질문만 반환했고 자동 보정에도 실패했습니다.";
  }
  if (message.includes("main worktree has uncommitted changes")) {
    return "Main 작업공간에 커밋되지 않은 변경이 있어 최신화를 중단했습니다.";
  }
  if (
    message.includes("run is not safe to delete while lock is active")
    || message.includes("실행 잠금 상태가 active")
  ) {
    return "이 작업 그룹에서 실행 중인 작업이 있습니다. 진행 작업을 먼저 중단한 뒤 삭제해 주세요.";
  }
  if (
    message.includes("run is not safe to delete while lock is unverifiable")
    || message.includes("실행 잠금 상태가 unverifiable")
  ) {
    return "작업 그룹 잠금의 소유 프로세스를 확인할 수 없어 삭제하지 않았습니다. 실행 엔진을 재시작한 뒤 다시 시도해 주세요.";
  }
  if (
    message.includes("run deletion timed out") ||
    message.includes("작업 그룹 삭제가 제한시간을 초과했습니다") ||
    message.includes("작업 그룹 삭제 요청이")
  ) {
    return "작업 그룹 삭제가 제한시간 안에 끝나지 않았습니다. Git 작업공간 상태를 새로고침한 뒤 다시 시도해 주세요.";
  }
  return message;
}
function isRunState(value: unknown): value is RunState { return Boolean(value && typeof value === "object" && "stage" in value && "tasks" in value); }
function localizePlanningText(value: string): string { return value.replace("Implementation scope is not specified.", "구현 대상 확인이 필요합니다.").replace("Which feature, change request, or planning topic should this implementation plan cover?", "어떤 기능, 변경 요청 또는 기획 영역을 기준으로 구현 계획을 작성할까요?"); }
function localizeEvent(value: string, purpose: "plan" | "chat" | "apply" = "plan"): string {
  const labels: Record<string, string> = { "planning document received": "기획문서를 받았습니다.", "planning document reviewed": "기획문서 검토를 완료했습니다.", "planning interrupted by user": "사용자가 기획 AI 작업을 중단했습니다.", "clarification answers received": "추가 질문 답변을 받았습니다.", "planning message received": "기획 AI 대화 메시지를 받았습니다.", "planning chat message received": "대화 메시지를 받았습니다.", "planning chat response received": "기획 AI 답변을 받았습니다.", "planning apply requested": "대화 내용을 계획과 작업으로 반영하고 있습니다.", "planning apply requested from chat": "채팅 요청을 계획과 작업으로 반영하고 있습니다.", "tasks decomposed and agents selected": "작업 분해와 Agent 선택을 완료했습니다.", "shared run worktree prepared": "작업 그룹 공유 작업공간과 작업 branch를 준비했습니다.", "agent work started": "Agent 작업을 시작했습니다.", "all agent tasks completed": "모든 Agent 작업이 완료됐습니다.", "verification commands passed": "검증 명령을 통과했습니다.", "shared run workspace commit verified": "공유 작업공간 commit 검증을 완료했습니다.", "verification failed": "검증에 실패했습니다.", "verified shared work branch pushed": "검증된 작업 branch를 Push했습니다.", "verified integration commit applied to main": "검증한 통합 commit을 Main에 반영했습니다.", "verified shared work commit applied and main branch pushed": "검증된 작업 commit을 Main에 반영하고 Main을 Push했습니다.", "shared run worktree and local branch cleaned": "작업 그룹 공유 작업공간과 로컬 작업 branch를 정리했습니다.", "main branch pushed": "Main 브랜치를 Push했습니다.", "deployment completed": "배포를 완료했습니다." };
  if (labels[value]) return labels[value];
  const attempt = value.match(/^planning agent attempt (\d+) started/);
  if (attempt) return planningPurposeActivity(purpose);
  const failedAttempt = value.match(/^planning agent attempt \d+ failed:/);
  if (failedAttempt) return purpose === "chat"
    ? "기획 AI 답변 생성에 실패했습니다."
    : purpose === "apply"
      ? "요청 내용을 계획에 반영하지 못했습니다."
      : "계획 생성에 실패했습니다.";
  const prompt = value.match(/^planning prompt prepared: (\d+) characters$/);
  if (prompt) return `기획 요청 ${Number(prompt[1]).toLocaleString("ko-KR")}자를 준비했습니다.`;
  const chatPrompt = value.match(/^planning chat prompt prepared: (\d+) characters$/);
  if (chatPrompt) return `대화 prompt ${Number(chatPrompt[1]).toLocaleString("ko-KR")}자를 준비했습니다.`;
  if (/^planning chat turn \d+ started/.test(value)) {
    return "기획 AI가 답변을 생성하고 있습니다.";
  }
  const sourceIndex = value.match(
    /^planning source index (reused|refreshed): (\d+) documents, (\d+) updated, (\d+) reused$/,
  );
  if (sourceIndex) {
    const action = sourceIndex[1] === "reused" ? "기존 색인을 재사용했습니다" : "색인을 갱신했습니다";
    return `기획문서 ${Number(sourceIndex[2]).toLocaleString("ko-KR")}개 · ${action}.`;
  }
  if (value === "planning scope selected: directed") {
    return "지정 작업과 관련된 기획문서만 확인합니다.";
  }
  if (value === "planning scope selected: auto") {
    return "기획문서에서 다음 미완료 작업을 탐색합니다.";
  }
  if (value === "planning transport selected: codex SDK") {
    return "Codex SDK로 기획을 실행합니다.";
  }
  if (
    value === "planning conversation continued on existing Codex SDK thread"
  ) {
    return "기존 Codex 대화를 이어서 처리합니다.";
  }
  if (value === "planning conversation restored on new Codex SDK thread") {
    return "저장된 문맥으로 새 Codex 대화를 복구합니다.";
  }
  const sdkIdleTimeout = value.match(
    /planning received no Codex SDK activity for ([0-9.]+) seconds/,
  );
  if (sdkIdleTimeout) {
    return `Codex SDK에서 ${sdkIdleTimeout[1]}초 동안 새 진행 이벤트가 없어 기획을 중단했습니다.`;
  }
  const codexProgress = value.match(
    /^codex sdk progress: ([a-z_]+)(?: \| (.*))?$/,
  );
  if (codexProgress) {
    const waiting = providerRetryWait(codexProgress[1], codexProgress[2] || "");
    if (waiting) return waiting;
    const progressLabels: Record<string, string> = {
      turn_started: "Codex가 요청 처리를 시작했습니다.",
      analyzing_request: "요청과 기획문서를 분석하고 있습니다.",
      organizing_plan: "작업 순서를 정리하고 있습니다.",
      plan_step: "계획 단계를 진행하고 있습니다.",
      searching_files: "관련 파일을 검색하고 있습니다.",
      reading_documents: "관련 문서를 읽고 있습니다.",
      checking_repository: "저장소 상태와 변경 내용을 확인하고 있습니다.",
      analyzing_project: "프로젝트 정보를 분석하고 있습니다.",
      running_command: "필요한 확인 명령을 실행하고 있습니다.",
      applying_changes: "파일 변경을 적용하고 있습니다.",
      calling_tool: "필요한 도구를 실행하고 있습니다.",
      searching_web: "관련 자료를 검색하고 있습니다.",
      inspecting_image: "첨부 이미지를 확인하고 있습니다.",
      compacting_context: "작업 문맥을 정리하고 있습니다.",
      coordinating_agents: "보조 작업을 조정하고 있습니다.",
      writing_response: planningPurposeActivity(purpose),
      response_received: "기획 응답을 받아 검증하고 있습니다.",
    };
    const label = progressLabels[codexProgress[1]] || "기획을 진행하고 있습니다.";
    return codexProgress[2] ? `${label} · ${codexProgress[2]}` : label;
  }
  if (value === "planning result cache miss") return "재사용할 계획이 없어 새 계획을 생성합니다.";
  return localizePlanningText(value);
}
