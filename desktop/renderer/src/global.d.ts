import { DesktopApi } from "../../shared/rpc";

declare module "*.css";

declare global {
  interface Window {
    orchestrator: DesktopApi;
  }
}

export {};
