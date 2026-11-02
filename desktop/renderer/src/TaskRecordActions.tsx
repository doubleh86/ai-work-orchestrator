import { useState } from "react";
import { FileText } from "lucide-react";

export function TaskRecordActions({ projectName, runId, taskId }: {
  projectName: string; runId: string; taskId: string;
}) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const open = async () => {
    if (opening) return;
    setOpening(true);
    setError("");
    try {
      const opened = await window.orchestrator.openTaskRecord(projectName, runId, taskId);
      if (!opened) throw new Error("텍스트 편집기가 파일을 열지 못했습니다.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : String(requestError));
    } finally {
      setOpening(false);
    }
  };
  return <section className="task-record-actions" aria-label="작업 기록">
    <div className="task-record-actions__buttons">
      <button className="button button--secondary" type="button" disabled={opening} onClick={() => void open()}
        title="현재 로그와 작업 기록의 사본을 텍스트 편집기로 엽니다."><FileText aria-hidden="true" size={16} />{opening ? "파일 여는 중…" : "기록 파일 열기"}</button>
    </div>
    {error ? <p role="alert">기록 파일을 열지 못했습니다. {error}</p> : null}
  </section>;
}
