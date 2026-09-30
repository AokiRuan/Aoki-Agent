"""把 MCP server 拉成子进程、建立 stdio 会话的测试辅助。讲解见 docs/03-mcp-server.md。"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def stdio_session(module: str):
    """例：async with stdio_session("backend.mcp_servers.seichi.server") as session: ..."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        cwd=str(PROJECT_ROOT),
        env={"PYTHONIOENCODING": "utf-8"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
