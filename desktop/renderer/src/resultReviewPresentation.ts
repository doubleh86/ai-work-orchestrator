import type { GroupResultRecord, PlanningMessage, ResultFileChange, RunState, TaskResultRecord, WorkTask } from "./types";

export function resultRevisionDiscussion(messages: PlanningMessage[]): string {
  const transcript = messages.slice(-12).map((message) => `${message.role === "user" ? "나" : "기획 AI"}: ${message.text}`).join("\n\n");
  return transcript.length > 7800 ? `[최근 대화 일부 · 전체 내용은 기획 대화에 보존됨]\n${transcript.slice(-7800)}` : transcript;
}

export type ResultStatus = "completed" | "failed" | "partial" | "in_progress";

export function resultStatus(run: RunState, task?: WorkTask): ResultStatus {
  if (task) {
    if (["completed", "merged"].includes(task.status)) return "completed";
    if (task.status === "failed") return "failed";
    return "in_progress";
  }
  if (run.stage === "failed") return run.tasks.some((item) => ["completed", "merged"].includes(item.status)) ? "partial" : "failed";
  if (["verified", "work_branch_pushed", "merged", "pushed", "deployed"].includes(run.stage)) {
    return run.tasks.every((item) => ["completed", "merged"].includes(item.status)) ? "completed" : "partial";
  }
  return "in_progress";
}

export function resultGroupStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    ready_to_merge: "병합 대기 · 통합 검증 필요",
    verified: "통합 검증 완료 · Main 반영 전",
    work_branch_pushed: "작업 Branch Push 완료 · Main 반영 전",
    merged: "Main 반영 완료 · Push 전",
    pushed: "Main Push 완료",
    deployed: "배포 완료",
    failed: "실패 · 완료 범위와 시도 기록 확인 필요",
  };
  return labels[stage] || "진행 중";
}

export function resultOutcome(run: RunState, task?: WorkTask): { title: string; detail: string; tone: "success" | "warning" | "neutral" } {
  const status = resultStatus(run, task);
  const verification = resultVerification(run, task);
  const verified = task ? verification.commands.length > 0 : run.verification_attempts.at(-1)?.status === "succeeded";
  if (status === "failed" || status === "partial") {
    return { title: status === "partial" ? "일부 작업을 확인해야 해요" : "작업을 확인해야 해요", detail: verification.label, tone: "warning" };
  }
  if (task) return { title: status === "completed" ? "작업을 완료했어요" : "작업 결과를 확인하고 있어요",
    detail: verification.label, tone: status === "completed" && verified ? "success" : status === "completed" ? "warning" : "neutral" };
  const outcomes: Record<string, [string, string]> = {
    verified: ["최종 검증을 마쳤어요", "main 반영 전"],
    work_branch_pushed: ["작업 브랜치를 푸시했어요", "main 반영 전"],
    merged: ["main에 반영했어요", "푸시 전"],
    pushed: ["main에 반영했어요", "푸시 완료"],
    deployed: ["배포를 마쳤어요", "배포 완료"],
  };
  const outcome = outcomes[run.stage];
  return { title: outcome?.[0] || "작업 결과를 확인하고 있어요",
    detail: [verification.label, outcome?.[1]].filter(Boolean).join(" · "),
    tone: status === "completed" && verified ? "success" : status === "completed" ? "warning" : "neutral" };
}

export function resultChangedPaths(tasks: WorkTask[]): string[] {
  return [...new Set(tasks.flatMap((task) => task.action_results.flatMap((result) => result.changed_paths)))];
}

export function currentTaskResult(task: WorkTask): TaskResultRecord | undefined {
  if (!["completed", "merged"].includes(task.status) || !task.completed_commit) return undefined;
  const result = task.result_history?.at(-1);
  return result?.result_commit === task.completed_commit ? result : undefined;
}

export function currentGroupResult(run: RunState): GroupResultRecord | undefined {
  const attempt = run.verification_attempts.at(-1);
  if (!attempt || attempt.status !== "succeeded" || !run.verified_integration_head) return undefined;
  const result = run.group_result_history?.at(-1);
  return result?.result_commit === run.verified_integration_head && result.verification_attempt_id === attempt.id ? result : undefined;
}

export function resultSelectablePaths(tasks: WorkTask[]): string[] {
  return [...new Set(tasks.flatMap((task) => {
    if (["completed", "merged"].includes(task.status)) {
      const result = currentTaskResult(task);
      return result?.files_state === "confirmed" ? result.files.map((file) => file.path) : [];
    }
    return task.action_results.flatMap((item) => item.changed_paths);
  }))];
}

export function resultFileLabel(file: ResultFileChange): string {
  const labels: Record<string, string> = { A: "추가", M: "수정", D: "삭제", T: "유형 변경" };
  return `${labels[file.change] || file.change} · ${file.path}`;
}

export function resultVerification(run: RunState, task?: WorkTask): { label: string; commands: string[] } {
  if (task) {
    const attempt = [...task.action_results].reverse().find((result) => result.action === "verify");
    if (attempt?.status === "failed") return { label: "Task 검증 실패", commands: [] };
    if (attempt?.status === "running") return { label: "Task 검증 진행 중", commands: [] };
    const commands = attempt?.status === "succeeded" ? attempt.passed_commands.map((command) => command.join(" ")) : [];
    return { label: commands.length ? "기록된 Task 검증 통과" : "미검증 · 통과 명령 기록 없음", commands };
  }
  const attempt = run.verification_attempts.at(-1);
  if (!attempt) return { label: "미검증 · 최종 검증 기록 없음", commands: [] };
  if (attempt.status !== "succeeded") return { label: `최종 검증 ${attempt.status === "failed" ? "실패" : "미완료"}`, commands: [] };
  return { label: "최종 검증 통과", commands: attempt.passed_commands.map((command) => command.join(" ")) };
}

export function resultRevisionContext(run: RunState, text: string, taskIds: string[], paths: string[]): string {
  const tasks = run.tasks.filter((task) => taskIds.includes(task.id)).map((task) => `${task.id}: ${task.title}`);
  return `원본 작업 그룹: ${run.id} · ${run.summary || "제목 없음"}\n선택 Task: ${tasks.join(", ") || "그룹 전체"}\n선택 변경 파일: ${paths.join(", ") || "선택 없음"}\n수정 요청: ${text}\n원본 완료 결과와 검증 기록을 보존하고 후속 작업만 계획해 주세요.`;
}
