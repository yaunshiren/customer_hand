# RAG 设计说明（customer_hand）

## 1. 目标

在电商客服场景下，对用户**知识类问题**（退货规则、到账时间等）给出带依据的回答，并在接口 `metadata` 中返回召回片段，便于排查幻觉与演示「可解释 RAG」。

## 2. 当前实现形态：检索 + 生成

实现入口：`app/rag/answerer.py` 中的 `KnowledgeAnswerer`（**对外接口不变**）。

1. **文档加载**：`KnowledgeDocumentLoader` 从 `settings.knowledge_dir`（默认 `data/knowledge`）读取 `.md` / `.txt`。
2. **切分**：`TextSplitter` 将长文档切成带 `chunk_id` 的片段。
3. **索引与检索**（由 `RAG_BACKEND` 切换）：
   - `keyword`：`SimpleKeywordIndex` 关键词匹配，`score` 为命中次数（整数）。
   - `chroma`：`EmbeddingClient` + `KnowledgeVectorStore` + `VectorKnowledgeRetriever`，`score` 为 **0～1 相似度**（越大越相似）。
4. **生成**（可选）：命中片段后，由 `LLMClient` 基于片段生成回答；无命中或 LLM 失败时有固定兜底。

重建向量索引：`rebuild_index()` 或 `POST /api/knowledge/reindex`（仅 `chroma` 模式）。

## 3. 触发条件

Agent 在解析 LLM 命令后，若存在 `knowledge_answer` 类型命令，会抽取查询文本并调用 `KnowledgeAnswerer.answer(query, top_k=3)`。详见 `app/agent/agent.py` 中 `_has_command_type` 与 `knowledge_answer` 分支。

在 **`LLM_ENABLED=false`** 时，命令生成器不工作，一般不会自动进入该分支；规则路径仍可走售后/物流 Flow。开启 LLM 后，模型可按 `CommandPromptBuilder` 中的规则输出 `knowledge_answer`。

## 4. 接口侧可观察行为

成功走 RAG 时，单条回复的 `metadata` 大致包含：

- `source`: `"rag"`
- `matches`: 列表项含 `chunk_id`、`source`、`score`、`text`、`metadata`、`rag_backend`
- `used_llm`: 是否实际调用了 LLM 做归纳

`KnowledgeAnswerer.answer()` 返回字段保持稳定：`answer`、`matches`、`used_llm`（成功调 LLM 时可有 `llm_result`）。

## 5. 双后端对比

| 维度 | `keyword` | `chroma` |
|------|-----------|----------|
| 召回机制 | 词面 / 二元组匹配 | embedding + Chroma cosine |
| `score` 含义 | 命中 token 次数（如 `3`） | 相似度 `1 - distance`（如 `0.71`） |
| 索引 | 内存，启动时 build | 持久化 `data/chroma`，需 `rebuild_index` |
| 每次提问 | 不耗 embedding Token | 仅 `embed_query` 耗 Token |

## 6. 调参指南（第 7 步）

### `RAG_BACKEND`

- 开发 / CI 默认可 `keyword`（无 API）。
- 语义问答：`chroma`，改后需 **重建索引** 并重启服务。

### `RAG_SCORE_THRESHOLD`（仅 chroma）

- 向量 `score` 与关键词 **不是同一刻度**，必须用真实问句在 Swagger / `test_vector_retrieve.py` 试。
- 过高 → `matches` 为空 → 兜底「暂时没有找到相关知识」。
- 建议：从 `0.45` 起，无命中则降到 `0.35`～`0.4`；误召回多则略升高。

### `RAG_TOP_K`

- 默认 `3`；增大提高召回率，但 prompt 更长、噪声更多。

### `TextSplitter`（`chunk_size` / `chunk_overlap`）

- 默认 `400` / `80`；短 FAQ 可能整篇 1 chunk，检索会带回全文。
- 效果不好时：减小 `chunk_size`，或按 Markdown `##` 切节（改代码后 **必须** `rebuild_index`）。

### `EMBEDDING_DIMENSIONS` / `EMBEDDING_MODEL`

- 与建索引、查询 **必须一致**。
- 修改后：**删除 `data/chroma` 或 `reset` + `rebuild_index()`**，否则维度不匹配会报错或结果异常。

### 何时重建索引

| 需要 | 不需要 |
|------|--------|
| 知识文件增删改 | 普通问答 |
| 切分策略变更 | 重启 uvicorn |
| 换 embedding 模型/维度 | 同一索引反复查询 |

## 7. 测试

- **CI（默认）**：`pytest -q`，向量相关用 `FakeEmbeddingClient` mock，不调 API。
- **集成（可选）**：

```cmd
set RUN_EMBEDDING_INTEGRATION=1
pytest test/test_vector_rag.py -m integration -v
```

需 `.env` 中 `EMBEDDING_ENABLED=true` 且有效 `DASHSCOPE_API_KEY`。

## 8. 相关文件

- `app/rag/documents.py` — 文档与 chunk 模型  
- `app/rag/splitter.py` — 切分策略  
- `app/rag/indexer.py` — 关键词索引  
- `app/rag/embedding.py` — 百炼 embedding API  
- `app/rag/vector_store.py` — Chroma 持久化  
- `app/rag/vector_retriever.py` — 向量检索  
- `app/rag/reindex.py` — 全量建索引  
- `app/rag/retriever.py` — `KnowledgeBaseRetriever` 门面（按 backend 切换）  
- `test/test_vector_rag.py` — 向量 RAG 测试集  
- `data/knowledge/shop_faq.md` — 示例知识  
