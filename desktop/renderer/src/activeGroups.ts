import type { ActiveGroupSnapshot, ActiveGroupSummary } from "./types";

export function reconcileActiveGroups(previous: ActiveGroupSnapshot, incoming: ActiveGroupSnapshot): ActiveGroupSnapshot {
  const failedProjects = new Set(incoming.errors.map((error) => error.project_name));
  const stale = previous.items.filter((item) => failedProjects.has(item.project_name)).map((item) => ({
    ...item,
    status: "check_required" as const,
    activity_kinds: [],
    stale: true,
  }));
  return { ...incoming, items: [...incoming.items, ...stale] };
}

export function visibleActiveGroups(snapshot: ActiveGroupSnapshot, search: string): ActiveGroupSummary[] {
  const query = search.trim().toLocaleLowerCase();
  return snapshot.items
    .filter((item) => !query || `${item.project_name} ${item.title}`.toLocaleLowerCase().includes(query))
    .sort((left, right) => Number(right.status === "active") - Number(left.status === "active")
      || right.last_activity_at.localeCompare(left.last_activity_at));
}

export function confirmedActiveGroupCount(snapshot: ActiveGroupSnapshot): number {
  return snapshot.items.filter((item) => item.status === "active" && !item.stale).length;
}

export function activeGroupActivityLabel(item: ActiveGroupSummary): string {
  if (item.status !== "active") return "상태 확인 필요";
  const labels: Record<string, string> = {
    planning: "기획 작업 중", task: "Task 실행 중", verification: "검증 중",
    integration: "통합·복구 중", push: "Push 중", deployment: "배포 중", maintenance: "작업 처리 중",
  };
  return item.activity_kinds.map((kind) => labels[kind] || "작업 처리 중").join(" · ") || "작업 처리 중";
}
