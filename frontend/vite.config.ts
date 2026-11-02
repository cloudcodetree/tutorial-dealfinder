import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: /api goes to the FastAPI backend on :8000 with /api stripped, the same
// mapping the deals Worker applies in production, so the app calls one path everywhere.
// This file runs in Node. Declaring the one global it reads lets `tsc -b` check it
// without adding @types/node to the app.
declare const process: { env: Record<string, string | undefined> };
const API_TARGET = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
