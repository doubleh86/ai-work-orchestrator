import { useEffect, useRef, useState } from "react";
import { CheckCircle2, FolderOpen, RefreshCw, ShieldCheck, Terminal } from "lucide-react";

export interface ClaudeConnectionStatus {
  installed: boolean;
  authenticated: boolean | null;
  auth_method: string;
  message: string;
  account_email?: string;
  plan_type?: string;
  selected_executable?: string;
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
  const [action, setAction] = useState<"" | "refresh" | "login" | "select" | "reset">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const pending = useRef(false);
  const busy = action !== "";
  async function acceptStatus(value: ClaudeConnectionStatus, request: number) {
    if (!value || typeof value.installed !== "boolean" || ![true, false, null].includes(value.authenticated)
      || typeof value.message !== "string" || typeof value.auth_method !== "string"
      || value.account_email !== undefined && typeof value.account_email !== "string"
      || value.plan_type !== undefined && typeof value.plan_type !== "string"
      || value.selected_executable !== undefined && typeof value.selected_executable !== "string"
      || value.authenticated === true && !value.installed) throw new Error("Claude 연결 응답을 확인하지 못했습니다.");
    if (request !== generation.current) return;
    setStatus(value);
    onStatusChange?.(value);
    try { await onChanged?.(); }
    catch {
      if (request === generation.current) setError("Claude 연결 상태는 확인했지만 모델 목록을 갱신하지 못했습니다. 연결을 다시 확인해 주세요.");
    }
  }
  async function refresh() {
    if (pending.current) return;
    pending.current = true;
    const request = ++generation.current;
    setAction("refresh"); setError(""); setNotice("");
    try {
      const value = await window.orchestrator.request<ClaudeConnectionStatus>("auth.claude.status", {});
      await acceptStatus(value, request);
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
  async function selectExecutable() {
    if (pending.current) return;
    pending.current = true; setAction("select"); setError(""); setNotice("");
    const request = ++generation.current;
    try {
      const path = await window.orchestrator.selectPath("claude");
      if (!path || request !== generation.current) return;
      const value = await window.orchestrator.request<ClaudeConnectionStatus>("auth.claude.setExecutable", { path });
      await acceptStatus(value, request);
      if (request === generation.current) setNotice("Claude 실행 파일을 저장하고 연결 상태를 확인했습니다.");
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : "Claude 실행 파일을 선택하지 못했습니다.");
    } finally {
      if (request === generation.current) { pending.current = false; setAction(""); }
    }
  }
  async function resetExecutable() {
    if (pending.current) return;
    pending.current = true; setAction("reset"); setError(""); setNotice("");
    const request = ++generation.current;
    try {
      const value = await window.orchestrator.request<ClaudeConnectionStatus>("auth.claude.clearExecutable", {});
      await acceptStatus(value, request);
      if (request === generation.current) setNotice("Claude 실행 파일 자동 탐색으로 돌아갔습니다.");
    } catch (cause) {
      if (request === generation.current) setError(cause instanceof Error ? cause.message : "Claude 실행 파일 설정을 초기화하지 못했습니다.");
    } finally {
      if (request === generation.current) { pending.current = false; setAction(""); }
    }
  }
  const connected = status?.authenticated === true;
  const account = claudeAccountDetails(status);
  const state = action === "refresh" ? "checking" : connected ? "connected" : error || status?.authenticated === null ? "status_error" : "signed_out";
  const title = action === "refresh" ? "연결 확인 중…" : connected ? `연결 완료 · ${status.message}` : error ? "연결 확인 실패" : status?.message || "연결 확인 필요";
  const description = action === "refresh" ? "Claude 로그인 상태를 확인하고 있어요."
    : connected ? "이제 Claude를 작업에 사용할 수 있어요."
      : status?.installed ? "Claude로 로그인하려면 아래 버튼을 누르세요."
        : status?.selected_executable ? "선택한 실행 파일을 사용할 수 없습니다. 다시 선택하거나 자동 탐색으로 돌아가세요."
          : status ? "Claude Code를 설치했는데도 찾지 못한다면 실행 파일을 직접 선택하세요." : "연결 상태를 다시 확인해 주세요.";
  return <section className="claude-connection-panel ai-auth-content" aria-label="Claude 연결">
    <section className="ai-auth-state" data-state={state} aria-live="polite">
      {state === "connected" ? <CheckCircle2 aria-hidden="true" size={22} /> : <ShieldCheck aria-hidden="true" size={22} />}
      <div><strong>{title}</strong><span>{description}</span></div>
    </section>
    {notice ? <p role="status">{notice}</p> : null}{error ? <p className="field-error" role="alert">{error}</p> : null}
    <footer className="ai-auth-actions">
      {!connected ? <button className={status?.installed ? "button button--quiet" : "button button--primary"}
        type="button" disabled={busy} onClick={() => void refresh()}>
        <RefreshCw aria-hidden="true" size={15} />{action === "refresh" ? "확인 중…" : "연결 다시 확인"}</button>
        : null}
      {connected ? (onContinue ? <button className="button button--primary" type="button" disabled={busy} onClick={onContinue}>계속하기</button> : null)
        : status?.installed ? <button className="button button--primary" type="button" disabled={busy} onClick={() => void login()}>
          <Terminal aria-hidden="true" size={15} />{action === "login" ? "여는 중…" : "Claude로 로그인"}</button> : null}
      {!connected ? <button className="button button--quiet" type="button" disabled={busy} onClick={() => void selectExecutable()}>
        <FolderOpen aria-hidden="true" size={15} />{action === "select" ? "선택 중…" : "실행 파일 선택"}</button> : null}
      {!connected && (status?.selected_executable || error) ? <button className="button button--quiet" type="button" disabled={busy}
        onClick={() => void resetExecutable()}>{action === "reset" ? "복구 중…" : "자동 탐색으로 돌아가기"}</button> : null}
    </footer>
    <details className="ai-connection-options">
      <summary>{connected ? "연결 관리" : "설치·터미널 안내"}</summary>
      <div className="ai-connection-options__body">
        {account && action !== "refresh" ? <dl className="ai-account-details">
          <div><dt className="sr-only">현재 계정</dt><dd title={account.email}>{account.email}</dd></div>
          <div><dt className="sr-only">로그인 방식</dt><dd title={account.method}>{account.method}</dd></div>
          <div><dt className="sr-only">요금제</dt><dd title={account.plan}>{account.plan}</dd></div>
        </dl> : null}
        {status?.selected_executable ? <p className="claude-executable-path">선택한 실행 파일: <code>{status.selected_executable}</code></p> : null}
        {connected ? <div className="ai-auth-actions">
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => void refresh()}>연결 다시 확인</button>
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => void login()}>
            <Terminal aria-hidden="true" size={15} />{action === "login" ? "여는 중…" : "로그인 관리"}</button>
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => void selectExecutable()}>
            <FolderOpen aria-hidden="true" size={15} />{action === "select" ? "선택 중…" : "실행 파일 변경"}</button>
          {status?.selected_executable ? <button className="button button--quiet" type="button" disabled={busy}
            onClick={() => void resetExecutable()}>{action === "reset" ? "복구 중…" : "자동 탐색으로 돌아가기"}</button> : null}
        </div> : null}
        <p>터미널에서 직접 로그인하려면 <code>claude auth login</code>을 실행하세요.</p>
        <p>Opus 5.5는 Claude Code 2.1.280 이상이 필요합니다. 버전은 <code>claude --version</code>으로 확인하고 <code>claude update</code>로 업데이트할 수 있습니다.</p>
      </div>
    </details>
  </section>;
}
