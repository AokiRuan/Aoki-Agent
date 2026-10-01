"""Harness —— 包在 agent loop 外面的运行时策略。讲解见 docs/06-harness.md。

把「循环怎么跑」和「循环跑失控了怎么办」分开：loop.py 只管主流程，
边界条件、降级策略、上下文裁剪都放这里。

重要：Harness 实例在应用里只有一个、被所有请求共享，所以它是**无状态**的——
只持有配置，不记录任何「本次运行」的信息。每次运行的状态（第几轮、调用过什么）
由 loop 自己在局部变量里维护，再作为参数传进来。
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

FORCE_FINAL_INSTRUCTION = (
    "已达到本轮对话的工具调用次数上限，不能再调用工具。"
    "请只根据上面已经获得的信息直接回答用户；信息不足的部分如实说明。"
)


class Harness:
    def __init__(
        self,
        max_iterations: int = 8,
        max_history_messages: int = 40,
        max_repeat_calls: int = 2,
    ) -> None:
        # 一次 run 里最多问 LLM 几轮（每轮可能包含多个并行的工具调用）
        self.max_iterations = max_iterations
        # 送给 LLM 的历史消息上限（不含 system）
        self.max_history_messages = max_history_messages
        # 同一个工具、同样的参数，最多真正执行几次
        self.max_repeat_calls = max_repeat_calls

    # ------------------------------------------------------------ 迭代上限

    def should_continue(self, iteration: int) -> bool:
        """第 iteration 轮（从 1 开始）是否还允许带着工具去问 LLM。"""
        return iteration <= self.max_iterations

    def force_final_message(self) -> dict[str, Any]:
        """超过上限时追加的指令：不再提供工具，让 LLM 基于已有信息收尾。

        比直接截断好：用户至少能拿到一个基于已有信息的回答。
        """
        return {"role": "user", "content": FORCE_FINAL_INSTRUCTION}

    # ------------------------------------------------------------ 重复调用检测

    @staticmethod
    def call_key(name: str, arguments: dict[str, Any]) -> str:
        return name + ":" + json.dumps(arguments, sort_keys=True, ensure_ascii=False)

    def repeated_call_message(self, name: str, arguments: dict[str, Any], seen: Counter) -> str | None:
        """同样的调用已经执行够多次时，返回给 LLM 的提示；否则返回 None 并计数。

        LLM 反复用同样的参数调同一个工具，通常说明它卡住了。再执行一次只会得到
        同样的结果，不如直接提醒它。
        """
        key = self.call_key(name, arguments)
        if seen[key] >= self.max_repeat_calls:
            return (
                f"你已经用相同的参数调用过 {name} {seen[key]} 次，结果不会变化，见上文。"
                "请换一种方式，或直接根据已有信息回答。"
            )
        seen[key] += 1
        return None

    # ------------------------------------------------------------ 错误转译

    @staticmethod
    def argument_error_message(name: str, error: str) -> str:
        return f"调用 {name} 失败：{error}。请修正参数后重试。"

    # ------------------------------------------------------------ 上下文裁剪

    def trim(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """保留所有 system 消息 + 最近的若干条消息。

        裁剪的起点必须落在一条 user 消息上。否则可能留下一条 role=tool 的消息，
        但它对应的、带 tool_calls 的 assistant 消息被裁掉了——多数 LLM 服务会直接报错。
        """
        system = [m for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        if len(rest) <= self.max_history_messages:
            return system + rest

        tail = rest[-self.max_history_messages :]
        for i, m in enumerate(tail):
            if m.get("role") == "user":
                return system + tail[i:]
        # 极端情况：最近的消息里一条 user 都没有（单轮里工具调用极多），
        # 退回到最后一条 user 消息，宁可超长也不能拆散 tool_calls 与结果
        last_user = max((i for i, m in enumerate(rest) if m.get("role") == "user"), default=None)
        return system + (rest[last_user:] if last_user is not None else tail)
