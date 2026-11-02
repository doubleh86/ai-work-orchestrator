export interface TaskLogSnapshot {
  value: string;
  error: string;
  loading: boolean;
  checkedAt?: number;
  changedAt?: number;
}
export const emptyTaskLog: TaskLogSnapshot = { value: "", error: "", loading: false };

/** Read-only poller with an explicit lifetime. Late responses never reach another Task. */
export function createTaskLogPoller(
  load: () => Promise<string>,
  publish: (snapshot: TaskLogSnapshot) => void,
  now: () => number = Date.now,
) {
  let alive = true;
  let inFlight = false;
  let snapshot: TaskLogSnapshot = { ...emptyTaskLog };
  return {
    async refresh(): Promise<void> {
      if (!alive || inFlight) return;
      inFlight = true;
      snapshot = { ...snapshot, loading: true };
      publish(snapshot);
      try {
        const value = await load();
        if (!alive) return;
        const at = now();
        snapshot = { value, error: "", loading: false, checkedAt: at,
          changedAt: value !== snapshot.value ? at : snapshot.changedAt };
        publish(snapshot);
      } catch (error: unknown) {
        if (!alive) return;
        snapshot = { ...snapshot, loading: false,
          error: `로그 갱신 실패: ${error instanceof Error ? error.message : String(error)}` };
        publish(snapshot);
      } finally { inFlight = false; }
    },
    stop(): void { alive = false; },
  };
}

export interface StoredTaskLog { key: string; snapshot: TaskLogSnapshot; }

export function selectTaskLogSnapshot(key: string, enabled: boolean, state: StoredTaskLog): TaskLogSnapshot {
  return enabled && state.key === key ? state.snapshot : { ...emptyTaskLog, loading: enabled };
}
