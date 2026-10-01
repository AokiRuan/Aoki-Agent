# 踩坑日志

开发过程中真实遇到的问题。每条按「现象 → 根因 → 解法 → 教训」记录。新坑追加在对应分类末尾。

**目录**：[Python 导入与运行](#python-导入与运行) · [Windows 环境](#windows-环境) · [依赖与包管理](#依赖与包管理) · [MCP SDK 2.x](#mcp-sdk-2x) · [第三方 API](#第三方-api) · [LLM 行为与输出](#llm-行为与输出)

---

## Python 导入与运行

### 测试目录叫 `test` 导致 ModuleNotFoundError

- **现象**：`python -m test.test_simple_agent` 报 `No module named test.test_simple_agent`，文件明明就在 `test/` 下
- **根因**：Python 标准库自带一个叫 `test` 的包（CPython 自己的测试套件，位于 `anaconda3\Lib\test\`）。项目的 `test/` 没有 `__init__.py`，是"命名空间包"；导入系统扫描 `sys.path` 时，命名空间包只是候选，**一旦在后面的路径找到同名的常规包（带 `__init__.py`），常规包胜出**。于是 `test` 被解析成了标准库那个
- **解法**：目录改名为 `tests`
- **教训**：别用标准库已有的名字给自己的包命名（`test`、`email`、`logging`、`queue`……）。不确定时 `python -c "import 名字; print(名字.__file__)"` 查一下

### 直接运行脚本，找不到同级目录的包

- **现象**：`python tests/test_simple_agent.py` 报 `No module named 'agent'`
- **根因**：直接运行脚本时，`sys.path[0]` 是**脚本所在目录**（`tests/`），不是项目根目录。`agent/` 在根目录下，自然找不到
- **解法**：在项目根目录用 `python -m tests.test_simple_agent`。`-m` 模式下 `sys.path[0]` 是当前工作目录
- **教训**：项目内一律 `python -m 模块路径`，一律在根目录执行。详见 [02 章](02-project-setup.md#包与导入为什么必须在根目录运行)

---

## Windows 环境

### 打印 emoji 报 UnicodeEncodeError

- **现象**：`print(f"✅ ...")` 报 `'gbk' codec can't encode character '✅'`
- **根因**：中文 Windows 终端默认代码页是 GBK，GBK 字符集里没有 emoji。Python 按终端编码输出，遇到编不了的字符就崩
- **解法**：`$env:PYTHONIOENCODING = "utf-8"` 强制 Python 用 UTF-8 输出。想永久生效可以设成用户级环境变量
- **教训**：Docker/Linux 下不会有这个问题，只在 Windows 本地开发时出现。**不要为了绕过它去删代码里的 emoji**——那是在修症状

### PowerShell 里 `python -c` 传多行代码被破坏

- **现象**：用 here-string 给 `python -c` 传多行代码，报 `SyntaxError: '(' was never closed`，f-string 的引号被吃掉了
- **根因**：PowerShell 5.1 调用原生程序时，对参数里的双引号的转义规则和 Python 期望的不一致
- **解法**：多于一行的代码，写成临时 `.py` 文件再执行
- **教训**：`python -c` 只用来跑单行、不含双引号嵌套的代码

---

## 依赖与包管理

### venv 里没有 pip

- **现象**：`python -m pip install ...` 报 `No module named pip`
- **根因**：`.venv` 是 `uv` 创建的（`.venv/pyvenv.cfg` 里有 `uv = ...`），uv 创建的 venv 默认不装 pip
- **解法**：用 `uv pip install ...`
- **教训**：遇到陌生环境先看 `pyvenv.cfg`，弄清楚是谁建的

### pypi.org 连接超时

- **现象**：`uv pip install` 重试 3 次、132 秒后报 `operation timed out`
- **根因**：国内网络直连 pypi.org 不稳定
- **解法**：`--index-url https://pypi.tuna.tsinghua.edu.cn/simple`，或设用户级环境变量 `UV_DEFAULT_INDEX`
- **教训**：写 Dockerfile 时同样要考虑——CI 跑在 GitHub（海外）不需要镜像，本地构建镜像时可能需要。别把镜像地址硬编码进 Dockerfile

---

## MCP SDK 2.x

**总教训：MCP SDK 1.x → 2.x 有大量破坏性改名，而网上绝大多数教程是 1.x 写法。写 MCP 代码时不要信搜索结果，直接看已安装版本的实际 API：**

```python
import inspect
from mcp.server.mcpserver import MCPServer
print(inspect.signature(MCPServer.tool))
```

### `FastMCP` 不存在

- **现象**：`from mcp.server.fastmcp import FastMCP` 报 `No module named 'mcp.server.fastmcp'`
- **根因**：2.x 把 `FastMCP` 改名为 `MCPServer`，导入路径也变了（错误信息里直接给了迁移指南链接）
- **解法**：`from mcp.server.mcpserver import MCPServer`。`@mcp.tool()` 装饰器和 `run()` 用法不变
- **预防**：`requirements.txt` 里钉住 `mcp>=2.2`

### `tool.inputSchema` 不存在

- **现象**：`'Tool' object has no attribute 'inputSchema'. Did you mean: 'input_schema'?`
- **根因**：2.x 的 Python 对象字段统一改成 snake_case：`inputSchema` → `input_schema`、`isError` → `is_error`、`structuredContent` → `structured_content`。**注意：JSON-RPC 线上传输的字段名仍是 camelCase**，只有 Python 侧改了
- **解法**：用 snake_case

### `list_tools()` 返回 coroutine

- **现象**：`TypeError: 'coroutine' object is not iterable`
- **根因**：2.x 里 `MCPServer.list_tools()` 是 async 方法
- **解法**：`await server.mcp.list_tools()`

### 返回 list 的工具，结构化结果被包了一层

- **现象**：工具返回 `[{...}]`，client 拿到的 `structured_content` 是 `{"result": [{...}]}`
- **根因**：MCP 规范要求 `structuredContent` 必须是 JSON object，所以 SDK 把非 object 的返回值包进 `result` 键
- **解法**：client 端解析时判断并解包
- **状态**：Day 2 写 mcp_client 时要处理

### 工具里抛异常，LLM 看不到原因

- **现象**：工具里 `raise ValueError("bad x=1")`，client 只收到 `Error executing tool boom`
- **根因**：SDK 的安全设计——未预期的异常不把内部信息泄露给 client。同时，**跨进程调用时异常不会让 client 抛错**，而是返回 `is_error=True` 的正常结果
- **解法**：可预期的错误主动 `return {"error": "具体原因"}`；client 端检查 `is_error` 而不是 `try/except`
- **详细对比**：[03 章 · 原则 5](03-mcp-server.md#5-错误是数据不是异常)

### 测试 teardown 报 "exit cancel scope in a different task"

- **现象**：用 pytest 异步 fixture 管理 MCP 连接（`yield` 前 connect、后 close），测试本身全部通过，但每个测试在 teardown 阶段报 `RuntimeError: Attempted to exit cancel scope in a different task than it was entered in`
- **根因**：MCP SDK 的 `stdio_client` 基于 anyio，要求连接在同一个 asyncio task 里打开和关闭；pytest-asyncio 在不同的 task 里执行 fixture 的 setup 和 teardown
- **解法**：`MCPClientPool` 实现 `__aenter__` / `__aexit__`，每个测试里用 `async with`
- **教训**：FastAPI 的 lifespan（一个函数里 yield 前后）天然满足这个约束；「startup 事件打开、shutdown 事件关闭」则不满足。详见 [07 章](07-mcp-client.md#生命周期必须在同一个-task-里打开和关闭)

### 子进程拿不到终端里设置的环境变量

- **现象**：（预防性发现，未实际出错）在终端设置的环境变量，MCP server 子进程里读不到
- **根因**：实测 SDK 启动子进程时用 `get_default_environment() | server.env`，默认只有 12 个系统变量（PATH、APPDATA、TEMP 等），出于安全考虑不继承其他变量
- **解法**：需要的变量显式传入 `StdioServerParameters(env=...)`。项目里透传了代理相关变量，否则在代理环境下天气/路线 server 会连不上外网，且只报一个笼统的超时
- **教训**：遇到「终端里能用、子进程里不行」，先查环境变量

---

## 第三方 API

### Anitabi 文档说有坐标，实际没有

- **现象**：文档示例里每个地标都有 `geo: [lat, lng]`，实测两部作品 0/84、0/63
- **根因**：线上 API 已变更，文档未同步
- **解法**：当前用 mock 数据；将来需从 `originURL` 提取（覆盖 42%）+ 地理编码补齐
- **教训**：**第三方 API 先写探测脚本、统计字段出现率，再写业务代码**。方法见 [03 章 · 先探测再写代码](03-mcp-server.md#案例先探测再写代码)

### Cloudflare 限流

- **现象**：约 25 个请求后全部返回 403 + HTML 挑战页，45 秒后仍未恢复
- **根因**：Anitabi 前置了 Cloudflare 防护
- **解法**：探测时控制频率；正式使用必须加本地缓存
- **教训**：演示当天依赖一个会限流的外部 API 是赌博。关键路径上的外部依赖要有离线兜底

### OSRM 官方 demo 的步行结果其实是驾车

- **现象**：`router.project-osrm.org/route/v1/foot/...` 和 `/driving/...` 返回完全相同的结果（京都音乐厅 → 宇治桥：21.6km、32 分钟）。不报错，看起来一切正常
- **根因**：官方 demo 只部署了驾车 profile，URL 里的 profile 段被忽略
- **解法**：改用 FOSSGIS 实例，它按 profile 分开部署：`routing.openstreetmap.de/routed-foot/...`（同一段路步行 20.5km、4.5 小时，符合步行速度）
- **教训**：**不报错的错误结果最危险**。探测时要检查结果是否符合常识（21km 步行 32 分钟显然不对），而不只是看状态码是不是 200

### 地理编码匹配到同名的其他地点

- **现象**：用 Nominatim 核对 mock 数据时，「須賀神社 男坂」没查到，退回只查「須賀神社」，结果匹配到仙台的一座同名神社，和东京的原坐标相差 302km
- **根因**：日本同名的神社、车站、公园非常多，只给名称时 Nominatim 按知名度排序
- **解法**：查询时加上城市名（实测「須賀神社 新宿区」就能找到正确的那座，离原坐标 115m）；从多个候选里选离预期位置最近的；偏差过大的结果人工确认，不自动采纳
- **教训**：这就是 `geocode` 工具返回多个候选、并在描述里要求 LLM「根据上下文选择」的原因。批量处理地理编码结果时，不能不看就直接替换

---

## LLM 行为与输出

### 流式输出每个字重复两遍

- **现象**：「没问题没问题！！我来我来帮你帮你」
- **根因**：`hello_agents` 的 `HelloAgentsLLM.think()` 是个生成器，它**在 yield 之前自己已经 print 了一遍**；调用方 `for chunk in llm.think(...)` 里又 print 了一遍
- **解法**：调用方只消费、不再打印
- **教训**：生成器最好只负责产出数据，不要在里面做 print 这类副作用。这正是本项目 `AgentLoop` 只 yield `AgentEvent`、由上层决定怎么展示的原因（[01 章 · 原则二](01-architecture.md#原则二用事件流对外输出而不是直接写响应)）

### 中文提问，LLM 却用英文说「我来查一下」

- **现象**：DeepSeek 返回 tool_calls 时附带的说明文字是英文（`I'll look up that anime first.`），最终回答却是中文
- **根因**：模型在「调工具前的过渡语」上有英文的倾向；system prompt 里抽象的「使用用户的语言」没能覆盖到这一句
- **解法**：把规则写具体：「调用工具前的说明文字也一样：用户用中文提问，就用中文说『我来查一下』，不要用英文」
- **教训**：写 prompt 时，**具体的例子比抽象的规则管用**

### LLM 在回答里抄错了坐标

- **现象**：LLM 把京都音乐厅的纬度 35.0504 写成了 34.0504
- **根因**：LLM 生成文本时抄写长数字不可靠
- **解法**：不让它抄——前端地图用 `tool_result` 事件里的结构化数据打点，这条通道不经过 LLM；system prompt 里要求不要在回答里写经纬度
- **教训**：**精确数据（坐标、价格、ID）走结构化通道，LLM 只负责自然语言**。详见 [05 章实测发现](05-agent-loop.md#实测发现)
