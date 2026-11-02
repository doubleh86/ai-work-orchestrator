import { useId, useLayoutEffect, useRef, useState } from "react";
import { ChatMarkdown } from "./ChatMarkdown";
import type { PlanningMessage } from "./types";

export function planningMessageKey(
  projectName: string, runId: string, message: Pick<PlanningMessage, "role" | "at">, index: number,
): string {
  return JSON.stringify([projectName, runId, message.role, message.at, index]);
}

export function planningMessageOverflows(scrollHeight: number, lineHeight: number, lines = 3): boolean | null {
  if (!Number.isFinite(scrollHeight) || !Number.isFinite(lineHeight) || scrollHeight < 0 || lineHeight <= 0) return null;
  return scrollHeight > lineHeight * lines + 1;
}

export function scrollPlanningContentIntoView(target: Element, block: "start" | "nearest" | "center" = "nearest"): void {
  for (let pane = target.parentElement; pane; pane = pane.parentElement) {
    const boundary = pane.matches(".task-workbench__body");
    if (pane.matches(".planning-messages, .planning-workbench, .task-workbench__body")
      && /^(auto|scroll)$/.test(window.getComputedStyle(pane).overflowY) && pane.scrollHeight > pane.clientHeight) {
      const targetRect = target.getBoundingClientRect();
      const paneTop = pane.getBoundingClientRect().top + pane.clientTop;
      const top = targetRect.top - paneTop;
      const bottom = targetRect.bottom - paneTop;
      const delta = block === "start" ? top : block === "center" ? top - (pane.clientHeight - targetRect.height) / 2
        : top < 0 ? top : bottom > pane.clientHeight ? bottom - pane.clientHeight : 0;
      pane.scrollTop = Math.max(0, Math.min(pane.scrollHeight - pane.clientHeight, pane.scrollTop + delta));
      return;
    }
    if (boundary) return;
  }
}

export function PlanningMessageDisclosure({ text, displayText = text, onExpandedChange, inline = false }: {
  text: string;
  displayText?: string;
  expanded: boolean;
  onExpandedChange(expanded: boolean): void;
  inline?: boolean;
}) {
  const bodyId = useId();
  const bodyRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const copyRef = useRef<HTMLButtonElement>(null);
  const copyPending = useRef(false);
  const copyGeneration = useRef(0);
  const [overflow, setOverflow] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"" | "copying" | "copied">("");
  const [copyError, setCopyError] = useState("");

  useLayoutEffect(() => {
    if (inline) return;
    const body = bodyRef.current;
    if (!body) return;
    let current = true;
    const measure = () => {
      if (!current || body.clientWidth <= 0) return;
      const measured = planningMessageOverflows(body.scrollHeight, Number.parseFloat(window.getComputedStyle(body).lineHeight));
      if (measured === null) return;
      if (!measured && displayText === text && toggleRef.current && document.activeElement === toggleRef.current) {
        copyRef.current?.focus({ preventScroll: true });
      }
      setOverflow(measured);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(measure);
    observer?.observe(body);
    window.addEventListener("resize", measure);
    const fonts = document.fonts;
    fonts?.addEventListener("loadingdone", measure);
    void fonts?.ready.then(measure);
    return () => {
      current = false;
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      fonts?.removeEventListener("loadingdone", measure);
    };
  }, [displayText, text, inline]);

  useLayoutEffect(() => {
    copyGeneration.current++;
    copyPending.current = false;
    setCopyStatus("");
    setCopyError("");
    return () => { copyGeneration.current++; copyPending.current = false; };
  }, [text]);

  const copy = async () => {
    if (copyPending.current) return;
    copyPending.current = true;
    const generation = ++copyGeneration.current;
    setCopyStatus("copying");
    setCopyError("");
    try {
      await navigator.clipboard.writeText(text);
      if (generation === copyGeneration.current) setCopyStatus("copied");
    } catch (cause) {
      if (generation === copyGeneration.current) {
        setCopyStatus("");
        setCopyError(`전체 내용을 복사하지 못했습니다. 다시 시도하세요. ${String(cause)}`);
      }
    } finally {
      if (generation === copyGeneration.current) copyPending.current = false;
    }
  };

  return <div className="planning-message-disclosure">
    <div ref={bodyRef} id={bodyId} className="planning-message-disclosure__body" data-expanded={inline}
      tabIndex={-1}><ChatMarkdown text={displayText} preview={!inline} /></div>
    <div className="planning-message-disclosure__actions">
      {!inline && (overflow || displayText !== text) ? <button ref={toggleRef} type="button" className="button button--quiet"
        aria-expanded={false} aria-haspopup="dialog" aria-controls="planning-message-dialog"
        onClick={() => onExpandedChange(true)}>전체 보기</button> : null}
      <button ref={copyRef} type="button" className="button button--quiet" disabled={copyStatus === "copying"}
        aria-label="전체 내용 복사" onClick={() => void copy()}>복사</button>
      {copyStatus ? <span className="planning-message-disclosure__hint" role="status">
        {copyStatus === "copying" ? "복사 중…" : "복사됨"}
      </span> : null}
    </div>
    {copyError ? <p className="planning-message-disclosure__error" role="alert">{copyError}</p> : null}
  </div>;
}
