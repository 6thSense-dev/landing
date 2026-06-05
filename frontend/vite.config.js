import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { seoPrerenderPlugin } from "./scripts/seoPrerenderPlugin.js";

export default defineConfig({
  plugins: [react(), seoPrerenderPlugin()],
  preview: {
    host: true,
    allowedHosts: true,
  },
});
