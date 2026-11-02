import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChatMarkdown } from "./ChatMarkdown";

export interface FullPlanningMessage { scope: string; key: string; text: string; meta: string; }

export function PlanningMessageDialog({ message, onClose }: { message: FullPlanningMessage; onClose(): void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const generation = useRef(0);
  const copying = useRef(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const sidebar = document.getElementById("planning-sidebar") as HTMLDialogElement | null;
    const suspended = Boolean(sidebar?.matches(":modal"));
    sidebar?.setAttribute("data-message-detail-open", "true");
    if (suspended) sidebar?.close();
    dialog.showModal();
    return () => {
      generation.current++;
      dialog.close();
      sidebar?.removeAttribute("data-message-detail-open");
      if (sidebar?.isConnected && !sidebar.open) {
        if (!window.matchMedia("(max-width: 74rem)").matches) sidebar.show();
        else if (suspended) sidebar.showModal();
      }
      if (previous?.isConnected && previous.getClientRects().length) previous.focus({ preventScroll: true });
    };
  }, [message.key]);
  async function copy() {
    if (copying.current) return;
    copying.current = true;
    const current = ++generation.current;
    setStatus("복사 중…"); setError("");
    try {
      await navigator.clipboard.writeText(message.text);
      if (current === generation.current) setStatus("전체 내용을 복사했습니다.");
    } catch (cause) {
      if (current === generation.current) { setStatus(""); setError(`전체 내용을 복사하지 못했습니다. 다시 시도하세요. ${String(cause)}`); }
    } finally {
      if (current === generation.current) copying.current = false;
    }
  }
  return createPortal(<dialog ref={dialogRef} id="planning-message-dialog" className="planning-message-dialog" aria-labelledby="planning-message-dialog-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header><div><h2 id="planning-message-dialog-title">대화 전체 내용</h2><p>{message.meta}</p></div>
      <button className="button button--quiet" type="button" onClick={onClose}>닫기</button></header>
    <div className="planning-message-dialog__body" tabIndex={0}><ChatMarkdown text={message.text} /></div>
    <footer><button className="button button--secondary" type="button" disabled={status === "복사 중…"} onClick={() => void copy()}>전체 내용 복사</button>
      {status ? <span role="status">{status}</span> : null}{error ? <p role="alert">{error}</p> : null}</footer>
  </dialog>, document.body);
}
