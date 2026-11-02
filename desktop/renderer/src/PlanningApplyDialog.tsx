import { useEffect, useRef, useState } from "react";

import type { PlanningApplyPreview, PlanningPreviewStatus, RunState } from "./types";
import { PlanningPreviewSession, previewApplyTiming, previewRetryTask } from "./planningPreviewRequest";
import { PlanningPreviewProgress } from "./PlanningPreviewProgress";
import type { PlanningPreviewContext } from "./PlanningPreviewProgress";
import { providerFailurePresentation } from "./providerFailure";

const kindLabels: Record<PlanningApplyPreview["changes"][number]["kind"], string> = {
  added: "추가",
  modified: "수정",
  excluded: "제외",
  unchanged: "그대로 유지",
  review_required: "재검토 필요",
};

const fieldLabels: Record<string, string> = {
  title: "제목", description: "설명", capabilities: "역량", depends_on: "선행 Task",
  is_prerequisite: "선행 작업 여부", acceptance_criteria: "완료 조건", expected_paths: "예상 경로",
  forbidden_paths: "금지 경로", verify_commands: "검증 명령", risk_level: "위험도",
  agent_id: "실행 Agent", provider_id: "실행 공급자", model: "실행 모델",
  reasoning_effort: "추론 강도", reviewer_agent_id: "리뷰 Agent",
  reviewer_provider_id: "리뷰 공급자", reviewer_model: "리뷰 모델",
};

function previewCounts(preview: PlanningApplyPreview) {
  return {
    added: preview.changes.filter((item) => item.kind === "added").length,
    modified: preview.changes.filter((item) => item.kind === "modified").length,
    excluded: preview.changes.filter((item) => item.kind === "excluded").length,
    unchanged: preview.changes.filter((item) => item.kind === "unchanged").length,
    review: preview.changes.filter((item) => item.kind === "review_required").length,
  };
}

function appliedNextStep(run: RunState | undefined): string {
  if (run?.stage === "failed") {
    return "변경된 Task와 실패 단계의 복구 행동을 확인하세요. 계획 반영만으로 실패 상태가 해소되지는 않습니다.";
  }
  if (run?.stage === "executing") {
    return "변경된 Task를 확인한 뒤 ‘그룹 재개’를 선택하세요. Task는 자동으로 시작되지 않습니다.";
  }
  if (run?.stage === "planned" || run?.stage === "needs_clarification") {
    return "변경된 계획을 확인·확정한 뒤 작업 실행을 선택하세요.";
  }
  if (run?.stage === "ready_to_merge") {
    return "Task 실행은 완료됐습니다. 통합·정리 단계에서 검증 결과를 확인하세요.";
  }
  return "작업 그룹으로 돌아가 현재 상태와 가능한 다음 행동을 확인하세요.";
}

function samePreview(candidate: PlanningApplyPreview | undefined, expected: PlanningApplyPreview): boolean {
  return Boolean(candidate && candidate.run_id === expected.run_id && candidate.preview_id === expected.preview_id
    && candidate.request_id === expected.request_id && candidate.fingerprint === expected.fingerprint
    && candidate.candidate_digest === expected.candidate_digest);
}

function confirmedReceipt(preview: PlanningApplyPreview): boolean {
  return preview.status === "applied" && Boolean(preview.actual && [preview.actual.added, preview.actual.modified,
    preview.actual.excluded, preview.actual.unchanged].every((count) => Number.isSafeInteger(count) && count >= 0));
}

export function PlanningApplyDialog({ projectName, runId, planDirty, context, embedded = false, continueTaskId, onContinue, onApplied, onRetry, onClose, onTaskEditStart }: {
  projectName: string;
  runId: string;
  planDirty: boolean;
  context?: PlanningPreviewContext;
  embedded?: boolean;
  continueTaskId?: string;
  onContinue?(taskId: string, run: RunState): void;
  onApplied(run: RunState, preview: PlanningApplyPreview): void;
  onRetry(taskId: string): void;
  onClose(): void;
  onTaskEditStart?(): () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(true);
  const session = useRef<PlanningPreviewSession | null>(null);
  const applyPending = useRef(false);
  const regeneratePending = useRef(false);
  const lookupVersion = useRef(0);
  const applyFailure = useRef("");
  const scope = useRef({ projectName, runId, planDirty });
  scope.current = { projectName, runId, planDirty };
  const onAppliedRef = useRef(onApplied);
  onAppliedRef.current = onApplied;
  const onTaskEditStartRef = useRef(onTaskEditStart);
  onTaskEditStartRef.current = onTaskEditStart;
  const [snapshot, setSnapshot] = useState<PlanningPreviewStatus>();
  const [appliedResult, setAppliedResult] = useState<{ receipt: string; run: RunState }>();
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [clockNow, setClockNow] = useState(Date.now());
  const [groupCheck, setGroupCheck] = useState(0);
  const [groupError, setGroupError] = useState("");
  const latestSnapshot = useRef(snapshot);
  latestSnapshot.current = snapshot;
  const preview = snapshot?.preview || undefined;
  const appliedReceipt = snapshot?.phase === "applied" && preview?.status === "applied"
    ? JSON.stringify([preview.run_id, preview.preview_id, preview.request_id, preview.fingerprint, preview.candidate_digest]) : "";
  const confirmedRun = appliedReceipt === appliedResult?.receipt ? appliedResult.run : undefined;
  const waiting = !snapshot || snapshot.work_state === "active" || ["chat", "generating", "comparing"].includes(snapshot.phase);
  const busy = waiting || applying;
  const changed = preview?.changes.filter((item) => item.kind !== "unchanged") || [];
  const repairTask = context?.projectName === projectName && context.run.id === runId && preview?.run_id === runId
    && context.run.stage === "failed" && context.run.failed_step === "agent_execution"
    && changed.length === 1 && changed[0].kind === "modified"
    ? context.run.tasks.find((task) => task.id === changed[0].task_id && task.status === "failed") : undefined;
  const retryTaskId = preview ? previewRetryTask(confirmedRun, preview) : "";
  const repairPreview = Boolean(repairTask || retryTaskId);
  const continueTaskIndex = context?.run.tasks.findIndex((task) => task.id === continueTaskId) ?? -1;
  const continueEligible = Boolean(onContinue && continueTaskId && continueTaskIndex >= 0 && repairTask?.id === continueTaskId);

  function current(owner: PlanningPreviewSession | null): owner is PlanningPreviewSession {
    return Boolean(owner && mounted.current && session.current === owner
      && scope.current.projectName === projectName && scope.current.runId === runId);
  }

  function publish(status: PlanningPreviewStatus | undefined) {
    latestSnapshot.current = status;
    setSnapshot(status);
  }

  function createSession() {
    lookupVersion.current += 1;
    applyFailure.current = "";
    const owner = new PlanningPreviewSession(window.orchestrator, projectName, runId, crypto.randomUUID(), (status) => {
      if (current(owner) && !applyPending.current) {
        if (status.phase === "applied") applyFailure.current = "";
        publish(status);
        setError(applyFailure.current);
      }
    }, () => onTaskEditStartRef.current?.() || (() => {}));
    session.current = owner;
    return owner;
  }

  async function check(owner = session.current) {
    if (!current(owner) || applyPending.current) return;
    const version = ++lookupVersion.current;
    try { await owner.check(); }
    catch (cause) {
      if (current(owner) && version === lookupVersion.current && !applyPending.current) {
        publish(undefined);
        setError(`${applyFailure.current} ${String(cause)}`.trim());
      }
    }
  }

  useEffect(() => {
    mounted.current = true;
    applyPending.current = false;
    regeneratePending.current = false;
    publish(undefined);
    setAppliedResult(undefined);
    setApplying(false);
    setError("");
    setGroupError("");
    const element = dialog.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    const sidebar = !embedded ? document.getElementById("planning-sidebar") as HTMLDialogElement | null : null;
    const suspended = Boolean(sidebar?.matches(":modal"));
    sidebar?.setAttribute("data-planning-preview-open", "");
    if (suspended) sidebar?.close();
    if (!embedded && element && !element.open) element.showModal();
    const currentSession = createSession();
    let active = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight || !active || regeneratePending.current || applyPending.current) return;
      inFlight = true;
      try { await check(); } finally { inFlight = false; }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      mounted.current = false;
      active = false;
      currentSession.dispose();
      session.current?.dispose();
      window.clearInterval(timer);
      if (element?.open) element.close();
      sidebar?.removeAttribute("data-planning-preview-open");
      if (sidebar?.isConnected && !sidebar.open) {
        if (!window.matchMedia("(max-width: 74rem)").matches) sidebar.show();
        else if (suspended) sidebar.showModal();
      }
      if (!embedded && previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [projectName, runId]);

  useEffect(() => {
    if (snapshot?.work_state !== "active") return;
    setClockNow(Date.now());
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [snapshot?.work_state]);

  useEffect(() => {
    if (!appliedReceipt) { setGroupError(""); return; }
    if (!preview || confirmedRun) return;
    const owner = session.current;
    let active = true;
    setGroupError("");
    void window.orchestrator.request<RunState>("runs.get", { projectName, runId }).then((run) => {
      if (!active || !current(owner) || !samePreview(latestSnapshot.current?.preview || undefined, preview)
        || latestSnapshot.current?.phase !== "applied") return;
      if (run.id !== runId || preview.run_id !== runId || !confirmedReceipt(preview)) {
        throw new Error("조회한 그룹 또는 계획 반영 기록이 확인한 후보와 일치하지 않습니다.");
      }
      setAppliedResult({ receipt: appliedReceipt, run });
      onAppliedRef.current(run, preview);
    }).catch((cause: unknown) => {
      if (active && current(owner) && samePreview(latestSnapshot.current?.preview || undefined, preview)
        && latestSnapshot.current?.phase === "applied") {
        setGroupError(`계획 반영 기록은 확인했지만 그룹 상태를 조회하지 못했습니다. ${String(cause)}`);
      }
    });
    return () => { active = false; };
  }, [appliedReceipt, confirmedRun, groupCheck, projectName, runId]);

  async function manualCheck() {
    if (!current(session.current) || applyPending.current || latestSnapshot.current !== snapshot) return;
    setError("");
    publish(undefined);
    setGroupCheck((value) => value + 1);
    await check();
  }

  async function regenerate() {
    if (!current(session.current) || latestSnapshot.current !== snapshot || busy || !snapshot?.can_generate
      || applyPending.current || regeneratePending.current) return;
    regeneratePending.current = true;
    session.current?.dispose();
    const owner = createSession();
    publish(undefined);
    setError("");
    try { await owner.restart(); }
    catch (cause) { if (current(owner)) setError(String(cause)); }
    finally { if (current(owner)) regeneratePending.current = false; }
  }

  async function apply(continueAfterApply = false) {
    const owner = session.current;
    if (continueAfterApply && !continueEligible) return;
    if (!current(owner) || latestSnapshot.current !== snapshot || !preview || snapshot?.phase !== "ready"
      || preview.status !== "preview" || preview.run_id !== runId || !preview.preview_id || !preview.fingerprint
      || !preview.candidate_digest || preview.stale || !preview.can_apply || scope.current.planDirty || busy
      || snapshot.work_state !== "idle" || !snapshot.can_apply
      || applyPending.current || regeneratePending.current) return;
    applyPending.current = true;
    lookupVersion.current += 1;
    applyFailure.current = "";
    owner.stopAutomaticGeneration();
    owner.invalidate();
    setApplying(true);
    setError("");
    let finishEditing = onTaskEditStartRef.current?.();
    let mutationRequested = false;
    try {
      const confirmed = await window.orchestrator.request<PlanningPreviewStatus>("runs.planningPreviewStatus", { projectName, runId });
      if (!current(owner)) return;
      publish(confirmed);
      if (scope.current.planDirty || confirmed.work_state !== "idle" || confirmed.phase !== "ready" || !confirmed.can_apply
        || !samePreview(confirmed.preview || undefined, preview) || confirmed.preview?.stale || !confirmed.preview?.can_apply) {
        setError("현재 작업 또는 후보가 변경됐습니다. 최신 상태를 확인한 뒤 다시 반영해 주세요.");
        return;
      }
      mutationRequested = true;
      const result = await window.orchestrator.request<{ run: RunState; preview: PlanningApplyPreview }>(
        "runs.applyPlanningPreview", { projectName, runId, previewId: preview.preview_id,
          fingerprint: preview.fingerprint, candidateDigest: preview.candidate_digest },
      );
      if (!current(owner)) return;
      if (result.run?.id !== runId || !samePreview(result.preview, preview) || !confirmedReceipt(result.preview)) {
        throw new Error("반영 응답이 확인한 그룹·후보의 적용 기록과 일치하지 않습니다.");
      }
      publish({ ...confirmed, phase: "applied", can_generate: false, can_apply: false, preview: result.preview });
      setAppliedResult({ receipt: JSON.stringify([result.preview.run_id, result.preview.preview_id,
        result.preview.request_id, result.preview.fingerprint, result.preview.candidate_digest]), run: result.run });
      setGroupError("");
      onAppliedRef.current(result.run, result.preview);
      finishEditing?.();
      finishEditing = undefined;
      if (continueAfterApply && continueTaskId && previewRetryTask(result.run, result.preview) === continueTaskId) {
        onContinue?.(continueTaskId, result.run);
      }
    } catch (cause) {
      if (current(owner)) {
        applyPending.current = false;
        publish(undefined);
        applyFailure.current = mutationRequested ? `반영 결과를 다시 확인합니다. ${String(cause)}`
          : `반영 전 작업 상태를 확인하지 못했습니다. ${String(cause)}`;
        setError(applyFailure.current);
        if (mutationRequested) await check(owner);
      }
    } finally {
      finishEditing?.();
      if (current(owner)) { applyPending.current = false; setApplying(false); }
    }
  }

  function close() {
    if (current(session.current) && !applyPending.current) onClose();
  }

  const counts = preview ? previewCounts(preview) : undefined;
  const errors = [...new Set([snapshot?.error, error, groupError].filter((message): message is string => Boolean(message)))];
  const actualMismatch = Boolean(preview?.actual && counts && (
    preview.actual.added !== counts.added || preview.actual.modified !== counts.modified
    || preview.actual.excluded !== counts.excluded || preview.actual.unchanged !== counts.unchanged
  ));
  const Surface = embedded ? "section" : "dialog";
  return <Surface ref={embedded ? undefined : dialog} className="planning-preview-dialog" aria-labelledby="planning-preview-title" onCancel={(event) => {
    event.preventDefault();
    close();
  }}>
    <header className="planning-preview-dialog__header">
      <div><h2 id="planning-preview-title">{repairPreview ? "복구안 확인" : embedded ? "AI 수정 제안" : "Task 변경 미리보기"}</h2></div>
      <div className="planning-preview-dialog__close">
        <button className="button button--quiet" type="button" disabled={applying} onClick={close}>{embedded ? "제안 접기" : preview?.status === "applied" ? "작업 그룹으로" : "닫기"}</button>
      </div>
    </header>
    <p>{repairPreview ? "복구안은 계획에만 저장 · 작업 재실행은 별도" : "계획만 변경 · Task 실행과 Main 반영은 별도"}</p>
    {context && (embedded || continueEligible) ? <p>{embedded ? `완료 작업 ${context.run.tasks.filter((task) => ["completed", "merged"].includes(task.status)).length}개는 보존합니다.` : ""}
      {continueEligible ? ` ‘계속’은 ${continueTaskIndex + 1}번 재실행 성공 후 남은 작업도 이어갑니다. 중지·다른 실패·승인 대기 시 멈춥니다.` : " 계획만 저장하면 실행하지 않습니다."}</p> : null}
    <PlanningPreviewProgress projectName={projectName} runId={runId} status={snapshot} context={context} applying={applying} now={clockNow} />
    {snapshot?.phase === "idle" ? <p>{snapshot.can_generate ? "기획 또는 Task 상태가 변경됐습니다. 현재 입력으로 변경안을 작성해 주세요." : "반영할 새 기획 대화가 없거나 현재 단계에서는 후보를 작성할 수 없습니다. 기획 대화에서 변경 내용을 확인하세요."}</p> : null}
    {errors.map((message) => {
      const providerFailure = providerFailurePresentation(message);
      return providerFailure ? <div key={message} className="planning-preview-dialog__error" role="alert">
        <p>{providerFailure.title}. {providerFailure.description}</p>
        <details><summary>오류 상세</summary><pre>{message}</pre></details>
      </div> : <p key={message} className="planning-preview-dialog__error" role="alert">{message}</p>;
    })}
    {groupError ? <button className="button button--secondary" type="button" disabled={applying} onClick={() => void manualCheck()}>상태 다시 확인</button> : null}
    {preview ? <>
      <div className="planning-preview-dialog__context">
        {snapshot?.phase !== "ready" || !snapshot.can_apply ? <small>적용 가능 시점: {previewApplyTiming(snapshot)}</small> : null}
        {snapshot?.work_state === "active" ? <small>저장된 미리보기 있음 · 현재 작업 종료 후 유효성 확인</small> : null}
        <details><summary>변경안 기록</summary><strong>{preview.run_title || "현재 작업 그룹"}</strong>
          <small>{preview.run_id} · 계획 revision {preview.plan_revision} · 대화 revision {preview.conversation_revision}</small>
          <small>생성 {new Date(preview.created_at).toLocaleString()} · 적용 가능 시점: {previewApplyTiming(snapshot)}</small>
          {counts ? <p>전체 비교: 추가 {counts.added} · 수정 {counts.modified} · 제외 {counts.excluded} · 유지 {counts.unchanged} · 재검토 {counts.review}</p> : null}
          <p>선행 Task 영향: {preview.dependency_impact ? "있음" : "없음"} · 검증 명령 영향: {preview.verification_impact ? "있음" : "없음"} · 완료 Task: {preview.completed_task_review ? "재검토 필요" : "자동 재실행 없음"}</p></details>
      </div>
      {preview.status === "applied" && preview.actual ? <>
        <p role="status">실제 반영: 추가 {preview.actual.added} · 수정 {preview.actual.modified} · 제외 {preview.actual.excluded} · 유지 {preview.actual.unchanged}</p>
        {preview.changes.filter((item) => item.kind !== "unchanged").map((item) => <p key={item.task_id}>
          {item.title || item.task_id} · {kindLabels[item.kind]}{item.fields.length ? ` · ${item.fields.map((field) => fieldLabels[field] || field).join(", ")}` : ""}
        </p>)}
        {actualMismatch ? <p className="planning-preview-dialog__error" role="alert">예상 변경 수와 실제 반영 결과가 다릅니다. 작업 탭에서 최종 Task를 다시 확인해 주세요.</p> : null}
        <p className="planning-preview-dialog__next-step"><strong>{retryTaskId ? "복구안 적용 완료" : "다음 단계"}</strong> {retryTaskId
          ? "아래 버튼을 누르면 적용한 계획으로 이 작업만 재실행합니다. 남은 작업은 이후 그룹 재개로 진행하세요." : appliedNextStep(confirmedRun)}</p>
        {retryTaskId ? <button type="button" className="button button--primary" onClick={() => {
          if (current(session.current) && latestSnapshot.current === snapshot && !applyPending.current) onRetry(retryTaskId);
        }}>적용한 복구안으로 재실행</button> : null}
      </> : <>
        {counts ? <p>예상 변경: {[["추가", counts.added], ["수정", counts.modified], ["제외", counts.excluded], ["재검토", counts.review]].filter(([, count]) => Number(count) > 0).map(([label, count]) => `${label} ${count}`).join(" · ") || "없음"}</p> : null}
        {preview.dependency_impact || preview.verification_impact || preview.completed_task_review ? <p>{[preview.dependency_impact ? "선행 Task 영향 있음" : "", preview.verification_impact ? "검증 명령 변경 있음" : "", preview.completed_task_review ? "완료 Task 재검토 필요" : ""].filter(Boolean).join(" · ")}</p> : null}
        {preview.stale ? <p className="planning-preview-dialog__error" role="alert">대화 또는 Task 상태가 변경됐습니다. 미리보기를 다시 생성해 주세요.</p> : null}
        {planDirty ? <p className="planning-preview-dialog__error" role="alert">미저장 Task 편집을 저장하거나 취소한 뒤 반영해 주세요.</p> : null}
        <details><summary>변경 작업·필드 상세</summary><ul className="planning-preview-dialog__changes">{preview.changes.map((item) => <li key={item.task_id} data-kind={item.kind}>
          <strong>{kindLabels[item.kind]} · {item.title}</strong><small>{item.task_id}</small>
          {item.fields.length ? <span>변경 필드: {item.fields.map((field) => fieldLabels[field] || field).join(", ")}</span> : null}
          {item.reason ? <span>{item.reason}</span> : null}
        </li>)}</ul></details>
      </>}
    </> : null}
    {preview?.status !== "applied" ? <footer className="planning-preview-dialog__actions">
      <button className="button button--secondary" type="button" disabled={applying} onClick={close}>돌아가서 수정</button>
      {error && !groupError ? <button className="button button--secondary" type="button" disabled={applying} onClick={() => void manualCheck()}>상태 다시 확인</button> : null}
      {snapshot?.can_generate && ["idle", "failed", "interrupted"].includes(snapshot.phase) ? <button className="button button--secondary" type="button" disabled={busy} onClick={() => void regenerate()}>변경안 다시 작성</button> : null}
      {snapshot?.work_state === "idle" && snapshot.can_apply && snapshot.phase === "ready" && preview?.status === "preview" && preview.run_id === runId && !preview.stale && preview.can_apply ? <button className="button button--primary" type="button" disabled={applying || planDirty} onClick={() => void apply()}>{repairPreview ? "복구안 적용" : embedded ? "계획만 저장" : "이 변경 반영"}</button> : null}
      {continueEligible && snapshot?.work_state === "idle" && snapshot.can_apply && snapshot.phase === "ready"
        && preview?.status === "preview" && preview.run_id === runId && !preview.stale && preview.can_apply
        ? <button className="button button--primary" type="button" disabled={applying || planDirty} onClick={() => void apply(true)}>복구안 적용 후 {continueTaskIndex + 1}번부터 계속</button> : null}

    </footer> : null}
  </Surface>;
}
