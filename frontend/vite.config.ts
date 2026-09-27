import react from '@vitejs/plugin-react'
// vite 의 defineConfig 타입에는 test 가 없다 — vitest 쪽을 써야 tsc 가 통과한다
import { defineConfig } from 'vitest/config'

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
  test: {
    // jsdom 에는 레이아웃 엔진이 없다 — 가로 오버플로 같은 CSS 문제는 여기서
    // 잡히지 않는다. 상태·피드백·렌더링 회귀를 고정하는 용도다.
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
})
