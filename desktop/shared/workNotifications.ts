export type WorkNotificationKind = "completed" | "failed" | "attention_required" | "connection_unknown";

export interface WorkNotificationEvent {
  event_id: string;
  source_key: string;
  project_key: string;
  project_name: string;
  run_id: string;
  run_title: string;
  target_kind: string;
  target_id: string;
  request_id: string;
  verification_attempt_id: string;
  kind: WorkNotificationKind;
  occurred_at: string;
  summary_code: string;
  related_targets: string[];
  os_eligible: boolean;
}

export interface StoredWorkNotification extends WorkNotificationEvent {
  received_at: string;
  read_at: string;
  os_delivery_attempted_at: string;
  receipt_origin: "live" | "initial_baseline" | "recovered";
}

export interface WorkNotificationSettings {
  enabled: boolean;
  completion: boolean;
  failure: boolean;
  attention_required: boolean;
}

export type WorkNotificationDismissScope = "read" | "all";

export interface WorkNotificationRefreshIssue {
  event_id: string;
  scope_key: string;
  method: "projects.list" | "notifications.list";
  project_name: string;
  project_key: string;
  backend: "control" | "planning" | "work";
  kind: "query_failed" | "response_delayed" | "connection_lost";
  first_failed_at: string;
  last_failed_at: string;
  last_success_at: string;
  recovered_at: string;
  failure_count: number;
  error_code: string;
  error_detail: string;
  instance_id: string;
  request_id: number;
}

export interface WorkNotificationSnapshot {
  items: StoredWorkNotification[];
  unread_count: number;
  settings: WorkNotificationSettings;
  delivery_error: string;
  read_state_notice: "" | "read_state_recovered_from_backup" | "read_state_recovered_with_baseline" | "read_state_future_schema";
  refresh_issues?: WorkNotificationRefreshIssue[];
  revision?: number;
  storage_identity?: string;
}

export interface WorkNotificationPage {
  items: Omit<WorkNotificationEvent, "project_name">[];
  next_cursor: string;
  has_more: boolean;
}

const copies: Record<string, { title: string; body: string }> = {
  task_completed: { title: "Task 완료", body: "작업 결과가 다음 단계에 반영됐습니다." },
  group_completed: { title: "작업 그룹 완료", body: "결과를 확인하세요." },
  integration_verification_required: { title: "통합 검증 대기", body: "Task 실행이 끝났습니다. 통합 검증을 진행할까요?" },
  task_retry_required: { title: "수정 지시 저장 · 실행 전", body: "수정 지시가 저장됐습니다. 이 Task를 다시 실행할까요?" },
  remaining_tasks_resume_required: { title: "복구 후 다음 작업 대기", body: "수정한 Task가 완료됐습니다. 남은 Task를 계속 진행할까요?" },
  work_branch_push_required: { title: "통합 검증 완료", body: "작업 Branch Push 확인이 필요합니다." },
  main_apply_required: { title: "Main 반영 대기", body: "검증한 결과의 Main 반영을 확인해 주세요." },
  main_push_required: { title: "Main Push 대기", body: "반영된 Main의 Push를 확인해 주세요." },
  deployment_approval_required: { title: "배포 확인 필요", body: "Main Push가 완료됐습니다. 배포 여부를 확인하세요." },
  task_failed: { title: "Task 실패", body: "원인과 복구 방법을 확인하세요." },
  verification_failed: { title: "검증 실패", body: "실패 근거와 수정 결과를 확인하세요." },
  run_failed: { title: "작업 실패", body: "원인과 복구 방법을 확인하세요." },
  integration_conflict: { title: "Main 통합 충돌", body: "충돌 해결이 필요합니다." },
  conflict_candidate_ready: { title: "충돌 해결안 준비됨", body: "변경 내용을 검토해 주세요." },
  planning_clarification_required: { title: "Planning 확인 필요", body: "작업을 이어갈 답변을 확인하세요." },
  plan_confirmation_required: { title: "계획 확인 필요", body: "실행할 Task와 완료 조건을 확인하세요." },
  manual_task_required: { title: "수동 작업 대기", body: "Task를 확인하고 완료 여부를 입력하세요." },
  stopped_task_requires_action: { title: "Task 중지됨", body: "보존된 변경을 확인하고 재개 여부를 선택하세요." },
  notification_query_failed: { title: "작업 알림을 갱신하지 못했습니다", body: "최근 알림이 늦게 표시될 수 있습니다. 작업 진행 여부는 아직 확인하지 못했습니다." },
  notification_response_delayed: { title: "실행 엔진 응답이 지연되고 있습니다", body: "알림 조회 응답을 기다리지 못했습니다. 작업 진행 여부는 아직 확인하지 못했습니다." },
  notification_connection_lost: { title: "실행 엔진 연결이 끊겼습니다", body: "작업 결과를 다시 확인해야 합니다. 연결 진단을 확인하세요." },
  connection_unknown: { title: "이전 상태 확인 기록", body: "당시 처리 상태를 확인하지 못했습니다. 현재 알림 진단을 확인하세요." },
};

export function notificationNeedsWaitingCheck(event: Pick<WorkNotificationEvent, "summary_code">): boolean {
  return ["task_retry_required", "remaining_tasks_resume_required", "integration_verification_required",
    "work_branch_push_required", "main_apply_required"].includes(event.summary_code);
}

export function waitingNotificationIsCurrent(
  event: Pick<WorkNotificationEvent, "source_key" | "run_id">,
  run: { id: string; waiting_prompt?: { source_key: string } | null },
): boolean {
  return run.id === event.run_id && run.waiting_prompt?.source_key === event.source_key;
}

export function workNotificationCopy(event: Pick<WorkNotificationEvent, "summary_code" | "run_title">): {
  title: string;
  body: string;
} {
  const copy = copies[event.summary_code] || { title: "작업 상태 변경", body: "작업 상태를 확인하세요." };
  return { title: copy.title, body: event.run_title && event.summary_code !== "connection_unknown" ? `${event.run_title} · ${copy.body}` : copy.body };
}

export function notificationRefreshCopy(issue: WorkNotificationRefreshIssue): { title: string; body: string } {
  if (issue.recovered_at) return { title: "알림 갱신이 정상화됐습니다", body: "실패했던 조회의 정상 응답을 확인했습니다. 작업 결과 확인·알림 읽음과는 별개입니다." };
  const code = issue.kind === "connection_lost" ? "notification_connection_lost"
    : issue.kind === "response_delayed" ? "notification_response_delayed" : "notification_query_failed";
  return workNotificationCopy({ summary_code: code, run_title: "" });
}

export function notificationErrorDetail(value: unknown): string {
  const text = value instanceof Error ? value.message : String(value);
  return text.replace(/\b(Bearer|Basic)\s+[^\s,;"']+/gi, "$1 [가림]")
    .replace(/((?:["']?)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)(?:["']?)\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;}]+)/gi, "$1[가림]");
}

export function reconcileNotificationSnapshot(current: WorkNotificationSnapshot, incoming: WorkNotificationSnapshot): WorkNotificationSnapshot {
  return current.storage_identity && current.storage_identity === incoming.storage_identity
    && current.revision !== undefined && incoming.revision !== undefined && incoming.revision < current.revision ? current : incoming;
}

export function notificationSettingAllows(
  settings: WorkNotificationSettings,
  event: Pick<WorkNotificationEvent, "kind">,
): boolean {
  if (!settings.enabled) return false;
  if (event.kind === "completed") return settings.completion;
  if (event.kind === "attention_required") return settings.attention_required;
  return settings.failure;
}

export const defaultWorkNotificationSettings: WorkNotificationSettings = {
  enabled: true,
  completion: true,
  failure: true,
  attention_required: true,
};
