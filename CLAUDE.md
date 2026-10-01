# Aoki-Agent

日本动画圣地巡礼 agent：FastAPI 后端 + 自建 agent loop/harness + MCP 工具 + React 前端。计划见 [docs/00-project-plan.md](docs/00-project-plan.md)。

**这是一个学习项目。用户的目标是理解自建 agent 项目的全流程，文档与代码同等重要。**

## 代码与文档同步（必须遵守）

学习手册在 [docs/](docs/)，索引与章节模板见 [docs/README.md](docs/README.md)。

- **改代码的同一轮里更新对应章节**。不要攒到最后补，也不要等用户提醒
- **新模块 → 新章节**：按 docs/README.md 的六段模板写（本章目标 / 核心概念 / 代码走读 / 设计取舍 / 动手验证 / 延伸思考），并更新索引里的状态
- **踩到坑就记进 [docs/pitfalls.md](docs/pitfalls.md)**：报错、库版本差异、第三方 API 与文档不符等，按「现象 → 根因 → 解法 → 教训」
- **文档里的命令必须实测过**。没法实测的（比如依赖未安装的工具）明确标注「未实测」
- **讲为什么，不只讲是什么**：每个设计决策都说明备选方案和不选它的理由
- **文档描述当前真实状态**，用 ✅ 已实现 / 🚧 骨架待填 / ⏳ 未开始 标注
- **代码模块的 docstring 顶部指向对应章节**，如 `讲解见 docs/03-mcp-server.md`
- 计划或决策变化时同步更新 docs/00-project-plan.md
- 文档与代码注释用中文

## 运行约定

- 所有命令在项目根目录执行，用 `python -m 模块路径`，不要按文件路径运行脚本（项目用绝对导入 `backend.xxx`）
- venv 由 uv 创建，**没有 pip**：装包用 `uv pip install`；国内网络加 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`
- Windows 终端需 `$env:PYTHONIOENCODING = "utf-8"`，否则打印 emoji 崩溃
- 测试：`python -m pytest`（配置见 pytest.ini，`asyncio_mode = auto`；打真实外部 API 的测试标记为 `network`，默认不跑）
- 命令行和 agent 对话：`python -m backend.cli "问题"`（会消耗 LLM token）；列出全部工具：`python -m backend.agent.mcp_client`
- 启动：`uvicorn backend.app.main:app --reload`
- `MCPClientPool` 必须在同一个 asyncio task 里打开和关闭（用 `async with`），不要用 pytest 的 async yield fixture 管理它

## 架构约束

- **依赖方向**：`backend/agent/` 不得 import `backend/app/` 或 `backend/store/`。loop 对 HTTP、数据库、具体 LLM 一无所知，外部依赖通过构造参数注入
- loop 只 yield `AgentEvent`（backend/agent/events.py），不直接写响应、不 print
- 会变的东西先立接口（`SessionStore`、`LLMClient`、`SeichiRepository`）
- 工具错误作为数据返回给 LLM，不抛异常中断对话

## MCP SDK 2.x

装的是 mcp 2.x，与网上多数 1.x 教程不兼容：`FastMCP` → `MCPServer`（`from mcp.server.mcpserver import MCPServer`），Python 侧字段 snake_case（`input_schema`、`is_error`、`structured_content`），`list_tools()` 是 async。**写 MCP 代码前用 `inspect.signature` 核实实际 API。** stdio server 里禁止 print 到 stdout。
