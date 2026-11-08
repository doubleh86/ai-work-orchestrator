import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { codexAccountDetails, codexAuthIsPending, type CodexAuthMethod, type CodexAuthState } from "../../shared/codexAuth";
import { ClaudeConnectionPanel } from "./ClaudeConnectionPanel";
import { CodexApiKeyConnection } from "./CodexApiKeyConnection";
import { NvidiaConnectionPanel } from "./NvidiaConnectionPanel";
import { AccountUsageControl } from "./AccountUsageControl";

const errorText = (error: unknown) => error instanceof Error ? error.message : "연결 상태를 확인하지 못했습니다.";

export function MakerWorkers({ active }: { active: boolean }) {
  const [notice, setNotice] = useState("");
  const changed = useCallback(async () => { setNotice("작업 AI 연결 상태를 확인했습니다. 작업별 AI·모델은 태스크 상세에서 선택할 수 있어요."); }, []);
  return <div className="maker-content maker-settings" hidden={!active}>
    <div className="maker-page-heading"><div><p className="maker-eyebrow">제작을 맡길 AI</p><h1>작업 AI</h1>
      <p>여러 AI를 함께 연결하고 태스크마다 다른 모델을 사용할 수 있습니다.</p></div><AccountUsageControl /></div>
    <p className="maker-notice">여기는 코딩 작업을 수행할 AI의 연결 설정입니다. 기획·제어용 외부 앱 연결은 ‘새 채팅’에서 준비하세요.</p>
    {notice ? <p role="status" className="maker-notice">{notice}</p> : null}
    <div className="maker-provider-grid">
      <section className="maker-panel"><h2>Codex</h2><CodexWorker active={active} onChanged={changed} /></section>
      <section className="maker-panel"><h2>Claude</h2><ClaudeConnectionPanel visible={active} onChanged={changed} /></section>
      <section className="maker-panel maker-provider-wide"><h2>NVIDIA</h2>
        <NvidiaConnectionPanel visible={active} onChanged={changed} /></section>
    </div>
  </div>;
}

export function CodexWorker({ active, onChanged }: { active: boolean; onChanged(): Promise<void> }) {
  const [state, setState] = useState<CodexAuthState>();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(true);
  const inFlight = useRef(false);
  const generation = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function perform(kind: string, action: () => Promise<CodexAuthState>): Promise<boolean> {
    if (inFlight.current) return false;
    inFlight.current = true; generation.current++; setBusy(kind); setError(""); setNotice("");
    try {
      const next = await action();
      if (!alive.current) return false;
      setState(next);
      if (next.status === "connected") await onChanged();
      return next.status === "connected";
    } catch (cause) { if (alive.current) setError(errorText(cause)); return false; }
    finally { inFlight.current = false; if (alive.current) setBusy(""); }
  }
  useEffect(() => { if (active) void perform("status", () => window.orchestrator.codexAuthStatus()); }, [active]);
  const pending = codexAuthIsPending(state);
  useEffect(() => {
    if (!pending || !state?.attempt_id) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout>;
    const attempt = state.attempt_id;
    async function poll() {
      if (inFlight.current) { if (current) timer = setTimeout(() => void poll(), 1000); return; }
      const version = generation.current;
      try {
        const next = await window.orchestrator.getCodexAuth(attempt);
        if (current && version === generation.current) {
          setState(next); setError("");
          if (next.status === "connected") await onChanged();
        }
      } catch (cause) { if (current && version === generation.current) setError(errorText(cause)); }
      finally { if (current) timer = setTimeout(() => void poll(), 1000); }
    }
    timer = setTimeout(() => void poll(), 1000);
    return () => { current = false; clearTimeout(timer); };
  }, [pending, state?.attempt_id, onChanged]);
  const account = codexAccountDetails(state);
  const missing = state?.error_code === "auth_runtime_missing";
  const canLogin = Boolean(state && !pending && !missing && state.status !== "unknown");
  function start(method: CodexAuthMethod) {
    void perform("start", () => window.orchestrator.startCodexAuth(method, crypto.randomUUID()));
  }
  async function simple(action: () => Promise<unknown>, success: string) {
    if (inFlight.current) return;
    inFlight.current = true; generation.current++; setBusy("open"); setError("");
    try { const value = await action(); if (value === false) throw Error("요청을 처리하지 못했습니다."); if (alive.current) setNotice(success); }
    catch (cause) { if (alive.current) setError(errorText(cause)); }
    finally { inFlight.current = false; if (alive.current) setBusy(""); }
  }
  return <div className="maker-worker-connection">
    <p className="maker-connection-state" role="status">{!state ? "연결 확인 중…" : state.status === "connected"
      ? `연결됨 · ${state.auth_label || "Codex"}` : state.message || (pending ? "로그인 확인 중…" : "로그인이 필요합니다.")}</p>
    {account ? <dl className="maker-key-values"><div><dt>현재 계정</dt><dd>{account.email}</dd></div>
      <div><dt>로그인 방식</dt><dd>{account.method}</dd></div><div><dt>요금제</dt><dd>{account.plan}</dd></div></dl> : null}
    {state?.user_code && pending ? <div className="maker-device-code"><strong>{state.user_code}</strong>
      <button className="maker-button" disabled={Boolean(busy)} onClick={() => void simple(() => window.orchestrator.copyCodexDeviceCode(state.attempt_id), "기기 코드를 복사했습니다.")}>코드 복사</button></div> : null}
    {state?.browser_open_error ? <p role="alert">{state.browser_open_error}</p> : null}
    <div className="maker-actions">
      {pending && state ? <><button className="maker-button" disabled={Boolean(busy)} onClick={() => void simple(() => window.orchestrator.reopenCodexAuth(state.attempt_id), "로그인 창을 다시 열었습니다.")}>로그인 창 다시 열기</button>
        <button className="maker-button" disabled={Boolean(busy)} onClick={() => void perform("cancel", () => window.orchestrator.cancelCodexAuth(state.attempt_id))}>로그인 취소</button></>
        : canLogin && state?.status !== "connected" ? <button className="maker-button maker-button--primary" disabled={Boolean(busy)} onClick={() => start("browser")}>ChatGPT로 로그인</button> : null}
      <button className="maker-button" disabled={Boolean(busy)} onClick={() => void perform("status", () => window.orchestrator.codexAuthStatus())}><RefreshCw size={15} />연결 다시 확인</button>
    </div>
    {!pending ? <details><summary>로그인 방법과 API 키 관리</summary><div className="maker-form-stack">
      {missing ? <button className="maker-button" onClick={() => void simple(() => window.orchestrator.openCodexInstallGuide(), "설치 안내를 열었습니다.")}>설치 안내 열기</button> : null}
      {canLogin ? <div className="maker-actions"><button className="maker-button" disabled={Boolean(busy)} onClick={() => start("device_code")}>기기 코드로 로그인</button>
        {state?.status === "connected" ? <button className="maker-button" disabled={Boolean(busy)} onClick={() => start("browser")}>ChatGPT 계정으로 로그인</button> : null}</div> : null}
      {!missing && active ? <CodexApiKeyConnection connected={state?.status === "connected"} hasApiKey={state?.status === "connected" && state.auth_method === "api_key"}
        busy={busy} blockedReason={!state || state.status === "unknown" ? "연결 상태를 확인한 뒤 이용해 주세요." : ""}
        onConnect={key => perform("api_key", () => window.orchestrator.connectCodexApiKey(key, crypto.randomUUID()))} /> : null}
    </div></details> : null}
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}
  </div>;
}
