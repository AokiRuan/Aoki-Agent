"""Harness —— 包在 agent loop 外面的运行时策略。

把「循环怎么跑」和「循环跑失控了怎么办」分开：loop.py 只管主流程，
边界条件、降级策略、上下文裁剪都放这里。这是本项目主要的学习点。

需要覆盖：
- 迭代上限：超过 max_iterations 时强制让 LLM 基于已有信息总结，而不是硬截断
- 错误恢复：工具调用失败不中断循环，把错误信息作为 tool result 交给 LLM 自行处理
- 上下文管理：demo 阶段简单截断即可，保留 system + 最近 N 轮
- 重复调用检测：同样的工具同样的参数连续调用多次，说明 LLM 卡住了
"""


class Harness:
    def __init__(self, max_iterations: int = 8, max_history_messages: int = 40) -> None:
        self.max_iterations = max_iterations
        self.max_history_messages = max_history_messages

    def should_continue(self, iteration: int) -> bool:
        """是否允许再跑一轮。"""
        return iteration < self.max_iterations

    def trim(self, messages: list[dict]) -> list[dict]:
        """裁剪上下文。注意：tool_calls 与其对应的 tool result 必须成对保留，
        否则多数 provider 会直接报错。"""
        raise NotImplementedError

    def on_tool_error(self, tool_name: str, error: Exception) -> str:
        """把工具异常转成给 LLM 看的文本结果。"""
        return f"工具 {tool_name} 调用失败：{error}"
