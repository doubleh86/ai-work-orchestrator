import { useId, useState } from "react";
import { ChevronDown, FolderKanban, MessageSquare, Plus } from "lucide-react";
import type { RegisteredProject, RunState } from "./types";
import type { RunSummaryCache } from "./runArchiveCache";

export function ChatProjectNavigation({ projects, cache, projectName, run, onProject, onOpen, onNew, onHistory }: {
  projects: RegisteredProject[]; cache: RunSummaryCache; projectName: string; run?: RunState;
  onProject(name: string): void; onOpen(name: string, runId: string): void;
  onNew(name: string): void; onHistory(name: string): void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const navigationId = useId();
  return <section className="chat-projects" aria-label="프로젝트와 대화">
    <h2>프로젝트</h2>
    {projects.map((project, index) => {
      const open = expanded[project.name] ?? project.name === projectName;
      const conversations = cache[project.name]?.active || [];
      const conversationId = `${navigationId}-${index}`;
      return <div className="chat-projects__project" key={project.name}>
        <div className="chat-projects__heading">
          <button type="button" data-navigation-action aria-expanded={open} aria-controls={conversationId}
            onClick={() => { setExpanded(current => ({ ...current, [project.name]: !open })); onProject(project.name); }}>
            <ChevronDown aria-hidden="true" size={14} data-open={open} /><FolderKanban aria-hidden="true" size={15} />{project.name}</button>
          <button className="icon-button" type="button" data-navigation-action aria-label={`${project.name}에서 새 대화`}
            onClick={() => onNew(project.name)}><Plus aria-hidden="true" size={14} /></button>
        </div>
        <div id={conversationId} hidden={!open} className="chat-projects__conversations">
          {conversations.slice(0, 6).map(item => <button type="button" key={item.id} data-navigation-action
            title={item.summary || "이름 없는 대화"} aria-current={project.name === projectName && item.id === run?.id ? "page" : undefined}
            onClick={() => onOpen(project.name, item.id)}><MessageSquare aria-hidden="true" size={14} />
            <span>{item.summary || "이름 없는 대화"}</span>{item.execution_situation === "running" ? <span className="chat-projects__active" aria-label="진행 중" /> : null}</button>)}
          {!conversations.length ? <button type="button" data-navigation-action onClick={() => onNew(project.name)}>새 대화 시작</button> : null}
          <button className="chat-projects__history" type="button" data-navigation-action onClick={() => onHistory(project.name)}>작업 기록 보기</button>
        </div>
      </div>;
    })}
  </section>;
}
