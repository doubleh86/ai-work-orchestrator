import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const workspaceRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: resolve(workspaceRoot, "desktop/renderer"),
  base: "./",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      allow: [resolve(workspaceRoot, "desktop")],
    },
  },
  build: {
    outDir: resolve(workspaceRoot, "dist/renderer"),
    emptyOutDir: true,
  },
});
