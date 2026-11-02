import type { RunSummary } from "./types";

export type RunStatusFilter = "all" | "running" | "failed" | "attention" | "completed";

export const runStatusFilterLabels: Record<RunStatusFilter, string> = {
  all: "전체",
  running: "실행 중",
  failed: "실패",
  attention: "내 확인 필요",
  completed: "완료",
};

export function runMatchesSearch(run: RunSummary, search: string): boolean {
  const keyword = search.trim().toLocaleLowerCase("ko");
  return !keyword || `${run.summary} ${run.id}`.toLocaleLowerCase("ko").includes(keyword);
}

export function runMatchesStatus(run: RunSummary, filter: RunStatusFilter): boolean {
  if (filter === "all") return true;
  if (filter === "running") return ["running", "preparing"].includes(run.execution_situation);
  if (filter === "failed") return run.stage === "failed" || run.failed_task_count > 0;
  if (filter === "attention") return run.attention_reasons.length > 0;
  return run.pipeline_complete;
}

export function filterRuns(runs: RunSummary[], search: string, filter: RunStatusFilter): RunSummary[] {
  return runs.filter((run) => runMatchesSearch(run, search) && runMatchesStatus(run, filter));
}

export function runFilterCounts(runs: RunSummary[], search: string): Record<RunStatusFilter, number> {
  const searched = runs.filter((run) => runMatchesSearch(run, search));
  return {
    all: searched.length,
    running: searched.filter((run) => runMatchesStatus(run, "running")).length,
    failed: searched.filter((run) => runMatchesStatus(run, "failed")).length,
    attention: searched.filter((run) => runMatchesStatus(run, "attention")).length,
    completed: searched.filter((run) => runMatchesStatus(run, "completed")).length,
  };
}
