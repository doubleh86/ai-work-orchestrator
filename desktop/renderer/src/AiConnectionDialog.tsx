import { useEffect, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";

import type { CodexAuthState } from "../../shared/codexAuth";
import type { NvidiaCredentialStatus } from "../../shared/nvidiaCredentials";
import { NvidiaConnectionPanel } from "./NvidiaConnectionPanel";
import { ClaudeConnectionPanel, type ClaudeConnectionStatus } from "./ClaudeConnectionPanel";

export function AiConnectionDialog(props: {
  codexState?: CodexAuthState;
  children: ReactNode;
  onNvidiaChanged(): Promise<void>;
  onClaudeChanged?(): Promise<void>;
  onClose(): void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [provider, setProvider] = useState<"codex" | "claude" | "nvidia">("codex");
  const [nvidia, setNvidia] = useState<NvidiaCredentialStatus>();
  const [nvidiaError, setNvidiaError] = useState(false);
  const [claudeStatus, setClaudeStatus] = useState<ClaudeConnectionStatus | null>();
  const mounted = useRef(false);
  async function refreshNvidia() {
    try {
      const status = await window.orchestrator.nvidiaCredentialStatus();
      if (!Array.isArray(status.keys)) throw Error("outdated app");
      if (mounted.current) { setNvidia(status); setNvidiaError(false); }
    } catch { if (mounted.current) setNvidiaError(true); }
  }
  useEffect(() => {
    mounted.current = true;
    ref.current?.showModal();
    void refreshNvidia();
    return () => { mounted.current = false; };
  }, []);
  const codexLabel = props.codexState?.status === "connected" ? "연결됨" : props.codexState ? "연결 확인 필요" : "확인 중…";
  const claudeLabel = claudeStatus === null || claudeStatus?.authenticated === null ? "연결 확인 실패"
    : claudeStatus?.authenticated ? "연결됨" : claudeStatus ? claudeStatus.installed ? "로그인 필요" : "CLI 설치 필요" : "연결 확인 필요";
  const nvidiaLabel = nvidiaError || nvidia?.error ? "설정 확인 필요" : !nvidia ? "확인 중…"
    : nvidia.source === "app" ? `키 ${nvidia.keys.length}개 등록` : nvidia.source === "environment" ? "환경 변수 사용" : "키 등록 필요";
  return <dialog ref={ref} className="modal ai-connection-dialog" aria-labelledby="ai-connection-title"
    onCancel={event => { event.preventDefault(); props.onClose(); }}>
    <div className="project-form">
      <header><div><span className="eyebrow">AI CONNECTIONS</span><h2 id="ai-connection-title">AI 연결</h2></div>
        <button className="icon-button" type="button" aria-label="닫기" onClick={props.onClose}><X aria-hidden="true" size={17} /></button>
      </header>
      <p>여러 AI를 함께 연결해 두고 작업마다 사용할 AI를 선택할 수 있습니다.</p>
      <div className="ai-connection-providers" role="group" aria-label="연결을 관리할 AI">
        <button type="button" className="ai-connection-provider" aria-pressed={provider === "codex"} aria-controls="codex-connection-panel"
          onClick={() => setProvider("codex")}><strong>Codex</strong><span>ChatGPT 계정 · API 키</span><small>{codexLabel}</small></button>
        <button type="button" className="ai-connection-provider" aria-pressed={provider === "claude"} aria-controls="claude-connection-panel"
          onClick={() => setProvider("claude")}><strong>Claude</strong><span>Claude Code CLI</span><small>{claudeLabel}</small></button>
        <button type="button" className="ai-connection-provider" aria-pressed={provider === "nvidia"} aria-controls="nvidia-connection-panel"
          onClick={() => setProvider("nvidia")}><strong>NVIDIA</strong><span>API 키 · 모델별 연결</span><small>{nvidiaLabel}</small></button>
      </div>
      <div id="codex-connection-panel" hidden={provider !== "codex"}>{props.children}</div>
      <div id="claude-connection-panel" hidden={provider !== "claude"}>
        <ClaudeConnectionPanel visible={provider === "claude"} onChanged={props.onClaudeChanged}
          onStatusChange={setClaudeStatus} onContinue={props.onClose} />
      </div>
      <div id="nvidia-connection-panel" hidden={provider !== "nvidia"}>
        <NvidiaConnectionPanel visible={provider === "nvidia"} onChanged={async () => {
          await refreshNvidia(); await props.onNvidiaChanged();
        }} />
      </div>
    </div>
  </dialog>;
}
