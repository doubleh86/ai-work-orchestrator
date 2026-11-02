import { useEffect, useId, useRef } from "react";
import { Ellipsis, ListChecks, Plus, Settings, ShieldCheck, Trash2 } from "lucide-react";

export function ProjectToolsMenu({ projectOnly = false, compact = false, onOpenGroups, onMainChanges, removeReason = "", projectName, settingsDisabled, removeDisabled, onAddProject, onOpenAuth, onOpenSettings, onRemoveProject }: {
  projectOnly?: boolean;
  compact?: boolean;
  onOpenGroups?(): void;
  onMainChanges?(): void;
  removeReason?: string;
  projectName: string;
  settingsDisabled: boolean;
  removeDisabled: boolean;
  onAddProject(): void;
  onOpenAuth(): void;
  onOpenSettings(): void;
  onRemoveProject(): void;
}) {
  const contentId = useId();
  const menuRef = useRef<HTMLDetailsElement>(null);
  const triggerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const closeOnPointer = (event: PointerEvent) => {
      if (menu.open && event.target instanceof Node && !menu.contains(event.target)) menu.open = false;
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (!menu.open || event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
      menu.open = false;
      event.preventDefault();
      event.stopPropagation();
      triggerRef.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", closeOnPointer, true);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointer, true);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  const choose = (action: () => void) => {
    if (menuRef.current) menuRef.current.open = false;
    action();
  };

  return <details ref={menuRef} className={`work-header-tools${compact ? " work-header-tools--compact" : ""}`} data-dismiss-on-outside onBlur={(event) => {
    if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
      event.currentTarget.open = false;
    }
  }}>
    <summary ref={triggerRef} aria-controls={contentId} aria-label={compact ? "작업 메뉴" : projectName ? `${projectName} 프로젝트 관리` : "프로젝트 관리"}>{compact ? <Ellipsis size={17} aria-hidden="true" /> : "프로젝트 관리"}</summary>
    <div id={contentId}>
      {onOpenGroups ? <button className="button button--quiet" type="button" onClick={() => choose(onOpenGroups)}>
        <ListChecks aria-hidden="true" size={15} />작업 그룹 전환
      </button> : null}
      {!projectOnly ? <button className="button button--quiet" type="button" onClick={() => choose(onAddProject)}>
        <Plus aria-hidden="true" size={15} />프로젝트
      </button> : null}
      {!projectOnly ? <button className="button button--quiet" type="button" onClick={() => choose(onOpenAuth)}>
        <ShieldCheck aria-hidden="true" size={15} />AI 연결
      </button> : null}
      <button className="button button--quiet" type="button" disabled={settingsDisabled} onClick={() => {
        if (!settingsDisabled) choose(onOpenSettings);
      }}><Settings aria-hidden="true" size={15} />{projectOnly ? "프로젝트 환경" : "설정"}</button>
      {onMainChanges ? <button className="button button--quiet" type="button" disabled={settingsDisabled} onClick={() => { if (!settingsDisabled) choose(onMainChanges); }}>원본 변경·동기화</button> : null}
      <button className="button button--danger" type="button" disabled={!projectName || removeDisabled}
        title={removeReason || "등록 목록에서만 삭제하며 프로젝트 파일은 유지합니다."} onClick={() => {
          if (projectName && !removeDisabled) choose(onRemoveProject);
        }}>
        <Trash2 aria-hidden="true" size={15} />
        <span className="work-header-tools__remove-label"><span>프로젝트 삭제</span>
          <small>{projectName || "프로젝트를 먼저 선택하세요"} · 등록만 해제</small>
        </span>
      </button>
      {removeDisabled && removeReason ? <p role="status">{removeReason}</p> : null}
    </div>
  </details>;
}
