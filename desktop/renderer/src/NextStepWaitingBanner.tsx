import type { NextStepWaitingPrompt } from "./types";

export function NextStepWaitingBanner({ prompt, busy, onAction, onLater }: {
  prompt: NextStepWaitingPrompt;
  busy: boolean;
  onAction(): void;
  onLater(): void;
}) {
  const labels = { retry: "이 Task 재시도", resume: "남은 Task 계속", verify: "통합 검증 시작", operations: "반영 내용 확인" };
  return <section className="run-next-action run-next-action--waiting" data-tone="warning" aria-label="다음 단계 선택 대기"
    data-attention-waiting={prompt.source_key} tabIndex={-1}>
    <div className="run-next-action__layout">
      <div className="run-next-action__copy"><span>다음 단계 선택 대기</span><strong>{prompt.question}</strong>
        {prompt.next_task_title ? <p>다음 작업 · {prompt.next_task_title}</p> : null}
        <small>한 단계씩 진행합니다. 실행이나 Main 반영은 자동으로 시작되지 않습니다.</small>
      </div>
      <div className="run-next-action__actions">
        <button type="button" className="button button--primary" disabled={busy} onClick={onAction}>{busy ? "현재 상태 확인 중" : labels[prompt.action]}</button>
        <button type="button" className="button button--quiet" disabled={busy} onClick={onLater}>나중에</button>
      </div>
    </div>
  </section>;
}
