import { useEffect, useRef, useState } from "react";
import { Bell, RefreshCw } from "lucide-react";
import { reconcileNotificationSnapshot, workNotificationCopy, type StoredWorkNotification, type WorkNotificationSnapshot } from "../../shared/workNotifications";

export function MakerNotifications({ active, onOpen }: { active: boolean; onOpen(item: StoredWorkNotification): void }) {
  const [snapshot, setSnapshot] = useState<WorkNotificationSnapshot>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  function accept(next: WorkNotificationSnapshot) { setSnapshot(current => current ? reconcileNotificationSnapshot(current, next) : next); }
  useEffect(() => {
    if (!active) return;
    let alive = true;
    void window.orchestrator.listNotifications().then(value => { if (alive) accept(value); }).catch(cause => { if (alive) setError(String(cause)); });
    const unsubscribe = window.orchestrator.onNotificationsChanged(value => { if (alive) accept(value); });
    return () => { alive = false; unsubscribe(); };
  }, [active]);
  async function action(callback: () => Promise<WorkNotificationSnapshot>, after?: () => void) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try { accept(await callback()); after?.(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "알림을 처리하지 못했습니다."); }
    finally { pending.current = false; setBusy(false); }
  }
  return <div className="maker-content" hidden={!active}>
    <div className="maker-page-heading"><div><p className="maker-eyebrow">확인할 소식</p><h1>작업 알림</h1><p>제작 준비와 직접 확인할 일, 작업 결과를 알려드립니다.</p></div>
      <button className="maker-button" disabled={busy} onClick={() => void action(() => window.orchestrator.listNotifications())}><RefreshCw size={16} />새로 확인</button></div>
    <section className="maker-panel maker-form-stack"><div className="maker-actions">
      <button className="maker-button" disabled={busy || !snapshot?.unread_count} onClick={() => void action(() => window.orchestrator.markAllNotificationsRead())}>모두 읽음</button>
      <button className="maker-button" disabled={busy || !snapshot?.items.length} onClick={() => void action(() => window.orchestrator.dismissNotifications("read"))}>읽은 알림 정리</button>
      {snapshot ? <label className="maker-check-option"><input type="checkbox" checked={snapshot.settings.enabled} disabled={busy}
        onChange={event => void action(() => window.orchestrator.updateNotificationSettings({ ...snapshot.settings, enabled: event.target.checked }))} />작업 알림 받기</label> : null}
    </div>
      {error ? <p role="alert">{error}</p> : null}{snapshot?.delivery_error ? <p role="alert">{snapshot.delivery_error}</p> : null}
      {snapshot?.read_state_notice ? <p role="status">알림 기록을 복구했습니다. 읽음 상태를 다시 확인해 주세요.</p> : null}
      {!snapshot && !error ? <p role="status">알림을 불러오고 있어요.</p> : snapshot && !snapshot.items.length ? <div className="maker-empty"><Bell size={30} /><p>새로운 알림이 없습니다.</p></div> : null}
      <ol className="maker-notification-list">{snapshot?.items.map(item => {
        const copy = workNotificationCopy(item);
        return <li key={item.event_id} data-unread={!item.read_at}><button disabled={busy}
          onClick={() => void action(() => window.orchestrator.markNotificationRead(item.event_id), () => onOpen(item))}>
          <strong>{copy.title}</strong><span>{copy.body}</span><small>{item.project_name} · {new Date(item.occurred_at).toLocaleString("ko-KR")}</small></button>
          <button className="maker-button" aria-label={`${copy.title} 알림 지우기`} disabled={busy} onClick={() => void action(() => window.orchestrator.dismissNotification(item.event_id))}>지우기</button></li>;
      })}</ol>
      {snapshot?.refresh_issues?.filter(item => !item.recovered_at).map(item => <p role="status" key={item.event_id}>상태 확인 필요 · {item.project_name || "실행 엔진"} · {item.error_detail}</p>)}
    </section>
  </div>;
}
