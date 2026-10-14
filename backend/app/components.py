"""组装点：把 LLM、MCP 工具、harness、会话存储、tracing 创建出来并接在一起。讲解见 docs/08-fastapi-sse.md。

FastAPI 的 lifespan 和 CLI 共用这里，保证两边的 agent 完全一致。
测试时不走这里，而是直接构造一个装着假 LLM / 假工具的 Components。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from backend.agent.harness import Harness
from backend.agent.llm import LLMClient
from backend.agent.loop import AgentLoop
from backend.agent.mcp_client import MCPClientPool
from backend.agent.tracing import Tracing
from backend.store.base import SessionStore
from backend.store.memory import InMemorySessionStore

from .config import Settings


@dataclass
class Components:
    loop: AgentLoop
    store: SessionStore
    tracing: Tracing


def build_store(settings: Settings) -> SessionStore:
    if settings.database_url:
        # Day 4 接入 PostgresSessionStore。配置了却没实现时明确报错，
        # 而不是悄悄退回内存——那样数据会在重启后丢失，而你以为它存进了数据库
        raise RuntimeError("DATABASE_URL 已配置，但 Postgres 存储将在 Day 4 实现。请先留空 DATABASE_URL。")
    return InMemorySessionStore()


@asynccontextmanager
async def default_components(settings: Settings) -> AsyncIterator[Components]:
    """启动时进入、关闭时退出。MCP 子进程在这里启动和结束（同一个 task，见 docs/07）。"""
    tracing = Tracing.from_settings(
        settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host
    )
    llm = LLMClient(settings.llm_model, settings.llm_api_key, settings.llm_base_url)
    store = build_store(settings)
    try:
        async with MCPClientPool() as tools:
            loop = AgentLoop(
                llm=tracing.wrap_llm(llm, settings.llm_model),
                tools=tracing.wrap_tools(tools),
                harness=Harness(max_iterations=settings.max_iterations),
            )
            yield Components(loop=loop, store=store, tracing=tracing)
    finally:
        tracing.shutdown()
