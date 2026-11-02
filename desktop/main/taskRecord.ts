import { mkdtemp, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { RpcMethod, RpcParams } from "../shared/rpc";

interface TaskRecordBridge {
  request<Result>(method: RpcMethod, params: RpcParams): Promise<Result>;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Resolve the selected task through Python; never accept a renderer file path. */
export async function openTaskRecord(
  bridge: TaskRecordBridge,
  temporaryRoot: string,
  openTextFile: (path: string) => Promise<string>,
  projectName: unknown,
  runId: unknown,
  taskId: unknown,
): Promise<boolean> {
  const identifiers = [projectName, runId, taskId];
  if (!identifiers.every((value) => typeof value === "string" && value.trim() && value.length <= 512 && !/[\x00-\x1f\x7f]/.test(value))) {
    throw new Error("작업 기록을 열려면 프로젝트·작업 그룹·작업 ID가 필요합니다.");
  }
  const params = { projectName: String(projectName).trim(), runId: String(runId).trim(), taskId: String(taskId).trim() };
  const [run, log] = await Promise.all([
    bridge.request<unknown>("runs.get", { projectName: params.projectName, runId: params.runId }),
    bridge.request<unknown>("tasks.log", params),
  ]);
  if (!record(run) || run.id !== params.runId || !Array.isArray(run.tasks) || !Array.isArray(run.events) || typeof log !== "string") {
    throw new Error("선택한 작업의 기록을 확인하지 못했습니다.");
  }
  const task = run.tasks.find((value: unknown) => record(value) && value.id === params.taskId);
  if (!record(task)) throw new Error("선택한 작업을 저장된 작업 그룹에서 찾지 못했습니다.");
  const content = [
    "[작업 기록 사본]", `프로젝트: ${params.projectName}`, `작업 그룹: ${params.runId}`, `작업: ${params.taskId}`,
    `저장 시각: ${new Date().toISOString()}`, "이 파일은 여는 시점의 사본이며 자동 갱신되지 않습니다.",
    "", "[현재 작업 로그]", log || "현재 저장된 로그가 없습니다.",
    "", "[작업 내용·모델·시도·결과 기록]", JSON.stringify(task, null, 2),
    "", "[작업 그룹 이벤트]", JSON.stringify(run.events, null, 2), "",
  ].join("\n");
  const directory = await mkdtemp(join(temporaryRoot, "ai-work-orchestrator-task-"));
  const path = join(directory, "task-record.txt");
  await writeFile(path, "\uFEFF" + content, { encoding: "utf8", flag: "wx" });
  const error = await openTextFile(path);
  if (error) throw new Error(`기록 파일을 텍스트 편집기로 열지 못했습니다. ${error}`);
  return true;
}
