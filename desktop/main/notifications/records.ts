import { StoredWorkNotification, WorkNotificationEvent, WorkNotificationRefreshIssue } from "../../shared/workNotifications";
import { MAX_READ_RECEIPTS, MAX_STORED_NOTIFICATIONS } from "./contracts";
import type { NotificationDismissedReceipt, NotificationProject, NotificationReadReceipt, PersistedNotificationState } from "./contracts";

export function refreshScopeKey(method: WorkNotificationRefreshIssue["method"], project?: NotificationProject): string {
  return JSON.stringify([method, project?.name || "", project?.repo || ""]);
}

export function ingest(
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

export function dismissItems(state: PersistedNotificationState, items: StoredWorkNotification[]): void {
  const dismissedAt = new Date().toISOString();
  const eventIds = new Set(items.map((item) => item.event_id));
  for (const item of items) upsertDismissedReceipt(state, item, dismissedAt);
  state.items = state.items.filter((item) => !eventIds.has(item.event_id));
}

export function findDismissedReceipt(
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

export function findReadReceipt(
  state: PersistedNotificationState,
  event: Pick<WorkNotificationEvent, "project_key" | "event_id" | "source_key">,
): NotificationReadReceipt | undefined {
  const eventKey = stableEventKey(event);
  const sourceKey = stableSourceKey(event);
  return state.read_receipts.find((receipt) =>
    receipt.stable_event_key === eventKey || Boolean(sourceKey && receipt.stable_source_key === sourceKey));
}

export function upsertReadReceipt(state: PersistedNotificationState, item: StoredWorkNotification): void {
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

export function markRecovered(state: PersistedNotificationState): PersistedNotificationState {
  for (const item of state.items) item.receipt_origin = "recovered";
  return state;
}

export function cloneState(state: PersistedNotificationState): PersistedNotificationState {
  return JSON.parse(JSON.stringify(state)) as PersistedNotificationState;
}
