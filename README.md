# customer_hand

基于 **FastAPI** 的学习型 **LLM 智能客服** 后端：在保持仓库轻量的前提下，覆盖 **API 契约、会话追踪、YAML Flow、可注册 Action、LLM 结构化命令、关键词 RAG、统一异常与链路 trace** 等简历常见考点。

更完整的设计说明见 **`docs/`**（阶段 7 沉淀）：

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 分层职责、请求生命周期、与开发计划映射 |
| [docs/prompt.md](docs/prompt.md) | 命令式 Prompt 与 RAG Prompt 分工 |
| [docs/rag.md](docs/rag.md) | 加载 / 切分 / 检索 / 生成与演进方向 |
| [docs/interview_qna.md](docs/interview_qna.md) | 高频面试问答与简历一句话模板 |

总体规划见仓库内 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)。

---

## 功能概览

- **HTTP**：`GET /health`、`POST /api/messages`、`GET/POST /api/tracker/...`、Swagger `GET /docs`、调试页 `GET /inspect`
- **编排**：`Agent` 串联 LLM 命令、RAG、规则理解、Flow 槽位与 Action
- **LLM**（可选）：OpenAI 兼容接口（如阿里云百炼），关闭时使用规则与流程兜底
- **RAG**：`data/knowledge` 下文档 → 切分 → **关键词索引**检索 → 可选 LLM 基于片段作答，响应中带 `matches`
- **观测**：请求级 `X-Trace-Id`、结构化日志、LLM/RAG 埋点事件

---

## 目录结构（节选）

```text
customer_hand/
  main.py                 FastAPI 入口与路由
  DEVELOPMENT_PLAN.md     分阶段开发计划
  docs/                   架构 / RAG / Prompt / 面试 Q&A
  app/
    api/                  schemas、异常处理、inspect 模板
    agent/                Agent 主流程
    actions/              Action 注册与内置动作
    core/                 Tracker、Flow 加载、日志、trace、异常
    dialogue/             LLM 命令生成与解析、Flow 执行
    llm/                  客户端、Prompt 构建
    rag/                  文档、切分、索引、检索、回答
    utils/                遥测等工具
  data/
    flows/                业务流程 YAML
    knowledge/            RAG 知识文档（.md / .txt）
  test/                   pytest
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

**不要**将真实 API Key 写入代码、README 或提交到 Git。密钥放在 `.env` 或系统环境变量中。

### 常用变量（与 `.env.example` 一致）

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` / `OPENAI_API_KEY` | 兼容 OpenAI SDK 的密钥 |
| `DASHSCOPE_BASE_URL` | 如百炼兼容端点 |
| `QWEN_MODEL` | 模型名，如 `qwen-plus` |
| `LLM_ENABLED` | `true` / `false`；`false` 时不调用大模型，便于确定性开发与测试 |
| `KNOWLEDGE_DIR` | 可选，默认 `data/knowledge` |

---

## 启动

```cmd
uvicorn main:app --reload
```

浏览器打开：`http://127.0.0.1:8000/docs`

模块方式：

```cmd
python main.py
```

---

## API 快速验证

### 健康检查

```cmd
curl http://127.0.0.1:8000/health
```

### 发送消息（售后意图示例）

```cmd
curl -X POST http://127.0.0.1:8000/api/messages ^
  -H "Content-Type: application/json" ^
  -d "{\"sender_id\":\"user_001\",\"message\":\"我要退货\"}"
```

返回为 **列表**，元素含 `recipient_id`、`text`、`timestamp`、`metadata`（可能含 `source`、`matches` 等）。

### 查看 / 重置会话

```cmd
curl http://127.0.0.1:8000/api/tracker/user_001/full
curl -X POST http://127.0.0.1:8000/api/tracker/user_001/reset
```

重置后若会话已删除，再次 `GET .../full` 可能返回 **404**，响应体中带 `trace_id`（与全局异常处理一致）。

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

## 演示问题建议

- 流程类：`我要退货`、`查物流`（配合后续提供订单号）
- 知识类（需 **`LLM_ENABLED=true`** 且模型输出 `knowledge_answer` 命令）：`退货规则`、`退款多久到账`
- 寒暄：`你好`

---

## 简历描述（可直接改编）

> 独立设计并实现电商场景智能客服后端（FastAPI）：会话状态追踪与 YAML 流程编排、可扩展 Action；通过 **LLM 输出结构化 JSON 命令** 驱动流程与 RAG，失败时降级为规则路径；实现关键词知识检索与带引用回答、统一 **trace_id** 与异常响应；pytest 覆盖核心 API 与编排逻辑。

---

## 常见问题

**conda / Python 版本不对**  
先 `conda activate customer`，保证 Python 3.10+。

**端口占用**  

```cmd
uvicorn main:app --reload --port 8001
```

**依赖报错**  
执行 `pip install -r requirements.txt`；若缺少 `pydantic-settings`，可 `pip install pydantic-settings`（部分环境需显式安装）。

**LLM 不想联网**  
设置 `LLM_ENABLED=false`，依赖规则与 Flow 仍可演示主链路。
