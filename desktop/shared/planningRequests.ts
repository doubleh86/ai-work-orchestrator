export type PlanningRequestKind = "plan" | "replan" | "chat" | "archived_chat";
export const PLANNING_REQUEST_METHODS = [
  "runs.decideProjectChat",
  "planning.refreshIndex", "planning.generateFeaturePlan", "runs.preparePlanning", "runs.proposeResultRevision",
  "runs.createResultRevision", "runs.runPlanning", "runs.start", "runs.sendPlanningMessage", "runs.previewPlanningApply",
  "runs.applyPlanningPreview", "runs.applyPlanningConversation", "runs.confirmTechStack", "runs.configureBootstrapInstructions",
] as const;
export interface PlanningRequestOwner {
  projectName: string;
  runId: string;
  requestId: string;
  kind: PlanningRequestKind;
  method: string;
  phase: "accepted" | "running" | "stopping" | "succeeded" | "failed" | "interrupted" | "confirmation_required";
  startedAt: number;
  error: string;
}
export interface PlanningRequestsSnapshot {
  active?: PlanningRequestOwner;
  recent: PlanningRequestOwner[];
  messageQueue?: import("./planningMessageQueue").PlanningMessageQueueSnapshot;
}
