# customer_hand

`customer_hand` 是一个面向学习和求职展示的 LLM 客服应用练习项目。当前阶段先完成 FastAPI 服务骨架、消息接口和会话状态查看/重置能力，后续会逐步加入 Tracker 对象化、Action、LLM Command、Tool Calling 和 RAG。

## 当前已完成功能

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

在 Windows PowerShell 或 CMD 中进入项目目录：

```powershell
cd D:\code4\llm-universe-main\customer_simple\customer_hand
conda activate customer
pip install -r requirements.txt
```

## 环境变量配置

本项目支持从 `.env` 或系统环境变量读取配置。你可以复制示例文件：

```powershell
copy .env.example .env
```

真实 API Key 不要提交到 Git，也不要写入代码。你已经在本机配置了阿里云百炼 API Key 环境变量时，可以不把真实 Key 写进 `.env`。

当前代码优先读取：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_BASE_URL`
- `QWEN_MODEL`
- `LLM_ENABLED`

如果你的本机使用其他变量名，请根据实际配置填写，例如 `BAILIAN_API_KEY` 或 `DASHSCOPE_API_KEY`。当前代码实际使用的是 `DASHSCOPE_API_KEY`；后续可以再统一变量名。

## 启动方式

```powershell
uvicorn main:app --reload
```

启动后访问：

```text
http://127.0.0.1:8000/docs
```

## API 验证方式

### 1. 健康检查

PowerShell:

```powershell
curl.exe http://127.0.0.1:8000/health
```

预期返回类似：

```json
{
  "status": "ok",
  "service": "customer_hand",
  "version": "0.1.0"
}
```

### 2. 发送消息

PowerShell:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/messages `
  -H "Content-Type: application/json" `
  -d "{\"sender_id\":\"user_001\",\"message\":\"我要退货\"}"
```

预期返回是列表结构，每一项至少包含：

```json
[
  {
    "recipient_id": "user_001",
    "text": "...",
    "timestamp": "...",
    "metadata": {}
  }
]
```

### 3. 查看 tracker

```powershell
curl.exe http://127.0.0.1:8000/api/tracker/user_001/full
```

预期返回：

```json
{
  "sender_id": "user_001",
  "exists": true,
  "tracker": {
    "...": "..."
  }
}
```

如果会话不存在，会返回 HTTP 404。

### 4. 重置 tracker

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/tracker/user_001/reset
```

预期返回：

```json
{
  "sender_id": "user_001",
  "reset": true,
  "message": "Tracker reset successfully"
}
```

## 当前项目边界

当前项目还是早期版本：

- 还没有完整的 Tracker 对象化。
- 还没有完整 Action 系统。
- 还没有生产级 LLM Command 链路。
- 还没有 Tool Calling。
- 还没有 RAG。

后续计划会逐步补齐：

1. Tracker 对象化和会话管理。
2. Action registry 和业务 Action。
3. LLM Prompt -> CommandParser -> CommandProcessor。
4. Tool Calling。
5. 最小可用 RAG。
6. 测试、日志、部署和作品集文档。

## 常见问题

### conda 环境未激活

如果提示找不到依赖或 Python 版本不对，先执行：

```powershell
conda activate customer
```

### 依赖未安装

执行：

```powershell
pip install -r requirements.txt
```

### 端口被占用

默认端口是 `8000`。如果被占用，可以换端口：

```powershell
uvicorn main:app --reload --port 8001
```

### API Key 不要写入代码

不要把真实 API Key 写入 Python 文件、README 或提交到 Git。真实密钥应放在系统环境变量或本地 `.env` 文件中，并确保 `.env` 已被 `.gitignore` 忽略。
