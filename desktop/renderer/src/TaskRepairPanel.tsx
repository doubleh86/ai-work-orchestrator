import { useEffect, useRef, useState } from "react";
import type { RunState, TaskRetryContext, WorkTask } from "./types";
import { summarizeProgressLog } from "./progressLog";
import { failedTaskQuestionKey } from "./failedTaskQuestionDrafts";
import { failurePresentation, isTaskScopeReview } from "./failurePresentation";

export function taskRepairQuestion(context: TaskRetryContext): string {
  if (isTaskScopeReview(context.error)) return "이 작업에 필요한 추가 경로와 이유를 확인하고, 기존 구현과 완료 조건을 보존하는 계획 변경안을 정리해 주세요.";
  return `이 작업의 문제를 해결해 주세요.\n문제: ${failurePresentation(context.error, "execute").title}`;
}

export function taskRepairMessage(context: TaskRetryContext, log: string, instruction: string): string {
  return `실패 Task ${context.task_id}: ${context.title}\n오류: ${context.error}\n완료 조건: ${context.acceptance_criteria.join("; ")}\n`
    + `이번 시도 AI 응답:\n${context.response.slice(-3000)}\n관련 로그:\n${log.slice(-4000)}\n`
    + `수정 지시: ${instruction}\n` + (isTaskScopeReview(context.error)
      ? "이것은 경로 추가 승인 요청입니다. 필요한 정확한 상대 경로와 이유를 검토하고 기존 계획 변경 흐름으로 안내하세요. 같은 계약의 재시도를 요청하지 마세요."
      : "현재 Task 계약을 유지하는 수정 방법을 논의해 주세요. 계획 필드 변경이 필요하면 먼저 구분해서 설명해 주세요.");
}

export function TaskRepairPanel({ projectName, run, task, draftRevision, onPrepared }: {
  projectName: string;
  run: RunState;
  task: WorkTask;
  draftRevision: number;
  onPrepared(message: string, draftRevision: number, diagnostic: string): void;
}) {
  const [context, setContext] = useState<TaskRetryContext>();
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  const [logError, setLogError] = useState("");
  const [logLoading, setLogLoading] = useState(true);
  const generation = useRef(0);
  const onPreparedRef = useRef(onPrepared);
  const revisionRef = useRef(draftRevision);
  onPreparedRef.current = onPrepared;
  revisionRef.current = draftRevision;
  const sourceKey = failedTaskQuestionKey(projectName, run, task);
  const sourceKeyRef = useRef(sourceKey);
  sourceKeyRef.current = sourceKey;

  async function load() {
    const current = ++generation.current;
    const revision = revisionRef.current;
    setError("");
    setContext(undefined);
    setLog("");
    setLogError("");
    setLogLoading(true);
    const [contextResult, logResult] = await Promise.allSettled([
      window.orchestrator.request<TaskRetryContext>("tasks.retryContext", { projectName, runId: run.id, taskId: task.id }),
      window.orchestrator.request<string>("tasks.log", { projectName, runId: run.id, taskId: task.id }),
    ]);
    if (current !== generation.current || sourceKeyRef.current !== sourceKey) return;
    setLogLoading(false);
    const logFailure = logResult.status === "rejected" ? String(logResult.reason) : "";
    const loadedLog = logResult.status === "fulfilled" ? logResult.value : "";
    setLog(loadedLog);
    setLogError(logFailure);
    if (contextResult.status === "rejected") { setError(String(contextResult.reason)); return; }
    const loaded = contextResult.value;
    if (loaded.task_id !== task.id) { setError("조회한 실패 기록의 작업이 현재 질문 대상과 다릅니다."); return; }
    setContext(loaded);
    onPreparedRef.current(taskRepairQuestion(loaded), revision,
      taskRepairMessage(loaded, logFailure ? `실행 기록 조회 실패: ${logFailure}` : loadedLog,
        loaded.instruction_current ? loaded.instruction?.text || "" : ""));
  }

  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [sourceKey]);

  return <section className="task-repair-panel" aria-label="실패 작업의 AI 논의 자료">
    <h3>이 작업의 문제 해결</h3>
    <p>질문을 확인·수정한 뒤 전송하세요. 이 작업의 진단 자료는 AI에게 함께 전달합니다.</p>
    {logLoading ? <p role="status">실패 자료를 불러오는 중입니다.</p> : !error ? <p role="status">실패 자료를 확인했습니다. 작성한 입력은 유지됩니다.</p> : null}
    {context ? <>
      <p>{failurePresentation(context.error, task.failed_action || "execute").title}</p>
      <details><summary>진단 자료 보기</summary><div className="task-repair-evidence">
        <p className="error-text">{context.error}</p>
        <section><h4>완료 조건</h4>{context.acceptance_criteria.length ? <ul>{context.acceptance_criteria.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>저장된 완료 조건이 없습니다.</p>}</section>
        <section><h4>AI 최종 응답</h4>{context.response ? <pre>{context.response}</pre> : <p>이 시도에 저장된 최종 응답이 없습니다. 아래 실행 기록에서 마지막 진행 내용을 확인하세요.</p>}</section>
        <section><h4>실행 기록</h4>{logError ? <p role="alert">로그 조회 실패: {logError}</p> : null}
          <pre aria-label="읽기 쉬운 실행 기록">{logLoading ? "실행 기록을 불러오는 중입니다." : summarizeProgressLog(log).text || (logError ? "실행 기록을 확인하지 못했습니다." : "저장된 실행 기록이 없습니다.")}</pre>
        </section>
        {log ? <details><summary>기술 정보 · 원문 로그</summary><pre aria-label="원문 로그">{log}</pre></details> : null}
      </div>
      </details>
    </> : null}
    {error ? <><p role="alert">실패 자료를 준비하지 못했습니다. 다시 조회하거나 질문을 직접 입력해 전송할 수 있습니다.</p>
      <details><summary>조회 오류 상세</summary><pre>{error}</pre>{logError ? <pre>{logError}</pre> : null}</details></> : null}
    {logError ? <p role="alert">{context ? "실행 기록을 조회하지 못했습니다. 확인한 실패 원인과 조회 오류를 AI에게 전달합니다." : "실행 기록을 조회하지 못했습니다. 다시 조회할 수 있습니다."}</p> : null}
    <div className="task-repair-panel__actions">
      {error || logError ? <button type="button" className="button button--secondary" disabled={logLoading} onClick={() => void load()}>실패 자료 다시 조회</button> : null}
    </div>
  </section>;
}
