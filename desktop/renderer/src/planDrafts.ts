import type { RunState, WorkTask } from "./types";

export interface TaskProfileSelection {
  agentId: string;
  model: string;
  reasoningEffort: string;
}

export interface TaskEditorInput {
  id: string;
  commands: string;
  capabilities: string;
  acceptance_criteria: string;
  dependencies: string;
  expected_paths: string;
  forbidden_paths: string;
}

export interface TaskDependencyOption {
  id: string;
  title: string;
  selected: boolean;
}

export interface TaskDraftError {
  taskId: string;
  field: "id" | "title" | "description" | "capabilities" | "acceptance_criteria" | "expected_paths" | "commands";
  message: string;
}

export function taskEditorInput(task: WorkTask): TaskEditorInput {
  return {
    id: task.id, commands: JSON.stringify(task.verify_commands, null, 2),
    capabilities: task.capabilities.join("\n"), acceptance_criteria: task.acceptance_criteria.join("\n"),
    dependencies: task.dependencies.join("\n"), expected_paths: task.expected_paths.join("\n"),
    forbidden_paths: task.forbidden_paths.join("\n"),
  };
}

export function parseDraftCommands(value: string): { commands?: string[][]; error: string } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed) || !parsed.every((command): command is string[] =>
      Array.isArray(command) && command.length > 0
      && command.every((argument) => typeof argument === "string" && argument.trim()))) {
      return { error: "argv 문자열 배열의 배열이어야 합니다." };
    }
    return { commands: parsed, error: "" };
  } catch {
    return { error: "JSON 입력이 완성되지 않았거나 형식이 올바르지 않습니다." };
  }
}

export function taskDependencyOptions(tasks: WorkTask[], currentTaskId: string, value: string): TaskDependencyOption[] {
  const selected = new Set(draftDependencyIds(value));
  return tasks.filter((candidate) => candidate.id !== currentTaskId).map((candidate) => ({
    id: candidate.id,
    title: candidate.title || "제목 없는 작업",
    selected: selected.has(candidate.id),
  }));
}

export function unresolvedDraftDependencies(tasks: WorkTask[], value: string): string[] {
  const known = new Set(tasks.map((task) => task.id));
  return draftDependencyIds(value).filter((dependency) => !known.has(dependency));
}

export function toggleDraftDependency(value: string, dependencyId: string, selected: boolean): string {
  const dependencies = draftDependencyIds(value).filter((dependency) => dependency !== dependencyId);
  if (selected) dependencies.push(dependencyId);
  return dependencies.join("\n");
}

export function planTasksSignature(tasks: WorkTask[], profiles: Record<string, TaskProfileSelection>): string {
  return JSON.stringify(tasks.map((task) => ({
    id: task.id, title: task.title, description: task.description, capabilities: task.capabilities,
    acceptanceCriteria: task.acceptance_criteria, dependencies: task.dependencies, isPrerequisite: task.is_prerequisite,
    expectedPaths: task.expected_paths, forbiddenPaths: task.forbidden_paths, verifyCommands: task.verify_commands,
    riskLevel: task.risk_level,
    profile: profiles[task.id]
      ? { ...profiles[task.id], selectionConfirmed: true }
      : { agentId: task.agent_id, model: task.model, reasoningEffort: task.reasoning_effort },
  })));
}

export interface PlanDraft {
  baseRevision: string;
  baseSignature: string;
  tasks: WorkTask[];
  profiles: Record<string, TaskProfileSelection>;
  inputs: Record<string, TaskEditorInput>;
  selectedTaskId: string;
}

export function createPlanDraft(run: RunState, selectedTaskId = ""): PlanDraft {
  return {
    baseRevision: String(run.plan_revision || ""), baseSignature: planTasksSignature(run.tasks, {}),
    tasks: structuredClone(run.tasks), profiles: {}, inputs: {},
    selectedTaskId: run.tasks.some((task) => task.id === selectedTaskId) ? selectedTaskId : run.tasks[0]?.id || "",
  };
}

export function planDraftDirty(draft: PlanDraft): boolean {
  return planTasksSignature(draft.tasks, draft.profiles) !== draft.baseSignature
    || draft.tasks.some((task) => {
      const input = draft.inputs[task.id];
      return input && JSON.stringify(input) !== JSON.stringify(taskEditorInput(task));
    });
}

export function reconcilePlanDraft(draft: PlanDraft | undefined, run: RunState): PlanDraft {
  if (!draft) return createPlanDraft(run);
  if (planDraftDirty(draft)) return draft;
  if (draft.baseRevision === String(run.plan_revision || "") && JSON.stringify(draft.tasks) === JSON.stringify(run.tasks)) return draft;
  return createPlanDraft(run, draft.selectedTaskId);
}

export function planDraftConflict(draft: PlanDraft, run: RunState): boolean {
  return planDraftDirty(draft) && (draft.baseRevision !== String(run.plan_revision || "")
    || draft.baseSignature !== planTasksSignature(run.tasks, {}));
}

export function canDiscardUntouchedTaskDraft(draft: PlanDraft, run: RunState, emptyTask: WorkTask): boolean {
  if (run.stage !== "planned" || run.tasks.some((task) => task.id === emptyTask.id)) return false;
  const task = draft.tasks.find((candidate) => candidate.id === emptyTask.id);
  if (!task || JSON.stringify(task) !== JSON.stringify(emptyTask) || draft.profiles[task.id]) return false;
  const input = draft.inputs[task.id];
  if (input && JSON.stringify(input) !== JSON.stringify(taskEditorInput(emptyTask))) return false;
  return !draft.tasks.some((candidate) => candidate.id !== task.id && (
    candidate.dependencies.includes(task.id) || candidate.conflict_dependencies.includes(task.id)
    || draft.inputs[candidate.id]?.dependencies.split(/\r?\n/).some((line) => line.trim() === task.id)
  ));
}

export function discardUntouchedTaskDraft(draft: PlanDraft, run: RunState, emptyTask: WorkTask): PlanDraft {
  if (!canDiscardUntouchedTaskDraft(draft, run, emptyTask)) return draft;
  const tasks = draft.tasks.filter((task) => task.id !== emptyTask.id);
  const inputs = { ...draft.inputs };
  delete inputs[emptyTask.id];
  return { ...draft, tasks, inputs, selectedTaskId: draft.selectedTaskId === emptyTask.id
    ? tasks[0]?.id || "" : draft.selectedTaskId };
}

export function planDraftErrors(draft: PlanDraft): TaskDraftError[] {
  return draft.tasks.flatMap((task) => {
    const input = draft.inputs[task.id] || taskEditorInput(task);
    const errors: TaskDraftError[] = [];
    if (!input.id.trim() || input.id.trim() !== task.id) errors.push({ taskId: task.id, field: "id", message: "Task ID 입력을 완료해 주세요." });
    if (!task.title.trim()) errors.push({ taskId: task.id, field: "title", message: requiredFieldMessage("title") });
    if (!task.description.trim()) errors.push({ taskId: task.id, field: "description", message: requiredFieldMessage("description") });
    for (const field of ["capabilities", "acceptance_criteria", "expected_paths"] as const) {
      if (!input[field].split("\n").some((line) => line.trim())) errors.push({ taskId: task.id, field, message: requiredFieldMessage(field) });
    }
    const parsed = parseDraftCommands(input.commands);
    const commandError = parsed.error || (parsed.commands?.length ? "" : requiredFieldMessage("commands"));
    if (commandError) errors.push({ taskId: task.id, field: "commands", message: commandError });
    return errors;
  });
}

function requiredFieldMessage(field: TaskDraftError["field"]): string {
  const labels: Record<TaskDraftError["field"], string> = {
    id: "Task ID", title: "제목", description: "설명", capabilities: "작업 역량", acceptance_criteria: "완료 조건",
    expected_paths: "예상 변경 경로", commands: "검증 명령",
  };
  return `${labels[field]} 입력이 필요합니다.${["capabilities", "acceptance_criteria", "expected_paths", "commands"].includes(field) ? " 한 개 이상 작성해 주세요." : ""}`;
}

export function taskDraftErrorIsAdvanced(field: TaskDraftError["field"]): boolean {
  return ["id", "capabilities", "expected_paths", "commands"].includes(field);
}

export function taskDraftErrorSummary(error: TaskDraftError, tasks: WorkTask[]): string {
  const task = tasks.find((candidate) => candidate.id === error.taskId);
  return `${task?.title.trim() || "제목 없는 작업"} (${error.taskId}) · ${error.message}`;
}

export function taskPlanFailure(message: string, tasks: WorkTask[]): TaskDraftError | undefined {
  const match = message.match(/invalid task plan: task ([^\s]+) (title|description|capabilities|acceptance_criteria|expected_paths|verify_commands) must (?:not be empty|be a non-empty string|be an array of non-empty strings|be a non-empty array of commands)(?:$|[\r\n])/u);
  if (!match || !tasks.some((task) => task.id === match[1])) return undefined;
  const field = match[2] === "verify_commands" ? "commands" : match[2] as TaskDraftError["field"];
  return { taskId: match[1], field, message: requiredFieldMessage(field) };
}

function draftDependencyIds(value: string): string[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}
