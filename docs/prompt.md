# Prompt 设计说明（customer_hand）

## 1. 总体策略

本项目中的 LLM 主要承担 **「命令生成器」** 角色，而不是无边界闲聊：输出必须是 **单一 JSON**，由 Python 解析后再决定启动 Flow、填槽、走 RAG 或闲聊。这样可以把「业务正确性」留在代码与 Action 中，把「意图理解与结构化」交给模型。

核心类：`app/llm/prompts.py` 中的 `CommandPromptBuilder`（对外别名 `PromptBuilder`）。

## 2. 双层 Prompt 结构

| 部分 | 方法 | 作用 |
|------|------|------|
| System | `_build_system_prompt` | 定义角色、输出格式禁令（无 Markdown/代码块）、命令类型枚举、业务优先级规则 |
| User | `_build_user_prompt` | 注入当前用户句、会话状态 JSON、可用 flows/tools 描述、schema 示例 |

## 3. 会话状态注入

User prompt 中的 `state` 包含：

- `sender_id`
- `slots`
- `active_flow`
- `latest_message`
- `history`：最近若干条事件的压缩列表（用于多轮上下文）

模型据此判断例如：是否已在售后 Flow、是否应输出 `set_slot` 填写 `order_id`。

## 4. 支持的命令类型（与代码契约一致）

在 system prompt 中声明的类型包括：

- `start_flow` — 启动 YAML 定义的流程（如 `postsale`、`logistics`）
- `set_slot` — 写入槽位（如订单号）
- `chitchat` — 直接回复，需带 `text`
- `knowledge_answer` — 触发 RAG，可带 `query`、`top_k`
- `call_tool` — 预留工具调用（如物流查询）

**设计意图**：用有限类型约束输出空间，降低解析失败率；解析逻辑见 `app/dialogue/command_parser.py` 等模块。

## 5. 默认决策规则（摘录）

System 段中用自然语言写明的优先级示例：

- 退货/退款/售后 → `start_flow`，`flow_id=postsale`
- 物流/快递 → `start_flow`，`flow_id=logistics`
- 在相关 Flow 中且输入像订单号 → `set_slot`，`name=order_id`
- 规则类咨询 → `knowledge_answer`
- 寒暄 → `chitchat`；不确定时亦倾向 `chitchat`，避免编造业务结果

## 6. RAG 子任务的 Prompt

`KnowledgeAnswerer` 使用另一套较短 Prompt（见 `app/rag/answerer.py`）：

- System：强调「仅根据给定片段、禁止编造」
- User：拼接「问题 + 知识片段」并要求简洁准确

与命令生成 Prompt **解耦**，避免单 prompt 过长且职责混杂。

## 7. 版本化与迭代建议

当前模板为代码内字符串，便于学习与单步调试。生产化时可：

- 拆为 `data/prompts/*.jinja2`，按版本号或 git tag 管理  
- 对同一意图 A/B 测试不同 system 段，对比命令解析成功率  

## 8. 常见追问准备

- **如何避免胡说？** 限制输出为 JSON；业务结果由 Action/Flow 产生；RAG 段强制基于片段。  
- **模型仍输出 Markdown 怎么办？** 解析前 strip / 正则提取 JSON；失败则降级为规则路径并记 `llm_error` 事件。  
