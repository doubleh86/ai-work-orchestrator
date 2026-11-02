import type { PlanningMode, RepositoryMaturityKind, RunEvent, RunState, RunSummary } from "./types";

export async function findPendingTechnologyPlanning(
  summaries: RunSummary[],
  loadRun: (runId: string) => Promise<RunState>,
  request?: { mode: PlanningMode; text: string; sourcePath: string },
): Promise<RunState | undefined> {
  const candidates = summaries.filter((run) => !run.archived && run.task_count === 0
    && ["reviewed", "needs_clarification", "planned", "failed"].includes(run.stage))
    .sort((left, right) => right.created_at.localeCompare(left.created_at));
  for (const candidate of candidates) {
    const run = await loadRun(candidate.id);
    if (run.id !== candidate.id || run.archive || run.repository_intent !== "new_project" || run.tasks.length
      || !["reviewed", "needs_clarification", "planned", "failed"].includes(run.stage)
      || !["stack_decision_required", "questions_required", "options_ready", "stack_confirmed"].includes(run.greenfield_phase || "")) continue;
    if (request && (run.planning_mode !== request.mode || run.planning_request.trim() !== request.text.trim()
      || run.spec_path.replace(/\\/g, "/") !== request.sourcePath.trim().replace(/\\/g, "/"))) continue;
    return run;
  }
  return undefined;
}

export interface PlanningStartReadinessInput {
  projectAvailable: boolean;
  mode: PlanningMode;
  request: string;
  sourcePath: string;
  profileCount: number;
  providerReady: boolean;
  repositoryMaturity?: RepositoryMaturityKind;
  repositoryIntent?: "" | "existing_structure" | "new_project";
  repositoryInspectionPending?: boolean;
}

export interface PlanningStartReadiness {
  ready: boolean;
  reason: string;
}

export type PlanningActivityPurpose = "plan" | "chat" | "apply";

export interface PlanningProgressContext {
  purpose: PlanningActivityPurpose;
  retryIndex: number;
}

export function planningStartReadiness(
  input: PlanningStartReadinessInput,
): PlanningStartReadiness {
  if (!input.projectAvailable) {
    return { ready: false, reason: "계획을 시작할 프로젝트를 먼저 선택해 주세요." };
  }
  if (input.repositoryInspectionPending) {
    return { ready: false, reason: "프로젝트의 코드와 기본 구조를 확인한 뒤 계획을 시작할 수 있습니다." };
  }
  if (input.repositoryMaturity === "ambiguous" && !input.repositoryIntent) {
    return { ready: false, reason: "현재 코드로 계속할지 기본 구조부터 만들지 먼저 선택해 주세요." };
  }
  if (input.mode === "directed" && !input.request.trim()) {
    return { ready: false, reason: "지정 작업에서 계획할 요청을 입력해 주세요." };
  }
  if (input.mode === "auto" && !input.sourcePath.trim()) {
    return { ready: false, reason: "풀 오토 탐색에는 확인할 기획 자료 디렉터리가 필요합니다." };
  }
  if (!input.profileCount) {
    return { ready: false, reason: "사용 가능한 기획 모델이 없습니다. AI 설정을 확인해 주세요." };
  }
  if (!input.providerReady) {
    return { ready: false, reason: "선택한 기획 모델의 인증 상태를 확인해 주세요." };
  }
  return { ready: true, reason: "" };
}

export function planningSourceSummary(
  mode: PlanningMode,
  sourcePath: string,
  documentCount?: number,
): string {
  if (!sourcePath.trim()) {
    return mode === "directed" ? "사용 안 함 · 요청과 저장소 기준" : "필수 · 선택 안 됨";
  }
  return documentCount === undefined
    ? "디렉터리 선택됨 · 색인 확인 필요"
    : `디렉터리 선택됨 · 색인 ${documentCount.toLocaleString("ko-KR")}개`;
}

export function planningProgressContext(events: RunEvent[]): PlanningProgressContext {
  let boundaryIndex = -1;
  let purpose: PlanningActivityPurpose = "plan";
  events.forEach((event, index) => {
    if (
      event.message === "planning message received" ||
      event.message === "planning chat message received"
    ) {
      boundaryIndex = index;
      purpose = "chat";
    } else if (
      event.message === "planning apply requested" ||
      event.message === "planning apply requested from chat"
    ) {
      boundaryIndex = index;
      purpose = "apply";
    } else if (event.message === "planning document reviewed") {
      boundaryIndex = index;
      purpose = "plan";
    }
  });

  const requestEvents = events.slice(boundaryIndex + 1);
  let completedFailures = 0;
  let retryIndex = 0;
  for (const event of requestEvents) {
    if (/^planning agent attempt \d+ failed:/.test(event.message)) {
      completedFailures += 1;
    }
    if (/^planning agent attempt \d+ started/.test(event.message) && completedFailures) {
      retryIndex = completedFailures;
    }
  }
  return { purpose, retryIndex };
}

export function planningPurposeActivity(purpose: PlanningActivityPurpose): string {
  if (purpose === "chat") return "답변을 작성하고 있습니다.";
  if (purpose === "apply") return "요청하신 내용을 계획에 반영하고 있습니다.";
  return "계획안을 작성하고 있습니다.";
}
