import { useId, useState } from "react";
import { Archive, ChevronDown, FolderKanban, MessageSquare, Plus, RefreshCw, Trash2 } from "lucide-react";
import type { RegisteredProject, RunState } from "./types";
import type { RunSummaryCache } from "./runArchiveCache";
import { planningRequestFor, type PlanningRequestsSnapshot } from "../../shared/planningRequests";
import type { PlanningChatDraft } from "./planningRequestDrafts";

export function ChatProjectNavigation({ projects, cache, projectName, run, drafts = [], selectedDraftId, archiving, deleting, planning, onProject, onOpen, onNew, onOpenDraft, onDeleteDraft, onHistory, onArchive, onDelete }: {
  projects: RegisteredProject[]; cache: RunSummaryCache; projectName: string; run?: RunState;
  archiving?: { projectName: string; runId: string };
  deleting?: { projectName: string; runId: string }; planning?: PlanningRequestsSnapshot;
  drafts?: PlanningChatDraft[]; selectedDraftId?: string;
  onProject(name: string): void; onOpen(name: string, runId: string): void;
  onNew(name: string): void; onHistory(name: string): void; onArchive(name: string, runId: string): void;
  onDelete(name: string, runId: string): void;
  onOpenDraft(name: string, chatId: string): void; onDeleteDraft(name: string, chatId: string): void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const navigationId = useId();
  return <section className="chat-projects" aria-label="프로젝트와 대화">
    <h2>프로젝트</h2>
    {projects.map((project, index) => {
      const open = expanded[project.name] ?? project.name === projectName;
      const conversations = cache[project.name]?.active || [];
      const newChats = drafts.filter(chat => chat.projectName === project.name);
      const conversationId = `${navigationId}-${index}`;
      return <div className="chat-projects__project" key={project.name}>
        <div className="chat-projects__heading">
          <button type="button" data-navigation-action aria-expanded={open} aria-controls={conversationId}
            onClick={() => { setExpanded(current => ({ ...current, [project.name]: !open })); onProject(project.name); }}>
            <ChevronDown aria-hidden="true" size={14} data-open={open} /><FolderKanban aria-hidden="true" size={15} /><span className="chat-projects__project-name">{project.name}</span></button>
          <button className="chat-projects__new" type="button" data-navigation-action aria-label={`${project.name}에서 새 대화`}
            onClick={() => { setExpanded(current => ({ ...current, [project.name]: true })); onNew(project.name); }}><Plus aria-hidden="true" size={14} /><span>새 채팅</span></button>
        </div>
        <div id={conversationId} hidden={!open} className="chat-projects__conversations">
          {newChats.map(chat => <div className="chat-projects__conversation chat-projects__draft" key={`draft:${chat.id}`}>
            <button className="chat-projects__open" type="button" data-navigation-action title={chat.title}
              aria-current={project.name === projectName && chat.id === selectedDraftId ? "page" : undefined}
              onClick={() => onOpenDraft(project.name, chat.id)}><MessageSquare aria-hidden="true" size={14} /><span>{chat.title}</span><small>{chat.preparing ? "준비 중" : "작성 중"}</small></button>
            <div className="chat-projects__actions" title={chat.preparing ? "채팅 준비가 끝나면 삭제할 수 있습니다" : "초안 삭제"}>
              <button className="chat-projects__delete" type="button" disabled={chat.preparing}
                aria-label={`${project.name} · ${chat.title} 초안 삭제`} onClick={() => { if (!chat.preparing) onDeleteDraft(project.name, chat.id); }}>
                <Trash2 aria-hidden="true" size={14} /><span className="sr-only">삭제</span></button></div>
          </div>)}
          {conversations.slice(0, 6).map(item => {
            const title = item.summary || "이름 없는 대화";
            const inUse = item.execution_situation === "running" || Boolean(planning && planningRequestFor(planning, project.name, item.id))
              || Boolean(project.name === projectName && run?.id === item.id && (run.active_step
                || run.tasks.some(task => task.active_action || ["running", "reviewing", "revising"].includes(task.status))));
            const actionsDisabled = Boolean(archiving || deleting || inUse);
            const canArchive = !item.archived && item.execution_situation !== "running"
              && (["pushed", "deployed"].includes(item.stage) || (item.stage === "merged" && item.pipeline_complete));
            const archivingItem = archiving?.projectName === project.name && archiving.runId === item.id;
            const deletingItem = deleting?.projectName === project.name && deleting.runId === item.id;
            return <div className="chat-projects__conversation" key={item.id}>
              <button type="button" className="chat-projects__open" data-navigation-action
                title={title} aria-current={project.name === projectName && item.id === run?.id ? "page" : undefined}
                onClick={() => onOpen(project.name, item.id)}><MessageSquare aria-hidden="true" size={14} />
                <span>{title}</span>{item.execution_situation === "running" ? <span className="chat-projects__active" aria-label="진행 중" /> : null}</button>
              <div className="chat-projects__actions" title={inUse ? "이 대화의 AI 응답·작업이 끝나거나 중단된 뒤 정리할 수 있습니다" : undefined}>
              {canArchive ? <button type="button" className="chat-projects__archive" data-navigation-action disabled={actionsDisabled}
                aria-label={`${project.name} · ${title} 보관·정리`} title={archivingItem ? "보관 중" : "완료 기록을 보관하고 임시 작업공간을 정리합니다"}
                aria-busy={archivingItem || undefined}
                onClick={() => { if (!actionsDisabled) onArchive(project.name, item.id); }}>
                {archivingItem ? <RefreshCw aria-hidden="true" className="spin" size={14} /> : <Archive aria-hidden="true" size={14} />}
                <span className="sr-only">{archivingItem ? "보관 중" : "보관·정리"}</span>
              </button> : null}
              <button type="button" className="chat-projects__delete" data-navigation-action disabled={actionsDisabled}
                aria-label={`${project.name} · ${title} 삭제`} title={deletingItem ? "삭제 중" : inUse ? "이 대화의 AI 응답·작업이 끝나거나 중단된 뒤 삭제할 수 있습니다" : "대화와 연결된 작업 기록·작업공간을 삭제합니다"}
                aria-busy={deletingItem || undefined}
                onClick={() => { if (!actionsDisabled) onDelete(project.name, item.id); }}>
                {deletingItem ? <RefreshCw aria-hidden="true" className="spin" size={14} /> : <Trash2 aria-hidden="true" size={14} />}
                <span className="sr-only">{deletingItem ? "삭제 중" : "삭제"}</span>
              </button>
              </div>
            </div>;
          })}
          {!conversations.length && !newChats.length ? <button type="button" data-navigation-action onClick={() => onNew(project.name)}>새 대화 시작</button> : null}
          <button className="chat-projects__history" type="button" data-navigation-action onClick={() => onHistory(project.name)}>전체 작업·보관 기록</button>
        </div>
      </div>;
    })}
  </section>;
}
