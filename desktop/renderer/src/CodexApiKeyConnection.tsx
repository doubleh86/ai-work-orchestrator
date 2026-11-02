import { useRef, useState, type FormEvent } from "react";

export function CodexApiKeyConnection({ connected, busy, blockedReason = "", onCancelPending, onConnect }: {
  connected: boolean;
  busy: string;
  blockedReason?: string;
  onCancelPending?(): void;
  onConnect(apiKey: string): Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const submitting = useRef(false);
  const valid = Boolean(apiKey.trim()) && apiKey.length <= 4096 && !/[\0\r\n]/u.test(apiKey) && !/[^\x21-\x7e]/u.test(apiKey.trim());
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || blockedReason || submitting.current || !valid) return;
    submitting.current = true;
    const value = apiKey.trim();
    setApiKey("");
    try { await onConnect(value); } finally { submitting.current = false; }
  }
  return <section className="codex-api-key" aria-labelledby="codex-api-key-heading">
    <h3 id="codex-api-key-heading">{connected ? "API 키로 전환 · 키 교체" : "OpenAI API 키로 연결"}</h3>
    <form onSubmit={submit}>
      {blockedReason ? <div className="codex-api-key__pending">
        <p className="field-note" id="codex-api-key-blocked" role="status">{blockedReason}</p>
        {onCancelPending ? <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={onCancelPending}>
          {busy === "cancel" ? "취소 확인 중…" : "로그인 취소"}
        </button> : null}
      </div> : null}
      <label className="field" htmlFor="codex-api-key-input">OpenAI API 키
        <input id="codex-api-key-input" type="password" autoComplete="off" spellCheck={false} maxLength={4096}
          aria-describedby={blockedReason ? "codex-api-key-blocked" : undefined}
          value={apiKey} onChange={event => setApiKey(event.target.value)} disabled={Boolean(busy || blockedReason)} placeholder="sk-…" />
      </label>
      <p className="muted">OpenAI API 사용량에 따라 별도 과금됩니다. 이 앱의 Codex 연결만 API 키 방식으로 전환됩니다.</p>
      <p className="field-note">키는 이 앱 전용 Codex 저장소에서 관리합니다. Codex 앱·CLI의 로그인은 변경하지 않습니다.</p>
      <button className="button button--primary" type="submit" disabled={Boolean(busy || blockedReason) || !valid}>
        {busy === "api_key" ? "연결 중…" : "API 키 연결"}
      </button>
    </form>
  </section>;
}
