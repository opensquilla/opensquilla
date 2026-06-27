/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// Where the dev server forwards backend traffic. The built bundle is served by
// the gateway itself (same origin), so this proxy only matters under `npm run
// dev`, where Vite serves the UI on its own port. Override the target to point
// at whichever local gateway you started.
const gatewayTarget = process.env.OPENSQUILLA_GATEWAY_URL || 'http://127.0.0.1:18790'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    proxy: {
      // REST endpoints (approvals, artifacts under /api/v1, file upload, audio, …).
      '/api': { target: gatewayTarget, changeOrigin: true },
      // RpcClient connects to ws://<host>/ws for the live chat/event stream.
      '/ws': { target: gatewayTarget, ws: true, changeOrigin: true },
      // Backend-owned static assets (brand mark, share-export images, …) that the
      // app loads from `${base}/static/*`. Scope to /control/static ONLY — the
      // bare /control prefix is the SPA router base and must stay with Vite, or
      // proxying it would forward the app's routes to the gateway and defeat HMR.
      '/control/static': { target: gatewayTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: resolve(__dirname, '../src/opensquilla/gateway/static/dist'),
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) => {
          const info = assetInfo.name?.split('.') || []
          const ext = info[info.length - 1]
          if (/\.(png|jpe?g|gif|svg|webp|ico)$/i.test(assetInfo.name || '')) {
            return `assets/img/[name]-[hash][extname]`
          }
          if (/\.(woff2?|ttf|otf|eot)$/i.test(assetInfo.name || '')) {
            return `assets/fonts/[name]-[hash][extname]`
          }
          return `assets/[name]-[hash][extname]`
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  // Vitest: pure unit/property tests for the chat reducer and the merge/parity
  // helpers. Node environment (no DOM needed); the Playwright e2e tree under
  // e2e/ has its own runner and is excluded.
  test: {
    environment: 'node',
    include: ['src/**/*.{test,spec}.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
