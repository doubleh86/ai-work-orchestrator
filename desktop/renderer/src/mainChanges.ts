import type { MainChangeItem, MainChangeSnapshot, MainSyncStatus } from "./types";

const changeLabels: Record<string, string> = {
  added: "추가",
  copied: "복사",
  deleted: "삭제",
  modified: "수정",
  renamed: "이름 변경",
  type_changed: "형식 변경",
  conflicted: "충돌",
  untracked: "추적 안 됨",
  changed: "변경",
};

export function mainChangeLabel(change: MainChangeItem): string {
  const scope = change.staged && change.unstaged ? "staged + unstaged" : change.staged ? "staged" : "unstaged";
  return `${changeLabels[change.status] || change.status} · ${scope}`;
}

export function mainSyncLabel(sync: MainSyncStatus): string {
  if (sync.relation === "equal") return "보낼 커밋 0개 · 받을 커밋 0개";
  if (sync.relation === "ahead") return `보낼 커밋 ${sync.ahead ?? 0}개 · 받을 커밋 0개`;
  if (sync.relation === "behind") return `보낼 커밋 0개 · 받을 커밋 ${sync.behind ?? 0}개`;
  if (sync.relation === "diverged") return `보낼 커밋 ${sync.ahead ?? 0}개 · 받을 커밋 ${sync.behind ?? 0}개 · 통합 필요`;
  return "원격 상태 미확인";
}

export function mainSnapshotSummary(snapshot: MainChangeSnapshot): string {
  const local = `로컬 변경 ${snapshot.changes.length}개`;
  return `${local} · ${mainSyncLabel(snapshot.sync)}`;
}

export function mainCanPull(snapshot: MainChangeSnapshot): boolean {
  return !snapshot.blocked_reason && snapshot.changes.length === 0 && snapshot.sync.relation === "behind";
}

export function mainCanPush(snapshot: MainChangeSnapshot): boolean {
  return !snapshot.blocked_reason && snapshot.sync.relation === "ahead" && Boolean(snapshot.sync.ahead);
}
