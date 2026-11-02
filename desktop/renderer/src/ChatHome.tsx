import { AlertCircle, FolderKanban, LoaderCircle, MessageSquare, Plus } from "lucide-react";
import type { RegisteredProject } from "./types";

export function ChatHome({ projects, choosing, onNew, onRegister, onCreate, onConnect, onCancel, connection, onRetry }: {
  projects: RegisteredProject[]; choosing: boolean; onNew(name: string): void;
  onRegister(): void; onCreate(): void; onConnect(): void; onCancel(): void;
  connection?: "connecting" | "unavailable"; onRetry?(): void;
}) {
  if (connection) return <section className="chat-home" aria-labelledby="chat-home-title" role="status">
    {connection === "connecting" ? <LoaderCircle className="spin" aria-hidden="true" size={30} /> : <AlertCircle aria-hidden="true" size={30} />}
    <h2 id="chat-home-title" tabIndex={-1}>{connection === "connecting" ? "실행 엔진 연결 중" : "프로젝트 목록을 불러오지 못했어요"}</h2>
    <p>{connection === "connecting" ? "연결이 확인되면 프로젝트와 작업을 불러옵니다." : "연결을 다시 확인해 기존 프로젝트 목록을 불러오세요."}</p>
    {connection === "unavailable" && onRetry ? <button className="button button--primary" type="button" onClick={onRetry}>연결 다시 확인</button> : null}
  </section>;
  return <section className="chat-home" aria-labelledby="chat-home-title">
    <MessageSquare aria-hidden="true" size={30} />
    <h2 id="chat-home-title" tabIndex={-1}>무엇을 함께 만들까요?</h2>
    <p>{projects.length ? "프로젝트를 선택해 대화를 시작하세요. 진행 중인 작업은 왼쪽 대화에서 이어볼 수 있습니다."
      : "AI를 연결하고 프로젝트를 열면 대화로 작업을 시작할 수 있습니다."}</p>
    {projects.length ? <div className="chat-home__projects">{projects.map(project => <button key={project.name}
      className="chat-home__project" type="button" onClick={() => onNew(project.name)}>
      <FolderKanban aria-hidden="true" size={20} /><strong>{project.name}</strong><span>새 대화</span>
    </button>)}</div> : null}
    <div className="chat-home__actions">
      {!projects.length ? <button className="button button--primary" type="button" onClick={onConnect}>AI 연결</button> : null}
      <button className="button button--secondary" type="button" onClick={onRegister}><FolderKanban aria-hidden="true" size={16} />기존 프로젝트 열기</button>
      <button className="button button--secondary" type="button" onClick={onCreate}><Plus aria-hidden="true" size={16} />새 프로젝트</button>
      {choosing ? <button className="button button--quiet" type="button" onClick={onCancel}>취소</button> : null}
    </div>
  </section>;
}
