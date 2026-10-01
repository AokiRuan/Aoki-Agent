# 07 · MCP Client

## 本章目标

读完能回答：

- 03、04 章写的三个 MCP server，agent 这一侧是怎么把它们接进来的？
- 工具调用失败有哪几种？分别怎么告诉 LLM？
- 为什么子进程连不上外网的问题可能和环境变量有关？
- `Attempted to exit cancel scope in a different task` 这个报错是什么意思？为什么用 `async with` 就解决了？

## 核心概念

[03 章](03-mcp-server.md)和 [04 章](04-external-mcp-servers.md)写的是 MCP 的 **server** 端：把功能暴露成工具。本章是 **client** 端：agent 这边怎么连上这些 server、怎么调用。

client 要解决的问题是**聚合**：LLM 面对的是一份统一的工具清单（6 个工具），它不需要、也不应该知道这些工具分别来自哪个 server、通过什么方式通信。

```
                         ┌─ seichi 子进程 ─ search_anime / list_spots / get_spot
loop ─ MCPClientPool ────┼─ weather 子进程 ─ get_weather_forecast
                         └─ route 子进程 ─── geocode / plan_route
```

对 loop 来说，工具层只有两个方法：

```python
class ToolExecutor(Protocol):
    def tool_schemas(self) -> list[dict]: ...                        # 给 LLM 的工具清单
    async def call_tool(self, name, arguments) -> ToolOutcome: ...   # 执行一个工具
```

[05 章的测试](05-agent-loop.md#测试)里的 `FakeTools` 就是只实现了这两个方法。

## 代码走读

[mcp_client.py](../backend/agent/mcp_client.py)

### 启动与工具发现

```python
DEFAULT_SERVERS = (
    ServerSpec("seichi",  "backend.mcp_servers.seichi.server"),
    ServerSpec("weather", "backend.mcp_servers.weather.server"),
    ServerSpec("route",   "backend.mcp_servers.route.server"),
)
```

`connect_all()` 依次启动每个 server，完成握手，拉取工具列表，建立"工具名 → 所属 server 的会话"的映射。

**工具名冲突时直接失败**。两个 server 都提供了叫 `search` 的工具时，与其让后注册的悄悄覆盖先注册的（LLM 以为调的是 A，实际调到了 B），不如启动时就报错。**配置错误应该在启动时暴露，而不是在运行时以奇怪的方式表现出来。**

**启动失败时清理自己**。如果第三个 server 启动失败，前两个已经启动的子进程不能留着不管，`connect_all()` 会在抛出异常前关掉它们。

三个子进程依次启动，实测共约 3 秒。可以并行启动来加快，但这只在应用启动时发生一次，不值得增加复杂度。

### 子进程的环境变量

```python
PASSTHROUGH_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", ...)

env = {"PYTHONIOENCODING": "utf-8"}
env.update({k: os.environ[k] for k in PASSTHROUGH_ENV if k in os.environ})
```

为什么要显式传代理变量？实测 MCP SDK 启动子进程时的环境变量是这样组成的：

```python
env = get_default_environment() | (server.env or {})
```

`get_default_environment()` 在 Windows 上只包含 12 个系统变量：`APPDATA`、`PATH`、`SYSTEMROOT`、`TEMP`、`USERPROFILE` 等。**你在终端里设置的其他环境变量，子进程都拿不到。**

这是 SDK 出于安全考虑的设计：MCP server 可能是第三方写的，不应该默认拿到你所有的环境变量（里面可能有各种 API key）。代价是，如果你通过代理上网，天气和路线 server 会连不上外部 API，而且报错只会是一个笼统的超时，很难想到原因。所以把代理相关的变量显式传进去。

同理，将来如果某个 server 需要 API key，也要通过 `env` 显式传入，而不能指望它自己从环境里读到。

另外两个参数：

- `command=sys.executable`：用**当前 venv 的 Python** 启动子进程。直接写 `"python"` 的话，可能启动的是系统里另一个 Python，找不到项目依赖
- `cwd=PROJECT_ROOT`：子进程要以 `python -m backend.mcp_servers.xxx` 的方式启动，工作目录必须是项目根目录（原因见 [02 章](02-project-setup.md#包与导入为什么必须在根目录运行)）

### 转成 LLM 的工具格式

```python
def _to_openai_schema(tool):
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": inspect.cleandoc(tool.description or ""),
            "parameters": tool.input_schema,
        },
    }
```

MCP 的工具定义和 OpenAI 的 tools 格式几乎一一对应，只是外面包了一层。`inspect.cleandoc` 去掉 docstring 里的缩进：不清理的话，每个工具描述里都带着一堆 `\n    `，每次调用 LLM 都要为这些空格付 token 费用（[03 章](03-mcp-server.md#llm-怎么知道有哪些工具json-schema)导出 schema 时发现的）。

### 调用与结果：三种结局

`call_tool()` 返回一个 `ToolOutcome`：

```python
@dataclass
class ToolOutcome:
    data: Any       # 结构化结果，给前端用（地图打点等）
    is_error: bool  # 协议层面是否失败
    text: str       # 回填给 LLM 的文本
```

**`data` 和 `text` 分开**，对应 [05 章实测发现 2](05-agent-loop.md#实测发现)：精确的结构化数据走 `data` 直接给前端，LLM 只看 `text`。

一次工具调用可能有三种结局，实测结果如下：

| 情况 | 例子 | `is_error` | LLM 看到的 |
|---|---|---|---|
| 成功 | `search_anime("莉可丽丝")` | False | 结果的 JSON |
| **业务上的失败** | `get_spot("bad-id")` | **False** | `{"error": "未找到圣地 bad-id"}` |
| 协议层面的失败 | 参数类型错、工具不存在、工具内部异常、子进程崩溃 | True | 错误原因 |

第二行值得注意："查不到"对工具来说是**正常执行完毕、如实报告结果**，协议上是成功的。"参数类型不对"才是调用本身失败了。这个区分会影响将来的评测统计：工具失败率应该只统计第三行。

处理结果时的三个细节，都是 Day 1 记下的：

- **检查 `is_error`，而不是用 try/except**。跨进程调用时工具出错不会让 client 抛异常（[03 章原则 5](03-mcp-server.md#5-错误是数据不是异常)）
- **解包 `{"result": [...]}`**。返回列表的工具，SDK 会把结构化结果包一层（[踩坑日志](pitfalls.md#返回-list-的工具结构化结果被包了一层)）
- **JSON 用 `ensure_ascii=False`**。不加的话中文会变成 `\u8389\u53ef` 这样的转义序列：LLM 能读懂，但一个汉字变成了 6 个 ASCII 字符，白白增加 token 消耗

还有第 4 种情况：**子进程崩溃、管道断开**。`session.call_tool()` 会抛异常，这里捕获后同样转成 `is_error=True` 的结果交给 LLM，不让它打断对话。

### 生命周期：必须在同一个 task 里打开和关闭

写测试时遇到了这个报错：

```
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

原因是 MCP SDK 的 `stdio_client` 基于 **anyio** 实现，anyio 要求一个"作用域"在哪个 asyncio task 里打开，就必须在同一个 task 里关闭。而 pytest-asyncio 的异步 fixture：

```python
@pytest.fixture
async def pool():
    p = MCPClientPool()
    await p.connect_all()   # ← setup，在 task A 里执行
    yield p
    await p.close()         # ← teardown，在 task B 里执行 → 报错
```

setup 和 teardown 是在**不同的 task** 里执行的，于是违反了这条规则。测试本身都通过了，只是清理时报错。

解决方法是给 `MCPClientPool` 实现 `__aenter__` / `__aexit__`，改用 `async with`：

```python
async with MCPClientPool() as pool:
    ...                       # 打开和关闭发生在同一个函数里，天然是同一个 task
```

这个约束在项目其他地方同样适用：

- **CLI**：`main()` 里用 `async with`，退出时（包括出错时）一定会关掉三个子进程
- **FastAPI**：lifespan 是一个函数，`yield` 之前打开、之后关闭，同一个 task，没问题。但如果写成"在 startup 事件里打开、在 shutdown 事件里关闭"，就会踩这个坑

## 设计取舍

**每个 server 一个子进程，还是把工具都写在一个进程里？**

一个进程更省资源，启动更快。分开的好处是隔离：路线 server 因为网络问题卡死或崩溃，圣地查询不受影响。每个 server 也可以单独开发、单独测试、单独给其他 MCP 客户端（比如 Claude Desktop）使用。

**工具冲突时报错，还是自动加前缀？**

有些框架会自动把工具名改成 `seichi__search_anime` 这样来避免冲突。好处是不会报错，坏处是工具名变长了，LLM 看到的名字和 server 里定义的不一样，排查问题时要多一层转换。本项目只有 3 个自己写的 server，冲突说明设计有问题，直接报错更合适。

## 动手验证

```powershell
# 真实拉起子进程测试（不需要联网，也不花 token）
python -m pytest -v backend/tests/test_mcp_client.py

# 列出 LLM 实际能看到的全部工具，以及各自来自哪个 server
python -m backend.agent.mcp_client
```

## 延伸思考

1. 某个 server 的子进程在运行中途崩溃了，现在的代码会怎样？之后对这个 server 的每次调用都会失败。要实现自动重启，应该放在哪一层？
2. `ToolOutcome.text` 里是工具结果的完整 JSON。`list_spots` 如果返回 500 个地标，这段文本会非常长。这个问题应该在 server 端解决（[03 章原则 3](03-mcp-server.md#3-输出要省-token)），还是 client 端截断？各有什么问题？
3. 为什么业务失败（查不到）的 `is_error` 是 False？如果改成 True，对 LLM 的行为会有影响吗？对评测统计呢？
