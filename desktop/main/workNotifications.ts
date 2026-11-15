import {
  StoredWorkNotification,
  WorkNotificationDismissScope,
  WorkNotificationPage,
  WorkNotificationSettings,
  WorkNotificationSnapshot,
  notificationErrorDetail,
} from "../shared/workNotifications";
import { sanitizeSettings } from "./notifications/codec";
import { MAX_READ_RECEIPTS } from "./notifications/contracts";
import type {
  NotificationBridge,
  NotificationHost,
  NotificationProject,
  PersistedNotificationState,
  ReadStateNotice,
  WaitingNotificationRun,
} from "./notifications/contracts";
import { WorkNotificationDelivery } from "./notifications/delivery";
import {
  cloneState,
  dismissItems,
  findDismissedReceipt,
  findReadReceipt,
  ingest,
  refreshScopeKey,
  upsertReadReceipt,
} from "./notifications/records";
import { recordRefreshFailure, recoverRefreshScope } from "./notifications/refresh";
import { WorkNotificationPersistenceError, loadState, writeState } from "./notifications/storage";

const POLL_INTERVAL_MS = 2_000;
const OS_GROUPING_WINDOW_MS = 3_000;

export class WorkNotificationCenter {
  private state: PersistedNotificationState;
  private storageWritable: boolean;
  private backupCurrentOnWrite: boolean;
  private readStateNotice: ReadStateNotice;
  private timer?: NodeJS.Timeout;
  private pollingGeneration = 0;
  private readonly delivery: WorkNotificationDelivery;
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
    this.delivery = new WorkNotificationDelivery({
      host: this.host, groupingWindowMs: this.groupingWindowMs,
      readState: () => this.state,
      persistCandidate: (candidate, throwOnError) => this.persistCandidate(candidate, throwOnError),
      readRun: (projectName, runId) => this.bridge.request<WaitingNotificationRun>("runs.get", { projectName, runId }),
    });
  }

  start(): void {
    if (this.timer) return;
    void this.poll();
    this.timer = setInterval(() => void this.poll(), POLL_INTERVAL_MS);
    this.timer.unref();
  }

  stop(): void {
    this.pollingGeneration++;
    if (this.timer) clearInterval(this.timer);
    this.delivery.stop();
    this.timer = undefined;
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
    this.delivery.removeDismissedPendingItems();
    return this.snapshot();
  }

  dismissNotifications(scope: WorkNotificationDismissScope): WorkNotificationSnapshot {
    const candidate = cloneState(this.state);
    const targets = candidate.items.filter((item) => scope === "all" || Boolean(item.read_at));
    if (targets.length === 0) return this.snapshot();
    dismissItems(candidate, targets);
    this.persistCandidate(candidate, true);
    this.delivery.removeDismissedPendingItems();
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
    const generation = this.pollingGeneration;
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
      if (generation !== this.pollingGeneration) return;
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
    if (generation !== this.pollingGeneration) return;
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
    try { await this.delivery.dispatch(fresh); }
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

export { WorkNotificationPersistenceError } from "./notifications/storage";
