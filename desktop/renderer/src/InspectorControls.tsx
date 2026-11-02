import { useLayoutEffect, useRef, type ReactNode, type RefObject } from "react";
import { PanelRight, PanelRightClose } from "lucide-react";

export type InspectorScrollMemory = Record<string, { top: number; left: number }>;

export function InspectorToggle({ open, panelId, onToggle }: {
  open: boolean;
  panelId: string;
  onToggle(): void;
}) {
  const label = open ? "상세 패널 접기" : "상세 패널 열기";
  return <span className="inspector-toggle">
    <button id={open ? undefined : "inspector-open"} type="button"
      className={open ? "icon-button" : "button button--quiet"}
      aria-label={label} aria-expanded={open} aria-controls={panelId}
      aria-describedby={open ? `${panelId}-toggle-tip` : undefined} onClick={onToggle}>
      {open ? <PanelRightClose aria-hidden="true" size={18} /> : <PanelRight aria-hidden="true" size={16} />}
      {open ? null : label}
    </button>
    {open ? <span id={`${panelId}-toggle-tip`} className="inspector-toggle__tip" role="tooltip">{label}</span> : null}
  </span>;
}

export function InspectorContent({ id, labelledBy, contextKey, visible, compact, memory, children }: {
  id: string;
  labelledBy: string;
  contextKey: string;
  visible: boolean;
  compact: boolean;
  memory: RefObject<InspectorScrollMemory>;
  children: ReactNode;
}) {
  const nodeRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = nodeRef.current;
    if (!node || !visible || compact) return;
    const position = memory.current[contextKey];
    node.scrollTop = position?.top || 0;
    node.scrollLeft = position?.left || 0;
  }, [compact, contextKey, memory, visible]);
  return <div ref={nodeRef} id={id} className="inspector-content" role="tabpanel" aria-labelledby={labelledBy}
    onScroll={(event) => {
      if (!visible || compact) return;
      memory.current[contextKey] = { top: event.currentTarget.scrollTop, left: event.currentTarget.scrollLeft };
    }}>{children}</div>;
}
