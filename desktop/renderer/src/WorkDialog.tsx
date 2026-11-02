import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function WorkDialog({ title, titleId, context, open = true, onClose, children, footer, className = "", suspendPlanning = false, inline = false, portal = false }: {
  title: string; titleId?: string; context?: string; open?: boolean; onClose(): void; children: ReactNode;
  footer?: ReactNode; className?: string; suspendPlanning?: boolean; inline?: boolean; portal?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open || inline) return;
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const sidebar = suspendPlanning ? document.getElementById("planning-sidebar") as HTMLDialogElement | null : null;
    const suspended = Boolean(sidebar?.matches(":modal"));
    sidebar?.setAttribute("data-planning-start-open", "true");
    if (suspended) sidebar?.close();
    ref.current?.showModal();
    return () => {
      ref.current?.close();
      sidebar?.removeAttribute("data-planning-start-open");
      if (sidebar?.isConnected && !sidebar.open) {
        if (!window.matchMedia("(max-width: 74rem)").matches) sidebar.show();
        else if (suspended) sidebar.showModal();
      }
      if (previousFocus.current?.isConnected) previousFocus.current.focus({ preventScroll: true });
    };
  }, [open, suspendPlanning, inline]);
  if (inline) return <section id={titleId} tabIndex={-1} className={`work-panel ${className}`} hidden={!open} aria-label={title}>
    <div className="work-panel__body">{children}</div>
    {footer ? <footer className="work-panel__footer">{footer}</footer> : null}
  </section>;
  const dialog = <dialog ref={ref} className={`modal work-dialog ${className}`} aria-label={title}
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header className="work-dialog__heading"><div><h2 id={titleId} tabIndex={-1}>{title}</h2>{context ? <p>{context}</p> : null}</div>
      <button className="button button--quiet" type="button" onClick={onClose}>닫기</button></header>
    <div className="work-dialog__body">{children}</div>
    {footer ? <footer className="work-dialog__footer">{footer}</footer> : null}
  </dialog>;
  return portal && typeof document !== "undefined" ? createPortal(dialog, document.body) : dialog;
}
