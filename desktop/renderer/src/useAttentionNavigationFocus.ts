import { useEffect, useRef, type RefObject } from "react";

export interface AttentionFocusRequest {
  projectName: string;
  runId: string;
  view: "tasks" | "planning" | "operations";
  taskId: string;
  kind: string;
  waitingSourceKey: string;
}

export interface AttentionFocusContext {
  projectName: string;
  runId: string;
  view: string;
  taskId: string;
  waitingSourceKey: string;
  inspectorTitleId: string;
}

export function attentionFocusMatches(request: AttentionFocusRequest, context: AttentionFocusContext): boolean {
  return request.projectName === context.projectName && request.runId === context.runId
    && request.view === context.view && (!request.taskId || request.taskId === context.taskId);
}

export function attentionFocusTarget(
  root: HTMLElement, request: AttentionFocusRequest, context: AttentionFocusContext,
): HTMLElement | undefined {
  if (!attentionFocusMatches(request, context) || root.dataset.attentionProject !== request.projectName
    || root.dataset.attentionRun !== request.runId) return undefined;
  const visible = (element: HTMLElement | null): HTMLElement | undefined =>
    element?.getClientRects().length ? element : undefined;
  const heading = (id: string) => {
    const element = root.ownerDocument.getElementById(id);
    return element && root.contains(element) ? visible(element) : undefined;
  };
  if (request.view === "planning") {
    return (request.kind === "planning_questions" ? visible(root.querySelector<HTMLElement>("[data-attention-question]")) : undefined)
      || heading("planning-workbench-title");
  }
  if (request.waitingSourceKey && request.waitingSourceKey === context.waitingSourceKey) {
    const waiting = root.querySelector<HTMLElement>("[data-attention-waiting]");
    if (waiting?.dataset.attentionWaiting === request.waitingSourceKey && visible(waiting)) return waiting;
  }
  if (request.view === "tasks" && request.taskId) {
    const detail = heading(context.inspectorTitleId);
    if (detail) return detail;
  }
  // A changed waiting source must not redirect focus to another question's action.
  return (!request.waitingSourceKey || request.waitingSourceKey === context.waitingSourceKey
    ? visible(root.querySelector<HTMLElement>("[data-attention-action]")) : undefined)
    || heading(`${request.view}-workbench-title`);
}

export function useAttentionNavigationFocus(
  request: AttentionFocusRequest | undefined, context: AttentionFocusContext, root: RefObject<HTMLElement | null>,
): void {
  const consumed = useRef<AttentionFocusRequest | undefined>(undefined);
  const latest = useRef({ request, context });
  latest.current = { request, context };
  useEffect(() => {
    if (!request || consumed.current === request) return;
    if (!attentionFocusMatches(request, context)) {
      consumed.current = request;
      return;
    }
    // Run after the navigation render and existing scroll restoration effects.
    const frame = window.requestAnimationFrame(() => {
      if (consumed.current === request || latest.current.request !== request) return;
      consumed.current = request;
      if (!root.current
        || root.current.ownerDocument.querySelector("dialog[open], [aria-modal='true']")) return;
      const target = attentionFocusTarget(root.current, request, latest.current.context);
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [request, context.projectName, context.runId, context.view, context.taskId,
    context.waitingSourceKey, context.inspectorTitleId, root]);
}
