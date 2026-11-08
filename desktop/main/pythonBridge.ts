import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";

import { RpcMethod, RpcParams } from "../shared/rpc";

interface RpcResponse {
  id: number | string | null;
  result?: unknown;
  error?: {
    code: string;
    message: string;
  };
}

interface PendingRequest {
  resolve(value: unknown): void;
  reject(reason: Error): void;
  timeout?: NodeJS.Timeout;
  backend: BackendRole;
  method: RpcMethod;
  requestId: number;
  instanceId: string;
}

export type BackendRole = "control" | "planning" | "work";
export type PythonBridgeErrorKind = "application" | "timeout" | "process_exit" | "transport" | "not_running" | "stopped";

export class PythonBridgeRequestError extends Error {
  constructor(
    readonly kind: PythonBridgeErrorKind, readonly backend: BackendRole, readonly method: RpcMethod,
    readonly requestId: number, readonly instanceId: string, message: string, readonly rpcCode = "",
  ) {
    super(message);
    this.name = "PythonBridgeRequestError";
  }
}

const REQUEST_TIMEOUT_MS = 30 * 60 * 1000;
const QUICK_REQUEST_TIMEOUT_MS = 15 * 1000;
const BOUNDED_REQUEST_TIMEOUT_MS: Partial<Record<RpcMethod, number>> = {
  "providers.accountUsage": 22 * 1000,
  "runs.recoveryPlan": 60 * 1000,
  "projects.checkDotnet": 75 * 1000,
  "planning.refreshIndex": 90 * 1000,
  "projects.updateMain": 90 * 1000,
  "projects.mainChanges": 45 * 1000,
  "projects.mainChangeDiff": 45 * 1000,
  "projects.refreshMainRemote": 90 * 1000,
  "projects.commitMainChanges": 90 * 1000,
  "projects.commitAndPushMainChanges": 90 * 1000,
  "projects.pushMainCommits": 90 * 1000,
  "runs.delete": 75 * 1000,
  "workspaces.list": 45 * 1000,
  "projects.codeStyleProfile": 45 * 1000,
  "projects.previewCodeStylePreference": 45 * 1000,
  "projects.updateCodeStylePreference": 45 * 1000,
};
const QUICK_REQUEST_METHODS = new Set<RpcMethod>([
  "system.hello",
  "connections.externalGuide",
  "runs.resultArtifact",
  "auth.claude.status",
  "projects.list",
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
  "providers.planning",
  "providers.execution",
  "providers.status",
  "providers.accountUsage",
  "runs.list",
  "runs.activeGroups",
  "runs.attentionItems",
  "runs.get",
  "runs.getPlanningPreview",
  "runs.planningPreviewStatus",
  "runs.previewEffortMode",
  "runs.setEffortMode",
  "runs.cancelEffortReservation",
  "tasks.retryContext",
  "tasks.saveRetryInstruction",
  "tasks.updateExecutionProfile",
  "runs.resultRevisions",
  "runs.beginPlanningRequest", "runs.finishPlanningRequest",
  "runs.requestChatControl", "runs.advanceChatControl", "runs.cancelChatControl",
  "runs.requestStop",
  "runs.requestDirectionChange",
  "operations.get",
  "operations.latest",
  "runs.integrationConflict",
  "tasks.log",
  "runs.excludeTasks",
  "runs.updatePlan",
  "runs.confirmPlan",
  "locks.get",
  "locks.clear",
]);
const WORK_REQUEST_METHODS = new Set<RpcMethod>([
  "connections.registerExternal",
  "runs.registerResult",
  "runs.launchResult",
  "runs.performProjectChat",
  "runs.recoveryPlan",
  "runs.applyRecovery",
  "runs.prepareConflictResolution",
  "runs.applyConflictResolution",
  "projects.updateMain",
  "projects.mainChanges",
  "projects.mainChangeDiff",
  "projects.refreshMainRemote",
  "projects.commitMainChanges",
  "projects.commitAndPushMainChanges",
  "projects.pushMainCommits",
  "runs.execute",
  "runs.resume",
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
  "runs.delete",
  "workspaces.cleanup",
]);
const PLANNING_REQUEST_METHODS = new Set<RpcMethod>([
  "runs.decideProjectChat",
  "planning.refreshIndex",
  "planning.generateFeaturePlan",
  "runs.preparePlanning",
  "runs.proposeResultRevision",
  "runs.createResultRevision",
  "runs.runPlanning",
  "runs.start",
  "runs.sendPlanningMessage",
  "runs.previewPlanningApply",
  "runs.applyPlanningPreview",
  "runs.applyPlanningConversation",
  "runs.confirmTechStack",
  "runs.configureBootstrapInstructions",
]);
const BACKEND_MANAGED_LONG_REQUEST_METHODS = new Set<RpcMethod>([
  "connections.registerExternal",
  "runs.registerResult",
  "runs.launchResult",
  "runs.decideProjectChat", "runs.performProjectChat",
  "runs.proposeResultRevision",
  "runs.createResultRevision",
  "runs.start",
  "runs.runPlanning",
  "runs.sendPlanningMessage",
  "runs.previewPlanningApply",
  "runs.applyPlanningPreview",
  "runs.applyPlanningConversation",
  "planning.generateFeaturePlan",
  "runs.confirmTechStack",
  "runs.configureBootstrapInstructions",
  "runs.applyRecovery",
  "runs.prepareConflictResolution",
  "runs.applyConflictResolution",
  "runs.execute",
  "runs.resume",
  "tasks.execute",
  "tasks.retry",
  "tasks.repairFromChat",
  "tasks.complete",
  "tasks.completeManualVerification",
  "runs.recordUserCheck",
  "tasks.handoffToAi",
  "runs.verify",
  "runs.verifyAndRepair",
  "runs.merge",
  "runs.push",
  "runs.retryMainPush",
  "runs.recoverMainApply",
  "runs.deploy",
  "workspaces.cleanup",
]);

export function requestTimeoutMilliseconds(method: RpcMethod): number | undefined {
  const bounded = BOUNDED_REQUEST_TIMEOUT_MS[method];
  if (bounded !== undefined) return bounded;
  if (QUICK_REQUEST_METHODS.has(method)) return QUICK_REQUEST_TIMEOUT_MS;
  if (BACKEND_MANAGED_LONG_REQUEST_METHODS.has(method)) return undefined;
  return REQUEST_TIMEOUT_MS;
}

export class PythonBridge {
  private readonly planningSessions = new Map<string, { bridge: PythonBridge; active: number; idle?: NodeJS.Timeout }>();
  private nvidiaApiKey: string | undefined;
  private nvidiaModelApiKeys: Readonly<Record<string, string>> = {};
  private controlProcess: ChildProcessWithoutNullStreams | null = null;
  private planningProcess: ChildProcessWithoutNullStreams | null = null;
  private workProcess: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private readonly instanceIds = new WeakMap<ChildProcessWithoutNullStreams, string>();
  private readonly closedChannels = new WeakSet<ChildProcessWithoutNullStreams>();
  private readonly lastInstanceIds: Partial<Record<BackendRole, string>> = {};

  constructor(private readonly backendExecutable?: string) {}

  setNvidiaApiKey(key: string | undefined, modelKeys: Readonly<Record<string, string>> = {}): void {
    this.nvidiaApiKey = key;
    this.nvidiaModelApiKeys = { ...modelKeys };
    for (const session of this.planningSessions.values()) session.bridge.setNvidiaApiKey(key, modelKeys);
  }

  async requestPlanning<Result>(method: RpcMethod, params: RpcParams): Promise<Result> {
    if (!PLANNING_REQUEST_METHODS.has(method)) return this.request<Result>(method, params);
    const key = JSON.stringify([params.projectName || "", params.runId || ""]);
    let session = this.planningSessions.get(key);
    if (!session || !session.bridge.planningProcess) {
      if (session?.idle) clearTimeout(session.idle);
      const bridge = new PythonBridge(this.backendExecutable);
      bridge.setNvidiaApiKey(this.nvidiaApiKey, this.nvidiaModelApiKeys);
      bridge.startBackend("planning");
      session = { bridge, active: 0 };
      this.planningSessions.set(key, session);
    }
    if (session.idle) clearTimeout(session.idle);
    session.active++;
    try { return await session.bridge.requestOnBackend<Result>("planning", method, params); }
    finally {
      session.active--;
      if (!session.active && this.planningSessions.get(key) === session) {
        const settled = session;
        settled.idle = setTimeout(() => {
          if (settled.active || this.planningSessions.get(key) !== settled) return;
          this.planningSessions.delete(key);
          void settled.bridge.stop().catch(error => process.stderr.write(`[python-planning-backend] idle cleanup failed: ${String(error)}\n`));
        }, 5 * 60 * 1000);
        settled.idle.unref();
      }
    }
  }

  start(): void {
    this.startBackend("control");
    this.startBackend("planning");
    this.startBackend("work");
  }

  private startBackend(backend: BackendRole): void {
    if (this.processFor(backend)) return;
    const workspaceRoot = resolve(__dirname, "..", "..");
    const [python, args] = backendCommand(workspaceRoot, this.backendExecutable);
    const registry = process.env.AI_ORCHESTRATOR_REGISTRY?.trim();
    if (registry) {
      args.push("--registry", registry);
    }

    const child = spawn(python, args, {
      cwd: workspaceRoot,
      env: {
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
      },
      shell: false,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.setProcess(backend, child);
    const instanceId = randomUUID();
    this.instanceIds.set(child, instanceId);
    this.lastInstanceIds[backend] = instanceId;

    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      if (this.processFor(backend) === child) this.handleLine(backend, line);
    });
    child.stdin.on("error", (error: Error) => {
      if (this.processFor(backend) !== child) return;
      this.closedChannels.add(child);
      this.failBackend(backend, error, "transport");
    });
    child.stdout.on("end", () => {
      if (this.processFor(backend) !== child) return;
      this.closedChannels.add(child);
      this.failBackend(backend, new Error(`Python ${backend} backend communication closed`), "transport");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      process.stderr.write(
        `[python-${backend}-backend] ${chunk.toString("utf8")}`,
      );
    });
    child.on("error", (error) => {
      if (this.processFor(backend) !== child) return;
      this.setProcess(backend, null);
      this.failBackend(backend, error, "transport");
    });
    child.on("exit", (code, signal) => {
      if (this.processFor(backend) !== child) return;
      this.setProcess(backend, null);
      this.failBackend(
        backend,
        new Error(
          `Python ${backend} backend exited ` +
            `(code=${String(code)}, signal=${String(signal)})`,
        ),
        "process_exit",
      );
    });
  }

  async request<Result>(method: RpcMethod, params: RpcParams = {}): Promise<Result> {
    const backend = PLANNING_REQUEST_METHODS.has(method)
      ? "planning"
      : WORK_REQUEST_METHODS.has(method)
        ? "work"
        : "control";
    return this.requestOnBackend(backend, method, params);
  }

  async healthCheck(): Promise<void> {
    await Promise.all([
      this.requestOnBackend("control", "system.hello", {}),
      this.requestOnBackend("planning", "system.hello", {}),
      this.requestOnBackend("work", "system.hello", {}),
    ]);
  }

  private async requestOnBackend<Result>(
    backend: BackendRole,
    method: RpcMethod,
    params: RpcParams,
  ): Promise<Result> {
    const child = this.processFor(backend);
    if (!child) {
      throw new PythonBridgeRequestError("not_running", backend, method, 0,
        this.lastInstanceIds[backend] || "", `Python ${backend} backend is not running`);
    }
    const instanceId = this.instanceIds.get(child) || "";
    if (this.closedChannels.has(child)) throw new PythonBridgeRequestError("transport", backend, method, 0,
      instanceId, `Python ${backend} backend communication closed`);
    const id = this.nextId++;
    const response = new Promise<Result>((resolveRequest, rejectRequest) => {
      const timeoutMs = requestTimeoutMilliseconds(method);
      const timeout = timeoutMs === undefined
        ? undefined
        : setTimeout(() => {
          this.pending.delete(id);
          rejectRequest(new PythonBridgeRequestError("timeout", backend, method, id, instanceId, requestTimeoutMessage(method, timeoutMs)));
        }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => resolveRequest(value as Result),
        reject: rejectRequest,
        timeout,
        backend,
        method,
        requestId: id,
        instanceId,
      });
    });
    try {
      const credential = this.nvidiaApiKey === undefined ? {} : { nvidia_api_key: this.nvidiaApiKey };
      const modelCredentials = Object.keys(this.nvidiaModelApiKeys).length ? { nvidia_model_api_keys: this.nvidiaModelApiKeys } : {};
      child.stdin.write(`${JSON.stringify({ id, method, params, ...credential, ...modelCredentials })}\n`, "utf8", (error) => {
        if (!error || this.processFor(backend) !== child) return;
        this.closedChannels.add(child);
        this.failBackend(backend, error, "transport");
      });
    } catch (cause) {
      this.closedChannels.add(child);
      this.failBackend(backend, cause instanceof Error ? cause : new Error(String(cause)), "transport");
    }
    return response;
  }

  async stop(): Promise<void> {
    const sessions = [...this.planningSessions.values()];
    this.planningSessions.clear();
    for (const session of sessions) if (session.idle) clearTimeout(session.idle);
    const children = [
      this.controlProcess,
      this.planningProcess,
      this.workProcess,
    ].filter(
      (child): child is ChildProcessWithoutNullStreams => child !== null,
    );
    this.controlProcess = null;
    this.planningProcess = null;
    this.workProcess = null;
    this.failAll(new Error("Python backend stopped"));
    await Promise.all([...children.map((child) => terminateProcessTree(child)), ...sessions.map(session => session.bridge.stop())]);
  }

  async restart(): Promise<void> {
    await this.stop();
    this.start();
  }

  async restartWork(): Promise<void> {
    const child = this.workProcess;
    this.workProcess = null;
    this.failBackend("work", new Error("Python work backend stopped"));
    if (child) {
      await terminateProcessTree(child);
    }
    this.startBackend("work");
    await this.requestOnBackend("work", "system.hello", {});
  }

  async restartPlanning(projectName?: string, runId?: string): Promise<void> {
    if (projectName !== undefined && runId !== undefined) {
      const key = JSON.stringify([projectName, runId]);
      const session = this.planningSessions.get(key);
      if (!session) return;
      if (session.idle) clearTimeout(session.idle);
      const child = session.bridge.planningProcess;
      if (child) await terminateProcessTree(child);
      if (session.bridge.planningProcess === child) session.bridge.planningProcess = null;
      session.bridge.failBackend("planning", new Error("Python planning conversation stopped"));
      this.planningSessions.delete(key);
      return;
    }
    const child = this.planningProcess;
    this.planningProcess = null;
    this.failBackend("planning", new Error("Python planning backend stopped"));
    if (child) {
      await terminateProcessTree(child);
    }
    this.startBackend("planning");
    await this.requestOnBackend("planning", "system.hello", {});
  }

  private handleLine(backend: BackendRole, line: string): void {
    let response: RpcResponse;
    try {
      response = JSON.parse(line) as RpcResponse;
    } catch {
      process.stderr.write(
        `[python-${backend}-backend] invalid response frame\n`,
      );
      return;
    }
    if (typeof response.id !== "number") {
      return;
    }
    const pending = this.pending.get(response.id);
    if (!pending || pending.backend !== backend) {
      return;
    }
    if (pending.timeout) clearTimeout(pending.timeout);
    this.pending.delete(response.id);
    if (response.error) {
      pending.reject(new PythonBridgeRequestError("application", backend, pending.method, pending.requestId,
        pending.instanceId, `${response.error.code}: ${response.error.message}`, response.error.code));
      return;
    }
    pending.resolve(response.result);
  }

  private failAll(error: Error): void {
    for (const pending of this.pending.values()) {
      if (pending.timeout) clearTimeout(pending.timeout);
      pending.reject(new PythonBridgeRequestError("stopped", pending.backend, pending.method, pending.requestId, pending.instanceId, error.message));
    }
    this.pending.clear();
  }

  private failBackend(backend: BackendRole, error: Error, kind: PythonBridgeErrorKind = "stopped"): void {
    for (const [id, pending] of this.pending) {
      if (pending.backend !== backend) continue;
      if (pending.timeout) clearTimeout(pending.timeout);
      pending.reject(new PythonBridgeRequestError(kind, backend, pending.method, pending.requestId, pending.instanceId, error.message));
      this.pending.delete(id);
    }
  }

  private processFor(
    backend: BackendRole,
  ): ChildProcessWithoutNullStreams | null {
    if (backend === "control") return this.controlProcess;
    return backend === "planning" ? this.planningProcess : this.workProcess;
  }

  private setProcess(
    backend: BackendRole,
    child: ChildProcessWithoutNullStreams | null,
  ): void {
    if (backend === "control") {
      this.controlProcess = child;
    } else if (backend === "planning") {
      this.planningProcess = child;
    } else {
      this.workProcess = child;
    }
  }
}

function requestTimeoutMessage(method: RpcMethod, timeoutMs: number): string {
  const seconds = Math.round(timeoutMs / 1000);
  if (method === "runs.recoveryPlan") {
    return `복구안 조회가 ${seconds}초 안에 완료되지 않았습니다. 조회 응답 대기를 종료했습니다. 복구는 적용되지 않았습니다.`;
  }
  if (method === "planning.refreshIndex") {
    return `문서 색인 요청이 ${seconds}초 안에 완료되지 않았습니다.`;
  }
  if (method === "projects.updateMain") {
    return `Main 최신화 요청이 ${seconds}초 안에 완료되지 않았습니다.`;
  }
  if (method === "runs.delete") {
    return `작업 그룹 삭제 요청이 ${seconds}초 안에 완료되지 않았습니다.`;
  }
  if (method === "workspaces.list") {
    return `작업공간 상태 조회가 ${seconds}초 안에 완료되지 않았습니다.`;
  }
  if (QUICK_REQUEST_METHODS.has(method)) {
    return `Backend 조회 요청이 ${seconds}초 안에 완료되지 않았습니다. (${method})`;
  }
  return `RPC request timed out after ${seconds}s: ${method}`;
}

async function terminateProcessTree(
  child: ChildProcessWithoutNullStreams,
): Promise<void> {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) {
    return;
  }
  if (process.platform !== "win32") {
    child.kill("SIGTERM");
    return;
  }
  await new Promise<void>((resolveTermination) => {
    const killer = spawn(
      "taskkill",
      ["/PID", String(child.pid), "/T", "/F"],
      { shell: false, windowsHide: true, stdio: "ignore" },
    );
    let settled = false;
    let fallbackTimer: NodeJS.Timeout | undefined;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (fallbackTimer) clearTimeout(fallbackTimer);
      resolveTermination();
    };
    killer.once("error", () => {
      child.kill();
      finish();
    });
    killer.once("exit", (code) => {
      if (code !== 0) child.kill();
      finish();
    });
    fallbackTimer = setTimeout(() => {
      if (!killer.killed) killer.kill();
      child.kill();
      finish();
    }, 5_000).unref();
  });
}

function resolvePython(workspaceRoot: string): string {
  const configured = process.env.AI_ORCHESTRATOR_PYTHON?.trim();
  if (configured) {
    return configured;
  }
  const candidates =
    process.platform === "win32"
      ? [resolve(workspaceRoot, ".venv", "Scripts", "python.exe")]
      : [resolve(workspaceRoot, ".venv", "bin", "python")];
  return candidates.find((candidate) => existsSync(candidate)) ?? "python";
}

export function backendCommand(workspaceRoot: string, backendExecutable?: string): [string, string[]] {
  if (backendExecutable) return [backendExecutable, []];
  return [resolvePython(workspaceRoot), ["-m", "ai_orchestrator.desktop_rpc"]];
}

export function bundledBackendExecutable(resourcesPath: string, platform = process.platform): string | undefined {
  if (platform !== "darwin" && platform !== "win32") return undefined;
  const candidate = join(resourcesPath, "backend", platform === "win32" ? "ai-orchestrator-backend.exe" : "ai-orchestrator-backend");
  return existsSync(candidate) ? candidate : undefined;
}
