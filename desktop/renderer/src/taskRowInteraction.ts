export interface TaskRowSelectionIntent {
  defaultPrevented: boolean;
  interactiveTarget: boolean;
  textSelected: boolean;
  pointerDragged: boolean;
}

export const taskRowInteractiveSelector = [
  "button",
  "input",
  "select",
  "textarea",
  "a",
  "label",
  "[role='button']",
  "[data-task-row-control]",
].join(",");

export function shouldSelectTaskRow(intent: TaskRowSelectionIntent): boolean {
  return !intent.defaultPrevented
    && !intent.interactiveTarget
    && !intent.textSelected
    && !intent.pointerDragged;
}
