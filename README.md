# Aoki-Agent

日本动画圣地巡礼 agent。自建 agent loop 与 harness，能力通过 MCP 工具接入。

> 计划与设计详见 [.claude/docs/project-vision.md](.claude/docs/project-vision.md)

## 核心场景

1. **查圣地** —— 「《リコリス・リコイル》的圣地在哪？」→ 列出取景地，地图打点
2. **查天气** —— 「这周末去镰仓巡礼，天气怎么样？」→ 结合圣地位置查预报
3. **规划路线** —— 「帮我安排一天走完这几个点」→ 排序、估算移动时间、给行程

## 技术栈

React (Vite + TS) · FastAPI · 自建 Agent Loop · MCP · Postgres · Langfuse · Docker · AWS App Runner · GitHub Actions

## 目录

```
backend/
  app/          FastAPI 入口、路由、SSE
  agent/        自建 loop、harness、MCP client、LLM 抽象
  store/        SessionStore 接口 + 内存 / Postgres 实现
  mcp_servers/  自建圣地巡礼 MCP server
frontend/       React（待初始化，需先装 Node）
evals/          评测（Day 6+）
learn/          学习期代码，仅作参考
```

## 本地开发

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # 填入 LLM_API_KEY

uvicorn backend.app.main:app --reload
```

`DATABASE_URL` 留空时自动回退到内存 store，本地不起 Postgres 也能开发。
