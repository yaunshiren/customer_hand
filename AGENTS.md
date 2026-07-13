# AGENTS.md

## 项目与目标

本仓库是基于 FastAPI、LangGraph、Hybrid RAG、Tool/Skill、Memory、Ticket 和 Trace/Eval 的智能清洁设备售后 Agent。

目标：

> 建设可供受控企业客户试点的垂直客服 Agent MVP。

优先级：身份可信与数据隔离 → 可测试与可回滚 → 垂直 Agent 效果 → 可靠性与运维 → 功能数量。

主要边界：

- `app/entry/`：认证、授权、归一化、限流和幂等
- `app/agent/graph/`：LangGraph 状态、节点和路由
- `app/rag/`：知识加载、检索、rerank 和引用
- `app/tools/`、`app/skills/`：业务 Tool 和 Agent Skill
- `app/memory/`、`app/tickets/`、`app/persistence/`：状态、工单和持久化
- `data/eval/`：合成评测数据，禁止真实客户 PII

## 安全不变量

1. Principal 只能来自服务端认证结果。
2. 客户端的 sender、tenant、owner、role 和 scope 均不可信。
3. 普通用户的 sender 必须从 Principal 派生，或与其严格一致。
4. Tracker、Memory、Ticket 和 Trace 必须执行资源级授权。
5. 无法确认 tenant 或 owner 时必须 fail-closed。
6. tenant admin 不得自动获得跨 tenant 权限。
7. 企业资源查询必须包含可信 tenant scope。
8. LLM、Prompt 和 Tool 参数不能决定身份、权限或租户边界。
9. 密钥、认证头和未经处理的 PII 不得进入日志或 Trace。
10. 写操作必须考虑授权、确认、业务幂等、timeout 和结果收敛；默认不得自动重试。
11. 依赖降级不得造成跨用户或跨 tenant 的状态回退。

## 开发与测试

1. 先读代码和调用链，再提出方案。
2. 每次只完成一个可独立测试、审查和回滚的任务。
3. 不做无关重构，不自动扩大范围或开始下一任务。
4. 保持 API 兼容；安全修复可以改变不安全行为。
5. 数据库结构变更必须提供 Alembic migration。
6. 业务行为变更必须增加或更新 pytest。
7. 不得删除断言、降低安全要求或修改 expected 数据来规避失败。
8. 不得写入真实密钥、Token 或客户数据。
9. 不得删除、覆盖或格式化用户的无关改动。
10. 测试结果、指标和命令输出必须来自实际执行。
11. pytest 默认不得读取开发 `.env`。
12. 普通测试不得连接真实 MySQL、Redis、LLM、Embedding、Chroma 或业务 Provider。
13. 集成测试必须有 marker 并显式启用。
14. fake、mock 和 spy 不得绕过任务需要证明的核心行为。
15. 未执行的测试不得描述为通过。
16. 未经明确要求，不执行 commit、push、merge 或历史重写。

## 命令边界

默认允许：

```bash
git status --short --branch
git diff --stat
git diff
git diff --check
git log -5 --oneline
python -m compileall <与任务相关的路径>
pytest -q <与当前任务直接相关的测试>
```

执行测试前必须确认不会连接开发或生产环境。

未经明确授权，不得执行：

```bash
pytest -q
alembic upgrade head
alembic downgrade
docker compose up
docker compose down
docker compose down -v
索引重建
数据迁移、回填或删除
真实外部 Provider 调用
git commit
git push
```

禁止执行：

```bash
git reset --hard
git clean -fd
git push --force
```

## 工作模式

### Analysis Mode

用户要求分析、解释、规划或审查时，只读取和分析，不修改文件；说明调用链、证据、风险和可选方案，并区分已实现、计划和未验证事项。

### Learning Mode

用户要求教学、结对编程、面试准备、逐步学习，或表示不理解时：

- 使用 `.agents/skills/learning-pair-programming/SKILL.md`
- 不直接完成整个任务
- 先让用户描述问题并提出初步方案
- 优先使用问题、提示、伪代码和小练习
- 将实现拆成小步骤，每一步后停止并做理解检查
- 目标是让用户能够解释、审查、调试并独立复现核心思想

除非用户明确结束 Learning Mode 并要求完整实施，否则不得一次性交付完整功能。

### Implementation Mode

只有用户明确要求实施已确认方案时才修改代码。

实施前说明：调用链与证据、修改文件、最小方案、安全与兼容风险、测试计划、验收和回滚方式。

每次只实施一个约定步骤，完成后停止等待审查。

## Skill 规则

- 全局规则以本文件为准。
- 专项任务使用 `.agents/skills/<skill-name>/SKILL.md`。
- Learning Mode 可与专项 Skill 同时启用。
- 规则冲突时遵循更严格规则。
- Skill 不得削弱安全、测试、命令或 Git 限制。

## 当前状态

S0-01～S0-04 已完成。接下来先复盘并掌握已有改造，再进行 S0-05 最小故障隔离和 S1 垂直 Agent 主线。

完整路线图以 `docs/enterprise_mvp_roadmap.md` 为准；与实现冲突时，以代码和测试证据为准。

## 完成报告

实施结束后说明：

- 修改内容、文件和关键设计
- 实际命令、退出码和测试统计
- API、数据和配置兼容性影响
- 未验证事项
- 回滚方法

不要自动开始下一任务。
