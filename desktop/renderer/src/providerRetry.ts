/** Read-only presentation of a scheduled provider retry, never dispatches requests. */
export function providerRetryWait(phase: string, detail: string, now = Date.now()): string | undefined {
  if (phase !== "provider_retry_wait") return undefined;
  try {
    const value: unknown = JSON.parse(detail);
    if (!value || typeof value !== "object" || !("retry_at" in value) || !("retry_index" in value) || !("max_retries" in value)
      || typeof value.retry_at !== "string" || typeof value.retry_index !== "number" || typeof value.max_retries !== "number"
      || !Number.isInteger(value.retry_index) || !Number.isInteger(value.max_retries)
      || value.retry_index < 1 || value.retry_index > value.max_retries || value.max_retries !== 4) return "AI 서버 혼잡 · 재시도 상태 확인 중";
    const due = Date.parse(value.retry_at);
    if (!Number.isFinite(due)) return "AI 서버 혼잡 · 재시도 상태 확인 중";
    const seconds = Math.max(0, Math.ceil((due - now) / 1000));
    return `AI 서버 혼잡 · ${seconds ? `${seconds}초 후 재시도` : "재시도 준비 중"} (${value.retry_index}/${value.max_retries})`;
  } catch { return "AI 서버 혼잡 · 재시도 상태 확인 중"; }
}
