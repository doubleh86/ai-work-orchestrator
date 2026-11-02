import { LoaderCircle } from "lucide-react";

import type { PlanningPreviewOperation, PlanningPreviewStatus, RunState } from "./types";
import { previewElapsed, previewOperationLabel, previewPhaseLabel } from "./planningPreviewRequest";
import { progressPhaseLabels } from "./progressLog";

export interface PlanningPreviewContext { projectName: string; run: RunState; }

function shortText(text: string): string {
  const normalized = text.trim().replace(/\s+/gu, " ");
  return normalized.length > 200 ? `${normalized.slice(0, 200)}…` : normalized;
}

function publicPhase(phase: string): string {
  return Object.hasOwn(progressPhaseLabels, phase) ? progressPhaseLabels[phase] : "";
}

function requestSummary(status: PlanningPreviewStatus | undefined, run: RunState | undefined, runId: string):
  { text: string; source: "chat" | "direction" } | undefined {
  const preview = status?.preview;
  if (!run || !preview || preview.run_id !== runId || !preview.preview_id || !preview.request_id
    || status.work_state !== "idle" || !["ready", "applied"].includes(status.phase)
    || (preview.stale && status.phase !== "applied") || preview.conversation_revision !== run.planning_conversation_revision) return undefined;
  const created = Date.parse(preview.created_at);
  if (!Number.isFinite(created)) return undefined;
  if (preview.direction_request_ids?.length) {
    const requests = preview.direction_request_ids.map((id) => run.direction_change_requests?.find((item) => item.request_id === id));
    if (requests.some((item) => !item || !item.text.trim() || !Number.isFinite(Date.parse(item.created_at))
      || Date.parse(item.created_at) > created)) return undefined;
    return { text: shortText(requests.map((item) => item?.text || "").join(" · ")), source: "direction" };
  }
  const message = run.planning_messages.filter((item) => item.role === "user" && item.text.trim()).at(-1);
  if (!message || !Number.isFinite(Date.parse(message.at)) || !Number.isFinite(Date.parse(preview.created_at))
    || Date.parse(message.at) > created) return undefined;
  return { text: shortText(message.text), source: "chat" };
}

function operationExplanation(kind: PlanningPreviewOperation["kind"]): { purpose: string; result: string } {
  const previewResult = "완료되면 추가·수정·유지되는 Task와 영향을 보여드립니다.";
  const descriptions: Record<PlanningPreviewOperation["kind"], { purpose: string; result: string }> = {
    planning_chat: { purpose: "현재 요청에 대한 기획 답변을 작성하고 있습니다.", result: "답변을 확인한 뒤 필요한 Task 변경안을 미리볼 수 있습니다." },
    preview_generation: { purpose: "요청 내용을 바탕으로 Task 변경안을 만들고 있습니다.", result: previewResult },
    preview_comparison: { purpose: "작성된 변경안을 현재 Task와 비교하고 있습니다.", result: previewResult },
    task_execute: { purpose: "확인된 Task의 구현 작업을 진행하고 있습니다.", result: "작업 결과와 검증·리뷰 상태를 확인할 수 있습니다." },
    task_review: { purpose: "Task 결과를 검토하고 있습니다.", result: "리뷰 결과에서 승인 또는 수정이 필요한지 확인할 수 있습니다." },
    task_verify: { purpose: "Task 변경과 검증 결과를 확인하고 있습니다.", result: "검증 결과와 실패한 경우의 근거를 확인할 수 있습니다." },
    plan_apply: { purpose: "확인한 변경안을 현재 그룹의 계획에 반영하고 있습니다.", result: "실제 반영된 Task 내역을 보여드립니다. Task 실행은 별도로 선택합니다." },
    run_verify: { purpose: "작업 그룹의 통합 검증을 진행하고 있습니다.", result: "검증 결과와 가능한 다음 행동을 확인할 수 있습니다." },
    run_operation: { purpose: "확인된 그룹 작업이 진행 중입니다.", result: "완료 후 그룹 상태와 가능한 다음 행동을 확인할 수 있습니다." },
  };
  return descriptions[kind];
}

function phaseExplanation(status: PlanningPreviewStatus | undefined, applying: boolean): { purpose: string; result: string } {
  if (applying) return { purpose: "현재 작업 상태를 다시 확인한 뒤 확인한 변경안을 반영합니다.", result: "실제 반영된 Task 내역을 보여드립니다. Task 실행은 별도로 선택합니다." };
  if (!status || !["idle", "active", "unknown", "interrupted"].includes(status.work_state)) {
    return { purpose: "현재 작업과 저장된 변경안의 상태를 확인하고 있습니다.", result: "확인된 작업의 목적과 다음 결과를 안내합니다." };
  }
  if (status?.work_state === "unknown" || status?.phase === "check_required") {
    return { purpose: "현재 작업 상태를 확인하지 못했습니다.", result: "상태를 확인한 뒤 현재 작업과 변경안을 안내합니다." };
  }
  if (status?.phase === "ready") return { purpose: "Task 변경안과 영향을 확인합니다.", result: "내용을 검토한 뒤 선택한 변경안을 명시적으로 반영할 수 있습니다." };
  if (status?.phase === "applied") return { purpose: "확인한 변경안의 실제 반영 내역을 확인합니다.", result: "변경된 계획을 확인한 뒤 그룹의 다음 행동을 선택하세요." };
  if (status?.phase === "failed" || status?.phase === "interrupted") {
    return { purpose: "변경안 작성을 완료하지 못했습니다.", result: "실패·중단 근거와 가능한 복구 행동을 확인하세요." };
  }
  if (status.phase === "idle") return { purpose: "현재 요청의 Task 변경안을 작성할 수 있는지 확인합니다.", result: "작성 가능한 변경안의 Task 내역과 영향을 확인할 수 있습니다." };
  return operationExplanation(status?.phase === "chat" ? "planning_chat" : status?.phase === "comparing" ? "preview_comparison" : "preview_generation");
}

function reportedActivity(operation: PlanningPreviewOperation, checkedAt: string, run: RunState | undefined): string {
  if (!run) return "";
  const start = Date.parse(operation.started_at);
  const checked = Date.parse(checkedAt);
  const inOperation = (at: string) => Number.isFinite(start) && Number.isFinite(checked)
    && Date.parse(at) >= start && Date.parse(at) <= checked;
  if (operation.task_id) {
    const task = run.tasks.find((item) => item.id === operation.task_id);
    const actions: Partial<Record<PlanningPreviewOperation["kind"], string[]>> = {
      task_execute: ["execute", "revise"], task_review: ["review"], task_verify: ["verify"],
    };
    if (!task || task.last_attempt_started_at !== operation.started_at || !actions[operation.kind]?.includes(task.active_action || "")
      || !inOperation(task.progress_updated_at)) return "";
    const observation = task.progress_observation;
    if (!observation || !task.last_attempt_id || observation.attempt_id !== task.last_attempt_id
      || observation.phase !== task.progress_phase || observation.last_event_received_at !== task.progress_updated_at) return "";
    if (observation.evidence_kind !== "local_phase" && task.active_invocation_id
      && observation.invocation_id !== task.active_invocation_id) return "";
    return publicPhase(task.progress_phase);
  }
  if (!["planning_chat", "preview_generation", "preview_comparison"].includes(operation.kind)) return "";
  const event = [...run.events].reverse().find((item) => item.kind === "planning_progress"
    && item.at === operation.last_activity_at && inOperation(item.at));
  const phase = event?.message.match(/^codex sdk progress: ([a-z_]+)(?:\s*\|.*)?$/u)?.[1];
  return phase ? publicPhase(phase) : "";
}

export function PlanningPreviewProgress({ projectName, runId, status, context, applying, now }: {
  projectName: string;
  runId: string;
  status: PlanningPreviewStatus | undefined;
  context?: PlanningPreviewContext;
  applying: boolean;
  now: number;
}) {
  const run = context?.projectName === projectName && context.run.id === runId ? context.run : undefined;
  const preview = status?.preview?.run_id === runId ? status.preview : undefined;
  const title = shortText(run?.summary || preview?.run_title || "현재 작업 그룹");
  const request = requestSummary(status, run, runId);
  const summary = request?.text || "";
  const operations = !applying && status?.work_state === "active" ? status.active_operations : [];
  const explanation = phaseExplanation(status, applying);
  const results = operations.length
    ? [...new Set(operations.map((operation) => operationExplanation(operation.kind).result))]
    : [explanation.result];
  return <section className="planning-preview-dialog__progress" aria-label="현재 작업 안내">
    <div className="planning-preview-dialog__request">
      <span className="planning-preview-dialog__label">요청 요약</span>
      <strong>{summary || title}</strong>
      <small>{projectName}{summary ? ` · ${title}` : ""}</small>
    </div>
    {operations.length ? operations.map((operation) => {
      const elapsed = previewElapsed(operation.started_at, now);
      const activity = reportedActivity(operation, status?.checked_at || "", run);
      return <div className="planning-preview-dialog__operation" key={`${operation.operation}:${operation.task_id}`}>
        <p><LoaderCircle className="planning-preview-dialog__spinner" size={16} aria-hidden="true" />
          <strong role="status">{previewOperationLabel(operation)}</strong><small>{elapsed === undefined ? "시작 시각 정보 없음" : `${elapsed}초 경과`}</small></p>
        {activity ? <p className="planning-preview-dialog__activity">최근 보고 · {activity}</p> : null}
      </div>;
    }) : <div>
      <p role="status"><strong>{applying ? "반영 전 상태 확인·계획 반영 중" : previewPhaseLabel(status)}</strong></p>
      <p>{explanation.purpose}</p>
    </div>}
    {results.map((result) => <p className="planning-preview-dialog__waiting" key={result}>{result}</p>)}
    <details className="planning-preview-dialog__progress-details">
      <summary>진행 상세</summary>
      {summary ? <small>요청 원문 · {request?.source === "direction" ? "방향 수정 내역" : "기획 대화"}</small> : null}
      {operations.map((operation) => <div key={`${operation.operation}:${operation.task_id}`}>
        {operations.length > 1 ? <strong>{previewOperationLabel(operation)}</strong> : null}
        <small>{operation.last_activity_at ? `최근 AI 활동 ${new Date(operation.last_activity_at).toLocaleString()}` : "최근 활동 정보 없음"}</small>
        {operation.stage_changed_at ? <small>작업 단계 변경 {new Date(operation.stage_changed_at).toLocaleString()}</small> : null}
      </div>)}
      {status?.checked_at ? <small>상태 조회 {new Date(status.checked_at).toLocaleTimeString()}</small> : <small>상태 조회 결과를 기다리고 있습니다.</small>}
    </details>
  </section>;
}
