import type { CodeStyleCheck, CodeStyleRule, CodeStyleSnapshot, CodeStyleTaskEvidence } from "./types";

const statusLabels: Record<string, string> = {
  detected: "저장소 코드 스타일을 적용합니다",
  partial: "일부 언어만 설정됨",
  unspecified: "코드 스타일 규칙 없음",
  conflict: "코드 스타일 규칙 확인 필요",
  unavailable: "코드 스타일을 확인하지 못했습니다",
};

const languageLabels: Record<string, string> = {
  all: "공통",
  csharp: "C#",
  go: "Go",
  javascript: "JavaScript",
  python: "Python",
  rust: "Rust",
  typescript: "TypeScript",
};

const standardLabels: Record<string, string> = {
  repository_instructions: "저장소 지침",
  editorconfig: ".editorconfig",
  pep8: "PEP 8",
  microsoft_dotnet: "Microsoft C#/.NET",
  dotnet_code_style: ".NET code style",
  dotnet_analyzers: ".NET analyzer",
  stylecop: "StyleCop",
  ruff: "Ruff",
  black: "Black",
  flake8: "Flake8",
  eslint: "ESLint",
  prettier: "Prettier",
  custom_instruction: "사용자 지침",
};

export function codeStyleStatusLabel(status: string): string {
  return statusLabels[status] || status;
}

export function codeStyleLanguageLabel(language: string): string {
  return languageLabels[language] || language;
}

export function codeStyleRuleSummary(rule: CodeStyleRule): string {
  const standard = standardLabels[rule.standard_id] || rule.standard_id;
  const source = rule.source_path || "보조 기본값";
  return `${codeStyleLanguageLabel(rule.language)} · ${standard} · ${source}`;
}

export function codeStyleSnapshotSummary(snapshot: CodeStyleSnapshot | null | undefined): string {
  if (!snapshot) return "snapshot 없음";
  const languages = snapshot.detected_languages.map(codeStyleLanguageLabel).join(", ") || "감지 언어 없음";
  return `${codeStyleStatusLabel(snapshot.status)} · ${languages} · 규칙 ${snapshot.rules.length}개 · 검사 ${snapshot.checks.length}개`;
}

export function styleCheckPurpose(command: string[], checks: CodeStyleCheck[] | undefined): string {
  if (!checks?.some((check) => check.argv.length === command.length && check.argv.every((part, index) => part === command[index]))) {
    return "검증";
  }
  return "코드 스타일";
}

export function taskCodeStyleEvidenceSummary(evidence: CodeStyleTaskEvidence | null | undefined): string {
  if (!evidence) return "기록 없음";
  const ruleState = evidence.rules_changed ? `snapshot과 차이 ${evidence.rule_changes.length}개` : "snapshot과 동일";
  return `적용 규칙 ${evidence.applicable_rules.length}개 · ${ruleState}`;
}

export function taskCodeStyleCheckSummary(evidence: CodeStyleTaskEvidence | null | undefined): string {
  if (!evidence?.checks.length) return "연결된 검사 없음";
  const counts = evidence.checks.reduce<Record<string, number>>((result, check) => {
    result[check.last_result] = (result[check.last_result] || 0) + 1;
    return result;
  }, {});
  const labels: Record<string, string> = { passed: "통과", failed: "실패", unavailable: "실행 불가", not_run: "미실행" };
  return Object.entries(counts).map(([status, count]) => `${labels[status] || status} ${count}개`).join(" · ");
}

export function taskCodeStyleCheckDetail(check: CodeStyleCheck): string {
  const labels: Record<string, string> = { passed: "통과", failed: "실패", unavailable: "실행 불가", not_run: "미실행" };
  return `${codeStyleLanguageLabel(check.language)} · ${check.argv.join(" ")} · ${labels[check.last_result] || check.last_result} · ${check.source_path || "출처 기록 없음"}`;
}
