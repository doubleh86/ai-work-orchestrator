/** Dismiss only explicitly marked floating disclosures, preserving document accordions. */
export function installDetailsDismissal(root: Document): () => void {
  const menus = () => root.querySelectorAll<HTMLDetailsElement>("details[data-dismiss-on-outside][open]");
  const closeOutside = (event: Event) => {
    const path = event.composedPath();
    for (const menu of menus()) if (!path.includes(menu)) menu.open = false;
  };
  const closeAction = (event: Event) => {
    const path = event.composedPath();
    for (const menu of menus()) {
      if (path.includes(menu) && [...menu.querySelectorAll("[data-dismiss-menu-action]")].some(action => path.includes(action))) {
        menu.open = false;
      }
    }
  };
  const closeEscape = (event: KeyboardEvent) => {
    if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
    const openMenus = [...menus()];
    for (const target of event.composedPath()) {
      const menu = openMenus.find(item => item === target);
      if (!menu) continue;
      menu.open = false;
      event.preventDefault();
      event.stopPropagation();
      menu.querySelector<HTMLElement>(":scope > summary")?.focus({ preventScroll: true });
      return;
    }
  };
  root.addEventListener("pointerdown", closeOutside, true);
  root.addEventListener("focusin", closeOutside, true);
  root.addEventListener("click", closeAction, true);
  root.addEventListener("keydown", closeEscape);
  return () => {
    root.removeEventListener("pointerdown", closeOutside, true);
    root.removeEventListener("focusin", closeOutside, true);
    root.removeEventListener("click", closeAction, true);
    root.removeEventListener("keydown", closeEscape);
  };
}
