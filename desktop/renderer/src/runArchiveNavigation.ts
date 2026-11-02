import type { RunListScope } from "./runArchiveCache";

export interface ArchiveNavigationContext {
  projectName: string;
  runId: string;
  scope: RunListScope;
}

export function archiveCompletionView(
  requested: ArchiveNavigationContext,
  current: ArchiveNavigationContext,
): "operations" | null {
  return current.projectName === requested.projectName
    && current.runId === requested.runId
    && current.scope === requested.scope
    ? "operations"
    : null;
}

export function selectedRunView(scope: RunListScope): "tasks" | "operations" {
  return scope === "archived" ? "operations" : "tasks";
}
