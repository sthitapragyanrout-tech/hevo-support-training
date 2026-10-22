/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Where the Django API lives in dev (override with API_TARGET to point the SPA
// at another backend, e.g. a throwaway one for end-to-end checks).
const apiTarget = process.env.API_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Forwards to Django so the browser only ever talks to one origin
      // (this dev server) — session/csrf cookies then behave as same-site
      // with no CORS setup needed, and it matches how nginx will front
      // both the SPA and the API under one origin in production.
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      // Emergency access to Django Admin (and its static files) on the same
      // origin. The SPA owns /admin, so Django's lives under /django-admin.
      '/django-admin': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/static': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
    globals: true,
  },
})
