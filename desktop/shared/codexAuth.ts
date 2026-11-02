export type CodexAuthStatus =
  | "signed_out"
  | "waiting"
  | "cancelling"
  | "connected"
  | "cancelled"
  | "failed"
  | "unknown"
  | "runtime_error"
  | "status_error";

export type CodexAuthMethod = "browser" | "device_code";

export interface CodexAuthState {
  status: CodexAuthStatus;
  attempt_id: string;
  method: CodexAuthMethod | "";
  started_at: string;
  auth_method: string;
  auth_label: string;
  account_email: string;
  plan_type: string;
  user_code: string;
  error_code: string;
  message: string;
  browser_open_error: string;
}

export function codexAuthIsPending(state: CodexAuthState | undefined): boolean {
  return state?.status === "waiting" || state?.status === "cancelling";
}

export function codexAccountDetails(state: CodexAuthState | undefined): { email: string; method: string; plan: string } | undefined {
  if (state?.status !== "connected") return undefined;
  if (state.auth_method === "chatgpt") return {
    email: state.account_email || "이메일 정보가 제공되지 않습니다",
    method: "ChatGPT 구독 로그인",
    plan: ({ free: "Free", go: "Go", plus: "Plus", pro: "Pro", prolite: "Pro Lite", promax: "Pro Max",
      team: "Team", business: "Business", enterprise: "Enterprise", edu: "Edu" } as Record<string, string>)[state.plan_type]
      || state.plan_type || "요금제 정보가 제공되지 않습니다",
  };
  return {
    email: state.auth_method === "api_key" ? "API 키 연결 · 계정 이메일을 제공하지 않습니다"
      : state.auth_method === "external" ? "외부 인증 · 계정 이메일을 제공하지 않습니다" : "이메일 정보가 제공되지 않습니다",
    method: state.auth_label || "로그인됨",
    plan: state.auth_method === "api_key" ? "OpenAI API 사용량에 따라 별도 과금" : "ChatGPT 요금제 정보가 제공되지 않습니다",
  };
}
