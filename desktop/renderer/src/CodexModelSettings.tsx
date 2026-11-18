import { useEffect, useState } from "react";

type ModelSettings = { models: string[]; enabled_models: string[] };

function modelLabel(id: string): string {
  return id.replace(/^gpt-/, "").replace(/-([a-z])/g, (_, letter: string) => ` ${letter.toUpperCase()}`);
}

export function CodexModelSettings() {
  const [settings, setSettings] = useState<ModelSettings>();
  const [enabled, setEnabled] = useState<string[]>([]);
  const [request, setRequest] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let current = true;
    setBusy(true);
    setError("");
    setSaved(false);
    void window.orchestrator.request<ModelSettings>("providers.codexModels").then(value => {
      if (current) { setSettings(value); setEnabled(value.enabled_models); }
    }).catch(cause => {
      if (current) setError(cause instanceof Error ? cause.message : "모델 설정을 불러오지 못했습니다.");
    }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [request]);

  const dirty = settings && (enabled.length !== settings.enabled_models.length || enabled.some(id => !settings.enabled_models.includes(id)));
  async function save() {
    if (!settings || busy || !dirty || !enabled.length) return;
    setBusy(true);
    setError("");
    try {
      const value = await window.orchestrator.request<ModelSettings>("providers.updateCodexModels", {
        models: enabled, expectedModels: settings.enabled_models,
      });
      setSettings(value);
      setEnabled(value.enabled_models);
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "모델 설정을 저장하지 못했습니다.");
    } finally { setBusy(false); }
  }

  return <details className="maker-codex-model-settings">
    <summary>사용할 모델</summary>
    <div className="maker-form-stack">
      <p>선택한 모델을 새 작업의 모델 목록과 자동 배정에 사용합니다. 모든 프로젝트에 적용됩니다.</p>
      {settings ? <div className="maker-codex-model-list" role="group" aria-label="사용할 Codex 모델">
        {settings.models.map(id => <label key={id}>
          <input type="checkbox" checked={enabled.includes(id)} disabled={busy} onChange={event => {
            const checked = event.target.checked;
            setEnabled(previous => checked ? [...previous, id] : previous.filter(model => model !== id));
            setSaved(false);
          }} /> {modelLabel(id)}
        </label>)}
      </div> : busy ? <p role="status">모델을 불러오는 중…</p> : null}
      {settings && !enabled.length ? <p role="status">모델을 하나 이상 선택해 주세요.</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {saved ? <p role="status">모델 설정을 저장했습니다.</p> : null}
      <div className="maker-actions">
        {settings ? <button type="button" className="maker-button maker-button--primary" disabled={busy || !dirty || !enabled.length}
          onClick={() => void save()}>모델 설정 저장</button> : null}
        {error ? <button type="button" className="maker-button" disabled={busy} onClick={() => setRequest(value => value + 1)}>
          다시 불러오기
        </button> : null}
      </div>
    </div>
  </details>;
}
