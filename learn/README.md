# learn

学习期代码，**仅作参考，不参与构建与部署**。

基于 `hello_agents` 做继承式改写，用于理解 agent 循环、工具注册、上下文管理的设计取舍。
新项目代码在 `backend/` 与 `frontend/`。

运行（从项目根目录，Windows 需设 `PYTHONIOENCODING=utf-8` 否则 emoji 打印会崩）：

```bash
python -m learn.tests.test_simple_agent
```

值得回看的几处：

- [tools/registry.py](tools/registry.py) —— 手工拼 JSON Schema 导出 OpenAI function-calling 格式。
  新项目改用 MCP，协议本身提供 schema，这层退化为 MCP client 的聚合层
- [tools/calculator_tool.py](tools/calculator_tool.py) —— AST 白名单求值，处理不可信输入的安全思路
- [agent/simple_agent.py](agent/simple_agent.py) —— 靠正则解析 `[TOOL_CALL:...]` 文本标记来触发工具，
  对比新项目用 LLM 原生 tool_calls 的差别
