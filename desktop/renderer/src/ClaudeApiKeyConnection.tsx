import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ClaudeCredentialStatus } from "../../shared/claudeCredentials";

export function ClaudeApiKeyConnection({ visible, busy, onChanged }: {
  visible: boolean; busy: boolean; onChanged(): Promise<void>;
}) {
  const [status, setStatus] = useState<ClaudeCredentialStatus>();
  const [key, setKey] = useState("");
  const [action, setAction] = useState<"" | "save" | "delete">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    const request = ++generation.current;
    setKey(""); setAction(""); setError(""); setNotice(""); setStatus(undefined); pending.current = false;
    if (visible) void window.orchestrator.claudeCredentialStatus().then(value => {
      if (request === generation.current) setStatus(value);
    }).catch(() => { if (request === generation.current) setError("Claude 키 저장 상태를 확인하지 못했습니다."); });
    return () => { generation.current++; pending.current = false; };
  }, [visible]);
  const disabled = busy || action !== "";
  const valid = Boolean(key.trim()) && key.length <= 4096 && !/[\0\r\n]/u.test(key) && !/[^\x21-\x7e]/u.test(key.trim());
  async function change(kind: "save" | "delete", event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (pending.current || disabled || !status || kind === "save" && (!valid || !status.storageAvailable)) return;
    pending.current = true;
    const request = ++generation.current, value = key.trim();
    setKey(""); setAction(kind); setError(""); setNotice("");
    try {
      const next = kind === "save" ? await window.orchestrator.saveClaudeCredential(value) : await window.orchestrator.deleteClaudeCredential();
      if (request !== generation.current) return;
      setStatus(next);
      if (next.error) { setError(next.error); return; }
      setNotice(kind === "save" ? "API 키를 저장했습니다. 다음 Claude 요청부터 사용합니다." : "앱에 저장된 키를 삭제했습니다.");
      try { await onChanged(); }
      catch { if (request === generation.current) setError("키 설정은 저장했지만 연결 상태를 갱신하지 못했습니다."); }
    } catch {
      if (request === generation.current) setError("Claude 키 설정을 변경하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      if (request === generation.current) { pending.current = false; setAction(""); }
    }
  }
  return <details className="ai-connection-options">
    <summary>{status?.hasStoredKey ? "API 키 관리" : "API 키로 연결"}</summary>
    <div className="ai-connection-options__body">
      <p className="muted">Anthropic API 사용량에 따라 별도 과금됩니다. 키는 이 앱에 암호화해 저장합니다.</p>
      {status?.source === "app" ? <p>앱에 API 키가 저장되어 있습니다.</p>
        : status?.source === "environment" ? <p>환경 변수에 API 키가 설정되어 있습니다.</p> : null}
      {error || status?.error ? <p role="alert" className="field-error">{error || status?.error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {status && !status.storageAvailable ? <p role="alert">OS 보안 저장소를 사용할 수 없어 키를 저장할 수 없습니다.</p> : null}
      <form onSubmit={event => void change("save", event)}>
        <label className="field" htmlFor="claude-api-key-input">Anthropic API 키
          <input id="claude-api-key-input" type="password" autoComplete="off" spellCheck={false} maxLength={4096}
            value={key} onChange={event => setKey(event.target.value)} disabled={disabled || !status?.storageAvailable} placeholder="sk-ant-…" />
        </label>
        <div className="ai-auth-actions">
          <button className="button button--primary" type="submit" disabled={disabled || !status?.storageAvailable || !valid}>
            {action === "save" ? "저장 중…" : status?.hasStoredKey ? "키 변경 저장" : "API 키 저장"}</button>
          {status?.hasStoredKey ? <button className="button button--quiet" type="button" disabled={disabled}
            onClick={() => void change("delete")}>{action === "delete" ? "삭제 중…" : "앱 키 삭제"}</button> : null}
        </div>
      </form>
      <p className="field-note">실제 API 연결은 작업 실행 시 확인합니다. 앱 키를 삭제하면 기존 Claude 로그인·환경 설정을 따릅니다.</p>
    </div>
  </details>;
}
