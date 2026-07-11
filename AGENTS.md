# AGENTS.md

## 项目定位

本仓库是一个基于 FastAPI、LangGraph、Hybrid RAG、Tool/Skill、Memory、Ticket 和 Trace/Eval 的垂直客服 Agent 系统。

当前目标是：

> 建设面向智能清洁设备售后场景、可供受控企业客户试点的企业级 MVP。

当前仓库仍处于从技术原型向企业级 MVP 演进的阶段。安全、身份可信、数据隔离、可测试和可回滚优先于扩展功能数量。

## 技术栈

* Python 3.11
* FastAPI
* LangGraph
* Pydantic / pydantic-settings
* SQLAlchemy / Alembic
* MySQL
* Redis
* ChromaDB / BM25 / Hybrid Retrieval
* pytest
* Docker / Docker Compose
* GitHub Actions

## 目录职责

* `main.py`：应用创建、middleware、router 和启动入口。
* `app/entry/`：认证、授权、请求归一化、限流、幂等、安全检测和 trace 注入。
* `app/api/`：API routes 和请求响应 schema。
* `app/agent/graph/`：LangGraph 状态、节点、路由和响应流程。
* `app/rag/`：知识加载、索引、检索、rerank 和引用。
* `app/tools/`、`app/skills/`：工具 schema、权限、执行和错误处理。
* `app/tickets/`：工单领域逻辑。
* `app/persistence/`：ORM、Repository、Migration 和 Trace/Eval Recorder。
* `app/memory/`：会话记忆、摘要和 query rewrite。
* `scripts/`：评测、报告和一次性维护脚本。
* `docs/`：架构、安全、运维和企业级 MVP 文档。
* `data/eval/`：评测数据，禁止放入真实客户 PII。

## 必须遵守的安全规则

1. Principal 必须来自服务端认证结果。
2. 客户端提交的 sender、tenant、owner、role 和 scope 均不可信。
3. 普通用户的 sender 必须从 Principal 派生，或与 Principal 做一致性校验。
4. Tracker、Memory、Ticket、Trace 等资源必须执行服务端资源级授权。
5. 无法确认 owner 或 tenant 时必须 fail-closed。
6. 管理员不得因为拥有 admin 角色而自动获得跨 tenant 权限。
7. Repository 的企业资源查询必须包含可信 tenant scope。
8. LLM、Prompt 和 Tool 参数不能决定权限结果。
9. 密码、Token、API Key、认证头和未经处理的 PII 不得进入日志或 Trace。
10. 工单等写操作必须考虑权限、明确确认、业务幂等和超时后结果收敛。
11. 写操作默认不得自动重试。
12. 所有外部调用必须有明确 timeout。

## 开发规则

1. 先读代码，再给方案。
2. 每次只完成一个可独立测试、审查和回滚的任务。
3. 不做与当前任务无关的重构。
4. 保持现有 API 兼容，除非任务明确要求安全性变更。
5. 安全修复优先于不安全的向后兼容。
6. 数据库结构变更必须提供 Alembic migration。
7. Migration 优先采用 expand、backfill、validate、contract。
8. 业务逻辑变更必须增加 pytest。
9. 入口层变更必须检查认证、授权、tenant、限流、幂等和统一异常。
10. 工具必须具备 Pydantic schema、权限、风险等级、timeout、错误返回、Trace 和测试。
11. 不得写入真实密钥或真实客户数据。
12. 不得删除、覆盖或格式化用户的无关改动。
13. 不得执行 Git commit、push、force push 或历史重写，除非用户明确要求。
14. 测试结果和指标必须来自实际命令，不得编造。

## 测试规则

1. pytest 默认不得读取开发环境的真实 `.env`。
2. 测试默认不得连接真实 MySQL、Redis、LLM、Chroma 或业务系统。
3. 集成测试必须有明确 marker，并在获得授权后执行。
4. 测试至少覆盖正常路径、未认证、无权限、跨用户、跨 tenant、边界输入和依赖异常。
5. 未执行的测试不得描述为通过。
6. 不得通过删除断言、降低安全要求或修改 expected 数据规避失败。

## 命令边界

默认可以执行低风险命令：

```bash
git status --short --branch
git diff --stat
git diff
git log -5 --oneline
python -m compileall app main.py scripts test
pytest -q <与当前任务直接相关的测试>
```

执行测试前，必须确认不会连接真实环境。

未经用户明确授权，不得执行：

```bash
alembic upgrade head
alembic downgrade
docker compose up
docker compose down
docker compose down -v
pytest -q
任何索引重建、数据回填、删除或外部系统调用
git commit
git push
```

禁止执行：

```bash
git reset --hard
git clean -fd
git push --force
```

## 当前实施顺序

当前优先完成阶段 0：

1. S0-01：Tracker 完整读取鉴权。
2. S0-02：sender 与 authenticated Principal 绑定。
3. S0-03：最小 tenant/owner 授权边界。
4. S0-04：pytest 与开发 `.env` 隔离。
5. S0-05：Memory 和 Trace 故障隔离。

阶段 0 未完成前，不优先实施 Planner、Reviewer、完整 tenant migration 或大型架构重构。

完整路线图以 `docs/enterprise_mvp_roadmap.md` 为准。

## Codex 工作方式

开始任务前先输出：

1. 需要阅读的文件。
2. 当前调用链和代码证据。
3. 准备修改的文件。
4. 最小修改方案。
5. 安全与兼容性风险。
6. 测试计划。
7. 验收标准。
8. 回滚方案。

如果用户只要求分析或规划，不得修改代码。

用户明确要求“开始修改”“实施任务”“修复问题”或“完成分析后直接实施”时，可以在分析后直接修改，不必重复请求确认。

## 完成任务后的输出

每次实施后必须说明：

* 修改摘要
* 修改文件及原因
* 关键设计决策
* 实际执行的命令和退出码
* 测试通过、失败和跳过数量
* API 和数据兼容性影响
* 未验证事项
* 后续问题
* 回滚步骤

不要自动开始下一个任务。
