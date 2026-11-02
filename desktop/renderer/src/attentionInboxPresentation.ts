import { runNextAction } from "./runNextAction";
import type { AttentionItem, AttentionSnapshot, RunState } from "./types";

export function attentionItemKey(item: AttentionItem): string {
  return JSON.stringify([item.project_name, item.run_id, item.kind]);
}

export function uncertainAttentionSnapshot(snapshot: AttentionSnapshot): AttentionSnapshot {
  return { ...snapshot, items: snapshot.items.map((item) => ({ ...item, status: "check_required", stale: true })) };
}

export function reconcileAttentionItems(previous: AttentionSnapshot, incoming: AttentionSnapshot): AttentionSnapshot {
  const failed = new Set(incoming.errors.map((item) => item.project_name));
  const retained = uncertainAttentionSnapshot({ ...previous, items: previous.items.filter((item) => failed.has(item.project_name)) });
  const items = new Map([...retained.items, ...incoming.items].map((item) => [attentionItemKey(item), item]));
  return { ...incoming, items: [...items.values()] };
}

export function confirmedAttentionCount(snapshot: AttentionSnapshot): number {
  return snapshot.items.filter((item) => item.status === "actionable" && !item.stale).length;
}

export function attentionNavigation(item: AttentionItem, latest: RunState): {
  view: "tasks" | "planning" | "operations";
  taskId: string;
  changed: boolean;
} {
  const needsRedirect = item.stage !== latest.stage || item.stale === true;
  const changed = needsRedirect || item.status === "check_required";
  const next = runNextAction(latest, { planDirty: false, pendingAction: "" });
  const view = needsRedirect
    ? next.kind === "planning" ? "planning" : next.kind === "operations" ? "operations" : "tasks"
    : item.view;
  return { view, taskId: view === "tasks" && latest.tasks.some((task) => task.id === item.task_id) ? item.task_id : "", changed };
}
