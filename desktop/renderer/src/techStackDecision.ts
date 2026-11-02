import type { TechStackDecision, TechStackOption } from "./types";

export function activeTechStackDecision(decisions: TechStackDecision[] | undefined): TechStackDecision | undefined {
  return [...(decisions || [])].reverse().find((decision) => decision.status !== "superseded");
}

export function techStackCoreItems(option: TechStackOption): string[] {
  return [
    ...option.components.languages,
    ...option.components.runtimes,
    ...option.components.application_frameworks,
    ...option.components.ui_frameworks,
    ...option.components.persistence,
  ];
}

export function techStackDevelopmentItems(option: TechStackOption): string[] {
  return [
    ...option.components.package_and_build_tools,
    ...option.components.test_tools,
    ...option.components.style_and_analysis,
  ];
}
