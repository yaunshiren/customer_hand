# ragenteval-main 接入 customer_hand 实施路线

> 目标：让 `D:\code4\llm-universe-main\customer_simple\ragenteval-main` 的评测流水线可以评测
> `D:\code4\llm-universe-main\customer_simple\customer_hand`，并尽量复用现有 `run -> score -> report` 链路。

## 1. 结论

`ragenteval-main` 可以用于 `customer_hand`，但不能原样运行。现有评测 runner 面向 `ragent` 后端，依赖：

- 登录接口：`POST /auth/login`
- 生产问答接口：`GET /rag/v3/chat`，SSE 流式返回
- 评测旁路接口：`GET /rag/eval`，返回检索证据、意图、trace 等结构化数据
- `doc_id_map.json`：把 ragent 内部文档 ID 映射回业务文档 ID

`customer_hand` 当前暴露的是：

- `GET /health`
- `POST /api/messages`
- `GET /api/tracker/{sender_id}/full`
- `POST /api/tracker/{sender_id}/reset`
- `GET /api/knowledge/status`
- `POST /api/knowledge/reindex`

因此推荐方案是：**保留 `ragenteval-main` 的数据模型、指标、报告能力，在 `customer_hand` 中补齐评测旁路，在 `ragenteval-main` 中新增 customer_hand runner/adapter。**

## 2. 接口差异分析

### 2.1 生产问答接口

| 项目 | 接口 | 方法 | 入参 | 出参 | 评测影响 |
|---|---|---|---|---|---|
| ragenteval 当前适配对象 ragent | `/rag/v3/chat` | GET + SSE | `question` query 参数 | SSE 事件：`meta`、`message`、`finish`、`reject`、`done` | 可以采集首 token 时间 `first_token_ms`、完整回答、thinking、最终状态 |
| customer_hand | `/api/messages` | POST JSON | `{"sender_id": "...", "message": "..."}` | `list[MessageResponse]`，字段为 `recipient_id/text/timestamp/metadata` | 非流式，只能采集总耗时；`first_token_ms` 初期可回退为 `latency_ms` |

现状差异：

- ragent runner 的 `stream_chat_one_query()` 写死了 SSE 解析。
- customer_hand 的 `/api/messages` 是同步 JSON 响应，不需要 token 登录。
- customer_hand 一次响应是列表，需要 runner 从列表中合并或选择最终 `text`。
- customer_hand 的 `metadata` 目前只暴露 `route`、`rag_match_count`、`ticket_id`、`error` 等，默认不暴露完整 `rag_matches`。

### 2.2 评测旁路接口

| 项目 | 接口 | 返回内容 | 当前状态 |
|---|---|---|---|
| ragent | `/rag/eval` | `retrievedDocIds`、`retrievedChunkIds`、`retrievedContexts`、`retrievedContextDocIds`、`intentLeafIds`、`hasKb`、`hasMcp`、`traceId` | 已由 `runner.py` 使用 |
| customer_hand | 无等价接口 | 内部 RAG 能拿到 `matches`，但 API 未公开 | 需要新增 |

如果不新增 customer_hand 评测旁路，只能评回答文本和粗略行为，无法可靠计算：

- `hit@k`
- `recall@k`
- `mrr@10`
- `context_precision`
- `context_recall`
- 检索证据相关失败样本定位

### 2.3 知识库接口

| 项目 | 知识库初始化方式 | 当前评测依赖 |
|---|---|---|
| ragenteval-main -> ragent | `eval/rag/init/create_kbs.py`、`upload_docs.py`、`build_intent_tree.py` 调 ragent 管理接口 | 依赖 ragent 数据库文档 ID 和 `doc_id_map.json` |
| customer_hand | 本地 `data/knowledge` 目录递归读取 `.md/.txt/.markdown` | 不需要上传接口，但需要把 `ragenteval-main/knowledge_base` 接入 `KNOWLEDGE_DIR` |

customer_hand 的 `KnowledgeDocumentLoader.load_directory()` 已支持递归读取 Markdown，因此有两种知识库接入方式：

1. 推荐：设置 `KNOWLEDGE_DIR=D:\code4\llm-universe-main\customer_simple\ragenteval-main\knowledge_base`。
2. 备选：把 `knowledge_base` 复制或同步到 `customer_hand/data/knowledge/bitselect`。

推荐使用环境变量方式，避免复制两份知识库导致不同步。

## 3. 数据结构差异分析

### 3.1 ragenteval 输入样本 EvalSample

`EvalSample` 来自 `eval/rag/dataset/eval_set_v1.jsonl`，核心字段：

| 字段 | 含义 | customer_hand 接入要求 |
|---|---|---|
| `query_id` | 样本 ID | 原样保留 |
| `query` | 用户问题 | 传给 `/api/messages.message` |
| `intent_l1` / `intent_l2` | 标注意图 | 用于指标分层；customer_hand 需要产出可对齐的 `intent_pred` |
| `requires_rag` | 是否需要检索 | 用于行为指标和 RAGAS 过滤 |
| `expected_doc_ids` | 必须命中文档 ID | customer_hand 检索结果必须能还原业务 doc_id |
| `expected_doc_ids_nice` | 可接受补充命中文档 ID | 原样保留 |
| `ground_truth` | 参考答案 | RAGAS 和 answer correctness 使用 |
| `expected_answer_type` / `trap_type` | 样本标签 | 可继续作为分析维度，当前指标不强依赖 |

### 3.2 ragenteval 输出记录 EvalRecord

所有评分和报告都依赖 `EvalRecord`。customer_hand runner 必须产出同形结构：

| EvalRecord 字段 | ragent 来源 | customer_hand 建议来源 |
|---|---|---|
| `query_id/user_input/reference/...` | `EvalSample` | `EvalSample` |
| `response` | SSE message 聚合 | `/api/messages` 返回列表中的 `text` 合并 |
| `thinking` | SSE think delta | 暂无，填 `None` |
| `latency_ms` | SSE 总耗时 | `POST /api/messages` 总耗时 |
| `first_token_ms` | 首个 response token 到达时间 | 初期填 `latency_ms`；后续如增加流式接口再精确采集 |
| `final_status` | SSE finish/reject/cancel/error | HTTP 2xx 且有文本为 `success`；业务拒答可按文本/metadata 判定 `refused` |
| `error` | 异常或 reject message | HTTP 错误、异常、metadata.error |
| `conversation_id` | SSE meta | 使用 `sender_id` 或 `None` |
| `task_id` | SSE meta | 暂无，填 `None` |
| `retrieved_doc_ids` | `/rag/eval.retrievedDocIds` 映射后 | 由 customer_hand eval 旁路从 `matches` 还原 |
| `retrieved_doc_ids_raw` | ragent 内部文档 ID | customer_hand 可与 `retrieved_doc_ids` 相同 |
| `retrieved_chunk_ids` | `/rag/eval.retrievedChunkIds` | `match.chunk_id` |
| `retrieved_contexts` | `/rag/eval.retrievedContexts` | `match.text`，建议带 frontmatter `doc_id` |
| `retrieved_context_doc_ids` | chunk 所属 doc_id | 从文件 frontmatter 或路径文件名还原 |
| `intent_pred` | `/rag/eval.intentLeafIds[0]` | 初期用 route/command_type 映射；后续加意图分类器 |
| `intent_pred_all` | `/rag/eval.intentLeafIds` | 同上，列表 |
| `has_kb` | 是否走知识库 | `route == "rag"` 或 eval 旁路命中 matches |
| `has_mcp` | 是否调用工具 | customer_hand 当前可用 `call_tool` / action 判断；初期可填 `False` |
| `trace_id` | `/rag/eval.traceId` | HTTP 响应头 `X-Trace-Id` |

### 3.3 customer_hand 内部 RAG 数据结构

customer_hand 当前内部结构如下：

| 结构 | 字段 | 说明 |
|---|---|---|
| `KnowledgeChunk` | `chunk_id/source/text/metadata` | 检索最小单元 |
| `RetrievalMatch` | `chunk/score` | 检索命中 |
| `RetrievalResult` | `query/matches` | 检索结果集合 |
| `KnowledgeAnswerer.answer()` 返回 dict | `answer/matches/used_llm/llm_result?` | `matches` 已序列化为 `chunk_id/source/score/text/metadata/rag_backend` |
| `AgentState` | `route/rag_query/rag_matches/knowledge_answer/used_llm` | Graph 内部保留完整 RAG 结果 |
| `MessageResponse` | `recipient_id/text/timestamp/metadata` | 对外生产响应，当前未完整暴露 `rag_matches` |

关键缺口：

- `KnowledgeDocumentLoader` 现在只返回 `(source, content)`，没有解析 Markdown frontmatter。
- `TextSplitter` 只写入 `chunk_index/start/end`，没有写入 `doc_id/title/doc_type`。
- `chunk_id` 由文件名 slug 加序号组成，例如 `PROD_PHONE_006-0`，但 `retrieved_doc_ids` 需要还原为 `PROD_PHONE_006`。
- `/api/messages` 不返回完整 `rag_matches`，评测 runner 无法直接拿到检索证据。

## 4. 接入总方案

### 4.1 推荐架构

```text
ragenteval-main
  eval/rag/dataset/eval_set_v1.jsonl
  eval/rag/pipeline/customer_hand_runner.py
        │
        │ POST /api/messages
        ▼
customer_hand 生产链路
        │
        │ GET /api/eval/rag?question=...
        ▼
customer_hand 评测旁路
        │
        ▼
EvalRecord JSONL
        │
        ├─ score: intent / retrieval / behavior / latency / RAGAS
        ▼
reports/<run>/{report.md, per_sample.csv, failures.jsonl, slides.html}
```

### 4.2 为什么采用“生产接口 + 评测旁路”双接口

- 生产接口保留真实用户体验，用于采集最终回答和耗时。
- 评测旁路只读、无副作用，用于暴露检索证据，避免污染生产 API。
- 与现有 ragent runner 的设计一致，迁移成本最低。
- 后续可 A/B 对比不同 customer_hand 配置，如 keyword vs chroma、不同 top_k、不同阈值。

## 5. 详细实施路线

### 阶段 0：基线准备

目标：确认两个项目可以单独运行。

任务：

1. 在 `customer_hand` 中确认依赖安装：

   ```cmd
   cd /d D:\code4\llm-universe-main\customer_simple\customer_hand
   conda activate customer
   pip install -r requirements.txt
   pytest -q
   ```

2. 启动 customer_hand：

   ```cmd
   uvicorn main:app --reload --port 8000
   ```

3. 验证生产接口：

   ```cmd
   curl http://127.0.0.1:8000/health
   curl -X POST http://127.0.0.1:8000/api/messages ^
     -H "Content-Type: application/json" ^
     -d "{\"sender_id\":\"eval_smoke\",\"message\":\"退货规则\"}"
   ```

4. 在 `ragenteval-main` 中确认评测 CLI 可导入：

   ```cmd
   cd /d D:\code4\llm-universe-main\customer_simple\ragenteval-main
   python -m eval rag score --skip-ragas
   ```

验收标准：

- `customer_hand` 的 `pytest` 通过。
- `/api/messages` 能返回 `MessageResponse` 列表。
- `ragenteval-main` 能正常导入 `eval` 包。

### 阶段 1：让 customer_hand 使用比特严选知识库

目标：让 customer_hand 检索 `ragenteval-main/knowledge_base`，而不是只检索默认 `shop_faq.md`。

任务：

1. 在 `customer_hand/.env` 中设置：

   ```env
   KNOWLEDGE_DIR=D:\code4\llm-universe-main\customer_simple\ragenteval-main\knowledge_base
   RAG_BACKEND=keyword
   RAG_TOP_K=5
   LLM_ENABLED=true
   ```

2. 如果先不接真实 LLM，可保留 `LLM_ENABLED=false` 做检索烟测，但完整回答质量会偏低。

3. 先用 keyword 后端完成评测闭环；后续再切 chroma。

4. 如需向量检索：

   ```env
   RAG_BACKEND=chroma
   CHROMA_PERSIST_DIR=data/chroma
   EMBEDDING_ENABLED=true
   ```

   然后调用：

   ```cmd
   curl -X POST http://127.0.0.1:8000/api/knowledge/reindex
   ```

验收标准：

- `GET /api/knowledge/status` 能看到知识库索引状态。
- 用 `退货规则`、`Redmi K70 拍照怎么样`、`扫地机充不进电` 等问题能命中比特严选文档。

### 阶段 2：补齐 doc_id 解析和 chunk 元数据

目标：让 customer_hand 的每个检索命中都能还原到业务文档 ID，例如 `PROD_PHONE_006`。

建议改动：

1. 在 `app/rag/documents.py` 中新增 `KnowledgeDocument` dataclass：

   ```python
   @dataclass
   class KnowledgeDocument:
       source: str
       text: str
       metadata: dict[str, Any]
   ```

2. 让 `KnowledgeDocumentLoader.load_directory()` 解析 Markdown frontmatter：

   - 如果文件以 `---` 开头，解析其中的 `doc_id`、`doc_type`、`title`、`version`、`related_intents`。
   - 如果没有 frontmatter，则从文件名 stem 推导 `doc_id`。

3. 让 `TextSplitter.split()` 接收 metadata，并写入每个 `KnowledgeChunk.metadata`：

   ```python
   {
       "doc_id": "PROD_PHONE_006",
       "doc_type": "product_detail",
       "title": "Redmi K70 商品详情",
       "source": ".../PROD_PHONE_006.md",
       "chunk_index": 0,
       "start": 0,
       "end": 400,
   }
   ```

4. 保持向后兼容：已有调用可以继续传 `(source, text)` 或让 loader 返回对象后在 retriever/reindex 中适配。

验收标准：

- `KnowledgeAnswerer.answer(...).matches[0]["metadata"]["doc_id"]` 存在。
- 对 `PROD_PHONE_006.md` 命中的 chunk，`doc_id == "PROD_PHONE_006"`。
- keyword 和 chroma 两个后端都保留 `doc_id`。

### 阶段 3：新增 customer_hand 评测旁路接口

目标：提供等价于 ragent `/rag/eval` 的只读接口。

建议新增接口：

```text
GET /api/eval/rag?question=...&top_k=5
```

建议响应结构：

```json
{
  "success": true,
  "data": {
    "question": "预算 3000 元左右，想买一台拍照还不错的手机，推荐哪款？",
    "retrievedDocIds": ["GUIDE_PHONE_002", "PROD_PHONE_006"],
    "retrievedChunkIds": ["GUIDE_PHONE_002-0", "PROD_PHONE_006-1"],
    "retrievedContexts": ["---\ndoc_id: GUIDE_PHONE_002\n---\n...", "..."],
    "retrievedContextDocIds": ["GUIDE_PHONE_002", "PROD_PHONE_006"],
    "intentLeafIds": ["S1_选购推荐"],
    "hasKb": true,
    "hasMcp": false,
    "traceId": "..."
  }
}
```

实现建议：

1. 新建 `app/api/eval.py` 或直接在 `main.py` 中先实现最小接口。
2. 复用 `agent.knowledge_answerer.retriever.retrieve(question, top_k=top_k)`。
3. 把 `RetrievalMatch` 转为 ragent 兼容字段：

   - `retrievedDocIds`: `match.chunk.metadata["doc_id"]`
   - `retrievedChunkIds`: `match.chunk.chunk_id`
   - `retrievedContexts`: 建议拼上 `doc_id` frontmatter，便于 `score.py` 的 sanity check：

     ```text
     ---
     doc_id: PROD_PHONE_006
     source: ...
     ---
     {chunk.text}
     ```

   - `retrievedContextDocIds`: 同 `doc_id`
   - `hasKb`: `len(matches) > 0`
   - `hasMcp`: 初期 `False`
   - `traceId`: `trace_id_from_request(request)`

4. 意图字段初期可以先做规则映射：

   - 如果问题包含“推荐/预算/买哪款” -> `S1_选购推荐`
   - 如果包含“查订单/APP” -> `S10_APP功能`
   - 如果包含“升级/固件” -> `S11_固件升级`
   - 如果包含“退货/退款/售后” -> 对应 `S8_售后政策` 或现有评估集意图

   后续再替换为独立意图分类器。

验收标准：

- `GET /api/eval/rag?question=退货规则` 返回 200。
- 返回字段名与 ragent `/rag/eval` 兼容。
- 命中文档时 `retrievedDocIds` 非空，且为业务 doc_id。

### 阶段 4：新增 ragenteval 的 customer_hand runner

目标：让评测侧可以通过 CLI 选择被测目标。

建议新增文件：

```text
eval/rag/pipeline/customer_hand_runner.py
```

职责：

1. 读取 `CUSTOMER_HAND_BASE_URL`，默认 `http://127.0.0.1:8000`。
2. 读取 `eval/rag/dataset/eval_set_v1.jsonl`。
3. 对每条样本：

   - 调 `POST /api/messages` 获取最终回答。
   - 调 `GET /api/eval/rag` 获取检索证据。
   - 合并为 `EvalRecord`。
   - 写入 `eval/runs/customer_hand_<ts>.jsonl` 或 `eval/runs/v1_customer_hand_<ts>.jsonl`。

4. 支持 `--limit`、`--start`、`--workers`、`--filter-intent`。

核心映射：

| customer_hand runner 状态 | EvalRecord |
|---|---|
| response list 的 text 合并 | `response` |
| POST 总耗时 | `latency_ms` |
| POST 总耗时 | `first_token_ms` 初期回填 |
| HTTP 成功 | `final_status="success"` |
| HTTP 异常 | `final_status="error"` |
| X-Trace-Id | `trace_id` |
| eval 旁路 data | `retrieved_*`、`intent_pred*`、`has_kb`、`has_mcp` |

验收标准：

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\ragenteval-main
set CUSTOMER_HAND_BASE_URL=http://127.0.0.1:8000
python -m eval rag run-customer-hand --limit 5 --skip-ragas
```

能够生成 runs 文件。

### 阶段 5：扩展 CLI

目标：让接入方式清晰，不破坏原有 ragent runner。

推荐 CLI 形态：

```cmd
python -m eval rag run --target customer_hand --limit 5
python -m eval rag all --target customer_hand --limit 5 --skip-ragas
```

如果希望少改原有 CLI，也可以先新增命令：

```cmd
python -m eval rag run-customer-hand --limit 5
python -m eval rag all-customer-hand --limit 5 --skip-ragas
```

推荐最终采用 `--target`，因为后续还可以支持：

- `--target ragent`
- `--target customer_hand`
- `--target mock`
- `--target remote`

验收标准：

- 原有 `python -m eval rag run` 仍能跑 ragent。
- 新增 `--target customer_hand` 后能跑 customer_hand。
- `score/report/diff` 不需要感知 target。

### 阶段 6：先跑自建指标，再跑 RAGAS

目标：先用低成本指标验证数据链路，再启用 LLM-as-judge。

执行顺序：

```cmd
python -m eval rag run --target customer_hand --limit 5
python -m eval rag score <runs_file> --skip-ragas
python -m eval rag report <runs_file>
```

确认无误后：

```cmd
set AIHUBMIX_API_KEY=...
python -m eval rag score <runs_file> --ragas-limit 5
python -m eval rag report <runs_file>
```

验收标准：

- 自建指标有输出：intent、hit@k、recall@k、mrr、behavior、latency。
- RAGAS 不再因为 `empty retrieved_contexts` 大量跳过。
- `reports/<run>/report.md`、`per_sample.csv`、`failures.jsonl`、`slides.html` 都生成。

### 阶段 7：补充测试

customer_hand 侧建议新增：

1. `test_eval_rag_api.py`
   - 验证 `/api/eval/rag` 字段完整。
   - 验证 `retrievedDocIds` 能从 frontmatter 还原。
   - 验证无命中时 `success=true` 且列表为空。

2. `test_document_metadata.py`
   - 验证 Markdown frontmatter 解析。
   - 验证无 frontmatter 时从文件名推导 doc_id。

ragenteval-main 侧建议新增：

1. `test_customer_hand_runner.py`
   - mock `/api/messages` 和 `/api/eval/rag`。
   - 验证能生成完整 `EvalRecord`。
   - 验证 response list 合并逻辑。

2. `test_customer_hand_mapping.py`
   - 验证 customer_hand eval payload 到 EvalRecord 的字段映射。

验收标准：

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\customer_hand
pytest -q

cd /d D:\code4\llm-universe-main\customer_simple\ragenteval-main
python -m pytest -q
```

## 6. 最小可用版本和完整版本

### 6.1 最小可用版本

只做以下改动：

1. `customer_hand` 使用 `KNOWLEDGE_DIR` 指向 `ragenteval-main/knowledge_base`。
2. `customer_hand` 新增 `/api/eval/rag`。
3. `ragenteval-main` 新增 `customer_hand_runner.py`。
4. `first_token_ms = latency_ms`。
5. `intent_pred` 先用简单规则或填 `None`。

能获得：

- 回答质量指标
- 检索 Hit/Recall/MRR
- latency 总耗时
- RAGAS 大部分指标

暂时不足：

- TTFT 不是真实首 token。
- 意图准确率不稳定或不可用。
- Tool Calling 仍未评。

### 6.2 完整版本

继续补：

1. customer_hand 增加流式接口或 SSE 包装，真实采集 TTFT。
2. customer_hand 增加独立意图分类器，输出 22 个二级意图。
3. eval_set 增加 `tool_calls_gold`，扩展 Tool Calling 评测。
4. 对比 `keyword` vs `chroma` vs `hybrid`。
5. 引入批量 A/B 评测和报告 diff。

## 7. 风险和处理策略

| 风险 | 表现 | 处理 |
|---|---|---|
| 知识库规模从 1 篇变 120 篇后 keyword 召回差 | Hit@K 低 | 先调 `RAG_TOP_K=5/10`，再切 chroma |
| 无 doc_id 元数据 | retrieval 指标全低 | 必须解析 frontmatter 或从文件名推导 |
| customer_hand LLM 命令没有路由到 RAG | 生产回答不走知识库 | Prompt 增加比特严选场景规则；或评测模式下对 requires_rag 样本强制 RAG |
| first_token_ms 不准确 | TTFT 指标虚高/不精确 | 初期声明回退总耗时；后续加流式接口 |
| RAGAS 成本高 | 评测慢且花费高 | 开发阶段用 `--skip-ragas` 或 `--ragas-limit 5` |
| 评估集和 customer_hand 业务能力不匹配 | 大量失败 | 先跑 5-20 条 smoke，按 failures 逐步补业务能力 |

## 8. 建议的提交顺序

1. `docs:` 添加本接入方案。
2. `feat(customer_hand): parse knowledge doc metadata`
3. `feat(customer_hand): add rag eval endpoint`
4. `test(customer_hand): cover eval rag endpoint`
5. `feat(eval): add customer_hand runner`
6. `feat(eval): support --target customer_hand`
7. `test(eval): cover customer_hand record mapping`
8. `docs:` 更新 README 的 customer_hand 评测命令。

## 9. 推荐最终命令

启动 customer_hand：

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\customer_hand
set KNOWLEDGE_DIR=D:\code4\llm-universe-main\customer_simple\ragenteval-main\knowledge_base
set RAG_BACKEND=keyword
set LLM_ENABLED=true
uvicorn main:app --reload --port 8000
```

运行评测：

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\ragenteval-main
set CUSTOMER_HAND_BASE_URL=http://127.0.0.1:8000
python -m eval rag all --target customer_hand --limit 5 --skip-ragas
```

生成完整报告：

```cmd
set AIHUBMIX_API_KEY=<your_key>
python -m eval rag score <runs_file> --ragas-limit 10
python -m eval rag report <runs_file>
```

## 10. 优先级建议

最高优先级：

- doc_id 元数据解析
- `/api/eval/rag`
- customer_hand runner

中优先级：

- CLI `--target`
- RAGAS 跑通
- failures 分析

低优先级：

- SSE/TTFT 精准采集
- Tool Calling 评测
- hybrid retrieval

按这个顺序推进，可以先在 1-2 天内拿到最小闭环，再逐步把它打磨成适合面试展示的“有评测闭环的大模型应用项目”。
