# customer_hand 接入 ragenteval-main 新手拆解版

本文是对 `docs/customer_hand_ragenteval_integration_plan.md` 的新手版细化。目标不是重新设计，而是把原方案里的每个阶段拆成足够小、可以照着做的小步。

参考代码目录：

- `D:\code4\llm-universe-main\customer_simple\customer_hand`
- `D:\code4\llm-universe-main\customer_simple\ragenteval-main`

## 0. 先看结论

当前两个项目已经具备一部分接入能力：

- `customer_hand/main.py` 已经有 `POST /api/messages`。
- `customer_hand/main.py` 当前也已有 `GET /api/eval/rag` 的初版评测旁路。
- `ragenteval-main/eval/rag/pipeline/customer_hand_runner.py` 已经有 customer_hand runner 初版。
- `ragenteval-main/eval/common/cli.py` 已经有 `--target customer_hand` 初版。

但还需要补强：

- `customer_hand/app/rag/documents.py` 还没有把 Markdown frontmatter 解析成 `doc_id/title/doc_type` 等 metadata。
- `customer_hand/app/rag/splitter.py` 还没有把文档 metadata 传进每个 chunk。
- `customer_hand/main.py` 的 `/api/eval/rag` 目前主要靠 `Path(source).stem` 还原 doc_id，能先跑通，但不够稳。
- `ragenteval-main/eval/rag/pipeline/customer_hand_runner.py` 生成的文件名是 `customer_hand_<ts>.jsonl`，而 `latest_runs_file()` 默认找 `v1_*.jsonl`，所以最好统一命名或显式传 runs 文件。
- 两边都缺少针对 customer_hand 接入链路的专门测试。

## 1. 阶段拆分总览

| 阶段 | 名称 | 建议拆成多少小步 | 当前状态 | 主要产物 |
|---|---:|---:|---|---|
| 阶段 0 | 基线准备 | 16 小步 | 需要你本地确认 | 两个项目都能单独启动或导入 |
| 阶段 1 | 让 customer_hand 使用比特严选知识库 | 18 小步 | 需要配置和验收 | `KNOWLEDGE_DIR` 指向 `ragenteval-main/knowledge_base` |
| 阶段 2 | 补齐 doc_id 解析和 chunk metadata | 24 小步 | 需要重点完善 | 每个检索 chunk 都能稳定还原业务 doc_id |
| 阶段 3 | 完善 customer_hand 评测旁路接口 | 21 小步 | 已有初版，需要加固 | `/api/eval/rag` 字段稳定、可被 runner 使用 |
| 阶段 4 | 完善 ragenteval 的 customer_hand runner | 20 小步 | 已有初版，需要加固 | customer_hand runs JSONL |
| 阶段 5 | 扩展和整理 CLI | 14 小步 | 已有初版，需要统一细节 | `python -m eval rag run --target customer_hand` |
| 阶段 6 | 先跑自建指标，再跑 RAGAS | 18 小步 | 需要端到端验收 | `_scores.json`、`report.md`、`slides.html` |
| 阶段 7 | 补充测试 | 28 小步 | 需要新增 | customer_hand 和 ragenteval 两侧测试 |

总计：159 个小步。

你可以按阶段提交代码。对新手最友好的顺序是：阶段 0 -> 阶段 1 -> 阶段 3 -> 阶段 4 -> 阶段 6，先跑通最小闭环；再回头做阶段 2、阶段 5、阶段 7，把质量补上。

## 2. 阶段 0：基线准备，16 小步

目标：先确认两个项目各自能工作，不要一开始就改代码。

涉及文件：

- `customer_hand/README.md`
- `customer_hand/requirements.txt`
- `customer_hand/main.py`
- `customer_hand/app/settings.py`
- `ragenteval-main/README.md`
- `ragenteval-main/eval/common/schemas.py`
- `ragenteval-main/eval/common/cli.py`

小步：

1. 打开 `customer_hand/docs/customer_hand_ragenteval_integration_plan.md`，先只看目录和阶段名称。
2. 打开 `ragenteval-main/README.md`，理解 `run -> score -> report` 三步。
3. 打开 `ragenteval-main/eval/common/schemas.py`，只看 `EvalSample`、`EvalRecord`、`MetricResult` 三个类。
4. 在 `customer_hand` 目录执行 `git status --short`，记录当前有哪些未提交文件。
5. 在 `ragenteval-main` 目录执行 `git status --short`，记录当前有哪些未提交文件。
6. 确认 Python 环境是你准备用的环境，例如 `conda activate customer`。
7. 在 `customer_hand` 中安装依赖：`python -m pip install -r requirements.txt`。
8. 先不要跑全量测试，先跑最小导入测试：`python -c "import main; print(main.SERVICE_NAME)"`。
9. 启动 customer_hand：`uvicorn main:app --reload --port 8000`。
10. 浏览器或命令行访问 `http://127.0.0.1:8000/health`，确认服务可用。
11. 调用 `POST /api/messages`，确认返回的是 list，元素里有 `recipient_id/text/timestamp/metadata`。
12. 调用 `GET /api/knowledge/status`，确认能返回 `chunk_count/rag_backend` 等字段。
13. 调用 `GET /api/eval/rag?question=退货规则&top_k=5`，确认当前旁路接口是否可用。
14. 在 `ragenteval-main` 中执行 `python -m eval --help`，确认 CLI 能导入。
15. 在 `ragenteval-main` 中执行 `python -m eval rag run --help`，确认能看到 `--target customer_hand`。
16. 把本阶段结果写到自己的笔记里，包括 customer_hand 地址、使用的 Python 环境、是否能访问 `/api/eval/rag`。

验收标准：

- `customer_hand` 能启动。
- `/health`、`/api/messages`、`/api/knowledge/status` 能访问。
- `ragenteval-main` 的 `python -m eval rag run --help` 能显示帮助。
- 你知道 `EvalRecord` 是后续所有指标和报告的核心输入。

## 3. 阶段 1：让 customer_hand 使用比特严选知识库，18 小步

目标：让 `customer_hand` 检索 `ragenteval-main/knowledge_base` 的 120 篇 Markdown，而不是只检索自己的默认小知识库。

涉及文件：

- `customer_hand/.env`
- `customer_hand/app/settings.py`
- `customer_hand/app/rag/documents.py`
- `customer_hand/app/rag/retriever.py`
- `customer_hand/app/rag/reindex.py`
- `ragenteval-main/knowledge_base`

小步：

1. 确认 `ragenteval-main/knowledge_base` 存在。
2. 统计知识库文件数，确认大约有 120 个 `.md` 文件。
3. 打开一个样例文件，例如 `knowledge_base/01_product/detail/PROD_AIR_001.md`。
4. 观察文件顶部的 frontmatter，重点看 `doc_id`、`doc_type`、`title`。
5. 打开 `customer_hand/app/settings.py`，确认 `knowledge_dir` 支持从 `.env` 的 `KNOWLEDGE_DIR` 读取。
6. 打开 `customer_hand/.env`。
7. 增加或修改 `KNOWLEDGE_DIR=D:\code4\llm-universe-main\customer_simple\ragenteval-main\knowledge_base`。
8. 初期建议先用 `RAG_BACKEND=keyword`，因为它不需要 embedding 网络调用。
9. 设置 `RAG_TOP_K=5`，让评测先取 5 个候选。
10. 如果你只想验证检索链路，可以先设置 `LLM_ENABLED=false`。
11. 重启 `customer_hand`，因为 `.env` 是启动时读取的。
12. 调用 `GET /api/knowledge/status`，确认服务正常。
13. 调用 `GET /api/eval/rag?question=小米 14 Pro 保修期多久&top_k=5`。
14. 检查返回里的 `retrievedDocIds` 是否出现类似 `POLICY_WAR_001` 的业务 doc_id。
15. 如果 `retrievedDocIds` 为空，先检查 `KNOWLEDGE_DIR` 路径是否写错。
16. 如果 `retrievedDocIds` 有值但不准，先不要急着改模型，记录失败样本。
17. 暂时不要切 Chroma，先用 keyword 把端到端流程跑通。
18. 把本阶段的配置写进文档或笔记，方便之后复现。

验收标准：

- `customer_hand` 实际读取的是 `ragenteval-main/knowledge_base`。
- `/api/eval/rag` 能返回非空 `retrievedChunkIds`。
- 对文件名是 `PROD_*`、`POLICY_*`、`FAQ_*` 的知识库，`retrievedDocIds` 能还原出业务文档 ID。

## 4. 阶段 2：补齐 doc_id 解析和 chunk metadata，24 小步

目标：让每个 chunk 都携带稳定 metadata，不再只靠文件名猜 doc_id。

为什么要做：

- `ragenteval-main/eval/rag/metrics/retrieval.py` 会用 `retrieved_doc_ids` 计算 `hit@k/recall@k/mrr@10`。
- `ragenteval-main/eval/rag/pipeline/score.py` 会检查 `retrieved_context_doc_ids` 和 context frontmatter 里的 `doc_id` 是否一致。
- 如果 doc_id 不稳定，检索指标会失真。

涉及文件：

- `customer_hand/app/rag/documents.py`
- `customer_hand/app/rag/splitter.py`
- `customer_hand/app/rag/reindex.py`
- `customer_hand/app/rag/retriever.py`
- `customer_hand/app/rag/vector_store.py`
- `customer_hand/test/`

小步：

1. 在 `documents.py` 中新增一个 `KnowledgeDocument` dataclass。
2. 字段建议为 `source: str`、`text: str`、`metadata: dict[str, Any]`。
3. 保留现有 `KnowledgeChunk`，不要删除。
4. 给 `KnowledgeDocumentLoader` 增加一个私有方法 `_parse_frontmatter(content)`。
5. 判断 Markdown 是否以 `---` 开头。
6. 找到第二个 `---`，把中间内容当作 frontmatter。
7. 对简单的 `key: value` 先做最小解析，支持 `doc_id`、`doc_type`、`title`、`version`。
8. 对列表字段如 `related_intents`、`tags`，初期可以先转成字符串，后续再精细解析。
9. 如果没有 frontmatter，就从 `Path(source).stem` 推导 `doc_id`。
10. 修改 `load_directory()`，让它返回 `list[KnowledgeDocument]`。
11. 为了少破坏旧代码，可以新增 `load_documents()`，再让旧 `load_directory()` 做兼容。
12. 修改 `TextSplitter.split()`，增加可选参数 `metadata: dict | None = None`。
13. 在生成 `KnowledgeChunk.metadata` 时合并文档 metadata。
14. 确保每个 chunk metadata 至少有 `doc_id`、`source`、`chunk_index`、`start`、`end`。
15. 确保 `chunk_id` 里包含 doc_id 和 chunk index，例如 `PROD_AIR_001-0`。
16. 修改 `KeywordKnowledgeRetriever.build()`，让它把 document metadata 传给 splitter。
17. 修改 `load_knowledge_chunks()`，让 Chroma 重建索引时也保留 metadata。
18. 检查 `KnowledgeVectorStore.upsert()`，确认 metadata 会写入 Chroma。
19. 检查 `VectorKnowledgeRetriever._to_retrieval_match()`，确认 metadata 会从 Chroma 读回来。
20. 写一个单测：有 frontmatter 时，`doc_id` 来自 frontmatter。
21. 写一个单测：没有 frontmatter 时，`doc_id` 来自文件名。
22. 写一个单测：split 后每个 chunk 都有 `metadata["doc_id"]`。
23. 写一个单测：keyword backend 返回的 match 有 `doc_id`。
24. 如果启用 Chroma，再写一个 mock embedding 测试，确认 vector backend 也有 `doc_id`。

验收标准：

- `KnowledgeAnswerer().answer(...).matches[0]["metadata"]["doc_id"]` 有值。
- keyword 和 chroma 两条路径都能保留 doc_id。
- `retrievedDocIds` 不再依赖临时猜测，而是优先来自 chunk metadata。

## 5. 阶段 3：完善 customer_hand 评测旁路接口，21 小步

目标：把当前已有的 `/api/eval/rag` 初版加固成稳定的评测接口。

当前代码位置：

- `customer_hand/main.py` 中的 `@app.get("/api/eval/rag")`
- 当前返回 `retrievedDocIds`、`retrievedChunkIds`、`retrievedContexts`、`retrievedContextDocIds`、`intentLeafIds`、`hasKb`、`hasMcp`、`traceId`

小步：

1. 先确认 `main.py` 的 `/api/eval/rag` 能访问。
2. 保留接口路径 `GET /api/eval/rag`，不要改名。
3. 保留参数 `question`，因为 runner 已经这样调用。
4. 保留参数 `top_k`，默认可以是 5。
5. 对空 question 返回 400，当前代码已有类似逻辑。
6. 对 `top_k` 做范围限制，例如最小 1，最大 20。
7. 从 `request.app.state.kb_retriever` 获取 retriever，不要每次新建。
8. 调用 `retriever.retrieve(question, top_k=effective_top_k)`。
9. 把 `RetrievalMatch` 转为 `retrievedChunkIds`。
10. 把 `match.chunk.metadata["doc_id"]` 转为 `retrievedContextDocIds`。
11. 如果 metadata 没有 `doc_id`，再 fallback 到 `Path(source).stem`。
12. 对 `retrievedDocIds` 去重，并保持原始命中顺序。
13. 生成 `retrievedContexts` 时，把 `doc_id/source/chunk_id` 放进 frontmatter。
14. 确认 `retrievedContexts` 的顺序和 `retrievedContextDocIds` 一致。
15. 给 `hasKb` 填 `bool(matches)`。
16. 初期 `hasMcp` 可以填 `False`。
17. `traceId` 使用 `trace_id_from_request(request)`。
18. `intentLeafIds` 初期可以用规则映射，但要在注释里说明只是临时方案。
19. 增加 `metadata` 透传时要注意不要返回敏感信息。
20. 给接口增加 `test_eval_rag_api.py`。
21. 用 `TestClient` mock retriever，避免单测真的调用 embedding。

验收标准：

- `GET /api/eval/rag?question=退货规则&top_k=5` 返回 200。
- 返回 JSON 顶层是 `{"success": true, "data": ...}`。
- `data.retrievedDocIds`、`data.retrievedChunkIds`、`data.retrievedContexts` 三者长度关系合理。
- `retrievedContexts` 的 frontmatter 中能看到 `doc_id:`。

## 6. 阶段 4：完善 ragenteval 的 customer_hand runner，20 小步

目标：让 `ragenteval-main` 可以把评估集逐条发给 `customer_hand`，并生成标准 `EvalRecord`。

当前代码位置：

- `ragenteval-main/eval/rag/pipeline/customer_hand_runner.py`
- `ragenteval-main/eval/common/schemas.py`
- `ragenteval-main/eval/rag/dataset/eval_set_v1.jsonl`

小步：

1. 打开 `customer_hand_runner.py`，先读文件顶部注释。
2. 确认 `_base_url()` 从 `CUSTOMER_HAND_BASE_URL` 读取地址。
3. 确认默认地址是 `http://127.0.0.1:8000`。
4. 确认 `_post_message()` 调用的是 `POST /api/messages`。
5. 确认 sender_id 当前用的是 `sample.query_id`。
6. 为了避免多次评测污染同一个 tracker，建议 sender_id 改成 `f"eval_{run_id}_{sample.query_id}"`。
7. 或者每条样本开始前调用 `POST /api/tracker/{sender_id}/reset`。
8. 确认 `_get_eval_rag()` 调用的是 `GET /api/eval/rag`。
9. 确认 `_combine_response_text()` 会把 response list 合并成一个字符串。
10. 确认 `_build_record()` 把 `EvalSample` 字段复制到 `EvalRecord`。
11. 确认 `response` 来自 `/api/messages` 的 `text`。
12. 确认 `latency_ms` 是 POST 总耗时。
13. 确认 `first_token_ms` 初期回填为 `latency_ms`。
14. 确认 `retrieved_doc_ids` 来自旁路接口 `retrievedDocIds`。
15. 确认 `intent_pred_all` 来自旁路接口 `intentLeafIds`。
16. 把输出文件名改成 `v1_customer_hand_<ts>.jsonl`，这样更容易被现有 score/report 发现。
17. 如果暂时不改文件名，后续 score 时必须显式传 runs 文件路径。
18. 给 runner 增加 `--start` 支持，当前 `cmd_run` 已经传入了 start。
19. 暂时不做并发，先保证顺序跑通；并发可放到后续。
20. 增加 runner 单测，mock `requests.post` 和 `requests.get`，不依赖真实服务。

验收标准：

- `python -m eval rag run --target customer_hand --limit 5` 能生成 JSONL。
- 每行 JSON 都能被 `EvalRecord.from_dict()` 解析。
- 如果 `/api/eval/rag` 报错，runner 能把错误写进 `record.error`，而不是崩溃。

## 7. 阶段 5：扩展和整理 CLI，14 小步

目标：让命令形式清晰，不破坏原有 ragent 评测。

当前代码位置：

- `ragenteval-main/eval/common/cli.py`

小步：

1. 打开 `cli.py`，找到 `cmd_run()`。
2. 确认 `args.target == "customer_hand"` 时会调用 `customer_hand_runner.run()`。
3. 打开 `build_parser()`，确认 `run` 子命令有 `--target`。
4. 确认 `--target` choices 包含 `ragent` 和 `customer_hand`。
5. 确认 `all` 子命令也有 `--target`。
6. 检查 `cmd_all()`，确认 customer_hand 分支是否传了 `start`、`workers` 等参数。
7. 如果 `customer_hand_runner.run()` 不支持 `workers`，CLI 帮助里要避免误导。
8. 保持默认 target 为 `ragent`，不要影响原项目。
9. 增加命令示例：`python -m eval rag run --target customer_hand --limit 5`。
10. 增加命令示例：`python -m eval rag all --target customer_hand --limit 5 --skip-ragas`。
11. 确认 `score` 可以接收 customer_hand 的 runs 文件。
12. 如果 runner 输出名不是 `v1_*.jsonl`，在 README 中提醒要显式传文件。
13. 增加 CLI 单测，检查 parser 能解析 `--target customer_hand`。
14. 增加 CLI 单测，mock runner，确认 target 分支走对。

验收标准：

- 原命令 `python -m eval rag run --limit 5` 仍默认走 ragent。
- 新命令 `python -m eval rag run --target customer_hand --limit 5` 走 customer_hand。
- `all --target customer_hand --skip-ragas` 能一条龙跑完最小闭环。

## 8. 阶段 6：先跑自建指标，再跑 RAGAS，18 小步

目标：先用不依赖 LLM judge 的指标验证链路，再考虑成本更高的 RAGAS。

涉及文件：

- `ragenteval-main/eval/rag/pipeline/score.py`
- `ragenteval-main/eval/rag/metrics/intent.py`
- `ragenteval-main/eval/rag/metrics/retrieval.py`
- `ragenteval-main/eval/rag/metrics/behavior.py`
- `ragenteval-main/eval/rag/metrics/latency.py`
- `ragenteval-main/eval/rag/metrics/ragas_judge.py`
- `ragenteval-main/eval/rag/report/markdown.py`
- `ragenteval-main/eval/rag/report/slides.py`

小步：

1. 先启动 `customer_hand`。
2. 设置 `CUSTOMER_HAND_BASE_URL=http://127.0.0.1:8000`。
3. 在 `ragenteval-main` 执行 `python -m eval rag run --target customer_hand --limit 5`。
4. 找到生成的 runs 文件。
5. 打开 runs 文件，确认每行都有 `query_id/user_input/response/retrieved_doc_ids`。
6. 执行 `python -m eval rag score <runs_file> --skip-ragas`。
7. 检查输出是否包含 `intent_top1`。
8. 检查输出是否包含 `hit@1/hit@3/hit@5`。
9. 检查输出是否包含 `recall@5/mrr@10`。
10. 检查输出是否包含 `refusal_when_required/over_retrieval_rate`。
11. 检查输出是否包含 `ttft_p95_ms/total_p95_ms`。
12. 如果 retrieval 指标全为 0，优先检查 `retrieved_doc_ids` 是否为空。
13. 如果 `retrieved_doc_ids` 不为空但指标仍为 0，检查 doc_id 是否和 `expected_doc_ids` 对齐。
14. 执行 `python -m eval rag report <runs_file>`。
15. 检查 `eval/reports/<run>/report.md`。
16. 检查 `eval/reports/<run>/per_sample.csv`。
17. 检查 `eval/reports/<run>/failures.jsonl`。
18. 只有当前 5 条 smoke 稳定后，再考虑加 `AIHUBMIX_API_KEY` 跑 RAGAS。

验收标准：

- 不跑 RAGAS 时也能产出 `_scores.json`。
- 报告目录下有 `report.md`、`per_sample.csv`、`failures.jsonl`、`slides.html`。
- 你能从 failures 里看出失败是检索问题、回答问题、意图问题还是延迟问题。

## 9. 阶段 7：补充测试，28 小步

目标：把最容易坏的接入点都用测试保护起来。

customer_hand 侧建议新增或补强：

- `test/test_eval_rag_api.py`
- `test/test_document_metadata.py`
- `test/test_rag_retriever.py`
- `test/test_vector_rag.py`

ragenteval-main 侧建议新增：

- `test/test_customer_hand_runner.py`
- `test/test_customer_hand_mapping.py`
- `test/test_cli_target.py`

小步：

1. 在 customer_hand 中新增 `test/test_document_metadata.py`。
2. 构造一个带 frontmatter 的临时 Markdown。
3. 测试 loader 能读出 `doc_id`。
4. 测试 loader 能读出 `title`。
5. 构造一个不带 frontmatter 的临时 Markdown。
6. 测试 loader 能从文件名推导 `doc_id`。
7. 测试 splitter 能把 doc metadata 写入 chunk metadata。
8. 测试 chunk_id 包含 doc_id 或至少稳定可追踪。
9. 在 customer_hand 中新增 `test/test_eval_rag_api.py`。
10. 用 FastAPI `TestClient` 请求 `/api/eval/rag`。
11. mock retriever 返回两个 match。
12. 验证响应字段完整。
13. 验证 `retrievedDocIds` 去重但保序。
14. 验证 `retrievedContexts` 包含 `doc_id:`。
15. 验证空 question 返回 400。
16. 验证 top_k 超大时会被限制。
17. 在 ragenteval-main 中新增 `test/test_customer_hand_mapping.py`。
18. 构造一个假的 `EvalSample`。
19. 构造假的 `/api/messages` response list。
20. 构造假的 `/api/eval/rag` payload。
21. 调 `_build_record()`。
22. 验证 `record.response` 合并正确。
23. 验证 `record.retrieved_doc_ids` 映射正确。
24. 验证 `record.intent_pred` 取 `intentLeafIds[0]`。
25. 在 ragenteval-main 中新增 `test/test_customer_hand_runner.py`。
26. mock `requests.post` 和 `requests.get`，跑 `run(limit=1, out_path=tmp_path/...)`。
27. 验证输出 JSONL 可以被 `EvalRecord.from_dict()` 读回。
28. 在 ragenteval-main 中新增 CLI parser 测试，确认 `--target customer_hand` 可解析。

验收标准：

- customer_hand 的新增测试不需要真实 LLM 或 embedding。
- ragenteval-main 的新增测试不需要真实 customer_hand 服务。
- 修改接口字段时，测试能第一时间失败。

## 10. 推荐执行顺序

如果你是新手，不建议一次完成 159 步。按下面顺序更稳：

1. 先做阶段 0，确认环境和接口可用。
2. 做阶段 1，用 keyword 接上 `knowledge_base`。
3. 做阶段 3，确认 `/api/eval/rag` 字段稳定。
4. 做阶段 4，用 runner 生成 5 条 runs。
5. 做阶段 6，先 `--skip-ragas` 生成报告。
6. 回头做阶段 2，补 metadata，让指标更可靠。
7. 做阶段 7，给链路补测试。
8. 最后整理阶段 5 的 CLI 和 README。

## 11. 最小闭环命令

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
python -m eval rag run --target customer_hand --limit 5
```

评分，先跳过 RAGAS：

```cmd
python -m eval rag score <runs_file> --skip-ragas
```

生成报告：

```cmd
python -m eval rag report <runs_file>
```

## 12. 新手常见卡点

| 卡点 | 现象 | 优先检查 |
|---|---|---|
| customer_hand 没读到比特严选知识库 | `retrievedDocIds` 为空 | `KNOWLEDGE_DIR` 是否是绝对路径，服务是否重启 |
| score 后 retrieval 全 0 | Hit@K、Recall@K 都很低 | `retrieved_doc_ids` 是否和 `expected_doc_ids` 同一种 doc_id |
| runner 报 404 | `/api/eval/rag` 找不到 | customer_hand 是否是最新代码，服务是否重启 |
| report 找不到 runs | `python -m eval rag score` 找不到文件 | 显式传 `<runs_file>`，或把 runner 输出命名改成 `v1_*.jsonl` |
| RAGAS 跑不起来 | 缺 API key 或依赖 | 开发阶段先用 `--skip-ragas` |
| Chroma 重建失败 | embedding 网络或 key 问题 | 先用 `RAG_BACKEND=keyword` 跑通闭环 |
| 问商品却进售后流程 | flow 抢占闲聊 | 检查 `app/agent/graph/nodes.py` 的 route 优先级和 slot 校验 |

## 13. 每个阶段的最终交付物

| 阶段 | 交付物 |
|---|---|
| 阶段 0 | 环境确认记录，服务可启动 |
| 阶段 1 | `.env` 配置和知识库 smoke 结果 |
| 阶段 2 | metadata 解析代码和单测 |
| 阶段 3 | 稳定的 `/api/eval/rag` 旁路接口 |
| 阶段 4 | customer_hand runner 生成的 runs JSONL |
| 阶段 5 | 清晰的 CLI target 支持 |
| 阶段 6 | `_scores.json` 和报告文件 |
| 阶段 7 | 两个项目的接入测试 |

做到阶段 6，你就已经有一个可以展示的“被测客服系统 + 自动评测系统”闭环。做到阶段 7，这个闭环就更像一个工程项目，而不是一次性脚本。
