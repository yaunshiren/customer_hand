# customer_hand 就业导向优化计划

> 目标：把 `customer_hand` 从“可运行的智能客服 Demo”升级为“能面试、能评测、能复盘、能解释工程取舍的 Agentic RAG 项目”。

本文结合当前项目、`ragenteval-main` 评测结果、`ragent-main` 企业级 RAG 架构思路，以及大模型应用开发岗位高频面试点整理。

---

## 1. 项目最终定位

### 1.1 推荐定位

项目建议定位为：

> 面向消费电子售后客服场景的 Agentic RAG 系统，支持意图识别、混合检索、工具调用、工单流转、多轮对话和自动化评测。

不要把项目讲成“调用大模型 API 的聊天机器人”，而要讲成一个完整系统：

```text
用户问题
  -> 会话记忆
  -> Query Rewrite
  -> Intent Classifier
  -> Route Policy
  -> RAG / Tool / Ticket / Flow / Chitchat
  -> Answer Generation
  -> Trace & Eval
  -> Badcase 回归优化
```

### 1.2 面向岗位

主要匹配岗位：

- 大模型应用开发工程师
- AI Agent 开发工程师
- RAG 工程师
- Python 后端开发工程师
- 智能客服 / 企业知识库方向实习或校招岗位

### 1.3 项目亮点目标

最终项目应能覆盖面试常问的 6 类能力：

| 能力 | 项目中对应实现 |
|---|---|
| RAG | 文档切分、Embedding、混合检索、Rerank、引用来源、评测 |
| Agent | Intent、Route、Tool Calling、Ticket、Flow、多轮 Memory |
| 工程化 | FastAPI、SSE、缓存、超时、降级、Docker、日志 |
| 可观测 | Trace、metadata、latency、retrieved contexts、badcase |
| 评测 | RAG-only、System E2E、hit@k、recall@k、MRR、拒答率 |
| 面试表达 | 架构图、指标变化、失败案例、优化过程 |

---

## 2. 当前现状与核心问题

### 2.1 已具备能力

当前 `customer_hand` 已经具备不错的基础：

- FastAPI HTTP 接口：`/api/messages`、`/health`、tracker API。
- Agent 编排：`load_context -> understand -> route -> rag/ticket/flow/action/chitchat`。
- RAG：支持知识库检索、回答生成、返回匹配文档。
- 工单能力：投诉、故障、售后类问题可以进入工单或流程。
- 评测接入：已接入 `ragenteval-main`，支持 RAG-only 与 System E2E 模式。
- Metadata：系统响应中已经能看到 `route`、`rag_doc_ids`、`ticket_id` 等信息。

### 2.2 评测暴露的问题

根据最近一次 system 模式评测：

```text
intent_top1              = —
hit@1                    = 77.8%
hit@3                    = 88.9%
mrr@10                   = 83.3%
refusal_when_required    = 11.1%
over_retrieval_rate      = 0.0%
ttft_p50_ms              = 5799
ttft_p95_ms              = 11779
```

主要问题：

1. `intent_top1 = —`
   - 系统没有暴露真实 intent 分类结果。
   - 无法证明系统的意图识别能力。

2. `F1-01` 和 `S16-05` 被路由到 `flow`
   - 例如“扫地机充不进电”直接要求订单号，没有先给故障排查。
   - “已发货能改地址吗”没有先回答物流政策。

3. system 模式没有持久化真实 contexts
   - 目前更偏向记录 doc id。
   - 后续 RAGAS、faithfulness、answer correctness 不好评估。

4. 检索还有提升空间
   - system 模式 `hit@1 = 77.8%`，说明 top1 排序不够稳定。
   - 产品型号、政策条款、物流售后类问题容易需要关键词 + 语义混合召回。

5. 非流式接口导致 `ttft` 与 total 接近
   - 用户体验和面试中的“流式输出”考点还没体现。

---

## 3. 总体优化原则

### 3.1 不做大而散

不建议一开始就复制完整企业平台，也不建议优先做庞大的后台页面。

就业导向项目最重要的是：

- 链路完整。
- 问题清晰。
- 指标可量化。
- badcase 能复盘。
- 优化前后能对比。

### 3.2 先能力闭环，再做外观包装

推荐顺序：

```text
Intent -> Route -> Retrieval -> Trace/Eval -> Tool -> Streaming -> Persistence -> README
```

原因：

- Intent 和 Route 直接决定系统是否“像智能客服”。
- Retrieval 决定 RAG 是否可靠。
- Trace/Eval 决定能否面试时讲清楚优化过程。
- Tool 和 Streaming 是加分项。
- 持久化要服务可观测和业务闭环，而不是变成普通 CRUD。

### 3.3 保留现有接口

优先保持以下接口兼容：

- `POST /api/messages`
- `GET /health`
- `GET /api/tracker/{sender_id}/full`
- `POST /api/tracker/{sender_id}/reset`
- `POST /api/eval/rag`

这样不会破坏已有演示和评测脚本。

---

## 4. 目标架构

### 4.1 请求链路

```text
POST /api/messages
  |
  v
Request Context
  - trace_id
  - sender_id
  - conversation_id
  |
  v
Memory Loader
  - 当前会话
  - 历史摘要
  |
  v
Query Rewrite
  - 指代消解
  - 多轮问题改写
  - 多问题拆分
  |
  v
Intent Classifier
  - top intent
  - confidence
  - candidate intents
  |
  v
Route Policy
  - RAG
  - Tool
  - Ticket
  - Flow
  - Chitchat
  - Fallback
  |
  +--> RAG Engine
  |      - keyword/BM25
  |      - vector search
  |      - intent-directed search
  |      - dedup
  |      - rerank
  |      - context builder
  |
  +--> Tool Executor
  |      - query_order
  |      - query_logistics
  |      - create_ticket
  |      - create_invoice
  |
  +--> Ticket Service
  |
  v
Answer Generator
  - prompt
  - citations
  - refusal/fallback
  |
  v
Trace Recorder
  - intent
  - route
  - docs/chunks
  - contexts
  - tool calls
  - latency
  - final answer
```

### 4.2 核心模块建议

```text
app/
  intent/
    schema.py
    taxonomy.py
    classifier.py
    prompt.py
    policy.py
  rag/
    retriever.py
    hybrid_retriever.py
    reranker.py
    context_builder.py
    citation.py
  tools/
    schemas.py
    registry.py
    builtin.py
  observability/
    trace_schema.py
    trace_store.py
    eval_exporter.py
  memory/
    summarizer.py
    rewrite.py
```

---

## 5. 阶段 0：建立稳定基线

预计时间：0.5 天。

### 5.1 目标

在大改前固定当前可运行状态，避免后面优化时不知道是变好还是变坏。

### 5.2 任务

- 跑通 `customer_hand` 测试。
- 跑通 `ragenteval-main` 的 RAG-only 与 system 模式。
- 保存当前 baseline 指标。
- 整理 5 到 10 个 badcase。

### 5.3 建议命令

```bash
cd D:\code4\llm-universe-main\customer_simple\customer_hand
python -m pytest
```

```bash
cd D:\code4\llm-universe-main\customer_simple\ragenteval-main
python -m eval rag run --target customer_hand --customer-mode system --limit 20
python -m eval rag score eval/runs/xxx.jsonl --skip-ragas
```

### 5.4 交付物

- `docs/eval_baseline_YYYYMMDD.md`
- baseline run jsonl
- baseline `_scores.json`
- badcase 表格

### 5.5 验收标准

- 测试全部通过。
- 能复现当前 system 指标。
- 至少列出 5 个错误样本及初步归因。

---

## 6. 阶段 1：真实 Intent Classifier

预计时间：2 到 3 天。

这是第一优先级。

### 6.1 背景

当前系统无法计算真实 `intent_top1`，说明系统没有暴露可评测的真实 intent 分类结果。

同时，`F1`、`S16` 被错误路由，说明 intent 与 route policy 需要拆开优化。

### 6.2 目标

实现一个真实 intent classifier，替代关键词兜底思路。

输出结构：

```json
{
  "intent_id": "S16_物流配送",
  "intent_name": "物流配送",
  "intent_type": "KB_TOOL",
  "confidence": 0.86,
  "candidates": [
    {"intent_id": "S16_物流配送", "confidence": 0.86},
    {"intent_id": "S15_退换货", "confidence": 0.42}
  ],
  "reason": "用户询问已发货后是否能改地址"
}
```

### 6.3 Intent 类型设计

| 类型 | 含义 | 示例 |
|---|---|---|
| `KB` | 纯知识问答 | 参数、保修、退换货政策 |
| `TOOL` | 需要查业务系统 | 查订单、查物流、开发票 |
| `KB_TOOL` | 先回答政策，再引导工具 | 已发货改地址、降价补差 |
| `TICKET` | 工单或人工处理 | 投诉、故障报修 |
| `FLOW` | 多轮槽位流程 | 退货申请、售后流程 |
| `CHITCHAT` | 闲聊或非业务问题 | 问候 |

### 6.4 建议新增文件

```text
app/intent/schema.py
app/intent/taxonomy.py
app/intent/classifier.py
app/intent/prompt.py
app/intent/policy.py
data/intents/customer_intents.yml
```

### 6.5 `customer_intents.yml` 示例

```yaml
version: v1
intents:
  - id: F1_故障报告
    name: 故障报告
    type: TICKET
    description: 用户反馈设备无法使用、故障、异常、报错等问题
    examples:
      - 我的扫地机充不进电了
      - 手表开不了机怎么办
      - 设备一直报错

  - id: S16_物流配送
    name: 物流配送
    type: KB_TOOL
    description: 用户咨询发货、配送、物流进度、改地址、签收等问题
    examples:
      - 我能改收货地址吗？已经发货了
      - 下单后多久能送到
      - 快递到哪里了
```

### 6.6 分类策略

推荐实现两层：

1. 规则兜底
   - 用于明显高置信关键词，如“投诉”“发票”“保修”。
   - 只作为兜底或候选，不作为最终唯一依据。

2. LLM 分类
   - 输入完整 intent tree。
   - 输出 JSON。
   - 服务端做 schema 校验。
   - 失败时降级到规则或 `unknown`。

### 6.7 路由策略

Intent classifier 不直接决定所有行为，而是交给 route policy。

```text
intent = F1_故障报告
  -> route = ticket_or_rag
  -> 先给基础排查步骤
  -> 再询问是否创建工单

intent = S16_物流配送
  -> route = kb_tool
  -> 先回答物流政策
  -> 如果用户提供订单号，再调用物流工具

intent = F2_功能建议
  -> route = ticket
  -> 不走 RAG

intent = F3_投诉吐槽
  -> route = ticket
  -> 不走 RAG
```

### 6.8 评测适配

System 响应 metadata 应包含：

```json
{
  "intentLeafIds": ["S16_物流配送"],
  "intentSource": "system_classifier",
  "intentConfidence": 0.86,
  "system_route": "kb_tool"
}
```

### 6.9 测试用例

至少覆盖：

- `F1-01` 我的扫地机充不进电了
- `F2-01` 希望 APP 能加个深色模式
- `F3-01` 客服态度太差了
- `S16-05` 我能改收货地址吗？已经发货了
- `S14-01` 小米 14 Pro 保修期多久？
- `S6-01` 小米 14 Pro 用什么充电器？

### 6.10 验收指标

| 指标 | 当前 | 目标 |
|---|---:|---:|
| `intent_top1` | `—` | 可计算 |
| `refusal_when_required` | 11.1% | 0% |
| F2/F3 是否检索 | 否 | 否 |
| F1 是否只要订单号 | 是 | 否 |
| S16 是否先答政策 | 否 | 是 |

### 6.11 面试讲法

> 我把意图识别从关键词路由升级成了基于意图树的结构化分类器。分类器输出 top intent、候选 intent、置信度和类型，再由 route policy 决定走 RAG、工具、工单还是闲聊。这样既能避免 F2/F3 这类非知识问题误触发 RAG，也能让系统评测计算 intent_top1。

---

## 7. 阶段 2：修复 Route Policy 与客服业务决策

预计时间：1 到 2 天。

### 7.1 目标

解决“分类对了但路由不合理”的问题。

### 7.2 重点 badcase

#### F1：故障问题

输入：

```text
我的扫地机充不进电了
```

不理想回答：

```text
请提供订单号，我来帮你继续处理。
```

目标回答：

```text
可以先检查充电座电源、金属触点是否有污渍、机器是否正确放回充电座。
如果仍无法充电，我可以帮你创建故障工单或引导售后维修。
```

#### S16：物流改地址

输入：

```text
我能改收货地址吗？已经发货了
```

目标回答：

```text
已发货订单通常不能直接修改地址，需要根据物流状态判断是否可以拦截或改派。
如果你提供订单号，我可以帮你查询当前物流状态。
```

### 7.3 Route Policy 规则

```text
KB:
  直接 RAG

TOOL:
  如果缺少必要参数，先追问
  如果参数齐全，调用工具

KB_TOOL:
  先 RAG 回答规则
  再判断是否需要工具

TICKET:
  先安抚/给基础建议
  再创建或建议创建工单

FLOW:
  进入槽位流程

CHITCHAT:
  简短回复，不检索
```

### 7.4 建议修改位置

```text
app/agent/graph/nodes.py
app/dialogue/llm_generator.py
app/llm/prompts.py
```

### 7.5 验收标准

- F1 不再直接要求订单号。
- S16 不再只进入流程，而是先给政策解释。
- F2/F3 不走 RAG，走工单或反馈收集。
- system eval 中 `refusal_when_required` 降到 0。

---

## 8. 阶段 3：混合检索与 Rerank

预计时间：3 到 5 天。

这是 RAG 面试最重要的升级点。

### 8.1 背景

当前 system 模式 `hit@1 = 77.8%`，说明召回或排序仍有提升空间。

消费电子客服里有大量精确实体：

- 产品型号：小米 14 Pro、小爱音箱 Pro、小米手表 S3。
- 政策词：保修、7 天无理由、价保、发票。
- 操作词：配网、升级、开机、滤芯更换。

只靠向量或只靠关键词都不稳定，应升级为混合检索。

### 8.2 目标架构

```text
query
  -> query rewrite
  -> entity extraction
  -> intent filter
  -> keyword search
  -> vector search
  -> intent-directed search
  -> merge
  -> dedup
  -> score normalization
  -> rerank
  -> top contexts
```

### 8.3 检索通道

| 通道 | 作用 | 适合问题 |
|---|---|---|
| Keyword/BM25 | 精确词匹配 | 型号、政策名、订单类词 |
| Vector | 语义相似 | 自然语言问法、口语表达 |
| Intent-directed | 按意图限定知识域 | S14 只搜售后政策 |
| Entity boost | 提升实体一致文档 | 小米 14 Pro、扫地机 |

### 8.4 建议新增或改造

```text
app/rag/hybrid_retriever.py
app/rag/reranker.py
app/rag/context_builder.py
app/rag/citation.py
app/rag/scoring.py
```

保留上层接口：

```python
knowledge_answerer.answer(query, top_k=3)
```

内部逐步替换实现。

### 8.5 Rerank 方案

第一版可以先做轻量规则 rerank：

- 文档 intent 与预测 intent 一致：加分。
- 产品型号完全匹配：加分。
- 标题命中关键词：加分。
- chunk 太短或太长：扣分。
- 重复文档：去重。

第二版再接入真实 rerank 模型：

- 本地 cross-encoder。
- API rerank。
- LLM-as-reranker。

### 8.6 上下文构造

回答 Prompt 中应包含：

```text
[来源 1]
doc_id: policy_after_sale
chunk_id: policy_after_sale#003
title: 售后政策 - 保修期
content: ...

[来源 2]
...
```

最终 metadata 应记录：

```json
{
  "rag_doc_ids": ["policy_after_sale"],
  "rag_chunk_ids": ["policy_after_sale#003"],
  "retrieved_contexts": ["..."],
  "context_doc_ids": ["policy_after_sale"]
}
```

### 8.7 验收指标

| 指标 | 当前 system | 目标 |
|---|---:|---:|
| `hit@1` | 77.8% | 90%+ |
| `hit@3` | 88.9% | 95%+ |
| `mrr@10` | 83.3% | 90%+ |
| S14 top1 | 不稳定 | 稳定命中售后政策 |
| S6 top1 | 不稳定 | 稳定命中配件/充电器 |

### 8.8 面试讲法

> 我没有只依赖向量检索，而是做了混合检索。向量负责语义召回，BM25 负责型号和政策词的精确匹配，intent-directed retrieval 负责缩小知识域，最后通过 rerank 和去重保证 topK 质量。优化后我用 hit@k、recall@k、MRR 验证效果。

---

## 9. 阶段 4：Trace 与评测持久化

预计时间：2 到 3 天。

这是最能体现工程能力的部分。

### 9.1 为什么优先做 Trace 持久化

普通业务持久化容易变成 CRUD。

大模型应用更重要的是：

- 这次为什么答错？
- 是 intent 错了，还是检索错了？
- 检索到了但模型没用，还是知识库缺失？
- 这次优化有没有让历史 badcase 变好？

所以要优先持久化 trace 和 eval。

### 9.2 推荐技术选型

第一版使用 SQLite 即可：

- 部署简单。
- 面试容易讲清楚。
- 不需要引入复杂依赖。
- 后续可以迁移到 MySQL/PostgreSQL。

### 9.3 建议表

#### `agent_trace`

| 字段 | 说明 |
|---|---|
| `id` | trace id |
| `sender_id` | 用户 id |
| `conversation_id` | 会话 id |
| `user_text` | 用户问题 |
| `rewritten_query` | 改写后问题 |
| `intent_id` | 意图 |
| `intent_confidence` | 置信度 |
| `route` | 路由 |
| `final_answer` | 最终回答 |
| `latency_ms` | 总耗时 |
| `created_at` | 时间 |

#### `retrieval_trace`

| 字段 | 说明 |
|---|---|
| `trace_id` | 请求 trace |
| `query` | 检索 query |
| `channel` | keyword/vector/intent |
| `doc_id` | 文档 id |
| `chunk_id` | chunk id |
| `score` | 原始分数 |
| `rerank_score` | 重排分数 |
| `content` | 实际上下文 |

#### `tool_trace`

| 字段 | 说明 |
|---|---|
| `trace_id` | 请求 trace |
| `tool_name` | 工具名 |
| `arguments_json` | 参数 |
| `result_json` | 结果 |
| `status` | success/failed |
| `latency_ms` | 耗时 |

#### `eval_record`

| 字段 | 说明 |
|---|---|
| `run_id` | 评测批次 |
| `case_id` | 样本 id |
| `question` | 问题 |
| `expected_intent` | 期望 intent |
| `predicted_intent` | 预测 intent |
| `expected_doc_ids` | 期望文档 |
| `retrieved_doc_ids` | 实际文档 |
| `answer` | 回答 |
| `is_hit` | 是否命中 |
| `error_type` | 错误类型 |

### 9.4 错误归因枚举

```text
INTENT_ERROR
ROUTE_ERROR
RETRIEVAL_MISS
RERANK_ERROR
CONTEXT_TOO_NOISY
GENERATION_HALLUCINATION
TOOL_ARGUMENT_ERROR
TOOL_FAILURE
KNOWLEDGE_MISSING
PROMPT_ERROR
```

### 9.5 验收标准

- 每次 `/api/messages` 都能生成 trace。
- system eval 的 jsonl 中包含真实 contexts。
- 能通过 trace 判断每个 badcase 的错误原因。
- 能导出 badcase markdown 报告。

### 9.6 面试讲法

> 大模型应用不能只看最终回答，我给每次请求记录了 intent、route、retrieved chunks、tool call、latency 和最终答案。线上 badcase 可以按链路定位到意图错误、召回缺失、重排错误或生成幻觉，并加入评测集做回归。

---

## 10. 阶段 5：Tool Calling 与业务动作

预计时间：2 到 3 天。

### 10.1 目标

让项目不只是知识问答，而是能执行客服业务动作。

### 10.2 第一批工具

```text
query_order(order_id)
query_logistics(order_id)
create_ticket(category, description, user_id)
create_invoice(order_id, title)
```

### 10.3 工具 schema 示例

```json
{
  "name": "query_logistics",
  "description": "查询订单物流状态",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": {
        "type": "string",
        "description": "订单号"
      }
    },
    "required": ["order_id"]
  }
}
```

### 10.4 Tool 调用策略

```text
用户问政策:
  走 RAG

用户问个人订单:
  如果有订单号 -> 调工具
  如果没有订单号 -> 追问

用户投诉:
  创建 ticket

工具失败:
  返回友好提示
  记录 tool_trace
  必要时转人工
```

### 10.5 防止 Agent 死循环

必须设置：

- 最大工具调用次数。
- 工具超时。
- 重试次数。
- 重复工具调用检测。
- 高风险操作二次确认。

### 10.6 验收标准

- “查一下订单 10001 到哪了”能调用物流工具。
- “我要投诉客服态度差”能创建工单。
- “怎么开发票”先 RAG；“订单 10001 开公司发票”调用发票工具。
- 工具失败能降级，不崩溃。

### 10.7 面试讲法

> RAG 只能回答知识，不能完成业务动作。我把客服场景拆成知识问答和工具调用两类：政策类问题走 RAG，订单、物流、发票类问题走 function calling。工具调用有 schema 校验、超时、重试和 trace 记录。

---

## 11. 阶段 6：Query Rewrite 与 Memory

预计时间：2 天。

### 11.1 目标

解决多轮对话中的指代和上下文缺失。

### 11.2 典型问题

```text
用户：小米 14 Pro 保修多久？
助手：...
用户：那它可以 7 天无理由吗？
```

第二句需要改写为：

```text
小米 14 Pro 可以 7 天无理由退货吗？
```

### 11.3 实现策略

- 短期记忆：保留最近 N 轮对话。
- 实体记忆：最近提到的产品、订单号、问题类型。
- Query Rewrite：把当前问题改写为独立问题。
- 长历史摘要：超过窗口后总结。

### 11.4 Metadata

```json
{
  "original_query": "那它可以 7 天无理由吗？",
  "rewritten_query": "小米 14 Pro 可以 7 天无理由退货吗？",
  "memory_entities": {
    "product": "小米 14 Pro"
  }
}
```

### 11.5 验收标准

- 支持至少 3 个多轮样例。
- 改写后的 query 参与检索。
- trace 中能看到 original 和 rewritten。

---

## 12. 阶段 7：SSE 流式输出与延迟优化

预计时间：1 到 2 天。

### 12.1 背景

当前评测里 `ttft` 接近 total，说明不是标准流式体验。

面试中“如何做流式输出”“如何降低延迟”是高频问题。

### 12.2 目标

新增 SSE 接口：

```text
POST /api/messages/stream
```

返回事件：

```text
event: metadata
data: {"trace_id": "...", "route": "rag"}

event: token
data: {"text": "可以"}

event: token
data: {"text": "先检查"}

event: done
data: {"latency_ms": 1234}
```

### 12.3 需要考虑

- 用户中断连接。
- 模型超时。
- token 记录完整回答。
- 敏感内容后处理。
- trace 记录首 token 延迟与总耗时。

### 12.4 验收标准

- Swagger 或 curl 能看到流式返回。
- trace 中有 `ttft_ms` 和 `total_ms`。
- system eval 可区分首 token 与总耗时。

---

## 13. 阶段 8：知识库导入与切分策略

预计时间：2 到 3 天。

### 13.1 目标

补齐 RAG 面试中的“文档解析、切分、版本管理”考点。

### 13.2 支持格式

第一版：

- Markdown
- TXT
- JSON FAQ
- CSV FAQ

第二版：

- PDF
- Word
- HTML

### 13.3 切分策略

| 文档类型 | 切分方式 |
|---|---|
| FAQ | 一个问答对一个 chunk |
| 政策文档 | 按标题层级 + 段落 |
| 产品参数 | 按产品型号 + 参数组 |
| 操作指南 | 按步骤段落 |

### 13.4 Chunk metadata

```json
{
  "doc_id": "after_sale_policy",
  "chunk_id": "after_sale_policy#003",
  "title": "7 天无理由退货",
  "intent_ids": ["S15_退换货"],
  "product_ids": [],
  "version": "2026-05-30",
  "source_path": "data/knowledge/after_sale.md"
}
```

### 13.5 验收标准

- 能重建知识库索引。
- chunk 有稳定 id。
- 检索结果能返回 source、title、chunk_id。
- 支持知识库版本号。

---

## 14. 阶段 9：缓存、降级与稳定性

预计时间：2 天。

### 14.1 缓存

优先实现：

- 高频问答缓存。
- intent 分类缓存。
- retrieval 缓存。
- embedding 缓存。

缓存 key 示例：

```text
intent:v1:{normalized_query}
retrieval:v1:{intent_id}:{normalized_query}
answer:v1:{query_hash}:{kb_version}
```

### 14.2 超时与降级

必须覆盖：

- LLM 超时。
- RAG 检索失败。
- 工具调用失败。
- JSON 解析失败。
- rerank 失败。

降级策略：

```text
LLM 分类失败 -> 规则分类
Rerank 失败 -> 使用原始召回排序
Tool 失败 -> 友好提示 + 转人工
RAG 无结果 -> 明确说明知识库未覆盖
```

### 14.3 验收标准

- 任意一个外部能力失败，接口不崩溃。
- trace 中记录 fallback reason。
- 用户看到友好提示。

---

## 15. 阶段 10：README、架构图与面试材料

预计时间：1 天。

### 15.1 README 必须包含

- 项目一句话定位。
- 架构图。
- 请求链路。
- RAG 流程。
- Agent 路由策略。
- Tool Calling 示例。
- 评测指标。
- badcase 修复前后。
- 启动方式。
- 测试方式。
- 项目亮点。

### 15.2 建议增加文档

```text
docs/
  job_ready_optimization_plan.md
  eval_baseline.md
  eval_report_after_intent.md
  rag_design.md
  agent_design.md
  badcase_analysis.md
  resume_pitch.md
```

### 15.3 简历表达

推荐写法：

> 基于 FastAPI + LangGraph 构建消费电子智能客服 Agentic RAG 系统，支持意图识别、混合检索、工具调用、工单流转和自动化评测。设计真实 intent classifier 输出意图、置信度与路由类型，区分 RAG、工具、工单、流程和闲聊场景；实现 keyword/vector/intent-directed 混合检索与 rerank，使用 hit@k、recall@k、MRR 和拒答率评估效果；记录每次请求的 intent、route、retrieved chunks、tool calls 和 latency，用于 badcase 归因与回归优化。

### 15.4 面试自述

```text
我做的是一个面向消费电子售后场景的智能客服 Agent。

系统不是简单问答，而是先做意图识别，再根据意图和置信度决定走 RAG、工具调用、工单流转还是闲聊。

RAG 部分我做了混合检索，关键词召回负责型号和政策词，向量召回负责语义匹配，再结合意图过滤和 rerank 提升 topK 质量。

为了避免只凭主观感觉判断效果，我接入了自动化评测，区分 RAG-only 和 System E2E 两种模式，指标包括 hit@k、recall@k、MRR、拒答率和延迟。

在评测中我发现 F1 故障类和 S16 物流类问题会被误路由，于是增加了真实 intent classifier 和 route policy，修复后再用同一批样本做回归验证。
```

---

## 16. 推荐执行排期

### 16.1 两周版本

适合快速形成可面试版本。

| 天数 | 任务 |
|---:|---|
| Day 1 | 固定 baseline，整理 badcase |
| Day 2-3 | 实现真实 intent classifier |
| Day 4 | 修复 route policy，重点处理 F1/S16/F2/F3 |
| Day 5-6 | system eval 输出真实 contexts 与 trace |
| Day 7-8 | 混合检索第一版：keyword + vector + intent filter |
| Day 9 | 轻量 rerank 与 citation |
| Day 10 | 跑评测，写优化前后报告 |
| Day 11 | Tool calling 第一版 |
| Day 12 | SSE 流式输出 |
| Day 13 | README、架构图、简历表达 |
| Day 14 | 模拟面试问答与最终清理 |

### 16.2 一个月版本

适合做成更完整毕业项目。

| 周 | 目标 |
|---|---|
| 第 1 周 | Intent、Route、Trace、Eval |
| 第 2 周 | Hybrid Retrieval、Rerank、Citation、Knowledge Ingestion |
| 第 3 周 | Tool Calling、Memory、Query Rewrite、Streaming |
| 第 4 周 | Cache、Fallback、Docker、Docs、面试材料 |

---

## 17. 验收指标总表

| 类别 | 指标 | 目标 |
|---|---|---|
| Intent | `intent_top1` | 可计算，目标 85%+ |
| Route | F1/S16 误路由 | 修复 |
| RAG | `hit@1` | 90%+ |
| RAG | `hit@3` | 95%+ |
| RAG | `mrr@10` | 90%+ |
| 行为 | `refusal_when_required` | 0% |
| 行为 | F2/F3 检索 | 不检索，不参与 RAG 指标 |
| 观测 | retrieved contexts | system 模式可记录 |
| 延迟 | `ttft` | 流式接口可观测 |
| 工程 | 测试 | pytest 通过 |
| 文档 | README | 能 2 分钟讲清项目 |

---

## 18. Badcase 回归清单

每次优化后至少跑这些样本：

| case_id | 问题 | 期望 |
|---|---|---|
| F1-01 | 我的扫地机充不进电了 | 先给排查建议，再引导工单 |
| F2-01 | 希望 APP 能加个深色模式 | 记录功能建议，不走 RAG |
| F3-01 | 客服态度太差了 | 安抚并创建投诉，不走 RAG |
| S1-01 | 预算 3000 元左右推荐手机 | 走选购推荐 RAG |
| S6-01 | 小米 14 Pro 用什么充电器 | 命中配件/充电器知识 |
| S14-01 | 小米 14 Pro 保修期多久 | 命中售后保修政策 |
| S15-06 | 买了 3 天降价了能退掉重新买吗 | 价保/退货策略正确 |
| S16-05 | 已发货能改收货地址吗 | 先答政策，再引导查订单 |
| S17-01 | 怎么开发票 | 先答开票规则，必要时工具 |

---

## 19. 面试高频问题与项目对应

| 面试问题 | 项目里怎么回答 |
|---|---|
| RAG 流程是什么？ | 文档导入、切分、索引、混合检索、rerank、构造 prompt、生成答案、引用来源 |
| 为什么要混合检索？ | 型号和政策词需要关键词，口语问题需要向量，意图过滤减少噪声 |
| Rerank 有什么用？ | 第一阶段召回重 recall，rerank 提升 topK 排序 |
| RAG 答错怎么排查？ | 看 trace：intent、route、retrieved chunks、rerank、final answer |
| Agent 和 ChatBot 区别？ | Agent 会根据 intent 调 RAG、工具、工单、流程，而不是只生成文本 |
| 工具调用失败怎么办？ | schema 校验、超时、重试、fallback、trace 记录 |
| 怎么做流式输出？ | SSE token event，记录 ttft 和 total |
| 怎么降低幻觉？ | RAG 上下文、引用来源、不知道就拒答、评测和 badcase 回归 |
| 怎么做线上监控？ | trace、latency、token、retrieval hit、tool status、fallback reason |
| 怎么降低成本？ | 缓存、控制 topK、query rewrite、短上下文、小模型分类 |

---

## 20. 最终成果检查清单

### 20.1 代码能力

- [ ] 有真实 intent classifier。
- [ ] 有清晰 route policy。
- [ ] 有混合检索。
- [ ] 有 rerank 或轻量重排。
- [ ] 有工具调用。
- [ ] 有 trace 持久化。
- [ ] 有 system eval contexts。
- [ ] 有 SSE 流式接口。
- [ ] 有测试。

### 20.2 评测能力

- [ ] RAG-only 只评测 `requires_rag=true`。
- [ ] F2/F3 不参与 RAG 检索指标。
- [ ] system eval 测真实 `/api/messages`。
- [ ] 有优化前后指标对比。
- [ ] 有 badcase 归因。

### 20.3 文档能力

- [ ] README 有项目定位。
- [ ] README 有架构图。
- [ ] docs 有 RAG 设计。
- [ ] docs 有 Agent 设计。
- [ ] docs 有评测报告。
- [ ] docs 有简历表达。

### 20.4 面试能力

- [ ] 能 1 分钟介绍项目。
- [ ] 能讲清楚一次 badcase 修复。
- [ ] 能解释为什么要混合检索。
- [ ] 能解释为什么 F2/F3 不参与 RAG 指标。
- [ ] 能解释 system eval 和 RAG-only eval 的区别。
- [ ] 能讲清楚 trace 对排查问题的价值。

---

## 21. 最推荐先做的 5 件事

如果时间有限，按这个顺序做：

1. 实现真实 intent classifier，让 `intent_top1` 可计算。
2. 修复 F1/S16 路由问题，把 `refusal_when_required` 降到 0。
3. system eval 保存真实 retrieved contexts，方便后续 RAGAS 和 badcase 分析。
4. 做 keyword + vector + intent filter 的混合检索，把 `hit@1` 往 90%+ 提。
5. 写一份优化前后评测报告，放到 README 和简历里。

---

## 22. 一句话总结

`customer_hand` 下一步不应该只是加功能，而应该围绕“大模型应用如何从 Demo 变成可评测、可观测、可迭代的业务系统”来优化。

最核心的升级路线是：

```text
真实意图识别
  -> 合理路由决策
  -> 混合检索与重排
  -> Trace 与评测闭环
  -> 工具调用和业务动作
  -> 流式输出与工程稳定性
```

这样最终在面试中，你能讲的不只是“我做了 RAG”，而是：

> 我用评测发现系统误路由和检索排序问题，用 intent classifier、route policy、hybrid retrieval、rerank 和 trace 持久化逐步定位并优化，并用自动化指标验证效果。

