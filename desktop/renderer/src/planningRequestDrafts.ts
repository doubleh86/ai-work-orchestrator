import type { EffortMode, PlanningMode, ProviderProfile, RepositoryMaturityKind } from "./types";

export interface PlanningRequestDraft {
  path: string;
  mode: PlanningMode;
  request: string;
  effortMode: EffortMode;
  profileKey: string;
  reasoning: string;
  profileManual: boolean;
  repositoryIntent: "" | "existing_structure" | "new_project";
}

export interface PlanningChatDraft {
  id: string;
  projectName: string;
  title: string;
  preparing?: boolean;
}

export function planningRepositoryIntent(
  maturity: RepositoryMaturityKind | undefined, intent: PlanningRequestDraft["repositoryIntent"],
): PlanningRequestDraft["repositoryIntent"] {
  if (maturity === "docs_only") return "new_project";
  if (maturity === "existing_code" && !intent) return "existing_structure";
  return intent;
}

export class PlanningRequestDrafts {
  private readonly drafts = new Map<string, PlanningRequestDraft>();
  private chats: PlanningChatDraft[] = [];
  private readonly listeners = new Set<() => void>();
  subscribe = (listener: () => void): (() => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  chatSnapshot = (): PlanningChatDraft[] => this.chats;

  createChat(projectName: string, id: string, path = ""): void {
    if (!projectName || !id || this.chats.some(chat => chat.id === id)) throw new Error("새 채팅의 프로젝트와 ID를 확인해 주세요.");
    const defaults = this.load(projectName, path);
    this.drafts.set(JSON.stringify([projectName, id]), { ...defaults, path: path || defaults.path, mode: "directed", request: "" });
    this.chats = [{ projectName, id, title: "새 채팅" }, ...this.chats];
    this.notify();
  }

  removeChat(projectName: string, id: string): void {
    this.drafts.delete(JSON.stringify([projectName, id]));
    this.chats = this.chats.filter(chat => chat.projectName !== projectName || chat.id !== id);
    this.notify();
  }

  setChatPreparing(projectName: string, id: string, preparing: boolean): void {
    if (!this.chats.some(chat => chat.projectName === projectName && chat.id === id)) return;
    this.chats = this.chats.map(chat => chat.projectName === projectName && chat.id === id ? { ...chat, preparing } : chat);
    this.notify();
  }

  private notify(): void { for (const listener of this.listeners) listener(); }

  load(projectName: string, path = "", repositoryIntent: PlanningRequestDraft["repositoryIntent"] = "", chatId = ""): PlanningRequestDraft {
    const key = JSON.stringify([projectName, chatId]);
    const saved = this.drafts.get(key);
    if (saved) return { ...saved };
    const initial: PlanningRequestDraft = {
      path, mode: "directed", request: "", effortMode: "balanced", profileKey: "", reasoning: "", profileManual: false, repositoryIntent,
    };
    this.drafts.set(key, initial);
    return { ...initial };
  }

  update(projectName: string, patch: Partial<PlanningRequestDraft>, chatId = ""): PlanningRequestDraft {
    const updated = { ...this.load(projectName, "", "", chatId), ...patch };
    this.drafts.set(JSON.stringify([projectName, chatId]), updated);
    if (chatId && patch.request !== undefined) {
      const title = patch.request.trim().split(/\r?\n/u)[0].slice(0, 80) || "새 채팅";
      this.chats = this.chats.map(chat => chat.projectName === projectName && chat.id === chatId ? { ...chat, title } : chat);
      this.notify();
    }
    return { ...updated };
  }
}

export function initialPlanningProfileParams(profile: ProviderProfile | undefined, reasoning: string, manual: boolean) {
  return {
    planningAgentId: profile?.agent_id || "",
    planningModel: profile?.model || "",
    planningReasoningEffort: reasoning,
    planningProfileSource: manual ? "manual" : "routing",
  };
}

export function planningMessageProfileParams(profile: ProviderProfile | undefined, reasoning: string, edited: boolean) {
  return edited ? {
    planningAgentId: profile?.agent_id || "", planningModel: profile?.model || "", planningReasoningEffort: reasoning,
  } : {};
}
