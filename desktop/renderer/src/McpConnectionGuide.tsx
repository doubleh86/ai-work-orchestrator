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

  async function copyConfig() {
    try {
      await navigator.clipboard.writeText(config);
      setMessage("Codex 설정을 복사했습니다.");
    } catch {
      setMessage("복사하지 못했습니다. 아래 설정을 직접 선택해 복사해 주세요.");
    }
  }

  return <section className="work-settings__card" aria-label="MCP 연결">
    <h3>MCP 연결</h3>
    <p>Codex 채팅에서 등록된 프로젝트의 진행 상황과 멈춘 이유를 확인할 수 있어요.</p>
    {command === null ? <p>소스에서 실행 중이면 MCP 옵션을 설치하고, <code>ai-orchestrator</code>를 PATH에 추가하세요.</p> : null}
    <label><input type="checkbox" checked={allowWrite} onChange={(event) => { setAllowWrite(event.target.checked); setMessage(""); }} /> 작업 변경 허용</label>
    <p>{allowWrite ? "기획서 연결, 작업 복구, 승인 후 로컬 Main 반영을 사용할 수 있어요." : "기본 연결은 조회만 허용해요."}</p>
    <button className="button button--secondary" type="button" disabled={!config} onClick={() => void copyConfig()}>Codex 설정 복사</button>
    <p>Codex의 <code>~/.codex/config.toml</code>에 붙여 넣으세요. <code>[mcp_servers.orchestrator]</code>가 있으면 그 블록을 교체하세요.</p>
    <p>Codex를 다시 열고 “오케스트레이터에 등록된 프로젝트 보여줘”라고 물어보세요.</p>
    {config ? <pre className="mcp-connection-config"><code>{config}</code></pre> : null}
    {message ? <p role="status">{message}</p> : null}
    <details><summary>별도 ZIP 또는 다른 PC에서 사용</summary>
      <p>Windows 릴리즈의 MCP ZIP을 풀고, 설정의 <code>command</code>에 포함된 <code>ai-orchestrator-backend.exe</code>의 전체 경로를 넣으세요.</p>
      <p>작업 PC가 따로 있으면 그 PC의 앱 또는 MCP ZIP을 같은 사용자 계정에서 사설망 SSH로 실행하세요. 같은 계정의 프로젝트 목록을 읽습니다.</p>
    </details>
  </section>;
}
