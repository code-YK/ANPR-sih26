import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Fixed port: in dev, media (HLS, MJPEG, evidence) is fetched from the
    // backend's own origin to keep it off this origin's HTTP/1.1 connection
    // pool (see src/lib/api/media.js), so this origin must be a known entry
    // in the backend's CORS allowlist (backend/app/main.py). 5174 belongs
    // to client.
    port: 5175,
    strictPort: true,
    // On this Windows setup the watcher has served a module read mid-write
    // (an edit landing in two quick writes) and then missed the final one,
    // leaving a stale, broken module until restart. Wait for writes to settle.
    watch: { awaitWriteFinish: { stabilityThreshold: 120, pollInterval: 40 } },
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.js"],
  },
});
