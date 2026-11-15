import { StoredWorkNotification, WorkNotificationRefreshIssue, notificationErrorDetail } from "../../shared/workNotifications";
import { PythonBridgeRequestError } from "../pythonBridge";
import type { NotificationProject, PersistedNotificationState } from "./contracts";
import { ingest, refreshScopeKey } from "./records";
import { randomUUID } from "node:crypto";

export function recordRefreshFailure(
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

export function recoverRefreshScope(state: PersistedNotificationState, scopeKey: string): void {
  const now = new Date().toISOString();
  state.refresh_successes[scopeKey] = now;
  for (const issue of state.refresh_issues) {
    if (issue.scope_key !== scopeKey || issue.backend !== "control" || issue.recovered_at) continue;
    issue.recovered_at = now;
    issue.last_success_at = now;
  }
}
