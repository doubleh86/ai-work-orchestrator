import {
  StoredWorkNotification,
  notificationErrorDetail,
  notificationNeedsWaitingCheck,
  notificationSettingAllows,
  waitingNotificationIsCurrent,
  workNotificationCopy,
} from "../../shared/workNotifications";
import type { NotificationHost, PersistedNotificationState, WaitingNotificationRun } from "./contracts";
import { cloneState, findDismissedReceipt } from "./records";

interface NotificationDeliveryOptions {
  host: Pick<NotificationHost, "isBackground" | "showOs" | "open" | "log">;
  groupingWindowMs: number;
  readState(): PersistedNotificationState;
  persistCandidate(candidate: PersistedNotificationState, throwOnError: boolean): boolean;
  readRun(projectName: string, runId: string): Promise<WaitingNotificationRun>;
}

export class WorkNotificationDelivery {
  private dispatchTimer?: NodeJS.Timeout;
  private pendingOs: StoredWorkNotification[] = [];
  private deliveryGeneration = 0;

  constructor(private readonly options: NotificationDeliveryOptions) {}

  stop(): void {
    this.deliveryGeneration++;
    if (this.dispatchTimer) clearTimeout(this.dispatchTimer);
    this.dispatchTimer = undefined;
    this.pendingOs = [];
  }

  async dispatch(items: StoredWorkNotification[]): Promise<void> {
    const eligible = items.filter((item) => item.os_eligible && notificationSettingAllows(this.options.readState().settings, item));
    if (eligible.length === 0) return;
    this.pendingOs.push(...eligible);
    if (this.dispatchTimer) return;
    if (this.options.groupingWindowMs <= 0) {
      await this.flushOsNotifications();
      return;
    }
    this.dispatchTimer = setTimeout(() => void this.flushOsNotifications(), this.options.groupingWindowMs);
    this.dispatchTimer.unref();
  }

  private async flushOsNotifications(): Promise<void> {
    const generation = this.deliveryGeneration;
    if (this.dispatchTimer) clearTimeout(this.dispatchTimer);
    this.dispatchTimer = undefined;
    const pending = this.pendingOs;
    this.pendingOs = [];
    if (!this.options.host.isBackground() || pending.length === 0) return;
    const reads = new Map<string, Promise<{ id: string; waiting_prompt?: { source_key: string } | null }>>();
    const confirmed: StoredWorkNotification[] = [];
    for (const item of pending) {
      if (!notificationNeedsWaitingCheck(item)) { confirmed.push(item); continue; }
      const key = `${item.project_name}\0${item.run_id}`;
      try {
        let read = reads.get(key);
        if (!read) {
          read = this.options.readRun(item.project_name, item.run_id);
          reads.set(key, read);
        }
        if (waitingNotificationIsCurrent(item, await read)) confirmed.push(item);
      } catch (cause) {
        const failed = cloneState(this.options.readState());
        failed.delivery_error = `다음 단계 대기 상태를 확인하지 못했습니다. ${notificationErrorDetail(cause)}`;
        this.options.persistCandidate(failed, false);
        this.options.host.log(failed.delivery_error);
      }
    }
    if (generation !== this.deliveryGeneration || !this.options.host.isBackground()) return;
    const eligible = confirmed.filter((item) => {
      const stored = this.options.readState().items.find((current) => current.event_id === item.event_id);
      return stored && !stored.read_at && !stored.os_delivery_attempted_at && notificationSettingAllows(this.options.readState().settings, stored);
    });
    if (!eligible.length) return;
    const groups = new Map<string, StoredWorkNotification[]>();
    for (const item of eligible) {
      const key = `${item.project_name}\0${item.run_id}`;
      groups.set(key, [...(groups.get(key) || []), item]);
    }
    const candidate = cloneState(this.options.readState());
    const attemptedAt = new Date().toISOString();
    for (const item of eligible) {
      const stored = candidate.items.find((candidateItem) => candidateItem.event_id === item.event_id);
      if (stored) stored.os_delivery_attempted_at = attemptedAt;
    }
    if (!this.options.persistCandidate(candidate, false)) return;
    for (const group of groups.values()) {
      const selected = [...group].sort((left, right) => notificationPriority(right) - notificationPriority(left))[0];
      const copy = workNotificationCopy(selected);
      const title = group.length > 1 ? `${copy.title} · ${group.length}건` : copy.title;
      const shown = this.options.host.showOs(selected.project_name ? `AI Work Orchestrator · ${selected.project_name}` : "AI Work Orchestrator",
        `${title}\n${copy.body}`, () => this.options.host.open(selected));
      if (!shown) {
        const failed = cloneState(this.options.readState());
        failed.delivery_error = "데스크톱 알림을 표시하지 못했습니다. 알림함에서 결과를 확인하세요.";
        this.options.persistCandidate(failed, false);
      }
    }
  }

  removeDismissedPendingItems(): void {
    this.pendingOs = this.pendingOs.filter((item) => !findDismissedReceipt(this.options.readState(), item));
  }
}

function notificationPriority(event: StoredWorkNotification): number {
  if (event.kind === "failed" || event.kind === "connection_unknown") return 3;
  return event.kind === "attention_required" ? 2 : 1;
}
