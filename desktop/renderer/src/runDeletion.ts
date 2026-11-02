export interface RunDeletionLock {
  state: string;
}

export function runDeletionBlockMessage(lock: RunDeletionLock): string {
  if (lock.state === "active") {
    return "이 작업 그룹에서 작업이 실행 중입니다. 현재 작업이 끝난 뒤 삭제해 주세요.";
  }
  return "";
}

export function runMissingMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (!message.includes("unknown run:")) return "";
  return "현재 프로젝트에서 작업 그룹을 찾지 못해 목록을 새로고침했습니다. 계속 표시되면 실행 엔진을 재시작해 주세요.";
}

export const runDeletionMissingMessage = runMissingMessage;

export function runDeletionNeedsBackendRestart(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("작업공간이 다른 프로그램에서 사용 중입니다:")
    && /WinError (?:5|32|33)/.test(message);
}
