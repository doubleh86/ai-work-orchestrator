import { AlertCircle, CheckCircle2, GitCommit, RefreshCw, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { mainCanPull, mainCanPush, mainChangeLabel, mainSnapshotSummary } from "./mainChanges";
import type {
  MainChangeDiff,
  MainChangeSelectionMode,
  MainChangeSnapshot,
  MainMutationResult,
  RepositoryUpdate,
} from "./types";

interface MainChangesDialogProps {
  projectName: string;
  onClose(): void;
  onChanged(message: string): void;
  onError(message: string): void;
}

type SelectionMap = Record<string, MainChangeSelectionMode>;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function shortCommit(commit: string): string {
  return commit ? commit.slice(0, 8) : "미확인";
}

export function MainChangesDialog({ projectName, onClose, onChanged, onError }: MainChangesDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [snapshot, setSnapshot] = useState<MainChangeSnapshot>();
  const [selection, setSelection] = useState<SelectionMap>({});
  const [selectedPath, setSelectedPath] = useState("");
  const [difference, setDifference] = useState<MainChangeDiff>();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [resultMessage, setResultMessage] = useState("");
  const initialLoadStarted = useRef(false);

  const load = useCallback(async (refreshRemote: boolean) => {
    setBusy(refreshRemote ? "원격 상태 확인 중" : "변경 확인 중");
    setDifference(undefined);
    try {
      const next = await window.orchestrator.request<MainChangeSnapshot>(
        refreshRemote ? "projects.refreshMainRemote" : "projects.mainChanges",
        { projectName },
      );
      setSnapshot(next);
      setSelection({});
      setSelectedPath(next.changes[0]?.path || "");
    } catch (error) {
      onError(errorText(error));
    } finally {
      setBusy("");
    }
  }, [onError, projectName]);

  useEffect(() => {
    if (ref.current && !ref.current.open) ref.current.showModal();
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    void load(true);
  }, [load]);

  const selectedEntries = useMemo(() => snapshot?.changes
    .filter((change) => selection[change.path])
    .map((change) => ({ path: change.path, mode: selection[change.path] })) || [], [selection, snapshot]);

  const loadDiff = useCallback(async (path: string, mode?: MainChangeSelectionMode) => {
    if (!snapshot) return;
    const change = snapshot.changes.find((item) => item.path === path);
    if (!change) return;
    const selectedMode = mode || selection[path] || (change.staged && !change.unstaged ? "staged" : "whole");
    setSelectedPath(path);
    setBusy("diff 확인 중");
    try {
      setDifference(await window.orchestrator.request<MainChangeDiff>("projects.mainChangeDiff", {
        projectName,
        snapshotId: snapshot.snapshot_id,
        path,
        mode: selectedMode,
      }));
    } catch (error) {
      onError(errorText(error));
    } finally {
      setBusy("");
    }
  }, [onError, projectName, selection, snapshot]);

  const applyResult = useCallback((result: MainMutationResult, action: "commit" | "push") => {
    setSnapshot(result.snapshot);
    setSelection({});
    setDifference(undefined);
    setSelectedPath(result.snapshot.changes[0]?.path || "");
    if (result.phase === "push_failed") {
      setResultMessage(`${result.commit_created ? "커밋 완료 · Push 실패" : "Push 실패"}: ${result.error}`);
      return;
    }
    const text = action === "commit"
      ? `커밋 완료 ${shortCommit(result.commit)} · 로컬 변경 ${result.remaining_change_count}개 남음`
      : `Push 완료 ${shortCommit(result.commit)} · ${result.remaining_change_count ? `로컬 변경 ${result.remaining_change_count}개 남음` : "원격 상태 확인 완료"}`;
    setResultMessage(text);
    onChanged(text);
  }, [onChanged]);

  const commit = useCallback(async (push: boolean) => {
    if (!snapshot || !selectedEntries.length || !message.trim()) return;
    setBusy(push ? "커밋 후 Push 중" : "커밋 중");
    try {
      const result = await window.orchestrator.approve<MainMutationResult>(
        push ? "projects.commitAndPushMainChanges" : "projects.commitMainChanges",
        {
          projectName,
          snapshotId: snapshot.snapshot_id,
          selections: selectedEntries,
          selectionCount: selectedEntries.length,
          message: message.trim(),
          branch: snapshot.expected_branch,
          remote: snapshot.sync.remote,
          pushCommitCount: snapshot.sync.ahead || 0,
        },
      );
      if (result) {
        applyResult(result, push ? "push" : "commit");
        setMessage("");
      }
    } catch (error) {
      onError(errorText(error));
    } finally {
      setBusy("");
    }
  }, [applyResult, message, onError, projectName, selectedEntries, snapshot]);

  const push = useCallback(async () => {
    if (!snapshot) return;
    setBusy("Push 중");
    try {
      const result = await window.orchestrator.approve<MainMutationResult>("projects.pushMainCommits", {
        projectName,
        snapshotId: snapshot.snapshot_id,
        branch: snapshot.expected_branch,
        remote: snapshot.sync.remote,
        pushCommitCount: snapshot.sync.ahead || 0,
        commit: snapshot.sync.local_head,
      });
      if (result) applyResult(result, "push");
    } catch (error) {
      onError(errorText(error));
    } finally {
      setBusy("");
    }
  }, [applyResult, onError, projectName, snapshot]);

  const pull = useCallback(async () => {
    setBusy("최신 Main 받는 중");
    try {
      const result = await window.orchestrator.approve<RepositoryUpdate>("projects.updateMain", { projectName });
      if (result) {
        const next = await window.orchestrator.request<MainChangeSnapshot>("projects.refreshMainRemote", { projectName });
        setSnapshot(next);
        const text = result.before_commit === result.after_commit
          ? "동기화 완료 · 받을 변경 없음"
          : `Main 갱신 ${shortCommit(result.before_commit)} → ${shortCommit(result.after_commit)}`;
        setResultMessage(text);
        onChanged(text);
      }
    } catch (error) {
      onError(errorText(error));
    } finally {
      setBusy("");
    }
  }, [onChanged, onError, projectName]);

  const close = () => {
    if (busy) return;
    ref.current?.close();
    onClose();
  };

  return (
    <dialog ref={ref} className="modal main-changes-dialog" aria-labelledby="main-changes-title" onCancel={(event) => { event.preventDefault(); close(); }}>
      <form className="project-form" method="dialog" onSubmit={(event) => event.preventDefault()}>
        <header className="main-changes-heading">
          <div><span className="eyebrow">MAIN WORKTREE</span><h2 id="main-changes-title">Main 변경 검토</h2><p>{projectName} · {snapshot?.branch || "확인 중"}</p></div>
          <button className="icon-button" type="button" aria-label="닫기" disabled={Boolean(busy)} onClick={close}><X aria-hidden="true" size={18} /></button>
        </header>
        <div className="main-changes-summary" role="status" aria-live="polite">
          {busy ? <><RefreshCw className="spin" aria-hidden="true" size={16} /><strong>{busy}</strong></> : snapshot ? <><CheckCircle2 aria-hidden="true" size={16} /><strong>{mainSnapshotSummary(snapshot)}</strong></> : <span>변경 상태를 확인하고 있습니다.</span>}
          {snapshot ? <small>원격 {snapshot.sync.remote}/{snapshot.sync.target_branch} · local {shortCommit(snapshot.sync.local_head)} · remote {shortCommit(snapshot.sync.remote_head)}</small> : null}
        </div>
        {snapshot?.blocked_reason ? <p className="main-changes-warning"><AlertCircle aria-hidden="true" size={16} />{snapshot.blocked_reason}</p> : null}
        {snapshot?.sync.error ? <p className="main-changes-warning"><AlertCircle aria-hidden="true" size={16} />원격 상태를 확인하지 못했습니다. {snapshot.sync.error}</p> : null}
        {resultMessage ? <p className={resultMessage.includes("실패") ? "main-changes-warning" : "main-changes-result"}>{resultMessage}</p> : null}
        <div className="main-changes-body">
          <section className="main-changes-list" aria-label="Main 변경 목록">
            {snapshot?.changes.length ? snapshot.changes.map((change) => {
              const checked = Boolean(selection[change.path]);
              const selectedMode = selection[change.path] || (change.staged && !change.unstaged ? "staged" : "whole");
              return <div className="main-change-row" data-active={selectedPath === change.path} key={change.path}>
                <input
                  type="checkbox"
                  aria-label={`${change.path} 선택`}
                  checked={checked}
                  disabled={Boolean(busy || snapshot.blocked_reason)}
                  onChange={(event) => setSelection((current) => {
                    if (!event.target.checked) { const next = { ...current }; delete next[change.path]; return next; }
                    return { ...current, [change.path]: selectedMode };
                  })}
                />
                <button type="button" onClick={() => void loadDiff(change.path, selectedMode)}><strong>{change.path}</strong><span>{mainChangeLabel(change)}</span></button>
                {change.staged && change.unstaged ? <select
                  aria-label={`${change.path} 커밋 범위`}
                  disabled={!checked || Boolean(busy)}
                  value={selectedMode}
                  onChange={(event) => {
                    const mode = event.target.value as MainChangeSelectionMode;
                    setSelection((current) => ({ ...current, [change.path]: mode }));
                    if (selectedPath === change.path) void loadDiff(change.path, mode);
                  }}
                ><option value="staged">스테이징된 내용만</option><option value="whole">파일 전체 변경</option></select> : null}
              </div>;
            }) : <p className="muted-copy">로컬 변경이 없습니다.</p>}
            {snapshot?.excluded_count ? <small>앱 관리 기록 또는 비밀 파일 {snapshot.excluded_count}개는 커밋 후보와 diff에서 제외했습니다.</small> : null}
          </section>
          <section className="main-change-diff" aria-label="선택한 변경 내용">
            <strong>{difference ? `${difference.path} · ${difference.mode === "staged" ? "스테이징된 내용" : "파일 전체 변경"}` : "변경 전/후 내용"}</strong>
            <pre>{difference?.content || "파일을 선택하면 diff를 표시합니다."}</pre>
            {difference?.binary ? <small>binary 파일은 변경 사실만 표시합니다.</small> : null}
            {difference?.truncated ? <small>큰 diff는 앞부분만 표시합니다.</small> : null}
          </section>
        </div>
        <label className="main-commit-message"><span>커밋 메시지</span><input value={message} maxLength={500} disabled={Boolean(busy)} onChange={(event) => setMessage(event.target.value)} placeholder="변경 목적을 입력하세요" /></label>
        <footer>
          <button className="button button--quiet" type="button" disabled={Boolean(busy)} onClick={() => void load(true)}><RefreshCw aria-hidden="true" size={15} />원격 상태 확인</button>
          {snapshot && mainCanPull(snapshot) ? <button className="button button--secondary" type="button" disabled={Boolean(busy)} onClick={() => void pull()}>최신 Main 받기</button> : null}
          {snapshot && mainCanPush(snapshot) ? <button className="button button--secondary" type="button" disabled={Boolean(busy)} onClick={() => void push()}><UploadCloud aria-hidden="true" size={15} />기존 {snapshot.sync.ahead}개 commit Push</button> : null}
          <button className="button button--secondary" type="button" disabled={Boolean(busy || !selectedEntries.length || !message.trim() || snapshot?.blocked_reason)} onClick={() => void commit(false)}><GitCommit aria-hidden="true" size={15} />선택한 변경 커밋</button>
          <button className="button button--primary" type="button" disabled={Boolean(busy || !selectedEntries.length || !message.trim() || snapshot?.blocked_reason || snapshot?.sync.behind || snapshot?.sync.ahead === null)} onClick={() => void commit(true)}><UploadCloud aria-hidden="true" size={15} />커밋하고 Push</button>
        </footer>
      </form>
    </dialog>
  );
}
