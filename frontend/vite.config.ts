import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  // 빌드 산출물을 FastAPI 가 그대로 서빙한다 (컨테이너 1개 구성)
  build: { outDir: '../backend/static', emptyOutDir: true },
})
