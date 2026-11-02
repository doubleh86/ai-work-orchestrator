import type { CodexAuthMethod, CodexAuthState, CodexAuthStatus } from "../shared/codexAuth";
import type { RpcMethod, RpcParams } from "../shared/rpc";

interface AuthBridge {
  request<Result>(method: RpcMethod, params?: RpcParams): Promise<Result>;
}

interface AuthHost {
  openExternal(url: string): Promise<void>;
  copyText(value: string): void;
}

interface BackendCodexAuthState extends Omit<CodexAuthState, "browser_open_error"> {
  auth_url?: string;
}

interface AttemptSecret {
  url: string;
  code: string;
  state: CodexAuthState;
}

const officialAuthHosts = new Set(["auth.openai.com", "chatgpt.com", "www.chatgpt.com"]);
const terminalStatuses = new Set<CodexAuthStatus>(["connected", "cancelled", "failed", "runtime_error", "status_error"]);

export class CodexAuthController {
  private readonly attempts = new Map<string, AttemptSecret>();

  constructor(private readonly bridge: AuthBridge, private readonly host: AuthHost) {}

  async status(): Promise<CodexAuthState> {
    return this.consume(await this.bridge.request("auth.codex.status"));
  }

  async start(method: CodexAuthMethod, requestId: string): Promise<CodexAuthState> {
    if (!requestId.trim()) throw new Error("Codex login request ID is required");
    return this.consume(
      await this.bridge.request("auth.codex.start", { method, requestId: requestId.trim() }),
      true,
    );
  }

  async get(attemptId: string): Promise<CodexAuthState> {
    return this.consume(
      await this.bridge.request("auth.codex.get", { attemptId: requiredAttemptId(attemptId) }),
    );
  }

  async connectApiKey(apiKey: string, requestId: string): Promise<CodexAuthState> {
    if (!requestId.trim() || requestId.length > 128 || /[\0\r\n]/u.test(requestId)) throw new Error("Codex login request ID is required");
    if (!apiKey.trim() || apiKey.length > 4096 || /[\0\r\n]/u.test(apiKey) || /[^\x21-\x7e]/u.test(apiKey.trim())) {
      throw new Error("OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.");
    }
    try {
      return await this.consume(await this.bridge.request("auth.codex.apiKey", { apiKey: apiKey.trim(), requestId: requestId.trim() }));
    } catch {
      throw new Error("Codex API 키 연결을 확인하지 못했습니다. 연결 상태를 다시 확인해 주세요.");
    }
  }

  async cancel(attemptId: string): Promise<CodexAuthState> {
    return this.consume(
      await this.bridge.request("auth.codex.cancel", { attemptId: requiredAttemptId(attemptId) }),
    );
  }

  async reopen(attemptId: string): Promise<CodexAuthState> {
    const selected = requiredAttemptId(attemptId);
    let secret = this.attempts.get(selected);
    if (!secret?.url) {
      await this.get(selected);
      secret = this.attempts.get(selected);
    }
    if (!secret?.url) throw new Error("다시 열 수 있는 Codex 로그인 주소가 없습니다.");
    return this.open(secret);
  }

  copyDeviceCode(attemptId: string): boolean {
    const secret = this.attempts.get(requiredAttemptId(attemptId));
    if (!secret?.code) return false;
    this.host.copyText(secret.code);
    return true;
  }

  clear(): void {
    this.attempts.clear();
  }

  private async consume(raw: unknown, openBrowser = false): Promise<CodexAuthState> {
    const backend = parseBackendState(raw);
    const previousBrowserError = backend.attempt_id && !terminalStatuses.has(backend.status)
      ? this.attempts.get(backend.attempt_id)?.state.browser_open_error || ""
      : "";
    const state: CodexAuthState = {
      status: backend.status,
      attempt_id: backend.attempt_id,
      method: backend.method,
      started_at: backend.started_at,
      auth_method: backend.auth_method,
      auth_label: backend.auth_label,
      account_email: backend.account_email,
      plan_type: backend.plan_type,
      user_code: backend.user_code,
      error_code: backend.error_code,
      message: backend.message,
      browser_open_error: previousBrowserError,
    };
    let invalidUrl = false;
    const url = backend.auth_url?.trim() || "";
    if (state.attempt_id && (url || state.user_code)) {
      if (url && !isOfficialAuthUrl(url)) invalidUrl = true;
      this.attempts.set(state.attempt_id, {
        url: invalidUrl ? "" : url,
        code: state.user_code,
        state,
      });
    }
    if (terminalStatuses.has(state.status) && state.attempt_id) this.attempts.delete(state.attempt_id);
    if (invalidUrl) return { ...state, browser_open_error: "공식 Codex 로그인 주소를 확인하지 못했습니다." };
    if (openBrowser && state.attempt_id) {
      const secret = this.attempts.get(state.attempt_id);
      if (secret?.url) return this.open(secret);
    }
    return state;
  }

  private async open(secret: AttemptSecret): Promise<CodexAuthState> {
    try {
      await this.host.openExternal(secret.url);
      return { ...secret.state, browser_open_error: "" };
    } catch {
      const state = { ...secret.state, browser_open_error: "기본 브라우저를 열지 못했습니다. 다시 열기를 시도하세요." };
      this.attempts.set(state.attempt_id, { ...secret, state });
      return state;
    }
  }
}

export function isOfficialAuthUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:"
      && (!parsed.port || parsed.port === "443")
      && officialAuthHosts.has(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
}

function requiredAttemptId(value: string): string {
  const selected = value.trim();
  if (!selected || selected.length > 128 || /[\0\r\n]/u.test(selected)) throw new Error("Codex login attempt ID is required");
  return selected;
}

function parseBackendState(raw: unknown): BackendCodexAuthState {
  if (!raw || typeof raw !== "object") throw new Error("Codex 로그인 상태 응답이 올바르지 않습니다.");
  const value = raw as Record<string, unknown>;
  const status = singleLine(value.status);
  const allowedStatuses = new Set<CodexAuthStatus>([
    "signed_out", "waiting", "cancelling", "connected", "cancelled", "failed", "unknown", "runtime_error", "status_error",
  ]);
  if (!allowedStatuses.has(status as CodexAuthStatus)) throw new Error("Codex 로그인 상태 응답이 올바르지 않습니다.");
  const method = singleLine(value.method);
  if (method && method !== "browser" && method !== "device_code") throw new Error("Codex 로그인 방식 응답이 올바르지 않습니다.");
  const attemptId = singleLine(value.attempt_id, 128);
  const authMethod = singleLine(value.auth_method, 64) || "none";
  const accountEmail = accountDisplayValue(value.account_email, 320);
  const planType = accountDisplayValue(value.plan_type, 128);
  const showAccount = status === "connected" && authMethod === "chatgpt";
  if (["waiting", "cancelling", "unknown"].includes(status) && !attemptId) {
    throw new Error("Codex 로그인 시도 응답이 올바르지 않습니다.");
  }
  return {
    status: status as CodexAuthStatus,
    attempt_id: attemptId,
    method: method as CodexAuthMethod | "",
    started_at: singleLine(value.started_at, 128),
    auth_method: authMethod,
    auth_label: singleLine(value.auth_label, 128) || "로그인 필요",
    account_email: showAccount ? accountEmail : "",
    plan_type: showAccount ? planType : "",
    auth_url: typeof value.auth_url === "string" && value.auth_url.length <= 8192 ? value.auth_url : "",
    user_code: singleLine(value.user_code, 128),
    error_code: singleLine(value.error_code, 128),
    message: singleLine(value.message, 512),
  };
}

function accountDisplayValue(value: unknown, limit: number): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string" || value.length > limit || /[\u0000-\u001f\u007f]/u.test(value)) {
    throw new Error("Codex 계정 표시 정보를 확인하지 못했습니다.");
  }
  return value.trim();
}

function singleLine(value: unknown, limit = 64): string {
  if (typeof value !== "string" || value.length > limit || /[\0\r\n]/u.test(value)) return "";
  return value;
}
