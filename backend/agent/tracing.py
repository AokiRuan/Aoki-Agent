"""Langfuse 可观测性接入。

Day 2 就接，不要留到最后——它是调试 agent loop 最好用的工具：
一眼看到 LLM 每轮收到什么上下文、决定调哪个工具、工具返回了什么。

用法：
- LLM 调用：用 langfuse.openai 的 drop-in 替换，自动记录 token 数与耗时
- loop 与工具调用：用 @observe() 装饰
- 演示时打开 trace 页面展示 agent 的完整决策链，这是「自建 harness」最直观的证明
"""


def init_tracing(public_key: str | None, secret_key: str | None, host: str | None) -> None:
    """初始化 Langfuse。未配置 key 时应静默跳过，不阻塞本地开发。"""
    raise NotImplementedError
