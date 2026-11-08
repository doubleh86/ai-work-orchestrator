import type { RunSummary } from "./types";

export interface McpConnectionGuide {
  command: string;
  args: string[];
  registration_command: string;
  registration_args: string[];
}

export function readMcpConnectionGuide(value: unknown): McpConnectionGuide {
  if (!value || typeof value !== "object" || !("command" in value) || typeof value.command !== "string" || !value.command
    || !("args" in value) || !Array.isArray(value.args) || !value.args.every(arg => typeof arg === "string")
    || !("registration_command" in value) || typeof value.registration_command !== "string" || !value.registration_command
    || !("registration_args" in value) || !Array.isArray(value.registration_args)
    || !value.registration_args.every(arg => typeof arg === "string")) {
    throw new Error("MCP 연결 정보를 확인하지 못했습니다. 오케스트레이터를 다시 열어 주세요.");
  }
  return { command: value.command, args: value.args, registration_command: value.registration_command, registration_args: value.registration_args };
}

export function mcpConnectionPrompt(guide: McpConnectionGuide): string {
  const server = { command: guide.command, args: guide.args };
  const registration = { command: guide.registration_command,
    args: [...guide.registration_args, "--client", "<codex 또는 claude 또는 claude-code>"] };
  return [
    "AI Work Orchestrator를 현재 이 대화 앱의 로컬 MCP에 설치·연결해줘.",
    "현재 앱이 Codex인지 Claude Desktop인지 Claude Code인지 확인하고 알맞은 연결만 등록해줘.",
    "이 요청은 외부 대화 앱과 오케스트레이터를 연결하는 작업이야. 오케스트레이터의 여러 작업 AI·모델·계정 설정은 그대로 유지해줘.",
    "서버 이름: ai_work_orchestrator\n서버 실행 설정:\n" + JSON.stringify(server, null, 2),
    "로컬 명령 실행 권한이 있으면 아래 등록 도우미의 --client 값을 현재 앱에 맞게 바꾸어 실행해줘. 인자는 shell 문자열로 합치지 말고 각각 전달해줘.\n"
      + JSON.stringify(registration, null, 2),
    "도우미는 기존 다른 MCP 서버와 설정을 보존하고, Claude Desktop의 Windows Store판 설정 위치도 처리해.",
    "로컬 설정을 수정할 도구가 없으면 현재 앱에서 필요한 설치·설정 단계를 안내해줘. 프롬프트를 받거나 설정을 저장한 것만으로 연결됐다고 말하지 마.",
    "앱 재시작이 필요하면 알려줘. 재연결 후 orchestrator_help와 도구 목록을 읽어 실제 연결을 확인해줘.",
    "연결을 마치면 이 채팅에서 무엇을 만들지 나와 논의해줘. 합의한 내용은 get_planning_context 기준에 맞춰 submit_plan으로 전달해줘.",
    "오케스트레이터가 태스크를 생성하고 기존 작업 AI 설정으로 모델을 배정해 제작 준비 알림을 제공하게 해줘. 계획을 보여주고 내가 요청하면 제작을 시작해줘.",
    "처음 제작을 시작하기 전에 작업 AI·모델과 속도·품질·비용 기준을 짧게 확인해줘. 이미 합의한 설정은 다시 묻거나 임의로 바꾸지 마.",
    "실행·재개·검증 요청이 접수되면 접수 결과만 짧게 알려주고 바로 답변을 끝내줘. 접수를 실제 작업 시작이나 완료로 표현하지 마.",
    "진행 상황·완료·실패·직접 확인할 일은 오케스트레이터 UI와 알림에서 확인할게. 완료를 기다리거나 get_control_request·get_run·report_progress를 반복 조회하지 마.",
    "내가 상태를 묻거나 요청한 후속 행동에 필요한 경우에만 상태를 조회해줘. 답변을 끝내기 위해 MCP 연결을 끊거나 서버를 종료하지 마.",
  ].join("\n\n");
}

export function makerStage(run: Pick<RunSummary, "stage">): string {
  const labels: Record<string, string> = {
    reviewed: "계획 준비 중", planned: "계획 확인", executing: "만드는 중", ready_to_merge: "결과 검증 대기",
    verified: "결과 확인 가능", work_branch_pushed: "결과 저장됨", merged: "완성본에 반영됨", pushed: "업로드됨",
    deployed: "배포됨", failed: "도움이 필요해요",
  };
  return labels[run.stage] || "상태 확인 필요";
}

export function latestMakerRun(runs: RunSummary[]): RunSummary | undefined {
  return [...runs].filter(run => !run.archived).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
    ?? [...runs].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
}
