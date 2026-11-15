import {
  StoredWorkNotification,
  WorkNotificationRefreshIssue,
  WorkNotificationSettings,
  defaultWorkNotificationSettings,
  notificationErrorDetail,
} from "../../shared/workNotifications";
import { MAX_READ_RECEIPTS, MAX_STORED_NOTIFICATIONS } from "./contracts";
import type { NotificationDismissedReceipt, NotificationReadReceipt, PersistedNotificationState, ProjectDeliveryState } from "./contracts";
import { refreshScopeKey, upsertReadReceipt } from "./records";
import { randomUUID } from "node:crypto";

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

export function emptyState(): PersistedNotificationState {
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

export function migrateV1(raw: Record<string, unknown>): PersistedNotificationState {
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

export function migrateV2(raw: Record<string, unknown>): PersistedNotificationState {
  return sanitizeState(raw, false);
}

export function sanitizeCurrentState(raw: Record<string, unknown>): PersistedNotificationState {
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

export function sanitizeSettings(settings?: Partial<WorkNotificationSettings>): WorkNotificationSettings {
  return {
    enabled: settings?.enabled !== false,
    completion: settings?.completion !== false,
    failure: settings?.failure !== false,
    attention_required: settings?.attention_required !== false,
  };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
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
