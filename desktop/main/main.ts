import { execFile } from "node:child_process";
import { dirname, join, resolve } from "node:path";

import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, MenuItemConstructorOptions, Notification, safeStorage, shell } from "electron";

import {
  ApprovedRpcMethod,
  CodexMcpRegistration,
  isApprovedRpcMethod,
  isRpcMethod,
  PathSelectionKind,
  RpcParams,
} from "../shared/rpc";
import { DESKTOP_WINDOW_BACKGROUND } from "../shared/theme";
import type { WorkNotificationDismissScope, WorkNotificationSettings, StoredWorkNotification } from "../shared/workNotifications";
import type { CodexAuthMethod } from "../shared/codexAuth";
import { CodexAuthController } from "./codexAuth";
import { ClaudeCredentialStore } from "./claudeCredentials";
import { DesktopTray } from "./desktopTray";
import { NvidiaCredentialStore } from "./nvidiaCredentials";
import { openTaskRecord } from "./taskRecord";
import { openClaudeLogin } from "./claudeLogin";
import { bundledBackendExecutable, PythonBridge } from "./pythonBridge";
import { WorkNotificationCenter } from "./workNotifications";
import { PlanningRequests } from "./planningRequests";
import { ChatControls } from "./chatControls";
import { PlanningMessageQueue } from "./planningMessageQueue";
import type { QueuedMessageInput, QueuedMessageChange } from "../shared/planningMessageQueue";

const packagedBackend = bundledBackendExecutable(process.resourcesPath);
const bridge = new PythonBridge(packagedBackend);
const planningRequests = new PlanningRequests(bridge);
const chatControls = new ChatControls(bridge, undefined, planningRequests);
const codexAuth = new CodexAuthController(bridge, {
  openExternal: (url) => shell.openExternal(url),
  copyText: (value) => clipboard.writeText(value),
});
let notificationCenter: WorkNotificationCenter | undefined;
let pendingNotificationOpen: StoredWorkNotification | undefined;
let messageQueue: PlanningMessageQueue | undefined;
let desktopTray: DesktopTray | undefined;

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    title: "AI Work Orchestrator",
    width: 1440,
    height: 920,
    minWidth: 320,
    minHeight: 520,
    backgroundColor: DESKTOP_WINDOW_BACKGROUND,
    show: false,
    webPreferences: {
      preload: resolve(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  desktopTray?.attach(window);
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-prevent-unload", (event) => {
    if (window.isMinimized()) window.restore();
    window.show();
    const choice = dialog.showMessageBoxSync(window, {
      type: "warning",
      title: "미저장 변경 있음",
      message: "저장하지 않은 계획 변경이 있습니다.",
      detail: "종료하거나 새로고침하면 모든 그룹의 미저장 초안이 사라집니다.",
      buttons: ["계속 편집", "변경 버리고 계속"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (choice === 1) event.preventDefault();
    else desktopTray?.cancelQuit();
  });
  window.once("ready-to-show", () => window.show());
  const developmentUrl = process.env.VITE_DEV_SERVER_URL?.trim();
  if (developmentUrl) {
    void window.loadURL(developmentUrl);
  } else {
    void window.loadFile(
      resolve(__dirname, "..", "..", "dist", "renderer", "index.html"),
    );
  }
  return window;
}

function showMainWindow(): void {
  if (backendStoppingForQuit) return;
  const window = BrowserWindow.getAllWindows().find((candidate) => !candidate.isDestroyed()) || createWindow();
  if (process.platform === "darwin" && app.dock && !app.dock.isVisible()) {
    void app.dock.show().catch((error: unknown) => process.stderr.write(`Dock restore failed: ${String(error)}\n`));
  }
  if (window.isMinimized()) window.restore();
  window.show();
  window.moveTop();
  window.focus();
}

function registerCodexConnection(allowPlanning: boolean): Promise<CodexMcpRegistration> {
  if (process.platform !== "win32" || !packagedBackend) return Promise.resolve("registration_failed");
  const args = allowPlanning ? ["mcp-connect", "--allow-planning"] : ["mcp-connect"];
  return new Promise((resolveRegistration) => {
    execFile(packagedBackend, args, { cwd: dirname(packagedBackend), timeout: 45_000, windowsHide: true }, (error, stdout) => {
      const status = stdout.trim();
      if (!error && status === "registered") resolveRegistration("registered");
      else resolveRegistration(status === "codex_missing" ? "codex_missing" : "registration_failed");
    });
  });
}

app.whenReady().then(() => {
  if (process.platform === "win32" && packagedBackend) {
    execFile(packagedBackend, ["mcp-stage"], { cwd: dirname(packagedBackend), timeout: 45_000, windowsHide: true }, (error) => {
      if (error) console.warn("Could not prepare the bundled Codex runtime", error.code);
    });
  }
  ipcMain.handle("orchestrator:mcp-command", () => packagedBackend ?? null);
  ipcMain.handle("orchestrator:mcp-register-codex", () => registerCodexConnection(false));
  ipcMain.handle("orchestrator:mcp-register-planning", () => registerCodexConnection(true));
  ipcMain.handle("orchestrator:codex-install-guide", () => shell.openExternal("https://learn.chatgpt.com/docs/codex/cli"));
  messageQueue = new PlanningMessageQueue(join(app.getPath("userData"), "queued-chat-messages.json"), planningRequests, bridge, chatControls);
  const menu: MenuItemConstructorOptions[] = [
    ...(process.platform === "darwin" ? [{ role: "appMenu" as const }] : []),
    {
      label: "File",
      submenu: [
        {
          label: "AI 연결…",
          click: (_item, window) => {
            const target = window instanceof BrowserWindow ? window : BrowserWindow.getFocusedWindow();
            target?.webContents.send("orchestrator:open-codex-auth");
          },
        },
        {
          label: "프로젝트 설정…",
          accelerator: "CmdOrCtrl+,",
          click: (_item, window) => {
            const target = window instanceof BrowserWindow ? window : BrowserWindow.getFocusedWindow();
            target?.webContents.send("orchestrator:open-project-settings");
          },
        },
        { type: "separator" },
        { role: process.platform === "darwin" ? "close" : "quit" },
      ],
    },
    { role: "editMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(menu));
  const nvidiaCredentials = new NvidiaCredentialStore(
    join(app.getPath("userData"), "nvidia-api-key.bin"), safeStorage,
    () => Boolean(process.env.NVIDIA_API_KEY?.trim()),
  );
  const syncNvidiaCredentials = () => bridge.setNvidiaApiKey(nvidiaCredentials.apiKey(), nvidiaCredentials.modelApiKeys());
  syncNvidiaCredentials();
  const claudeCredentials = new ClaudeCredentialStore(
    join(app.getPath("userData"), "claude-api-key.bin"), safeStorage,
    () => Boolean(process.env.ANTHROPIC_API_KEY?.trim()),
  );
  const syncClaudeCredentials = () => bridge.setClaudeApiKey(claudeCredentials.apiKey());
  syncClaudeCredentials();
  bridge.start();
  notificationCenter = new WorkNotificationCenter(
    join(app.getPath("userData"), "work-notifications.json"),
    bridge,
    {
      isBackground: () => !BrowserWindow.getAllWindows().some(
        (window) => window.isVisible() && !window.isMinimized() && window.isFocused(),
      ),
      publish: (snapshot) => {
        for (const window of BrowserWindow.getAllWindows()) {
          if (!window.isDestroyed()) window.webContents.send("orchestrator:notifications-changed", snapshot);
        }
      },
      showOs: (title, body, onClick) => {
        if (!Notification.isSupported()) return false;
        const notification = new Notification({ title, body });
        notification.on("click", onClick);
        notification.show();
        return true;
      },
      open: openNotificationTarget,
      log: (message) => process.stderr.write(`[work-notifications] ${message}\n`),
    },
  );
  notificationCenter.start();
  ipcMain.handle(
    "orchestrator:request",
    (_event, method: unknown, params: unknown) => {
      if (typeof method !== "string" || !isRpcMethod(method)) {
        throw new Error("Unsupported desktop request");
      }
      if (["runs.beginPlanningRequest", "runs.finishPlanningRequest", "runs.requestChatControl", "runs.advanceChatControl"].includes(method)) throw new Error("Internal request lifecycle method");
      if (params !== undefined && (params === null || typeof params !== "object")) {
        throw new Error("Desktop request params must be an object");
      }
      if (method === "runs.controlChat") return chatControls.start((params ?? {}) as RpcParams);
      return planningRequests.request(method, (params ?? {}) as RpcParams);
    },
  );
  ipcMain.handle("orchestrator:nvidia-credential-status", () => nvidiaCredentials.status());
  ipcMain.handle("orchestrator:claude-credential-status", () => claudeCredentials.status());
  ipcMain.handle("orchestrator:claude-credential-save", (_event, key: unknown) => {
    const status = claudeCredentials.save(key);
    syncClaudeCredentials();
    return status;
  });
  ipcMain.handle("orchestrator:claude-credential-delete", () => {
    const status = claudeCredentials.delete();
    syncClaudeCredentials();
    return status;
  });
  ipcMain.handle("orchestrator:claude-login", async () => {
    const status = await bridge.request<{ selected_executable?: unknown }>("auth.claude.status", {});
    if (status.selected_executable !== undefined && typeof status.selected_executable !== "string") {
      throw new Error("Claude 실행 파일 설정을 확인하지 못했습니다.");
    }
    return openClaudeLogin(app.getPath("temp"), status.selected_executable || "");
  });
  ipcMain.handle("orchestrator:nvidia-credential-save", (_event, key: unknown, options: unknown) => {
    const status = nvidiaCredentials.save(key, options);
    syncNvidiaCredentials();
    return status;
  });
  ipcMain.handle("orchestrator:nvidia-credential-delete", (_event, id: unknown) => {
    const status = nvidiaCredentials.delete(id);
    syncNvidiaCredentials();
    return status;
  });
  ipcMain.handle("orchestrator:nvidia-credential-routing", (_event, defaultKeyId: unknown, modelBindings: unknown) => {
    const status = nvidiaCredentials.setRouting(defaultKeyId, modelBindings);
    syncNvidiaCredentials();
    return status;
  });
  ipcMain.handle("orchestrator:codex-auth-status", () => codexAuth.status());
  ipcMain.handle("orchestrator:codex-auth-start", (_event, method: unknown, requestId: unknown) => {
    if (!isCodexAuthMethod(method) || typeof requestId !== "string") throw new Error("Invalid Codex login request");
    return codexAuth.start(method, requestId);
  });
  ipcMain.handle("orchestrator:codex-auth-api-key", (_event, apiKey: unknown, requestId: unknown) => {
    if (typeof apiKey !== "string" || typeof requestId !== "string") throw new Error("Invalid Codex API key login request");
    return codexAuth.connectApiKey(apiKey, requestId);
  });
  ipcMain.handle("orchestrator:codex-auth-get", (_event, attemptId: unknown) => {
    if (typeof attemptId !== "string") throw new Error("Invalid Codex login attempt");
    return codexAuth.get(attemptId);
  });
  ipcMain.handle("orchestrator:codex-auth-cancel", (_event, attemptId: unknown) => {
    if (typeof attemptId !== "string") throw new Error("Invalid Codex login attempt");
    return codexAuth.cancel(attemptId);
  });
  ipcMain.handle("orchestrator:codex-auth-reopen", (_event, attemptId: unknown) => {
    if (typeof attemptId !== "string") throw new Error("Invalid Codex login attempt");
    return codexAuth.reopen(attemptId);
  });
  ipcMain.handle("orchestrator:codex-auth-copy-code", (_event, attemptId: unknown) => {
    if (typeof attemptId !== "string") throw new Error("Invalid Codex login attempt");
    return codexAuth.copyDeviceCode(attemptId);
  });
  ipcMain.handle("orchestrator:notifications-list", async (event, refreshScope: unknown) => {
    if (refreshScope !== undefined && (typeof refreshScope !== "string" || !refreshScope.trim())) throw new Error("Invalid notification refresh scope");
    const center = requireNotificationCenter();
    if (typeof refreshScope === "string") await center.poll(refreshScope);
    const snapshot = center.snapshot();
    const pending = pendingNotificationOpen;
    if (pending) {
      setImmediate(() => {
        if (pendingNotificationOpen === pending && !event.sender.isDestroyed()) event.sender.send("orchestrator:notification-open", pending);
      });
    }
    return snapshot;
  });
  ipcMain.handle("orchestrator:notifications-mark-read", (_event, eventId: unknown) => {
    if (typeof eventId !== "string" || !eventId.trim()) throw new Error("Notification event ID is required");
    if (pendingNotificationOpen?.event_id === eventId.trim()) pendingNotificationOpen = undefined;
    return requireNotificationCenter().markRead(eventId.trim());
  });
  ipcMain.handle("orchestrator:notifications-mark-all-read", () => requireNotificationCenter().markAllRead());
  ipcMain.handle("orchestrator:notifications-dismiss", (_event, eventId: unknown) => {
    if (typeof eventId !== "string" || !eventId.trim()) throw new Error("Notification event ID is required");
    const snapshot = requireNotificationCenter().dismissNotification(eventId.trim());
    if (pendingNotificationOpen?.event_id === eventId.trim()) pendingNotificationOpen = undefined;
    return snapshot;
  });
  ipcMain.handle("orchestrator:notifications-dismiss-many", (_event, scope: unknown) => {
    if (!isNotificationDismissScope(scope)) throw new Error("Invalid notification dismissal scope");
    const snapshot = requireNotificationCenter().dismissNotifications(scope);
    pendingNotificationOpen = undefined;
    return snapshot;
  });
  ipcMain.handle("orchestrator:notifications-settings", (_event, settings: unknown) => {
    if (!isNotificationSettings(settings)) throw new Error("Invalid notification settings");
    return requireNotificationCenter().updateSettings(settings);
  });
  ipcMain.handle(
    "orchestrator:approved-request",
    async (event, method: unknown, params: unknown) => {
      if (typeof method !== "string" || !isApprovedRpcMethod(method)) {
        throw new Error("Unsupported approved desktop request");
      }
      if (params !== undefined && (params === null || typeof params !== "object")) {
        throw new Error("Approved desktop request params must be an object");
      }
      const parent = BrowserWindow.fromWebContents(event.sender);
      if (!parent) {
        throw new Error("Desktop window is unavailable");
      }
      const confirmation = approvalCopy(method, (params ?? {}) as RpcParams);
      const result = await dialog.showMessageBox(parent, {
        type: "warning",
        title: confirmation.title,
        message: confirmation.message,
        detail: confirmation.detail,
        buttons: ["취소", confirmation.confirmLabel],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
      });
      if (result.response !== 1) {
        return null;
      }
      return planningRequests.request(method, {
        ...((params ?? {}) as RpcParams),
        approved: true,
      });
    },
  );
  ipcMain.handle(
    "orchestrator:select-path",
    async (event, kind: unknown) => {
      if (!isPathSelectionKind(kind)) {
        throw new Error("Unsupported path selection kind");
      }
      const parent = BrowserWindow.fromWebContents(event.sender);
      if (!parent) {
        throw new Error("Desktop window is unavailable");
      }
      const result = await dialog.showOpenDialog(parent, {
        title: pathSelectionTitle(kind),
        properties: kind === "config" || kind === "dotnet" || kind === "claude" ? ["openFile"] : ["openDirectory"],
        filters:
          kind === "config"
            ? [{ name: "Orchestrator TOML", extensions: ["toml"] }]
            : kind === "dotnet" && process.platform === "win32"
              ? [{ name: ".NET host (dotnet.exe)", extensions: ["exe"] }]
              : kind === "claude" && process.platform === "win32"
                ? [{ name: "Claude Code", extensions: ["exe", "cmd", "bat"] }]
              : undefined,
      });
      return result.canceled ? null : result.filePaths[0] ?? null;
    },
  );
  ipcMain.handle("orchestrator:open-archive-folder", async (_event, projectName: unknown, runId: unknown) => {
    if (typeof projectName !== "string" || !projectName.trim() || typeof runId !== "string" || !runId.trim()) {
      throw new Error("Archive folder requires project and run IDs");
    }
    const plan = await bridge.request<{ archived: boolean; record_path: string }>("runs.archivePlan", {
      projectName: projectName.trim(),
      runId: runId.trim(),
    });
    if (!plan.archived || !plan.record_path) throw new Error("Archived run record folder is unavailable");
    const openError = await shell.openPath(resolve(plan.record_path));
    if (openError) throw new Error(`Could not open archived run record folder: ${openError}`);
    return true;
  });
  ipcMain.handle("orchestrator:open-task-record", async (_event, projectName: unknown, runId: unknown, taskId: unknown) => {
    return openTaskRecord(bridge, app.getPath("temp"), (path) => shell.openPath(path), projectName, runId, taskId);
  });
  ipcMain.handle("orchestrator:restart-backend", async (event) => {
    const parent = BrowserWindow.fromWebContents(event.sender);
    if (!parent) {
      throw new Error("Desktop window is unavailable");
    }
    const result = await dialog.showMessageBox(parent, {
      type: "warning",
      title: "Python Backend 재시작",
      message: "응답하지 않는 Python Backend를 재시작할까요?",
      detail: "진행 중인 Planning, 색인 또는 Task 실행은 중단됩니다.",
      buttons: ["취소", "재시작"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (result.response !== 1) {
      return false;
    }
    await bridge.restart();
    await bridge.healthCheck();
    return true;
  });
  ipcMain.handle("orchestrator:planning-requests", () => ({ ...planningRequests.snapshot(), messageQueue: messageQueue?.snapshot() }));
  ipcMain.handle("orchestrator:queue-planning-message", (_event, input: QueuedMessageInput) => messageQueue!.enqueue(input));
  ipcMain.handle("orchestrator:change-queued-planning-message", (_event, change: QueuedMessageChange) => messageQueue!.change(change));
  ipcMain.handle("orchestrator:chat-controls", () => chatControls.snapshot());
  ipcMain.handle("orchestrator:interrupt-planning", async (_event, projectName: unknown, runId: unknown, requestId: unknown) => {
    if (typeof projectName !== "string" || !projectName.trim() || typeof runId !== "string" || typeof requestId !== "string") {
      throw new Error("Planning interruption requires the original project, run and request IDs");
    }
    return planningRequests.interrupt(projectName, runId, requestId);
  });
  try {
    desktopTray = new DesktopTray(showMainWindow, () => app.quit());
  } catch (error) {
    process.stderr.write(`Tray setup failed: ${String(error)}\n`);
    dialog.showErrorBox("트레이 준비 실패", "트레이를 만들 수 없어 창을 닫으면 앱이 종료됩니다. 앱을 다시 실행해 주세요.");
  }
  createWindow();
  app.on("activate", showMainWindow);
});

app.on("before-quit", () => desktopTray?.beginQuit());

app.on("window-all-closed", () => {
  if (process.platform !== "darwin" && !desktopTray?.isAvailable()) {
    app.quit();
  }
});

let backendStoppedForQuit = false;
let backendStoppingForQuit = false;

// Stop the backend only after every window has accepted closing its drafts.
app.on("will-quit", (event) => {
  if (backendStoppedForQuit) return;
  event.preventDefault();
  if (backendStoppingForQuit) return;
  backendStoppingForQuit = true;
  ipcMain.removeHandler("orchestrator:request");
  ipcMain.removeHandler("orchestrator:claude-credential-status");
  ipcMain.removeHandler("orchestrator:claude-credential-save");
  ipcMain.removeHandler("orchestrator:claude-credential-delete");
  ipcMain.removeHandler("orchestrator:codex-auth-status");
  ipcMain.removeHandler("orchestrator:codex-auth-start");
  ipcMain.removeHandler("orchestrator:codex-auth-api-key");
  ipcMain.removeHandler("orchestrator:codex-auth-get");
  ipcMain.removeHandler("orchestrator:codex-auth-cancel");
  ipcMain.removeHandler("orchestrator:codex-auth-reopen");
  ipcMain.removeHandler("orchestrator:codex-auth-copy-code");
  ipcMain.removeHandler("orchestrator:approved-request");
  ipcMain.removeHandler("orchestrator:select-path");
  ipcMain.removeHandler("orchestrator:open-archive-folder");
  ipcMain.removeHandler("orchestrator:restart-backend");
  ipcMain.removeHandler("orchestrator:interrupt-planning");
  ipcMain.removeHandler("orchestrator:planning-requests");
  ipcMain.removeHandler("orchestrator:chat-controls");
  ipcMain.removeHandler("orchestrator:queue-planning-message");
  ipcMain.removeHandler("orchestrator:change-queued-planning-message");
  messageQueue?.close();
  ipcMain.removeHandler("orchestrator:notifications-list");
  ipcMain.removeHandler("orchestrator:notifications-mark-read");
  ipcMain.removeHandler("orchestrator:notifications-mark-all-read");
  ipcMain.removeHandler("orchestrator:notifications-dismiss");
  ipcMain.removeHandler("orchestrator:notifications-dismiss-many");
  ipcMain.removeHandler("orchestrator:notifications-settings");
  notificationCenter?.stop();
  notificationCenter = undefined;
  codexAuth.clear();
  void bridge.stop().finally(() => {
    backendStoppedForQuit = true;
    desktopTray?.destroy();
    app.quit();
  });
});

function requireNotificationCenter(): WorkNotificationCenter {
  if (!notificationCenter) throw new Error("Notification center is unavailable");
  return notificationCenter;
}

function openNotificationTarget(notification: StoredWorkNotification): void {
  pendingNotificationOpen = notification;
  const focused = BrowserWindow.getFocusedWindow();
  const existing = focused && !focused.isDestroyed() ? focused : BrowserWindow.getAllWindows().find((window) => !window.isDestroyed());
  const target = existing || createWindow();
  const activate = () => {
    if (target.isDestroyed() || pendingNotificationOpen !== notification) return;
    if (target.isMinimized()) target.restore();
    target.show();
    target.moveTop();
    target.focus();
  };
  activate();
  if (!existing) target.once("ready-to-show", activate);
  const deliver = () => {
    if (!target.isDestroyed() && pendingNotificationOpen === notification) target.webContents.send("orchestrator:notification-open", notification);
  };
  if (target.webContents.isLoadingMainFrame()) target.webContents.once("did-finish-load", deliver);
  else deliver();
}

function isNotificationSettings(value: unknown): value is WorkNotificationSettings {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return ["enabled", "completion", "failure", "attention_required"].every(
    (key) => typeof candidate[key] === "boolean",
  );
}

function isNotificationDismissScope(value: unknown): value is WorkNotificationDismissScope {
  return value === "read" || value === "all";
}

function isCodexAuthMethod(value: unknown): value is CodexAuthMethod {
  return value === "browser" || value === "device_code";
}

function approvalCopy(
  method: ApprovedRpcMethod,
  params: RpcParams,
): { title: string; message: string; detail: string; confirmLabel: string } {
  const project = stringParam(params, "projectName");
  const run = stringParam(params, "runId");
  const task = stringParam(params, "taskId");
  const sharedWorkspace = params.workspaceMode === "shared";
  const remoteConfigured = params.remoteConfigured !== false;
  const cleanupTargetCount = typeof params.cleanupTargetCount === "number" ? params.cleanupTargetCount : 0;
  const copies: Record<
    ApprovedRpcMethod,
    { title: string; message: string; detail: string; confirmLabel: string }
  > = {
    "projects.updateWorkerMcp": {
      title: "작업 도구 연결",
      message: `'${project}'의 작업 AI가 사용할 도구 연결을 저장할까요?`,
      detail: "등록한 MCP의 실행 명령·서버 주소를 작업 AI에 연결합니다. 로컬 도구는 실행될 수 있으며, 도구를 통해 연결한 앱과 서비스에 작업할 수 있습니다. 현재 실행에는 영향을 주지 않고 다음 실행부터 적용합니다.",
      confirmLabel: "도구 연결 저장",
    },
    "projects.initializeGit": {
      title: "로컬 Git 저장소 만들기",
      message: `'${stringParam(params, "repo")}' 폴더를 Git 저장소로 초기화할까요?`,
      detail: "main branch와 로컬 .git을 만들고 오케스트레이터 관리 폴더를 Git 관리 대상에서 제외합니다. 기존 파일을 stage하거나 commit하지 않으며 원격 저장소도 변경하지 않습니다.",
      confirmLabel: "로컬 Git 저장소 만들기",
    },
    "projects.createInitialCommit": {
      title: "첫 commit 만들기",
      message: `선택한 파일 ${typeof params.selectionCount === "number" ? params.selectionCount : 0}개로 첫 commit을 만들까요?`,
      detail: `경로: ${stringParam(params, "repo")}\n커밋 메시지: ${stringParam(params, "message")}\n선택하지 않은 파일과 기존 staging은 보존하며 원격 저장소에는 전송하지 않습니다.`,
      confirmLabel: "첫 commit 만들기",
    },
    "runs.applyRecovery": {
      title: "현재 그룹 복구안 적용",
      message: `'${run}'에 선택한 선행 commit을 통합하고 Task를 재계획할까요?`,
      detail: "현재 그룹의 작업 branch와 Task 계획이 변경됩니다. 충돌 시 임의 해결하지 않으며, main·원격은 변경하지 않습니다. 복구 후 실행은 별도로 선택합니다.",
      confirmLabel: "복구안 적용",
    },
    "runs.applyConflictResolution": {
      title: "Main 충돌 해결안 적용",
      message: `'${run}'에 검토한 충돌 해결안을 적용하고 전체 검증을 다시 실행할까요?`,
      detail: "현재 그룹 작업 branch만 승인한 후보 commit으로 진행합니다. Main과 원격 저장소는 변경하지 않으며, 기준이나 후보 내용이 달라졌으면 중단됩니다.",
      confirmLabel: "적용 후 재검증",
    },
    "projects.remove": {
      title: "프로젝트 제외",
      message: `등록 목록에서 '${project}' 프로젝트를 제외할까요?`,
      detail: "저장소와 설정 파일은 삭제하지 않습니다.",
      confirmLabel: "제외",
    },
    "projects.updateCodeStylePreference": {
      title: "코드 스타일 설정 저장",
      message: `'${project}'의 코드 스타일 fallback과 사용자 지침을 저장할까요?`,
      detail: "이 PC의 프로젝트 registry만 변경합니다. 저장소 파일을 수정하거나 검사 명령을 실행하지 않으며, 새 Run부터 적용됩니다.",
      confirmLabel: "코드 스타일 저장",
    },
    "projects.updateMain": {
      title: "최신 Main 받기",
      message: `'${project}' 저장소의 Main을 fast-forward로 갱신할까요?`,
      detail: "저장소가 clean 상태가 아니거나 fast-forward가 불가능하면 중단됩니다.",
      confirmLabel: "최신 받기",
    },
    "projects.commitMainChanges": {
      title: "선택한 Main 변경 커밋",
      message: `'${project}'의 선택한 변경 ${typeof params.selectionCount === "number" ? params.selectionCount : 0}개를 커밋할까요?`,
      detail: `branch: ${stringParam(params, "branch")}\n커밋 메시지: ${stringParam(params, "message")}\n미선택 변경과 기존 staging은 보존됩니다.`,
      confirmLabel: "선택한 변경 커밋",
    },
    "projects.commitAndPushMainChanges": {
      title: "선택한 Main 변경 커밋·Push",
      message: `'${project}'의 선택한 변경을 커밋하고 ${stringParam(params, "remote")}/${stringParam(params, "branch")}에 Push할까요?`,
      detail: `선택 변경 ${typeof params.selectionCount === "number" ? params.selectionCount : 0}개 · 전송될 commit ${typeof params.pushCommitCount === "number" ? params.pushCommitCount + 1 : 1}개\n커밋 메시지: ${stringParam(params, "message")}\nforce Push는 사용하지 않습니다.`,
      confirmLabel: "커밋하고 Push",
    },
    "projects.pushMainCommits": {
      title: "Main commit Push",
      message: `'${project}'의 미전송 commit을 ${stringParam(params, "remote")}/${stringParam(params, "branch")}에 Push할까요?`,
      detail: `전송될 commit ${typeof params.pushCommitCount === "number" ? params.pushCommitCount : 0}개 · 대상 ${stringParam(params, "commit")}\nforce Push는 사용하지 않습니다.`,
      confirmLabel: "Main commit Push",
    },
    "runs.excludeTasks": {
      title: "Task 제외",
      message: `선택한 Task를 '${run}' 실행 계획에서 제외할까요?`,
      detail: "아직 실행하지 않은 Task만 제외할 수 있으며 의존성이 남으면 중단됩니다.",
      confirmLabel: "제외",
    },
    "runs.merge": {
      title: sharedWorkspace && remoteConfigured ? "Main 반영·Push" : "Main 반영",
      message: sharedWorkspace && remoteConfigured
        ? `'${run}'의 검증된 작업 commit을 Main에 반영하고 Main을 Push할까요?`
        : `'${run}'의 검증된 통합 commit을 Main에 반영할까요?`,
      detail: sharedWorkspace && remoteConfigured
        ? "검증 이후 Main이나 작업 branch가 변경되었으면 중단됩니다. 완료 후 로컬 공유 작업공간을 정리합니다."
        : remoteConfigured
          ? "검증 이후 Main이나 Task branch가 변경되었으면 중단됩니다."
          : "검증 이후 Main이나 작업 branch가 변경되었으면 중단됩니다. 로컬 Main만 변경하며 원격 저장소에는 전송하지 않습니다.",
      confirmLabel: sharedWorkspace && remoteConfigured ? "Main 반영·Push" : "Main 반영",
    },
    "runs.push": {
      title: sharedWorkspace ? "작업 Branch Push" : "Push",
      message: sharedWorkspace
        ? `'${run}'의 검증된 작업 branch를 원격 저장소에 Push할까요?`
        : `'${run}'의 Main commit을 원격 저장소에 Push할까요?`,
      detail: sharedWorkspace
        ? "원격 작업 branch 상태가 변경됩니다. Main 반영과 Main Push는 다음 단계에서 별도로 확인합니다."
        : "원격 저장소 상태가 변경됩니다.",
      confirmLabel: sharedWorkspace ? "작업 Branch Push" : "Push",
    },
    "runs.retryMainPush": {
      title: "Main Push 재시도",
      message: `'${run}'의 이미 Main에 반영된 commit을 원격 Main에 전송할까요?`,
      detail: "로컬·원격 commit을 다시 확인합니다. 로컬 Main 병합은 반복하지 않으며, 원격이 이미 목표 commit이면 전송하지 않습니다. 원격 변경이 있으면 중단하고 force Push는 사용하지 않습니다.",
      confirmLabel: "Main Push 재시도",
    },
    "runs.recoverMainApply": {
      title: "중단된 Main 반영 확인",
      message: `'${run}'의 Main 반영 결과를 원본 확인 후 확정할까요?`,
      detail: `저장소: ${stringParam(params, "repoPath")}\n검증 commit: ${stringParam(params, "targetCommit")}\nMain ref·index·작업 폴더가 이 commit과 일치할 때만 실행 기록을 복구합니다. Git 변경을 다시 적용하거나 commit하지 않습니다. 원격 Main Push는 별도 승인입니다.`,
      confirmLabel: "확인 후 복구 승인",
    },
    "runs.deploy": {
      title: "배포",
      message: `'${run}'의 설정된 배포 명령을 실행할까요?`,
      detail: "배포 대상 환경이 변경될 수 있습니다.",
      confirmLabel: "배포",
    },
    "runs.delete": {
      title: "작업 그룹 삭제",
      message: `'${run}' 작업 그룹과 소유 작업공간을 삭제할까요?`,
      detail: "Python이 해당 그룹이 소유한 branch와 worktree만 검증한 뒤 제거합니다.",
      confirmLabel: "삭제",
    },
    "runs.archive": {
      title: "완료 작업 그룹 보관",
      message: `'${run}' 완료 기록을 보관하고 작업공간 ${cleanupTargetCount}개를 확인할까요?`,
      detail: "요청·계획·Task·검증·로그와 결과 commit 참조는 보존합니다. 소유권과 청결 상태를 확인한 worktree만 정리하며, 보류된 대상은 기록에 남깁니다.",
      confirmLabel: "보관·정리",
    },
    "runs.retryArchiveCleanup": {
      title: "보관 작업공간 정리 재시도",
      message: "보류된 작업공간 정리를 다시 시도할까요?",
      detail: "현재 HEAD와 소유권, 미커밋 변경을 다시 확인하고 안전한 작업공간만 정리합니다.",
      confirmLabel: "정리 재시도",
    },
    "workspaces.cleanup": {
      title: "작업공간 정리",
      message: `'${task}' Task 작업공간을 정리할까요?`,
      detail: "Main에 통합된 clean 작업공간만 정리할 수 있습니다.",
      confirmLabel: "정리",
    },
    "locks.clear": {
      title: "실행 잠금 정리",
      message: `'${run}'의 stale 잠금을 정리할까요?`,
      detail: "같은 host에서 종료된 프로세스의 stale 잠금만 제거됩니다.",
      confirmLabel: "잠금 정리",
    },
  };
  return copies[method];
}

function stringParam(params: RpcParams, name: string): string {
  const value = params[name];
  return typeof value === "string" && value.trim() ? value.trim() : "선택 항목";
}

function isPathSelectionKind(value: unknown): value is PathSelectionKind {
  return ["repository", "config", "planningSource", "dotnet", "claude"].includes(String(value));
}

function pathSelectionTitle(kind: PathSelectionKind): string {
  if (kind === "repository") return "프로젝트 저장소 선택";
  if (kind === "config") return "orchestrator.toml 선택";
  if (kind === "dotnet") return "dotnet 실행 파일 선택";
  if (kind === "claude") return "Claude Code 실행 파일 선택";
  return "기획문서 디렉터리 선택";
}
