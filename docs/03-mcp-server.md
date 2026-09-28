# 03 · MCP Server：圣地巡礼

## 本章目标

读完能回答：

- MCP 是什么？和"在后端写个 Python 函数给 LLM 调"有什么区别？
- stdio 传输下，两个进程之间到底在传什么？为什么 server 里不能 `print()`？
- `@mcp.tool()` 装饰一个普通函数之后，LLM 是怎么知道这个工具的用途和参数的？
- 给 LLM 用的工具，和给程序员用的函数，设计上有什么不同？
- 为什么数据源要单独抽一层 Repository？
- 面对一个陌生的第三方 API，怎么在写代码之前摸清它的真实行为？

## 核心概念

### MCP 解决什么问题

没有 MCP 时，每个 agent 框架都有自己的工具定义方式——LangChain 一套、OpenAI Assistants 一套、[学习期的 hello_agents](../learn/tools/registry.py) 又一套。写好的工具换个框架就得重写。

**MCP（Model Context Protocol）把"工具提供方"和"工具使用方"用一个标准协议隔开**：

```
┌────────────────┐    MCP 协议     ┌────────────────┐
│  MCP Client    │ ◀────────────▶ │  MCP Server    │
│  (我们的 agent) │  JSON-RPC 2.0  │  (圣地巡礼工具) │
└────────────────┘                └────────────────┘
```

同一个 seichi server，我们的 agent 能用，Claude Desktop、Cursor 也能直接接——不用改一行代码。

MCP 定义了三种能力：**tools**（可调用的函数）、**resources**（可读取的数据）、**prompts**（提示词模板）。本项目只用 tools。

### stdio 传输：两个进程怎么说话

MCP 支持三种传输方式：`stdio`、`sse`、`streamable-http`。我们用 stdio：

1. Client 把 server **作为子进程启动**
2. Client 往子进程的 **stdin** 写 JSON-RPC 请求
3. Server 从 stdin 读请求，处理完往 **stdout** 写响应
4. Client 从子进程的 stdout 读响应

一次工具调用在管道里大致长这样：

```jsonc
// client → server (stdin)
{"jsonrpc": "2.0", "id": 3, "method": "tools/call",
 "params": {"name": "search_anime", "arguments": {"title": "莉可丽丝"}}}

// server → client (stdout)
{"jsonrpc": "2.0", "id": 3, "result": {"content": [...], "structuredContent": {...}, "isError": false}}
```

完整的会话顺序是：`initialize`（握手、交换能力）→ `tools/list`（拉取工具清单）→ 若干次 `tools/call`。

**由此得出一条硬规则：stdio server 里绝对不能 `print()`。** stdout 是协议通道，你 print 的任何东西都会被 client 当成 JSON-RPC 消息解析，直接破坏通信。调试信息写 stderr（`print(..., file=sys.stderr)` 或用 `logging`，它默认就写 stderr）。

为什么选 stdio 而不是 HTTP：seichi server 和后端跑在同一个容器里，子进程不需要端口、不需要网络配置、父进程退出子进程自动跟着退。外部的天气/路线服务如果是远程的，才需要 HTTP 传输。

## 代码走读

三个文件，职责分明：

```
mcp_servers/seichi/
├── server.py          MCP 协议层：把函数暴露成工具
├── repository.py      数据访问层：数据从哪来、怎么查
└── data/
    └── mock_spots.json   当前的数据源
```

### server.py：从普通函数到 MCP 工具

[server.py](../backend/mcp_servers/seichi/server.py) 核心就这几行：

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("seichi")
repo = get_repository()

@mcp.tool()
def list_spots(anime_id: int) -> list[dict[str, Any]]:
    """列出某作品的全部圣地：名称、经纬度、对应集数与时间点、所在城市。

    anime_id 来自 search_anime 的返回结果。
    """
    return repo.list_spots(anime_id)
```

`@mcp.tool()` 做了三件事：

1. **函数名 → 工具名**：`list_spots`
2. **docstring → 工具描述**：这段文字会原样发给 LLM，LLM 靠它判断什么时候该用这个工具
3. **类型标注 → 参数的 JSON Schema**：`anime_id: int` 自动变成

   ```json
   {"properties": {"anime_id": {"type": "integer", ...}}, "required": ["anime_id"]}
   ```

第 3 点就是 [learn/tools/registry.py](../learn/tools/registry.py) 里手工拼的那一大段 `to_openai_schema()`——现在从函数签名自动生成，不会再出现"改了函数参数但忘了改 schema"的问题。

类型标注不只是生成文档，**还会做运行时校验**。实测：传 `{"anime_id": "42"}` 会被自动转成整数 42；传 `{"anime_id": "nope"}` 会被拒绝，返回的错误信息里带着完整的 pydantic 校验详情——LLM 看到后可以自己修正参数重试。

**返回值**：工具返回 dict 或 list，SDK 会同时生成两份结果：`content`（JSON 序列化成的文本，给只认文本的 client 用）和 `structured_content`（结构化数据）。注意：**返回 list 时，`structured_content` 会被包成 `{"result": [...]}`**——Day 2 写 client 解析结果时要记得这一点。

最后：

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

这个文件用了相对导入（`from .repository import ...`），所以必须以模块方式启动：`python -m backend.mcp_servers.seichi.server`。原因见 [02 章](02-project-setup.md#包与导入为什么必须在根目录运行)。

### repository.py：把"数据从哪来"隔离出去

[repository.py](../backend/mcp_servers/seichi/repository.py) 定义了接口和实现：

```python
class SeichiRepository(ABC):
    def search_anime(self, title: str, limit: int = 5) -> list[dict]: ...
    def list_spots(self, anime_id: int) -> list[dict]: ...
    def get_spot(self, spot_id: str) -> dict | None: ...

class MockRepository(SeichiRepository):
    """读本地 JSON"""

def get_repository() -> SeichiRepository:
    return MockRepository()      # ← 将来切 Anitabi 只改这一行
```

server.py 只认识 `SeichiRepository` 这个接口，不知道数据来自 JSON 还是 HTTP API。这是 [01 章原则四](01-architecture.md#原则四会变的东西先立接口)的直接应用——而且这次是**真用上了**：数据源原计划用 Anitabi，实测发现不可用后，切 mock 只改了 `get_repository()` 一处。

几个实现细节：

- **`@lru_cache` 加载 JSON**：数据文件只在第一次访问时读一次，之后都从内存拿。代价是改了 JSON 要重启进程才生效
- **`_anime_brief()` 故意不带地标列表**：见下文「给 LLM 设计工具」第 3 条
- **`_spot_out()` 做字段转换**：把 Anitabi 的 `geo: [lat, lng]` 拆成 `lat` / `lng`，`ep` / `s` 改名成 `episode` / `timestamp_sec`。原因见下文第 4 条

## 给 LLM 设计工具的六条原则

这是本章最重要的部分。**工具的使用者是 LLM，不是程序员**——这个视角转换会改变很多设计决策。

### 1. docstring 是写给 LLM 的 prompt

程序员看 docstring 是为了理解实现；LLM 看 docstring 是为了**决定要不要调、怎么调**。所以要写清楚：这个工具干什么、参数从哪来、拿到结果后下一步做什么。

```python
"""按作品名搜索动画，返回作品 id 与基本信息。

拿到 anime_id 后用 list_spots 查该作品的圣地。       ← 告诉 LLM 下一步
支持中文名、日文原名、城市名模糊匹配。                ← 告诉 LLM 能传什么
"""
```

"拿到 anime_id 后用 list_spots"这句话看起来多余，但它直接影响 LLM 的调用链规划。没有它，LLM 可能拿着作品名直接去调 `list_spots`，然后失败。

### 2. 类型标注就是参数约束

`anime_id: int` 不只是给 IDE 看的。它生成的 schema 会告诉 LLM "这里要整数"，同时在运行时拦住错误输入。能用 `int` 就别用 `str`，能用 `Literal["a", "b"]` 就别用自由字符串——约束越紧，LLM 越不容易传错。

### 3. 输出要省 token

`search_anime` 只返回作品摘要和 `spots_count`，**不返回地标列表**。如果搜一个关键词命中 3 部作品、每部 80 个地标，一次返回 240 条数据，会直接塞满 LLM 的上下文窗口——而 LLM 这时候可能只是想确认"是哪部作品"。

分层返回：先给摘要，LLM 需要细节时再调下一个工具。

### 4. 字段名要自解释

```python
"lat": 35.7108,          # 而不是 "geo": [35.7108, 139.7967]
"lng": 139.7967,
"name_ja": "浅草寺 雷門",  # 而不是 "name"
"name_cn": "浅草寺 雷门",  # 而不是 "cn"
"episode": 1,            # 而不是 "ep"
"timestamp_sec": 210,    # 而不是 "s"
```

`geo: [a, b]` 哪个是纬度哪个是经度？LLM 和前端都得猜（而且不同系统的约定还真不一样，GeoJSON 就是先经度后纬度）。`s` 是什么？秒？季？LLM 看不懂的字段，它就会瞎用或忽略。

### 5. 错误是数据，不是异常

```python
@mcp.tool()
def get_spot(spot_id: str) -> dict:
    spot = repo.get_spot(spot_id)
    if spot is None:
        return {"error": f"未找到圣地 {spot_id}"}   # 而不是 raise
    return spot
```

实测对比了三种错误在 stdio 传输下的表现：

| 情况 | client 收到的 `is_error` | LLM 看到的信息 |
|---|---|---|
| 工具里 `raise ValueError("bad x=1")` | `True` | `Error executing tool boom` —— **真实原因被隐藏了** |
| 参数类型不对 | `True` | 完整的 pydantic 校验错误，LLM 能据此修正 |
| 主动 `return {"error": "..."}` | `False` | 你写的错误信息，完全可控 |

第一行是关键：**未捕获的异常，其消息不会传给 client**（这是 SDK 的安全设计，防止泄露服务端内部信息）。LLM 只知道"出错了"，不知道为什么，也就没法调整。主动返回错误信息，LLM 才能决定"换个 id 重试"还是"告诉用户没找到"。

另一个发现对 Day 2 很重要：**跨进程时，工具出错 client 端不会抛异常**，而是拿到 `is_error=True` 的正常结果。所以 mcp_client 不能靠 `try/except` 判断工具是否失败，必须检查 `is_error`。

### 6. 工具粒度：宁可多一步，不要一个大工具

也可以只做一个 `find_spots_by_title(title)` 一步到位。拆成 search → list → get 三步的理由：

- 搜索可能命中多部作品（搜"莉可丽丝"会命中正片、新作、剧场版），需要 LLM 或用户确认是哪一部
- 用户可能只是问"有哪些作品在宇治取景"，根本不需要地标详情
- 每个工具职责单一，描述写得清楚，LLM 更容易选对

代价是多了 LLM 调用轮次（更慢、更费 token）。这个取舍在评测阶段可以用数据验证。

## 案例：先探测，再写代码

计划里 Day 1 上午的任务是"验证 Anitabi API"。这个验证过程本身值得单独讲，因为它**避免了一个 Day 3 才会暴露的致命问题**。

### 方法

1. **读文档**，列出要用的端点
2. **写探测脚本打真实请求**，不要只信文档
3. **统计字段出现率，而不是看一条样本**：

   ```python
   from collections import Counter
   c = Counter(key for point in points for key in point)
   # {'id': '84/84', 'name': '84/84', 'image': '83/84', 'ep': '80/84', ...}
   ```

   只看第一条样本，你会漏掉"大部分数据缺某个字段"这种问题
4. **换几个样本交叉验证**：一部作品有问题可能是个例，两部都有问题就是系统性的
5. **注意限流**：探测时别一口气发几十个请求

### 发现

文档里每个地标都有 `geo` 坐标。实测：

- 两部作品的地标，`geo` 字段出现率 **0/84、0/63**——线上 API 已经不返回了
- 部分坐标能从 `originURL` 里救回（Google Maps 链接带 `ll=纬度,经度` 参数），但只覆盖 **42%**
- 约 25 个请求后被 Cloudflare 403，45 秒后仍未恢复
- Anitabi **没有按标题搜索的端点**；用 Bangumi 官方的 `POST api.bgm.tv/v0/search/subjects` 可以补上

**如果照着文档直接写代码**：Day 1 的 MCP server 能跑，Day 2 的 agent 能跑，到 Day 3 做地图打点时才发现——没有坐标。那时候已经没有时间调整方案了。

完整实测数据见 [项目计划 4.1 节](00-project-plan.md#41-圣地巡礼-mcp-server自建)。

### mock 数据的设计

[mock_spots.json](../backend/mcp_servers/seichi/data/mock_spots.json)：5 部作品、22 个地标，坐标零缺失。

设计要点是**格式对齐上游**：结构和 Anitabi 的响应完全一致，唯一的差异是给每个地标补上了 `geo`。这样**差异本身就是待办清单**——将来接真实 API 时，`AnitabiRepository` 要额外解决的事情就是"坐标补全"，一目了然。

`_meta` 字段诚实地标注了数据的局限：哪些 id 是真实验证过的、坐标只是近似值、不能用于实际导航。mock 数据最怕的是被当成真数据用。

## 设计取舍

**mock 数据 vs 实时 API**

mock 的缺点显而易见：数据少、不能真实反映 Anitabi 的全部作品。但对这个 demo，它反而更合适：演示时零网络依赖、零限流风险、毫秒级响应。demo 的技术展示点是 agent loop 和 MCP，不是数据完整性。天气和路线两个 MCP 仍然会实时调外部 API，"调用真实服务"这个能力照样能展示。

**`lru_cache` vs 每次读文件**

每次调用都读 JSON 最简单，改数据立即生效；但每次工具调用都有一次磁盘 IO。用 `lru_cache` 只读一次。对只读的小数据集，缓存是对的；如果数据会在运行时更新，就不能这么做。

## 动手验证

```powershell
# 1. 跑 seichi 的全部测试（含一个真实 stdio 子进程往返）
python -m pytest -v -k seichi

# 2. 手动启动 server —— 它会"卡住"不动，这是正常的：
#    它在等 stdin 上的 JSON-RPC 消息。Ctrl+C 退出
python -m backend.mcp_servers.seichi.server

# 3. 进程内直接调工具函数看看返回格式
python -c "from backend.mcp_servers.seichi import server; import json; print(json.dumps(server.list_spots(364450)[0], ensure_ascii=False, indent=2))"
```

重点读一下 [test_seichi.py](../backend/tests/test_seichi.py) 里的 `test_stdio_roundtrip_as_subprocess`——它把 server 拉成子进程、走完整的 `initialize` → `call_tool` 协议流程。**这就是 Day 2 的 `mcp_client.py` 要做的事情的最小原型。**

图形化调试工具 MCP Inspector 需要 Node.js，装好之后可以用（未实测）：

```powershell
npx @modelcontextprotocol/inspector python -m backend.mcp_servers.seichi.server
```

## 延伸思考

1. 原则 5 说"错误是数据"。但 `get_spot` 返回 `{"error": ...}` 时 `is_error=False`——从协议层面看，这次调用是"成功"的。这会不会让 client 端（比如将来的评测脚本）难以统计工具失败率？有什么办法两全？
2. `search_anime` 目前是简单的子串匹配。用户说"那个京都吹小号的动画"，能搜到吗？如果搜不到，应该改进工具，还是依赖 LLM 自己把用户的话改写成作品名？
3. 如果将来接入 Anitabi 的 580 个地标，`list_spots` 一次全返回会有什么问题？原则 3 在这里该怎么应用？（提示：想想"这周末去巡礼"和"列出所有圣地"这两种需求的区别）
4. MCP server 是独立进程。如果它崩了，agent 这边会发生什么？谁负责重启它？
