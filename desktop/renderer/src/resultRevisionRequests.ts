import type { ResultRevisionProposal, ResultRevisionRequest } from "./types";

export interface ResultRevisionPending {
  readonly id: string;
  readonly action: "generate" | "save";
}

export interface ResultRevisionRequestState {
  readonly editorOpen: boolean;
  readonly pending?: ResultRevisionPending;
  readonly proposal?: ResultRevisionProposal;
  readonly saved?: ResultRevisionRequest;
  readonly error: string;
}

export function resultRevisionRequestKey(projectName: string, runId: string, taskId = ""): string {
  return JSON.stringify([projectName, runId, taskId]);
}

export class ResultRevisionRequests {
  private readonly states = new Map<string, ResultRevisionRequestState>();
  private readonly listeners = new Set<() => void>();

  constructor(private readonly createId: () => string = () => crypto.randomUUID()) {}

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  read(key: string): ResultRevisionRequestState {
    let state = this.states.get(key);
    if (!state) {
      state = { editorOpen: false, error: "" };
      this.states.set(key, state);
    }
    return state;
  }

  setEditorOpen(key: string, editorOpen: boolean): void {
    const current = this.read(key);
    if (current.editorOpen !== editorOpen) this.save(key, { ...current, editorOpen });
  }

  begin(key: string, action: ResultRevisionPending["action"]): ResultRevisionPending | undefined {
    const current = this.read(key);
    if (current.pending) return undefined;
    const pending = { id: this.createId(), action };
    this.save(key, { ...current, pending, error: "" });
    return pending;
  }

  complete(key: string, pending: ResultRevisionPending, result: {
    proposal?: ResultRevisionProposal; saved?: ResultRevisionRequest; error?: string;
  }): void {
    const current = this.read(key);
    if (current.pending !== pending) return;
    this.save(key, { ...current, ...result, pending: undefined, error: result.error || "" });
  }

  fail(key: string, pending: ResultRevisionPending, error: string): void {
    const current = this.read(key);
    if (current.pending === pending) this.save(key, { ...current, pending: undefined, error });
  }

  private save(key: string, state: ResultRevisionRequestState): void {
    this.states.set(key, state);
    for (const listener of this.listeners) listener();
  }
}
