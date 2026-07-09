# AGENTS.md

## 项目定位

本仓库是一个基于 **FastAPI + LangGraph** 的垂直客服 Agent 运行与评测系统。项目目标不是普通 FAQ Bot，而是面向真实客服业务流程，强调：

- Agent 编排与状态流转
- RAG 知识库问答
- Tool Calling / Tool Schema
- 生产化入口治理：鉴权、权限、限流、幂等、安全检测、trace 注入
- 执行轨迹：agent_trace / retrieval_trace / tool_trace
- 自动化评测、badcase 归因与 Prompt / Tool Schema 迭代
- 后端工程规范：数据库迁移、测试、Docker、文档、CI

## 技术栈

- Python 3.11
- FastAPI
- LangGraph
- Pydantic / pydantic-settings
- SQLAlchemy / Alembic
- MySQL
- Redis，后续生产化改造目标
- ChromaDB / BM25 / Hybrid Retrieval
- pytest
- Docker / docker compose

## 目录职责约定

- `main.py`：只保留应用创建、middleware 注册、router 注册和启动入口。不要继续堆业务逻辑。
- `app/entry/`：入口治理层，包括请求归一化、鉴权、权限、限流、幂等、安全检测、trace 注入。
- `app/agent/graph/`：LangGraph Agent 编排层，包括节点、状态、路由、RAG、工具调用、响应生成。
- `app/rag/`：知识库加载、切分、索引、检索、rerank、引用和 retrieval trace。
- `app/tools/`：业务工具 / Agent Skill 的 schema、service、调用结果、异常处理。
- `app/tickets/`：工单领域模型与业务服务，不要把领域逻辑写死在工具 handler 中。
- `app/persistence/`：数据库连接、ORM model、repository、trace/eval recorder。
- `app/memory/`：会话记忆、摘要、query rewrite。
- `scripts/`：一次性脚本、评测脚本、报告生成脚本。脚本文件不要命名为 `test_*.py`。
- `docs/`：架构、入口治理、Agent 流程、Prompt、Skills、Eval、Badcase 文档。
- `reports/`：评测报告、badcase 导出、Codex handoff。
- `data/eval/`：评测集 jsonl。

## 开发原则

1. 先读代码，再给方案，不要直接大规模修改。
2. 每次只完成一个小任务，不做无关重构。
3. 保持现有 API 行为兼容，除非任务明确要求破坏性变更。
4. 涉及数据库表结构变更必须补 Alembic migration。
5. 涉及业务逻辑必须补 pytest。
6. 涉及入口层必须考虑 trace、权限、限流、幂等、安全和统一异常返回。
7. 涉及 Agent 链路必须保留 agent_trace、retrieval_trace、tool_trace。
8. 涉及工具调用必须定义 Pydantic schema、风险等级、错误返回、trace 与测试。
9. 不允许把真实密钥写入代码、测试、README 或文档。
10. 不要删除已有功能，除非用户明确要求。
11. 生成指标时必须来自脚本或测试输出，不要凭空编造。
12. 修改后必须说明改了哪些文件、为什么改、如何测试。

## 常用命令

```bash
python -m compileall app main.py scripts test
pytest -q
alembic upgrade head
docker compose up --build
```

如果依赖不完整，应先指出缺失依赖，不要绕过测试。

## 当前生产化改造优先级

P0：
- 修复依赖与 pytest 收集范围
- 清理根目录临时调试文件
- 拆分 `main.py`
- 补全 `docs/`

P1：
- 工单从 mock 改为 MySQL 持久化
- Redis 化幂等与限流
- JWT / API Key 鉴权替代 dev token
- 自动化评测与 badcase 报告自包含

P2：
- OpenTelemetry / metrics
- Docker 启动自动迁移
- GitHub Actions CI
- Agent improvement loop：trace → badcase → eval → codex_handoff → fix → rerun eval

## Codex 工作方式

开始任何任务前，先输出：

1. 需要阅读的文件
2. 对现状的理解
3. 修改方案
4. 风险点
5. 验收标准

除非用户明确说“开始修改”，否则不要直接改代码。
