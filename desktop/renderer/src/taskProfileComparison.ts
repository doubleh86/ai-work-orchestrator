export interface TaskProfileBasis {
  profile_source?: "manual" | "mode" | "routing" | "legacy";
  model_selection_reason?: string;
  agent_id: string;
  model: string;
  reasoning_effort: string;
  provider_id: string;
}

export interface TaskProfileSelectionValue {
  agentId: string;
  model: string;
  reasoningEffort: string;
}

export interface TaskProfileOptionValue {
  agent_id: string;
  model: string;
  provider_id: string;
}

export interface TaskProfileComparison {
  changed: boolean;
  originLabel: string;
  selectedSummary: string;
  recommendedSummary: string;
}

function profileSummary(model: string, effort: string, provider: string): string {
  const modelLabel = model || "자동 모델";
  const effortLabel = effort || "자동 추론";
  return `${modelLabel} · ${effortLabel} · ${provider || "AI 제공자"}`;
}

export function taskProfileComparison(
  task: TaskProfileBasis,
  selection: TaskProfileSelectionValue,
  selectedProvider: string,
  recommendedProvider: string,
): TaskProfileComparison {
  const changed = selection.agentId !== task.agent_id
    || selection.model !== task.model
    || selection.reasoningEffort !== task.reasoning_effort;
  return {
    changed,
    originLabel: changed || task.profile_source === "manual" ? "사용자 선택 · 실행 전"
      : task.model_selection_reason ? "자동 선택 · 실행 전" : "기획 AI 추천 · 실행 전",
    selectedSummary: profileSummary(selection.model, selection.reasoningEffort, selectedProvider),
    recommendedSummary: profileSummary(task.model, task.reasoning_effort, recommendedProvider),
  };
}

export function taskProfileOptionLabel(label: string, recommended: boolean): string {
  return recommended ? `${label} · 추천` : label;
}

export function taskProfileRequiresReselection(
  task: TaskProfileBasis & { reviewer_provider_id?: string; status?: string },
  selection: TaskProfileSelectionValue | undefined,
  options: TaskProfileOptionValue[],
): boolean {
  if (task.status && task.status !== "pending") return false;
  if (task.provider_id !== "claude" && task.reviewer_provider_id !== "claude") return false;
  const current = selection || { agentId: task.agent_id, model: task.model };
  return !options.some((option) => (
    option.agent_id === current.agentId
    && option.model === current.model
  ));
}
