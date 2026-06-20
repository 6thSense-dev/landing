import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { seoPrerenderPlugin } from "./scripts/seoPrerenderPlugin.js";

export default defineConfig({
  plugins: [react(), seoPrerenderPlugin()],
  build: {
    rollupOptions: {
      output: {
        // Split rarely-changing vendor libs into separately-cacheable chunks so
        // an app-code change doesn't invalidate the whole bundle for returning
        // visitors. Paired with immutable caching of /assets/* in the Caddyfile.
        manualChunks: {
          "react-vendor": ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
        },
      },
    },
  },
  preview: {
    host: true,
    allowedHosts: true,
  },
});
