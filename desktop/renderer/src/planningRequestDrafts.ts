import type { EffortMode, PlanningMode, ProviderProfile, RepositoryMaturityKind } from "./types";

export interface PlanningRequestDraft {
  path: string;
  mode: PlanningMode;
  request: string;
  effortMode: EffortMode;
  profileKey: string;
  reasoning: string;
  profileManual: boolean;
  repositoryIntent: "" | "existing_structure" | "new_project";
}

export function planningRepositoryIntent(
  maturity: RepositoryMaturityKind | undefined, intent: PlanningRequestDraft["repositoryIntent"],
): PlanningRequestDraft["repositoryIntent"] {
  if (maturity === "docs_only") return "new_project";
  if (maturity === "existing_code" && !intent) return "existing_structure";
  return intent;
}

export class PlanningRequestDrafts {
  private readonly drafts = new Map<string, PlanningRequestDraft>();

  load(projectName: string, path = "", repositoryIntent: PlanningRequestDraft["repositoryIntent"] = ""): PlanningRequestDraft {
    const saved = this.drafts.get(projectName);
    if (saved) return { ...saved };
    const initial: PlanningRequestDraft = {
      path, mode: "directed", request: "", effortMode: "balanced", profileKey: "", reasoning: "", profileManual: false, repositoryIntent,
    };
    this.drafts.set(projectName, initial);
    return { ...initial };
  }

  update(projectName: string, patch: Partial<PlanningRequestDraft>): PlanningRequestDraft {
    const updated = { ...this.load(projectName), ...patch };
    this.drafts.set(projectName, updated);
    return { ...updated };
  }
}

export function initialPlanningProfileParams(profile: ProviderProfile | undefined, reasoning: string, manual: boolean) {
  return {
    planningAgentId: profile?.agent_id || "",
    planningModel: profile?.model || "",
    planningReasoningEffort: reasoning,
    planningProfileSource: manual ? "manual" : "routing",
  };
}

export function planningMessageProfileParams(profile: ProviderProfile | undefined, reasoning: string, edited: boolean) {
  return edited ? {
    planningAgentId: profile?.agent_id || "", planningModel: profile?.model || "", planningReasoningEffort: reasoning,
  } : {};
}
