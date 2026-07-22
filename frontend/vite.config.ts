import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend on :8000 so the SPA and
// API share an origin during development. In production the backend serves the
// built dist/ directly, so relative fetch() paths just work.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": "http://localhost:8000",
      "/projects": "http://localhost:8000",
      "/processes": "http://localhost:8000",
      "/csv": "http://localhost:8000",
      "/datasets": "http://localhost:8000",
      "/reconcile": "http://localhost:8000",
      "/transfer": "http://localhost:8000",
      "/retry": "http://localhost:8000",
      "/queue": "http://localhost:8000",
      "/config": "http://localhost:8000",
      "/events": "http://localhost:8000",
    },
  },
});
