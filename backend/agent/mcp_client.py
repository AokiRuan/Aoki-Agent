"""MCP 客户端聚合层。

职责：
1. 启动时连接所有 MCP server（自建圣地 server 走 stdio 子进程，外部服务按配置）
2. 拉取各 server 的工具列表，转成 LLM 需要的 tool schema
3. 按工具名把调用分发到对应的 server
4. 维护工具名到 server 的映射，处理重名

MCP 协议本身已提供工具 schema，所以这里不需要像 learn/tools/registry.py
那样手工拼 JSON Schema，只做格式转换与聚合。
"""
from typing import Any


class MCPClientPool:
    """管理到多个 MCP server 的连接。"""

    def __init__(self) -> None:
        # TODO(Day 1-2): 会话句柄、工具名 -> server 的映射
        raise NotImplementedError

    async def connect_all(self) -> None:
        """连接所有已配置的 MCP server 并完成工具发现。应在 FastAPI lifespan 中调用。"""
        raise NotImplementedError

    async def list_tool_schemas(self) -> list[dict[str, Any]]:
        """返回可直接传给 LLM 的 tool schema 列表。"""
        raise NotImplementedError

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用工具。失败时不要抛到 loop 外——把错误作为结果返回，交给 LLM 自行处理。"""
        raise NotImplementedError

    async def close(self) -> None:
        """关闭所有连接与子进程。"""
        raise NotImplementedError
