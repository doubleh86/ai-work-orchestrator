export interface NotificationDismissFocusRequest {
  eventId: string;
  index: number;
}

export function notificationDismissFocusIndex(
  request: NotificationDismissFocusRequest,
  items: readonly { event_id: string }[],
): number | null {
  if (items.some((item) => item.event_id === request.eventId)) return null;
  return items.length ? Math.max(0, Math.min(request.index, items.length - 1)) : -1;
}
