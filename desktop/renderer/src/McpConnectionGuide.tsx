import { useEffect, useState } from "react";

export function mcpConnectionConfig(command: string, allowWrite: boolean): string {
  const args = allowWrite ? ["mcp", "--allow-write"] : ["mcp"];
  return ["[mcp_servers.orchestrator]", `command = ${JSON.stringify(command)}`, `args = ${JSON.stringify(args)}`,
    ...(allowWrite ? ["tool_timeout_sec = 3600"] : [])].join("\n");
}

export function McpConnectionGuide({ visible }: { visible: boolean }) {
  const [command, setCommand] = useState<string | null>();
  const [allowWrite, setAllowWrite] = useState(false);
  const [message, setMessage] = useState("");
  const [registering, setRegistering] = useState(false);
  const [codexMissing, setCodexMissing] = useState(false);

  useEffect(() => {
    if (!visible || command !== undefined) return;
    let active = true;
    void (async () => {
      try {
        const executable = await window.orchestrator.mcpConnectionCommand();
        if (active) setCommand(executable);
      } catch {
        if (active) setMessage("실행 경로를 확인하지 못했습니다. 설정 화면을 다시 열어 주세요.");
      }
    })();
    return () => { active = false; };
  }, [command, visible]);

  const config = command === undefined ? "" : mcpConnectionConfig(command ?? "ai-orchestrator", allowWrite);
  const canRegister = command?.toLowerCase().endsWith(".exe") === true;

  async function register() {
    setRegistering(true);
    setCodexMissing(false);
    setMessage("");
    try {
      const result = await window.orchestrator.registerCodexMcp();
      if (result === "registered") {
        setMessage("조회 연결을 등록했어요. Codex를 다시 열고 ‘오케스트레이터 작업 진행 상황 알려줘’라고 물어보세요.");
      } else if (result === "codex_missing") {
        setCodexMissing(true);
        setMessage("설치된 Codex를 찾지 못했어요. Codex를 설치하거나 아래에서 수동으로 연결해 주세요.");
      } else {
        setMessage("Codex에 등록하지 못했습니다. 다시 시도하거나 아래에서 수동으로 연결해 주세요.");
      }
    } catch {
      setMessage("Codex에 등록하지 못했습니다. 다시 시도하거나 아래에서 수동으로 연결해 주세요.");
    } finally {
      setRegistering(false);
    }
  }

  async function showInstallGuide() {
    try {
      await window.orchestrator.openCodexInstallGuide();
    } catch {
      setMessage("Codex 설치 안내를 열지 못했습니다.");
    }
  }

  async function copyConfig() {
    try {
      await navigator.clipboard.writeText(config);
      setMessage("Codex 설정을 복사했습니다.");
    } catch {
      setMessage("복사하지 못했습니다. 아래 설정을 직접 선택해 복사해 주세요.");
    }
  }

  return <section className="work-settings__card" aria-label="Codex 연결">
    <h3>Codex 연결</h3>
    <p>Codex 채팅에서 프로젝트의 진행 상황과 멈춘 이유를 확인할 수 있어요.</p>
    {canRegister ? <>
      <p>앱에 포함된 연결 파일을 자동으로 설치해요. 새 버전의 앱을 열면 다음 Codex 연결에 반영돼요.</p>
      <button className="button button--secondary" type="button" disabled={registering} onClick={() => void register()}>
        {registering ? "Codex에 등록 중…" : "Codex에서 진행 상황 보기"}
      </button>
    </> : null}
    {message ? <p role="status">{message}</p> : null}
    {codexMissing ? <button className="button button--secondary" type="button" onClick={() => void showInstallGuide()}>Codex 설치 안내</button> : null}
    <details open={!canRegister}><summary>수동 연결 및 작업 권한 설정</summary>
      {command === null ? <p>소스에서 실행 중이면 MCP 옵션을 설치하고, <code>ai-orchestrator</code>를 PATH에 추가하세요.</p> : null}
      <label><input type="checkbox" checked={allowWrite} onChange={(event) => { setAllowWrite(event.target.checked); setMessage(""); }} /> 작업 변경 허용</label>
      <p>{allowWrite ? "기획서 연결, 작업 복구, 승인 후 로컬 Main 반영을 사용할 수 있어요." : "기본 연결은 조회만 허용해요."}</p>
      <p>AI 작업을 실행할 PC에는 Codex CLI 또는 Claude Code CLI를 설치해 주세요.</p>
      <button className="button button--secondary" type="button" disabled={!config} onClick={() => void copyConfig()}>Codex 설정 복사</button>
      <p>Codex의 <code>~/.codex/config.toml</code>에 붙여 넣으세요. <code>[mcp_servers.orchestrator]</code>가 있으면 그 블록을 교체하세요.</p>
      <p>Codex를 다시 열고 “오케스트레이터에 등록된 프로젝트 보여줘”라고 물어보세요.</p>
      {config ? <pre className="mcp-connection-config"><code>{config}</code></pre> : null}
      <p>작업 PC가 따로 있으면 그 PC의 앱 또는 MCP ZIP을 같은 사용자 계정에서 사설망 SSH로 실행하세요.</p>
    </details>
  </section>;
}
