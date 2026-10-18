import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Mirrors docker/nginx.conf: /api goes to the FastAPI service.
    proxy: Object.fromEntries(
      ['/api', '/feeds', '/media'].map((path) => [
        path,
        { target: process.env.BYOP_API_URL ?? 'http://localhost:8000' },
      ]),
    ),
  },
  css: {
    preprocessorOptions: {
      scss: {
        // The vendored theme and Bootstrap 5 still use @import and legacy Sass APIs.
        quietDeps: true,
        silenceDeprecations: ['import', 'global-builtin', 'color-functions', 'if-function'],
      },
    },
  },
  build: {
    // The lazy-loaded Costs chunk carries ApexCharts; the entry chunk stays small.
    chunkSizeWarningLimit: 1000,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Multi-step form flows type a lot; CI runners are slower than laptops.
    testTimeout: 20_000,
  },
});
