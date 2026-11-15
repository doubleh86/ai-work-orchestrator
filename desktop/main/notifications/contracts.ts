import type { RpcMethod, RpcParams } from "../../shared/rpc";
import {
  StoredWorkNotification,
  WorkNotificationRefreshIssue,
  WorkNotificationSettings,
  WorkNotificationSnapshot,
} from "../../shared/workNotifications";

export interface NotificationProject {
  name: string;
  repo: string;
}

export interface ProjectDeliveryState {
  cursor: string;
  initialized_at: string;
  baseline_at: string;
  project_key: string;
}

export interface NotificationReadReceipt {
  stable_event_key: string;
  stable_source_key: string;
  read_at: string;
}

export interface NotificationDismissedReceipt {
  stable_event_key: string;
  stable_source_key: string;
  dismissed_at: string;
}

export interface PersistedNotificationState {
  schema_version: 4;
  revision: number;
  storage_identity: string;
  projects: Record<string, ProjectDeliveryState>;
  items: StoredWorkNotification[];
  read_receipts: NotificationReadReceipt[];
  dismissed_receipts: NotificationDismissedReceipt[];
  settings: WorkNotificationSettings;
  delivery_error: string;
  last_successful_write_at: string;
  refresh_issues: WorkNotificationRefreshIssue[];
  refresh_successes: Record<string, string>;
}

export type ReadStateNotice = WorkNotificationSnapshot["read_state_notice"];

export interface LoadedNotificationState {
  state: PersistedNotificationState;
  writable: boolean;
  backup_current_on_write: boolean;
  notice: ReadStateNotice;
}

export interface ParsedState {
  status: "valid" | "invalid" | "future" | "missing";
  state?: PersistedNotificationState;
}

export interface NotificationHost {
  isBackground(): boolean;
  publish(snapshot: WorkNotificationSnapshot): void;
  showOs(title: string, body: string, onClick: () => void): boolean;
  open(notification: StoredWorkNotification): void;
  log(message: string): void;
}

export interface NotificationBridge {
  request<Result>(method: RpcMethod, params?: RpcParams): Promise<Result>;
}

export const MAX_STORED_NOTIFICATIONS = 500;

export const MAX_READ_RECEIPTS = 2_000;

export interface WaitingNotificationRun {
  id: string;
  waiting_prompt?: { source_key: string } | null;
}
