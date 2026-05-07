import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // Mermaid's lazy-loaded renderer emits a large vendor chunk; it is not part of initial load.
    chunkSizeWarningLimit: 800,
  },
  server: {
    host: '0.0.0.0',
    port: 3100,
    allowedHosts: ['footer.kr', 's-mac-mini-1.tail991e46.ts.net'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // 백엔드 죽어도 프론트 안 죽도록
        configure: (proxy) => {
          proxy.on('error', () => {})
        },
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', () => {})
        },
      },
    },
  },
})
