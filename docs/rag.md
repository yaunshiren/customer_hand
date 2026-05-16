# RAG 设计说明（customer_hand）

## 1. 目标

在电商客服场景下，对用户**知识类问题**（退货规则、到账时间等）给出带依据的回答，并在接口 `metadata` 中返回召回片段，便于排查幻觉与演示「可解释 RAG」。

## 2. 当前实现形态：检索 + 生成

实现入口：`app/rag/answerer.py` 中的 `KnowledgeAnswerer`。

1. **文档加载**：`KnowledgeDocumentLoader` 从 `settings.knowledge_dir`（默认 `data/knowledge`）读取 `.md` / `.txt`。
2. **切分**：`TextSplitter` 将长文档切成带 `chunk_id` 的片段。
3. **索引与检索**：`SimpleKeywordIndex`（`app/rag/indexer.py`）基于关键词匹配打分，**非向量嵌入**。
4. **生成**（可选）：命中片段后，由 `LLMClient.generate_json` 在严格 system prompt 下基于片段生成回答；若 LLM 不可用或失败，返回规则兜底文案，并仍返回 `matches` 供前端或调试使用。

## 3. 触发条件

Agent 在解析 LLM 命令后，若存在 `knowledge_answer` 类型命令，会抽取查询文本并调用 `KnowledgeAnswerer.answer(query, top_k=3)`。详见 `app/agent/agent.py` 中 `_has_command_type` 与 `knowledge_answer` 分支。

在 **`LLM_ENABLED=false`** 时，命令生成器不工作，一般不会自动进入该分支；规则路径仍可走售后/物流 Flow。开启 LLM 后，模型可按 `CommandPromptBuilder` 中的规则输出 `knowledge_answer`。

## 4. 接口侧可观察行为

成功走 RAG 时，单条回复的 `metadata` 大致包含：

- `source`: `"rag"`
- `matches`: 列表项含 `chunk_id`、`source`、`score`、`text`
- `used_llm`: 是否实际调用了 LLM 做归纳

## 5. 与「向量 RAG」的差异（面试常问）

| 维度 | 当前关键词 RAG | 典型向量 RAG |
|------|------------------|----------------|
| 召回机制 | 词面匹配 | embedding + ANN |
| 依赖 | 低，易本地跑 | 需模型与向量库 |
| 语义泛化 | 弱 | 强 |
| 适用阶段 | MVP / 教学演示 | 生产语义问答 |

演进路线：保留 `KnowledgeAnswerer` 接口，将 `KnowledgeBaseRetriever` 内部替换为 embedding + Chroma/Milvus 等，上层 Agent 改动最小。

## 6. 调参与排错

- **top_k**：默认 3；增大可提升召回率，噪声与 prompt 长度同步增加。
- **无命中**：返回固定兜底句，`matches` 为空。
- **有命中但 LLM 失败**：`_fallback_answer` 提示用户参考来源文件名，体现降级策略。

## 7. 相关文件

- `app/rag/documents.py` — 文档与 chunk 模型  
- `app/rag/splitter.py` — 切分策略  
- `app/rag/indexer.py` — 索引与搜索  
- `app/rag/retriever.py` — `KnowledgeBaseRetriever` 门面  
- `data/knowledge/shop_faq.md` — 示例知识  
