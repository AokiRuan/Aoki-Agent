"""FastAPI 入口。

lifespan 里要做的事：
1. 连接所有 MCP server（自建圣地 server 走 stdio 子进程），完成工具发现
2. 初始化 SessionStore（有 DATABASE_URL 用 Postgres，否则内存），建表
3. 初始化 Langfuse
关闭时反序清理。

同时托管 frontend 的构建产物，单容器对外。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO(Day 2): 启动 MCP / store / tracing，挂到 app.state
    yield
    # TODO(Day 2): 关闭 MCP 子进程与数据库连接


app = FastAPI(title="Aoki-Agent", lifespan=lifespan)

# TODO(Day 2): app.include_router(chat.router) / sessions.router
# TODO(Day 3): 挂载 frontend/dist 静态文件，SPA fallback 到 index.html


@app.get("/health")
async def health():
    return {"status": "ok"}
