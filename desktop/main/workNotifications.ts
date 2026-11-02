import { randomUUID } from "node:crypto";
import {
  closeSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";

import type { RpcMethod, RpcParams } from "../shared/rpc";
import { PythonBridgeRequestError } from "./pythonBridge";
import {
  defaultWorkNotificationSettings,
  notificationSettingAllows,
  notificationNeedsWaitingCheck,
  waitingNotificationIsCurrent,
  StoredWorkNotification,
  WorkNotificationEvent,
  WorkNotificationDismissScope,
  WorkNotificationPage,
  WorkNotificationSettings,
  WorkNotificationSnapshot,
  workNotificationCopy,
  notificationErrorDetail,
  WorkNotificationRefreshIssue,
} from "../shared/workNotifications";

interface NotificationProject {
  name: string;
  repo: string;
}

interface ProjectDeliveryState {
  cursor: string;
  initialized_at: string;
  baseline_at: string;
  project_key: string;
}

interface NotificationReadReceipt {
  stable_event_key: string;
  stable_source_key: string;
  read_at: string;
}

interface NotificationDismissedReceipt {
  stable_event_key: string;
  stable_source_key: string;
  dismissed_at: string;
}

interface PersistedNotificationState {
  schema_version: 4;
  revision: number;
  storage_identity: string;
  projects: Record<string, ProjectDeliveryState>;
  items: StoredWorkNotification[];
  read_receipts: NotificationReadReceipt[];
  dismissed_receipts: NotificationDismissedReceipt[];
  settings: WorkNotificationSettings;
  delivery_error: string;
  last_successful_write_at: string;
  refresh_issues: WorkNotificationRefreshIssue[];
  refresh_successes: Record<string, string>;
}

type ReadStateNotice = WorkNotificationSnapshot["read_state_notice"];

interface LoadedNotificationState {
  state: PersistedNotificationState;
  writable: boolean;
  backup_current_on_write: boolean;
  notice: ReadStateNotice;
}

interface ParsedState {
  status: "valid" | "invalid" | "future" | "missing";
  state?: PersistedNotificationState;
}

interface NotificationHost {
  isBackground(): boolean;
  publish(snapshot: WorkNotificationSnapshot): void;
  showOs(title: string, body: string, onClick: () => void): boolean;
  open(notification: StoredWorkNotification): void;
  log(message: string): void;
}

interface NotificationBridge {
  request<Result>(method: RpcMethod, params?: RpcParams): Promise<Result>;
}

const MAX_STORED_NOTIFICATIONS = 500;
const MAX_READ_RECEIPTS = 2_000;
const POLL_INTERVAL_MS = 2_000;
const OS_GROUPING_WINDOW_MS = 3_000;

export class WorkNotificationPersistenceError extends Error {
  readonly code = "notification_state_save_failed";

  constructor(cause?: unknown) {
    super("Notification read state could not be saved", cause === undefined ? undefined : { cause });
    this.name = "WorkNotificationPersistenceError";
  }
}

export class WorkNotificationCenter {
  private state: PersistedNotificationState;
  private storageWritable: boolean;
  private backupCurrentOnWrite: boolean;
  private readStateNotice: ReadStateNotice;
  private timer?: NodeJS.Timeout;
  private dispatchTimer?: NodeJS.Timeout;
  private pendingOs: StoredWorkNotification[] = [];
  private deliveryGeneration = 0;
  private polling?: Promise<void>;
  private pollingScope?: string;
  private persistenceError = "";

  constructor(
    private readonly storePath: string,
    private readonly bridge: NotificationBridge,
    private readonly host: NotificationHost,
    private readonly groupingWindowMs = OS_GROUPING_WINDOW_MS,
  ) {
    const loaded = loadState(storePath);
    this.state = loaded.state;
    this.storageWritable = loaded.writable;
    this.backupCurrentOnWrite = loaded.backup_current_on_write;
    this.readStateNotice = loaded.notice;
  }

  start(): void {
    if (this.timer) return;
    void this.poll();
    this.timer = setInterval(() => void this.poll(), POLL_INTERVAL_MS);
    this.timer.unref();
  }

  stop(): void {
    this.deliveryGeneration++;
    if (this.timer) clearInterval(this.timer);
    if (this.dispatchTimer) clearTimeout(this.dispatchTimer);
    this.timer = undefined;
    this.dispatchTimer = undefined;
    this.pendingOs = [];
  }

  snapshot(): WorkNotificationSnapshot {
    const items = [...this.state.items].sort((left, right) =>
      right.occurred_at.localeCompare(left.occurred_at) || right.event_id.localeCompare(left.event_id));
    return {
      items,
      unread_count: items.filter((item) => !item.read_at).length,
      settings: { ...this.state.settings },
      delivery_error: notificationErrorDetail(this.persistenceError || this.state.delivery_error),
      read_state_notice: this.readStateNotice,
      refresh_issues: this.state.refresh_issues.map((issue) => ({ ...issue })),
      revision: this.state.revision,
      storage_identity: this.state.storage_identity,
    };
  }

  markRead(eventId: string): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    const item = candidate.items.find((stored) => stored.event_id === eventId);
    if (!item || item.read_at) return this.snapshot();
    item.read_at = new Date().toISOString();
    upsertReadReceipt(candidate, item);
    this.persistCandidate(candidate, true);
    return this.snapshot();
  }

  markAllRead(): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    const readAt = new Date().toISOString();
    let changed = false;
    for (const item of candidate.items) {
      if (item.read_at) continue;
      changed = true;
      item.read_at = readAt;
      upsertReadReceipt(candidate, item);
    }
    const latestScopes = new Set<string>();
    candidate.refresh_issues = [...candidate.refresh_issues].reverse().filter((issue) => {
      const latest = !latestScopes.has(issue.scope_key);
      latestScopes.add(issue.scope_key);
      return latest || !issue.recovered_at || candidate.items.some((item) => item.event_id === issue.event_id);
    }).reverse();
    if (!changed) return this.snapshot();
    this.persistCandidate(candidate, true);
    return this.snapshot();
  }

  dismissNotification(eventId: string): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    const item = candidate.items.find((stored) => stored.event_id === eventId);
    if (!item) return this.snapshot();
    dismissItems(candidate, [item]);
    this.persistCandidate(candidate, true);
    this.removeDismissedPendingItems();
    return this.snapshot();
  }

  dismissNotifications(scope: WorkNotificationDismissScope): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    const targets = candidate.items.filter((item) => scope === "all" || Boolean(item.read_at));
    if (targets.length === 0) return this.snapshot();
    dismissItems(candidate, targets);
    this.persistCandidate(candidate, true);
    this.removeDismissedPendingItems();
    return this.snapshot();
  }

  updateSettings(settings: WorkNotificationSettings): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    candidate.settings = sanitizeSettings(settings);
    this.persistCandidate(candidate, true);
    return this.snapshot();
  }

  async poll(scopeKey?: string): Promise<void> {
    if (this.polling) {
      const coversScope = this.pollingScope === undefined || this.pollingScope === scopeKey;
      await this.polling;
      if (coversScope) return;
      return this.poll(scopeKey);
    }
    const polling = this.pollScopes(scopeKey);
    this.polling = polling;
    this.pollingScope = scopeKey;
    try { await polling; }
    finally { if (this.polling === polling) { this.polling = undefined; this.pollingScope = undefined; } }
  }

  private async pollScopes(scopeKey?: string): Promise<void> {
    const scope = scopeKey === undefined ? undefined : [...this.state.refresh_issues].reverse().find((issue) => issue.scope_key === scopeKey);
    if (scopeKey !== undefined && !scope) throw new Error("알림 조회 대상이 변경됐습니다. 현재 진단을 다시 확인하세요.");
    const generation = this.deliveryGeneration;
    let candidate = cloneState(this.state);
    const fresh: StoredWorkNotification[] = [];
    let projects: NotificationProject[];
    try {
      projects = await this.bridge.request<NotificationProject[]>("projects.list");
      if (!Array.isArray(projects) || projects.some((project) => !project || typeof project.name !== "string"
        || !project.name.trim() || typeof project.repo !== "string" || !project.repo.trim())) throw new Error("등록 프로젝트 조회 응답이 올바르지 않습니다.");
      recoverRefreshScope(candidate, refreshScopeKey("projects.list"));
    } catch (error) {
      const event = recordRefreshFailure(candidate, "projects.list", undefined, error);
      if (event) fresh.push(event);
      await this.finishPoll(candidate, fresh, generation);
      return;
    }
    if (scope?.method === "notifications.list" && !projects.some((project) => project.name === scope.project_name && project.repo === scope.project_key)) {
      const event = recordRefreshFailure(candidate, "notifications.list", { name: scope.project_name, repo: scope.project_key },
        new Error("조회 대상 프로젝트가 등록 목록에서 변경되거나 제외됐습니다."));
      if (event) fresh.push(event);
      await this.finishPoll(candidate, fresh, generation);
      return;
    }
    for (const project of projects) {
      if (generation !== this.deliveryGeneration) return;
      if (scope && (scope.method !== "notifications.list" || scope.project_name !== project.name || scope.project_key !== project.repo)) continue;
      const projectCandidate = cloneState(candidate);
      try {
        const items = await this.pollProject(projectCandidate, project);
        recoverRefreshScope(projectCandidate, refreshScopeKey("notifications.list", project));
        candidate = projectCandidate;
        fresh.push(...items);
      } catch (error) {
        const event = recordRefreshFailure(candidate, "notifications.list", project, error);
        if (event) fresh.push(event);
      }
    }
    await this.finishPoll(candidate, fresh, generation);
  }

  private async finishPoll(candidate: PersistedNotificationState, fresh: StoredWorkNotification[], generation: number): Promise<void> {
    if (generation !== this.deliveryGeneration) return;
    // Read/dismiss/settings and OS delivery receipts may change while an RPC is pending.
    candidate.settings = { ...this.state.settings };
    candidate.read_receipts = [...new Map([...candidate.read_receipts, ...this.state.read_receipts].map((receipt) => [receipt.stable_event_key, receipt])).values()].slice(-MAX_READ_RECEIPTS);
    candidate.dismissed_receipts = [...new Map([...candidate.dismissed_receipts, ...this.state.dismissed_receipts].map((receipt) => [receipt.stable_event_key, receipt])).values()];
    candidate.items = candidate.items.filter((item) => !findDismissedReceipt(candidate, item));
    for (const item of candidate.items) {
      item.read_at = findReadReceipt(candidate, item)?.read_at || item.read_at;
      item.os_delivery_attempted_at = this.state.items.find((stored) => stored.event_id === item.event_id)?.os_delivery_attempted_at || item.os_delivery_attempted_at;
    }
    if (!this.persistCandidate(candidate, false)) return;
    try { await this.dispatch(fresh); }
    catch (error) {
      const failed = cloneState(this.state);
      failed.delivery_error = `알림 전달에 실패했습니다. ${notificationErrorDetail(error)}`;
      this.persistCandidate(failed, false);
      this.host.log(failed.delivery_error);
    }
  }

  private async pollProject(state: PersistedNotificationState, project: NotificationProject): Promise<StoredWorkNotification[]> {
    const known = state.projects[project.name];
    const projectState = known?.project_key === project.repo
      ? known
      : { cursor: "", initialized_at: "", baseline_at: "", project_key: project.repo };
    const catchUp = !projectState.initialized_at;
    const fresh: StoredWorkNotification[] = [];
    let pageCount = 0;
    do {
      const page = await this.bridge.request<WorkNotificationPage>("notifications.list", {
        projectName: project.name,
        afterCursor: projectState.cursor,
        limit: 200,
      });
      if (!page || !Array.isArray(page.items) || typeof page.next_cursor !== "string" || typeof page.has_more !== "boolean") {
        throw new Error("프로젝트 알림 조회 응답이 올바르지 않습니다.");
      }
      for (const incoming of page.items) {
        const stored = ingest(state, { ...incoming, project_name: project.name }, catchUp ? "initial_baseline" : "live");
        if (stored && !catchUp) fresh.push(stored);
      }
      projectState.cursor = page.next_cursor || projectState.cursor;
      pageCount += 1;
      if (!page.has_more || pageCount >= 10) break;
    } while (true);
    if (catchUp) {
      const initializedAt = new Date().toISOString();
      projectState.initialized_at = initializedAt;
      projectState.baseline_at = initializedAt;
    }
    state.projects[project.name] = projectState;
    return fresh;
  }

  private async dispatch(items: StoredWorkNotification[]): Promise<void> {
    const eligible = items.filter((item) => item.os_eligible && notificationSettingAllows(this.state.settings, item));
    if (eligible.length === 0) return;
    this.pendingOs.push(...eligible);
    if (this.dispatchTimer) return;
    if (this.groupingWindowMs <= 0) {
      await this.flushOsNotifications();
      return;
    }
    this.dispatchTimer = setTimeout(() => void this.flushOsNotifications(), this.groupingWindowMs);
    this.dispatchTimer.unref();
  }

  private async flushOsNotifications(): Promise<void> {
    const generation = this.deliveryGeneration;
    if (this.dispatchTimer) clearTimeout(this.dispatchTimer);
    this.dispatchTimer = undefined;
    const pending = this.pendingOs;
    this.pendingOs = [];
    if (!this.host.isBackground() || pending.length === 0) return;
    const reads = new Map<string, Promise<{ id: string; waiting_prompt?: { source_key: string } | null }>>();
    const confirmed: StoredWorkNotification[] = [];
    for (const item of pending) {
      if (!notificationNeedsWaitingCheck(item)) { confirmed.push(item); continue; }
      const key = `${item.project_name}\0${item.run_id}`;
      try {
        let read = reads.get(key);
        if (!read) {
          read = this.bridge.request("runs.get", { projectName: item.project_name, runId: item.run_id });
          reads.set(key, read);
        }
        if (waitingNotificationIsCurrent(item, await read)) confirmed.push(item);
      } catch (cause) {
        const failed = cloneState(this.state);
        failed.delivery_error = `다음 단계 대기 상태를 확인하지 못했습니다. ${notificationErrorDetail(cause)}`;
        this.persistCandidate(failed, false);
        this.host.log(failed.delivery_error);
      }
    }
    if (generation !== this.deliveryGeneration || !this.host.isBackground()) return;
    const eligible = confirmed.filter((item) => {
      const stored = this.state.items.find((current) => current.event_id === item.event_id);
      return stored && !stored.read_at && !stored.os_delivery_attempted_at && notificationSettingAllows(this.state.settings, stored);
    });
    if (!eligible.length) return;
    const groups = new Map<string, StoredWorkNotification[]>();
    for (const item of eligible) {
      const key = `${item.project_name}\0${item.run_id}`;
      groups.set(key, [...(groups.get(key) || []), item]);
    }
    const candidate = cloneState(this.state);
    const attemptedAt = new Date().toISOString();
    for (const item of eligible) {
      const stored = candidate.items.find((candidateItem) => candidateItem.event_id === item.event_id);
      if (stored) stored.os_delivery_attempted_at = attemptedAt;
    }
    if (!this.persistCandidate(candidate, false)) return;
    for (const group of groups.values()) {
      const selected = [...group].sort((left, right) => notificationPriority(right) - notificationPriority(left))[0];
      const copy = workNotificationCopy(selected);
      const title = group.length > 1 ? `${copy.title} · ${group.length}건` : copy.title;
      const shown = this.host.showOs(selected.project_name ? `AI Work Orchestrator · ${selected.project_name}` : "AI Work Orchestrator",
        `${title}\n${copy.body}`, () => this.host.open(selected));
      if (!shown) {
        const failed = cloneState(this.state);
        failed.delivery_error = "데스크톱 알림을 표시하지 못했습니다. 알림함에서 결과를 확인하세요.";
        this.persistCandidate(failed, false);
      }
    }
  }

  private removeDismissedPendingItems(): void {
    this.pendingOs = this.pendingOs.filter((item) => !findDismissedReceipt(this.state, item));
  }

  private persistCandidate(candidate: PersistedNotificationState, throwOnError: boolean): boolean {
    if (!this.storageWritable) {
      const error = new WorkNotificationPersistenceError();
      this.host.log("work notification state save blocked by a newer schema");
      this.persistenceError = "이 버전에서는 알림 기록을 저장할 수 없습니다.";
      this.host.publish(this.snapshot());
      if (throwOnError) throw error;
      return false;
    }
    candidate.revision = this.state.revision + 1;
    candidate.last_successful_write_at = new Date().toISOString();
    try {
      writeState(this.storePath, candidate, this.backupCurrentOnWrite);
    } catch (cause) {
      const error = new WorkNotificationPersistenceError(cause);
      this.host.log(`work notification state save failed: ${notificationErrorDetail(cause)}`);
      this.persistenceError = "알림 기록을 저장하지 못했습니다. 최근 알림과 읽음 상태가 저장되지 않았을 수 있습니다.";
      this.host.publish(this.snapshot());
      if (throwOnError) throw error;
      return false;
    }
    this.state = candidate;
    this.persistenceError = "";
    this.backupCurrentOnWrite = true;
    this.host.publish(this.snapshot());
    return true;
  }
}

function refreshScopeKey(method: WorkNotificationRefreshIssue["method"], project?: NotificationProject): string {
  return JSON.stringify([method, project?.name || "", project?.repo || ""]);
}

function recordRefreshFailure(
  state: PersistedNotificationState, method: WorkNotificationRefreshIssue["method"], project: NotificationProject | undefined, error: unknown,
): StoredWorkNotification | undefined {
  const typed = error instanceof PythonBridgeRequestError ? error : undefined;
  const kind = typed?.kind === "timeout" ? "response_delayed"
    : typed && ["process_exit", "transport", "not_running", "stopped"].includes(typed.kind) ? "connection_lost" : "query_failed";
  const backend = typed?.backend || "control";
  const scopeKey = refreshScopeKey(method, project);
  const now = new Date().toISOString();
  let issue = state.refresh_issues.find((entry) => entry.scope_key === scopeKey && entry.backend === backend && !entry.recovered_at);
  if (!issue) {
    const sameConnection = kind === "connection_lost" ? state.refresh_issues.find((entry) =>
      entry.kind === kind && entry.backend === backend && entry.instance_id === (typed?.instanceId || "") && !entry.recovered_at) : undefined;
    issue = { event_id: sameConnection?.event_id || `notification-refresh-${randomUUID()}`, scope_key: scopeKey, method,
      project_name: project?.name || "", project_key: project?.repo || "", backend, kind,
      first_failed_at: now, last_failed_at: now, last_success_at: state.refresh_successes[scopeKey] || "",
      recovered_at: "", failure_count: 0, error_code: "", error_detail: "", instance_id: "", request_id: 0 };
    state.refresh_issues.push(issue);
  }
  issue.kind = kind;
  issue.last_failed_at = now;
  issue.failure_count++;
  issue.error_code = notificationErrorDetail(typed?.rpcCode || typed?.kind || "query_error");
  issue.error_detail = notificationErrorDetail(error).slice(0, 4_000);
  issue.instance_id = typed?.instanceId || "";
  issue.request_id = typed?.requestId || 0;
  if (issue.failure_count < 2 && kind !== "connection_lost") return undefined;
  return ingest(state, {
    event_id: issue.event_id, source_key: `notification-refresh:${issue.event_id}`,
    // Main-generated incidents keep one receipt identity even if the diagnosis escalates.
    project_key: "",
    project_name: kind === "connection_lost" ? "" : issue.project_name,
    run_id: "", run_title: "", target_kind: "notification_refresh", target_id: scopeKey,
    request_id: "", verification_attempt_id: "", kind: "attention_required", occurred_at: issue.first_failed_at,
    summary_code: kind === "connection_lost" ? "notification_connection_lost"
      : kind === "response_delayed" ? "notification_response_delayed" : "notification_query_failed",
    related_targets: [], os_eligible: true,
  }, "live");
}

function recoverRefreshScope(state: PersistedNotificationState, scopeKey: string): void {
  const now = new Date().toISOString();
  state.refresh_successes[scopeKey] = now;
  for (const issue of state.refresh_issues) {
    if (issue.scope_key !== scopeKey || issue.backend !== "control" || issue.recovered_at) continue;
    issue.recovered_at = now;
    issue.last_success_at = now;
  }
}

function sanitizeRefreshIssues(value: unknown): WorkNotificationRefreshIssue[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("Invalid notification refresh state");
  const issues: WorkNotificationRefreshIssue[] = [];
  for (const entry of value) {
    if (!isRecord(entry) || !nonEmptyString(entry.event_id) || !nonEmptyString(entry.scope_key)
      || (entry.method !== "projects.list" && entry.method !== "notifications.list")
      || (entry.backend !== "control" && entry.backend !== "planning" && entry.backend !== "work")
      || (entry.kind !== "query_failed" && entry.kind !== "response_delayed" && entry.kind !== "connection_lost")) throw new Error("Invalid notification refresh issue");
    const scopeKey = refreshScopeKey(entry.method, { name: stringValue(entry.project_name), repo: stringValue(entry.project_key) });
    if (entry.scope_key !== scopeKey || !Number.isFinite(Date.parse(stringValue(entry.first_failed_at)))) throw new Error("Invalid notification refresh scope");
    issues.push({ event_id: stringValue(entry.event_id), scope_key: scopeKey, method: entry.method,
      project_name: stringValue(entry.project_name), project_key: stringValue(entry.project_key), backend: entry.backend, kind: entry.kind,
      first_failed_at: stringValue(entry.first_failed_at), last_failed_at: stringValue(entry.last_failed_at),
      last_success_at: stringValue(entry.last_success_at), recovered_at: stringValue(entry.recovered_at),
      failure_count: nonNegativeInteger(entry.failure_count), error_code: notificationErrorDetail(stringValue(entry.error_code)),
      error_detail: notificationErrorDetail(stringValue(entry.error_detail)), instance_id: stringValue(entry.instance_id), request_id: nonNegativeInteger(entry.request_id) });
  }
  return issues;
}

function emptyState(): PersistedNotificationState {
  return {
    schema_version: 4,
    revision: 0,
    storage_identity: randomUUID(),
    projects: {},
    items: [],
    read_receipts: [],
    dismissed_receipts: [],
    settings: { ...defaultWorkNotificationSettings },
    delivery_error: "",
    last_successful_write_at: "",
    refresh_issues: [],
    refresh_successes: {},
  };
}

function loadState(path: string): LoadedNotificationState {
  const primary = parseStateFile(path);
  if (primary.status === "future") {
    return { state: emptyState(), writable: false, backup_current_on_write: false, notice: "read_state_future_schema" };
  }
  if (primary.status === "valid" && primary.state) {
    return { state: primary.state, writable: true, backup_current_on_write: true, notice: "" };
  }
  const backup = parseStateFile(backupPath(path));
  if (backup.status === "valid" && backup.state) {
    return {
      state: markRecovered(backup.state),
      writable: true,
      backup_current_on_write: false,
      notice: "read_state_recovered_from_backup",
    };
  }
  const missing = primary.status === "missing" && backup.status === "missing";
  return {
    state: emptyState(),
    writable: true,
    backup_current_on_write: false,
    notice: missing ? "" : "read_state_recovered_with_baseline",
  };
}

function parseStateFile(path: string): ParsedState {
  if (!existsSync(path)) return { status: "missing" };
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!isRecord(raw) || typeof raw.schema_version !== "number") return { status: "invalid" };
    if (raw.schema_version > 4) return { status: "future" };
    if (raw.schema_version === 1) return { status: "valid", state: migrateV1(raw) };
    if (raw.schema_version === 2) return { status: "valid", state: migrateV2(raw) };
    if (raw.schema_version !== 3 && raw.schema_version !== 4) return { status: "invalid" };
    if (raw.schema_version === 4 && (!Array.isArray(raw.refresh_issues) || !isRecord(raw.refresh_successes))) return { status: "invalid" };
    return { status: "valid", state: sanitizeCurrentState(raw) };
  } catch {
    return { status: "invalid" };
  }
}

function migrateV1(raw: Record<string, unknown>): PersistedNotificationState {
  const state = emptyState();
  const migratedAt = new Date().toISOString();
  state.projects = sanitizeProjects(raw.projects, migratedAt);
  state.items = sanitizeItems(raw.items, "recovered");
  state.settings = sanitizeSettings(isRecord(raw.settings) ? raw.settings : undefined);
  state.delivery_error = typeof raw.delivery_error === "string" ? raw.delivery_error : "";
  for (const item of state.items) {
    if (item.read_at) upsertReadReceipt(state, item);
  }
  return state;
}

function migrateV2(raw: Record<string, unknown>): PersistedNotificationState {
  return sanitizeState(raw, false);
}

function sanitizeCurrentState(raw: Record<string, unknown>): PersistedNotificationState {
  return sanitizeState(raw, true);
}

function sanitizeState(raw: Record<string, unknown>, includeDismissedReceipts: boolean): PersistedNotificationState {
  const state = emptyState();
  state.revision = nonNegativeInteger(raw.revision);
  state.storage_identity = nonEmptyString(raw.storage_identity) || state.storage_identity;
  state.projects = sanitizeProjects(raw.projects, "");
  state.items = sanitizeItems(raw.items, "recovered");
  state.read_receipts = sanitizeReadReceipts(raw.read_receipts);
  state.dismissed_receipts = includeDismissedReceipts ? sanitizeDismissedReceipts(raw.dismissed_receipts) : [];
  state.settings = sanitizeSettings(isRecord(raw.settings) ? raw.settings : undefined);
  state.delivery_error = typeof raw.delivery_error === "string" ? raw.delivery_error : "";
  state.last_successful_write_at = typeof raw.last_successful_write_at === "string" ? raw.last_successful_write_at : "";
  state.refresh_issues = sanitizeRefreshIssues(raw.refresh_issues);
  if (isRecord(raw.refresh_successes)) {
    for (const [key, value] of Object.entries(raw.refresh_successes)) {
      if (typeof value === "string" && Number.isFinite(Date.parse(value))) state.refresh_successes[key] = value;
    }
  }
  for (const item of state.items) {
    if (item.read_at) upsertReadReceipt(state, item);
  }
  return state;
}

function sanitizeDismissedReceipts(value: unknown): NotificationDismissedReceipt[] {
  if (!Array.isArray(value)) return [];
  const receipts: NotificationDismissedReceipt[] = [];
  for (const candidate of value) {
    if (!isRecord(candidate)) continue;
    const eventKey = nonEmptyString(candidate.stable_event_key);
    const dismissedAt = nonEmptyString(candidate.dismissed_at);
    if (!eventKey || !dismissedAt) continue;
    receipts.push({
      stable_event_key: eventKey,
      stable_source_key: stringValue(candidate.stable_source_key),
      dismissed_at: dismissedAt,
    });
  }
  return receipts;
}

function sanitizeProjects(value: unknown, migratedAt: string): Record<string, ProjectDeliveryState> {
  if (!isRecord(value)) return {};
  const projects: Record<string, ProjectDeliveryState> = {};
  for (const [name, candidate] of Object.entries(value)) {
    if (!isRecord(candidate)) continue;
    const projectKey = typeof candidate.project_key === "string" ? candidate.project_key : "";
    if (!projectKey) continue;
    const initializedAt = typeof candidate.initialized_at === "string"
      ? candidate.initialized_at
      : candidate.initialized === true ? migratedAt : "";
    projects[name] = {
      cursor: typeof candidate.cursor === "string" ? candidate.cursor : "",
      initialized_at: initializedAt,
      baseline_at: typeof candidate.baseline_at === "string" ? candidate.baseline_at : initializedAt,
      project_key: projectKey,
    };
  }
  return projects;
}

function sanitizeItems(value: unknown, fallbackOrigin: StoredWorkNotification["receipt_origin"]): StoredWorkNotification[] {
  if (!Array.isArray(value)) return [];
  const items: StoredWorkNotification[] = [];
  for (const candidate of value) {
    const item = sanitizeItem(candidate, fallbackOrigin);
    if (item) items.push(item);
  }
  return items.slice(-MAX_STORED_NOTIFICATIONS);
}

function sanitizeItem(value: unknown, fallbackOrigin: StoredWorkNotification["receipt_origin"]): StoredWorkNotification | undefined {
  if (!isRecord(value)) return undefined;
  const kind = value.kind;
  if (kind !== "completed" && kind !== "failed" && kind !== "attention_required" && kind !== "connection_unknown") return undefined;
  const eventId = nonEmptyString(value.event_id);
  const sourceKey = nonEmptyString(value.source_key);
  const occurredAt = nonEmptyString(value.occurred_at);
  if (!eventId || !sourceKey || !occurredAt) return undefined;
  const origin = value.receipt_origin;
  return {
    event_id: eventId,
    source_key: sourceKey,
    project_key: stringValue(value.project_key),
    project_name: stringValue(value.project_name),
    run_id: stringValue(value.run_id),
    run_title: stringValue(value.run_title),
    target_kind: stringValue(value.target_kind),
    target_id: stringValue(value.target_id),
    request_id: stringValue(value.request_id),
    verification_attempt_id: stringValue(value.verification_attempt_id),
    kind,
    occurred_at: occurredAt,
    summary_code: stringValue(value.summary_code),
    related_targets: Array.isArray(value.related_targets) ? value.related_targets.filter((item): item is string => typeof item === "string") : [],
    os_eligible: value.os_eligible === true,
    received_at: stringValue(value.received_at),
    read_at: stringValue(value.read_at),
    os_delivery_attempted_at: stringValue(value.os_delivery_attempted_at),
    receipt_origin: origin === "live" || origin === "initial_baseline" || origin === "recovered" ? origin : fallbackOrigin,
  };
}

function sanitizeReadReceipts(value: unknown): NotificationReadReceipt[] {
  if (!Array.isArray(value)) return [];
  const receipts: NotificationReadReceipt[] = [];
  for (const candidate of value) {
    if (!isRecord(candidate)) continue;
    const eventKey = nonEmptyString(candidate.stable_event_key);
    const readAt = nonEmptyString(candidate.read_at);
    if (!eventKey || !readAt) continue;
    receipts.push({
      stable_event_key: eventKey,
      stable_source_key: stringValue(candidate.stable_source_key),
      read_at: readAt,
    });
  }
  return receipts.slice(-MAX_READ_RECEIPTS);
}

function ingest(
  state: PersistedNotificationState,
  event: WorkNotificationEvent,
  receiptOrigin: StoredWorkNotification["receipt_origin"],
): StoredWorkNotification | undefined {
  if (findDismissedReceipt(state, event)) return undefined;
  if (state.items.some((item) => item.event_id === event.event_id || (
    item.project_name === event.project_name && item.source_key === event.source_key
  ))) return undefined;
  const receivedAt = new Date().toISOString();
  const receipt = findReadReceipt(state, event);
  const stored: StoredWorkNotification = {
    ...event,
    received_at: receivedAt,
    read_at: receipt?.read_at || (receiptOrigin === "initial_baseline" ? receivedAt : ""),
    os_delivery_attempted_at: "",
    receipt_origin: receiptOrigin,
  };
  state.items.push(stored);
  state.items.sort((left, right) => left.occurred_at.localeCompare(right.occurred_at) || left.event_id.localeCompare(right.event_id));
  if (state.items.length > MAX_STORED_NOTIFICATIONS) {
    state.items.splice(0, state.items.length - MAX_STORED_NOTIFICATIONS);
  }
  if (stored.read_at) upsertReadReceipt(state, stored);
  return stored;
}

function dismissItems(state: PersistedNotificationState, items: StoredWorkNotification[]): void {
  const dismissedAt = new Date().toISOString();
  const eventIds = new Set(items.map((item) => item.event_id));
  for (const item of items) upsertDismissedReceipt(state, item, dismissedAt);
  state.items = state.items.filter((item) => !eventIds.has(item.event_id));
}

function findDismissedReceipt(
  state: PersistedNotificationState,
  event: Pick<WorkNotificationEvent, "project_key" | "event_id" | "source_key">,
): NotificationDismissedReceipt | undefined {
  const eventKey = stableEventKey(event);
  const sourceKey = stableSourceKey(event);
  return state.dismissed_receipts.find((receipt) =>
    receipt.stable_event_key === eventKey || Boolean(sourceKey && receipt.stable_source_key === sourceKey));
}

function upsertDismissedReceipt(state: PersistedNotificationState, item: StoredWorkNotification, dismissedAt: string): void {
  const eventKey = stableEventKey(item);
  const sourceKey = stableSourceKey(item);
  const existing = findDismissedReceipt(state, item);
  if (existing) {
    existing.stable_event_key = eventKey;
    existing.stable_source_key = sourceKey;
    existing.dismissed_at = existing.dismissed_at || dismissedAt;
  } else {
    state.dismissed_receipts.push({ stable_event_key: eventKey, stable_source_key: sourceKey, dismissed_at: dismissedAt });
  }
}

function findReadReceipt(
  state: PersistedNotificationState,
  event: Pick<WorkNotificationEvent, "project_key" | "event_id" | "source_key">,
): NotificationReadReceipt | undefined {
  const eventKey = stableEventKey(event);
  const sourceKey = stableSourceKey(event);
  return state.read_receipts.find((receipt) =>
    receipt.stable_event_key === eventKey || Boolean(sourceKey && receipt.stable_source_key === sourceKey));
}

function upsertReadReceipt(state: PersistedNotificationState, item: StoredWorkNotification): void {
  if (!item.read_at) return;
  const eventKey = stableEventKey(item);
  const sourceKey = stableSourceKey(item);
  const existing = state.read_receipts.find((receipt) =>
    receipt.stable_event_key === eventKey || Boolean(sourceKey && receipt.stable_source_key === sourceKey));
  if (existing) {
    existing.read_at = existing.read_at || item.read_at;
    existing.stable_event_key = eventKey;
    existing.stable_source_key = sourceKey;
  } else {
    state.read_receipts.push({ stable_event_key: eventKey, stable_source_key: sourceKey, read_at: item.read_at });
  }
  state.read_receipts.sort((left, right) => left.read_at.localeCompare(right.read_at));
  if (state.read_receipts.length > MAX_READ_RECEIPTS) {
    state.read_receipts.splice(0, state.read_receipts.length - MAX_READ_RECEIPTS);
  }
}

function stableEventKey(event: Pick<WorkNotificationEvent, "project_key" | "event_id">): string {
  return `${event.project_key}\0${event.event_id}`;
}

function stableSourceKey(event: Pick<WorkNotificationEvent, "project_key" | "source_key">): string {
  return event.source_key ? `${event.project_key}\0${event.source_key}` : "";
}

function markRecovered(state: PersistedNotificationState): PersistedNotificationState {
  for (const item of state.items) item.receipt_origin = "recovered";
  return state;
}

function cloneState(state: PersistedNotificationState): PersistedNotificationState {
  return JSON.parse(JSON.stringify(state)) as PersistedNotificationState;
}

function writeState(path: string, state: PersistedNotificationState, backupCurrent: boolean): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.tmp`;
  let fileDescriptor: number | undefined;
  try {
    fileDescriptor = openSync(temporary, "wx");
    writeFileSync(fileDescriptor, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    fsyncSync(fileDescriptor);
    closeSync(fileDescriptor);
    fileDescriptor = undefined;
    if (backupCurrent && existsSync(path)) copyFileSync(path, backupPath(path));
    renameSync(temporary, path);
  } finally {
    if (fileDescriptor !== undefined) closeSync(fileDescriptor);
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}

function backupPath(path: string): string {
  return `${path}.bak`;
}

function sanitizeSettings(settings?: Partial<WorkNotificationSettings>): WorkNotificationSettings {
  return {
    enabled: settings?.enabled !== false,
    completion: settings?.completion !== false,
    failure: settings?.failure !== false,
    attention_required: settings?.attention_required !== false,
  };
}

function notificationPriority(event: StoredWorkNotification): number {
  if (event.kind === "failed" || event.kind === "connection_unknown") return 3;
  return event.kind === "attention_required" ? 2 : 1;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function nonEmptyString(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

function nonNegativeInteger(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : 0;
}
