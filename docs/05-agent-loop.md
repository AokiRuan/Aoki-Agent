# 05 · Agent Loop

## 本章目标

读完能回答：

- LLM 的 tool calling 在消息层面到底是怎么一来一回的？`tool_call_id` 是干什么的？
- agent loop 的核心代码只有几十行，它具体做了哪几件事？
- 为什么 loop 不直接用 openai SDK 返回的对象，而要自己定义 `LLMResponse`？
- system prompt 里为什么要写"今天是几号"？
- 不花一分钱 token，怎么测试一个依赖 LLM 的循环？

## 核心概念

### Tool calling 的消息协议

对话历史是一个消息列表，每条消息有一个 `role`。有工具参与时，会出现四种角色：

```
system     "你是圣地巡礼助手……今天是 2026-10-01（周四）……"
user       "京都和东京明天天气怎么样？"
assistant  content: "我来查一下"                      ← LLM 的第 1 轮回复
           tool_calls: [
             {id: "call_00", name: "get_weather_forecast", arguments: "{\"lat\": 34.99, ...}"},
             {id: "call_01", name: "get_weather_forecast", arguments: "{\"lat\": 35.68, ...}"}
           ]
tool       tool_call_id: "call_00", content: "{\"days\": [...]}"   ← 我们执行工具后追加
tool       tool_call_id: "call_01", content: "{\"days\": [...]}"
assistant  content: "明天京都晴，东京小雨……"            ← LLM 的第 2 轮回复
```

关键点：

- **LLM 不执行任何东西**。它只是在 `tool_calls` 里说"我想调这个工具、参数是这些"。执行是我们的代码做的
- **每个 tool 消息必须用 `tool_call_id` 指明它回答的是哪个调用**。一轮里可能有多个调用，LLM 靠这个 id 把结果和调用对上
- **带 `tool_calls` 的 assistant 消息和它对应的 tool 消息必须成对出现在历史里**。只有 tool 消息、没有对应的调用，多数 LLM 服务会直接报错。这一点在 [06 章的上下文裁剪](06-harness.md#上下文裁剪)里很重要
- **`arguments` 是 JSON 字符串，不是对象**。要自己解析，而 LLM 生成的 JSON 可能是坏的

### 先探测：DeepSeek 的实际行为

照 [03 章的规矩](03-mcp-server.md#案例先探测再写代码)，写代码前先用真实请求探测。发现了四件影响设计的事：

| 发现 | 影响 |
|---|---|
| 同时问两个城市，**一次返回两个 tool_call** | loop 要支持一轮多个工具调用，而且可以并行执行 |
| 返回 tool_calls 时 **`content` 不为空**，还附带一句英文 `"I'll check the weather..."` | loop 要把这段文字也输出；system prompt 要规定语言 |
| `arguments` 是 JSON 字符串 | 要解析，要处理解析失败 |
| openai SDK 装的是 3.6.0 | 核实过，`chat.completions.create(tools=..., stream=...)` 接口和 1.x 一致 |

用户说"明天"，模型自己推出 `days: 2`（今天 + 明天）；每轮调用约 1 秒。

## 代码走读

```
agent/
├── llm.py       LLM 抽象：LLMResponse / ToolCall / ChatModel / LLMClient
├── loop.py      核心循环
├── prompts.py   system prompt
├── harness.py   边界策略（06 章）
└── mcp_client.py 工具层（07 章）
cli.py           命令行入口：组装以上各部分
```

### llm.py：让 loop 不认识 openai SDK

[llm.py](../backend/agent/llm.py) 定义了 loop 需要的全部数据结构：

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict          # 解析后的参数
    raw_arguments: str       # LLM 给的原文
    parse_error: str | None  # 解析失败的原因

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    usage: dict | None

    def to_message(self) -> dict: ...   # 转成可以追加进历史的 assistant 消息
```

loop 只和这两个类打交道，**完全不知道 openai SDK 的存在**。好处：

- **测试时可以换成假 LLM**：假 LLM 只要返回 `LLMResponse` 就行，不用去模拟 openai SDK 那一大堆嵌套对象（见下文「测试」）
- **换 SDK 不用动 loop**：将来换成别家 SDK，只需在 `LLMClient` 里做转换

两个细节：

- **同时保留 `arguments` 和 `raw_arguments`**。执行工具用解析后的 dict；写回历史用原文。如果 LLM 给了坏 JSON，写回历史时用原文，LLM 下一轮才能看到"自己写错了什么"
- **`ChatModel` 用的是 `Protocol` 而不是 `ABC`**。假 LLM 写在测试里，没必要继承任何类，只要有签名一致的 `chat()` 方法就行。这正是 [03 章 ABC 对比表](03-mcp-server.md)里说的 Protocol 适用场景

### loop.py：核心循环

[loop.py](../backend/agent/loop.py) 的 `run()` 去掉注释和事件构造，骨架是这样的：

```python
history = harness.trim(list(messages))      # ① 复制一份，不修改调用方的列表
while True:
    iteration += 1
    final_round = not harness.should_continue(iteration)   # ② 超过上限了吗
    resp = await llm.chat(history, None if final_round else schemas)
    history.append(resp.to_message())

    if resp.content:        yield token 事件
    if not resp.tool_calls: yield done 事件; return     # ③ 没有工具调用 = 最终回答

    for tc in resp.tool_calls: yield tool_call 事件
    outcomes = await asyncio.gather(*(execute(tc) for tc in resp.tool_calls))   # ④ 并行执行
    for tc, outcome in zip(resp.tool_calls, outcomes):
        history.append({"role": "tool", "tool_call_id": tc.id, "content": outcome.text})
        yield tool_result 事件
```

逐点说明：

**① 复制输入**。`list(messages)` 复制一份再操作。调用方传进来的列表可能还要用（比如 CLI 里的会话历史），loop 不应该偷偷修改它。

**② 迭代上限**。超过上限时不再提供工具，逼 LLM 基于已有信息收尾，详见 [06 章](06-harness.md#迭代上限)。

**③ 循环的出口**。LLM 的回复里没有 `tool_calls`，就说明它认为信息够了、给出了最终回答。**什么时候停是 LLM 决定的**，这正是 agent 和普通程序的区别。

**④ 并行执行**。DeepSeek 会一次返回多个 tool_call（实测同时查两个城市的天气），它们互不依赖，用 `asyncio.gather` 并行执行。结果按**调用的原始顺序**追加，不是按完成顺序，保证历史是确定的。

### 本次运行产生的消息怎么交给调用方

loop 不碰数据库，但调用方需要把新产生的消息存进会话。做法是放在最后的 `done` 事件里：

```python
yield AgentEvent(type="done", payload={
    "new_messages": history[start:],   # 本次新增的 assistant / tool 消息
    "iterations": iteration,
    "usage": {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...},
})
```

另一种做法是直接修改调用方传进来的列表。那样更"省事"，但副作用是隐式的：调用方得知道"传进去的列表会被改"。通过事件显式交出去，数据流向一目了然。

### 错误分两类

| 错误 | 处理 |
|---|---|
| 工具失败（超时、参数错、查不到） | 作为 tool 消息交给 LLM，由它决定重试还是如实告诉用户 |
| LLM 本身失败（key 失效、服务挂了） | yield `error` 事件结束。LLM 自己挂了，就没法"把错误交给 LLM 处理"了 |

这回答了 [01 章延伸思考第 2 题](01-architecture.md#延伸思考)。

### prompts.py：system prompt

[prompts.py](../backend/agent/prompts.py) 每次请求都重新生成，里面写了几类内容：

**当前日期**。LLM 不知道今天是几号，它的知识停在训练截止那天。用户问"这周末天气怎么样"，LLM 必须先知道今天是周几才能算出周末是哪两天。实测它能正确推算："今天是 2026-10-01 周四，这周末是 10/3 周六、10/4 周日"。

日期用**日本时间**，而且用固定偏移 `timezone(timedelta(hours=9))`，不用 `zoneinfo.ZoneInfo("Asia/Tokyo")`：后者在 Windows 上需要额外安装 `tzdata` 包，否则报 `ZoneInfoNotFoundError`。日本不实行夏令时，全年 UTC+9，固定偏移完全正确。

**回答语言**。探测时 DeepSeek 用英文说"我来查一下"。第一版写的是"始终使用用户提问所用的语言回答，包括调用工具前的说明文字"，实测仍然有一次用了英文。改成更具体的写法后就好了：

```
调用工具前的说明文字也一样：用户用中文提问，就用中文说「我来查一下」，不要用英文。
```

这是写 prompt 的一个通用经验：**抽象的规则不如具体的例子**。

**工具使用策略**。先 search 再 list、suggest_transit 怎么处理、不要编造圣地等。这些在工具描述里也有，system prompt 里写的是**跨工具的流程**，工具描述里写的是**单个工具的用法**。

**不要写经纬度**。见下文「实测发现」第 2 条。

### cli.py：组装点

[cli.py](../backend/cli.py) 把各部分创建出来、注入 loop：

```python
llm = LLMClient(settings.llm_model, settings.llm_api_key, settings.llm_base_url)
async with MCPClientPool() as tools:
    loop = AgentLoop(llm, tools, Harness(max_iterations=settings.max_iterations))
```

这种"负责创建所有对象并把它们接在一起"的地方，叫**组装点（composition root）**。项目里只有两个组装点：`cli.py` 和将来的 FastAPI lifespan。其他模块都只接收依赖，不自己创建依赖。

CLI 还维护了多轮对话的历史：每次回答结束后，把用户消息和 `new_messages` 追加进历史。**system prompt 不进历史**，因为它每次都重新生成（日期会变）。

## 实测发现

用 CLI 跑通了计划里的三个 demo 场景，外加一次两轮对话。几个值得记录的现象：

**1. 错误交给 LLM 的设计，在真实故障里起作用了**

场景 2 第一次调天气工具时 Open-Meteo 超时（`ConnectTimeout`）。工具返回了错误信息而不是崩溃，LLM 看到后自己说"天气服务暂时连不上，我重试一次"，重试成功。这是 [03 章原则 5](03-mcp-server.md#5-错误是数据不是异常) 设计的场景，这次在没有任何模拟的情况下自然发生了。

**2. LLM 抄错了坐标 → 精确数据走结构化通道**

场景 1 里，LLM 在回答中列出了京都音乐厅的坐标，把纬度 **35**.0504 写成了 **34**.0504。LLM 生成文本时抄写数字并不可靠。

解决办法不是"让 LLM 抄得更准"，而是**让它根本不用抄**：前端地图的打点数据来自 `tool_result` 事件里的结构化数据，这条通道完全不经过 LLM。所以 system prompt 里加了"不要在回答里写经纬度"。

**通用原则：精确的数据（坐标、价格、ID）走结构化通道直接给前端，LLM 只负责自然语言部分。**

**3. 有依赖关系的调用被并行发出**

场景 2 里，LLM 同时发出了 `geocode("鎌倉駅")` 和 `get_weather_forecast(...)`，天气调用用的坐标是它**凭自己的知识猜的**，没等 geocode 的结果。这次猜得很准，没造成问题，但说明 LLM 的"并行"判断不总是对的。

**4. LLM 会用自身知识补充描述，有时不准确**

LLM 说"大吉山展望台是第 8 集久美子与丽奈夜间登山的场景"，这是对的；但说"あじろぎの道是宇治川中的沙洲步道"，其实它是河岸边的步道。system prompt 要求圣地名称、坐标、集数只能来自工具，但管不住描述性内容。这类问题只能靠评测阶段发现。

**5. token 消耗**

每个问题 6600～8000 tokens，其中大部分是**每轮都要重复发送的** system prompt 和 6 个工具的 schema。3 轮调用就要发 3 次。DeepSeek 有前缀缓存（响应里的 `prompt_cache_hit_tokens`），重复部分会便宜很多。

## 测试

[test_loop.py](../backend/tests/test_loop.py) 用一个**按剧本回复的假 LLM** 测试 loop：

```python
class FakeLLM:
    def __init__(self, *script):
        self.script = list(script)       # 预先写好的回复
        self.requests = []               # 记录每次收到了什么

    async def chat(self, messages, tools=None):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": tools})
        return self.script.pop(0)

llm = FakeLLM(
    with_tools(call("c1", title="莉可丽丝")),   # 第 1 轮：调工具
    answer("找到了"),                          # 第 2 轮：给出回答
)
```

这样做的好处：

- **不花 token、不受网络影响、结果确定**。真实 LLM 每次回答都可能不同，没法写断言
- **能制造难以触发的情况**：LLM 无限调工具、给出坏 JSON、LLM 服务报错、完全相同的调用重复三次……用真 LLM 很难稳定复现
- **能检查 LLM 收到了什么**：`requests` 记录了每次请求，可以断言"第二次请求的历史里有对应 id 的 tool 消息"

这一切之所以可能，是因为 loop 通过构造参数接收 LLM，而不是自己创建（[01 章原则一](01-architecture.md#原则一agent-loop-在最中心对外界一无所知)）。

一个有意思的测试是 `test_parallel_tool_calls_run_concurrently`：两个工具调用都等待一个"两个都已开始"的信号。如果是串行执行，第一个调用会一直等不到第二个开始，最终超时失败。用这种方式**证明**了它们确实是并行的。

[test_llm.py](../backend/tests/test_llm.py) 用 04 章同样的 `httpx.MockTransport` 手法测试 `LLMClient` 对响应的解析：`AsyncOpenAI` 接受一个 `http_client` 参数，传入走 MockTransport 的 httpx 客户端即可。

## 设计取舍

**为什么先做非流式？**

流式模式下，`tool_calls` 是分成很多片段陆续到达的，要按 index 把碎片拼起来，逻辑复杂很多。先用非流式把"调工具 → 回填 → 再问"的主逻辑跑通、测透，再加流式，出了问题容易定位。现在的 `token` 事件是一次输出整段文字，改成流式后会变成逐字输出，**事件类型不变，前端不用改**。

**tool_calls 附带的 content 要不要输出？**

DeepSeek 调工具时往往附带一句"我来查一下"。可以丢掉，只输出最终回答。选择输出，是因为它让用户知道 agent 在做什么，在等待工具结果的几秒里不至于面对一片空白。

**收尾指令为什么不存进历史？**

超过迭代上限时追加的"请直接回答"指令，只在那一次请求里发给 LLM，不进 `history`。它不是用户说的话，如果存进会话，下次加载历史时它会被当成用户消息显示出来。

## 动手验证

```powershell
# 1. 单次提问（需要 .env 里配好 LLM_API_KEY，会消耗少量 token）
python -m backend.cli "吹响吧！上低音号的圣地在哪？"

# 2. 交互模式，多轮对话，输入 exit 退出
python -m backend.cli

# 3. loop 与 LLM 客户端的测试（不花 token）
python -m pytest -v backend/tests/test_loop.py backend/tests/test_llm.py
```

## 延伸思考

1. 实测发现 3 里，LLM 并行发出了有依赖关系的两个调用。要不要在 system prompt 里禁止？如果禁止，查京都和东京的天气这种真正可以并行的情况会不会变慢？
2. `new_messages` 里包含了工具返回的完整 JSON（比如 `list_spots` 的全部 6 个地标）。多轮对话之后历史会越来越大，06 章的裁剪是按**消息条数**裁的。按条数裁剪有什么问题？
3. 现在每轮都把 6 个工具的 schema 全部发给 LLM。如果将来有 50 个工具呢？
4. 实测发现 4 说"只能靠评测发现"。你能想到一种自动检测"LLM 描述了工具结果里没有的信息"的方法吗？
