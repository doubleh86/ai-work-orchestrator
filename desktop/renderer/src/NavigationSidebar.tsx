import { useEffect, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";

/** Keep navigation mounted so opening a compact menu does not reset the workspace. */
export function NavigationSidebar({ openRequest, children }: { openRequest: number; children: ReactNode }) {
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 60rem)").matches);
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 60rem)");
    const changed = () => { setCompact(query.matches); setOpen(false); };
    query.addEventListener("change", changed);
    return () => query.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    if (!openRequest || !compact) return;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpen(true);
  }, [openRequest]);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (dialog.open) dialog.close();
    if (!compact) dialog.show();
    else if (open) dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, [compact, open]);
  function close(restoreFocus: boolean) {
    if (!compact) return;
    dialogRef.current?.close(); setOpen(false);
    if (restoreFocus) returnFocus.current?.focus({ preventScroll: true });
  }
  return <dialog ref={dialogRef} id="main-navigation" className="navigation-sidebar" aria-label="주 메뉴"
    onCancel={(event) => { event.preventDefault(); close(true); }}
    onClick={(event) => { if ((event.target as Element).closest("[data-navigation-action]")) close(false); }}>
    <header className="navigation-sidebar__brand"><h1>AI Work<br />Orchestrator</h1>
      <button className="icon-button navigation-sidebar__close" type="button" aria-label="주 메뉴 닫기" onClick={() => close(true)}><X aria-hidden="true" size={18} /></button>
    </header>
    {children}
  </dialog>;
}
