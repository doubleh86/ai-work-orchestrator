import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AlertCircle, ArrowUpRight, Check, CheckCircle2, ChevronRight, Files, ListChecks, MessageSquare, RefreshCw } from "lucide-react";

import {
  currentGroupResult, currentTaskResult, resultChangedPaths, resultFileLabel,
  resultOutcome, resultRevisionContext, resultStatus, resultVerification,
} from "./resultReviewPresentation";
import type { ResultFileChange, ResultRevisionLinks, ResultRevisionProposal, ResultRevisionRequest, RunState, WorkTask } from "./types";
import { ResultRevisionRequests, resultRevisionRequestKey } from "./resultRevisionRequests";

export interface ResultRevisionDraft {
  requestId: string;
  text: string;
  proposalId: string;
  reply?: string;
}

interface ResultReviewProps {
  projectName: string;
  run: RunState;
  focusTaskId: string;
  draft?: ResultRevisionDraft;
  requests: ResultRevisionRequests;
  onDraftChange(update: ResultRevisionDraft | ((current: ResultRevisionDraft | undefined) => ResultRevisionDraft | undefined)): void;
  onNavigate(runId: string, view: "results" | "planning", message?: string): void;
  onOpenTask(taskId: string): void;
  onOpenOperations(): void;
  onDiscuss?(): void;
  discussionText?: string;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function FinalFiles({ state, files, error, expanded = false }: { state: string; files: ResultFileChange[]; error?: string; expanded?: boolean }) {
  if (state === "none") return <p>파일 변경 없음</p>;
  if (state !== "confirmed") return <p>최종 변경 파일 확인 불가{error ? ` · ${error}` : ""}</p>;
  return <>
    <p>파일 {files.length}개 변경</p>
    {expanded ? <ul>{files.map((file) => <li key={`${file.change}-${file.path}`}><code>{resultFileLabel(file)}</code></li>)}</ul>
      : <details><summary>변경 파일 보기</summary><ul>{files.map((file) => <li key={`${file.change}-${file.path}`}><code>{resultFileLabel(file)}</code></li>)}</ul></details>}
  </>;
}

function PriorTaskResults({ task }: { task: WorkTask }) {
  const current = currentTaskResult(task);
  const prior = current ? task.result_history.slice(0, -1) : task.result_history;
  if (!prior.length) return null;
  return <details className="result-review__history"><summary>이전 완료 기록 · {prior.length}건</summary>
    {prior.map((record, index) => <div key={`${record.result_commit}-${index}`}>
      <p>완료 {new Date(record.captured_at).toLocaleString()} · commit <code>{record.result_commit}</code></p>
      <FinalFiles state={record.files_state} files={record.files} error={record.error} />
    </div>)}
  </details>;
}

function TaskResultCard({ task, onOpenTask }: { task: WorkTask; onOpenTask(taskId: string): void }) {
  const result = currentTaskResult(task);
  const taskStatus = ["completed", "merged"].includes(task.status) ? "완료" : task.status === "failed" ? "실패" : "미완료";
  return <article className="result-review__task">
    <h4>{task.title} <small>· {taskStatus}</small></h4>
    {result ? <>
      {!result.self_report ? <p className="muted-copy">AI 요약 없음</p> : null}
      <FinalFiles state={result.files_state} files={result.files} error={result.error} />
      <p className="muted-copy">검증: {result.verification_status === "passed" ? "Task 검증 통과" : "미검증"}
        </p><details><summary>완료 기록 보기</summary>{result.self_report ? <p>AI 자체 보고 · {result.self_report}</p> : null}<p>작업 ID · {task.id} · 결과 commit: <code>{result.result_commit}</code> · 완료: {new Date(result.captured_at).toLocaleString()}</p></details>
    </> : <p>최종 변경 파일 확인 불가 · 완료 결과 기록 없음</p>}
    <PriorTaskResults task={task} />
    <button className="button button--quiet" type="button" onClick={() => onOpenTask(task.id)}>Task 상세·로그</button>
  </article>;
}

export function ResultReview({ projectName, run, focusTaskId, draft, requests, onDraftChange, onNavigate, onOpenTask, onOpenOperations, onDiscuss, discussionText }: ResultReviewProps) {
  const [linkedResult, setLinkedResult] = useState<{ key: string; value: ResultRevisionLinks }>();
  const [loading, setLoading] = useState(true);
  const [queryError, setQueryError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const task = run.tasks.find((item) => item.id === focusTaskId);
  const tasks = task ? [task] : run.tasks;
  const attemptedPaths = resultChangedPaths(tasks);
  const taskResult = task ? currentTaskResult(task) : undefined;
  const groupResult = task ? undefined : currentGroupResult(run);
  const status = resultStatus(run, task);
  const verification = resultVerification(run, task);
  const outcome = resultOutcome(run, task);
  const completedTasks = run.tasks.filter((item) => ["completed", "merged"].includes(item.status));
  const finalResult = taskResult || groupResult;
  const fileSummary = finalResult?.files_state === "confirmed" ? `${finalResult.files.length}개`
    : finalResult?.files_state === "none" ? "변경 없음" : "확인 불가";
  const currentDraft = draft || { requestId: "", text: "", proposalId: "", reply: "" };
  const focusId = task?.id || "";
  const scopeKey = resultRevisionRequestKey(projectName, run.id, focusId);
  const requestState = useSyncExternalStore(requests.subscribe, () => requests.read(scopeKey));
  const generating = requestState.pending?.action === "generate";
  const submitting = requestState.pending?.action === "save";
  const links = linkedResult?.key === scopeKey ? linkedResult.value : undefined;
  const proposals = [...(links?.proposals || [])];
  if (requestState.proposal && !proposals.some((item) => item.proposal_id === requestState.proposal?.proposal_id)) proposals.push(requestState.proposal);
  const relevantProposals = proposals.reverse().filter((item) => item.text === currentDraft.text.trim() && item.focus_task_id === focusId);
  const currentProposal = currentDraft.proposalId ? relevantProposals.find((item) => item.proposal_id === currentDraft.proposalId) : relevantProposals[0];
  const matchingProposal = currentProposal && !currentProposal.stale && ["ready", "needs_clarification"].includes(currentProposal.status) ? currentProposal : undefined;
  const failedProposal = currentProposal && !currentProposal.stale && currentProposal.status === "failed" ? currentProposal : undefined;
  const staleProposal = currentProposal?.stale ? currentProposal : undefined;
  const savedRequests = [...(links?.requests || [])];
  if (requestState.saved && !savedRequests.some((item) => item.request_id === requestState.saved?.request_id)) savedRequests.push(requestState.saved);
  const submitted = savedRequests.find((request) => request.request_id === currentDraft.requestId);
  const relatedRequests = savedRequests.filter((request) => request.target_run_id === run.id && request.request_id !== currentDraft.requestId);
  const hasRelated = Boolean(links?.origin || links?.children.length || relatedRequests.length);
  const requestOpen = Boolean(currentDraft.text || currentDraft.reply || currentProposal || submitted || generating || submitting || requestState.error);
  const canRequest = status !== "in_progress" || run.tasks.some((item) => item.action_results.length);
  const error = [requestState.error, queryError].filter(Boolean).join(" ");
  const mounted = useRef(true);
  const context = useRef({ scopeKey, draft, canRequest, loading });
  context.current = { scopeKey, draft, canRequest, loading };

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, [scopeKey]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setQueryError("");
    void window.orchestrator.request<ResultRevisionLinks>("runs.resultRevisions", { projectName, runId: run.id })
      .then((result) => { if (active) setLinkedResult({ key: scopeKey, value: result }); })
      .catch((requestError) => { if (active) setQueryError(`후속 요청 관계를 확인하지 못했습니다. ${errorMessage(requestError)}`); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scopeKey, projectName, run.id, refreshKey, requestState.proposal, requestState.saved]);

  useEffect(() => {
    if (draft || !links || requestState.pending) return;
    const latest = (links.proposals || []).slice().reverse().find((item) => item.focus_task_id === focusId && !item.stale
      && (item.status === "ready" || item.status === "needs_clarification"));
    if (!latest) return;
    const accepted = links.requests.find((item) => item.proposal_id === latest.proposal_id);
    onDraftChange((current) => current || { requestId: accepted?.request_id || "", text: latest.text, proposalId: latest.proposal_id });
  }, [draft, focusId, links, onDraftChange, requestState.pending]);

  const canStartRequest = () => mounted.current && context.current.scopeKey === scopeKey
    && context.current.draft === draft && context.current.canRequest && !context.current.loading
    && requests.read(scopeKey) === requestState;

  const generateProposal = async (textOverride?: string) => {
    const text = textOverride ?? currentDraft.text;
    if (!canStartRequest() || (!text.trim() && !(run.stage === "failed" && run.failed_step === "agent_execution"))) return;
    const reply = textOverride === undefined ? currentDraft.reply?.trim() : "";
    const proposalText = reply && matchingProposal ? [
      matchingProposal.text,
      `이전 AI 제안: ${matchingProposal.summary}`,
      matchingProposal.question ? `확인 질문: ${matchingProposal.question}` : "",
      `사용자 답변·수정: ${reply}`,
    ].filter(Boolean).join("\n") : text;
    const pending = requests.begin(scopeKey, "generate");
    if (!pending) return;
    const submittedDraft = { ...currentDraft, text: proposalText, requestId: "", proposalId: "", reply: "" };
    try {
      const result = await window.orchestrator.request<ResultRevisionProposal>("runs.proposeResultRevision", {
        projectName, runId: run.id, proposalId: pending.id, text: proposalText, focusTaskId: focusId,
      });
      if (!result.proposal_id || result.text !== proposalText.trim() || result.focus_task_id !== focusId
        || !["ready", "needs_clarification", "failed"].includes(result.status)) {
        throw new Error("대상 결과의 AI 제안 완료 기록이 요청과 일치하지 않습니다. 상태를 다시 확인하세요.");
      }
      requests.complete(scopeKey, pending, { proposal: result,
        error: result.status === "failed" ? `AI 수정 제안 실패 · ${result.error || "실패 이유 기록 없음"}` : "" });
      if (result.status === "ready" || result.status === "needs_clarification") {
        onDraftChange((current) => current === draft
          ? { ...submittedDraft, text: result.text, reply: "", proposalId: result.proposal_id, requestId: "" } : current);
      }
    } catch (requestError) {
      requests.fail(scopeKey, pending, `AI 수정 제안을 만들지 못했습니다. ${errorMessage(requestError)}`);
    }
  };
  const submit = async () => {
    const selected = matchingProposal;
    if (!canStartRequest() || !selected || selected.stale || selected.status !== "ready"
      || selected.next_action === "recovery" || currentDraft.reply?.trim() || submitted) return;
    const pending = requests.begin(scopeKey, "save");
    if (!pending) return;
    const requestId = currentDraft.requestId || pending.id;
    onDraftChange((current) => current === draft ? { ...currentDraft, requestId, proposalId: selected.proposal_id } : current);
    try {
      const saved = await window.orchestrator.request<ResultRevisionRequest>("runs.createResultRevision", {
        projectName, runId: run.id, requestId, text: selected.text,
        taskIds: selected.task_ids, paths: selected.paths, proposalId: selected.proposal_id,
      });
      if (saved.request_id !== requestId || saved.proposal_id !== selected.proposal_id || saved.text !== selected.text
        || !saved.target_run_id || JSON.stringify(saved.task_ids) !== JSON.stringify(selected.task_ids)
        || JSON.stringify(saved.paths) !== JSON.stringify(selected.paths)) {
        throw new Error("수정 요청 저장 기록이 확인한 제안과 일치하지 않습니다. 상태를 다시 확인하세요.");
      }
      requests.complete(scopeKey, pending, { saved });
    } catch (requestError) {
      requests.fail(scopeKey, pending, `수정 요청 초안을 저장하지 못했습니다. ${errorMessage(requestError)}`);
    }
  };

  return <section className="result-review" aria-label="결과 확인">
    <header className="result-review__header">
      <span className="result-review__eyebrow">{task ? "작업" : "작업 그룹"}</span>
      <h2 id="results-workbench-title" tabIndex={-1}>{task?.title || run.summary || "작업 그룹"}</h2>
    </header>
    <div className="result-review__outcome" data-tone={outcome.tone} role="status">
      <span className="result-review__outcome-icon">{outcome.tone === "success" ? <Check size={18} aria-hidden="true" />
        : outcome.tone === "warning" ? <AlertCircle size={18} aria-hidden="true" /> : <ListChecks size={18} aria-hidden="true" />}</span>
      <div><h3>{outcome.title}</h3><p className="result-review__verification">{outcome.detail}</p></div>
    </div>
    <section className="result-review__summary" aria-label="바뀐 내용">
      <h3>바뀐 내용</h3>
      {task ? taskResult?.self_report ? <p className="result-review__self-report">{taskResult.self_report}</p>
        : <p className="muted-copy">저장된 변경 요약이 없습니다. 변경 파일과 완료 기록을 확인하세요.</p>
        : completedTasks.length ? <><ul>{completedTasks.slice(0, 3).map((item) => <li key={item.id}>{item.title}</li>)}</ul>
          {completedTasks.length > 3 ? <p className="muted-copy">외 {completedTasks.length - 3}개 작업 · 아래 작업 결과에서 확인할 수 있어요.</p> : null}</>
          : <p className="muted-copy">완료된 작업 기록이 아직 없습니다.</p>}
    </section>
    <div className="result-review__resources">
    <details className="result-review__files">
      <summary><span><Files size={17} aria-hidden="true" />변경 파일</span><span className="result-review__resource-meta">{fileSummary}<ChevronRight size={14} aria-hidden="true" /></span></summary>
      <div className="result-review__resource-body">
        {task ? <>
          <FinalFiles expanded state={taskResult?.files_state || "unavailable"} files={taskResult?.files || []} error={taskResult?.error} />
          {taskResult ? <details><summary>완료 기록 보기</summary><small>작업 ID · {task?.id} · 결과 commit · <code>{taskResult.result_commit}</code> · 완료 {new Date(taskResult.captured_at).toLocaleString()}</small></details> : null}
          <PriorTaskResults task={task} />
        </> : <>
          <FinalFiles expanded state={groupResult?.files_state || "unavailable"} files={groupResult?.files || []} error={groupResult?.error} />
          {groupResult ? <details><summary>검증 기록 보기</summary><small>통합 commit · <code>{groupResult.result_commit}</code> · 검증 완료 {new Date(groupResult.captured_at).toLocaleString()}</small></details> : null}
        </>}
      </div>
    </details>
    {!task ? <details className="result-review__tasks" aria-label="Task별 작업 결과">
      <summary><span><ListChecks size={17} aria-hidden="true" />작업 결과</span><span className="result-review__resource-meta">{completedTasks.length}/{run.tasks.length}개 완료<ChevronRight size={14} aria-hidden="true" /></span></summary>
      <div className="result-review__task-list">{run.tasks.length ? run.tasks.map((item) => <TaskResultCard key={item.id} task={item} onOpenTask={onOpenTask} />) : <p>Task 기록 없음</p>}</div>
    </details> : null}
    </div>
    <details className="result-review__details" open={requestOpen || Boolean(error)}>
      <summary><ChevronRight size={14} aria-hidden="true" />상세 기록</summary>
      <div className="result-review__details-body">
    <div className="result-review__actions">
      {task ? <button className="button button--secondary" type="button" onClick={() => onOpenTask(task.id)}>Task 상세·로그</button> : null}
      <button className="button button--secondary" type="button" onClick={onOpenOperations}>최종 검증 기록</button>
    </div>
    <details className="result-review__evidence"><summary>시도 중 변경 경로·통과 명령 기록 보기</summary>
      <h3>실행 시도 중 변경 경로</h3><p className="muted-copy">재시도에서 되돌린 파일이 포함될 수 있어 최종 변경 파일과 다릅니다.</p>
      {attemptedPaths.length ? <ul>{attemptedPaths.map((path) => <li key={path}><code>{path}</code></li>)}</ul> : <p>기록 없음</p>}
      <h3>통과 명령</h3>{verification.commands.length ? <ul>{verification.commands.map((command, index) => <li key={`${index}-${command}`}><code>{command}</code></li>)}</ul> : <p>미검증 · 통과 명령 기록 없음</p>}
    </details>
    {hasRelated ? <details className="result-review__related" aria-label="연결된 작업">
      <summary>연결된 작업</summary>
      {loading ? <p role="status">연결 관계 확인 중…</p> : null}
      {links?.origin ? <button className="button button--quiet" type="button" onClick={() => onNavigate(links.origin!.id, "results")}>원래 결과 · {links.origin.summary || links.origin.id}</button> : null}
      {links?.children.map((child) => <button className="button button--quiet" type="button" key={child.id} onClick={() => onNavigate(child.id, "planning")}>후속 그룹 · {child.summary || child.id}</button>)}
      {relatedRequests.map((request) =>
        <div key={request.request_id} className="result-review__saved-request">
          <p>{request.handling === "same_task_retry" ? "같은 Task 재시도 지시" : "같은 그룹의 수정 요청 초안"} · {request.text}</p>
          {request.handling === "same_task_retry"
            ? <button className="button button--quiet" type="button" onClick={() => onOpenTask(request.task_ids[0])}>실패 Task 보기</button>
            : <button className="button button--quiet" type="button" onClick={() => onNavigate(run.id, "planning", resultRevisionContext(run, request.text, request.task_ids, request.paths))}>후속 계획 열기</button>}
        </div>)}
    </details> : null}
    {canRequest ? <details className="result-review__request" aria-label="수정 요청" open={requestOpen}>
      <summary>수정 요청</summary>
      <div className="result-review__request-heading"><div><h3>수정할 점이 있나요?</h3><p>AI가 저장된 결과와 실패 근거를 보고 대상과 다음 행동을 제안합니다. 제안만으로 실행되지는 않습니다.</p></div></div>
      <div className="result-review__editor">
        {matchingProposal ? <div className="result-review__preview" role="status"><strong>{matchingProposal.status === "needs_clarification" ? "대상 확인 필요" : "AI 수정 제안"}</strong>
          {matchingProposal.summary ? <p>{matchingProposal.summary}</p> : null}
          {matchingProposal.reason ? <p>근거 · {matchingProposal.reason}</p> : null}
          {matchingProposal.question ? <p>확인 질문 · {matchingProposal.question}</p> : null}
          {matchingProposal.status === "ready" ? <>
            <p>대상 · {matchingProposal.task_ids.map((id) => run.tasks.find((item) => item.id === id)?.title || id).join(", ")}</p>
            {matchingProposal.paths.length ? <details><summary>관련 파일 {matchingProposal.paths.length}개</summary><ul>{matchingProposal.paths.map((path) => <li key={path}><code>{path}</code></li>)}</ul></details> : null}
            <p>다음 단계 · {matchingProposal.next_action === "retry_task" ? "같은 Task의 재시도 지시를 저장합니다. 재시도는 Task 화면에서 별도로 시작합니다."
              : matchingProposal.next_action === "same_group_plan" ? "현재 그룹의 후속 계획 초안을 저장합니다."
                : matchingProposal.next_action === "linked_group" ? "원본을 보존하고 연결된 새 그룹의 기획 초안을 만듭니다."
                  : "개별 Task 재시도 대상이 아닙니다. 그룹 복구 경로를 확인해 주세요."}</p>
            {matchingProposal.next_action === "recovery" ? <button className="button button--quiet" type="button" onClick={onOpenOperations}>실패·검증 기록 보기</button> : null}
          </> : null}
        </div> : null}
        <button className="button button--secondary" type="button" disabled={loading || generating || submitting || (!discussionText?.trim() && !currentDraft.text.trim() && !(run.stage === "failed" && run.failed_step === "agent_execution"))}
          onClick={() => void generateProposal(discussionText?.trim() || undefined)}>{generating ? <RefreshCw className="spin" size={16} aria-hidden="true" /> : null}{generating ? "수정안 작성 중" : matchingProposal ? "대화로 수정안 다시 만들기" : "대화로 수정안 만들기"}</button>
        {currentDraft.text ? <details><summary>수정안에 전달한 대화</summary><p className="work-ai-proposal">{currentDraft.text}</p></details> : <p className="muted-copy">기존 채팅에서 바꿀 점을 이야기한 뒤 수정안을 만들어 주세요.</p>}
        {failedProposal ? <p role="alert" className="inline-error">AI 수정 제안 실패 · {failedProposal.error}</p> : null}
        {staleProposal ? <p role="status" className="muted-copy">원본 결과가 바뀌었습니다. AI 제안을 다시 받아 확인해 주세요.</p> : null}
        {submitted ? <div role="status" className="result-review__submitted"><CheckCircle2 size={16} aria-hidden="true" />수정안 저장됨 · {submitted.handling === "same_task_retry"
          ? <button className="button button--quiet" type="button" onClick={() => onOpenTask(submitted.task_ids[0])}>실패 Task 보기</button>
          : <button className="button button--quiet" type="button" onClick={() => onNavigate(submitted.target_run_id, "planning", submitted.target_run_id === run.id ? resultRevisionContext(run, submitted.text, submitted.task_ids, submitted.paths) : undefined)}>후속 작업으로 이동</button>}
          <button className="button button--quiet" type="button" disabled={generating || submitting} onClick={() => onDraftChange({ requestId: "", text: "", proposalId: "" })}>새 수정 요청</button></div>
          : matchingProposal?.status === "ready" && matchingProposal.next_action !== "recovery" && !currentDraft.reply?.trim() ? <button className="button button--primary" type="button" disabled={generating || submitting || loading} onClick={() => void submit()}>{submitting ? <RefreshCw className="spin" size={16} aria-hidden="true" /> : null}수정안 확인·저장</button> : null}
      </div>
    </details> : null}
      </div>
    </details>
    {error ? <p className="inline-error" role="alert"><AlertCircle size={16} aria-hidden="true" />{error}{queryError ? <button className="button button--quiet" type="button" disabled={loading} onClick={() => setRefreshKey((value) => value + 1)}>다시 확인</button> : null}</p> : null}
    {onDiscuss ? <footer className="result-review__footer"><span>더 확인하거나 수정하고 싶다면</span><button className="button button--quiet" type="button" onClick={onDiscuss}><MessageSquare size={15} aria-hidden="true" />채팅에서 이어가기<ArrowUpRight size={14} aria-hidden="true" /></button></footer> : null}
  </section>;
}
