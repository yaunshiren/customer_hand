# customer_hand

`customer_hand` 是一个学习型 LLM 智能客服项目，目标是通过一个可运行、可测试、可演示的小项目，逐步掌握大模型应用开发工程师需要的后端、LLM、Agent、Tool Calling 和 RAG 能力。

当前阶段重点是先跑通 FastAPI API、消息收发、会话状态查看和会话重置。后续会继续加入 Tracker 对象化、Action、Flow、LLM Command、Tool Calling 和 RAG。

## 当前已完成接口

- `GET /health`：服务健康检查。
- `POST /api/messages`：发送用户消息，返回稳定的消息响应结构。
- `GET /api/tracker/{sender_id}/full`：查看指定用户当前会话状态。
- `POST /api/tracker/{sender_id}/reset`：重置指定用户会话状态。

## 项目目录说明

```text
customer_hand/
  main.py                 FastAPI 入口
  app/
    agent/                Agent 主流程
    core/                 Flow 加载、Tracker 存储
    dialogue/             Prompt、LLM、命令解析、Flow 执行
    actions/              后续放 Action 抽象和业务动作
  data/
    flows/                当前 YAML Flow 配置
  test/                   pytest 测试
  requirements.txt        最小依赖列表
  .env.example            环境变量示例
```

## 环境准备

在 Windows CMD 或 PowerShell 中进入项目目录：

```cmd
cd /d D:\code4\llm-universe-main\customer_simple\customer_hand
conda activate customer
pip install -r requirements.txt
```

## 环境变量说明

复制环境变量示例文件：

```cmd
copy .env.example .env
```

真实 API Key 不要提交到 Git，也不要写入代码或 README。你使用的是阿里云百炼平台 API Key，并且已经在本机环境变量中配置好时，可以不把真实 Key 写入 `.env`。

当前代码优先读取：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL`
- `QWEN_MODEL`
- `LLM_ENABLED`

如果你的本机使用其他变量名，请根据实际配置填写，例如 `BAILIAN_API_KEY` 或 `DASHSCOPE_API_KEY`。当前 demo 即使不启用真实 LLM，也应该能跑通基础 API；如需避免真实 LLM 调用，可保持：

```cmd
set LLM_ENABLED=false
```

## 启动服务

```cmd
uvicorn main:app --reload
```

启动后访问 API 文档：

```text
http://127.0.0.1:8000/docs
```

## 第一轮 Demo 操作步骤

### Step 1：检查健康状态

CMD:

```cmd
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{
  "status": "ok",
  "service": "customer_hand",
  "version": "0.1.0"
}
```

### Step 2：发送一条消息

CMD:

```cmd
curl -X POST http://127.0.0.1:8000/api/messages ^
  -H "Content-Type: application/json" ^
  -d "{\"sender_id\":\"user_001\",\"message\":\"我要退货\"}"
```

预期返回是列表结构，每一项至少包含 `recipient_id`、`text`、`timestamp`、`metadata`：

```json
[
  {
    "recipient_id": "user_001",
    "text": "请提供订单号。",
    "timestamp": "2026-05-08T12:00:00+00:00",
    "metadata": {}
  }
]
```

实际 `text` 会根据当前 Agent 逻辑变化，但返回结构应保持稳定。

### Step 3：查看 tracker

CMD:

```cmd
curl http://127.0.0.1:8000/api/tracker/user_001/full
```

可以看到 `user_001` 的当前会话状态，包括用户消息、机器人回复、槽位和当前流程状态。预期结构：

```json
{
  "sender_id": "user_001",
  "exists": true,
  "tracker": {
    "sender_id": "user_001",
    "latest_message": "我要退货",
    "slots": {},
    "events": []
  }
}
```

### Step 4：重置 tracker

CMD:

```cmd
curl -X POST http://127.0.0.1:8000/api/tracker/user_001/reset
```

预期返回：

```json
{
  "sender_id": "user_001",
  "reset": true,
  "message": "Tracker reset successfully"
}
```

### Step 5：再次查看 tracker

CMD:

```cmd
curl http://127.0.0.1:8000/api/tracker/user_001/full
```

当前代码的实际行为是：reset 后该会话被删除，再次查询会返回 HTTP `404`，响应中包含：

```json
{
  "detail": "Tracker not found"
}
```

## 推荐演示问题

当前阶段可以用这些问题测试基础消息链路：

- `我要退货`
- `查物流`
- `你好`
- `我的订单到了吗`
- `帮我看看售后怎么处理`

注意：当前项目还处在最小可用 API demo 阶段，回复可能是规则回复或最小可用回复。

## 运行测试

```cmd
pytest test/test_api_basic.py -v
```

当前测试覆盖：

- `GET /health`
- `POST /api/messages`
- `POST /api/tracker/{sender_id}/reset`
- reset 后再次查询 tracker 返回 404

## 当前项目边界

当前项目还不是完整智能客服：

- 当前 LLM、Action、Flow、RAG 还在后续开发中。
- 当前回复可能是最小可用回复或规则回复。
- 当前 README 主要用于跑通第一轮 API demo。
- 当前重点是保证 API 结构稳定、会话可查看、会话可重置。

## 后续计划

- Day 6-8：实现 `DialogueStateTracker`，让会话状态从裸字典逐步对象化。
- Day 9-14：实现 Action + Flow 闭环，把硬编码回复迁移到 Action。
- Day 15-20：接入 LLM Command，让 LLM 输出受约束命令，再由程序执行。
- Day 21-25：完善 API 和 inspect 页面，让状态、命令、流程变化可视化。
- Day 26-36：实现业务 Action + Tool Calling，体现 Agent 工具调用能力。
- Day 37-40：实现最小可用 RAG MVP，补充知识库问答能力。

## 常见问题

### conda 环境未激活

如果提示找不到依赖或 Python 版本不对，先执行：

```cmd
conda activate customer
```

### 依赖未安装

执行：

```cmd
pip install -r requirements.txt
```

### 端口被占用

默认端口是 `8000`。如果被占用，可以换端口：

```cmd
uvicorn main:app --reload --port 8001
```

### API Key 不要写入代码

不要把真实 API Key 写入 Python 文件、README 或提交到 Git。真实密钥应放在系统环境变量或本地 `.env` 文件中，并确保 `.env` 已被 `.gitignore` 忽略。
