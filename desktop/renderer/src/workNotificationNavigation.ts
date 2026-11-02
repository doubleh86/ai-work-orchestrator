import type { StoredWorkNotification } from "../../shared/workNotifications";

export interface NotificationNavigation {
  view: "tasks" | "planning" | "operations" | "results";
  taskId: string;
  inspector: "detail" | "log" | "events";
}

export function notificationNavigation(
  notification: Pick<StoredWorkNotification, "target_kind" | "target_id" | "summary_code">,
): NotificationNavigation {
  if (notification.summary_code === "task_completed") {
    return { view: "results", taskId: notification.target_id, inspector: "detail" };
  }
  if (notification.summary_code === "group_completed") {
    return { view: "results", taskId: "", inspector: "detail" };
  }
  if (notification.target_kind === "planning") {
    return { view: "planning", taskId: "", inspector: "detail" };
  }
  if (["operations", "verification", "conflict"].includes(notification.target_kind)) {
    return { view: "operations", taskId: "", inspector: "detail" };
  }
  if (notification.target_kind === "task") {
    return {
      view: "tasks",
      taskId: notification.target_id,
      inspector: notification.summary_code === "task_failed" ? "log" : "detail",
    };
  }
  return { view: "tasks", taskId: "", inspector: "events" };
}
