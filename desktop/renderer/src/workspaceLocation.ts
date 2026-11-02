import type { RunState } from "./types";
import { operationsSnapshotMatches, workspaceStateLabel, type OperationsSnapshot } from "./integrationCompletion";

export interface RunWorkspacePresentation {
  path: string;
  status: string;
}

export function runWorkspacePresentation(run: RunState, snapshot?: OperationsSnapshot, projectName = ""): RunWorkspacePresentation {
  const recorded = recordedWorkspacePresentation(run);
  if (!recorded.path || !operationsSnapshotMatches(snapshot, projectName, run)) return recorded;
  const paths = run.workspace_mode === "shared"
    ? [run.execution_worktree || run.tasks.find((task) => task.worktree)?.worktree].filter((path): path is string => Boolean(path))
    : run.tasks.map((task) => task.worktree).filter(Boolean);
  const expected = [...new Set(paths.map(normalizeRecordedPath))];
  if (!expected.length) return recorded;
  const states = expected.map((path) => snapshot?.workspaces.find((workspace) => workspace.run_id === run.id
    && normalizeRecordedPath(workspace.worktree) === path)?.state);
  if (states.some((state) => !state || !["not_prepared", "active", "stale", "cleaned", "unsafe"].includes(state))) {
    return { ...recorded, status: "상태 확인 필요" };
  }
  const distinct = [...new Set(states)];
  const status = distinct.length === 1 ? workspaceStateLabel(distinct[0] || "")
    : distinct.includes("unsafe") ? workspaceStateLabel("unsafe")
      : distinct.includes("cleaned") ? "일부 정리" : "작업공간별 상태 확인";
  return { ...recorded, status };
}

function recordedWorkspacePresentation(run: RunState): RunWorkspacePresentation {
  if (run.execution_worktree) {
    return { path: run.execution_worktree, status: "기록된 경로" };
  }
  if (run.workspace_location) {
    const status = run.tasks.some((task) => Boolean(task.worktree)) ? "기록된 경로" : "생성 예정";
    return { path: joinPathForDisplay(run.workspace_location.root, run.id), status };
  }
  const recorded = run.tasks.find((task) => Boolean(task.worktree))?.worktree || "";
  if (!recorded) return { path: "", status: "기록 없음" };
  return {
    path: run.workspace_mode === "shared" ? recorded : parentPathForDisplay(recorded),
    status: "기록된 경로",
  };
}

function normalizeRecordedPath(value: string): string {
  const normalized = value.replace(/\\/g, "/").replace(/\/+$/, "");
  return /^[a-z]:\//i.test(normalized) || value.startsWith("\\\\") ? normalized.toLowerCase() : normalized;
}

export function joinPathForDisplay(root: string, child: string): string {
  const separator = root.includes("\\") ? "\\" : "/";
  return `${root.replace(/[\\/]+$/, "")}${separator}${child}`;
}

function parentPathForDisplay(value: string): string {
  return value.replace(/[\\/]+$/, "").replace(/[\\/][^\\/]+$/, "");
}
