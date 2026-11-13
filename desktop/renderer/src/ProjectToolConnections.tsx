import { useEffect, useRef, useState, type FormEvent } from "react";
import { WorkDialog } from "./WorkDialog";

interface ToolConnection {
  id: string; label: string; transport: "stdio" | "http"; command: string; args: string[]; url: string;
  env_vars: Record<string, string>; bearer_token_env_var: string; env_http_headers: Record<string, string>;
  enabled_tools: string[] | null; enabled: boolean; exclusive: boolean;
}
interface ToolSettings { revision: number; servers: ToolConnection[] }
interface ConnectionResult { id: string; status: "connected" | "error"; message: string; tool_count?: number }

function friendlyError(cause: unknown): string {
  const text = cause instanceof Error ? cause.message.replace(/^Error invoking remote method '[^']+':\s*/, "")
    .replace(/^PythonBridgeRequestError:\s*/, "").replace(/^(?:application_error|invalid_params):\s*/, "") : "";
  return /[가-힣]/.test(text) && text.length <= 250 ? text : "도구 연결을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.";
}

export function ProjectToolConnections({ projectName, active, onChanged }: {
  projectName: string; active: boolean; onChanged(): Promise<void>;
}) {
  const [settings, setSettings] = useState<ToolSettings>();
  const [health, setHealth] = useState<Record<string, ConnectionResult>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState("");
  const [reload, setReload] = useState(0);
  const [adding, setAdding] = useState(false);
  const [mode, setMode] = useState<"url" | "config">("url");
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [configuration, setConfiguration] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    if (!active) return;
    const current = ++generation.current;
    setLoading(true); setSettings(undefined); setBusy(false); setChecking(""); setHealth({}); setError("");
    setNotice(""); setAdding(false); setLabel(""); setUrl(""); setConfiguration("");
    void window.orchestrator.request<ToolSettings>("projects.workerMcp", { projectName }).then(value => {
      if (current === generation.current) setSettings(value);
    }).catch(cause => { if (current === generation.current) setError(friendlyError(cause)); })
      .finally(() => { if (current === generation.current) setLoading(false); });
    return () => { generation.current++; };
  }, [active, projectName, reload]);

  async function save(servers: unknown, append = false): Promise<boolean> {
    if (busy || !settings) return false;
    const current = generation.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const next = await window.orchestrator.approve<ToolSettings>("projects.updateWorkerMcp", {
        projectName, servers, append, expectedRevision: settings.revision,
      });
      if (current !== generation.current || next === null) return false;
      setSettings(next); setHealth({}); setNotice("도구 연결을 저장했습니다. 다음 실행부터 사용합니다.");
      await onChanged();
      return true;
    } catch (cause) { if (current === generation.current) setError(friendlyError(cause)); return false; }
    finally { if (current === generation.current) setBusy(false); }
  }

  async function check(id: string) {
    if (busy || !settings) return;
    const current = generation.current;
    setBusy(true); setChecking(id); setError(""); setNotice("");
    try {
      const result = await window.orchestrator.request<ConnectionResult>("projects.checkWorkerMcp", {
        projectName, serverId: id, expectedRevision: settings.revision,
      });
      if (current === generation.current) setHealth(previous => ({ ...previous, [id]: result }));
    } catch (cause) {
      if (current === generation.current) setHealth(previous => ({ ...previous,
        [id]: { id, status: "error", message: friendlyError(cause) },
      }));
    } finally { if (current === generation.current) { setBusy(false); setChecking(""); } }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    let value: unknown;
    if (mode === "url") {
      if (!url.trim()) { setError("도구의 서버 주소를 입력해 주세요."); return; }
      value = [{ id: `tool-${crypto.randomUUID()}`, label: label.trim() || "새 도구", transport: "http", url: url.trim() }];
    } else {
      try { value = JSON.parse(configuration) as unknown; }
      catch { setError("MCP 연결 설정의 JSON 형식을 확인해 주세요."); return; }
    }
    if (await save(value, true)) { setAdding(false); setLabel(""); setUrl(""); setConfiguration(""); }
  }

  if (!active) return null;
  return <section className="maker-panel">
    <div className="maker-section-heading"><h2>도구 연결</h2>
      <button className="maker-button" disabled={busy || loading || !settings} onClick={() => { setError(""); setAdding(true); }}>도구 추가</button></div>
    <p className="maker-muted">Unity 등 필요한 도구를 이 프로젝트의 작업 AI에 연결합니다.</p>
    {loading ? <p role="status">연결 설정을 확인하고 있어요.</p> : null}
    {!loading && !settings ? <button className="maker-button" onClick={() => setReload(value => value + 1)}>연결 설정 다시 확인</button> : null}
    {settings && !settings.servers.length ? <p>연결된 도구가 없습니다.</p> : null}
    <div className="maker-form-stack">{settings?.servers.map(server => {
      const result = health[server.id];
      return <div className="maker-form-stack" key={server.id}>
        <div><strong>{server.label || server.id}</strong><p className="maker-muted" role={result?.status === "error" ? "alert" : "status"}>
          {!server.enabled ? "사용 중지" : checking === server.id ? "연결 확인 중…" : result?.status === "connected"
            ? `연결 확인됨 · 도구 ${result.tool_count ?? 0}개` : result?.message || "저장됨 · 연결 확인 전"}</p></div>
        <div className="maker-actions">
          <button className="maker-button" disabled={busy || !server.enabled} onClick={() => void check(server.id)}>연결 확인</button>
          <button className="maker-button" disabled={busy} onClick={() => void save(settings.servers.map(item =>
            item.id === server.id ? { ...item, enabled: !item.enabled } : item))}>{server.enabled ? "사용 중지" : "사용하기"}</button>
          <button className="maker-button" disabled={busy} onClick={() => void save(settings.servers.filter(item => item.id !== server.id))}>연결 해제</button>
        </div>
      </div>;
    })}</div>
    {!adding && error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {adding ? <WorkDialog title="도구 연결 추가" className="maker-dialog" onClose={() => { if (!busy) setAdding(false); }}>
      <form className="maker-form-stack" onSubmit={event => void add(event)}>
        <p>도구 제공자가 안내한 주소나 MCP 연결 설정을 넣어 주세요.</p>
        <label className="field"><span>연결 방식</span><select disabled={busy} value={mode} onChange={event => setMode(event.target.value === "url" ? "url" : "config")}>
          <option value="url">서버 주소</option><option value="config">설정 붙여넣기</option></select></label>
        {mode === "url" ? <>
          <label className="field"><span>연결 이름</span><input disabled={busy} value={label} maxLength={80} onChange={event => setLabel(event.target.value)} /></label>
          <label className="field"><span>MCP 서버 주소</span><input disabled={busy} value={url} type="url" placeholder="https://example.com/mcp"
            onChange={event => setUrl(event.target.value)} /></label>
        </> : <label className="field"><span>MCP 연결 설정</span><textarea disabled={busy} rows={8} maxLength={65536} value={configuration}
          onChange={event => setConfiguration(event.target.value)} /></label>}
        <p className="maker-muted">로컬 실행과 HTTP 연결을 지원합니다. 키가 필요한 설정은 환경변수 참조를 사용합니다.</p>
        {error ? <p role="alert">{error}</p> : null}
        <button className="maker-button maker-button--primary" disabled={busy} type="submit">{busy ? "저장 중…" : "연결 저장"}</button>
      </form>
    </WorkDialog> : null}
  </section>;
}
