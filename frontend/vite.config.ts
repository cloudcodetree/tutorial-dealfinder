import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: forward the API routes to the FastAPI backend on :8000 so the SPA
// can call same-origin paths (/search, /search/stream, /me) in development and
// EventSource works without CORS. In production the SPA talks to VITE_API_BASE.
const API_TARGET = process.env.VITE_API_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/search": { target: API_TARGET, changeOrigin: true },
      "/me": { target: API_TARGET, changeOrigin: true },
      "/healthz": { target: API_TARGET, changeOrigin: true },
    },
  },
});
