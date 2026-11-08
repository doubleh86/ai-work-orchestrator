import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function WorkDialog({ title, titleId, context, open = true, onClose, children, footer, className = "", portal = false }: {
  title: string; titleId?: string; context?: string; open?: boolean; onClose(): void; children: ReactNode;
  footer?: ReactNode; className?: string; portal?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.showModal();
    return () => {
      ref.current?.close();
      if (previousFocus.current?.isConnected) previousFocus.current.focus({ preventScroll: true });
    };
  }, [open]);
  const dialog = <dialog ref={ref} className={`modal work-dialog ${className}`} aria-label={title}
    onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <header className="work-dialog__heading"><div><h2 id={titleId} tabIndex={-1}>{title}</h2>{context ? <p>{context}</p> : null}</div>
      <button className="button button--quiet" type="button" onClick={onClose}>닫기</button></header>
    <div className="work-dialog__body">{children}</div>
    {footer ? <footer className="work-dialog__footer">{footer}</footer> : null}
  </dialog>;
  return portal && typeof document !== "undefined" ? createPortal(dialog, document.body) : dialog;
}
