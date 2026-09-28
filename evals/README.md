# evals

Agent 评测。**Day 6+，不在 5 天 demo 范围内。**

- **评测集**：20~30 条 query，每条标注期望的工具调用序列与期望命中的圣地
- **指标**：工具选择准确率、圣地召回率、LLM-as-judge 评回答质量
- **工具**：Langfuse Datasets + Experiments，结果与 trace 关联，改 prompt 后可对比回归

评测框架搭好后，harness 的每次改动都有量化反馈——这才是评测的真正价值。

前置条件：`backend/agent/loop.py` 的 `AgentLoop.run()` 直接产出事件流，
评测脚本可以绕过 HTTP 层直接消费，不需要起服务。
