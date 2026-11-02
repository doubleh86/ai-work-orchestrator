import type { RunState, WorkTask } from "./types";

export function failedTaskQuestionKey(projectName: string, run: RunState, task: WorkTask): string {
  return JSON.stringify([projectName, run.id, run.plan_revision, run.stage, run.failed_step,
    task.id, task.status, task.attempt_count, task.last_attempt_id, task.last_attempt_started_at,
    task.last_attempt_finished_at, task.failed_action, task.error, task.title, task.acceptance_criteria]);
}

interface PreparedQuestion {
  active?: { source: string; block: string };
  edited: Set<string>;
}

/** Own only the exact text inserted by the app; user edits always take precedence. */
export class FailedTaskQuestionDrafts {
  private readonly questions = new Map<string, PreparedQuestion>();
  private readonly diagnostics = new Map<string, { source: string; text: string }>();

  diagnostic(projectName: string, runId: string, source: string): string {
    const saved = this.diagnostics.get(JSON.stringify([projectName, runId]));
    return saved?.source === source ? saved.text : "";
  }

  cacheDiagnostic(projectName: string, runId: string, source: string, text: string): void {
    this.diagnostics.set(JSON.stringify([projectName, runId]), { source, text });
  }

  release(projectName: string, runId: string, source?: string): void {
    const key = JSON.stringify([projectName, runId]);
    const question = this.questions.get(key);
    if (!source || question?.active?.source === source) this.questions.delete(key);
    else question?.edited.delete(source);
  }

  prepare(projectName: string, runId: string, source: string, current: string, message: string, diagnostic = ""): string {
    const key = JSON.stringify([projectName, runId]);
    this.cacheDiagnostic(projectName, runId, source, diagnostic);
    const question = this.questions.get(key) || { edited: new Set<string>() };
    this.questions.set(key, question);
    if (!current.trim()) {
      question.edited.clear();
      question.active = { source, block: message };
      return message;
    }
    const previous = question.active;
    const index = previous ? current.indexOf(previous.block) : -1;
    const intact = previous && index >= 0 && current.indexOf(previous.block, index + previous.block.length) < 0;
    if (previous && !intact) {
      question.edited.add(previous.source);
      question.active = undefined;
    }
    if (question.edited.has(source)) {
      if (previous && intact && previous.source !== source) {
        question.active = undefined;
        return current.slice(0, index) + current.slice(index + previous.block.length);
      }
      return current;
    }
    if (previous && intact) {
      question.active = { source, block: message };
      return current.slice(0, index) + message + current.slice(index + previous.block.length);
    }
    if (current.includes(message)) {
      question.edited.add(source);
      return current;
    }
    question.active = { source, block: message };
    return `${current}\n\n${message}`;
  }
}
