import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 讲解见 docs/10-frontend.md「开发时的代理」
export default defineConfig({
  plugins: [react()],
  server: {
    // 开发时页面在 :5173，后端在 :8000。前端代码只写相对路径 /api/...，
    // 由 Vite 转发给后端——浏览器看来是同源请求，不需要后端开 CORS
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
