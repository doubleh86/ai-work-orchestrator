import { useEffect, useRef, useSyncExternalStore } from "react";

import { DirectionChangeDrafts } from "./directionChangeDrafts";
import type { DirectionChangeRequest, RunState } from "./types";

const statusLabels: Record<DirectionChangeRequest["status"], string> = {
  received: "요청 접수",
  queued: "다음 안전한 단계 대기",
  reviewing: "검토 중",
  awaiting_confirmation: "변경 확인 대기",
  applied: "반영 완료",
  blocked: "반영 불가",
};

export function DirectionChangePanel({ projectName, run, drafts, onAccepted, onOpenPreview, onDiscuss, previewElsewhere = false }: {
  projectName: string;
  run: RunState;
  drafts: DirectionChangeDrafts;
  onAccepted(): void;
  onOpenPreview(): void;
  onDiscuss?(): void;
  previewElsewhere?: boolean;
}) {
  const draft = useSyncExternalStore(drafts.subscribe, () => drafts.read(projectName, run.id));
  const { text, busy, error } = draft;
  const mounted = useRef(true);
  const conversationText = [...(run.planning_messages || [])].reverse().find((message) => message.role === "user")?.text || "";
  const latestScope = useRef({ projectName, runId: run.id, stage: run.stage, onAccepted, conversationText });
  latestScope.current = { projectName, runId: run.id, stage: run.stage, onAccepted, conversationText };
  const active = run.tasks.find((task) => task.active_action || ["running", "reviewing", "revising"].includes(task.status));
  const requests = [...(run.direction_change_requests || [])].reverse();
  const latest = requests[0];
  const previewReady = !active && latest && latest.status !== "applied" && latest.status !== "reviewing";
  const canSubmit = run.stage === "executing";
  const inputState = text ? draft.pending?.editRevision === draft.editRevision
    ? busy ? "전송 결과 확인 중" : "접수 확인 필요" : "미전송 초안" : "";

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, [projectName, run.id]);

  useEffect(() => { drafts.reconcile(projectName, run); }, [drafts, projectName, run]);

  async function submit() {
    const scope = latestScope.current;
    if (!mounted.current || scope.projectName !== projectName || scope.runId !== run.id || scope.stage !== "executing") return;
    if (!drafts.read(projectName, run.id).text.trim() && scope.conversationText.trim()) drafts.edit(projectName, run.id, scope.conversationText);
    const pending = drafts.begin(projectName, run.id);
    if (!pending) return;
    try {
      const updated = await window.orchestrator.request<RunState>("runs.requestDirectionChange", {
        projectName, runId: run.id, requestId: pending.requestId, text: pending.text,
      });
      const confirmed = drafts.confirm(projectName, run.id, pending.requestId, updated);
      const current = latestScope.current;
      if (confirmed && mounted.current && current.projectName === projectName && current.runId === run.id) current.onAccepted();
    } catch (cause) {
      drafts.fail(projectName, run.id, pending.requestId, cause instanceof Error ? cause.message : String(cause));
    }
  }

  return <section className="direction-change" aria-labelledby="direction-change-title">
    <div className="direction-change__heading">
      <div><h3 id="direction-change-title">다음 작업 변경</h3><p>지금 하는 작업은 계속하고, 다음 작업 전에 변경을 확인합니다.</p></div>
      {previewReady && !previewElsewhere ? <button className="button button--secondary" type="button" onClick={onOpenPreview}>변경 미리보기</button> : null}
    </div>
    <p className="direction-change__context">{active ? `현재 작업 · ${active.title}` : "다음 작업 시작 전"}</p>
    {busy ? <p className="direction-change__context" role="status">전송 결과 확인 중 · 화면을 이동해도 접수 상태와 새 입력을 유지합니다.</p>
      : text && !draft.pending ? <p className="direction-change__context">{canSubmit ? `${inputState} · 대화 입력을 변경 요청으로 접수할 수 있습니다.` : "현재 단계에서는 새 요청을 접수할 수 없습니다. 초안을 보존했습니다."}</p> : null}
    {!busy && draft.pending && draft.pending.editRevision === draft.editRevision ? <p role="status">접수 확인 필요 · 같은 요청으로 다시 확인할 수 있습니다.</p> : null}
    {draft.pending && draft.pending.editRevision !== draft.editRevision ? <p className="direction-change__context">전송한 요청 · {draft.pending.text}</p> : null}
    {draft.confirmed && !requests.some((item) => item.request_id === draft.confirmed?.requestId)
      ? <p className="direction-change__context" role="status">요청 접수 확인 · {draft.confirmed.text}</p> : null}
    <div className="direction-change__actions">
      {onDiscuss ? <button className="button button--quiet" type="button" onClick={onDiscuss}>대화로 변경 논의</button> : null}
      {canSubmit ? <button className="button button--secondary" type="button" disabled={(!text.trim() && !conversationText.trim()) || busy} onClick={() => void submit()}>{busy ? "접수 중…" : "다음 작업에 반영 요청"}</button> : null}
    </div>
    {error ? <p className="direction-change__error" role="alert">전송 결과를 확인하지 못했습니다. 내용을 유지했습니다. {error}</p> : null}
    {latest ? <p role={latest.error ? "alert" : "status"}>{statusLabels[latest.status]} · {latest.next_step}{latest.error ? ` · ${latest.error}` : ""}</p> : null}
    {requests.length ? <details><summary>변경 요청 기록 · {requests.length}건</summary><ol className="direction-change__history">{requests.map((item) => <li key={item.request_id}>
      <strong>{statusLabels[item.status]}</strong><time>{new Date(item.updated_at || item.created_at).toLocaleString()}</time>
      <p>{item.text}</p><small>접수 당시 Task · {item.task_id ? `${item.task_id} ${item.task_title}` : "다음 Task 시작 전"} · {item.next_step}</small>
      {item.error ? <small className="direction-change__error">{item.error}</small> : null}
    </li>)}</ol></details> : null}
  </section>;
}
