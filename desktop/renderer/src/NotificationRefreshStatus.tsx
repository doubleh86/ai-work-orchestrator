import { notificationRefreshCopy, type WorkNotificationRefreshIssue } from "../../shared/workNotifications";

export function NotificationRefreshStatus({ issues, busy, onRefresh }: {
  issues: WorkNotificationRefreshIssue[];
  busy: boolean;
  onRefresh(scopeKey: string): void;
}) {
  const currentScopes = new Set<string>();
  const current = [...issues].reverse().filter((issue) => {
    if (currentScopes.has(issue.scope_key)) return false;
    currentScopes.add(issue.scope_key);
    return true;
  }).reverse();
  if (!current.length) return null;
  const time = (value: string) => value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString("ko-KR") : "확인 기록 없음";
  return <div className="notification-refresh-status" aria-label="알림 갱신 상태">
    {current.map((issue) => {
      const copy = notificationRefreshCopy(issue);
      return <section key={issue.scope_key} data-recovered={Boolean(issue.recovered_at)}>
        <strong>{copy.title}</strong>
        <span>{issue.project_name || "등록 프로젝트 목록"}</span>
        <p>{copy.body}</p>
        {!issue.recovered_at ? <button type="button" className="button button--quiet" disabled={busy}
          onClick={() => onRefresh(issue.scope_key)}>{busy ? "현재 상태 확인 중" : "상태 다시 확인"}</button> : <small>복구됨 · {time(issue.recovered_at)}</small>}
        <details><summary>진단 상세</summary><dl>
          <dt>조회 대상</dt><dd>{issue.method === "projects.list" ? "등록 프로젝트 목록" : "프로젝트 작업 알림"}</dd>
          <dt>첫 실패</dt><dd>{time(issue.first_failed_at)}</dd>
          <dt>최근 실패</dt><dd>{time(issue.last_failed_at)}</dd>
          <dt>마지막 정상 조회</dt><dd>{time(issue.last_success_at)}</dd>
          <dt>오류 분류</dt><dd>{issue.error_code}</dd>
          <dt>확인한 연결</dt><dd>{issue.backend} · {issue.instance_id || "인스턴스 정보 없음"} · 요청 {issue.request_id || "정보 없음"}</dd>
        </dl><pre>{issue.error_detail}</pre></details>
      </section>;
    })}
  </div>;
}
