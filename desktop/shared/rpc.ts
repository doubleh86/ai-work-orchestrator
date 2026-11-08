export const RPC_METHODS = [
  "system.hello",
  "connections.externalGuide",
  "connections.registerExternal",
  "runs.resultArtifact",
  "runs.registerResult",
  "runs.launchResult",
  "runs.controlChat",
  "runs.decideProjectChat",
  "runs.performProjectChat",
  "runs.requestChatControl",
  "runs.advanceChatControl",
  "runs.cancelChatControl",
  "runs.beginPlanningRequest",
  "runs.finishPlanningRequest",
  "auth.codex.status",
  "auth.claude.status",
  "auth.codex.start",
  "auth.codex.apiKey",
  "auth.codex.get",
  "auth.codex.cancel",
  "projects.list",
  "projects.inspectGitReadiness",
  "projects.previewGitInitialization",
  "projects.initializeGit",
  "projects.previewInitialCommit",
  "projects.createInitialCommit",
  "notifications.list",
  "projects.add",
  "projects.remove",
  "projects.updatePlanningSource",
  "projects.updateDotnet",
  "projects.capabilities",
  "projects.codeStyleProfile",
  "projects.previewCodeStylePreference",
  "projects.updateCodeStylePreference",
  "planning.inspectRepositoryMaturity",
  "planning.previewBootstrap",
  "planning.generateFeaturePlan",
  "projects.workspaceLocation",
  "projects.checkDotnet",
  "projects.updateMain",
  "projects.mainChanges",
  "projects.mainChangeDiff",
  "projects.refreshMainRemote",
  "projects.commitMainChanges",
  "projects.commitAndPushMainChanges",
  "projects.pushMainCommits",
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
  "runs.interruptPlanning",
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
  "runs.requestStop",
  "runs.recoveryPlan",
  "runs.applyRecovery",
  "operations.get",
  "operations.latest",
  "runs.integrationConflict",
  "runs.prepareConflictResolution",
  "runs.applyConflictResolution",
  "tasks.execute",
  "tasks.retry",
  "tasks.repairFromChat",
  "tasks.updateExecutionProfile",
  "tasks.complete",
  "tasks.completeManualVerification",
  "runs.recordUserCheck",
  "tasks.handoffToAi",
  "tasks.deferManual",
  "tasks.resumeManual",
  "runs.verify",
  "runs.verifyAndRepair",
  "runs.excludeTasks",
  "runs.updatePlan",
  "runs.confirmPlan",
  "runs.merge",
  "runs.push",
  "runs.retryMainPush",
  "runs.recoverMainApply",
  "runs.deploy",
  "runs.archive",
  "runs.retryArchiveCleanup",
  "runs.delete",
  "workspaces.list",
  "workspaces.cleanup",
  "locks.get",
  "locks.clear",
] as const;

export type RpcMethod = (typeof RPC_METHODS)[number];

export type RpcParams = Readonly<Record<string, unknown>>;

export const APPROVED_RPC_METHODS = [
  "projects.initializeGit",
  "projects.createInitialCommit",
  "runs.applyRecovery",
  "runs.applyConflictResolution",
  "projects.remove",
  "projects.updateCodeStylePreference",
  "projects.updateMain",
  "projects.commitMainChanges",
  "projects.commitAndPushMainChanges",
  "projects.pushMainCommits",
  "runs.excludeTasks",
  "runs.merge",
  "runs.push",
  "runs.retryMainPush",
  "runs.recoverMainApply",
  "runs.deploy",
  "runs.archive",
  "runs.retryArchiveCleanup",
  "runs.delete",
  "workspaces.cleanup",
  "locks.clear",
] as const satisfies readonly RpcMethod[];

export type ApprovedRpcMethod = (typeof APPROVED_RPC_METHODS)[number];
export type PathSelectionKind = "repository" | "config" | "planningSource" | "dotnet";

export type CodexMcpRegistration = "registered" | "codex_missing" | "registration_failed";

export interface DesktopApi {
  mcpConnectionCommand(): Promise<string | null>;
  registerCodexMcp(): Promise<CodexMcpRegistration>;
  registerCodexPlanning(): Promise<CodexMcpRegistration>;
  openCodexInstallGuide(): Promise<void>;
  openClaudeLogin(): Promise<boolean>;
  nvidiaCredentialStatus(): Promise<import("./nvidiaCredentials").NvidiaCredentialStatus>;
  saveNvidiaCredential(key: string, options?: import("./nvidiaCredentials").NvidiaCredentialOptions): Promise<import("./nvidiaCredentials").NvidiaCredentialStatus>;
  deleteNvidiaCredential(id?: string): Promise<import("./nvidiaCredentials").NvidiaCredentialStatus>;
  setNvidiaCredentialRouting(defaultKeyId: string, modelBindings: Readonly<Record<string, string>>): Promise<import("./nvidiaCredentials").NvidiaCredentialStatus>;
  onOpenProjectSettings(callback: () => void): () => void;
  onOpenCodexAuth(callback: () => void): () => void;
  codexAuthStatus(): Promise<import("./codexAuth").CodexAuthState>;
  startCodexAuth(method: import("./codexAuth").CodexAuthMethod, requestId: string): Promise<import("./codexAuth").CodexAuthState>;
  connectCodexApiKey(apiKey: string, requestId: string): Promise<import("./codexAuth").CodexAuthState>;
  getCodexAuth(attemptId: string): Promise<import("./codexAuth").CodexAuthState>;
  cancelCodexAuth(attemptId: string): Promise<import("./codexAuth").CodexAuthState>;
  reopenCodexAuth(attemptId: string): Promise<import("./codexAuth").CodexAuthState>;
  copyCodexDeviceCode(attemptId: string): Promise<boolean>;
  onNotificationsChanged(callback: (snapshot: import("./workNotifications").WorkNotificationSnapshot) => void): () => void;
  onNotificationOpen(callback: (notification: import("./workNotifications").StoredWorkNotification) => void): () => void;
  listNotifications(refreshScope?: string): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  markNotificationRead(eventId: string): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  markAllNotificationsRead(): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  dismissNotification(eventId: string): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  dismissNotifications(
    scope: import("./workNotifications").WorkNotificationDismissScope,
  ): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  updateNotificationSettings(
    settings: import("./workNotifications").WorkNotificationSettings,
  ): Promise<import("./workNotifications").WorkNotificationSnapshot>;
  request<Result>(method: RpcMethod, params?: RpcParams): Promise<Result>;
  approve<Result>(
    method: ApprovedRpcMethod,
    params?: RpcParams,
  ): Promise<Result | null>;
  selectPath(kind: PathSelectionKind): Promise<string | null>;
  openArchiveFolder(projectName: string, runId: string): Promise<boolean>;
  openTaskRecord(projectName: string, runId: string, taskId: string): Promise<boolean>;
  restartBackend(): Promise<boolean>;
  chatControls(): Promise<import("./chatControls").ChatControlView[]>;
  planningRequests(): Promise<import("./planningRequests").PlanningRequestsSnapshot>;
  queuePlanningMessage(input: import("./planningMessageQueue").QueuedMessageInput): Promise<import("./planningMessageQueue").PlanningMessageQueueSnapshot>;
  changeQueuedPlanningMessage(change: import("./planningMessageQueue").QueuedMessageChange): Promise<import("./planningMessageQueue").PlanningMessageQueueSnapshot>;
  interruptPlanning<Result>(
    projectName: string,
    runId: string,
    targetRequestId: string,
  ): Promise<Result | null>;
}

export function isRpcMethod(value: string): value is RpcMethod {
  return (RPC_METHODS as readonly string[]).includes(value);
}

export function isApprovedRpcMethod(
  value: string,
): value is ApprovedRpcMethod {
  return (APPROVED_RPC_METHODS as readonly string[]).includes(value);
}
