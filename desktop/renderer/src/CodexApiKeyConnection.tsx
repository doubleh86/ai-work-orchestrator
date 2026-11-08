import { useRef, useState, type FormEvent } from "react";

export function CodexApiKeyConnection({ connected, hasApiKey, busy, blockedReason = "", onConnect }: {
  connected: boolean;
  hasApiKey: boolean;
  busy: string;
  blockedReason?: string;
  onConnect(apiKey: string): Promise<boolean>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [editing, setEditing] = useState(false);
  const submitting = useRef(false);
  const restoreFocus = useRef(false);
  const valid = Boolean(apiKey.trim()) && apiKey.length <= 4096 && !/[\0\r\n]/u.test(apiKey) && !/[^\x21-\x7e]/u.test(apiKey.trim());
  function closeEditor() {
    setApiKey("");
    restoreFocus.current = true;
    setEditing(false);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || blockedReason || submitting.current || !valid) return;
    submitting.current = true;
    const value = apiKey.trim();
    setApiKey("");
    try {
      if (await onConnect(value) && hasApiKey) closeEditor();
    } finally {
      submitting.current = false;
    }
  }
  if (hasApiKey && !editing) return <div className="codex-auth-actions">
    <button className="button button--secondary" type="button" disabled={Boolean(busy)} onClick={() => setEditing(true)}
      ref={button => { if (button && !button.disabled && restoreFocus.current) { button.focus(); restoreFocus.current = false; } }}>
      API 키 변경
    </button>
  </div>;
  return <section className="codex-api-key" aria-labelledby="codex-api-key-heading">
    <h3 id="codex-api-key-heading">{hasApiKey ? "API 키 변경" : connected ? "OpenAI API 키로 전환" : "OpenAI API 키로 연결"}</h3>
    <form onSubmit={submit}>
      {blockedReason ? <p className="field-note" id="codex-api-key-blocked" role="status">{blockedReason}</p> : null}
      <label className="field" htmlFor="codex-api-key-input">OpenAI API 키
        <input id="codex-api-key-input" type="password" autoFocus={hasApiKey} autoComplete="off" spellCheck={false} maxLength={4096}
          aria-describedby={blockedReason ? "codex-api-key-blocked" : undefined}
          value={apiKey} onChange={event => setApiKey(event.target.value)} disabled={Boolean(busy || blockedReason)} placeholder="sk-…" />
      </label>
      <p className="muted">OpenAI API 사용량에 따라 별도 과금됩니다.{hasApiKey ? "" : " 이 앱의 Codex 연결만 API 키 방식으로 전환됩니다."}</p>
      <p className="field-note">키는 이 앱 전용 Codex 저장소에서 관리합니다. Codex 앱·CLI의 로그인은 변경하지 않습니다.</p>
      <div className="codex-auth-actions">
        <button className="button button--primary" type="submit" disabled={Boolean(busy || blockedReason) || !valid}>
          {busy === "api_key" ? "연결 중…" : hasApiKey ? "변경 저장" : "API 키 연결"}
        </button>
        {hasApiKey ? <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={closeEditor}>취소</button> : null}
      </div>
    </form>
  </section>;
}
