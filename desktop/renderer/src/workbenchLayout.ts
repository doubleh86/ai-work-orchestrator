export type WorkbenchLayout = "wide" | "medium" | "compact" | "single";
export type TaskContentView = "list" | "detail" | "log" | "events";
export type MobileWorkbenchPane = "groups" | "workbench";

export interface WorkbenchLayoutInput {
  viewportWidth: number;
  groupPaneWidth: number;
  inspectorWidth: number;
  previous?: WorkbenchLayout;
}

const SINGLE_MAX = 40 * 16;
const COMPACT_MAX = 60 * 16;
const WIDE_CONTENT_MIN = 680;
const WIDE_CONTENT_RESTORE = 704;
const RESIZER_WIDTH = 8;
const TASK_HORIZONTAL_PADDING = 48;

export function expectedWideTaskContentWidth(input: WorkbenchLayoutInput): number {
  return input.viewportWidth
    - input.groupPaneWidth
    - input.inspectorWidth
    - RESIZER_WIDTH
    - TASK_HORIZONTAL_PADDING;
}

export function resolveWorkbenchLayout(input: WorkbenchLayoutInput): WorkbenchLayout {
  if (input.viewportWidth < SINGLE_MAX) return "single";
  if (input.viewportWidth < COMPACT_MAX) return "compact";
  const contentWidth = expectedWideTaskContentWidth(input);
  const threshold = input.previous === "wide" ? WIDE_CONTENT_MIN : WIDE_CONTENT_RESTORE;
  return contentWidth >= threshold ? "wide" : "medium";
}

export function taskSelectionOpensDetail(layout: WorkbenchLayout, userOpen = true): boolean {
  return userOpen && (layout === "compact" || layout === "single");
}

export function sideInspectorVisible(layout: WorkbenchLayout, userOpen: boolean): boolean {
  return layout === "wide" && userOpen;
}

export function inspectorPanelId(layout: WorkbenchLayout): string {
  return layout === "wide" ? "side-inspector" : "task-inspector";
}

export function taskViewForInspectorTab(tab: Exclude<TaskContentView, "list">): TaskContentView {
  return tab;
}

export function mobileWorkbenchPane(input: {
  layout: WorkbenchLayout;
  groupsRequested: boolean;
  hasRun: boolean;
  workbenchView: "tasks" | "planning" | "operations" | "results";
}): MobileWorkbenchPane {
  if (input.layout !== "compact" && input.layout !== "single") return "workbench";
  if (input.groupsRequested || (!input.hasRun && input.workbenchView === "tasks")) return "groups";
  return "workbench";
}
