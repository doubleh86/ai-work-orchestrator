import { contextBridge, ipcRenderer } from "electron";

import type {
  ApprovedRpcMethod,
  DesktopApi,
  PathSelectionKind,
  RpcMethod,
  RpcParams,
} from "../shared/rpc";
import type {
  StoredWorkNotification,
  WorkNotificationDismissScope,
  WorkNotificationSettings,
  WorkNotificationSnapshot,
} from "../shared/workNotifications";

const allowedMethods = new Set<RpcMethod>([
  "system.hello",
  "connections.externalGuide",
  "connections.registerExternal",
  "runs.resultArtifact",
  "runs.registerResult",
  "runs.launchResult",
  "runs.recordUserCheck",
  "auth.claude.status",
  "projects.list",
  "projects.inspectGitReadiness",
  "projects.previewGitInitialization",
  "projects.previewInitialCommit",
  "projects.add",
  "projects.updatePlanningSource",
  "projects.updateDotnet",
  "projects.capabilities",
  "projects.codeStyleProfile",
  "projects.previewCodeStylePreference",
  "planning.inspectRepositoryMaturity",
  "planning.previewBootstrap",
  "planning.generateFeaturePlan",
  "projects.workspaceLocation",
  "projects.checkDotnet",
  "projects.mainChanges",
  "projects.mainChangeDiff",
  "projects.refreshMainRemote",
  "providers.planning",
  "providers.execution",
  "providers.status",
  "providers.accountUsage",
  "planning.refreshIndex",
  "runs.list",
  "runs.activeGroups",
  "runs.attentionItems",
  "runs.archivePlan",
  "runs.get",
  "runs.getPlanningPreview",
  "runs.planningPreviewStatus",
  "runs.previewEffortMode",
  "runs.usage",
  "runs.setEffortMode",
  "runs.cancelEffortReservation",
  "runs.applyEffortModeToPlan",
  "tasks.retryContext",
  "tasks.saveRetryInstruction",
  "runs.resultRevisions",
  "runs.proposeResultRevision",
  "runs.createResultRevision",
  "runs.preparePlanning",
  "runs.runPlanning",
  "runs.start",
  "runs.sendPlanningMessage",
  "runs.requestDirectionChange",
  "runs.previewPlanningApply",
  "runs.applyPlanningPreview",
  "runs.applyPlanningConversation",
  "runs.confirmTechStack",
  "runs.configureBootstrapInstructions",
  "tasks.log",
  "runs.execute",
  "runs.resume",
  "runs.controlChat",
  "runs.cancelChatControl",
  "runs.requestStop",
  "runs.recoveryPlan",
  "operations.get",
  "operations.latest",
  "runs.integrationConflict",
  "runs.prepareConflictResolution",
  "tasks.execute",
  "tasks.retry",
  "tasks.repairFromChat",
  "tasks.updateExecutionProfile",
  "tasks.complete",
  "tasks.completeManualVerification",
  "tasks.handoffToAi",
  "tasks.deferManual",
  "tasks.resumeManual",
  "runs.verify",
  "runs.verifyAndRepair",
  "runs.updatePlan",
  "runs.confirmPlan",
  "workspaces.list",
  "locks.get",
]);

const api: DesktopApi = {
  mcpConnectionCommand() {
    return ipcRenderer.invoke("orchestrator:mcp-command");
  },
  registerCodexMcp() {
    return ipcRenderer.invoke("orchestrator:mcp-register-codex");
  },
  registerCodexPlanning() {
    return ipcRenderer.invoke("orchestrator:mcp-register-planning");
  },
  openCodexInstallGuide() {
    return ipcRenderer.invoke("orchestrator:codex-install-guide");
  },
  openClaudeLogin() {
    return ipcRenderer.invoke("orchestrator:claude-login");
  },
  nvidiaCredentialStatus() {
    return ipcRenderer.invoke("orchestrator:nvidia-credential-status");
  },
  saveNvidiaCredential(key: string, options) {
    return ipcRenderer.invoke("orchestrator:nvidia-credential-save", key, options);
  },
  deleteNvidiaCredential(id) {
    return ipcRenderer.invoke("orchestrator:nvidia-credential-delete", id);
  },
  setNvidiaCredentialRouting(defaultKeyId, modelBindings) {
    return ipcRenderer.invoke("orchestrator:nvidia-credential-routing", defaultKeyId, modelBindings);
  },
  onOpenProjectSettings(callback: () => void): () => void {
    const listener = () => callback();
    ipcRenderer.on("orchestrator:open-project-settings", listener);
    return () => ipcRenderer.removeListener("orchestrator:open-project-settings", listener);
  },
  onOpenCodexAuth(callback: () => void): () => void {
    const listener = () => callback();
    ipcRenderer.on("orchestrator:open-codex-auth", listener);
    return () => ipcRenderer.removeListener("orchestrator:open-codex-auth", listener);
  },
  codexAuthStatus() {
    return ipcRenderer.invoke("orchestrator:codex-auth-status");
  },
  startCodexAuth(method, requestId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-start", method, requestId);
  },
  connectCodexApiKey(apiKey, requestId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-api-key", apiKey, requestId);
  },
  getCodexAuth(attemptId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-get", attemptId);
  },
  cancelCodexAuth(attemptId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-cancel", attemptId);
  },
  reopenCodexAuth(attemptId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-reopen", attemptId);
  },
  copyCodexDeviceCode(attemptId) {
    return ipcRenderer.invoke("orchestrator:codex-auth-copy-code", attemptId);
  },
  onNotificationsChanged(callback: (snapshot: WorkNotificationSnapshot) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, snapshot: WorkNotificationSnapshot) => callback(snapshot);
    ipcRenderer.on("orchestrator:notifications-changed", listener);
    return () => ipcRenderer.removeListener("orchestrator:notifications-changed", listener);
  },
  onNotificationOpen(callback: (notification: StoredWorkNotification) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, notification: StoredWorkNotification) => callback(notification);
    ipcRenderer.on("orchestrator:notification-open", listener);
    return () => ipcRenderer.removeListener("orchestrator:notification-open", listener);
  },
  listNotifications(refreshScope?: string): Promise<WorkNotificationSnapshot> {
    return (refreshScope === undefined ? ipcRenderer.invoke("orchestrator:notifications-list")
      : ipcRenderer.invoke("orchestrator:notifications-list", refreshScope)) as Promise<WorkNotificationSnapshot>;
  },
  markNotificationRead(eventId: string): Promise<WorkNotificationSnapshot> {
    return ipcRenderer.invoke("orchestrator:notifications-mark-read", eventId) as Promise<WorkNotificationSnapshot>;
  },
  markAllNotificationsRead(): Promise<WorkNotificationSnapshot> {
    return ipcRenderer.invoke("orchestrator:notifications-mark-all-read") as Promise<WorkNotificationSnapshot>;
  },
  dismissNotification(eventId: string): Promise<WorkNotificationSnapshot> {
    return ipcRenderer.invoke("orchestrator:notifications-dismiss", eventId) as Promise<WorkNotificationSnapshot>;
  },
  dismissNotifications(scope: WorkNotificationDismissScope): Promise<WorkNotificationSnapshot> {
    return ipcRenderer.invoke("orchestrator:notifications-dismiss-many", scope) as Promise<WorkNotificationSnapshot>;
  },
  updateNotificationSettings(settings: WorkNotificationSettings): Promise<WorkNotificationSnapshot> {
    return ipcRenderer.invoke("orchestrator:notifications-settings", settings) as Promise<WorkNotificationSnapshot>;
  },
  request<Result>(method: RpcMethod, params: RpcParams = {}): Promise<Result> {
    if (!allowedMethods.has(method)) {
      return Promise.reject(new Error(`Unsupported RPC method: ${method}`));
    }
    return ipcRenderer.invoke("orchestrator:request", method, params) as Promise<Result>;
  },
  approve<Result>(
    method: ApprovedRpcMethod,
    params: RpcParams = {},
  ): Promise<Result | null> {
    return ipcRenderer.invoke(
      "orchestrator:approved-request",
      method,
      params,
    ) as Promise<Result | null>;
  },
  selectPath(kind: PathSelectionKind): Promise<string | null> {
    return ipcRenderer.invoke("orchestrator:select-path", kind) as Promise<
      string | null
    >;
  },
  openArchiveFolder(projectName: string, runId: string): Promise<boolean> {
    return ipcRenderer.invoke("orchestrator:open-archive-folder", projectName, runId) as Promise<boolean>;
  },
  openTaskRecord(projectName: string, runId: string, taskId: string): Promise<boolean> {
    return ipcRenderer.invoke("orchestrator:open-task-record", projectName, runId, taskId) as Promise<boolean>;
  },
  restartBackend(): Promise<boolean> {
    return ipcRenderer.invoke("orchestrator:restart-backend") as Promise<boolean>;
  },
  chatControls() { return ipcRenderer.invoke("orchestrator:chat-controls"); },
  planningRequests() {
    return ipcRenderer.invoke("orchestrator:planning-requests");
  },
  queuePlanningMessage(input) { return ipcRenderer.invoke("orchestrator:queue-planning-message", input); },
  changeQueuedPlanningMessage(change) { return ipcRenderer.invoke("orchestrator:change-queued-planning-message", change); },
  interruptPlanning<Result>(
    projectName: string,
    runId: string,
    targetRequestId: string,
  ): Promise<Result | null> {
    return ipcRenderer.invoke(
      "orchestrator:interrupt-planning",
      projectName,
      runId,
      targetRequestId,
    ) as Promise<Result | null>;
  },
};

contextBridge.exposeInMainWorld("orchestrator", api);
