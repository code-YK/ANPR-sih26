import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // The app talks to the backend via relative /api/* paths (see api.js)
      // so the same code works in dev (proxied here) and once built and
      // served by FastAPI directly (same origin, no proxy needed).
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
