import type { ActiveGroupSnapshot, RegisteredProject, RunSummary, RunExecutionControl } from "./types";
import { activeGroupActivityLabel } from "./activeGroups";

export type WorkBucket = "attention" | "running" | "waiting" | "completed";
export const workBucketLabels: Record<WorkBucket, string> = {
  attention: "확인 필요", running: "실행 중", waiting: "실행 대기", completed: "완료",
};
export const workBuckets: WorkBucket[] = ["running", "attention", "waiting", "completed"];

export interface ProjectWorkSnapshot {
  groups: RunSummary[];
  checkedAt: string;
  error: string;
  controls?: Record<string, RunExecutionControl>;
  controlErrors?: Record<string, string>;
}
export interface ProjectWork {
  name: string;
  groups: { run: RunSummary; bucket: WorkBucket; active: boolean; reason: string }[];
  counts: Record<WorkBucket, number>;
  completedTasks: number;
  totalTasks: number;
  checkedAt: string;
  error: string;
  pending: boolean;
  unknown: boolean;
}

export type ProjectWorkFilter = "all" | "running" | "attention";

export function filterProjectWork(projects: ProjectWork[], filter: ProjectWorkFilter, search: string): ProjectWork[] {
  const query = search.trim().toLocaleLowerCase("ko-KR");
  return projects.filter((project) => (!query || project.name.toLocaleLowerCase("ko-KR").includes(query))
    && (filter === "all" || filter === "running" && project.groups.some((item) => item.active)
      || filter === "attention" && Boolean(project.error || project.unknown || project.counts.attention)));
}

export function projectWork(projects: RegisteredProject[], snapshots: Record<string, ProjectWorkSnapshot>, active: ActiveGroupSnapshot): ProjectWork[] {
  return projects.map((project) => {
    const snapshot = snapshots[project.name];
    const activityError = active.errors.find((item) => item.project_name === project.name)?.error || "";
    const error = snapshot?.error || activityError;
    const counts = { attention: 0, running: 0, waiting: 0, completed: 0 };
    const groups = (snapshot?.groups || []).map((run) => {
      const evidence = active.items.find((item) => item.project_name === project.name && item.run_id === run.id);
      const control = snapshot?.controls?.[run.id];
      const uncertain = Boolean(error || snapshot?.controlErrors?.[run.id] || evidence?.stale || evidence?.status === "check_required"
        || run.execution_situation === "status_unknown");
      const live = Boolean(evidence?.status === "active" && !uncertain);
      const stopped = control?.stop_phase === "stopped";
      const bucket: WorkBucket = uncertain || run.stage === "failed" || run.failed_task_count > 0
        ? "attention" : stopped ? "waiting" : run.attention_reasons.length ? "attention"
          : live ? "running" : run.pipeline_complete ? "completed" : "waiting";
      counts[bucket]++;
      return { run, bucket, active: live, reason: uncertain ? "최신 상태 확인 불가"
        : stopped ? `중지됨 · ${control.action === "resume" ? "재개 가능" : "재개 조건 확인 필요"} · 자동으로 재개하지 않습니다` : live && evidence ? activeGroupActivityLabel(evidence)
          : control?.stop_phase === "stopping" ? "중지 요청 처리 중"
          : run.attention_reasons.length ? "사용자 확인 대기" : run.pipeline_complete ? "작업 완료" : "실행 조건 확인·대기" };
    });
    return { name: project.name, groups, counts,
      completedTasks: groups.reduce((sum, item) => sum + item.run.completed_task_count, 0),
      totalTasks: groups.reduce((sum, item) => sum + item.run.task_count, 0),
      checkedAt: snapshot?.checkedAt || "", error, pending: !snapshot,
      unknown: Boolean(error || groups.some((item) => item.reason === "최신 상태 확인 불가")) };
  }).sort((left, right) => projectPriority(left) - projectPriority(right));
}

function projectPriority(project: ProjectWork): number {
  if (project.groups.some((item) => item.active)) return 0;
  if (project.error || project.counts.attention) return 1;
  if (project.counts.waiting || project.pending) return 2;
  return 3;
}

export function initialWorkBucket(project: ProjectWork): WorkBucket[] {
  const first = workBuckets.find((bucket) => project.counts[bucket]);
  return first ? [first] : [];
}
