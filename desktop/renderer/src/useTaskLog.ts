import { useCallback, useEffect, useRef, useState } from "react";
import { createTaskLogPoller, emptyTaskLog, selectTaskLogSnapshot, type TaskLogSnapshot } from "./logPolling";

export interface TaskLogState extends TaskLogSnapshot { refresh(): void; }

export function useTaskLog(resourceKey: string, enabled: boolean, load: () => Promise<string>): TaskLogState {
  const [state, setState] = useState<{ key: string; snapshot: TaskLogSnapshot }>({ key: "", snapshot: emptyTaskLog });
  const refreshRef = useRef<(() => Promise<void>) | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const poller = createTaskLogPoller(load, (snapshot) => setState({ key: resourceKey, snapshot }));
    refreshRef.current = poller.refresh;
    void poller.refresh();
    const timer = window.setInterval(() => void poller.refresh(), 2000);
    return () => {
      poller.stop();
      refreshRef.current = null;
      window.clearInterval(timer);
    };
  }, [enabled, resourceKey, load]);
  const refresh = useCallback(() => { void refreshRef.current?.(); }, []);
  // Mask old data synchronously, before the effect for a newly selected Task runs.
  const snapshot = selectTaskLogSnapshot(resourceKey, enabled, state);
  return { ...snapshot, refresh };
}
