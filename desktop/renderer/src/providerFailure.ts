export const modelCapacityMessage = "선택한 AI 모델이 혼잡합니다";

/** Use confirmed error text only; a status code or the word capacity is insufficient. */
export function isModelCapacityFailure(error: string): boolean {
  return error.includes(`${modelCapacityMessage}.`)
    || error.toLowerCase().includes("selected model is at capacity. please try a different model.");
}

/** Presentation of saved provider failures; never grants retry or changes execution state. */
export function providerFailurePresentation(error: string): {
  kind: "capacity" | "rate" | "usage" | "unavailable"; label: string; title: string; description: string;
} | undefined {
  if (error.includes("AI 사용 한도에 도달했습니다.")
    || /\b(?:usageLimitExceeded|usage_limit_exceeded|insufficient_quota|credit_balance_exhausted|organization_spend_limit_exceeded|project_spend_limit_exceeded|organization_usage_limit_exceeded)\b/i.test(error)
    || /\byou(?:'ve| have) (?:hit|reached) your usage limit\b|\byou exceeded your current quota\b/i.test(error)) return {
    kind: "usage", label: "AI 사용 한도", title: "AI 사용 한도에 도달했습니다",
    description: "AI 사용 한도와 갱신 시점을 확인한 뒤 다시 시도해 주세요.",
  };
  if (error.includes("AI 요청이 제한되었습니다.")
    || /\bexceeded retry limit,\s*last status:\s*429\b/i.test(error)
    || /\b(?:rateLimitExceeded|rate_limit_exceeded|rate_limit_error|slow_down)\b/i.test(error)
    || /Codex SDK failed:/i.test(error) && /\brate limit (?:reached|exceeded)\b|\b(?:last status:\s*|HTTP(?:\/\d(?:\.\d)?)?\s+)429\b|\b429\s+Too Many Requests\b/i.test(error)) return {
    kind: "rate", label: "AI 요청 제한", title: "AI 요청이 제한되었습니다",
    description: "잠시 후 다시 시도해 주세요.",
  };
  if (isModelCapacityFailure(error)) return {
    kind: "capacity", label: "AI 모델 혼잡", title: modelCapacityMessage,
    description: "잠시 후 해당 작업만 다시 시도해 주세요. 모델은 기존 실행 설정에서 변경할 수 있습니다.",
  };
  if (error.includes("AI 서버가 일시적으로 응답하지 않습니다.")) return {
    kind: "unavailable", label: "AI 서버 일시 오류", title: "AI 서버가 일시적으로 응답하지 않습니다",
    description: "잠시 후 해당 작업만 다시 시도해 주세요.",
  };
  return undefined;
}
