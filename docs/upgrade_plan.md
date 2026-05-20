# customer_hand 二开升级计划

## 1. 项目定位

当前项目是一个基于 FastAPI 的学习型电商智能客服后端，已经具备 API 契约、会话追踪、YAML Flow、可注册 Action、LLM 结构化命令、关键词 RAG、统一异常和 trace 等能力。

二开目标不是把项目改成大而全的平台，而是围绕“大模型应用开发工程师”岗位，把它升级成一个能讲清楚、能运行、能展示业务闭环的简历项目。

目标项目定位：

> 电商智能客服与工单助手系统：基于 FastAPI + LangGraph + 向量 RAG，实现多轮售后流程、知识库问答、低置信度转人工、工单摘要与处理建议，并支持 Docker Compose 一键启动。

## 2. 总体升级目标

补齐 4 个关键能力：

1. 将关键词 RAG 升级为向量检索。
2. 引入 LangGraph 编排 Agent 主流程。
3. 增加 Docker Compose 一键启动能力。
4. 增加工单助手能力，包括低置信度转人工、工单摘要、分类、优先级和处理建议。

最终希望简历可以这样描述：

> 独立设计并实现电商智能客服与工单助手系统：基于 FastAPI + LangGraph 构建多节点 Agent 编排，将用户理解、意图路由、向量 RAG、YAML Flow、Action 调用、工单生成与回复生成拆分为可观测节点；使用 Chroma + BGE embedding 实现企业知识库检索与答案引用；支持低置信度转人工、工单摘要、分类优先级和处理建议；提供 Docker Compose 一键部署与 pytest 自动化测试。

## 3. 执行原则

### 3.1 保留现有接口

现有接口尽量保持兼容：

- `POST /api/messages`
- `GET /health`
- `GET /api/tracker/{sender_id}/full`
- `POST /api/tracker/{sender_id}/reset`

这样二开过程中不会破坏已有演示和测试。

### 3.2 保留 KnowledgeAnswerer 接口

当前 RAG 入口是 `KnowledgeAnswerer.answer(query, top_k=3)`。

升级向量检索时，上层 Agent 不应该感知底层从关键词检索换成了 Chroma 或 FAISS。应该保持：

```python
answer = knowledge_answerer.answer(query, top_k=3)
```

接口不变，内部实现替换。

### 3.3 先业务闭环，再架构美化

推荐顺序：

1. 先做向量 RAG。
2. 再做工单助手。
3. 再引入 LangGraph。
4. 最后 Docker 化和文档包装。

原因是 RAG 和工单助手最容易形成可见成果，LangGraph 是架构升级，应该在业务链路稳定后再接入。

## 4. 阶段 0：整理现状和建立基线

预计时间：0.5 到 1 天。

### 目标

确认当前项目可运行、测试可通过，并把当前架构梳理清楚。

### 需要关注的文件

```text
main.py
app/agent/agent.py
app/rag/answerer.py
app/rag/retriever.py
app/dialogue/flow_executor.py
app/actions/registry.py
docs/architecture.md
docs/rag.md
docs/interview_qna.md
```

### 执行步骤

1. 跑通现有测试：

```bash
pytest -q
```

2. 手动验证接口：

```bash
uvicorn main:app --reload
```

访问：

```text
http://127.0.0.1:8000/docs
```

3. 验证典型问题：

```text
我要退货
查物流
退货规则
你好
```

4. 记录当前能力边界：

- 当前 RAG 是关键词检索，不是向量检索。
- 当前 Agent 主流程还不是 LangGraph 编排。
- 当前工单能力没有独立模块。
- 当前没有 Docker Compose 一键启动。

### 验收标准

- `pytest -q` 通过。
- `/health` 正常返回。
- `/api/messages` 能处理流程类、知识类和闲聊类输入。
- 能用 1 分钟讲清楚当前架构。

## 5. 阶段 1：关键词 RAG 升级为向量检索

预计时间：3 到 5 天。

### 目标

将当前关键词检索升级为 Chroma 向量检索，并保留 `KnowledgeAnswerer` 对外接口。

### 技术选型

推荐第一版使用：

- Chroma：向量数据库。
- sentence-transformers：本地 embedding。
- `BAAI/bge-small-zh-v1.5`：中文 embedding 模型。

不优先使用 FAISS 的原因：

- FAISS 更像本地向量索引库。
- Chroma 更容易讲成“向量数据库 + 持久化 + collection”。
- Chroma 后续更容易扩展 metadata、重建索引和 Docker 服务。

### 依赖建议

在 `requirements.txt` 中增加：

```text
chromadb
sentence-transformers
```

### 配置建议

在 `.env.example` 中增加：

```env
RAG_BACKEND=chroma
CHROMA_PERSIST_DIR=data/chroma
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
RAG_TOP_K=3
RAG_SCORE_THRESHOLD=0.45
```

### 建议新增文件

```text
app/rag/embedding.py
app/rag/vector_store.py
app/rag/vector_retriever.py
app/rag/reindex.py
```

### 建议修改文件

```text
app/rag/answerer.py
app/rag/retriever.py
app/settings.py
requirements.txt
.env.example
```

### 实现设计

#### 5.1 Embedding 层

新增 `app/rag/embedding.py`：

职责：

- 加载 embedding 模型。
- 提供 `embed_documents(texts)`。
- 提供 `embed_query(query)`。

建议接口：

```python
class EmbeddingModel:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, query: str) -> list[float]:
        ...
```

#### 5.2 Vector Store 层

新增 `app/rag/vector_store.py`：

职责：

- 初始化 Chroma collection。
- 写入 chunk、source、metadata。
- 根据 query embedding 检索 top_k。

返回结果结构建议：

```python
{
    "text": "...",
    "source": "shop_faq.md",
    "score": 0.82,
    "metadata": {}
}
```

#### 5.3 Vector Retriever 层

新增 `app/rag/vector_retriever.py`：

职责：

- 对外提供 `retrieve(query, top_k)`。
- 屏蔽 embedding 和 vector store 细节。
- 根据 `RAG_SCORE_THRESHOLD` 过滤低分结果。

#### 5.4 Reindex 能力

新增 `app/rag/reindex.py`：

职责：

- 加载 `data/knowledge` 下的文档。
- 切分 chunk。
- 写入 Chroma。
- 支持手动重建索引。

可以先做成函数：

```python
def rebuild_index() -> dict:
    ...
```

后续可以挂到 API：

```text
POST /api/knowledge/reindex
GET /api/knowledge/status
```

### API 建议

新增知识库管理接口：

```text
POST /api/knowledge/reindex
GET /api/knowledge/status
```

第一版不需要做复杂上传，先支持本地 `data/knowledge` 重建索引即可。

### 测试建议

新增：

```text
test/test_vector_rag.py
```

覆盖场景：

1. 文档能成功切分并写入向量库。
2. 查询“退货规则”能命中知识片段。
3. `KnowledgeAnswerer.answer()` 接口保持不变。
4. 无命中时返回兜底答案。
5. 响应 metadata 中保留 `matches`。

### 验收标准

- 查询知识类问题时能返回基于向量检索的结果。
- 响应 metadata 中包含 `matches`。
- `matches` 中包含 `text`、`source`、`score`。
- 重启服务后索引仍可用。
- README 中能明确写出“Chroma + BGE embedding + 引用溯源”。

### 难点

主要难点不是接 Chroma API，而是效果调优：

- chunk 太大会导致答案不精确。
- chunk 太小会导致语义断裂。
- score 阈值太低容易胡答。
- score 阈值太高容易频繁无命中。
- 必须保留引用来源，否则面试时说服力弱。

## 6. 阶段 2：加工单助手能力

预计时间：4 到 6 天。

### 目标

让系统从“能回答问题”升级为“能处理客服业务闭环”。

新增能力：

- 低置信度转人工。
- 自动生成工单摘要。
- 自动分类。
- 自动判断优先级。
- 生成处理建议。

### 建议新增目录

```text
app/tickets/
  __init__.py
  models.py
  service.py
  classifier.py
  summarizer.py
  priority.py
  store.py
```

### 数据模型设计

建议在 `app/tickets/models.py` 中定义：

```python
class Ticket:
    ticket_id: str
    sender_id: str
    title: str
    summary: str
    category: str
    priority: str
    suggestion: str
    status: str
    created_at: str
    metadata: dict
```

分类建议：

```text
pre_sale
order
logistics
refund
complaint
knowledge_miss
other
```

优先级建议：

```text
low
medium
high
urgent
```

### 触发转人工的条件

第一版建议用规则 + 可选 LLM。

规则触发：

- 用户包含“人工”“转人工”“投诉”“没人处理”“退款失败”等关键词。
- RAG 最高分低于 `TICKET_CONFIDENCE_THRESHOLD`。
- 连续多轮没有解决。
- Flow 缺少关键槽位且用户多次无法补充。

配置项：

```env
TICKET_CONFIDENCE_THRESHOLD=0.55
TICKET_AUTO_CREATE=true
```

### 工单摘要设计

输入：

- 当前用户消息。
- tracker 历史。
- 当前 Flow 状态。
- RAG matches。
- 已收集 slots。

输出：

```json
{
  "title": "用户申请退货但缺少订单号",
  "summary": "用户表示需要退货，系统已提示补充订单号。",
  "category": "refund",
  "priority": "medium",
  "suggestion": "建议客服核对订单号、签收时间和商品状态；若符合退货规则，可引导用户提交售后申请。"
}
```

### API 建议

新增：

```text
POST /api/tickets
GET /api/tickets/{ticket_id}
GET /api/tickets?sender_id=xxx
```

第一版 store 可以先用内存，后续再换 SQLite 或 Redis。

### Agent 集成方式

在 Agent 中增加 ticket 分支：

```text
用户输入
-> 理解
-> 路由
-> 若低置信度或用户要求人工
-> TicketService.create_ticket()
-> 返回“已为你生成工单”
```

返回给用户的话术示例：

```text
这个问题需要人工进一步确认，我已经帮你生成工单，客服会根据订单信息继续处理。
```

metadata 中建议包含：

```json
{
  "source": "ticket",
  "ticket_id": "...",
  "category": "refund",
  "priority": "medium"
}
```

### 测试建议

新增：

```text
test/test_ticket_service.py
test/test_ticket_route.py
```

覆盖场景：

1. 用户说“我要人工”能生成工单。
2. RAG 无命中或低分能生成工单。
3. 工单包含标题、摘要、分类、优先级和建议。
4. API 能查询工单。
5. Agent 回复中包含转人工提示。

### 验收标准

- 用户主动要求人工时能生成工单。
- 知识库低命中时能生成工单。
- 工单字段结构完整。
- 工单可以通过 API 查询。
- README 中能描述工单助手业务闭环。

### 难点

难点在于“什么时候应该转人工”：

- 不能所有无命中都转人工，否则显得系统没能力。
- 不能永远不转人工，否则业务不真实。
- 工单摘要不能胡编，只能基于当前对话和检索结果。
- 分类和优先级要有规则支撑，不能完全依赖模型自由发挥。

## 7. 阶段 3：引入 LangGraph 编排

预计时间：4 到 6 天。

### 目标

把当前 `Agent.handle_message()` 中的主流程拆成 LangGraph 节点，实现可观测、可扩展的 Agent 编排。

注意：不要直接删除原有主流程。第一版应该让 `Agent.handle_message()` 成为 LangGraph 的入口包装器。

升级后调用方式：

```text
Agent.handle_message()
  -> graph.invoke(state)
  -> responses
```

### 依赖建议

在 `requirements.txt` 中增加：

```text
langgraph
```

### 建议新增目录

```text
app/agent/graph/
  __init__.py
  state.py
  nodes.py
  edges.py
  builder.py
```

### State 设计

建议在 `app/agent/graph/state.py` 中定义：

```python
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    sender_id: str
    message: str
    trace_id: str

    tracker: Any
    commands: list[dict[str, Any]]
    route: str
    confidence: float

    rag_matches: list[dict[str, Any]]
    rag_answer: str

    flow_result: dict[str, Any]
    action_result: dict[str, Any]
    ticket: dict[str, Any]

    responses: list[dict[str, Any]]
    error: str
```

### 节点设计

建议节点：

```text
load_context
understand
route
rag
flow
action
ticket
generate_response
save_context
```

职责说明：

| 节点 | 职责 |
|---|---|
| `load_context` | 根据 sender_id 加载 tracker |
| `understand` | 调 LLMCommandGenerator 或规则 fallback |
| `route` | 判断进入 RAG、Flow、Action、Ticket 或 Chitchat |
| `rag` | 调用 KnowledgeAnswerer |
| `flow` | 调用 FlowExecutor |
| `action` | 调用 ActionRegistry |
| `ticket` | 调用 TicketService 生成工单 |
| `generate_response` | 统一组装 MessageResponse |
| `save_context` | 保存 tracker 和事件 |

### 路由规则

建议路由：

```text
knowledge_answer -> rag
active_flow -> flow
start_flow / set_slot -> flow
action_required -> action
low_confidence -> ticket
human_required -> ticket
chitchat -> generate_response
error -> generate_response
```

### Builder 设计

`app/agent/graph/builder.py` 负责构建图：

```python
from langgraph.graph import StateGraph, START, END


def build_agent_graph(deps):
    graph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("understand", understand)
    graph.add_node("rag", rag)
    graph.add_node("flow", flow)
    graph.add_node("action", action)
    graph.add_node("ticket", ticket)
    graph.add_node("generate_response", generate_response)
    graph.add_node("save_context", save_context)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "understand")
    graph.add_conditional_edges("understand", route)
    graph.add_edge("rag", "generate_response")
    graph.add_edge("flow", "generate_response")
    graph.add_edge("action", "generate_response")
    graph.add_edge("ticket", "generate_response")
    graph.add_edge("generate_response", "save_context")
    graph.add_edge("save_context", END)

    return graph.compile()
```

### Agent 集成方式

在 `app/agent/agent.py` 中：

```python
class Agent:
    def __init__(...):
        self.graph = build_agent_graph(...)

    def handle_message(self, message: str, sender_id: str) -> list[dict]:
        state = self.graph.invoke({
            "message": message,
            "sender_id": sender_id,
        })
        return state["responses"]
```

### 测试建议

新增：

```text
test/test_agent_graph.py
```

覆盖场景：

1. “退货规则”进入 RAG 节点。
2. “我要退货”进入 Flow 节点。
3. “我要人工”进入 Ticket 节点。
4. LLM 失败后走规则 fallback。
5. 最终 `/api/messages` 返回结构不变。

### 验收标准

- 原有 API 不变。
- 原有测试仍通过。
- LangGraph 节点能处理 RAG、Flow、Ticket 三条路径。
- 日志或 trace 中能看到 route。
- README 中有 LangGraph 流程图。

### 难点

LangGraph 的难点不是调用库，而是 State 和路由设计：

- State 太散会导致节点之间强耦合。
- 路由条件不清楚会导致流程不可控。
- 节点拆太细会增加理解成本。
- 节点拆太粗又体现不出 LangGraph 的价值。

建议第一版只拆关键节点，不追求复杂图。

## 8. 阶段 4：Docker Compose 一键启动

预计时间：2 到 3 天。

### 目标

让项目支持一条命令启动，提升工程化程度和简历可信度。

### 建议新增文件

```text
Dockerfile
docker-compose.yml
.dockerignore
scripts/start.sh
```

### 第一版 Compose 设计

建议第一版使用本地持久化 Chroma，而不是单独起 Chroma 服务。

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    command: uvicorn main:app --host 0.0.0.0 --port 8000
```

优点：

- 依赖少。
- 启动稳定。
- 便于 Windows 本地演示。
- Chroma 数据可以通过 `./data` 持久化。

### 第二版 Compose 设计

如果需要更像企业部署，可以再拆出独立 Chroma 服务：

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - chroma
    env_file:
      - .env

  chroma:
    image: chromadb/chroma
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

volumes:
  chroma_data:
```

第一阶段不强制做第二版。

### Dockerfile 建议

基础思路：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### .dockerignore 建议

```text
.git
.pytest_cache
__pycache__
*.pyc
.env
data/chroma
```

注意：真实 `.env` 不要打进镜像。

### README 增加

```bash
copy .env.example .env
docker compose up --build
```

访问：

```text
http://127.0.0.1:8000/docs
```

### 验收标准

- `docker compose up --build` 能启动。
- `/health` 正常。
- `/docs` 正常。
- `/api/messages` 能返回结果。
- Chroma 索引或数据目录能持久化。

### 难点

Docker 的难点主要是工程细节：

- `.env` 不要泄露。
- 容器内路径和 Windows 本地路径要统一。
- Chroma 持久化目录要挂载。
- embedding 模型下载可能导致镜像构建慢。
- 需要避免每次启动都重新建索引。

## 9. 最终验收清单

### 功能验收

- [ ] 用户问“退货规则”时，系统走向量 RAG。
- [ ] RAG 返回结果中包含 `matches`、`source`、`score`。
- [ ] 用户说“我要退货”时，系统走售后 Flow。
- [ ] 用户说“我要人工”时，系统生成工单。
- [ ] RAG 低置信度时，系统能转人工或生成工单。
- [ ] 工单包含标题、摘要、分类、优先级和处理建议。
- [ ] `/api/tickets/{ticket_id}` 能查询工单。
- [ ] LangGraph 能编排 RAG、Flow、Ticket 路径。
- [ ] Docker Compose 可以一键启动。

### 测试验收

- [ ] 原有测试通过。
- [ ] 新增向量 RAG 测试。
- [ ] 新增工单服务测试。
- [ ] 新增 LangGraph 路由测试。
- [ ] API 基础测试通过。

### 文档验收

- [ ] README 增加新架构说明。
- [ ] README 增加 Docker 启动方式。
- [ ] `docs/rag.md` 更新为向量 RAG。
- [ ] `docs/architecture.md` 增加 LangGraph 流程图。
- [ ] `docs/interview_qna.md` 增加二开后的面试问答。

## 10. 推荐里程碑

### 第 1 周

目标：完成向量 RAG。

交付：

- Chroma 向量检索。
- embedding 接入。
- 知识库重建索引。
- RAG matches 返回 source 和 score。
- RAG 测试。

### 第 2 周

目标：完成工单助手。

交付：

- Ticket 模块。
- 低置信度转人工。
- 工单摘要、分类、优先级、建议。
- Ticket API。
- 工单测试。

### 第 3 周

目标：完成 LangGraph 编排。

交付：

- AgentState。
- graph nodes。
- route 逻辑。
- Agent.handle_message 接入 LangGraph。
- LangGraph 路由测试。

### 第 4 周

目标：完成工程化和简历包装。

交付：

- Dockerfile。
- docker-compose.yml。
- README 更新。
- 架构图更新。
- 面试 Q&A 更新。
- 最终演示脚本。

## 11. 面试讲解重点

### 11.1 不是普通聊天机器人

重点讲：

- LLM 不直接执行业务。
- LLM 输出结构化命令。
- 程序根据命令进入 Flow、RAG、Action 或 Ticket。
- 关键业务可控、可追踪。

### 11.2 RAG 有引用溯源

重点讲：

- 文档切分。
- embedding。
- Chroma 检索。
- top_k。
- score 阈值。
- matches 返回来源。

### 11.3 LangGraph 提升可维护性

重点讲：

- 把主链路拆成节点。
- 每个节点职责单一。
- route 决定后续路径。
- trace 可以看到路径。

### 11.4 工单助手体现业务闭环

重点讲：

- 低置信度不强行回答。
- 生成结构化工单。
- 分类和优先级辅助人工客服。
- 处理建议减少客服工作量。

## 12. 最大风险和规避方式

| 风险 | 表现 | 规避方式 |
|---|---|---|
| 技术堆料 | 功能很多但主链路跑不通 | 每阶段都保留可演示场景 |
| RAG 效果差 | 检索不到或乱答 | 调 chunk、top_k、score 阈值，保留引用 |
| LangGraph 过度复杂 | 节点太多，难维护 | 第一版只拆关键节点 |
| 工单生成太假 | 摘要和分类像 prompt demo | 用规则约束字段，用对话历史作为输入 |
| Docker 启动慢 | embedding 模型下载慢 | 支持本地模型缓存或先用轻量模型 |
| 测试缺失 | 改 Agent 后频繁回归 | 每条主路径都补测试 |

## 13. 最小可交付版本

如果时间只有 1 到 2 周，最小可交付版本建议只做：

1. Chroma 向量 RAG。
2. 低置信度转人工工单。
3. README 和面试 Q&A 更新。

这样已经能明显区别于普通 demo。

LangGraph 和 Docker 可以作为第二阶段继续完善。
