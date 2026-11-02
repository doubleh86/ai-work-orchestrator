import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";
import type { RunState, WorkTask } from "./types";
import { createPlanDraft, discardUntouchedTaskDraft, planDraftDirty, reconcilePlanDraft, type PlanDraft } from "./planDrafts";
import { runRequestKey } from "./runExecutionControl";

export function usePlanDrafts(projectName: string, runId: string, run?: RunState) {
  const [drafts, setDrafts] = useState<Record<string, PlanDraft>>({});
  const key = runRequestKey(projectName, runId);
  const current = useRef({ key, run });
  current.current = { key, run };
  const draft = run ? reconcilePlanDraft(drafts[key], run) : undefined;

  useEffect(() => {
    if (!run) return;
    setDrafts((all) => {
      const next = reconcilePlanDraft(all[key], run);
      return next === all[key] ? all : { ...all, [key]: next };
    });
  }, [key, run]);

  const setField = useCallback(<K extends keyof PlanDraft>(field: K, value: SetStateAction<PlanDraft[K]>) => {
    const { key: target, run: snapshot } = current.current;
    if (!snapshot) return;
    setDrafts((all) => {
      const previous = reconcilePlanDraft(all[target], snapshot);
      const nextValue = typeof value === "function"
        ? (value as (old: PlanDraft[K]) => PlanDraft[K])(previous[field]) : value;
      return { ...all, [target]: { ...previous, [field]: nextValue } };
    });
  }, []);

  const acceptSaved = useCallback((project: string, saved: RunState) => {
    const target = runRequestKey(project, saved.id);
    setDrafts((all) => ({ ...all, [target]: createPlanDraft(saved, all[target]?.selectedTaskId) }));
  }, []);

  const discardUntouchedTask = useCallback((project: string, groupId: string, emptyTask: WorkTask) => {
    const target = runRequestKey(project, groupId);
    const { key: active, run: snapshot } = current.current;
    if (target !== active || !snapshot || snapshot.id !== groupId) return;
    setDrafts((all) => {
      const previous = reconcilePlanDraft(all[target], snapshot);
      const next = discardUntouchedTaskDraft(previous, snapshot, emptyTask);
      return next === previous ? all : { ...all, [target]: next };
    });
  }, []);

  const dirtyCount = Object.values({ ...drafts, ...(draft ? { [key]: draft } : {}) }).filter(planDraftDirty).length;
  useEffect(() => {
    if (!dirtyCount) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirtyCount]);

  return { draft, setField, acceptSaved, discardUntouchedTask, dirtyCount };
}
