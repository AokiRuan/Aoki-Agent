# Aoki-Agent 项目计划

> 最后更新：2026-09-18

## 一、项目定位

做一个**日本动画圣地巡礼 agent** 的完整前后端。用户说「我想去《你的名字》的取景地」，agent 查圣地、看天气、规划路线、给出行程建议——所有能力通过 MCP 工具接入，agent loop 与 harness 自建。

**目标：5 天 vibe coding 出可用 demo（评测除外），部署到 AWS 可公网访问。**

这是一个学习驱动的项目，但学习方式从「继承改写现成框架」切换为「在真实场景下自建 loop 与 harness」。技术栈刻意覆盖一条完整的工程链路：MCP → agent → API → 前端 → 可观测 → 容器 → 云 → CI/CD。

## 二、Demo 核心场景

范围控制的锚点。Demo 只需要把这三个场景跑顺：

1. **查圣地** — 「《リコリス・リコイル》的圣地在哪？」→ 列出取景地，地图上打点
2. **查天气** — 「这周末去镰仓巡礼，天气怎么样？」→ 结合圣地位置查天气预报
3. **规划路线** — 「帮我安排一天走完这几个点」→ 按地理位置排序、估算移动时间、给出行程

三个场景分别对应三类 MCP 工具，也分别验证 agent 的单工具调用、多工具组合、多轮推理能力。

## 三、技术架构

```
┌──────────────────────────────┐
│   React (Vite + TS)          │  聊天面板 + 地图面板 (Leaflet)
└──────────────┬───────────────┘
               │ SSE
┌──────────────▼───────────────┐
│   FastAPI                    │  /chat 流式端点 · 会话管理 ──▶ Postgres
├──────────────────────────────┤
│   Agent Loop + Harness (自建) │  ← 本项目核心
│   · LLM 调用 / tool_calls 解析 │
│   · 迭代上限 / 错误恢复        │
│   · 上下文管理 / 流式事件      │
├──────────────────────────────┤
│   MCP Client                 │  工具发现 → schema → 调用分发
└───┬──────────┬──────────┬────┘
    ▼          ▼          ▼
 圣地巡礼     天气        路线/地图
 MCP Server  MCP        MCP
 (自建)      (外部)     (外部)
    │
    ▼
 Langfuse ──── 全链路 trace
```

部署形态：**单容器 + 外部数据库**（FastAPI 托管 React 静态文件，自建 MCP server 作为 stdio 子进程；Postgres 在容器外），ECR → App Runner，GitHub Actions 驱动。

## 四、模块拆解

### 4.1 圣地巡礼 MCP Server（自建）

- **职责**：把圣地巡礼数据封装成 MCP 工具，供 agent 调用
- **工具设计**：
  - `search_anime(title)` — 按作品名模糊搜索，返回作品 id 与基本信息
  - `list_spots(anime_id)` — 返回该作品的所有圣地（名称、坐标、对应剧集/场景、地址）
  - `get_spot(spot_id)` — 单个圣地详情
- **实现**：MCP SDK 2.x + stdio 传输，用 MCP Inspector 单独验证
- **数据源：已验证，当前用 mock**。`repository.py` 把数据源抽象成 `SeichiRepository` 接口，
  server.py 只依赖接口，将来切回真实 API 只改 `get_repository()` 一处

#### Anitabi API 实测结论（2026-09-28）

能用的：

| 端点 | 结果 |
|---|---|
| `GET api.anitabi.cn/bangumi/{id}/lite` | 200，97ms。作品元信息 + 前 10 地标 + **作品级**地图中心坐标 |
| `GET api.anitabi.cn/bangumi/{id}/points/detail` | 200。全部地标（115908 返回 84 条） |
| `POST api.bgm.tv/v0/search/subjects` | 200。**补上了文档缺口**——Anitabi 没有按标题搜索的端点，用 Bangumi 官方搜索拿 subjectID |

三个坑：

1. **地标级 `geo` 线上已不再返回**。文档示例里有，实测两部作品 **0/84、0/63**，字段全集里没有 `geo`。只剩作品级中心点
2. **坐标只能部分救回**。`originURL` 里 Google Maps 的 `ll=` 参数可提取坐标，但仅覆盖 **35/84 = 42%**；Anitabi 自有来源的 49 个地标 URL 里只有 id 没有坐标
3. **Cloudflare 限流严格**。约 25 个请求后被 403，45 秒后仍未恢复。**演示当天实时调用有翻车风险**

另：`pointsLength` 声称 582 个地标，`points/detail` 实际只返回 84 个。

#### 当前方案：mock 数据

`data/mock_spots.json` 按 Anitabi 格式伪造，5 部作品 22 个地标，坐标零缺失。
与 Anitabi 的唯一结构差异是 `points[].geo` —— 那正是接真实 API 时要额外解决的部分。

接回真实 API 前必须先解决：坐标补全（Nominatim 地理编码或其他途径）、
本地缓存以规避限流、Anitabi 数据遵循 CC BY-NC-SA 4.0 需标注来源并支持跳转（`origin` / `origin_url` 字段已预留）。

### 4.2 外部 MCP 服务

只接两个，不贪多：

- **天气**：Open-Meteo（免费、无需 key、有日本覆盖）。优先找社区现成 MCP server，没有合适的就自己包——包一个 `get_forecast(lat, lng, days)` 一小时的事
- **路线/地图**：Google Maps（需 key + 绑卡）或 OSRM + Nominatim（免费）。Demo 需要的只是「两点间移动时间」和「地址→坐标」，OSRM 就够

### 4.3 Agent Loop + Harness（自建）

不再依赖 `hello_agents`。核心循环：

```
messages → LLM(tools=mcp_schemas) → 有 tool_calls?
   ├─ 是 → 经 MCP client 执行 → 结果追加到 messages → 回到开头
   └─ 否 → 输出最终回答
```

Harness 需要覆盖的点：
- **工具发现**：启动时连接所有 MCP server，拉取工具列表，转成 LLM 的 tool schema
- **迭代上限**：防止死循环，超限时强制让 LLM 总结
- **错误恢复**：工具调用失败不中断，把错误信息作为 tool result 交给 LLM 自行处理
- **流式事件**：loop 内部产出结构化事件流（token / tool_call / tool_result / done），供 SSE 转发
- **上下文管理**：demo 阶段做简单截断即可
- **可观测**：每一轮 LLM 调用和工具调用都打到 Langfuse

`tools/registry.py` 里的 schema 导出思路可以借鉴，但 MCP 协议本身已提供工具 schema，registry 的角色变成「MCP client 的聚合层」。

### 4.4 后端 FastAPI

- `POST /chat` — SSE 流式，事件类型：`token` / `tool_call` / `tool_result` / `done` / `error`；带 `session_id`，不存在则新建
- `GET /sessions` — 会话列表（id、标题、更新时间）
- `GET /sessions/{id}` — 拉取该会话的完整消息，用于刷新页面后恢复
- 托管 React 构建产物，单容器对外
- 启动时拉起 MCP server 子进程并完成工具发现

**会话持久化**：

- Postgres + SQLAlchemy（async），两张表：`sessions`（id / title / created_at / updated_at）、`messages`（id / session_id / role / content / tool_calls / tool_results / created_at）
- `tool_calls` 与 `tool_results` 存 JSON 列，这样重新加载历史时前端能复现工具调用过程，而不只是最终回答
- 会话标题：首条用户消息截断即可，不额外调 LLM 生成
- 建表用 `create_all` 启动时执行，demo 不引入 Alembic
- 先定义 `SessionStore` 接口，Day 2 用内存实现让 loop 跑起来，Day 4 换 Postgres 实现——接口不变，前端与 loop 都不用动

### 4.5 前端 React

- Vite + React + TypeScript
- **双面板**：左侧聊天，右侧地图（Leaflet + OpenStreetMap，免费无 key）
- SSE 消费，**工具调用过程可视化**——用户能看到「正在查询圣地…」「正在获取天气…」，这是 agent demo 的核心观感
- `tool_result` 里的圣地坐标自动打点到地图，路线场景画出连线
- 会话侧栏：列出历史会话，点击切换；刷新页面后从 `GET /sessions/{id}` 恢复，包括工具调用记录与地图打点

### 4.6 可观测性 Langfuse

- 用 Langfuse Cloud 免费版，不自托管
- Python SDK：`@observe()` 装饰 loop 与工具调用，LLM 调用走 `langfuse.openai` drop-in
- Demo 价值：演示时打开 trace 页面，展示 agent 的完整决策链——这是「自建 harness」最直观的证明

### 4.7 Docker

- 多阶段构建：node 阶段 build React → python 阶段 runtime
- 单镜像：FastAPI + 静态文件 + 自建 MCP server（stdio 子进程，无需网络配置）
- `docker-compose.yml` 本地一键起：app + postgres 两个服务，作为部署失败时的兜底演示方式

### 4.8 AWS 部署

- **选型：ECR + App Runner**。理由：从镜像直接跑、自动 HTTPS、零运维、按需计费，demo 成本几美元
- **数据库必须在容器外**：App Runner 的文件系统是临时的，重启/重部署就丢，容器内 SQLite 不可行。用托管 Postgres，只需一个连接串环境变量
- 备选：EC2 + docker compose。更土但出问题时更容易排查，且 Postgres 可以直接跟着 compose 跑
- 环境变量（LLM key、Langfuse key、地图 key、`DATABASE_URL`）走 App Runner 配置，不进镜像

### 4.9 CI/CD GitHub Actions

- **PR 触发**：ruff lint + pytest + 前端 build 检查
- **main 推送**：build 镜像 → push ECR → App Runner 自动拉取新镜像部署
- AWS 凭证走 GitHub OIDC，不存长期 key

### 4.10 Agent 评测（Day 6+，不在 demo 范围）

- **评测集**：20～30 条 query，每条标注期望的工具调用序列与期望命中的圣地
- **指标**：工具选择准确率、圣地召回率、LLM-as-judge 评回答质量
- **工具**：Langfuse Datasets + Experiments，结果与 trace 关联，改 prompt 后可对比回归
- 评测框架搭好后，harness 的每次改动都有量化反馈——这是评测的真正价值

## 五、五天计划

| Day | 主线 | 产出 | 验收 |
|---|---|---|---|
| **1** ✅ | 数据 + 圣地 MCP | ~~验证数据源~~ → Anitabi 不可用，已切 mock；MCP server 三个工具跑通 | ✅ 三个工具可查到《リコリス・リコイル》等 5 部作品共 22 个地标，坐标零缺失 |
| **2** | Agent loop + 后端 | 自建 loop 接三个 MCP；FastAPI SSE 端点；`SessionStore` 接口 + 内存实现；Langfuse 打点 | curl 能流式拿到带工具调用的回答，Langfuse 看到完整 trace |
| **3** | React 前端 | 聊天 + 地图双面板；SSE 消费；工具过程可视化；打点；会话侧栏 | 三个核心场景在浏览器里全部跑通，能切换会话 |
| **4** | Docker + 持久化 + CI | 多阶段 Dockerfile；compose 起 app + postgres；`SessionStore` 换 Postgres 实现；GitHub Actions PR 检查 + 镜像推 ECR | `docker compose up` 一键可用，重启容器会话还在；PR 有绿勾；ECR 有镜像 |
| **5** | AWS 部署 + 缓冲 | App Runner 上线；域名/HTTPS；**留半天修 bug** | 公网 URL 可访问，三个场景可演示 |

**Langfuse 在 Day 2 就接**，不要留到最后——它是 debug agent loop 最好用的工具，早接早受益。

## 六、明确不做

- 用户系统 / 登录 / 鉴权（会话持久化但不区分用户，所有会话全局可见）
- 数据库迁移工具（Alembic），`create_all` 够用
- 多语言 UI（界面中文，agent 回答跟随用户语言）
- 移动端适配（响应式做到手机能看即可）
- 语音
- 自托管 Langfuse
- 评测（Day 6+）

## 七、风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| ~~圣地数据源不可用~~ **已发生** | Anitabi 被 Cloudflare 拦截 + 地标坐标已不返回 | ✅ 已切 mock 数据，`SeichiRepository` 接口隔离，解封后只改一处 |
| AWS 部署踩坑 | Day 5 交不出公网 URL | 本地 compose + 录屏演示兜底；App Runner 不行切 EC2 |
| 社区 MCP server 质量参差 | 天气/路线接不上 | 自己包，Open-Meteo 和 OSRM 都是简单 REST，各一小时 |
| LLM tool calling 不稳定 | agent 乱调工具或不调 | 现用 DeepSeek 支持 function calling；LLM 层保留 provider 抽象，随时可换 |
| 流式 + tool calls 的解析 | loop 实现复杂度被低估 | Day 2 先做非流式版本跑通逻辑，再加流式 |

## 八、待定决策

- **LLM**：继续 DeepSeek 还是换 tool calling 更强的模型——Day 2 跑起来后凭实际表现定
- **路线 API**：Google Maps（质量好、要绑卡）vs OSRM（免费、够用）——倾向 OSRM，demo 不值得绑卡
- **生产 Postgres 托管**：RDS（AWS 原生，但要配 VPC / 安全组，吃掉 Day 5 半天）vs Neon / Supabase 这类托管免费层（拿到连接串就能用）——倾向后者，Day 5 的时间留给部署本身
- **何时切回真实 Anitabi 数据**：需先解决坐标补全（42% 可从 originURL 提取，其余靠地理编码）与限流缓存。
  也可能维持 mock——demo 的技术展示点在 agent loop 与 MCP，不在数据完整性

## 九、目标目录结构

```
Aoki-Agent/
├── backend/
│   ├── app/              FastAPI 入口、路由、SSE
│   ├── agent/            自建 loop、harness、MCP client
│   ├── store/            SessionStore 接口 + 内存 / Postgres 实现
│   └── mcp_servers/
│       └── seichi/       圣地巡礼 MCP server
├── frontend/             React (Vite + TS)
├── evals/                评测（Day 6+）
├── docs/                 学习手册：计划、架构、逐模块讲解、踩坑日志
├── learn/                学习期代码（原 core/ agent/ tools/ tests/）
├── CLAUDE.md             项目约定（含「代码与文档同步」规则）
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/
```

## 十、参考

- MCP Python SDK 2.x（注意：`FastMCP` 已改名 `MCPServer`）
- Langfuse Python SDK 文档
- Open-Meteo API
- OSRM / Nominatim
- Anitabi 开放 API（实测结论见 4.1）
- Bangumi API `api.bgm.tv/v0/search/subjects`
