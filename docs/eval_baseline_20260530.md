# customer_hand 评测基线报告（2026-05-30）

本文记录阶段 0 的基线结果，用作后续优化的对照组。

---

## 1. 本次结论

阶段 0 已完成。

当前系统已经具备可运行、可测试、可评测的基础：

- `customer_hand` 单元测试通过：`62 passed, 1 skipped`。
- `system` 模式可以真实测试 `/api/messages` 端到端链路。
- `rag` 模式可以只测试 RAG 检索能力，并且已经排除不需要 RAG 的 F2/F3/C 类样本。

核心判断：

1. RAG-only 表现优于 system，说明检索模块本身比端到端系统链路更稳定。
2. system 的主要问题不是“完全搜不到”，而是 intent/route 决策不稳定。
3. `intent_top1 = —` 仍是最大短板，下一阶段必须实现真实 intent classifier。
4. system 模式仍没有保存真实 `retrieved_contexts`，后续 RAGAS 和生成质量评测会受影响。

---

## 2. 运行记录

### 2.1 System E2E 评测

运行文件：

```text
D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\runs\v1_customer_hand_20260530_144204.jsonl
```

评分报告：

```text
D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\reports\v1_customer_hand_20260530_144204\_scores.json
```

命令：

```bash
python -m eval rag score eval/runs/v1_customer_hand_20260530_144204.jsonl --skip-ragas
```

数据规模：

```text
total records    = 150
requires_rag     = 132
non_rag          = 18
success          = 150
```

路由分布：

```text
rag       = 126
chitchat  = 15
flow      = 7
ticket    = 2
```

### 2.2 RAG-only 评测

运行文件：

```text
D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\runs\v1_customer_hand_20260530_152628.jsonl
```

评分报告：

```text
D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\reports\v1_customer_hand_20260530_152628\_scores.json
```

命令：

```bash
python -m eval rag score eval/runs/v1_customer_hand_20260530_152628.jsonl --skip-ragas
```

数据规模：

```text
total records    = 132
requires_rag     = 132
non_rag          = 0
success          = 132
```

说明：

RAG-only 模式已经只跑 `requires_rag=true` 的样本，因此 `over_retrieval_rate = —` 是合理结果。

### 2.3 单元测试

命令：

```bash
pytest
```

结果：

```text
62 passed, 1 skipped in 17.24s
```

---

## 3. 指标对比

| 指标 | System E2E | RAG-only | 说明 |
|---|---:|---:|---|
| `intent_top1` | — | — | 尚未暴露真实 intent 分类结果 |
| `hit@1` | 72.7% | 78.8% | RAG-only 高 6.1 个点 |
| `recall@1` | 44.4% | 48.2% | RAG-only 更稳定 |
| `hit@3` | 83.3% | 91.7% | 端到端路由拖累明显 |
| `recall@3` | 58.7% | 68.2% | RAG-only 高 9.5 个点 |
| `hit@5` | 83.3% | 93.9% | system 有些样本未进入 RAG |
| `recall@5` | 58.7% | 70.6% | RAG 本身仍需优化排序 |
| `mrr@10` | 77.7% | 85.4% | RAG-only 排序更好 |
| `refusal_when_required` | 6.8% | 0.0% | system 存在错误流程回复 |
| `fallback_when_required` | 0.0% | 0.0% | 暂无兜底失败 |
| `over_retrieval_rate` | 16.7% | — | system 对非 RAG 样本仍有误检索 |
| `ttft_p50_ms` | 5671 | 246 | system 包含 LLM 生成耗时 |
| `ttft_p95_ms` | 9849 | 287 | RAG-only 基本是检索延迟 |
| `ttft_mean_ms` | 5853 | 247 | system 需要后续 SSE 改造 |

---

## 4. 关键问题归因

### 4.1 问题一：真实 intent 仍不可评测

现象：

```text
intent_top1 = —
```

原因：

- 当前系统没有对外暴露真实 intent 分类结果。
- 评测侧无法判断系统是否识别出 `S16_物流配送`、`F1_故障报告`、`F2_功能建议` 等类别。

影响：

- 面试时无法证明“意图识别能力”。
- Route 错误时无法区分是 intent 错，还是 route policy 错。

下一步：

- 实现真实 intent classifier。
- 在 system response metadata 中输出：

```json
{
  "intentLeafIds": ["S16_物流配送"],
  "intentSource": "system_classifier",
  "intentConfidence": 0.86
}
```

---

### 4.2 问题二：System 路由错误导致需要 RAG 的问题没有检索

System 中：

```text
requires_rag but docs=0 = 9
refusal_when_required    = 6.8%
```

这些样本应回答知识或至少结合知识库，但被路由到 `flow` 或 `chitchat`。

| case_id | intent | route | 问题 | 当前问题 |
|---|---|---|---|---|
| `S1-05` | S1_选购推荐 | chitchat | 想给女朋友买礼物，预算 1000 左右，有没有不踩雷的？ | 没有检索礼物指南，泛化回答 |
| `S12-05` | S12_生态联动 | chitchat | 想做个离家模式，关灯关空调启动扫地机 | 没有检索自动化指南 |
| `S13-07` | S13_保养维护 | flow | 扫地机用了半年吸力变弱了 | 直接要求订单号 |
| `S15-02` | S15_退换货 | flow | 怎么申请退货？ | 直接要求订单号 |
| `S16-04` | S16_物流配送 | flow | 我下单了 3 天还没发货 | 直接要求订单号 |
| `S16-05` | S16_物流配送 | flow | 我能改收货地址吗？已经发货了 | 直接要求订单号 |
| `F1-01` | F1_故障报告 | flow | 我的扫地机充不进电了 | 没有给故障排查 |
| `F3-02` | F3_投诉吐槽 | flow | 等了一周还没发货，太慢了！ | 没有安抚和物流政策 |
| `F3-03` | F3_投诉吐槽 | flow | 这手机用了 3 个月就卡 | 没有故障排查和保修政策 |

结论：

这不是单纯 RAG 检索问题，而是 intent/route policy 问题。下一阶段应优先修复。

---

### 4.3 问题三：非 RAG 样本仍有误检索

System 中：

```text
over_retrieval_rate = 16.7%
```

误检索样本：

| case_id | intent | route | 问题 | 误召回 |
|---|---|---|---|---|
| `F2-02` | F2_功能建议 | rag | 扫地机能不能加个语音播报关闭功能 | `FAQ_VAC_001`, `PROD_VAC_002`, `PROD_VAC_003` |
| `F2-03` | F2_功能建议 | rag | 为啥不能在 APP 里直接看说明书？ | `progress`, `doc_index`, `doc_template` |
| `C2-02` | C2_越界提问 | rag | 苹果 15 Pro 怎么样？ | `PROD_PHONE_004`, `PROD_BOOK_002` |

下一步：

- F2 功能建议应进入 feedback/ticket，不应走 RAG。
- C2 越界问题应简短拒答或引导回业务范围，不应触发商品检索。
- 需要在 route policy 中加入 `requires_rag=false` 的强约束。

---

### 4.4 问题四：RAG-only 仍有排序与召回问题

RAG-only 表现明显好于 system，但仍有 28 个 `hit@1` miss，11 个 `hit@3` miss。

Top3 仍未命中的关键样本：

| case_id | intent | 问题 | 期望文档 | 实际文档 |
|---|---|---|---|---|
| `S3-03` | S3_对比选购 | 小米 13 和小米 14 哪个值得买？ | `PROD_PHONE_001`, `PROD_PHONE_003` | `GUIDE_PHONE_004`, `GUIDE_PHONE_001`, `GUIDE_PHONE_003` |
| `S4-01` | S4_价格活动 | 小米 14 Pro 现在有什么优惠活动？ | `POLICY_RET_004` | `PROD_PHONE_004`, `PROD_PHONE_003`, `GUIDE_PHONE_001` |
| `S4-04` | S4_价格活动 | 200 元的优惠券能用在扫地机上吗？ | `POLICY_RET_004`, `POLICY_LOG_001` | `GUIDE_GIFT_001`, `GUIDE_VAC_001`, `PROD_VAC_002` |
| `S5-01` | S5_库存到货 | 小米 14 Pro 黑色款有货吗？ | `POLICY_LOG_001` | `PROD_PHONE_004`, `PROD_PHONE_003`, `PROD_PHONE_002` |
| `S5-04` | S5_库存到货 | 新款手表什么时候上市？ | `GUIDE_WATCH_001`, `POLICY_LOG_001` | `PROD_WATCH_003`, `PROD_WATCH_002`, `PROD_WATCH_001` |
| `S1-09` | S1_选购推荐 | 通勤和线上会议都想用，耳机和音箱怎么搭配买？ | `GUIDE_BUDS_001`, `PROD_BUDS_003`, `PROD_SPK_002` | `GUIDE_GIFT_002`, `PROD_BUDS_001`, `MANUAL_BUDS_001` |
| `S9-07` | S9_配网连接 | 蓝牙连上了但 APP 显示离线 | `NET_GUIDE_001`, `FAQ_NET_001`, `APP_GUIDE_002` | `NET_GUIDE_002`, `APP_GUIDE_004`, `FAQ_LOCK_001` |
| `S10-03` | S10_APP功能 | APP 里怎么查扫地机的清扫记录？ | `APP_GUIDE_003`, `MANUAL_VAC_002` | `MANUAL_VAC_001`, `progress` |
| `S12-04` | S12_生态联动 | 门锁开门后扫地机自动暂停能实现吗？ | `AUTO_GUIDE_001`, `AUTO_GUIDE_002`, `PROD_LOCK_001`, `MANUAL_VAC_002` | `CODE_VAC_001`, `FAQ_VAC_001`, `MANUAL_VAC_001` |
| `F1-05` | F1_故障报告 | 手表充电时发烫得厉害 | `MANUAL_WATCH_001`, `POLICY_WAR_001`, `POLICY_WAR_002` | `CODE_PHONE_001` |
| `F3-03` | F3_投诉吐槽 | 这手机用了 3 个月就卡 | `CODE_PHONE_001`, `POLICY_WAR_001`, `POLICY_WAR_002` | `MANUAL_PHONE_001`, `CODE_FW_001`, `PROD_PHONE_005` |

归因：

- 动态类问题需要政策/工具优先，而不是产品详情优先。
- 精确产品型号和品类没有足够强的 entity boost。
- APP 功能、生态联动、配网连接容易召回相近但错误的操作文档。
- 故障类需要设备品类识别，例如“手表发烫”不应召回手机故障文档。

---

## 5. 低分 Intent 分布

### 5.1 System hit@1 较低的 intent

| intent | hit@1 |
|---|---:|
| `F3_投诉吐槽` | 0.0% |
| `S5_库存到货` | 50.0% |
| `S13_保养维护` | 55.6% |
| `S4_价格活动` | 57.1% |
| `S10_APP功能` | 57.1% |
| `F1_故障报告` | 60.0% |
| `S12_生态联动` | 66.7% |
| `S16_物流配送` | 66.7% |

### 5.2 RAG-only hit@1 较低的 intent

| intent | hit@1 |
|---|---:|
| `S5_库存到货` | 50.0% |
| `F3_投诉吐槽` | 50.0% |
| `S4_价格活动` | 57.1% |
| `S10_APP功能` | 57.1% |
| `S13_保养维护` | 66.7% |
| `S6_配件兼容` | 71.4% |
| `S9_配网连接` | 71.4% |
| `S2_参数咨询` | 72.7% |

结论：

- system 低分 intent 主要受路由影响。
- RAG-only 低分 intent 主要受检索排序和领域过滤影响。

---

## 6. 阶段 1 优先事项

### 6.1 必做

1. 实现真实 intent classifier。
2. 在 `/api/messages` metadata 中暴露 `intentLeafIds`、`intentSource`、`intentConfidence`。
3. 修改 route policy：
   - F2/F3/C2 不应误走 RAG。
   - F1/S13/S15/S16/F3 这类需要政策或排查步骤的问题，不应直接进入“请提供订单号”。
4. system 模式保存真实 `retrieved_contexts`。
5. 把本报告中的 badcase 加入回归清单。

### 6.2 优先修复样本

第一批回归样本：

```text
F1-01
F2-02
F2-03
F3-02
F3-03
S1-05
S12-05
S13-07
S15-02
S16-04
S16-05
C2-02
```

### 6.3 下一次验收目标

| 指标 | 当前 System | 阶段 1 目标 |
|---|---:|---:|
| `intent_top1` | — | 可计算 |
| `refusal_when_required` | 6.8% | 0.0% |
| `over_retrieval_rate` | 16.7% | 0.0% |
| `hit@1` | 72.7% | 78%+ |
| `hit@3` | 83.3% | 90%+ |
| system `retrieved_contexts` | 空 | 可记录 |

---

## 7. 阶段 0 状态

阶段 0 验收项：

- [x] `customer_hand` 测试通过。
- [x] system E2E 跑通并落盘。
- [x] RAG-only 跑通并落盘。
- [x] 保存 baseline 指标。
- [x] 整理 badcase。
- [x] 明确阶段 1 优先优化方向。

阶段 0 完成。

