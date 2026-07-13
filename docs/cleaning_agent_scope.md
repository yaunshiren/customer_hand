# V1-01 智能清洁设备首版范围与最小 Golden Set

## 1. 文档状态

- 任务编号：`V1-01`
- 数据集版本：`cleaning_mvp_v1`
- 状态：首版产品范围、问题分类和最小 Golden Set 已定义
- 适用对象：BitSelect 智能清洁设备售后 Agent 的离线数据契约

本任务只建立范围、目录、问题分类、评测数据和离线验证测试，不修改 Agent、Prompt、上下文模型、RAG、reranker、知识 metadata、Eval scorer、API、数据库或 CI。

> 重要边界：数据契约已经建立，不代表运行时已经实现型号解析、型号过滤 RAG、Reviewer 或 HumanGate。当前结果不能描述为生产可用。

## 2. 证据口径

本范围中的型号、产品能力、错误码和 `doc_id` 均来自仓库知识文件。知识文件是项目内证据，但没有 `approval_status`、官方来源 URL 或外部品牌核验，因此不能视为已完成生产审核。

四款支持型号共享以下知识：

- 基础使用：[MANUAL_VAC_001](../data/knowledge/bitselect/02_manual/product/MANUAL_VAC_001.md)
- 地图和清扫设置：[MANUAL_VAC_002](../data/knowledge/bitselect/02_manual/product/MANUAL_VAC_002.md)
- 保养维护：[MANUAL_VAC_003](../data/knowledge/bitselect/02_manual/product/MANUAL_VAC_003.md)
- 故障排查：[FAQ_VAC_001](../data/knowledge/bitselect/04_faq/trouble/FAQ_VAC_001.md)
- 错误码：[CODE_VAC_001](../data/knowledge/bitselect/04_faq/error_code/CODE_VAC_001.md)

## 3. 第一版产品范围

| 型号 | 商品详情证据 | 支持级别 | 知识完整度 | 已确认的主要边界 |
|---|---|---|---|---|
| T7 | [PROD_VAC_001](../data/knowledge/bitselect/01_product/detail/PROD_VAC_001.md) | 标准支持 | 高 | 不支持拖布自动抬升、自动集尘或自清洁基站 |
| T7S Plus | [PROD_VAC_002](../data/knowledge/bitselect/01_product/detail/PROD_VAC_002.md) | 有限支持 | 中 | 支持拖布抬升；自动集尘需专用集尘座；缺少专用集尘座故障资料 |
| G10 | [PROD_VAC_003](../data/knowledge/bitselect/01_product/detail/PROD_VAC_003.md) | 标准支持 | 中 | 支持拖布回洗和自动补水，不支持自动集尘和热风烘干 |
| G10S Pro | [PROD_VAC_004](../data/knowledge/bitselect/01_product/detail/PROD_VAC_004.md) | 标准支持 | 高 | 支持自动集尘、拖布回洗、自动补水和热风烘干 |

`米家无线吸尘器 2 / B205` 暂不支持。仓库只有其商品详情 `PROD_VAC_005`，没有独立手册、故障 FAQ 或错误码文档；它也是手持吸尘器，不属于本版扫地机器人产品线。

### 3.1 T7S Plus 有限覆盖规则

1. 可以使用 `PROD_VAC_002` 以及明确覆盖四款扫地机器人的共享手册和通用错误码。
2. 不得把 G10 或 G10S Pro 的自清洁基站、补水、洗拖布、尘袋或热风烘干步骤用于 T7S Plus。
3. 专用集尘座故障缺少直接知识证据时，必须澄清集尘座型号和现象，或转人工。
4. 不得以其他型号资料填补缺失内容。

## 4. 问题范围

### 4.1 第一阶段支持

- `POWER_CHARGING_FAILURE`
- `CLEANING_INTERRUPTION_OR_STUCK`
- `CLEANING_PERFORMANCE_DROP`
- `MOPPING_OR_BASE_STATION_FAILURE`
- `ERROR_CODE_DIAGNOSIS`

### 4.2 第二阶段仅记录规划

- `NETWORK_OR_MAP_FAILURE`
- `MAINTENANCE_AND_CONSUMABLE`
- `WARRANTY_AND_REPAIR`

第二阶段类型不属于 `cleaning_mvp_v1` 的验收范围，也不能据此宣称已实现对应运行时能力。

## 5. 型号缺失与安全规则

用户没有提供具体型号时：

1. 先询问订单商品名、机身铭牌或 APP 中显示的型号。
2. 只允许提供四款型号都安全适用的基础检查。
3. 不猜测型号，不提供型号专属功能、配件、错误码或基站步骤。
4. 在型号明确前，不得引用型号专属商品详情作为诊断依据。

出现异常发热、冒烟、烧焦味或电气区域进水时：

1. 停止普通排障和继续运行建议。
2. 建议断电或停止使用；只有在不会增加触电、烫伤或进水风险时才进行安全操作。
3. 建议转人工售后处理。

其中“异常发热、烧焦味后停止使用并转人工”有 `FAQ_VAC_001` 和 `CODE_VAC_001` 证据；“冒烟、电气区域进水”来自 V1-01 已确认的安全范围决策，尚未在清洁设备知识文件中形成独立条目。

## 6. Golden Set 设计

`data/eval/cleaning_mvp_v1.jsonl` 恰好包含 8 条合成用例：

| 用例 | 型号/状态 | 问题类型 | 主要目的 |
|---|---|---|---|
| `cleaning_t7_power_001` | T7 | 电源/充电 | 充电指示灯不亮后的停止条件和人工处理 |
| `cleaning_t7s_stuck_001` | T7S Plus | 清扫中断/卡困 | 有限覆盖型号的通用安全排障 |
| `cleaning_g10_performance_001` | G10 | 清洁效果下降 | 尘盒、滤网、主刷和风道排查 |
| `cleaning_g10s_dock_001` | G10S Pro | 拖地/基站 | `DOCK_DUST` 的型号专属基站步骤 |
| `cleaning_model_missing_001` | 型号缺失 | 拖地/基站 | 必须先澄清，不猜型号 |
| `cleaning_t7_cross_model_001` | T7 | 跨型号负例 | 阻止召回 T7S Plus/G10/G10S Pro 的拖布抬升能力 |
| `cleaning_g10s_danger_001` | G10S Pro | 电源/充电 | 异常发热和烧焦味时停止普通排障并转人工 |
| `cleaning_g10_injection_001` | G10 | 错误码 | 标记 Prompt injection，拒绝拆机短接，并按 E05 安全处理 |

扩展评测契约放在 `metadata.golden`，现有顶层 `EvalCase` 字段保持不变。旧数据缺少 `golden` 时使用空字典，因此保持向后兼容。Eval scorer 未修改，当前 scorer 也不会自动消费这些扩展字段。

## 7. 评分边界

| 能力 | 当前状态 | 说明 |
|---|---|---|
| intent、route、工具选择、工具参数 | 自动评分 | 由现有 Eval scorer 比较结构化 trace |
| Top-3 检索关键词命中 | 自动评分 | 当前逻辑为“任一关键词命中”，不是所有必需文档都命中 |
| Prompt injection 标记 | 自动评分 | 检查安全 flag 或安全错误码 |
| 回答是否带有与检索 trace 相连的引用 | 自动评分 | 只能证明引用链存在，不能证明引用支持每个具体结论 |
| 8 条数量、四型号覆盖、五问题类型覆盖 | 规则评分 | 由 `test_cleaning_scope_dataset.py` 离线校验 |
| `expected_doc_ids`、`forbidden_doc_ids` 的存在性和冲突 | 规则评分 | 只校验数据契约，不修改 scorer |
| 型号缺失、危险症状、跨型号负例、Prompt injection 覆盖 | 规则评分 | 校验标签和预期字段 |
| 回答事实是否完全正确 | 人工评分 | 当前 scorer 不做语义事实判定 |
| 是否暗中混入其他型号能力 | 人工评分 | `forbidden_doc_ids` 尚未接入运行时 scorer |
| 澄清问题是否充分、转人工时机是否合理 | 人工评分 | 需要结合回答和 trace 审核 |
| 引用是否真正支持每一句结论 | 人工评分 | 当前自动检查只验证引用与检索结果相连 |

## 8. 已知缺口与未验证事项

1. 当前 RAG 没有按 `applicable_models` 执行强型号过滤，本数据集不会自动改变运行时检索行为。
2. 知识 metadata 缺少统一的 `brand`、`model`、`applicable_models`、`approval_status` 和官方来源 URL。
3. T7S Plus 专用集尘座缺少独立故障排查和错误码范围。
4. G10S Pro 自动上下水套件只有少量注意事项，不能据此完成复杂漏水诊断。
5. 当前 scorer 不读取 `metadata.golden.expected_doc_ids`、`forbidden_doc_ids` 或 `expected_handoff`。
6. 本任务没有调用真实 Agent、LLM、Embedding、向量库或外部服务，因此没有生成实际效果指标。

## 9. 回滚方式

删除本任务新增的五个数据/文档/测试文件，并移除 `EvalCaseMetadata.golden` 可选字段即可回滚。没有数据库迁移、索引变更或运行时行为变更。
