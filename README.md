# Travel Agent · 智能旅行规划智能体

> 基于 LangGraph + MCP + RAG 的多阶段行程编排系统，面向自然语言交互，一键生成含交通、景点、餐饮、住宿与预算的逐日旅行方案。

用户用一句话描述出行需求（出发地 / 目的地 / 日期 / 人数 / 预算 / 偏好），系统通过多阶段 Agent Workflow 输出可执行的逐日行程，并具备长期记忆与预算自适应能力。

---

## 核心能力

- **意图理解与约束抽取**：识别 5 类意图（规划 / 偏好更新 / 记忆查询 / 信息查询 / 未知），解析硬约束（地点、日期、人数、预算）与软约束（酒店品牌、航司、座位偏好）。
- **多源数据并行获取**：交通（12306 火车 + 途牛机票）、地图 POI（高德）、知识库 RAG 三路并发。
- **行程智能编排**：地理聚类 + TSP 路线优化逐日分配 POI，自动计算游玩时长与移动耗时。
- **预算自适应**：住宿高 / 中 / 低三档备选，总价超预算 70% 时自动降档重排。
- **长期记忆**：跨会话沉淀用户偏好与历史行程，自动注入下一次会话。

## 技术栈

| 层级 | 选型 |
| --- | --- |
| 编排框架 | LangGraph（StateGraph + Checkpointer，并行 fan-out / 条件路由 / 重试循环） |
| LLM | 豆包（火山引擎 API） |
| 工具协议 | MCP：高德地图（SSE）、途牛 CLI（STDIO）、12306（STDIO） |
| 向量检索 | Milvus / ChromaDB + bge-small-zh-v1.5（本地嵌入） |
| 持久化 | AsyncSqliteSaver（SQLite） |
| Web 后端 | FastAPI + SSE 流式响应 |
| 前端 | Vite + React + Ant Design |
| CLI | Rich |

## 架构设计

```
graph/          LangGraph 工作流核心（state.py / workflow.py / nodes/）
agents/         领域智能体（transport / poi / accommodation / rag_base）
mcp_clients/    MCP 客户端封装（高德 / 途牛 / 12306）
context/        记忆系统（checkpointer 短期 + JSON 长期）
app/            FastAPI Web 后端
frontend/       Vite + React 前端
utils/          工具模块（熔断器 / 日期解析 / POI 过滤 / 知识库解析等）
```

## 工作流 Pipeline

```
意图抽取 → 约束抽取 → 约束校验
   ↓（planning 分支）
[并行] RAG / 去程交通 / 返程交通
   ↓（汇合）
LLM 种子 POI 提取 → POI 获取
   ↓
行程规划（地理聚类 + TSP）→ POI 富化
   ↓
行程审查（最多重试 2 次）
   ↓
餐厅推荐 → 住宿查询 → 预算校验（超限降档）
   ↓
最终响应渲染（含 RAG Tips / Risks）
```

## 快速开始

```bash
# 1. 安装后端依赖
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env        # 填入途牛 TUNIU_API_KEY
cp config.example.py config.py   # 填入豆包与高德 API Key

# 3. 启动 CLI 交互式界面
python cli.py

# 4. 或启动 Web 服务（FastAPI + 前端）
# 后端：
uvicorn app.main:app --reload
# 前端：
cd frontend && npm install && npm run dev
```

## 安全说明

- **严禁提交** `config.py`、`.env`、`frontend/.env` 等含密钥文件；
- 密钥统一通过 `.env` 与 `config.example.py` 模板管理；
- `data/` 目录（模型权重、checkpointer 数据库、用户记忆）不入版本库。

## 项目背景

　　本人参与东南大学交通学院国家自然科学基金重点项目“超大规模多模式交通系统仿真关键技术与软件研发”。课题4子方向 **LLM Agent 在智能出行规划中的应用**，重点探索 LangGraph 多阶段工作流编排、MCP 多源异构数据接入、以及 RAG + 长期记忆增强的个性化行程生成。

