import { Menu, nativeImage, Tray, type BrowserWindow } from "electron";

// Embedded PNG keeps the tray icon available in both development and packaged apps.
const TRAY_ICON = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABE0lEQVR4nM2Xyw3DIAxAMwELZJ6MUCnnHHpgB24ZIEuwQkaolBE6QcZojWSkiGJD+Mg9vEsE9osxhAzPx3uQRDR5qYACJkADBtH4TPUUmIEd+CTYcWwzAfdmR0bikAPnVgmYgsQhplRga5Dcs90VaPHmWZWg1jwV7AQssCIWn6Xm/fRETIBrOJdkYZZtSYgcKYGZmfwCRia5Z8SxVJyZE6D2+ZmZ/CpBVWKnBBRjzZWdWw4qnooJUM13FiT3UFWYYgKaGGwrBCwRU8cEqL2/VgisREzzlwLiSyDehOLb0CF6EDnEj2KH6MeIa8ZQpNvnmDsTasi+kHhEr2QtK1F8Kb32hNi1PNyiIj8mIWK/Zl0QF/gClsjarhIexgQAAAAASUVORK5CYII=";

export class DesktopTray {
  private readonly tray: Tray;
  private quitting = false;

  constructor(showWindow: () => void, requestQuit: () => void) {
    const image = nativeImage.createFromDataURL(TRAY_ICON);
    if (image.isEmpty()) throw new Error("Tray icon could not be loaded");
    const icon = process.platform === "darwin" ? image.resize({ width: 16, height: 16 }) : image;
    if (process.platform === "darwin") icon.setTemplateImage(true);
    this.tray = new Tray(icon);
    const open = () => {
      if (!this.quitting && this.isAvailable()) showWindow();
    };
    const quit = () => {
      if (this.quitting) return;
      this.beginQuit();
      requestQuit();
    };
    try {
      this.tray.setToolTip("AI Work Orchestrator");
      this.tray.setContextMenu(Menu.buildFromTemplate([
        { label: "열기", click: open },
        { type: "separator" },
        { label: "종료", click: quit },
      ]));
      if (process.platform === "win32") this.tray.on("click", open);
      this.tray.on("double-click", open);
    } catch (error) {
      this.destroy();
      throw error;
    }
  }

  attach(window: BrowserWindow): void {
    window.on("close", (event) => {
      if (this.quitting || !this.isAvailable()) return;
      event.preventDefault();
      window.hide();
    });
  }

  isAvailable(): boolean {
    return !this.tray.isDestroyed();
  }

  beginQuit(): void {
    this.quitting = true;
  }

  cancelQuit(): void {
    this.quitting = false;
  }

  destroy(): void {
    if (this.isAvailable()) this.tray.destroy();
  }
}
