import { providerFailurePresentation } from "./providerFailure";

interface FailurePresentation {
  title: string;
  description: string;
}

export function isTaskVerificationTimeout(error: string, action = ""): boolean {
  return error.includes("Task 검증 시간 초과") || error.includes("Task 검증 전체 제한시간을 초과했습니다:")
    || action === "verify" && /^command timed out after /i.test(error);
}

export function isTaskScopeReview(error: string): boolean {
  return /(?:^|application_error:\s*)task_scope_review_required:/.test(error);
}

/** Summarize confirmed failures without showing diagnostic output by default. */
export function failurePresentation(error: string, action = ""): FailurePresentation {
  if (isTaskScopeReview(error)) return {
    title: "수정 범위 확인이 필요합니다",
    description: "AI가 필요한 파일의 허용 범위 변경을 요청했습니다. 채팅에서 경로와 이유를 검토하고 계획에 반영한 뒤 계속하세요.",
  };
  if (isTaskVerificationTimeout(error, action)) return {
    title: "검증 시간 초과 · 완료 여부 미확인",
    description: error.includes("같은 검증 조건에서 시간 초과가 반복")
      ? "같은 조건의 검증을 반복하지 않습니다. 지연되는 테스트를 확인해야 합니다."
      : "검증 시간을 늘린 뒤 결과를 다시 확인할 수 있습니다. 구현을 다시 시작하지 않습니다.",
  };
  const provider = providerFailurePresentation(error);
  if (provider) return { title: provider.title, description: provider.description };
  if (error.includes("실행 중인 앱이 빌드 출력 파일을 사용하고 있어")
    || /\bMSB302[127]\b[^\r\n]*(?:locked by|being used by another process|다른 프로세스|잠겨)/i.test(error)) return {
    title: "실행 중인 앱이 작업 파일을 사용하고 있습니다",
    description: "해당 앱을 닫은 뒤 다시 확인해 주세요.",
  };
  const accessDenied = /access (?:to [^\r\n]* )?is denied|permission denied|액세스.*거부|접근.*거부/i.test(error);
  if (accessDenied && /\bMSB(?:4018|3101)\b/.test(error)) return {
    title: "빌드 파일에 접근할 수 없습니다",
    description: "파일 접근 문제를 해결해야 합니다. AI에게 도움을 요청해 주세요.",
  };
  if (/change scope violation|outside expected_paths|forbidden path/i.test(error)) return {
    title: "허용된 작업 범위를 벗어난 변경이 있습니다",
    description: "AI와 변경 범위를 확인한 뒤 진행해 주세요.",
  };
  if (/produced no commit/i.test(error)) return {
    title: "작업의 변경 기록을 확인하지 못했습니다",
    description: "기존 작업 결과를 확인해야 합니다. AI에게 도움을 요청해 주세요.",
  };
  if (/is already locked \(operation=/.test(error)) return {
    title: "다른 요청의 잠금 때문에 진행하지 못했습니다",
    description: "현재 요청 상태를 확인한 뒤 다시 시도해 주세요.",
  };
  if (error.includes("Claude 로그인이 필요합니다.") || error.includes("Claude 로그인이 만료되었거나 인증에 실패했습니다.")) return {
    title: "Claude 로그인이 필요합니다",
    description: "AI 연결에서 ‘Claude 로그인’을 완료한 뒤 ‘연결 다시 확인’을 눌러 주세요.",
  };
  if (/not authenticated|authentication required|로그인이 필요|로그인.*만료/i.test(error)) return {
    title: "로그인 상태를 확인해야 합니다",
    description: "계정 연결을 확인한 뒤 다시 시도해 주세요.",
  };
  if (accessDenied) return {
    title: "파일 접근 권한 때문에 진행하지 못했습니다",
    description: "접근 권한을 확인한 뒤 다시 시도해 주세요.",
  };
  if (/\btimed out\b|\bTimeoutError\b|제한\s*시간.*초과|시간\s*초과/i.test(error)) return {
    title: "응답을 기다리는 시간이 초과되었습니다",
    description: "현재 진행 상태를 확인한 뒤 다시 시도해 주세요.",
  };
  if (/검증 자동 수정 한도 \d+회에 도달/.test(error)) return {
    title: "자동 수정 후에도 검사를 통과하지 못했습니다",
    description: "반복된 문제를 확인해야 합니다. AI에게 도움을 요청해 주세요.",
  };
  if (/통합 검증 명령이 실패했습니다:/.test(error)) return {
    title: "최종 동작 검사를 통과하지 못했습니다",
    description: "검사에서 발견된 문제를 수정해야 합니다. 결과 검사를 다시 실행하면 자동 수정을 시도합니다.",
  };
  const text = error.trim();
  if (text !== "실패 상세가 기록되지 않았습니다." && /[가-힣]/.test(text) && text.length <= 180
    && !/[\r\n{}]|[A-Za-z]:[\\/]|Traceback|application_error|exit code|PythonBridgeRequestError|MSB\d+|expected_paths/i.test(text)) {
    return { title: text, description: "입력과 현재 상태를 확인한 뒤 다시 시도해 주세요." };
  }
  return {
    title: action === "verify" ? "동작 확인을 통과하지 못했습니다"
      : action === "review" ? "내용 점검을 통과하지 못했습니다"
        : action ? "작업을 마치지 못했습니다" : "요청을 처리하지 못했습니다",
    description: "확인된 정보만으로 원인을 특정하지 못했습니다. AI에게 도움을 요청해 주세요.",
  };
}
