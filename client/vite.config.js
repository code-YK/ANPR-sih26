import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Fixed, not Vite's auto-picked next-free-port: hlsProxyUrl/recordingMediaUrl
    // (see api.js) deliberately fetch video cross-origin from the backend even
    // in dev, so this origin has to be a known, stable entry in the backend's
    // CORS allowlist (backend/app/main.py) rather than whatever port happened
    // to be free -- a Vite auto-increment (5175, 5176, ...) here would silently
    // break every video fetch with a CORS error the next time frontend-v5's own
    // dev server (port 5175) was already running first.
    port: 5174,
    strictPort: true,
    proxy: {
      // The app talks to the backend via relative /api/* paths (see api.js)
      // so the same code works in dev (proxied here) and once built and
      // served by FastAPI directly (same origin, no proxy needed).
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
