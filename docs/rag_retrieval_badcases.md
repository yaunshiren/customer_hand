# RAG 检索 Badcase 诊断报告

生成日期：2026-06-02

本报告用于阶段 3 第 1 步：在改混合检索和 rerank 前，先定位当前 RAG 检索到底错在哪里。

## 1. 数据来源

| 项目 | 内容 |
|---|---|
| run 文件 | `D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\runs\改进路由之后\v1_customer_hand_20260601_225702.jsonl` |
| score 文件 | `D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\reports\v1_customer_hand_20260601_225702\_scores.json` |
| eval mode | `rag` |
| 样本数 | 132 |
| 说明 | `eval\runs` 根目录下也有同名文件，和上述文件 SHA256 一致。本文按用户指定的“改进路由之后”目录记录。 |

## 2. 当前指标

| 指标 | 当前值 | 诊断 |
|---|---:|---|
| hit@1 | 78.8% | top1 排序还有明显提升空间 |
| hit@3 | 91.7% | top3 召回基本可用 |
| recall@3 | 68.2% | 多参考文档场景召回不完整 |
| mrr@10 | 85.4% | 正确文档经常在前几位，但不一定是第 1 位 |
| ttft_mean_ms | 260 | 纯 RAG 检索很快，瓶颈不在检索耗时 |

统计结论：

- `hit@1 = 0` 的样本有 28 条。
- `recall@3 < 0.5` 的严重低召回样本有 22 条。
- `recall@3 < 1.0` 的部分召回样本有 72 条，说明多文档问题经常只命中其中一部分。
- 主要问题不是“完全检索不到”，而是“正确文档在 top3 内但没有排到 top1”，以及“多参考文档没有补齐”。

## 3. 重点类别概览

| 类别 | 样本数 | hit@1 | recall@3 | hit@1 失败样本 | 主要问题 |
|---|---:|---:|---:|---|---|
| S6_配件兼容 | 7 | 71.4% | 53.6% | S6-01, S6-05 | 型号实体识别和配件/手册文档 boost 不足 |
| S14_售后政策 | 8 | 87.5% | 75.0% | S14-01 | 产品详情压过保修政策 |
| S9_配网连接 | 7 | 71.4% | 45.2% | S9-04, S9-07 | 配网、APP、FAQ 多域文档召回不完整 |
| S13_保养维护 | 9 | 66.7% | 72.2% | S13-05, S13-06, S13-09 | 维护手册/FAQ 被产品详情或其他品类手册压过 |
| F1_故障报告 | 5 | 80.0% | 60.0% | F1-05 | 设备类型实体错配，手表问题召回到手机故障码 |

## 4. 全量 hit@1 失败样本

| query_id | intent | 用户问题 | 期望 doc_id | 实际 top3 doc_id | recall@3 | 初步错因 |
|---|---|---|---|---|---:|---|
| S2-03 | S2_参数咨询 | 米家空气净化器 4 Pro 适合多大面积？ | `PROD_AIR_003` | `GUIDE_AIR_001`, `PROD_AIR_003`, `PROD_AIR_002` | 1.00 | 排序问题：空气净化器指南压过产品详情 |
| S2-08 | S2_参数咨询 | 石头 G10 在地毯上吸力会下降吗？ | `PROD_VAC_003` | `GUIDE_VAC_002`, `PROD_VAC_003`, `GUIDE_VAC_003` | 1.00 | 排序问题：场景指南压过具体产品详情 |
| S2-10 | S2_参数咨询 | 小米 Buds 4 的延迟多少 ms？打游戏够用吗？ | `PROD_BUDS_003`, `MANUAL_BUDS_001` | `PROD_BUDS_004`, `PROD_BUDS_003` | 0.50 | 型号混淆：Buds 4 Pro 压过 Buds 4 |
| S3-03 | S3_对比选购 | 小米 13 和小米 14 哪个值得买？ | `PROD_PHONE_001`, `PROD_PHONE_003` | `GUIDE_PHONE_004`, `GUIDE_PHONE_001`, `GUIDE_PHONE_003` | 0.00 | 召回失败：具体型号对比被泛化到选购指南 |
| S4-01 | S4_价格活动 | 小米 14 Pro 现在有什么优惠活动？ | `POLICY_RET_004` | `PROD_PHONE_004`, `PROD_PHONE_003`, `GUIDE_PHONE_001` | 0.00 | 召回失败：价格活动应命中政策域，实际被产品详情吸走 |
| S4-04 | S4_价格活动 | 200 元的优惠券能用在扫地机上吗？ | `POLICY_RET_004`, `POLICY_LOG_001` | `GUIDE_GIFT_001`, `GUIDE_VAC_001`, `PROD_VAC_002` | 0.00 | 召回失败：优惠券关键词没有稳定命中活动政策 |
| S5-01 | S5_库存到货 | 小米 14 Pro 黑色款有货吗？ | `POLICY_LOG_001` | `PROD_PHONE_004`, `PROD_PHONE_003`, `PROD_PHONE_002` | 0.00 | 召回失败：库存/有货应命中物流库存政策，实际命中产品详情 |
| S5-04 | S5_库存到货 | 新款手表什么时候上市？ | `GUIDE_WATCH_001`, `POLICY_LOG_001` | `PROD_WATCH_003`, `PROD_WATCH_002`, `PROD_WATCH_001` | 0.00 | 召回失败：上市/到货语义没有拉起指南和物流政策 |
| S5-05 | S5_库存到货 | 上次缺货那款补货了吗？ | `POLICY_LOG_001` | `progress`, `POLICY_LOG_001` | 1.00 | 排序问题：`_meta/progress.md` 污染 top1 |
| S6-01 | S6_配件兼容 | 小米 14 Pro 用什么充电器？ | `PROD_PHONE_004`, `MANUAL_PHONE_001` | `PROD_PHONE_002`, `PROD_PHONE_004`, `PROD_PHONE_003` | 0.50 | 排序问题：小米 14 Pro 实体未被强 boost，错误产品详情排 top1 |
| S6-05 | S6_配件兼容 | 我有小米 13 的 67W 充电器，给小米 14 Pro 用会慢吗？ | `PROD_PHONE_001`, `PROD_PHONE_004`, `MANUAL_PHONE_001` | `PROD_PHONE_002`, `PROD_PHONE_001`, `PROD_PHONE_004` | 0.67 | 排序问题：多型号问题中无关手机详情排 top1，充电手册未进 top3 |
| S7-05 | S7_适用场景 | 我家是长条户型，扫地机会乱跑吗？ | `GUIDE_VAC_002`, `MANUAL_VAC_002` | `GUIDE_VAC_003`, `GUIDE_VAC_002` | 0.50 | 排序问题：户型/导航场景与其他扫地机指南混淆 |
| S1-09 | S1_选购推荐 | 通勤和线上会议都想用，耳机和音箱怎么搭配买？ | `GUIDE_BUDS_001`, `PROD_BUDS_003`, `PROD_SPK_002` | `GUIDE_GIFT_002`, `PROD_BUDS_001`, `MANUAL_BUDS_001` | 0.00 | 召回失败：通勤会议场景被礼物指南吸走 |
| S4-07 | S4_价格活动 | 小米平板 6 Pro 现在参考价是多少，活动价会变吗？ | `PROD_PAD_003`, `PRODUCT_MAPPING`, `POLICY_RET_004` | `product_mapping`, `PROD_PAD_002`, `PROD_PAD_003` | 0.33 | 排序/规范化问题：`product_mapping` 与 `PRODUCT_MAPPING` 大小写不一致 |
| S8-03 | S8_操作指引 | 扫地机怎么设置定时清扫？ | `MANUAL_VAC_002`, `APP_GUIDE_002` | `MANUAL_VAC_001`, `MANUAL_VAC_002` | 0.50 | 排序问题：通用扫地机手册压过定时/APP 操作手册 |
| S8-06 | S8_操作指引 | 扫地机怎么设置只扫客厅不扫卧室？ | `MANUAL_VAC_002`, `APP_GUIDE_002` | `MANUAL_VAC_001`, `MANUAL_VAC_002` | 0.50 | 排序问题：区域清扫应加强 APP/地图相关文档 |
| S9-04 | S9_配网连接 | 换了路由器，所有设备都要重新配网吗？ | `NET_GUIDE_003`, `APP_GUIDE_002` | `NET_GUIDE_001`, `FAQ_NET_001`, `NET_GUIDE_003` | 0.50 | 排序问题：换路由器场景文档已召回但未排 top1 |
| S9-07 | S9_配网连接 | 蓝牙连上了但 APP 显示离线 | `NET_GUIDE_001`, `FAQ_NET_001`, `APP_GUIDE_002` | `NET_GUIDE_002`, `APP_GUIDE_004`, `FAQ_LOCK_001` | 0.00 | 召回失败：APP 离线/蓝牙场景没有命中正确配网 FAQ |
| S10-02 | S10_APP功能 | 怎么修改收货地址？ | `APP_GUIDE_001` | `POLICY_LOG_003`, `APP_GUIDE_001` | 1.00 | 排序问题：物流改地址政策压过 APP 地址操作文档 |
| S10-03 | S10_APP功能 | APP 里怎么查扫地机的清扫记录？ | `APP_GUIDE_003`, `MANUAL_VAC_002` | `MANUAL_VAC_001`, `progress` | 0.00 | 召回失败：清扫记录应命中 APP 指南，且存在 `_meta/progress.md` 污染 |
| S10-05 | S10_APP功能 | APP 推送太多怎么关闭？ | `APP_GUIDE_005` | `APP_GUIDE_004`, `APP_GUIDE_005`, `APP_GUIDE_001` | 1.00 | 排序问题：通知/推送文档被其他 APP 指南压过 |
| S12-04 | S12_生态联动 | 门锁开门后扫地机自动暂停能实现吗？ | `AUTO_GUIDE_001`, `AUTO_GUIDE_002`, `PROD_LOCK_001`, `MANUAL_VAC_002` | `CODE_VAC_001`, `FAQ_VAC_001`, `MANUAL_VAC_001` | 0.00 | 召回失败：联动场景被扫地机故障/手册文档吸走 |
| S13-05 | S13_保养维护 | 扫地机的水箱可以用洗洁精洗吗？ | `MANUAL_VAC_003`, `MANUAL_VAC_001` | `PROD_VAC_003`, `MANUAL_VAC_003`, `PROD_VAC_001` | 0.50 | 排序问题：维护手册已召回但产品详情排 top1 |
| S13-06 | S13_保养维护 | 手表怎么深度清洁？ | `MANUAL_WATCH_001` | `MANUAL_VAC_003`, `MANUAL_WATCH_001`, `MANUAL_VAC_001` | 1.00 | 排序问题：手表实体未被强约束，扫地机维护手册排 top1 |
| S13-09 | S13_保养维护 | 扫地机刷头掉毛了还能用吗？要换吗？ | `MANUAL_VAC_003`, `FAQ_VAC_001` | `PROD_VAC_001`, `MANUAL_HEALTH_001`, `FAQ_VAC_001` | 0.50 | 排序问题：维护/耗材 FAQ 被产品详情和健康手册压过 |
| S14-01 | S14_售后政策 | 小米 14 Pro 保修期多久？ | `POLICY_WAR_001`, `POLICY_WAR_002` | `PROD_PHONE_004`, `POLICY_WAR_002`, `PROD_PHONE_003` | 0.50 | 排序问题：保修政策已召回但产品详情排 top1 |
| F1-05 | F1_故障报告 | 手表充电时发烫得厉害 | `MANUAL_WATCH_001`, `POLICY_WAR_001`, `POLICY_WAR_002` | `CODE_PHONE_001` | 0.00 | 召回失败：手表故障误召回手机故障码，设备实体错配 |
| F3-03 | F3_投诉吐槽 | 这手机用了 3 个月就卡 | `CODE_PHONE_001`, `POLICY_WAR_001`, `POLICY_WAR_002` | `MANUAL_PHONE_001`, `CODE_FW_001`, `PROD_PHONE_005` | 0.00 | 召回失败：手机卡顿投诉应命中手机故障和保修政策 |

## 5. 重点类别 badcase 细查

### 5.1 S6_配件兼容

| query_id | 用户问题 | 期望 doc_id | 实际 top3 doc_id | hit@1 | recall@3 | 错因 |
|---|---|---|---|---:|---:|---|
| S6-01 | 小米 14 Pro 用什么充电器？ | `PROD_PHONE_004`, `MANUAL_PHONE_001` | `PROD_PHONE_002`, `PROD_PHONE_004`, `PROD_PHONE_003` | 0 | 0.50 | 型号实体排序不稳，`小米 14 Pro` 没有把 `PROD_PHONE_004` 推到 top1；配件/充电手册也未进 top3 |
| S6-02 | 石头 T7 的滤芯型号是什么？ | `PROD_VAC_001`, `MANUAL_VAC_003` | `PROD_VAC_001`, `PROD_VAC_002` | 1 | 0.50 | top1 正确，但耗材/维护手册未补齐 |
| S6-03 | 我的旧充电线还能给小米 14 用吗？ | `PROD_PHONE_003`, `MANUAL_PHONE_001` | `PROD_PHONE_003`, `CODE_PHONE_001`, `PROD_PHONE_002` | 1 | 0.50 | 产品详情命中，充电兼容手册未进入 top3 |
| S6-04 | T7 的滤芯能用在 G10S Pro 上吗？ | `PROD_VAC_001`, `PROD_VAC_004`, `MANUAL_VAC_003` | `PROD_VAC_004`, `MANUAL_VAC_003`, `PROD_VAC_002` | 1 | 0.67 | 多型号兼容问题只召回部分相关产品 |
| S6-05 | 我有小米 13 的 67W 充电器，给小米 14 Pro 用会慢吗？ | `PROD_PHONE_001`, `PROD_PHONE_004`, `MANUAL_PHONE_001` | `PROD_PHONE_002`, `PROD_PHONE_001`, `PROD_PHONE_004` | 0 | 0.67 | 多实体排序错误，`PROD_PHONE_002` 干扰；充电手册缺失 |
| S6-06 | Redmi Buds 3 Pro 的耳塞套小米 Buds 4 能用吗？ | `PROD_BUDS_002`, `PROD_BUDS_003`, `MANUAL_BUDS_001` | `PROD_BUDS_002`, `PROD_BUDS_004`, `PROD_BUDS_003` | 1 | 0.67 | 耳机兼容手册未补齐，Buds 4 Pro 干扰 |
| S6-07 | 扫地机的边刷哪几个型号是通用的？ | `MANUAL_VAC_003`, `PROD_VAC_001`, `PROD_VAC_002`, `PROD_VAC_004` | `PROD_VAC_001`, `GUIDE_VAC_003`, `GUIDE_VAC_002` | 1 | 0.25 | 需要耗材通用关系文档，当前召回偏产品/指南 |

诊断：S6 的问题主要是多实体和配件手册不稳定。后续需要产品型号实体抽取、配件词 boost、`MANUAL_*` 配件/耗材文档 boost。

### 5.2 S14_售后政策

| query_id | 用户问题 | 期望 doc_id | 实际 top3 doc_id | hit@1 | recall@3 | 错因 |
|---|---|---|---|---:|---:|---|
| S14-01 | 小米 14 Pro 保修期多久？ | `POLICY_WAR_001`, `POLICY_WAR_002` | `PROD_PHONE_004`, `POLICY_WAR_002`, `PROD_PHONE_003` | 0 | 0.50 | 产品型号匹配强于保修政策，产品详情压过政策文档 |
| S14-03 | 进水了能保修吗？ | `POLICY_WAR_002`, `POLICY_WAR_004` | `POLICY_WAR_002`, `POLICY_WAR_001` | 1 | 0.50 | top1 正确，但人为损坏/进水边界政策未补齐 |
| S14-07 | 我没有发票还能保修吗？ | `POLICY_WAR_005`, `POLICY_WAR_001` | `POLICY_WAR_005`, `progress` | 1 | 0.50 | `_meta/progress.md` 污染 top3，基础保修政策未补齐 |
| S14-08 | 我在二手平台买的，能享受官方保修吗？ | `POLICY_WAR_005`, `POLICY_WAR_001` | `POLICY_WAR_005`, `POLICY_WAR_002`, `POLICY_WAR_004` | 1 | 0.50 | 转让/凭证政策命中，但基础保修政策未补齐 |

诊断：S14 的 top1 已较稳定，但 `保修期` 这类问题仍被产品详情抢占。应按 intent 把 S14 限定到 warranty/policy 域，再让产品详情只作为辅助实体证据。

### 5.3 S9_配网连接

| query_id | 用户问题 | 期望 doc_id | 实际 top3 doc_id | hit@1 | recall@3 | 错因 |
|---|---|---|---|---:|---:|---|
| S9-02 | 智能门锁配网失败怎么办？ | `NET_GUIDE_001`, `FAQ_LOCK_001`, `MANUAL_LOCK_001` | `FAQ_LOCK_001`, `FAQ_NET_001`, `CODE_LOCK_001` | 1 | 0.33 | 门锁 FAQ 命中，但通用配网指南和门锁手册缺失 |
| S9-03 | 我家是 5G WiFi，扫地机连不上 | `NET_GUIDE_002`, `FAQ_NET_001` | `NET_GUIDE_002`, `FAQ_AIR_001`, `NET_GUIDE_001` | 1 | 0.50 | 5G WiFi 命中，但通用网络 FAQ 被空气净化器 FAQ 干扰 |
| S9-04 | 换了路由器，所有设备都要重新配网吗？ | `NET_GUIDE_003`, `APP_GUIDE_002` | `NET_GUIDE_001`, `FAQ_NET_001`, `NET_GUIDE_003` | 0 | 0.50 | 换路由器场景文档已召回但未排 top1，APP 指南缺失 |
| S9-05 | 智能门锁离路由器太远连不上怎么办？ | `NET_GUIDE_001`, `NET_GUIDE_003`, `FAQ_LOCK_001` | `FAQ_LOCK_001`, `CODE_LOCK_001`, `FAQ_NET_001` | 1 | 0.33 | 门锁 FAQ 命中，但网络距离/信号指南缺失 |
| S9-06 | 扫地机一直配网失败，重启也没用 | `NET_GUIDE_001`, `NET_GUIDE_002`, `FAQ_NET_001`, `FAQ_VAC_001` | `FAQ_NET_001`, `NET_GUIDE_002`, `MANUAL_VAC_001` | 1 | 0.50 | FAQ 命中，设备手册进入但通用配网指南不足 |
| S9-07 | 蓝牙连上了但 APP 显示离线 | `NET_GUIDE_001`, `FAQ_NET_001`, `APP_GUIDE_002` | `NET_GUIDE_002`, `APP_GUIDE_004`, `FAQ_LOCK_001` | 0 | 0.00 | APP 离线/蓝牙场景召回失败，误入其他 APP/门锁 FAQ |

诊断：S9 需要把“配网失败、5G WiFi、换路由、APP 离线、蓝牙”等场景词做 keyword/BM25 精确匹配，并把 `NET_GUIDE_*`、`FAQ_NET_*`、`APP_GUIDE_*` 作为意图限定域。

### 5.4 S13_保养维护

| query_id | 用户问题 | 期望 doc_id | 实际 top3 doc_id | hit@1 | recall@3 | 错因 |
|---|---|---|---|---:|---:|---|
| S13-01 | 净化器滤芯多久换一次？ | `MANUAL_AIR_002`, `FAQ_AIR_001` | `MANUAL_AIR_002`, `PROD_AIR_001` | 1 | 0.50 | 手册命中，FAQ 未补齐 |
| S13-05 | 扫地机的水箱可以用洗洁精洗吗？ | `MANUAL_VAC_003`, `MANUAL_VAC_001` | `PROD_VAC_003`, `MANUAL_VAC_003`, `PROD_VAC_001` | 0 | 0.50 | 产品详情压过维护手册 |
| S13-06 | 手表怎么深度清洁？ | `MANUAL_WATCH_001` | `MANUAL_VAC_003`, `MANUAL_WATCH_001`, `MANUAL_VAC_001` | 0 | 1.00 | 设备类型错配，扫地机维护手册排在手表手册前 |
| S13-07 | 扫地机用了半年吸力变弱了 | `MANUAL_VAC_003`, `FAQ_VAC_001`, `CODE_VAC_001` | `FAQ_VAC_001`, `PROD_VAC_002`, `PROD_VAC_003` | 1 | 0.33 | FAQ 命中，但维护手册和故障码文档缺失 |
| S13-08 | 净化器一直亮红灯，是滤芯问题吗？ | `FAQ_AIR_001`, `MANUAL_AIR_002`, `CODE_AIR_001` | `FAQ_AIR_001`, `CODE_AIR_001` | 1 | 0.67 | FAQ 和故障码命中，滤芯手册缺失 |
| S13-09 | 扫地机刷头掉毛了还能用吗？要换吗？ | `MANUAL_VAC_003`, `FAQ_VAC_001` | `PROD_VAC_001`, `MANUAL_HEALTH_001`, `FAQ_VAC_001` | 0 | 0.50 | 产品详情和健康手册干扰，耗材维护手册未进入 top3 |

诊断：S13 的关键词很具体，例如“滤芯、刷头、水箱、深度清洁、吸力变弱”。这些词适合 BM25 和 metadata keyword boost，不应主要依赖语义向量。

### 5.5 F1_故障报告

| query_id | 用户问题 | 期望 doc_id | 实际 top3 doc_id | hit@1 | recall@3 | 错因 |
|---|---|---|---|---:|---:|---|
| F1-01 | 我的扫地机充不进电了 | `FAQ_VAC_001`, `CODE_VAC_001`, `MANUAL_VAC_001` | `FAQ_VAC_001`, `MANUAL_VAC_002`, `CODE_VAC_001` | 1 | 0.67 | 基础故障 FAQ 命中，但充电/设备手册不完整 |
| F1-02 | 净化器开机后没反应 | `FAQ_AIR_001`, `CODE_AIR_001`, `MANUAL_AIR_001` | `CODE_AIR_001`, `FAQ_AIR_001` | 1 | 0.67 | 故障码和 FAQ 命中，基础手册缺失 |
| F1-03 | 智能门锁指纹突然识别不了了 | `FAQ_LOCK_001`, `CODE_LOCK_001`, `MANUAL_LOCK_001` | `FAQ_LOCK_001`, `MANUAL_LOCK_001`, `MANUAL_LOCK_002` | 1 | 0.67 | FAQ 和手册命中，故障码文档未进入 top3 |
| F1-05 | 手表充电时发烫得厉害 | `MANUAL_WATCH_001`, `POLICY_WAR_001`, `POLICY_WAR_002` | `CODE_PHONE_001` | 0 | 0.00 | 严重实体错配：手表充电发烫被召回到手机故障码 |

诊断：F1 的主问题不是所有故障都差，而是设备类型没有强约束。`手表`、`扫地机`、`净化器`、`门锁` 应该先抽取实体域，再在对应设备的 FAQ/CODE/MANUAL 中检索。

## 6. 错因归纳

### 6.1 排序问题多于召回问题

很多样本的正确文档已经进入 top3，但没有排到 top1，例如：

- `S14-01`：`POLICY_WAR_002` 已进 top3，但 `PROD_PHONE_004` 排 top1。
- `S9-04`：`NET_GUIDE_003` 已进 top3，但 `NET_GUIDE_001` 排 top1。
- `S13-06`：`MANUAL_WATCH_001` 已进 top3，但 `MANUAL_VAC_003` 排 top1。

这说明下一步 rerank 的收益会很明显。

### 6.2 意图域过滤不足

同一个问题里有产品型号时，产品详情文档很容易抢分：

- 保修问题被产品详情抢走。
- 库存/活动问题被产品详情抢走。
- 配件问题被相近型号产品详情抢走。

需要根据 intent 做候选域过滤或加权：

| intent | 应优先域 |
|---|---|
| S6_配件兼容 | `MANUAL_*`, `PROD_*` 中的配件/充电字段 |
| S9_配网连接 | `NET_GUIDE_*`, `FAQ_NET_*`, `APP_GUIDE_*`, 设备手册 |
| S13_保养维护 | `MANUAL_*`, `FAQ_*`, `CODE_*` |
| S14_售后政策 | `POLICY_WAR_*` |
| F1_故障报告 | 对应设备的 `FAQ_*`, `CODE_*`, `MANUAL_*`, 必要时补 `POLICY_WAR_*` |

### 6.3 实体抽取和实体 boost 不足

典型错误：

- `小米 14 Pro` 问题召回到其他手机型号。
- `手表` 问题召回到手机故障码。
- `手表深度清洁` 召回到扫地机维护手册。
- `Buds 4` 被 `Buds 4 Pro` 干扰。

需要抽取产品实体、设备类型、型号后缀，并在 rerank 中加分。

### 6.4 元数据文档污染

`progress` 出现在多个结果中：

- `S5-05`：`progress` 排 top1。
- `S10-03`：`progress` 进入 top3。
- `S14-07`：`progress` 进入 top3。

建议过滤 `_meta/progress.md`，或者把 `_meta` 类文档标成不可检索。

### 6.5 doc_id 规范化问题

`S4-07` 中实际返回 `product_mapping`，期望是 `PRODUCT_MAPPING`。这可能导致评分不命中。

建议统一 doc_id 大小写，或者在评测和检索 metadata 中做规范化映射。

## 7. 下一步改造建议

阶段 3 后续实现时建议按以下优先级处理：

1. 先补 metadata：给文档标注 `intent_ids`、`product_names`、`device_type`、`doc_domain`、`keywords`。
2. 加不可检索过滤：过滤 `_meta/progress.md` 这类目录和文档。
3. 做 entity extraction：抽取产品型号、设备类型、政策词、操作词。
4. 做 intent-directed search：S14 优先搜 `POLICY_WAR_*`，S9 优先搜 `NET/FAQ/APP`，S13/F1 优先搜对应设备的 `MANUAL/FAQ/CODE`。
5. 做 rule-based rerank：实体一致、intent 一致、标题命中、关键词命中加分；设备类型冲突扣分。
6. 再跑同一份 eval，重点看 `S6/S14/S9/S13/F1` 的 hit@1 和 recall@3 是否提升。

第一轮优化目标建议：

| 指标 | 当前 | 第一轮目标 |
|---|---:|---:|
| hit@1 | 78.8% | 85%+ |
| hit@3 | 91.7% | 93%+ |
| recall@3 | 68.2% | 75%+ |
| mrr@10 | 85.4% | 88%+ |
| S6 hit@1 | 71.4% | 85%+ |
| S9 recall@3 | 45.2% | 65%+ |
| S13 hit@1 | 66.7% | 80%+ |
| F1-05 | 0 | 必须命中手表手册或保修政策 |

