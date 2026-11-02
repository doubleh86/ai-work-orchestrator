import { useEffect, useRef, useState, type ReactNode } from "react";
import { MessageSquare, X } from "lucide-react";

// Keep this contract in sync with the primary details overlay media query in chat-first.css.
export const PRIMARY_DETAILS_OVERLAY_QUERY = "(max-width: 60rem)";

export function PlanningSidebar({ context, onTarget, openRequest = 0, primary = false, inactive = false, status }: {
  context: string; onTarget(target: HTMLDivElement | null): void; openRequest?: number;
  primary?: boolean; inactive?: boolean; status?: ReactNode;
}) {
  const [compact, setCompact] = useState(() => window.matchMedia(primary ? PRIMARY_DETAILS_OVERLAY_QUERY : "(max-width: 74rem)").matches);
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const backgroundFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const query = window.matchMedia(primary ? PRIMARY_DETAILS_OVERLAY_QUERY : "(max-width: 74rem)");
    const changed = () => { setCompact(query.matches); if (!query.matches) setOpen(false); };
    changed();
    query.addEventListener("change", changed);
    return () => query.removeEventListener("change", changed);
  }, [primary]);
  useEffect(() => {
    if (primary && inactive && compact) {
      const focused = document.activeElement;
      if (focused instanceof HTMLElement && dialogRef.current?.contains(focused)) {
        backgroundFocus.current = focused;
        document.querySelector<HTMLElement>('#chat-work-details button:not(:disabled)')?.focus({ preventScroll: true });
      }
    } else if (backgroundFocus.current) {
      const target = backgroundFocus.current;
      backgroundFocus.current = null;
      if (target.isConnected && !target.closest("[inert]")) target.focus({ preventScroll: true });
    }
  }, [primary, inactive, compact]);
  useEffect(() => {
    if (!openRequest) return;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (compact && !primary) setOpen(true);
    else dialogRef.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true });
  }, [openRequest]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (primary) {
      if (dialog.matches(":modal")) dialog.close();
      if (!dialog.open) dialog.show();
      return;
    }
    if (dialog.open) dialog.close();
    if (!dialog.hasAttribute("data-message-detail-open") && !dialog.hasAttribute("data-planning-start-open") && !dialog.hasAttribute("data-planning-preview-open")) {
      if (!compact) dialog.show();
      else if (open) dialog.showModal();
    }
    return () => { if (dialog.open) dialog.close(); };
  }, [compact, open, primary]);
  function close() {
    dialogRef.current?.close();
    setOpen(false);
    const target = returnFocus.current?.isConnected ? returnFocus.current : launcherRef.current;
    target?.focus({ preventScroll: true });
  }
  return <>
    {!primary ? <button ref={launcherRef} className="button button--secondary planning-chat-launcher" type="button"
      aria-haspopup="dialog" aria-controls="planning-sidebar" aria-expanded={compact && open}
      onClick={() => { returnFocus.current = launcherRef.current; setOpen(true); }}>
      <MessageSquare size={16} aria-hidden="true" />Planning AI
    </button> : null}
    <dialog ref={dialogRef} id="planning-sidebar" className={`planning-sidebar${primary ? " planning-sidebar--primary" : ""}`}
      data-primary-chat={primary} inert={primary && inactive && compact} aria-labelledby="planning-sidebar-title"
      onCancel={(event) => { event.preventDefault(); if (!primary) close(); }}>
      <header className="planning-sidebar__header"><div><h2 id="planning-sidebar-title">Planning AI</h2><p title={context}>{context || "프로젝트를 선택하세요."}</p></div>
        <button className="icon-button planning-sidebar__close" type="button" aria-label="Planning AI 닫기" onClick={close}><X size={18} aria-hidden="true" /></button>
      </header>
      {primary ? status : null}
      <div ref={onTarget} className="planning-sidebar__content" />
    </dialog>
  </>;
}
