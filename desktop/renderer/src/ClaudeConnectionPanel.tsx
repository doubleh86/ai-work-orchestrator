import { useEffect, useRef, useState } from "react";
import { CheckCircle2, RefreshCw, ShieldCheck, Terminal } from "lucide-react";

export interface ClaudeConnectionStatus {
  installed: boolean;
  authenticated: boolean | null;
  auth_method: string;
  message: string;
  account_email?: string;
  plan_type?: string;
}

export function claudeAccountDetails(status?: ClaudeConnectionStatus): { email: string; method: string; plan: string } | undefined {
  if (!status?.installed || status.authenticated !== true) return;
  if (status.auth_method === "claude_subscription") return {
    email: status.account_email || "이메일 정보가 제공되지 않습니다",
    method: "Claude 구독 로그인",
    plan: ({ pro: "Pro", max: "Max", team: "Team", enterprise: "Enterprise" } as Record<string, string>)[status.plan_type || ""]
      || "요금제 정보가 제공되지 않습니다",
  };
  return {
    email: status.auth_method === "api_key" ? "API 인증 · 계정 이메일을 제공하지 않습니다" : "외부 인증 · 계정 이메일을 제공하지 않습니다",
    method: status.auth_method === "api_key" ? "API 인증" : "외부 인증",
    plan: "구독 요금제 정보가 제공되지 않습니다",
  };
}

export function ClaudeConnectionPanel({ visible, onChanged, onStatusChange, onContinue }: {
  visible: boolean; onChanged?(): Promise<void>; onStatusChange?(status: ClaudeConnectionStatus | null): void; onContinue?(): void;
}) {
  const [status, setStatus] = useState<ClaudeConnectionStatus>();
  const [action, setAction] = useState<"" | "refresh" | "login">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const pending = useRef(false);
  const busy = action !== "";
  async function refresh() {
    if (pending.current) return;
    pending.current = true;
    const request = ++generation.current;
    setAction("refresh"); setError(""); setNotice("");
    try {
      const value = await window.orchestrator.request<ClaudeConnectionStatus>("auth.claude.status", {});
      if (!value || typeof value.installed !== "boolean" || ![true, false, null].includes(value.authenticated)
        || typeof value.message !== "string" || typeof value.auth_method !== "string"
        || value.account_email !== undefined && typeof value.account_email !== "string"
        || value.plan_type !== undefined && typeof value.plan_type !== "string"
        || value.authenticated === true && !value.installed) throw new Error("Claude 연결 응답을 확인하지 못했습니다.");
      if (request !== generation.current) return;
      setStatus(value);
      onStatusChange?.(value);
      try { await onChanged?.(); }
      catch {
        if (request === generation.current) setError("Claude 연결 상태는 확인했지만 모델 목록을 갱신하지 못했습니다. 연결을 다시 확인해 주세요.");
      }
    } catch (cause) {
      if (request === generation.current) {
        setStatus(undefined); onStatusChange?.(null);
        setError(cause instanceof Error ? cause.message : "Claude 연결 확인에 실패했습니다.");
      }
    } finally {
      if (request === generation.current) { pending.current = false; setAction(""); }
    }
  }
  useEffect(() => {
    setAction("");
    if (visible) void refresh();
    return () => { generation.current++; pending.current = false; };
  }, [visible]);
  async function login() {
    if (pending.current || !status?.installed) return;
    pending.current = true; setAction("login"); setError(""); setNotice("");
    const request = ++generation.current;
    try {
      const opened = await window.orchestrator.openClaudeLogin();
      if (!opened) throw new Error("로그인 터미널을 열지 못했습니다.");
      if (request === generation.current) setNotice("Claude 로그인 터미널을 열었습니다. 로그인을 마친 뒤 연결을 다시 확인하세요.");
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : "Claude 로그인 터미널을 열지 못했습니다.");
    } finally {
      if (request === generation.current) { pending.current = false; setAction(""); }
    }
  }
  const connected = status?.authenticated === true;
  const account = claudeAccountDetails(status);
  const state = action === "refresh" ? "checking" : connected ? "connected" : error || status?.authenticated === null ? "status_error" : "signed_out";
  const title = action === "refresh" ? "연결 확인 중…" : connected ? `연결 완료 · ${status.message}` : error ? "연결 확인 실패" : status?.message || "연결 확인 필요";
  return <section className="claude-connection-panel ai-auth-content" aria-label="Claude 연결">
    <p>Claude Code의 로그인을 사용해 대화·기획·작업 실행·리뷰를 진행합니다. 비밀번호와 인증 토큰은 앱에 입력하거나 저장하지 않습니다.</p>
    <section className="ai-auth-state" data-state={state} aria-live="polite">
      {state === "connected" ? <CheckCircle2 aria-hidden="true" size={22} /> : <ShieldCheck aria-hidden="true" size={22} />}
      <div><strong>{title}</strong><span>{action === "refresh" ? "Claude 로그인 상태를 확인하고 있습니다." : connected ? "Claude 연결이 완료됐습니다." : status && !status.installed ? "Claude Code CLI를 설치한 뒤 연결을 다시 확인하세요." : "Claude 로그인 상태를 확인합니다."}</span></div>
    </section>
    {account && action !== "refresh" ? <dl className="ai-account-details">
      <div><dt>현재 계정</dt><dd>{account.email}</dd></div>
      <div><dt>로그인 방식</dt><dd>{account.method}</dd></div>
      <div><dt>요금제</dt><dd>{account.plan}</dd></div>
    </dl> : null}
    {notice ? <p role="status">{notice}</p> : null}{error ? <p className="field-error" role="alert">{error}</p> : null}
    <details><summary>설치·터미널 안내</summary><code>claude auth login</code><p>로그인은 공식 CLI에서 진행합니다. 로그인 후 연결을 다시 확인하면 작업 모델에서 Claude를 선택할 수 있습니다.</p>
      <p>Opus 5.5는 Claude Code 2.1.280 이상이 필요합니다. 버전은 <code>claude --version</code>으로 확인하고 <code>claude update</code>로 업데이트할 수 있습니다.</p>
    </details>
    <footer className="ai-auth-actions">
      {connected ? <button className="button button--quiet" type="button" disabled={busy} onClick={() => void login()}>
        <Terminal aria-hidden="true" size={15} />{action === "login" ? "여는 중…" : "로그인 관리"}</button> : null}
      <button className="button button--quiet" type="button" disabled={busy} onClick={() => void refresh()}>
        <RefreshCw aria-hidden="true" size={15} />{action === "refresh" ? "확인 중…" : "연결 다시 확인"}</button>
      {connected ? <button className="button button--primary" type="button" disabled={busy} onClick={onContinue}>계속하기</button>
        : status?.installed ? <button className="button button--primary" type="button" disabled={busy} onClick={() => void login()}>
          <Terminal aria-hidden="true" size={15} />{action === "login" ? "여는 중…" : "Claude로 로그인"}</button> : null}
    </footer>
  </section>;
}
