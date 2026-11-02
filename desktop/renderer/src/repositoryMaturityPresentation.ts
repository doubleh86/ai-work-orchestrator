import type { PlanningMode, RepositoryMaturityAssessment } from "./types";

export type RepositoryIntent = "" | "existing_structure" | "new_project";

export interface RepositoryEvidenceGroup {
  label: "코드 파일" | "프로젝트 설정 파일" | "기획 문서" | "확인하지 못한 이유";
  count: number;
  paths: string[];
  notes: string[];
}

export function planningStartLabel(
  maturity: RepositoryMaturityAssessment["kind"] | undefined,
  intent: RepositoryIntent,
  mode: PlanningMode,
): string {
  if (maturity === "docs_only") return "기술 스택 추천받기";
  if (maturity === "ambiguous" && intent === "existing_structure") return "현재 코드로 계획 만들기";
  if (maturity === "ambiguous" && intent === "new_project") return "기본 구조 계획 만들기";
  return mode === "directed" ? "지정 작업 계획" : "풀 오토 계획";
}

export function repositoryEvidenceGroups(assessment: RepositoryMaturityAssessment): RepositoryEvidenceGroup[] {
  const definitions = [
    { label: "코드 파일" as const, kinds: new Set(["source", "test"]) },
    { label: "프로젝트 설정 파일" as const, kinds: new Set(["manifest", "build"]) },
    { label: "기획 문서" as const, kinds: new Set(["document"]) },
  ];
  const groups: RepositoryEvidenceGroup[] = definitions.map(({ label, kinds }) => {
    const matches = assessment.evidence.filter((item) => kinds.has(item.evidence_kind));
    return { label, count: matches.length, paths: matches.slice(0, 5).map((item) => item.relative_path), notes: [] };
  }).filter((group) => group.count > 0);
  const unknown = assessment.evidence.filter((item) => ["unknown", "generated"].includes(item.evidence_kind));
  const notes: string[] = [];
  if (assessment.truncated) notes.push("확인할 파일이 많아 일부만 살펴봤습니다.");
  if (assessment.detected_application_roots.length > 1) notes.push("여러 위치에서 프로젝트 단서를 찾아 시작점을 하나로 정하지 못했습니다.");
  if (unknown.length) notes.push("종류를 판단하기 어려운 파일이 있습니다.");
  if (assessment.kind === "ambiguous" && !notes.length) notes.push("프로젝트 설정과 코드가 함께 있는지 확실히 확인하지 못했습니다.");
  if (unknown.length || notes.length) {
    groups.push({
      label: "확인하지 못한 이유",
      count: Math.max(unknown.length, notes.length),
      paths: unknown.slice(0, 5).map((item) => item.relative_path),
      notes,
    });
  }
  return groups;
}
