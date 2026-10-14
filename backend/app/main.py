"""FastAPI 入口。讲解见 docs/08-fastapi-sse.md。

    uvicorn backend.app.main:app --reload

create_app() 接受一个「组件工厂」：生产环境用 default_components（真 LLM、真 MCP 子进程），
测试传入一个返回假 LLM / 假工具的工厂。两者走的是完全相同的路由代码。
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from .chat_service import ChatService
from .components import Components, default_components
from .config import settings
from .routes import chat, sessions

ComponentsFactory = Callable[[], AbstractAsyncContextManager[Components]]


def create_app(components_factory: ComponentsFactory | None = None) -> FastAPI:
    factory = components_factory or (lambda: default_components(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # yield 之前：启动（拉起 MCP 子进程等）；yield 之后：关闭。
        # 两者在同一个函数、同一个 task 里——MCP SDK 要求如此（见 docs/07）
        async with factory() as components:
            app.state.service = ChatService(components)
            yield

    app = FastAPI(title="Seichi-junrei Agent", lifespan=lifespan)
    app.include_router(chat.router)
    app.include_router(sessions.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # TODO(Day 3)：挂载 frontend/dist 静态文件，SPA fallback 到 index.html
    return app


app = create_app()
