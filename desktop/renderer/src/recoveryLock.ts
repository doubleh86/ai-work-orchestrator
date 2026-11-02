import type { DesktopApi } from "../../shared/rpc";
import type { RunLockStatus } from "./types";

export interface RecoveryError {
  message: string;
  details: string;
  canClearLock: boolean;
}

export async function describeRecoveryError(
  cause: unknown,
  api: Pick<DesktopApi, "request">,
  projectName: string,
  runId: string,
): Promise<RecoveryError> {
  const details = String(cause);
  if (!details.includes("is already locked")) return { message: details, details: "", canClearLock: false };
  try {
    const lock = await api.request<RunLockStatus>("locks.get", { projectName, runId });
    if (lock.state === "stale") return {
      message: "이전 작업이 종료됐지만 잠금이 남아 있습니다. 아래 ‘잠금 해제 후 다시 조회’를 눌러 잠금을 해제해 주세요.",
      details, canClearLock: true,
    };
    if (lock.state === "active") return {
      message: "다른 작업이 이 그룹의 잠금을 사용 중입니다. 작업이 끝난 뒤 복구안을 다시 조회해 주세요.",
      details, canClearLock: false,
    };
    if (lock.state === "unlocked") return {
      message: "이전 작업의 잠금이 해제됐습니다. ‘복구안 다시 조회’를 눌러 주세요.",
      details, canClearLock: false,
    };
    return { message: "잠금 소유 프로세스를 확인할 수 없습니다. ‘통합·정리’에서 실행 잠금 상태를 확인해 주세요.", details, canClearLock: false };
  } catch (error) {
    return {
      message: "다른 작업의 잠금이 남아 있지만 상태 조회에 실패했습니다. ‘통합·정리’에서 실행 잠금 상태를 확인해 주세요.",
      details: `${details}\n잠금 상태 조회 실패: ${String(error)}`, canClearLock: false,
    };
  }
}
