import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle } from "lucide-react";

import {
  recoveryDelayState,
  recoveryElapsedSeconds,
  recoveryPhaseLabel,
  recoveryPlanFromOperation,
  recoveryResumeInput,
  type RecoveryOperation,
  type RecoveryOperationKind,
  type RecoveryPlan,
} from "./recoveryOperation";
import { describeRecoveryError, type RecoveryError } from "./recoveryLock";
import type { RunState } from "./types";
import { providerFailurePresentation } from "./providerFailure";

function newRequestId(): string {
  return crypto.randomUUID();
}

function optimisticOperation(runId: string, action: RecoveryOperationKind, phase: string, requestId: string): RecoveryOperation {
  const now = new Date().toISOString();
  return {
    request_id: requestId,
    run_id: runId,
    action,
    digest: "",
    phase,
    status: "running",
    error: "",
    error_code: "",
    finished_at: "",
    result_revision: 0,
    result_commit: "",
    result_ref: "",
    resume_request_id: "",
    lock_state: "unknown",
    created_at: now,
    updated_at: now,
    result: null,
  };
}

function operationDescription(operation: RecoveryOperation): string {
  if (operation.status === "partial") {
    return `완료 결과는 ${operation.result_commit.slice(0, 12)} commit까지 통합됐습니다. 같은 commit에서 남은 작업 재계획만 다시 시도할 수 있습니다.`;
  }
  if (operation.action === "recovery_preview") {
    return operation.phase === "collecting_sources"
      ? "현재 그룹의 실패와 같은 프로젝트에서 가져올 수 있는 완료 결과를 확인하고 있습니다."
      : "현재 그룹의 실패 원인과 작업공간 기준을 확인하고 있습니다. 아직 복구를 적용하지 않았습니다.";
  }
  if (operation.phase === "integrating_commits") return "승인한 완료 결과를 현재 그룹의 공유 작업공간에 통합하고 있습니다.";
  if (operation.phase === "replanning") return "통합 결과를 보존한 채 실패한 작업과 남은 의존 작업을 다시 계획하고 있습니다.";
  return "선택한 복구안과 현재 그룹 상태가 승인 시점과 같은지 확인하고 있습니다.";
}

export function RecoveryDialog({ projectName, runId, runTitle, onApplied, onClose }: {
  projectName: string; runId: string; runTitle: string; onApplied(run: RunState): void; onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const requestVersion = useRef(0);
  const completedApplyRequest = useRef("");
  const [plan, setPlan] = useState<RecoveryPlan>();
  const [selected, setSelected] = useState<string[]>([]);
  const [operation, setOperation] = useState<RecoveryOperation>();
  const [operationConfirmed, setOperationConfirmed] = useState(false);
  const [recoveryError, setRecoveryError] = useState<RecoveryError>();
  const [pollError, setPollError] = useState("");
  const [checkingOperation, setCheckingOperation] = useState(true);
  const [clearingLock, setClearingLock] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const [historyUnconfirmed, setHistoryUnconfirmed] = useState(false);
  const operationRunning = operation?.status === "running";
  const previewing = operationRunning && operation.action === "recovery_preview";
  const applying = operationRunning && operation.action === "recovery_apply";
  const confirmingAppliedRun = operation?.action === "recovery_apply" && operation.status === "succeeded";
  const partial = operation?.status === "partial";
  const elapsed = operation ? recoveryElapsedSeconds(operation.created_at, clock) : 0;
  const delayState = operation ? recoveryDelayState(operation, clock) : "normal";
  const resumeInput = operation ? recoveryResumeInput(operation) : undefined;
  const selectedSources = plan?.sources.filter((source) => selected.includes(source.run_id)) || [];
  const selectedCommitCount = new Set(selectedSources.flatMap((source) => source.commits)).size;
  const requestActive = Boolean(operationRunning || clearingLock || confirmingAppliedRun || historyUnconfirmed || checkingOperation);
  const canClose = !clearingLock && (!applying || delayState === "unconfirmed");

  useEffect(() => {
    if (!operationRunning && !clearingLock) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [clearingLock, operationRunning]);

  async function acceptOperation(next: RecoveryOperation) {
    const version = requestVersion.current;
    setOperation(next);
    setOperationConfirmed(true);
    setPollError("");
    if (next.status === "succeeded") setRecoveryError(undefined);
    const restoredPlan = recoveryPlanFromOperation(next);
    if (restoredPlan) {
      setPlan(restoredPlan);
      setSelected([]);
      setRecoveryError(undefined);
      return;
    }
    if (next.status === "interrupted" && next.lock_state === "stale") {
      if (next.action === "recovery_apply") {
        setPlan(undefined);
        setSelected([]);
      }
      setRecoveryError({
        message: "복구 요청을 실행한 프로세스가 종료됐고 잠금이 남아 있습니다. 잠금을 해제한 뒤 복구안을 다시 조회해 주세요.",
        details: next.error,
        canClearLock: true,
      });
      return;
    }
    if (next.status === "failed" || next.status === "interrupted") {
      if (next.action === "recovery_apply") {
        setPlan(undefined);
        setSelected([]);
      }
      const providerFailure = next.status === "failed" ? providerFailurePresentation(next.error) : undefined;
      const failure = providerFailure
        ? { message: `${providerFailure.title}. ${providerFailure.kind === "capacity" ? "잠시 후 복구안을 다시 조회해 주세요." : providerFailure.description}`, details: next.error, canClearLock: false }
        : await describeRecoveryError(new Error(next.error || recoveryPhaseLabel(next)), window.orchestrator, projectName, runId);
      if (requestVersion.current === version) setRecoveryError(failure);
      return;
    }
    if (next.status === "partial") {
      const providerFailure = providerFailurePresentation(next.error);
      setRecoveryError({
        message: providerFailure
          ? `${providerFailure.title}. 통합 결과는 보존됐습니다. ${providerFailure.kind === "usage" ? providerFailure.description : "잠시 후 아래에서 작업 재계획만 다시 시도하세요."}`
          : next.error || "완료 결과 통합 뒤 작업 재계획에 실패했습니다.",
        details: providerFailure ? next.error : "",
        canClearLock: false,
      });
      return;
    }
  }

  useEffect(() => {
    if (!confirmingAppliedRun || !operation || completedApplyRequest.current === operation.request_id) return;
    let cancelled = false;
    let timer: number | undefined;
    const confirm = async () => {
      let updated: RunState;
      try {
        updated = await window.orchestrator.request<RunState>("runs.get", { projectName, runId });
      } catch (cause) {
        if (!cancelled) {
          setPollError(`복구는 완료됐지만 그룹 상태 조회에 실패했습니다. 다시 확인합니다: ${String(cause)}`);
          timer = window.setTimeout(() => void confirm(), 5_000);
        }
        return;
      }
      if (cancelled) return;
      completedApplyRequest.current = operation.request_id;
      onApplied(updated);
      onClose();
    };
    void confirm();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [operation?.request_id, operation?.status, projectName, runId]);

  useEffect(() => {
    if (!operationRunning || !operation) return;
    let cancelled = false;
    let failures = 0;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await window.orchestrator.request<RecoveryOperation>("operations.get", {
          projectName,
          runId,
          requestId: operation.request_id,
        });
        failures = 0;
        if (!cancelled) await acceptOperation(next);
      } catch (cause) {
        failures += 1;
        if (!cancelled) setPollError(`요청 상태 조회 실패: ${String(cause)}`);
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), failures > 1 ? 10_000 : failures ? 5_000 : 2_000);
      }
    };
    timer = window.setTimeout(() => void poll(), 2_000);
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [operation?.request_id, operationRunning, projectName, runId]);

  async function loadLatestOperations() {
    const version = ++requestVersion.current;
    setCheckingOperation(true);
    try {
      const records = await Promise.all([
        window.orchestrator.request<RecoveryOperation | null>("operations.latest", { projectName, runId, kind: "recovery_preview" }),
        window.orchestrator.request<RecoveryOperation | null>("operations.latest", { projectName, runId, kind: "recovery_apply" }),
      ]);
      if (requestVersion.current !== version) return;
      setHistoryUnconfirmed(false);
      setRecoveryError(undefined);
      const latest = records.filter((item): item is RecoveryOperation => Boolean(item))
        .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0];
      if (latest) await acceptOperation(latest);
      else { setCheckingOperation(false); await preview(); }
    } catch (cause) {
      if (requestVersion.current === version) {
        setHistoryUnconfirmed(true);
        setRecoveryError({ message: "이전 복구 요청 상태를 확인하지 못했습니다. 상태를 다시 확인해 주세요.", details: String(cause), canClearLock: false });
      }
    } finally {
      if (requestVersion.current === version) setCheckingOperation(false);
    }
  }

  useEffect(() => {
    dialog.current?.showModal();
    void loadLatestOperations();
    return () => { requestVersion.current += 1; };
  }, []);

  async function refreshOperationAfterError(cause: unknown, requestId: string) {
    const version = requestVersion.current;
    try {
      const tracked = await window.orchestrator.request<RecoveryOperation>("operations.get", { projectName, runId, requestId });
      if (requestVersion.current === version && tracked.request_id === requestId) await acceptOperation(tracked);
    } catch (queryError) {
      if (requestVersion.current === version) {
        setPollError("요청 오류 뒤 최종 상태를 확인하지 못했습니다. 같은 요청을 다시 보내지 말고 상태를 확인해 주세요.");
        setRecoveryError({ message: "복구 결과 확인 중입니다. 오류만으로 실패나 종료를 확정할 수 없습니다.",
          details: `${String(cause)}\n상태 조회 오류: ${String(queryError)}`, canClearLock: false });
      }
    }
  }

  async function checkOperationNow() {
    if (!operation || checkingOperation) return;
    const requestId = operation.request_id;
    const version = requestVersion.current;
    setCheckingOperation(true);
    try {
      const tracked = await window.orchestrator.request<RecoveryOperation>("operations.get", { projectName, runId, requestId });
      if (requestVersion.current === version && tracked.request_id === requestId) await acceptOperation(tracked);
    } catch (cause) {
      if (requestVersion.current === version) setPollError(`복구 상태를 확인하지 못했습니다: ${String(cause)}`);
    } finally {
      if (requestVersion.current === version) setCheckingOperation(false);
    }
  }

  async function preview() {
    const version = ++requestVersion.current;
    const requestId = newRequestId();
    setOperation(optimisticOperation(runId, "recovery_preview", "requesting", requestId));
    setOperationConfirmed(false);
    setRecoveryError(undefined);
    setPollError("");
    setPlan(undefined);
    setSelected([]);
    setClock(Date.now());
    try {
      const result = await window.orchestrator.request<RecoveryPlan>("runs.recoveryPlan", { projectName, runId, requestId });
      if (requestVersion.current !== version) return;
      setPlan(result);
      const tracked = await window.orchestrator.request<RecoveryOperation>("operations.get", { projectName, runId, requestId });
      if (requestVersion.current === version) await acceptOperation(tracked);
    } catch (cause) {
      if (requestVersion.current === version) await refreshOperationAfterError(cause, requestId);
    }
  }

  async function clearLock() {
    setClearingLock(true);
    let cleared = false;
    try {
      cleared = Boolean(await window.orchestrator.approve("locks.clear", { projectName, runId }));
    } catch (cause) {
      setRecoveryError(await describeRecoveryError(cause, window.orchestrator, projectName, runId));
    } finally {
      setClearingLock(false);
    }
    if (cleared) await preview();
  }

  async function apply(resume?: { fingerprint: string; sourceIds: string[] }) {
    if (!plan && !resume) return;
    const version = ++requestVersion.current;
    const requestId = newRequestId();
    const fingerprint = resume?.fingerprint || plan?.fingerprint || "";
    const sourceIds = resume?.sourceIds || selected;
    const previousRequestId = resume ? operation?.request_id || "" : "";
    setOperation(optimisticOperation(runId, "recovery_apply", "awaiting_approval", requestId));
    setOperationConfirmed(false);
    setRecoveryError(undefined);
    setPollError("");
    setClock(Date.now());
    try {
      const result = await window.orchestrator.approve<RunState>("runs.applyRecovery", {
        projectName,
        runId,
        fingerprint,
        sourceIds,
        requestId,
        ...(previousRequestId ? { resumeRequestId: previousRequestId } : {}),
      });
      if (requestVersion.current !== version) return;
      if (!result) {
        setOperation(undefined);
        return;
      }
      completedApplyRequest.current = requestId;
      onApplied(result);
      onClose();
    } catch (cause) {
      if (requestVersion.current === version) await refreshOperationAfterError(cause, requestId);
    }
  }

  const operationStatus = useMemo(() => operation ? recoveryPhaseLabel(operation) : "", [operation]);
  return <dialog ref={dialog} className="modal recovery-dialog" aria-labelledby="recovery-title" onCancel={(event) => { event.preventDefault(); if (canClose) onClose(); }}>
    <div className="project-form">
      <header className="recovery-heading">
        <h2 id="recovery-title">작업 그룹 복구</h2>
        <p>{projectName} · {runTitle || runId}</p>
      </header>
      <ol className="recovery-steps" aria-label="복구 순서">
        <li aria-current={previewing || (!plan && !applying && !partial) ? "step" : undefined}>1. 복구안 조회</li>
        <li aria-current={plan && !applying && !partial ? "step" : undefined}>2. 내용 검토</li>
        <li aria-current={applying || partial ? "step" : undefined}>3. 확인 후 적용</li>
      </ol>
      <div className="recovery-content">
      {historyUnconfirmed || checkingOperation && !operation ? <section className="recovery-progress">
        <strong role="status">{historyUnconfirmed ? "이전 복구 결과 확인 필요" : "이전 복구 상태 확인 중"}</strong>
        <p>기존 요청의 실행·종료 상태를 확인한 뒤 새 요청을 보낼 수 있습니다.</p>
        <button className="button button--secondary" disabled={checkingOperation} onClick={() => void loadLatestOperations()}>{checkingOperation ? "확인 중" : "이전 복구 상태 다시 확인"}</button>
      </section> : null}
      {operationRunning || partial ? <section className="recovery-progress" data-delayed={delayState !== "normal" || partial}>
        <div className="recovery-progress__title">
          {delayState !== "normal" || partial ? <AlertCircle size={18} aria-hidden="true" /> : <LoaderCircle className="spin" size={18} aria-hidden="true" />}
          <strong role="status">{operationStatus}</strong>
          <time>요청 후 {elapsed}초</time>
        </div>
        <p>{operation ? operationDescription(operation) : "복구 요청을 확인하고 있습니다."}</p>
        <p>{operationConfirmed ? `최근 단계 갱신 ${recoveryElapsedSeconds(operation?.updated_at || "", clock)}초 전` : "아직 실행 엔진의 처리 상태를 받지 못했습니다."}</p>
        {delayState === "delayed" ? <p className="recovery-progress__help">응답이 늦어지고 있습니다. 상태 조회를 계속하며, 경과 시간만으로 작업 중단을 판단하지 않습니다.</p> : null}
        {delayState === "unconfirmed" ? <p className="recovery-progress__help">60초 동안 최종 결과를 확인하지 못했습니다. 상태 조회는 계속됩니다. 같은 요청을 다시 보내지 말고 이 창을 닫은 뒤 나중에 확인할 수 있습니다.</p> : null}
        {delayState === "unconfirmed" ? <button className="button button--secondary" disabled={checkingOperation} onClick={() => void checkOperationNow()}>{checkingOperation ? "확인 중" : "복구 상태 다시 확인"}</button> : null}
        {pollError ? <p className="recovery-progress__help" role="alert">{pollError}</p> : null}
      </section> : null}
      {confirmingAppliedRun ? <section className="recovery-progress">
        <div className="recovery-progress__title"><CheckCircle2 size={18} aria-hidden="true" /><strong role="status">복구 적용 완료 · 그룹 상태 확인 중</strong></div>
        <p>복구 결과를 그룹 화면에 반영한 뒤 닫습니다. 이후 작업을 확인하고 ‘그룹 재개’를 눌러 주세요.</p>
        {pollError ? <p className="recovery-progress__help" role="alert">{pollError}</p> : null}
      </section> : null}
      {clearingLock ? <section className="recovery-progress"><div className="recovery-progress__title"><LoaderCircle className="spin" size={18} aria-hidden="true" /><strong role="status">잠금 해제 결과 확인 중</strong></div></section> : null}
      {recoveryError ? <div className="recovery-error">
        <strong>{historyUnconfirmed || operationRunning ? "복구 결과 확인 필요" : partial ? "결과 통합 완료 · 재계획 확인 필요" : "복구 요청을 완료하지 못했습니다"}</strong>
        <p role="alert">{recoveryError.message}</p>
        {recoveryError.canClearLock ? <button className="button button--primary" disabled={requestActive} onClick={() => void clearLock()}>잠금 해제 후 다시 조회</button> : null}
        {recoveryError.details ? <details><summary>오류 상세</summary><pre>{recoveryError.details}</pre></details> : null}
      </div> : null}
      {plan ? <>
        {!requestActive && !partial ? <p className="recovery-ready" role="status"><CheckCircle2 size={16} aria-hidden="true" />복구안 준비됨 · 후보 {plan.sources.length}개 · 적용 전 확인이 필요합니다.</p> : null}
        <section className="recovery-section">
          <h3>실패한 작업부터 확인하세요</h3>
          <details><summary>작업 그룹 오류·기준 정보</summary><p>{plan.failure}</p><p>그룹 ID: {plan.run_id}<br />작업공간: {plan.worktree}<br />기준 commit: {plan.baseline}</p></details>
          {plan.failed_tasks.map((task) => <details key={task.id}>
            <summary>{task.title}</summary>
            <p className="recovery-error-copy">{task.error}</p>
            <strong>에이전트 응답 · 원문</strong>
            <pre tabIndex={0}>{task.response || "기록된 에이전트 응답이 없습니다. 작업 로그를 확인해 주세요."}</pre>
          </details>)}
        </section>
        <section className="recovery-section">
          <h3>가져올 다른 그룹의 완료 결과</h3>
          <p>필요한 선행 결과가 있을 때만 선택하세요. 해당 commit의 이전 변경 이력도 함께 포함됩니다.</p>
          {!plan.sources.length ? <p className="recovery-empty">가져올 완료 결과 후보가 없습니다. 현재 그룹의 실패 원인을 바탕으로 작업만 다시 계획할 수 있습니다.</p> : null}
        {plan.sources.map((source) => <fieldset key={source.run_id} disabled={requestActive || partial}>
          <label><input type="checkbox" checked={selected.includes(source.run_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, source.run_id] : current.filter((id) => id !== source.run_id))} /> {source.summary || source.run_id}</label>
          <p>완료 결과 {source.completed_tasks.length}개</p>
          <details><summary>통합할 commit · 미완료 작업 확인</summary><small>{source.run_id}</small><p>완료 결과 · {source.completed_tasks.join(", ")}</p><pre>{source.commits.join("\n")}</pre>{source.pending_tasks.map((task, index) => <p key={index}>{task.title}<br />허용 경로: {task.expected_paths.join(", ")}</p>)}</details>
        </fieldset>)}
        </section>
        <section className="recovery-selection" aria-label="적용할 변경 요약">
          <strong>{selected.length ? `${selected.length}개 그룹의 완료 결과를 가져옵니다` : "현재 그룹의 작업만 다시 계획합니다"}</strong>
          <p>{selected.length ? `선택한 commit ${selectedCommitCount}개와 그 이전 변경 이력을 통합하고, 미완료 선행 작업을 참고해 현재 그룹을 재계획합니다.` : "다른 그룹의 결과는 가져오지 않습니다. 실패 원인을 바탕으로 현재 그룹을 재계획합니다."}</p>
          <p>적용 후 작업 내용을 확인하고 ‘그룹 재개’를 눌러 실행합니다. 새 작업 그룹을 만들지 않습니다.</p>
        </section>
      </> : null}
      </div>
      <footer>
        <button className="button button--quiet" disabled={!canClose} onClick={onClose}>{applying && delayState === "unconfirmed" ? "닫고 나중에 확인" : "닫기"}</button>
        <button className="button button--secondary" disabled={requestActive} onClick={() => void preview()}>복구안 다시 조회</button>
        <button className="button button--primary" disabled={requestActive || (!plan && !resumeInput)} onClick={() => void apply(resumeInput)}>{partial ? resumeInput ? "작업 재계획 다시 시도" : "재계획 재시도 정보 없음" : !plan ? "복구안 확인 필요" : selected.length ? "선택 결과 통합·재계획" : "현재 그룹 재계획"}</button>
      </footer>
    </div>
  </dialog>;
}
