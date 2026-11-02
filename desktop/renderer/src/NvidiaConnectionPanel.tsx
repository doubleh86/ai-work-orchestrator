import { useEffect, useId, useState } from "react";

import type { NvidiaCredentialStatus } from "../../shared/nvidiaCredentials";

export function NvidiaConnectionPanel(props: { visible: boolean; onChanged(): Promise<void> }) {
  const inputId = useId();
  const [status, setStatus] = useState<NvidiaCredentialStatus>();
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [editingId, setEditingId] = useState("");
  const [model, setModel] = useState("");
  const [modelKeyId, setModelKeyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setKey(""); setLabel(""); setEditingId(""); setMessage("");
    if (!props.visible) return;
    let current = true;
    setBusy(true); setError("");
    void Promise.resolve().then(() => window.orchestrator.nvidiaCredentialStatus()).then((value) => {
      if (!Array.isArray(value.keys)) throw Error("outdated app");
      if (current) setStatus(value);
    }).catch(() => {
      if (current) setError("NVIDIA 키 설정을 불러오지 못했습니다. 앱을 완전히 종료한 뒤 다시 열어 주세요.");
    }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, [props.visible]);

  async function change(action: () => Promise<NvidiaCredentialStatus>, success: string, clearInput = false) {
    if (busy) return;
    setBusy(true); setMessage(""); setError("");
    try {
      const value = await action();
      if (!Array.isArray(value.keys)) throw Error("outdated app");
      setStatus(value);
      if (!value.error) {
        if (modelKeyId && !value.keys.some(item => item.id === modelKeyId)) setModelKeyId("");
        if (clearInput) { setKey(""); setLabel(""); setEditingId(""); }
        setMessage(success);
        try { await props.onChanged(); }
        catch { setError("키 설정은 반영했지만 연결 상태를 불러오지 못했습니다. 연결 창을 다시 열어 주세요."); }
      }
    } catch { setError("NVIDIA 키 설정을 변경하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }

  const keys = status?.keys || [];
  const bindings = status?.modelBindings || {};
  const defaultLabel = keys.find(item => item.id === status?.defaultKeyId)?.label;
  const disabled = busy || !status?.storageAvailable;
  const save = () => change(() => window.orchestrator.saveNvidiaCredential(key, {
    ...(editingId ? { id: editingId } : {}), label: label.trim() || "기본 키",
  }), "키를 저장했습니다. 다음 요청부터 적용됩니다.", true);
  const route = (defaultId: string, selected: Readonly<Record<string, string>>) => change(
    () => window.orchestrator.setNvidiaCredentialRouting(defaultId, selected), "키 연결을 저장했습니다. 다음 요청부터 적용됩니다.",
  );

  return <section className="nvidia-connection" aria-label="NVIDIA API 연결">
    <h3>NVIDIA API 키</h3>
    <p>{!status ? "등록 상태 확인 중…" : status.source === "app" ? `${keys.length}개 등록 · 기본 키: ${defaultLabel}`
      : status.source === "environment" ? "NVIDIA_API_KEY 환경 변수 사용 중" : "등록된 키 없음"}</p>
    {keys.length ? <ul className="nvidia-connection__keys" aria-label="저장한 NVIDIA 키">
      {keys.map(item => <li key={item.id}>
        <span>{item.label}{item.id === status?.defaultKeyId ? " · 기본" : ""}</span>
        <div className="nvidia-connection__actions">
          <button className="button button--quiet" type="button" disabled={disabled} aria-label={`${item.label} 교체`}
            onClick={() => { setEditingId(item.id); setLabel(item.label); setKey(""); }}>교체</button>
          <button className="button button--quiet" type="button" disabled={busy} aria-label={`${item.label} 삭제`}
            onClick={() => void change(() => window.orchestrator.deleteNvidiaCredential(item.id), "키를 삭제했습니다. 앱 키가 없으면 환경 변수의 키를 사용합니다.", true)}>삭제</button>
        </div>
      </li>)}
    </ul> : null}
    {status?.hasStoredKey && !keys.length ? <button className="button button--secondary" disabled={busy} type="button"
      onClick={() => void change(() => window.orchestrator.deleteNvidiaCredential(), "저장한 키 정보를 삭제했습니다.")}>손상된 키 저장 삭제</button> : null}
    <form className="nvidia-connection__key-form" aria-label={editingId ? "NVIDIA 키 교체" : "NVIDIA 키 추가"}
      onSubmit={event => { event.preventDefault(); void save(); }}>
      <label className="field">키 이름
        <input value={label} maxLength={80} disabled={disabled} placeholder={keys.length ? "예: 리뷰용, 코딩용" : "기본 키"}
          onChange={event => setLabel(event.target.value)} />
      </label>
      <label className="field" htmlFor={inputId}>{editingId ? "교체할 API 키" : "추가할 API 키"}
        <input id={inputId} type="password" autoComplete="off" spellCheck={false} maxLength={4096}
          value={key} onChange={event => setKey(event.target.value)} disabled={disabled} placeholder="NVIDIA에서 발급한 API 키" />
      </label>
      <div className="nvidia-connection__actions">
        <button className="button button--primary" type="submit" disabled={disabled || !key.trim() || (keys.length > 0 && !label.trim())}>
          {editingId ? "키 교체 저장" : "키 저장"}</button>
        {editingId ? <button className="button button--quiet" type="button" disabled={busy}
          onClick={() => { setEditingId(""); setKey(""); setLabel(""); }}>교체 취소</button> : null}
      </div>
    </form>
    {keys.length ? <section className="nvidia-connection__routing" aria-label="모델별 키 연결">
      <label className="field">기본 키
        <select aria-label="NVIDIA 기본 키" value={status?.defaultKeyId} disabled={disabled}
          onChange={event => void route(event.target.value, bindings)}>
          {keys.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <h4>모델별 사용할 키</h4>
      <small>지정하지 않은 모델은 기본 키를 사용합니다. 모델 ID를 등록하면 실행 모델 목록에도 표시됩니다.</small>
      {Object.entries(bindings).map(([modelId, keyId]) => <div className="nvidia-connection__binding" key={modelId}>
        <label className="field"><span>{modelId}</span>
          <select aria-label={`${modelId} 사용할 키`} value={keyId} disabled={disabled}
            onChange={event => void route(status?.defaultKeyId || "", { ...bindings, [modelId]: event.target.value })}>
            <option value="">기본 키 사용</option>
            {keys.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <button className="button button--quiet" type="button" disabled={disabled} aria-label={`${modelId} 모델 삭제`}
          onClick={() => { const selected = { ...bindings }; delete selected[modelId]; void route(status?.defaultKeyId || "", selected); }}>모델 삭제</button>
      </div>)}
      <form className="nvidia-connection__model-form" aria-label="모델별 키 지정" onSubmit={event => {
        event.preventDefault();
        void route(status?.defaultKeyId || "", { ...bindings, [model.trim()]: modelKeyId });
      }}>
        <label className="field">모델 ID
          <input value={model} maxLength={200} disabled={disabled} placeholder="예: nvidia/nemotron-3-super-120b-a12b"
            onChange={event => setModel(event.target.value)} />
        </label>
        <label className="field">사용할 키
          <select value={modelKeyId} disabled={disabled} onChange={event => setModelKeyId(event.target.value)}>
            <option value="">기본 키 사용</option>
            {keys.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <button className="button button--secondary" type="submit" disabled={disabled || !model.trim()}>모델에 키 연결</button>
      </form>
    </section> : null}
    {status && !status.storageAvailable ? <p role="status">OS 보안 저장소를 사용할 수 없습니다. NVIDIA_API_KEY 환경 변수를 사용해 주세요.</p> : null}
    {error || status?.error ? <p role="alert">{error || status?.error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <small>키는 암호화해 앱에만 저장합니다. 저장 여부와 실제 API 인증은 다르며, 연결은 작업 실행 시 확인합니다.</small>
  </section>;
}
