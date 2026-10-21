# frontend

React + Vite + TypeScript。讲解见 [docs/10-frontend.md](../docs/10-frontend.md)。

```powershell
npm install
npm test          # 单元测试（vitest）
npm run lint      # oxlint
npm run dev       # 开发服务器 http://localhost:5173 ，/api 代理到后端 :8000
npm run build     # 产物在 dist/，由 FastAPI 在 http://127.0.0.1:8000 托管
```

开发时需要另开一个终端在项目根目录启动后端：`uvicorn backend.app.main:app --reload`。
