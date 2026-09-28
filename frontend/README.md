# frontend

React + Vite + TypeScript。**尚未初始化**——本机没有装 Node。

装好 Node 后在项目根目录执行：

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install leaflet react-leaflet
```

（`npm create vite` 会拒绝写入非空目录，先把这个 README 挪走或直接让它覆盖后再放回。）

## 结构规划

- **双面板**：左侧聊天，右侧地图（Leaflet + OpenStreetMap，免费无 key）
- **SSE 消费**：`POST /chat` 的事件流，按 `token` / `tool_call` / `tool_result` / `done` / `error` 分别处理
- **工具调用可视化**：展示「正在查询圣地…」「正在获取天气…」，这是 agent demo 的核心观感
- **地图联动**：`tool_result` 里的坐标自动打点，路线场景画连线
- **会话侧栏**：`GET /sessions` 列表，点击切换；刷新后 `GET /sessions/{id}` 恢复，含工具调用记录与打点

构建产物 `dist/` 由 FastAPI 托管，单容器对外。
