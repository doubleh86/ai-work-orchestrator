import { useEffect, useRef, type RefObject } from "react";
import { ListChecks } from "lucide-react";
import { attentionItemKey, confirmedAttentionCount } from "./attentionInboxPresentation";
import type { AttentionItem, AttentionSnapshot } from "./types";

function attentionSummary(snapshot: AttentionSnapshot, error: string) {
  const confirmed = confirmedAttentionCount(snapshot);
  const uncertain = snapshot.items.filter(item => item.status === "check_required" || item.stale).length;
  const complete = Boolean(snapshot.checked_at) && !error && !snapshot.errors.length && !uncertain;
  const warning = error ? "조회 실패" : snapshot.errors.length ? "일부 조회 실패" : uncertain ? "상태 미확인"
    : !snapshot.checked_at ? "미확인" : "";
  return { confirmed, uncertain, complete, warning };
}

export function AttentionInboxTrigger({ snapshot, error, open, buttonRef, onClick }: {
  snapshot: AttentionSnapshot;
  error: string;
  open: boolean;
  buttonRef: RefObject<HTMLButtonElement | null>;
  onClick(): void;
}) {
  const { confirmed, complete, warning } = attentionSummary(snapshot, error);
  const label = complete ? `확인할 일 ${confirmed}개` : confirmed ? `확인된 일 ${confirmed}개` : "확인할 일";
  return <button ref={buttonRef} className="button button--quiet" type="button" data-navigation-action aria-haspopup="dialog"
    aria-expanded={open} onClick={onClick}>
    <ListChecks aria-hidden="true" size={15} />{label}
    {warning ? <span className="attention-inbox__warning">{warning}</span> : null}
  </button>;
}

export function AttentionInbox({ snapshot, loading, error, onRefresh, onOpen, onClose }: {
  snapshot: AttentionSnapshot;
  loading: boolean;
  error: string;
  onRefresh(): void;
  onOpen(item: AttentionItem): void;
  onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
    return () => { if (element?.open) element.close(); };
  }, []);
  const { confirmed, uncertain, complete } = attentionSummary(snapshot, error);
  const title = complete ? `처리할 일 ${confirmed}개` : confirmed ? `확인된 일 ${confirmed}개` : "처리할 일";
  return <dialog ref={dialog} className="modal attention-inbox" aria-labelledby="attention-inbox-title" onCancel={onClose}>
    <header className="attention-inbox__header">
      <div><h2 id="attention-inbox-title">{title}</h2><p>지금 선택이 필요한 작업을 확인하세요. 항목을 열면 최신 상태를 확인합니다.</p></div>
      <button type="button" className="button button--quiet" onClick={onClose}>닫기</button>
    </header>
    <div className="attention-inbox__body" aria-busy={loading}>
      <div className="attention-inbox__status">
        <span role="status">{loading ? "현재 상태 확인 중…" : snapshot.checked_at ? `확인 ${new Date(snapshot.checked_at).toLocaleTimeString()}` : "현재 상태를 아직 확인하지 못했습니다."}
          {uncertain ? ` · 상태 확인 필요 ${uncertain}개` : ""}</span>
        <button type="button" className="button button--quiet" disabled={loading} onClick={onRefresh}>새로고침</button>
      </div>
      {error ? <p className="attention-inbox__error" role="alert">처리할 일을 조회하지 못했습니다. 이전 항목은 상태 확인이 필요합니다. {error}</p> : null}
      {snapshot.errors.length ? <div className="attention-inbox__error" role="alert">
        <p>조회하지 못한 프로젝트 {snapshot.errors.length}개</p>
        <ul>{snapshot.errors.map((item) => <li key={item.project_name}>{item.project_name} · {item.error}</li>)}</ul>
      </div> : null}
      <ul className="attention-inbox__items">{snapshot.items.map((item) => <li key={attentionItemKey(item)} data-uncertain={Boolean(item.stale || item.status === "check_required")}>
        <span className="attention-inbox__project">{item.project_name} · {item.run_title}</span>
        <strong>{item.stale || item.status === "check_required" ? "상태 확인 필요" : item.title}</strong>
        <p>{item.stale ? "이전 조회 결과입니다. 최신 상태를 확인한 뒤 행동을 선택하세요." : item.reason}</p>
        <button type="button" className="button button--quiet" onClick={() => onOpen(item)}>{item.stale || item.status === "check_required" ? "그룹 상태 확인" : `${item.title} 화면 열기`}</button>
      </li>)}</ul>
      {!snapshot.items.length && snapshot.checked_at && !error && !snapshot.errors.length && !loading ? <p>현재 사람이 선택할 미해결 항목이 없습니다.</p> : null}
    </div>
  </dialog>;
}
