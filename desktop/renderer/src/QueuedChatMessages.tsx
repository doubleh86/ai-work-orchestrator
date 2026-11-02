import { useRef, useState } from "react";
import { Clock3, Pencil, RotateCcw, X } from "lucide-react";
import type { QueuedMessageChange, QueuedPlanningMessage } from "../../shared/planningMessageQueue";

const statusLabels: Record<QueuedPlanningMessage["status"], string> = {
  queued: "답변 후 전송", paused: "예약 일시 정지", sending: "예약 메시지 전송 중", sent: "전송 완료",
  failed: "예약 전송 실패", uncertain: "전송 결과 확인 필요",
};

export function QueuedChatMessages({ items, onChange, onRestore }: {
  items: QueuedPlanningMessage[];
  onChange(change: QueuedMessageChange): Promise<boolean>;
  onRestore(item: QueuedPlanningMessage): Promise<boolean>;
}) {
  const [pending, setPending] = useState("");
  const pendingRef = useRef(false);
  const visible = items.filter(item => item.status !== "sent");
  if (!visible.length) return null;
  const act = async (item: QueuedPlanningMessage, action: QueuedMessageChange["action"] | "restore") => {
    if (pendingRef.current) return;
    pendingRef.current = true; setPending(item.id);
    try {
      if (action === "restore") await onRestore(item);
      else await onChange({ projectName: item.projectName, runId: item.runId, id: item.id, revision: item.revision, action });
    } finally { pendingRef.current = false; setPending(""); }
  };
  return <section className="chat-queue" aria-label="예약 메시지">
    <div className="chat-queue__heading" aria-live="polite"><Clock3 size={14} aria-hidden="true" /><span>예약 메시지 {visible.length}</span></div>
    <ol>{visible.map(item => <li key={item.id} data-status={item.status}>
      <div className="chat-queue__body"><small>{statusLabels[item.status]} · {item.profile.planningModel || item.profile.planningAgentId}</small>
        <p>{item.text}</p>
        {item.error ? <small className="chat-queue__error" role={item.status === "failed" || item.status === "uncertain" ? "alert" : undefined}>{item.error}</small> : null}
      </div>
      {item.status !== "sending" ? <div className="chat-queue__actions">
        {["paused", "failed"].includes(item.status) ? <button className="button button--quiet" type="button" disabled={Boolean(pending)}
          onClick={() => void act(item, "resume")}><RotateCcw size={14} aria-hidden="true" />다시 예약</button> : null}
        <button className="button button--quiet" type="button" disabled={Boolean(pending)}
          aria-label={item.status === "uncertain" ? "예약 메시지를 입력창으로 가져오기" : "예약 메시지 수정"} title="입력창에서 수정"
          onClick={() => void act(item, "restore")}><Pencil size={14} aria-hidden="true" />{item.status === "uncertain" ? "입력창으로" : null}</button>
        <button className="button button--quiet" type="button" disabled={Boolean(pending)} aria-label="예약 취소"
          onClick={() => void act(item, "cancel")}><X size={14} aria-hidden="true" /></button>
      </div> : null}
    </li>)}</ol>
  </section>;
}
