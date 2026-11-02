import type { RunState } from "./types";

export interface DirectionChangeSubmission {
  readonly requestId: string;
  readonly text: string;
  readonly editRevision: number;
}

export interface DirectionChangeDraft {
  readonly text: string;
  readonly editRevision: number;
  readonly busy: boolean;
  readonly error: string;
  readonly pending?: DirectionChangeSubmission;
  readonly confirmed?: DirectionChangeSubmission;
}

export class DirectionChangeDrafts {
  private readonly drafts = new Map<string, DirectionChangeDraft>();
  private readonly listeners = new Set<() => void>();

  constructor(private readonly createRequestId: () => string = () => crypto.randomUUID()) {}

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  read(projectName: string, runId: string): DirectionChangeDraft {
    const key = JSON.stringify([projectName, runId]);
    let draft = this.drafts.get(key);
    if (!draft) {
      draft = { text: "", editRevision: 0, busy: false, error: "" };
      this.drafts.set(key, draft);
    }
    return draft;
  }

  edit(projectName: string, runId: string, text: string): void {
    const draft = this.read(projectName, runId);
    if (draft.text === text) return;
    this.save(projectName, runId, { ...draft, text, editRevision: draft.editRevision + 1 });
  }

  begin(projectName: string, runId: string): DirectionChangeSubmission | undefined {
    const draft = this.read(projectName, runId);
    const text = draft.text.trim();
    if (!text || draft.busy) return undefined;
    const pending: DirectionChangeSubmission = {
      requestId: draft.pending?.text === text ? draft.pending.requestId : this.createRequestId(),
      text, editRevision: draft.editRevision,
    };
    this.save(projectName, runId, { ...draft, pending, busy: true, error: "" });
    return pending;
  }

  confirm(projectName: string, runId: string, requestId: string, result: RunState): boolean {
    const draft = this.read(projectName, runId);
    if (draft.pending?.requestId !== requestId) return false;
    const receipt = result.direction_change_requests?.find((item) => item.request_id === requestId);
    if (result.id !== runId || !receipt || receipt.text !== draft.pending.text) {
      throw new Error("대상 그룹의 방향 수정 접수 기록이 요청과 일치하지 않습니다. 상태를 다시 확인하세요.");
    }
    this.save(projectName, runId, {
      ...draft, text: draft.editRevision === draft.pending.editRevision ? "" : draft.text,
      confirmed: draft.pending, pending: undefined, busy: false, error: "",
    });
    return true;
  }

  fail(projectName: string, runId: string, requestId: string, error: string): void {
    const draft = this.read(projectName, runId);
    if (draft.pending?.requestId !== requestId) return;
    this.save(projectName, runId, { ...draft, busy: false, error });
  }

  reconcile(projectName: string, run: RunState): void {
    const draft = this.read(projectName, run.id);
    const pending = draft.pending;
    if (!pending || !run.direction_change_requests?.some((item) => item.request_id === pending.requestId)) return;
    try { this.confirm(projectName, run.id, pending.requestId, run); }
    catch (cause) { this.fail(projectName, run.id, pending.requestId, cause instanceof Error ? cause.message : String(cause)); }
  }

  private save(projectName: string, runId: string, draft: DirectionChangeDraft): void {
    this.drafts.set(JSON.stringify([projectName, runId]), draft);
    for (const listener of this.listeners) listener();
  }
}
