"""命令行调试入口：不经过 HTTP，直接在终端里和 agent 对话。讲解见 docs/05-agent-loop.md。

    python -m backend.cli "莉可丽丝的圣地在哪？"     # 单次提问
    python -m backend.cli                           # 交互模式，支持多轮对话，输入 exit 退出

这个文件是「组装点」：它负责把 LLM、MCP 工具、harness 创建出来并注入 AgentLoop。
Day 2 后半段的 FastAPI 做的是同一件事，只是把终端换成了 HTTP。
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from backend.agent.events import AgentEvent
from backend.agent.harness import Harness
from backend.agent.llm import LLMClient
from backend.agent.loop import AgentLoop
from backend.agent.mcp_client import MCPClientPool
from backend.agent.prompts import build_system_prompt
from backend.app.config import settings


async def ask(loop: AgentLoop, history: list[dict[str, Any]], question: str) -> None:
    user_msg = {"role": "user", "content": question}
    messages = [{"role": "system", "content": build_system_prompt()}, *history, user_msg]

    async for event in loop.run(messages):
        render(event)
        if event.type == "done":
            # system prompt 每次重新生成，不进历史；历史里只存对话本身
            history.append(user_msg)
            history.extend(event.payload["new_messages"])


def render(event: AgentEvent) -> None:
    if event.type == "token":
        print(event.content)
    elif event.type == "tool_call":
        args = json.dumps(event.payload, ensure_ascii=False)
        print(f"  🔧 {event.tool_name}({args})")
    elif event.type == "tool_result":
        print(f"  {'❌' if event.payload['is_error'] else '✅'} {event.tool_name} → {summarize(event.payload['data'])}")
    elif event.type == "done":
        p = event.payload
        print(f"  —— {p['iterations']} 轮 LLM 调用，{p['usage'].get('total_tokens', '?')} tokens")
    elif event.type == "error":
        print(f"  ⚠️ {event.message}")


def summarize(data: Any) -> str:
    if isinstance(data, list):
        return f"{len(data)} 条结果"
    if isinstance(data, dict) and "error" in data:
        return f"错误：{data['error']}"
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return text if len(text) <= 80 else text[:80] + "…"


async def main(argv: list[str]) -> None:
    llm = LLMClient(settings.llm_model, settings.llm_api_key, settings.llm_base_url)
    history: list[dict[str, Any]] = []

    # async with：保证三个 MCP 子进程在退出时（包括出错时）一定被关掉
    async with MCPClientPool() as tools:
        loop = AgentLoop(llm, tools, Harness(max_iterations=settings.max_iterations))
        if argv:
            await ask(loop, history, " ".join(argv))
            return
        print("圣地巡礼助手（输入 exit 退出）")
        while True:
            # input() 会阻塞，放到线程里执行，避免卡住事件循环
            question = (await asyncio.to_thread(input, "\n你> ")).strip()
            if question.lower() in ("exit", "quit"):
                break
            if question:
                await ask(loop, history, question)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
