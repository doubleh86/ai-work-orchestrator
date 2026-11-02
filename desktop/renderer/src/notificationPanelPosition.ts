export interface NotificationPanelAnchor {
  top: number;
  right: number;
  bottom: number;
}

export interface NotificationViewport {
  width: number;
  height: number;
  offsetLeft?: number;
  offsetTop?: number;
}

export interface NotificationPanelPosition {
  left: number;
  top?: number;
  bottom?: number;
  width: number;
  maxHeight: number;
  opensAbove: boolean;
}

const VIEWPORT_INSET = 12;
const TRIGGER_GAP = 8;
const MAX_PANEL_WIDTH = 400;
const MIN_LIST_SPACE = 240;

export function notificationPanelPosition(
  anchor: NotificationPanelAnchor,
  viewport: NotificationViewport,
): NotificationPanelPosition {
  const offsetLeft = viewport.offsetLeft || 0;
  const offsetTop = viewport.offsetTop || 0;
  const viewportRight = offsetLeft + Math.max(0, viewport.width);
  const viewportBottom = offsetTop + Math.max(0, viewport.height);
  const width = Math.max(0, Math.min(MAX_PANEL_WIDTH, viewport.width - VIEWPORT_INSET * 2));
  const availableBelow = Math.max(0, viewportBottom - anchor.bottom - TRIGGER_GAP - VIEWPORT_INSET);
  const availableAbove = Math.max(0, anchor.top - offsetTop - TRIGGER_GAP - VIEWPORT_INSET);
  const opensAbove = availableBelow < MIN_LIST_SPACE && availableAbove > availableBelow;
  const desiredLeft = anchor.right - width;
  const left = clamp(desiredLeft, offsetLeft + VIEWPORT_INSET, viewportRight - VIEWPORT_INSET - width);

  if (opensAbove) {
    return {
      left,
      bottom: Math.max(VIEWPORT_INSET, viewportBottom - anchor.top + TRIGGER_GAP),
      width,
      maxHeight: availableAbove,
      opensAbove: true,
    };
  }
  return {
    left,
    top: Math.min(viewportBottom - VIEWPORT_INSET, anchor.bottom + TRIGGER_GAP),
    width,
    maxHeight: availableBelow,
    opensAbove: false,
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  if (maximum < minimum) return minimum;
  return Math.min(Math.max(value, minimum), maximum);
}
