export const progressPhaseLabels: Record<string, string> = {
  provider_retry_wait: "AI 서버 혼잡 · 재시도 대기",
  turn_started: "Codex 시작 중",
  analyzing_request: "분석 중",
  organizing_plan: "작업 순서 정리 중",
  plan_step: "계획 수행 중",
  searching_files: "파일 검색 중",
  reading_documents: "문서·코드 확인 중",
  checking_repository: "Git 상태 확인 중",
  analyzing_project: "프로젝트 분석 중",
  running_command: "명령 실행 중",
  applying_changes: "코드 수정 중",
  calling_tool: "도구 실행 중",
  searching_web: "웹 검색 중",
  inspecting_image: "이미지 확인 중",
  compacting_context: "대화 맥락 정리 중",
  coordinating_agents: "보조 작업 조율 중",
  writing_response: "응답 작성 중",
  response_received: "Codex 응답 수신",
  command_finished: "명령 실행 종료",
  changes_finished: "파일 변경 결과",
  preparing_task: "다음 작업 실행 준비 중",
  preparing_verification: "검증 환경 확인 중",
  verifying_command: "검증 명령 실행 중",
  checking_verification_result: "검증 결과 확인 중",
};

interface ProgressRow {
  raw: string;
  attemptId: string;
  invocationId: string;
  turnId: string;
  itemId: string;
  phase: string;
  detail: string;
  receivedAt: string;
  eventSeq: number;
}

function parseProgressRow(raw: string): ProgressRow | undefined {
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return undefined;
    const row = value as Record<string, unknown>;
    if (row.event !== "turn-progress" || typeof row.phase !== "string") return undefined;
    const attemptId = typeof row.attempt_id === "string" ? row.attempt_id : "";
    const invocationId = typeof row.invocation_id === "string" ? row.invocation_id : "";
    const eventSeq = typeof row.event_seq === "number" ? row.event_seq : 0;
    return {
      raw, attemptId, invocationId,
      turnId: typeof row.turn_id === "string" ? row.turn_id : "",
      itemId: typeof row.item_id === "string" ? row.item_id : "",
      phase: row.phase,
      detail: typeof row.detail === "string" ? row.detail : "",
      receivedAt: typeof row.received_at === "string" && row.received_at ? row.received_at
        : typeof row.at === "string" ? row.at : "",
      eventSeq,
    };
  } catch { return undefined; }
}

function clock(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "시각 미기록";
  return new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function summarizeSdkEvent(raw: string): string | undefined {
  if (raw.startsWith("…") && /"(?:event_seq|invocation_id|transport|evidence_kind)"\s*:/.test(raw)) {
    return "[로그 구간의 첫 기록이 잘렸습니다. 기술 정보의 원문 로그를 확인하세요.]";
  }
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return undefined;
    const row = value as Record<string, unknown>;
    if (row.transport !== "codex-sdk" || typeof row.event !== "string") return undefined;
    const labels: Record<string, string> = {
      "turn-request": "AI 실행 요청", "execution-profile": "실행 설정 확인", "turn-completed": "AI 호출 종료",
      "turn-failed": "AI 호출 실패", "turn-timeout": "AI 응답 대기 시간 초과", "turn-stopped": "AI 실행 중지",
    };
    const label = labels[row.event];
    if (!label) return undefined;
    const stringValue = (key: string) => typeof row[key] === "string" ? row[key] as string : "";
    let detail = "";
    if (row.event === "turn-request" || row.event === "execution-profile") {
      detail = [stringValue("effective_model") || stringValue("model"),
        stringValue("effective_reasoning_effort") || stringValue("reasoning_effort")].filter(Boolean).join(" · ");
    } else if (row.event === "turn-completed") {
      const status = stringValue("status");
      const statuses: Record<string, string> = { completed: "응답 수신", failed: "실패", interrupted: "중단" };
      detail = statuses[status] || status || "상태 미기록";
      if (stringValue("final_response")) detail += `\n${stringValue("final_response")}`;
    } else {
      detail = stringValue("error") || (stringValue("reason") === "user_requested" ? "사용자 요청" : stringValue("reason"));
    }
    return `[${clock(stringValue("at"))}] ${label}${detail ? ` · ${detail}` : ""}`;
  } catch { return undefined; }
}

function renderGroup(rows: ProgressRow[]): string {
  const first = rows[0];
  const last = rows.at(-1) || first;
  const label = progressPhaseLabels[first.phase] || first.phase;
  const detail = first.detail ? ` · ${first.detail}` : "";
  if (rows.length === 1) return `[${clock(first.receivedAt)}] ${label}${detail}`;
  return `[${clock(first.receivedAt)}~${clock(last.receivedAt)}] ${label}${detail} · ${rows.length}회 보고`;
}

function canGroup(previous: ProgressRow, next: ProgressRow): boolean {
  return Boolean(previous.attemptId && previous.invocationId && previous.eventSeq && next.eventSeq)
    && previous.attemptId === next.attemptId
    && previous.invocationId === next.invocationId
    && previous.turnId === next.turnId
    && previous.itemId === next.itemId
    && previous.phase === next.phase
    && previous.detail === next.detail
    && next.eventSeq > previous.eventSeq;
}

export interface ProgressLogSummary {
  text: string;
  originalLineCount: number;
  displayedLineCount: number;
  groupedReportCount: number;
}

export function summarizeProgressLog(raw: string): ProgressLogSummary {
  const source = raw ? raw.split(/\r?\n/) : [];
  const output: string[] = [];
  let group: ProgressRow[] = [];
  let groupedReportCount = 0;
  const flush = () => {
    if (!group.length) return;
    output.push(renderGroup(group));
    if (group.length > 1) groupedReportCount += group.length;
    group = [];
  };
  for (const line of source) {
    const row = parseProgressRow(line);
    if (!row) {
      flush();
      output.push(summarizeSdkEvent(line) ?? line);
      continue;
    }
    if (!group.length || canGroup(group.at(-1) as ProgressRow, row)) group.push(row);
    else { flush(); group.push(row); }
  }
  flush();
  const text = output.join("\n");
  return { text, originalLineCount: source.length, displayedLineCount: text ? text.split(/\r?\n/).length : 0, groupedReportCount };
}
