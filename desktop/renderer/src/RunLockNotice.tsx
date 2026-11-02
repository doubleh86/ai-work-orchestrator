import { useEffect, useRef, useState, type ReactNode } from "react";
import { RunLockRecoverySession, runLockAction, type RunLockRecoverySnapshot } from "./runLockRecovery";
import type { RunState } from "./types";

export function RunLockNotice({ projectName, runId, title, refreshKey, active = true, busy = false, activeOnCards = false, progressOperation = "", compact = false,
  onUpdated, onInspect, onBlocking, children }: {
  projectName: string; runId: string; title?: string; refreshKey?: string; active?: boolean; busy?: boolean; activeOnCards?: boolean; progressOperation?: string; compact?: boolean;
  onUpdated(run: RunState): void; onInspect(): void; onBlocking?(blocking: boolean, progressVisible: boolean): void; children?: ReactNode;
}) {
  const context = JSON.stringify([projectName, runId]);
  const [state, setState] = useState<{ context: string; snapshot: RunLockRecoverySnapshot }>();
  const snapshot = state?.context === context ? state.snapshot : undefined;
  const session = useRef<RunLockRecoverySession | undefined>(undefined);
  const callbacks = useRef({ onUpdated, onInspect, onBlocking });
  callbacks.current = { onUpdated, onInspect, onBlocking };
  useEffect(() => {
    setState(undefined);
    if (!active || !projectName || !runId) return;
    const owner = new RunLockRecoverySession(window.orchestrator, projectName, runId,
      (snapshot) => setState({ context, snapshot }));
    session.current = owner;
    return () => { owner.dispose(); if (session.current === owner) session.current = undefined; };
  }, [projectName, runId, active]);
  useEffect(() => {
    if (active) void session.current?.check();
  }, [projectName, runId, active, refreshKey]);
  const action = snapshot?.run && snapshot.lock ? runLockAction(snapshot.run, snapshot.lock) : undefined;
  const acting = snapshot?.phase === "acting";
  const checking = snapshot?.phase === "loading" || !snapshot;
  const readFailed = snapshot?.phase === "error" || checking && Boolean(snapshot?.error);
  const coveredByCards = activeOnCards && snapshot?.lock?.state === "active" && action?.kind !== "inspect";
  const coveredByOperation = Boolean(progressOperation && snapshot?.lock?.state === "active"
    && snapshot.lock.operation === progressOperation && action?.kind !== "inspect");
  const show = active && (!(coveredByCards || coveredByOperation) && action || snapshot?.error || snapshot?.message);
  const blocking = Boolean(show && (action && action.kind !== "stop" || readFailed));
  const progressVisible = Boolean(show && snapshot?.lock?.state === "active" && action && action.kind !== "inspect" && !readFailed);
  useEffect(() => { callbacks.current.onBlocking?.(blocking, progressVisible); }, [blocking, progressVisible]);
  if (!show) return <>{children}</>;
  const invoke = async () => {
    const owner = session.current;
    if (!owner || busy || acting || checking) return;
    if (snapshot?.phase === "error") {
      const updated = await owner.check();
      if (updated && session.current === owner) callbacks.current.onUpdated(updated);
      return;
    }
    if (action?.kind === "inspect") { callbacks.current.onInspect(); return; }
    const updated = action?.kind === "clear" || action?.kind === "stop" ? await owner.act(action.kind) : await owner.check();
    if (updated && session.current === owner) callbacks.current.onUpdated(updated);
  };
  return <>
    <section className="run-lock-notice" data-compact={compact || undefined} data-run-id={runId} role={snapshot?.error ? "alert" : "status"} aria-busy={checking || acting}>
      <div>{title ? <strong>{title}</strong> : null}<p>{snapshot?.message || (readFailed ? "잠금 상태 확인 실패" : action?.status)}</p>
        {action?.kind === "clear" && !readFailed && !compact ? <small>잠금만 해제 · 작업은 재개하지 않음</small> : null}</div>
      {action || readFailed ? <button className={`button button--${action?.kind === "clear" ? "primary" : action?.kind === "stop" ? "danger" : "secondary"}`}
        type="button" disabled={busy || acting || checking} onClick={() => void invoke()}>{acting ? "처리 중…" : readFailed ? "다시 확인" : action?.label || "다시 확인"}</button> : null}
      <details data-dismiss-on-outside={compact || undefined}><summary>{compact ? "상세" : "잠금 기록"}</summary><div>
        {compact && action?.kind === "clear" && !readFailed ? <p>잠금만 해제 · 작업은 재개하지 않음</p> : null}
        <p>작업 그룹 · {runId}</p>{snapshot?.lock ? <p>{snapshot.lock.operation} · {snapshot.lock.reason}</p> : null}
        {snapshot?.error ? <pre>{snapshot.error}</pre> : null}</div></details>
    </section>
    {!action ? children : null}
  </>;
}
