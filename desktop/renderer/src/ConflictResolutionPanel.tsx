import { AlertTriangle, GitMerge, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { IntegrationConflictDetail, ProviderProfile, RunState } from "./types";
import {
  attemptStatusLabel, candidateFileCopy, conflictDetailBasis, conflictPhaseLabel, conflictProgressPresentation, conflictRequestTiming,
  conflictResolutionSummary, currentConflictDetail,
  activeConflictPhase,
  type PendingConflictRequest,
} from "./recoveryTaskPresentation";
import { operationsSnapshotMatches, verifiedResult, type OperationsSnapshot } from "./integrationCompletion";

interface ConflictResolutionPanelProps {
  projectName: string;
  run: RunState;
  recoveryTaskId?: string;
  operationsCheckedAt?: string;
  operationsSnapshot?: OperationsSnapshot;
  onVerify?(): void;
  verifyDisabled?: boolean;
  onUpdated(): void;
}

function requestId(): string {
  return crypto.randomUUID();
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function ConflictResolutionPanel({ projectName, run, recoveryTaskId = "", operationsCheckedAt = "", operationsSnapshot,
  onVerify, verifyDisabled = false, onUpdated }: ConflictResolutionPanelProps) {
  const selectedRecoveryTask = run.recovery_tasks?.find((task) => task.id === recoveryTaskId)
    || run.recovery_tasks?.find((task) => task.conflict.id === run.integration_conflict?.id);
  const snapshot = selectedRecoveryTask?.conflict || run.integration_conflict;
  const [detail, setDetail] = useState<IntegrationConflictDetail>();
  const [detailBasis, setDetailBasis] = useState("");
  const [selectedPath, setSelectedPath] = useState(snapshot?.files[0]?.path || "");
  const [profiles, setProfiles] = useState<ProviderProfile[]>([]);
  const [profileKey, setProfileKey] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("");
  const [busy, setBusy] = useState<"prepare" | "apply" | "">("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [error, setError] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [lastCheckedAt, setLastCheckedAt] = useState("");
  const [pendingRequest, setPendingRequest] = useState<PendingConflictRequest>();
  const [clock, setClock] = useState(Date.now());
  const identity = conflictDetailBasis(projectName, run.id, snapshot?.id || "", selectedRecoveryTask?.id || "", "", "");
  const observedAt = operationsSnapshotMatches(operationsSnapshot, projectName, run) ? operationsSnapshot!.checkedAt : operationsCheckedAt;
  const basis = conflictDetailBasis(projectName, run.id, snapshot?.id || "", selectedRecoveryTask?.id || "", run.updated_at, observedAt);
  const activeIdentity = useRef("");
  const activePath = useRef(snapshot?.files[0]?.path || "");
  const loadRequest = useRef(0);
  const profileRequest = useRef(0);
  const terminalRefresh = useRef("");
  const freshDetail = currentConflictDetail(detail, detailBasis, basis);

  const load = async (path = selectedPath, silent = false): Promise<IntegrationConflictDetail | undefined> => {
    if (!snapshot) return undefined;
    const request = ++loadRequest.current;
    if (!silent) {
      setLoadingFile(true);
      setError("");
    }
    try {
      const result = await window.orchestrator.request<IntegrationConflictDetail>("runs.integrationConflict", {
        projectName,
        runId: run.id,
        conflictId: snapshot.id,
        filePath: path,
        recoveryTaskId: selectedRecoveryTask?.id || "",
      });
      if (request === loadRequest.current && path === activePath.current) {
        setDetail(result);
        setDetailBasis(basis);
        setLookupError("");
        setLastCheckedAt(new Date().toISOString());
        return result;
      }
    } catch (requestError) {
      if (request === loadRequest.current && path === activePath.current) {
        setLookupError(message(requestError));
        if (!silent) setError(message(requestError));
      }
    } finally {
      if (request === loadRequest.current && path === activePath.current) setLoadingFile(false);
    }
    return undefined;
  };

  useEffect(() => {
    if (!snapshot) return;
    const identityChanged = activeIdentity.current !== identity;
    activeIdentity.current = identity;
    const path = identityChanged ? snapshot.files[0]?.path || "" : selectedPath;
    if (identityChanged) {
      activePath.current = path;
      setSelectedPath(path);
      setDetail(undefined);
      setDetailBasis("");
      setProfiles([]);
      setProfileKey("");
      setPendingRequest(undefined);
      setBusy("");
      setLookupError("");
      setLastCheckedAt("");
      terminalRefresh.current = "";
      const request = ++profileRequest.current;
      void window.orchestrator.request<ProviderProfile[]>("providers.execution", { projectName, capabilities: ["general"] })
        .then((options) => {
          if (request !== profileRequest.current) return;
          setProfiles(options);
          const preferred = options.find((item) => item.is_default) || options[0];
          if (preferred) setProfileKey(`${preferred.agent_id}\u001f${preferred.model}`);
        })
        .catch((requestError) => { if (request === profileRequest.current) setError(message(requestError)); });
    }
    void load(path).then((result) => refreshIfTerminal(result));
  }, [identity, run.updated_at, observedAt]);

  const latestAttempt = freshDetail?.attempts?.at(-1);
  const trackedAttempt = pendingRequest
    ? freshDetail?.attempts?.find((attempt) => attempt.request_id === pendingRequest.id)
    : latestAttempt;
  const currentStatus = freshDetail?.conflict.resolution_status || snapshot?.resolution_status;
  const historical = Boolean(selectedRecoveryTask?.superseded_by) || Boolean(snapshot && snapshot.id !== run.integration_conflict?.id);
  const activePhase = historical ? undefined : activeConflictPhase(run, operationsSnapshot, projectName);
  const verificationConfirmed = !historical && currentStatus === "applied" && Boolean(freshDetail)
    && operationsSnapshotMatches(operationsSnapshot, projectName, run) && operationsSnapshot?.lock?.run_id === run.id
    && operationsSnapshot.lock.state === "unlocked" && verifiedResult(run);
  const awaitingResult = !verificationConfirmed && Boolean(pendingRequest || latestAttempt?.status === "running"
    || currentStatus === "generating" || currentStatus === "applying");
  const pendingAge = pendingRequest ? clock - Date.parse(pendingRequest.startedAt) : Number.NaN;
  const starting = !historical && !verificationConfirmed && !activePhase && Boolean(pendingRequest) && pendingAge >= 0 && pendingAge < 60000;
  const unconfirmed = !historical && !activePhase && awaitingResult && !starting;
  const pollActive = Boolean(activePhase || starting);
  const requestBlocked = pollActive || unconfirmed;
  const progress = conflictProgressPresentation(trackedAttempt, pendingRequest, clock, lookupError,
    activePhase ? { state: "active", phase: activePhase } : { state: starting ? "pending" : "unconfirmed" });
  const refreshIfTerminal = (result: IntegrationConflictDetail | undefined, request = ""): boolean => {
    if (!result || (!request && !pollActive && !lookupError && !unconfirmed)) return false;
    const trackedId = request || pendingRequest?.id;
    const last = trackedId
      ? result.attempts?.find((attempt) => attempt.request_id === trackedId)
      : result.attempts?.at(-1);
    if (!last || last.status === "running") return false;
    if (pendingRequest?.id === last.request_id) setPendingRequest(undefined);
    if (last.request_id !== terminalRefresh.current) {
      terminalRefresh.current = last.request_id;
      onUpdated();
    }
    return true;
  };
  useEffect(() => {
    if (!pollActive) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [pollActive]);

  useEffect(() => {
    if (!pollActive || !snapshot) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      const result = await load(selectedPath, true);
      if (cancelled) return;
      if (refreshIfTerminal(result)) return;
      timer = window.setTimeout(() => void poll(), result ? 2000 : 5000);
    };
    timer = window.setTimeout(() => void poll(), 2000);
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [identity, basis, selectedPath, pollActive, pendingRequest?.id, lookupError]);

  const selectedProfile = useMemo(() => profiles.find((item) => `${item.agent_id}\u001f${item.model}` === profileKey), [profiles, profileKey]);
  if (!snapshot) return null;
  const current = freshDetail?.conflict || snapshot;
  const unsupported = current.files.filter((item) => !item.supported);
  const candidateCopy = candidateFileCopy(freshDetail?.selected_file);
  const guidance = activePhase ? {
    label: activePhase === "verify" ? current.resolution_status === "applied" ? "해결안 적용됨 · 결과 검사 중" : "결과 검사 중"
      : activePhase === "prepare" ? "AI 해결안 생성 중" : "충돌 해결 처리 중",
    detail: activePhase === "verify" ? "현재 검사 진행과 중지는 위쪽 검사 카드에서 확인하세요."
      : "현재 실행을 확인했습니다. 처리가 끝나면 결과를 갱신합니다.", tone: "active",
  } : verificationConfirmed ? { label: "충돌 해결·검증 완료", detail: "검증을 마쳤습니다. 위쪽 반영 버튼으로 계속 진행하세요.", tone: "success" }
    : unconfirmed ? { label: "현재 실행 여부 확인 필요", detail: "이전 요청의 기록을 보존했습니다. 상태를 다시 확인한 뒤 진행하세요.", tone: "warning" }
      : starting ? { label: "요청 시작 확인 중", detail: "요청한 작업의 현재 상태를 확인하고 있습니다.", tone: "active" }
        : conflictResolutionSummary(current, latestAttempt, historical);
  const canRetryVerification = !historical && current.resolution_status === "applied" && Boolean(freshDetail)
    && operationsSnapshotMatches(operationsSnapshot, projectName, run) && operationsSnapshot?.lock?.run_id === run.id
    && operationsSnapshot.lock.state === "unlocked" && Boolean(run.integration_control?.can_verify)
    && !busy && !loadingFile && !lookupError && !activePhase && !verifyDisabled;
  const hasErrors = Boolean(error || lookupError || current.error || current.abort_error || latestAttempt?.error
    || freshDetail?.selected_file?.candidate_error);

  const prepare = async () => {
    const id = requestId();
    const mutationIdentity = identity;
    setPendingRequest({ id, kind: "prepare", startedAt: new Date().toISOString() });
    setClock(Date.now());
    setBusy("prepare");
    setError("");
    try {
      await window.orchestrator.request<IntegrationConflictDetail>("runs.prepareConflictResolution", {
        projectName,
        runId: run.id,
        conflictId: current.id,
        fingerprint: current.fingerprint,
        requestId: id,
        agentId: selectedProfile?.agent_id || "",
        model: selectedProfile?.model || "",
        reasoningEffort,
      });
      if (activeIdentity.current !== mutationIdentity) return;
      const result = await load(selectedPath, true);
      const attempt = result?.attempts?.find((item) => item.request_id === id);
      if (attempt) setPendingRequest(undefined);
      if (!refreshIfTerminal(result, id)) onUpdated();
    } catch (requestError) {
      if (activeIdentity.current !== mutationIdentity) return;
      const result = await load(selectedPath, true);
      refreshIfTerminal(result, id);
      setError(message(requestError));
    } finally {
      if (activeIdentity.current === mutationIdentity) setBusy("");
    }
  };

  const apply = async () => {
    if (!current.candidate) return;
    const id = requestId();
    const mutationIdentity = identity;
    setPendingRequest({ id, kind: "apply", startedAt: new Date().toISOString() });
    setClock(Date.now());
    setBusy("apply");
    setError("");
    try {
      const result = await window.orchestrator.approve<RunState>("runs.applyConflictResolution", {
        projectName,
        runId: run.id,
        conflictId: current.id,
        candidateId: current.candidate.id,
        candidateRevision: current.candidate.revision,
        fingerprint: current.fingerprint,
        requestId: id,
      });
      if (activeIdentity.current !== mutationIdentity) return;
      if (result) {
        const refreshed = await load(selectedPath, true);
        const attempt = refreshed?.attempts?.find((item) => item.request_id === id);
        if (attempt) setPendingRequest(undefined);
        if (!refreshIfTerminal(refreshed, id)) onUpdated();
      } else setPendingRequest(undefined);
    } catch (requestError) {
      if (activeIdentity.current !== mutationIdentity) return;
      const result = await load(selectedPath, true);
      refreshIfTerminal(result, id);
      setError(message(requestError));
    } finally {
      if (activeIdentity.current === mutationIdentity) setBusy("");
    }
  };

  const showRequestProgress = Boolean((pollActive && activePhase !== "verify") || unconfirmed || lookupError);
  return <section className="operation-section conflict-resolution" aria-labelledby="conflict-resolution-title">
    <div className="operation-section__heading"><h3 id="conflict-resolution-title"><AlertTriangle aria-hidden="true" size={18} /> Main 충돌 해결 · {current.files.length}개 파일</h3></div>
    {!showRequestProgress ? <div className="conflict-resolution__summary" data-tone={guidance.tone}>
      <strong>{!freshDetail && loadingFile ? "현재 상태 확인 중" : guidance.label}</strong>
      <p>{!freshDetail && loadingFile ? "현재 상태를 확인한 뒤 해결 방법을 안내합니다." : guidance.detail}</p>
    </div> : null}
    {showRequestProgress ? <div className="conflict-operation-progress" data-delay={progress.delay}>
      {pollActive ? <RefreshCw aria-hidden="true" className="spin" size={16} /> : null}
      <div>
        <strong role="status">{progress.label}</strong>
        {progress.delay !== "normal" || lookupError ? <span>{lookupError ? "최신 상태를 확인하지 못했습니다. 상태를 다시 확인한 뒤 진행하세요."
          : trackedAttempt?.status === "failed" ? "처리에 실패했습니다. 오류 상세를 확인해 주세요." : progress.detail}</span> : null}
        {!unconfirmed ? <span>{starting ? "요청 후 " : "요청 기록 · "}{conflictRequestTiming(trackedAttempt, pendingRequest, clock)}</span> : null}
      </div>
      {lookupError || unconfirmed ? <button className="button button--secondary" type="button" disabled={loadingFile}
        onClick={() => { void load(selectedPath).then((result) => refreshIfTerminal(result)); onUpdated(); }}>상태 다시 확인</button> : null}
    </div> : null}
    {hasErrors && !lookupError && !activePhase && !verificationConfirmed ? <p role="alert">처리 중 오류가 발생했습니다. 아래 ‘오류·실행 기록’에서 원인을 확인하세요.</p> : null}
    {unsupported.length ? <p role="alert">직접 확인이 필요한 파일 {unsupported.length}개가 있습니다. 파일별 비교를 확인하세요.</p> : null}
    {!profiles.length && !error ? <p className="provider-selection-warning" role="alert">사용 가능한 충돌 해결 모델이 없습니다. AI 제공자 연결 상태를 확인해 주세요.</p> : null}
    {!verificationConfirmed ? <div className="conflict-resolution__controls">
      <button className="button button--secondary" type="button" title={lookupError || unconfirmed ? "상태를 다시 확인한 뒤 요청할 수 있습니다." : pollActive ? "현재 요청의 결과를 확인하는 중입니다." : freshDetail?.prepare_block_reason || undefined} disabled={historical || Boolean(busy) || requestBlocked || Boolean(lookupError) || loadingFile || !freshDetail?.can_prepare || !selectedProfile} onClick={() => void prepare()}>{busy === "prepare" && pollActive ? <RefreshCw aria-hidden="true" className="spin" size={16} /> : <GitMerge aria-hidden="true" size={16} />}{busy === "prepare" && pollActive ? "격리 후보 생성 중…" : current.candidate ? "해결안 다시 만들기" : "AI로 해결안 만들기"}</button>
      {current.resolution_status === "applied" && onVerify ? <button className="button button--primary" type="button"
        disabled={!canRetryVerification} onClick={onVerify}><RefreshCw aria-hidden="true" size={16} />결과 다시 검사</button>
        : <button className="button button--primary" type="button" title={lookupError || unconfirmed ? "상태를 다시 확인한 뒤 요청할 수 있습니다." : pollActive ? "현재 요청의 결과를 확인하는 중입니다." : freshDetail?.apply_block_reason || undefined} disabled={historical || Boolean(busy) || requestBlocked || Boolean(lookupError) || loadingFile || !freshDetail?.can_apply || freshDetail?.selected_file?.path !== selectedPath} onClick={() => void apply()}>{busy === "apply" && pollActive ? <RefreshCw aria-hidden="true" className="spin" size={16} /> : <ShieldCheck aria-hidden="true" size={16} />}{busy === "apply" && pollActive ? "적용·전체 검증 중…" : "해결안 적용 후 재검증"}</button>}
    </div> : null}
    {current.candidate?.summary ? <details className="conflict-resolution__details"><summary>AI 해결 설명</summary><p className="work-ai-proposal">{current.candidate.summary}</p></details> : null}
    <details className="conflict-resolution__details"><summary>파일별 코드 비교 · {current.files.length}개</summary>
    <div className="conflict-file-list" role="list" aria-label="충돌 파일">{current.files.map((file) => <button key={file.path} type="button" className={file.path === selectedPath ? "is-selected" : ""} onClick={() => { activePath.current = file.path; setSelectedPath(file.path); void load(file.path).then((result) => refreshIfTerminal(result)); }}><span>{file.path}</span><small>{file.kind} · {file.supported ? "AI 해결 지원" : file.binary ? "바이너리" : "수동 결정 필요"}</small></button>)}</div>
    {freshDetail?.selected_file?.path === selectedPath ? <div className="conflict-compare" aria-label={`${selectedPath} 비교`}><article><strong>작업 결과</strong><pre>{freshDetail.selected_file.work || "(파일 없음)"}</pre></article><article><strong>Main 변경</strong><pre>{freshDetail.selected_file.main || "(파일 없음)"}</pre></article><article><strong>해결안</strong><pre>{candidateCopy}</pre>{freshDetail.selected_file.candidate_error ? <small>{freshDetail.selected_file.candidate_error}</small> : null}</article></div> : loadingFile || (!freshDetail && !error) ? <p role="status">선택한 파일을 읽는 중…</p> : !freshDetail ? <p role="alert">최신 비교 자료를 확인하지 못했습니다. 상태를 다시 확인해 주세요.</p> : null}
    </details>
    <details className="conflict-resolution__details"><summary>{hasErrors ? "오류·실행 기록" : "실행 기록·기술 정보"}</summary>
    <dl className="detail-list"><div><dt>작업 commit</dt><dd className="mono">{current.work_head.slice(0, 12)}</dd></div><div><dt>Main commit</dt><dd className="mono">{current.main_head.slice(0, 12)}</dd></div><div><dt>merge 취소</dt><dd>{current.abort_status === "verified" ? "원래 상태 복원 확인" : current.abort_status}</dd></div></dl>
    {(pendingRequest || trackedAttempt) ? <p>요청 {pendingRequest?.id || trackedAttempt?.request_id} · {conflictRequestTiming(trackedAttempt, pendingRequest, clock)}</p> : null}
    {lastCheckedAt ? <p>마지막 확인 {new Date(lastCheckedAt).toLocaleString("ko-KR")}</p> : null}
    {progress.activity ? <p>{progress.activity.label}{progress.activity.detail ? ` · ${progress.activity.detail}` : ""}</p> : null}
    {progress.activity?.lastEventAt ? <p>마지막 SDK 이벤트 {new Date(progress.activity.lastEventAt).toLocaleString("ko-KR")} · 마지막 활동 변화 {progress.activity.lastActivityAt ? new Date(progress.activity.lastActivityAt).toLocaleString("ko-KR") : "정보 미수신"}</p> : null}
    {current.abort_error ? <p role="alert">작업공간 복구 확인 실패: {current.abort_error}</p> : null}
    {current.error ? <p role="alert">{current.error}</p> : null}
    {freshDetail?.selected_file?.candidate_error ? <p role="alert">해결안 파일 확인 실패: {freshDetail.selected_file.candidate_error}</p> : null}
    {lookupError ? <p role="alert">진행 상태 조회 실패: {lookupError} · 현재 상태를 확인하기 전에는 새 요청을 보내지 않습니다.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {freshDetail?.attempts?.length ? <div className="conflict-attempts"><h4>복구 시도와 로그</h4>{freshDetail.attempts.map((attempt, index) => <details key={attempt.request_id} open={index === freshDetail.attempts!.length - 1 && attempt.status === "failed"}><summary>{index + 1}. {attempt.action === "conflict_resolution_apply" ? "적용·검증" : "해결안 생성"} · {attemptStatusLabel(attempt.status)} · {conflictPhaseLabel(attempt.phase)}</summary><dl className="detail-list"><div><dt>요청 ID</dt><dd className="mono">{attempt.request_id}</dd></div><div><dt>갱신 시각</dt><dd>{attempt.updated_at || attempt.created_at || "기록 없음"}</dd></div>{attempt.progress_observation?.attempt_id === attempt.request_id ? <div><dt>마지막 SDK 이벤트</dt><dd>{attempt.progress_observation.last_event_received_at || "기록 없음"}</dd></div> : null}{attempt.progress_observation?.attempt_id === attempt.request_id ? <div><dt>마지막 활동 변화</dt><dd>{attempt.progress_observation.last_activity_changed_at || "기록 없음"}</dd></div> : null}{attempt.result_commit ? <div><dt>결과 commit</dt><dd className="mono">{attempt.result_commit}</dd></div> : null}</dl>{attempt.error ? <p role="alert">{attempt.error}</p> : null}{attempt.log ? <pre className="conflict-attempt-log">{attempt.log}</pre> : <p>저장된 AI 제공자 로그가 없습니다.</p>}</details>)}</div> : null}
    </details>
    <details className="conflict-resolution__details"><summary>AI 설정</summary>
    <div className="conflict-resolution__controls">
      <label><span>해결 모델</span><select value={profileKey} disabled={Boolean(busy) || requestBlocked} onChange={(event) => { setProfileKey(event.target.value); setReasoningEffort(""); }}>{profiles.map((profile) => <option key={`${profile.agent_id}\u001f${profile.model}`} value={`${profile.agent_id}\u001f${profile.model}`}>{profile.model || "자동 선택"} · {profile.provider_id}</option>)}</select></label>
      <label><span>추론 강도</span><select value={reasoningEffort} disabled={Boolean(busy) || requestBlocked} onChange={(event) => setReasoningEffort(event.target.value)}><option value="">자동 선택</option>{(selectedProfile?.reasoning_efforts || []).map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></label>
    </div>
    </details>
  </section>;
}
