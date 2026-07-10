# customer_hand

基于 **FastAPI** 的学习型 **LLM 智能客服后端**。项目围绕电商客服场景，覆盖生产入口层、会话追踪、意图识别、YAML Flow、可注册 Action、工具调用、工单、RAG 知识问答、会话记忆、链路 trace、评测与持久化等能力。

更完整的设计说明见 `docs/`：

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 分层职责、请求生命周期、与开发计划映射 |
| [docs/prompt.md](docs/prompt.md) | 命令式 Prompt 与 RAG Prompt 分工 |
| [docs/rag.md](docs/rag.md) | 文档加载、切分、检索、生成与演进方向 |
| [docs/skills_design.md](docs/skills_design.md) | Skill Runtime、工单 Skill 策略与兼容边界 |
| [docs/interview_qna.md](docs/interview_qna.md) | 高频面试问答与简历表达 |

总体规划见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)。

---

## 功能概览

- **HTTP API**：健康检查、消息入口、会话查看/重置、RAG 评测、知识库状态与重建、Swagger 文档、调试页。
- **入口治理**：请求标准化、开发 token 鉴权、角色校验、限流、幂等、安全降级、统一错误响应和 `X-Trace-Id`。
- **Agent 编排**：基于 LangGraph 风格节点串联理解、路由、RAG、工具、工单、Flow、记忆和响应生成。
- **LLM**：支持 OpenAI 兼容接口，例如阿里云百炼；`LLM_ENABLED=false` 时可依赖规则、Flow 与兜底逻辑做确定性演示。
- **RAG**：支持 `keyword`、`chroma`、`hybrid` 三种后端；`.env.example` 默认使用 Chroma 向量检索。
- **业务能力**：售后/物流流程、模拟业务工具、工单流转、意图树、会话摘要和查询改写。
- **Skill Runtime**：统一 Skill 注册、Pydantic v2 输入输出校验、角色/风险/幂等要求、超时重试、标准错误和脱敏 tool trace；首批迁移工单创建与状态查询。
- **自动化 Eval**：真实调用 `/api/messages`，用响应头 `X-Trace-Id` 关联三类 trace，生成确定性指标、badcase 和 Codex handoff。
- **观测与评测**：结构化日志、trace 记录、检索记录、工具调用记录、RAG 评测接口、MySQL/SQLAlchemy/Alembic 持久化。

---

## 目录结构

```text
customer_hand/
  main.py                 FastAPI 应用入口与路由注册
  DEVELOPMENT_PLAN.md     分阶段开发计划
  docs/                   架构、RAG、Prompt、评测、生产入口层等文档
  app/
    api/                  响应模型、异常处理、inspect 页面模板
    entry/                入口鉴权、限流、幂等、标准化、安全检查
    eval/                 Eval 契约、trace evidence、指标、badcase 与报告
    agent/                Agent 主流程与 graph 节点
    intent/               意图 taxonomy、分类、策略与 Prompt
    actions/              Action 注册与内置动作
    skills/               Skill 定义、注册、执行、上下文和 trace 脱敏
    tools/                业务工具 schema、服务与 mock store
    tickets/              工单模型、分类、路由、服务与存储
    memory/               会话记忆、实体抽取、摘要、查询改写
    rag/                  文档、切分、关键词/向量/混合检索、引用与回答
    persistence/          trace、eval、retrieval、tool 记录与数据库模型
    core/                 Tracker、Flow 加载、日志、trace、异常
    dialogue/             LLM 命令生成/解析与 Flow 执行
    llm/                  OpenAI 兼容客户端与 Prompt 构建
    utils/                遥测等工具
  data/
    flows/                业务流程 YAML
    intents/              客服意图配置
    knowledge/            RAG 知识文档与产品/政策/FAQ 资料
    eval/                 Agent 回归评测 JSONL 数据集
  scripts/                评测、索引、演示脚本
  test/                   pytest 用例
  reports/                本地生成报告（仅 README 被 Git 跟踪）
  alembic/                持久化表结构迁移
  docker-compose.yml      API + MySQL 本地容器编排
  requirements.txt
  .env.example
```

---

## 环境准备

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\customer_hand
conda activate customer
pip install -r requirements.txt
```

复制环境变量示例：

```cmd
copy .env.example .env
```

**不要**将真实 API Key 写入代码、README 或提交到 Git。密钥请放在 `.env` 或系统环境变量中。

如果本地环境提示缺少 `pydantic_settings`，先安装：

```cmd
pip install pydantic-settings
```

---

## 常用配置

| 变量 | 说明 |
|------|------|
| `APP_ENV` | `development` 默认允许匿名开发请求；`production` 要求鉴权 |
| `DASHSCOPE_API_KEY` / `BAILIAN_API_KEY` / `OPENAI_API_KEY` | OpenAI 兼容接口密钥 |
| `DASHSCOPE_BASE_URL` / `BAILIAN_BASE_URL` | OpenAI 兼容接口地址 |
| `QWEN_MODEL` / `BAILIAN_MODEL` | 对话模型名，例如 `qwen-plus` |
| `LLM_ENABLED` | 是否启用真实 LLM 调用 |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | LLM 与 embedding 请求超时和重试 |
| `RAG_BACKEND` | `keyword`、`chroma` 或 `hybrid`；无 `.env` 时代码默认 `keyword` |
| `KNOWLEDGE_DIR` | 知识库目录，默认 `data/knowledge` |
| `CHROMA_PERSIST_DIR` | Chroma 向量库目录，默认 `data/chroma` |
| `EMBEDDING_ENABLED` | 是否允许调用 embedding；Chroma/hybrid 查询和重建索引需要它 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | 远程向量模型与维度 |
| `TRACE_DB_URL` | 本地 Python 进程连接 MySQL 的 SQLAlchemy URL |
| `TRACE_DB_DOCKER_URL` | Docker Compose 中 API 容器连接 MySQL 的 URL |
| `MEMORY_*` | 会话记忆最近轮次、摘要开关与摘要阈值 |

完全离线演示时，建议设置：

```env
LLM_ENABLED=false
RAG_BACKEND=keyword
```

如果使用 `.env.example` 默认的 `RAG_BACKEND=chroma`，知识检索会依赖 Chroma 索引；查询或重建索引可能触发 embedding 调用。

---

## 启动

本地开发：

```cmd
uvicorn main:app --reload
```

模块方式：

```cmd
python main.py
```

启动后访问：

- Swagger：`http://127.0.0.1:8000/docs`
- 调试页：`http://127.0.0.1:8000/inspect`
- 健康检查：`http://127.0.0.1:8000/health`

### Docker 启动

```cmd
copy .env.example .env
docker compose up --build
```

当前 `docker-compose.yml` 会启动两个服务：

- `api`：FastAPI 服务，监听宿主机 `8000`。
- `mysql`：trace/eval/tool/retrieval 等持久化数据使用的 MySQL 8.0，宿主机端口默认 `3307`。

`./data` 会挂载到容器内 `/app/data`，用于知识库、索引和业务数据。API 容器会通过 `TRACE_DB_DOCKER_URL` 连接 compose 内的 MySQL。

工单默认持久化到同一个 MySQL：

```env
TICKET_STORE_BACKEND=mysql
```

仅本地演示或单元测试可显式设为 `memory`。MySQL 模式下，`ticket.id` 是数据库内部
主键，`ticket_id` 是兼容 Agent 的稳定系统 ID，`ticket_no` 是返回给用户并供
`query_ticket_status` 查询的业务工单号。部署新版本前需执行 `alembic upgrade head`。

多实例或准生产部署应把入口幂等切换为共享 Redis：

```env
IDEMPOTENCY_BACKEND=redis
IDEMPOTENCY_TTL_SECONDS=86400
REDIS_URL=redis://127.0.0.1:6379/0
```

本地 Python 进程通过宿主机映射访问 `redis://127.0.0.1:6379/0`；如果 API 和名为
`redis` 的 Redis 服务运行在同一个 Docker Compose 网络内，则使用
`redis://redis:6379/0`。当前 compose 文件不新增 Redis 服务，需要部署环境自行提供。

本地 pytest 会在 settings 初始化前强制使用 `memory`，不依赖 Redis。memory 后端只适合
单进程测试或演示，不适合多实例生产部署。配置为 redis 后若 Redis 不可用，入口会
fail-closed 返回 `503 idempotency_backend_unavailable`，不会静默降级到进程内存。
`REDIS_URL` 若包含密码，只能放在本地环境变量或部署平台 Secret 中，不要提交到仓库。

多实例部署还应启用 Redis 分布式限流：

```env
RATE_LIMIT_BACKEND=redis
RATE_LIMIT_KEY_PREFIX=customer_hand:rate_limit:v1
RATE_LIMIT_CHAT_CAPACITY=30
RATE_LIMIT_CHAT_WINDOW_SECONDS=60
RATE_LIMIT_TOOL_CAPACITY=5
RATE_LIMIT_TOOL_WINDOW_SECONDS=60
RATE_LIMIT_RAG_EVAL_CAPACITY=10
RATE_LIMIT_RAG_EVAL_WINDOW_SECONDS=60
RATE_LIMIT_ADMIN_REINDEX_CAPACITY=1
RATE_LIMIT_ADMIN_REINDEX_WINDOW_SECONDS=3600
```

限流复用 `REDIS_URL`：本机 Python 使用 `redis://127.0.0.1:6379/0`，Compose 网络内
使用 `redis://redis:6379/0`。不要使用其他项目占用的 6380。Redis 限流后端不可用时
返回 `503 rate_limit_backend_unavailable`，不会回退到进程内 memory。

真实 Redis 冒烟测试默认跳过；显式执行方式：

```powershell
$env:RUN_REDIS_INTEGRATION="1"
pytest -q test/test_redis_idempotency_integration.py test/test_redis_rate_limiter_integration.py
```

---

## API 快速验证

### 健康检查

```cmd
curl http://127.0.0.1:8000/health
```

### 发送消息

`/api/messages` 需要 `user`、`evaluator` 或 `admin` API Key。下面使用
`.env.example` 中的 demo user key：

```cmd
curl -X POST http://127.0.0.1:8000/api/messages ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer demo-user-key" ^
  -d "{\"sender_id\":\"user_001\",\"message\":\"我要退货\"}"
```

也可以使用 `X-API-Key`：

```cmd
curl -X POST http://127.0.0.1:8000/api/messages ^
  -H "Content-Type: application/json" ^
  -H "X-API-Key: demo-user-key" ^
  -d "{\"sender_id\":\"user_001\",\"message\":\"查物流\",\"conversation_id\":\"conv_001\"}"
```

返回为列表，元素包含 `recipient_id`、`text`、`timestamp`、`metadata`。`metadata` 中可能包含路由、意图、RAG matches、工具 trace、记忆快照等信息。

### 查看 / 重置会话

查看会话：

```cmd
curl http://127.0.0.1:8000/api/tracker/user_001/full
```

重置会话需要管理员或本人身份：

```cmd
curl -X POST http://127.0.0.1:8000/api/tracker/user_001/reset ^
  -H "Authorization: Bearer demo-user-key"
```

重置后再次查询可能返回 `404`，错误响应会带 `trace_id`。

### RAG 评测

`/api/eval/rag` 需要 `evaluator` 或 `admin` 角色：

```cmd
curl "http://127.0.0.1:8000/api/eval/rag?question=退货规则&top_k=5" ^
  -H "Authorization: Bearer demo-evaluator-key"
```

### 知识库状态与重建

查看知识库状态：

```cmd
curl http://127.0.0.1:8000/api/knowledge/status
```

重建 Chroma 向量索引需要 `RAG_BACKEND=chroma`，并且请求者需要 `admin` 角色：

```cmd
curl -X POST http://127.0.0.1:8000/api/knowledge/reindex ^
  -H "Authorization: Bearer demo-admin-key" ^
  -H "Idempotency-Key: reindex-20260709-001"
```

---

## 鉴权与权限

API Key 在 `.env` 中映射为 Principal：

```text
API_KEY_PRINCIPALS={"demo-user-key":{"principal_id":"user_001","tenant_id":"tenant_demo","roles":["user"]}}
```

不要把真实 API Key 提交到仓库。服务优先读取
`Authorization: Bearer <api_key>`，没有 Authorization 时再读取 `X-API-Key`。

常见角色：

- `user`：普通用户，可发送消息，可重置自己的 tracker。
- `evaluator`：可访问 RAG 评测接口。
- `admin`：可执行管理员操作，例如知识库重建，也可重置任意 tracker。

开发 token `Bearer dev:{user_id}:{tenant_id}:{roles}` 仅作为旧调用兼容，
要求 `AUTH_ALLOW_DEV_TOKENS=true`，并且在生产环境中始终禁用。受保护接口缺少
或使用无效 API Key 时返回 `401`。

---

## RAG 后端

| 后端 | 配置 | 说明 |
|------|------|------|
| 关键词检索 | `RAG_BACKEND=keyword` | 加载 `data/knowledge` 后建立内存关键词索引，适合离线演示 |
| 向量检索 | `RAG_BACKEND=chroma` | 使用 Chroma 持久化索引，查询前需有索引数据 |
| 混合检索 | `RAG_BACKEND=hybrid` | 组合关键词/BM25/向量通道并融合排序 |

使用向量检索时，`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS` 与建索引时必须保持一致。

---

## 测试

```cmd
pytest -q
```

或指定文件：

```cmd
pytest test/test_api_basic.py -v
```

---

## Agent Eval 与 Badcase 闭环

先验证数据集；该命令不需要 API、MySQL、Redis 或外部 eval 包：

```cmd
python scripts/run_agent_eval.py --validate-only
```

真实运行必须先启动 API，并确保 API 和 runner 使用同一个可访问的 trace MySQL。
API Key 只能通过环境变量提供，不支持命令行参数：

```cmd
set EVAL_API_KEY=demo-user-key
python scripts/run_agent_eval.py --base-url http://127.0.0.1:8000
```

建议基准回归使用 `LLM_ENABLED=false`、`RAG_BACKEND=keyword`，减少模型与向量服务波动。
runner 会真实调用 `/api/messages`，以响应头 `X-Trace-Id` 查询 `agent_trace`、
`retrieval_trace` 和 `tool_trace`。API、trace MySQL、API Key 或必要 trace 不完整时，
runner 会退出且不生成本次报告。写操作 case 会使用独立 sender、conversation 和
`Idempotency-Key`，并在报告中标记 `writes_state=true`。

成功运行后生成：

- `reports/eval_report.md`
- `reports/eval_report.json`
- `reports/badcases.jsonl`
- `reports/codex_handoff.md`

真实报告默认不提交 Git，具体隐私边界见 `reports/README.md`。

---

## 演示问题建议

- 流程类：`我要退货`、`查物流`，可继续补充订单号。
- 知识类：`退货规则`、`退款多久到账`、`这款耳机支持降噪吗`。
- 工单类：`我要投诉商品质量问题`、`帮我创建售后工单`。
- 寒暄：`你好`。

---

## 常见问题

**端口占用**

```cmd
uvicorn main:app --reload --port 8001
```

**Docker 卡在等待 MySQL**

检查 `.env` 中 `TRACE_MYSQL_ROOT_PASSWORD`、`TRACE_MYSQL_USER`、`TRACE_MYSQL_PASSWORD` 是否已设置，MySQL 首次启动会初始化数据卷，可能需要稍等。

**不想发生任何 LLM/embedding 联网调用**

设置：

```env
LLM_ENABLED=false
RAG_BACKEND=keyword
EMBEDDING_ENABLED=false
```

**Chroma 查询没有结果**

确认 `RAG_BACKEND=chroma`，再用管理员 token 调用 `POST /api/knowledge/reindex` 重建索引；同时确认 embedding 密钥和维度配置有效。
