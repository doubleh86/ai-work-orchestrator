import type { WorkTask } from "./types";

export interface TaskDependencyLink {
  id: string;
  title: string;
  status: string;
  available: boolean;
  blocked: boolean;
}

export interface TaskDependencySection {
  kind: "declared" | "inferred" | "conflict";
  title: string;
  items: TaskDependencyLink[];
}

export function taskDependencySections(task: WorkTask, tasks: WorkTask[]): TaskDependencySection[] {
  const byId = new Map(tasks.map((candidate) => [candidate.id, candidate]));
  const blockedBy = new Set(task.blocked_by);
  const links = (ids: string[], blocking: boolean, excludeCurrent = false): TaskDependencyLink[] => [...new Set(ids.filter((id) => id && (!excludeCurrent || id !== task.id)))].map((id) => {
    const dependency = byId.get(id);
    return {
      id,
      title: dependency?.title || (dependency ? "제목 없는 작업" : "확인 불가"),
      status: dependency?.status || "",
      available: Boolean(dependency),
      blocked: blocking && blockedBy.has(id),
    };
  });
  const declared = new Set(task.dependencies);
  const sections: TaskDependencySection[] = [
    { kind: "declared", title: "선행 작업", items: links(task.dependencies, true) },
    { kind: "inferred", title: "자동 선행 작업", items: links(task.conflict_dependencies.filter((id) => !declared.has(id)), true) },
    { kind: "conflict", title: "충돌 가능 그룹", items: links(task.conflict_group, false, true) },
  ];
  return sections.filter((section) => section.items.length > 0);
}
