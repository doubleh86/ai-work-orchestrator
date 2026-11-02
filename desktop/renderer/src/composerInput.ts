export function composerIsComposing(composing: boolean, event?: { isComposing?: boolean; keyCode?: number }): boolean {
  return composing || Boolean(event?.isComposing) || event?.keyCode === 229;
}
