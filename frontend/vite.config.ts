/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// In development the UI runs on Vite's server and /api is proxied to the
// backend (`meeting-assistant serve`), so the browser sees one origin exactly
// as it does in production, where FastAPI serves the built UI itself.
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000'

/**
 * Preload the two fonts every page uses (Latin UI text and Devanagari
 * transcripts), so text does not wait for the CSS to be parsed before the
 * font download starts. Build only: the emitted files have hashed names,
 * which are only known once the bundle exists.
 */
function preloadCriticalFonts(patterns: RegExp[]): Plugin {
  return {
    name: 'preload-critical-fonts',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(_html, context) {
        const files = Object.keys(context.bundle ?? {})
        return patterns
          .map((pattern) => files.find((file) => pattern.test(file)))
          .filter((file): file is string => file !== undefined)
          .map((file) => ({
            tag: 'link',
            attrs: {
              rel: 'preload',
              as: 'font',
              type: 'font/woff2',
              href: `/${file}`,
              crossorigin: '',
            },
            injectTo: 'head' as const,
          }))
      },
    },
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    preloadCriticalFonts([
      /inter-latin-wght-normal-[\w-]+\.woff2$/,
      /noto-sans-devanagari-devanagari-wght-normal-[\w-]+\.woff2$/,
    ]),
  ],
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  build: {
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    testTimeout: 15_000,
  },
})
