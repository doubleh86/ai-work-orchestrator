import { emptyState, isRecord, migrateV1, migrateV2, sanitizeCurrentState } from "./codec";
import type { LoadedNotificationState, ParsedState, PersistedNotificationState } from "./contracts";
import { markRecovered } from "./records";
import { randomUUID } from "node:crypto";
import {
  closeSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";

export class WorkNotificationPersistenceError extends Error {
  readonly code = "notification_state_save_failed";

  constructor(cause?: unknown) {
    super("Notification read state could not be saved", cause === undefined ? undefined : { cause });
    this.name = "WorkNotificationPersistenceError";
  }
}

export function loadState(path: string): LoadedNotificationState {
  const primary = parseStateFile(path);
  if (primary.status === "future") {
    return { state: emptyState(), writable: false, backup_current_on_write: false, notice: "read_state_future_schema" };
  }
  if (primary.status === "valid" && primary.state) {
    return { state: primary.state, writable: true, backup_current_on_write: true, notice: "" };
  }
  const backup = parseStateFile(backupPath(path));
  if (backup.status === "valid" && backup.state) {
    return {
      state: markRecovered(backup.state),
      writable: true,
      backup_current_on_write: false,
      notice: "read_state_recovered_from_backup",
    };
  }
  const missing = primary.status === "missing" && backup.status === "missing";
  return {
    state: emptyState(),
    writable: true,
    backup_current_on_write: false,
    notice: missing ? "" : "read_state_recovered_with_baseline",
  };
}

function parseStateFile(path: string): ParsedState {
  if (!existsSync(path)) return { status: "missing" };
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!isRecord(raw) || typeof raw.schema_version !== "number") return { status: "invalid" };
    if (raw.schema_version > 4) return { status: "future" };
    if (raw.schema_version === 1) return { status: "valid", state: migrateV1(raw) };
    if (raw.schema_version === 2) return { status: "valid", state: migrateV2(raw) };
    if (raw.schema_version !== 3 && raw.schema_version !== 4) return { status: "invalid" };
    if (raw.schema_version === 4 && (!Array.isArray(raw.refresh_issues) || !isRecord(raw.refresh_successes))) return { status: "invalid" };
    return { status: "valid", state: sanitizeCurrentState(raw) };
  } catch {
    return { status: "invalid" };
  }
}

export function writeState(path: string, state: PersistedNotificationState, backupCurrent: boolean): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.tmp`;
  let fileDescriptor: number | undefined;
  try {
    fileDescriptor = openSync(temporary, "wx");
    writeFileSync(fileDescriptor, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    fsyncSync(fileDescriptor);
    closeSync(fileDescriptor);
    fileDescriptor = undefined;
    if (backupCurrent && existsSync(path)) copyFileSync(path, backupPath(path));
    renameSync(temporary, path);
  } finally {
    if (fileDescriptor !== undefined) closeSync(fileDescriptor);
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}

function backupPath(path: string): string {
  return `${path}.bak`;
}
