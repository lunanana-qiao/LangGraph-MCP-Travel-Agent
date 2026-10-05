# Travel Agent 架构与设计说明

> 智能旅行规划 Agent —— 基于 LangGraph + MCP + RAG 的多阶段行程编排系统

---

## 1. 项目概述

Travel Agent 是一个面向自然语言交互的智能旅行规划系统。用户用一句话描述出行需求(出发地、目的地、日期、人数、预算、偏好),系统通过多阶段 Agent Workflow 输出可执行的逐日行程,包括交通方案、景点排布、餐饮推荐、住宿安排与预算核算。

**核心能力**

- **意图理解与约束抽取**:从自由文本中识别 5 类意图(规划 / 偏好更新 / 记忆查询 / 信息查询 / 未知),并解析硬约束(地点、日期、人数、预算)与软约束(酒店品牌、航司、座位偏好)。
- **多源数据并行获取**:交通(12306 火车 + 途牛机票)、地图 POI(高德)、知识库 RAG(经验 + 避坑)三路并发。
- **行程智能编排**:基于地理聚类 + TSP 路线优化进行逐日 POI 分配,自动计算游玩时长与移动耗时。
- **预算自适应**:住宿三档(高/中/低)备选,当总价超过 70% 预算上限时自动降档重排。
- **长期记忆**:跨会话保存用户偏好(常住地、偏好品牌、航司)、历史行程,自动注入到下一次会话的系统提示词中。

---

## 2. 技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| 编排框架 | **LangGraph** | StateGraph + Checkpointer,支持并行 fan-out / 条件路由 / 重试循环 |
| LLM | **豆包 (ByteDance Doubao)** | 火山引擎 API,温度 0.7,max_tokens 8192 |
| 工具协议 | **MCP (Model Context Protocol)** | 接入高德地图、途牛 CLI、12306 |
| 向量检索 | **ChromaDB + bge-small-zh-v1.5** | 本地嵌入模型,旅游攻略知识库 |
| 持久化 | **AsyncSqliteSaver** | LangGraph checkpointer,SQLite 后端 (data/aligo.sqlite) |
| Web 后端 | **FastAPI + SSE** | 流式响应,会话级缓存 |
| 前端 | **Vite + React** | 开发端口 5173 |
| CLI | **Rich** | 终端交互式界面 |

## 3. 目录结构
travelAgent/
├── graph/ # LangGraph 工作流核心
│ ├── state.py # TravelGraphState 定义(分层状态)
│ ├── workflow.py # build_graph() 节点装配与边路由
│ └── nodes/ # 各阶段节点实现
├── agents/ # 领域智能体
│ ├── transport_agent.py # 交通方案(火车/飞机/天气)
│ ├── poi_agent.py # 高德 POI 检索
│ ├── accommodation_agent.py # 住宿三档备选
│ └── lazy_agent_registry.py # 懒加载注册表
├── mcp_clients/ # MCP 客户端封装
│ ├── amap_client.py # 高德地图(SSE)
│ ├── tuniu_client.py # 途牛 CLI(机票/酒店/门票)
│ └── train_client.py # 12306(STDIO)
├── context/ # 记忆系统
│ ├── memory_manager.py # 长短期记忆统一入口
│ └── long_term_memory.py # 偏好/历史/统计 JSON 持久化
├── .claude/skills/ # 可调度 Skills
│ ├── rag-experience/ # 旅游经验抽取
│ ├── rag-risk/ # 避坑要点抽取
│ ├── ask-question/ # 通用 QA(ChromaDB 向量检索)
│ ├── query-info/ # 天气/网络搜索
│ ├── memory-query/ # 跨会话记忆查询
│ ├── preference/ # 偏好更新
│ ├── accommodation-query/ # 住宿查询
│ └── tuniu-cli/ # 途牛多产品统一入口
├── utils/ # 工具模块
│ ├── date_resolver.py # 相对日期归一化("明天" → ISO 8601)
│ ├── poi_category.py # 高德 typecode 景点过滤
│ ├── tuniu_budget.py # 途牛 API 配额(RPM/RPD)
│ └── skill_loader.py # Skill SKILL.md frontmatter 解析
├── app/ # FastAPI Web 后端
│ ├── main.py # 入口、checkpointer、CORS
│ └── routes/ # sessions / sse_chat
├── frontend/ # Vite + React 前端
├── data/ # 持久化数据
│ ├── aligo.sqlite # LangGraph checkpointer
│ ├── memory/{user_id}.json # 长期记忆
│ └── models/bge-small-zh-v1.5/ # 本地嵌入模型
├── cli.py # 终端交互入口(Rich)
└── config.py # LLM / RAG / MCP / Resilience 集中配置

---

## 4. LangGraph State 分层设计
`TravelGraphState` (`graph/state.py`) 是整个 Workflow 的"单一真相源",采用 **TypedDict + Annotated reducer** 形式,按职责分为 4 层:
### 4.1 约束层(Constraint Layer)
由 P1 阶段抽取与校验,后续节点只读。
| 字段 | 类型 | 说明 |
|------|------|------|
| `hard_constraints` | dict | origin / destination / start_date / end_date / pax / budget |
| `soft_constraints` | dict | 酒店品牌偏好、航司偏好、座位等级、特殊需求 |
| `rule_violations` | list | 校验失败项,分 `critical` / `warning` 两级 |
| `accommodation_prefs` | dict | 单独抽出的住宿偏好(品牌、星级、价位) |

### 4.2 规划层(Planning Layer)
P2~P4 阶段持续填充,是行程生成的中间产物。
| 字段 | 类型 | 说明 |
|------|------|------|
| `transport_options` | list | 去程候选(火车 + 飞机,各 Top3) |
| `transport_return_options` | list | 返程候选 |
| `poi_candidates` | list | 高德返回的 POI 池 |
| `daily_itinerary` | list[Day] | 逐日 POI 分配结果 |
| `daily_routes` | list | TSP 优化后的逐日路线 |
| `daily_restaurants` | dict | 每日餐厅推荐(围绕 POI 中心) |
| `daily_options_by_tier` | dict | 三档(高/中/低)住宿备选 |
| `accommodation_downgrade_level` | int | 当前降档次数(0/1/2) |

### 4.3 RAG 与富化层(Enrichment Layer)
| 字段 | 类型 | 说明 |
|------|------|------|
| `rag_context` | RAGContext | 容器对象:snippets / experience / risks |
| `llm_seed_pois` | list[str] | LLM 从 RAG + 知识库提取的具体 POI 名 |
| `attraction_hints` | list | 景点搜索关键词提示 |
| `poi_descriptions` | dict | POI 介绍文本(Wikipedia / 高德) |
| `poi_photos` | dict | POI 配图 URL |

### 4.4 编排层(Orchestration Layer)
驱动节点间流转与最终输出。
| 字段 | 类型 | Reducer | 说明 |
|------|------|---------|------|
| `messages` | list | `add_messages` | LangGraph 标准消息列表,由 checkpointer 持久化 |
| `intent_type` | enum | 覆盖写 | planning / preference_only / memory_only / info_only / unknown |
| `intent_data` | dict | 覆盖写 | 意图槽位(实体、动作) |
| `skill_results` | dict | `skill_results_reducer` | 各 skill 输出,支持 `SKILL_RESULTS_RESET` 哨兵清空 |
| `final_response` | str | 覆盖写 | 渲染给用户的最终回复 |
| `travel_style` | str | 覆盖写 | 旅行风格(亲子 / 商务 / 深度 / 打卡) |
| `daily_budget_per_person` | float | 覆盖写 | 人均日预算,预算检查依据 |
| `budget_fit_message` | str | 覆盖写 | 预算超标时的提示文案 |

**Reducer 设计要点**
- `messages` 使用 LangGraph 内置 `add_messages`,保证多节点并发追加不丢失。
- `skill_results` 自定义 reducer:默认合并(浅拷贝 update),遇到 `SKILL_RESULTS_RESET` 值则清空 —— 用于在新一轮 retry 前重置上轮结果。
- 其他字段无 reducer 即"覆盖写"语义,后写者赢。

## 5. 工作流节点 Pipeline

`graph/workflow.py::build_graph()` 按 5+1 阶段装配节点。整体形态:**线性骨架 + P2 并行 fan-out + P3.5 重试回环 + P4 预算自检分支**。

### 5.1 P1 —— 意图与约束抽取

| 节点 | 职责 |
|------|------|
| `intent_node` | **W 镜像模式**:LLM 同时输出 intent_type + key_entities + accommodation_prefs;同步将提到的酒店品牌写入长期记忆 |
| `extract_constraints_node` | NLU 抽取 origin / destination / dates / pax / budget,缺失字段标记为 None |
| `validate_constraints_node` | 规则校验:日期合法性、时空冲突、预算合理性,产出 `rule_violations` |
| `negotiate_node` | 当存在阻塞型 critical 错误时,生成追问话术请求补充信息 |

### 5.2 P1.5 意图分流(`route_after_validation`)
planning → fan-out [rag, transport_outbound, transport_return]
preference_only → preference_node
memory_only → memory_query_node
info_only → info_query_node
unknown → respond_node

### 5.3 P2 —— 并行数据获取
三路并行,在 P3 入口汇合:
- **`rag_node`** —— 并发调用 `rag-experience` + `rag-risk` 两个 skill,聚合为 `RAGContext`(snippets / experience / risks)。
- **`transport_outbound_node` / `transport_return_node`** —— 通过 TransportAgent 同步查询火车(12306)、机票(途牛)、目的地天气(高德);按价格排序后返回各类型 Top3,并对全局最低价打 `is_recommended=True` 标记。
- **`llm_seed_extract_node`** —— LLM 从 `rag_context.snippets` + 知识库 `must_visit` 中提取具体景点名,写入 `llm_seed_pois`,供 `poi_fetch_node` 使用。
- **`poi_fetch_node`** —— 知识库感知的 POI 检索:
  - **KB 城市**:`must_visit` + `route_combo` + `llm_seed_pois` + `attraction_hints` 多路召回
  - **非 KB 城市**:`llm_seed_pois` + `attraction_hints` + 兜底泛搜
  - 使用 `utils/poi_category.py` 按高德 typecode 过滤纯景点

### 5.4 P3 —— 行程编排
- **`itinerary_planning_node`** —— 核心大节点:
  1. 按经纬度对 POI 聚类(每日不超过半径阈值)
  2. 每日内部 TSP 路线优化(最短总移动距离)
  3. 调用 LLM 的 `PoiTimeInfo` 结构化输出获取每个 POI 的合理游玩时长
  4. 计算逐日预算占用(交通 + 门票)
- **`poi_enrich_node`** —— 并发抓取 POI 描述与图片(Wikipedia 优先,高德兜底)

### 5.5 P3.5 —— 行程审查与重试(`route_after_review`)
itinerary_review_node 检测 rule_violations:
critical 且 retry_count < 2 → 回到 itinerary_planning_node (重试,重置 skill_results)
否则 → 进入 P3.6 restaurant_node
重试上限由 `REVIEW_MAX_RETRIES = 2` 控制,避免死循环。

### 5.6 P3.6 / P4 —— 餐饮、住宿与预算
- **`restaurant_node`** —— 计算每日 POI 的几何中心,以中心为锚点用高德搜索附近餐厅,每天 5 家。**有意放在重试循环之外**,避免每次 retry 重复消耗高德配额(见记忆条目 `project_restaurant_timing.md`)。
- **`accommodation_node`** —— AccommodationAgent 计算每日地理中心,查询附近酒店,生成 3 档(高/中/低)备选;查不到时按 `centers → arrival_hub → destination` 三级降级搜索范围。
- **`budget_check_node`** + **`route_after_budget_check`**:
  - 计算 `(住宿 + 交通) / 总预算`
  - **超过 70%**:`accommodation_downgrade_level += 1`,回到 `accommodation_node` 选更低档
  - **达到最低档仍超**:写入 `budget_fit_message` 提示用户,放行
  - **通过**:进入 P5

### 5.7 P5 —— 响应渲染
`respond_node`:
- 组装 `chat_summary`:headline / timeline / budget / tips(来自 RAG experience) / risks(来自 RAG risk)
- 调用 `long_term.add_trip_history()` 保存本次行程
- 渲染最终 `final_response`(CLI 渲染 markdown,Web 推送 SSE chunk)

### 5.8 整体流转示意
HumanMessage
│
▼
[intent] → [extract_constraints] → [validate_constraints]
│              │
│           (缺信息)                    │ (有 critical)
▼                                      ▼
[negotiate] ◀───────────────── route_after_validation
│ (planning)
┌────────────────────────────┼────────────────────────────┐
▼                            ▼                             ▼
[rag]                [transport_outbound]           [transport_return]
│                            │                             │
└────────────► [llm_seed_extract] → [poi_fetch] ◀─────────┘
│
▼
[itinerary_planning] ──► [poi_enrich]
│
▼
[itinerary_review] ──┐ critical & retry<2
│ ok │
▼ └──► back to planning
[restaurant]
│
▼
[accommodation] ◀──┐ over budget
│                   │
▼                   │
[budget_check] ─────┘
│ pass
▼
[respond] ──► END

## 6. 领域 Agent 设计
`agents/` 下的智能体不直接出现在 LangGraph 节点拓扑里,而是由节点按需调用 —— 节点负责状态管理,Agent 负责具体业务逻辑。这种分离让 Agent 可独立测试,也避免节点函数过度膨胀。

### 6.1 TransportAgent (`agents/transport_agent.py`)
**纯规则型,不调用 LLM**。
- 并发调度三路查询:12306 火车票、途牛机票、高德目的地天气
- 各结果按价格升序排序,分别取 Top3
- 在全局最低价(跨火车/飞机)上打 `is_recommended=True`
- 失败容错:任一路超时或异常时返回空列表,不阻断其他两路
**为什么不用 LLM**:交通方案是强结构化数据(出发到达时间、价格、舱位),LLM 加入只会引入幻觉与延迟,不如直接走 MCP + 规则排序。

### 6.2 POIFetchAgent (`agents/poi_agent.py`)
**知识库感知的多路召回**,根据目的地是否在 CityKnowledgeDB 中走不同分支:
| 输入信号 | 策略 |
|---------|------|
| `must_visit` (KB) | 必去景点,直接精确搜索 |
| `route_combo` (KB) | 推荐组合路线节点 |
| `llm_seed_pois` | LLM 从 RAG 抽取的具体名称 |
| `attraction_hints` | 关键词提示(如"古镇"、"博物馆") |
| 兜底 | 高德泛搜 `<destination> 景点` |
所有结果统一过 `utils/poi_category.py::is_attraction()` 过滤,排除餐饮、购物等非景点类目。

### 6.3 AccommodationAgent (`agents/accommodation_agent.py`)
**三档备选 + 地理降级**。
- 输入:每日 POI 几何中心、用户软约束(品牌/星级/价位)、`accommodation_downgrade_level`
- 输出:每日 `daily_options_by_tier = {high, mid, low}` 三档酒店
- 地理降级:`daily_centers → arrival_hub → destination_center`,确保偏远 POI 日也能匹配到酒店
- 与 `budget_check_node` 联动:当总预算超 70% 时,通过递增 `downgrade_level` 重新选档

### 6.4 LazyAgentRegistry (`agents/lazy_agent_registry.py`)
懒加载注册表,首次访问时实例化并缓存。规避启动期初始化所有 Agent(及其 MCP 连接)的开销,提升冷启动速度。

---

## 7. MCP 集成
所有外部数据源通过 MCP 协议接入,客户端封装在 `mcp_clients/`,统一暴露 `async def call(tool, **kwargs)` 接口。

### 7.1 高德地图 (`mcp_clients/amap_client.py`)
| 项 | 值 |
|----|----|
| 传输 | **SSE** (`https://mcp.amap.com/sse`) |
| API Key | 配置于 `config.py::AMAP_MCP_CONFIG` |
| 超时 | 30s |
| 核心工具 | `poi.search` / `poi.detail` / `geocode` / `regeo` / `maps_weather` |

**使用位置**:
- `poi_fetch_node` —— 景点搜索
- `accommodation_node` —— 周边酒店搜索
- `restaurant_node` —— POI 中心附近餐厅搜索
- `transport_node` —— 目的地天气查询

### 7.2 途牛 CLI (`mcp_clients/tuniu_client.py`)
| 项 | 值 |
|----|----|
| 传输 | **STDIO**(子进程方式启动 CLI) |
| API Key | `.env` 中 `TUNIU_API_KEY` |
| 配额 | RPM=5, RPD=50(`utils/tuniu_budget.py` 跟踪) |
| 缓存 | 按工具分别配置 TTL:酒店搜索 600s,机票 180s |
| 核心工具 | `searchLowestPriceFlight` / `hotel_search` / 火车票 / 门票 / 邮轮 / 度假产品 |
**配额超限处理**:抛 `TuniuBudgetExceeded` 异常,被 TransportAgent 捕获后该路返回空,不影响其他数据源。

### 7.3 12306 火车票 (`mcp_clients/train_client.py`)
| 项 | 值 |
|----|----|
| 传输 | **STDIO** |
| 工具 | `query_ticket_price`(返回二等座价格) |
| 集成方 | TransportAgent 并行调用 |

### 7.4 MCP 调用统一模式
```python
# 伪代码:节点中的 MCP 调用骨架
async with circuit_breaker.guard("amap"):
    try:
        result = await amap_client.call("poi.search", keywords=..., city=...)
    except (TimeoutError, MCPError) as e:
        logger.warning(f"Amap 调用失败: {e}")
        return []  # 兜底空结果,不阻断 workflow
关键设计:
熔断器(config.py::RESILIENCE_CONFIG):5 次失败后熔断,60s 后自动恢复
重试:最多 3 次,指数退避
优雅降级:MCP 失败时该路返回空,由上层节点决定是否阻塞流程

## 8. 记忆系统

Travel Agent 的记忆分为**短期会话上下文**与**长期跨会话记忆**两层,职责严格分离 —— 这是 2026-05-12 短期记忆统一改造后的最终形态。

### 8.1 短期会话上下文 —— Checkpointer 单一真相源

- **载体**:LangGraph 'MemorySaver' (CLI) / 'AsyncSqliteSaver' (Web)
- **键**:'thread_id'(等同 'session_id')
- **内容**:'state["messages"]' —— 所有 HumanMessage / AIMessage / ToolMessage / SystemMessage
- **生命周期**:进程内驻留(CLI) / SQLite 持久化(Web,'data/aligo.sqlite')

> **设计决策**:历史上曾存在 'ShortTermMemory' 类与 'state["messages"]' 双写,存在数据漂移风险。改造后**短期上下文以 checkpointer 为唯一来源**,'MemoryManager' 不再持有 'short_term'。CLI 的 'show_status' 通过 `graph.get_state(config).values["messages"]` 读取消息;`clear` 命令通过重置 `session_id` / `thread_id 实现"清空会话"(旧上下文仍在 checkpointer,但新轮看不到)。

### 8.2 长期记忆 —— LongTermMemory

context/long_term_memory.py,JSON 持久化在 data/memory/{user_id}.json。

| 字段 | 结构 | 说明 |
|------|------|------|
| preferences | list[{type, value}] | 偏好条目,type 如 hotel_brand / airline / seat_class / home_location |
| trip_history | list[Trip] | 历史行程摘要(目的地、日期、参与人数、预算) |
| chat_history | list[Message] | 跨会话聊天摘要(可选) |
| statistics | dict | 高频目的地、平均预算等聚合统计 |

**核心方法**:
- save_preference(type, value) / add_hotel_brand(brand) / add_airline(airline)
- get_trip_history(limit=10) / get_frequent_destinations()
- 数据迁移:自动检测旧 dict 格式 → 新 list 格式,修复历史嵌套 bug

### 8.3 MemoryManager 入口

context/memory_manager.py 是上层统一门面:

- long_term —— 暴露 LongTermMemory 全部能力
- add_message(message) —— **仅写 long_term**(短期由 checkpointer 接管,此方法已不再调用 short_term)
- summarize_for_prompt() —— 把长期偏好 + 历史行程序列化为 SystemMessage,供 P1 intent_node 注入

### 8.4 W 镜像模式 —— 长期记忆的自动回写

intent_node 采用"W 镜像"设计:在做意图识别的同一次 LLM 调用中,**顺手**抽取用户消息里隐含的偏好(如"我们家一般住汉庭")并立即写入 long_term。这样用户无需显式说"记住我喜欢汉庭",偏好就在自然对话中沉淀。
User: "下次去成都还想住汉庭"
│
▼
intent_node (LLM)
├─ intent_type = "planning"
├─ key_entities = {destination: "成都", ...}
└─ accommodation_prefs.hotel_brand = ["汉庭"] ─► long_term.add_hotel_brand("汉庭")

---
## 9. RAG 知识库
### 9.1 双层知识源
| 层 | 载体 | 内容 | 检索方式 |
|----|------|------|----------|
| **结构化知识库** | CityKnowledgeDB (utils/knowledge_parser.py) | 城市的 must_visit / route_combo / best_season / transport_hubs | 直接按城市名 key 查 |
| **非结构化文档库** | ChromaDB 向量库 | 旅游攻略原文片段 | 语义检索 (bge-small-zh-v1.5) |
向量库文档存放在 .claude/skills/ask-question/data/documents/,启动时构建索引,使用本地嵌入模型 data/models/bge-small-zh-v1.5/ 避免外部 API 依赖。
### 9.2 RAG 节点的双 Skill 并发
rag_node 同时调度两个 skill,语义互补:
| Skill | 抽取目标 | 输出结构 |
|-------|---------|---------|
| rag-experience | 可操作的旅游建议、风格适配理由 | [{tip, applies_to_style, source}] |
| rag-risk | 避坑要点(场景 + 后果 + 建议三要素) | [{scenario, consequence, mitigation}] |
两路结果聚合进 RAGContext:
'''
python
RAGContext(
    rag_snippets   = [...],   # 原始片段(供 llm_seed_extract 使用)
    rag_experience = [...],   # 结构化经验
    rag_risks      = [...],   # 结构化风险
)
'''
9.3 RAG 在 Workflow 中的三处复用
llm_seed_extract_node —— 读取 rag_snippets + KB 提取具体 POI 名,反哺 poi_fetch_node,显著提升非 KB 城市的景点召回质量。
itinerary_planning_node —— 读取 rag_experience 调整旅行风格匹配(亲子日避免登山 POI 等)。
respond_node —— 把 rag_experience 渲染为"旅行小贴士",rag_risks 渲染为"避坑提示",作为最终回复的独立区块。
9.4 Skill 与 Workflow 的协作分工
.claude/skills/ 下的 skill 不是 LangGraph 节点,而是节点内调用的能力单元。设计上区分两类调用方式:

节点内显式调用:rag_node、memory_query_node、info_query_node 等 —— Skill 输出写入 state["skill_results"][skill_name],统一由 respond_node 消费。
CLI 用户直接 /skill-name 触发:绕过 graph,用于查询场景(如 /memory-query 我去过哪些地方)。