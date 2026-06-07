# Badcase Report 2026-06-06

## Summary

| Item | Value |
|---|---:|
| Run ID | `v1_customer_hand_20260604_205942` |
| Source JSONL | `D:\code4\llm-universe-main\customer_simple\ragenteval-main\eval\runs\v1_customer_hand_20260604_205942.jsonl` |
| Badcase rows | 40 |
| Rows with error_type | 40 |
| Rows marked miss | 11 |

## Error Type Distribution

| Error Type | Count |
|---|---:|
| `RERANK_ERROR` | 29 |
| `RETRIEVAL_MISS` | 11 |

## Badcases

### RERANK_ERROR

| Case | Hit | Route | Trace | Expected Intent | Predicted Intent | Expected Docs | Retrieved Docs |
|---|---|---|---|---|---|---|---|
| F1-01 | true | - | 7bd3f7647ac746a9afa477cabf936a98 | F1_故障报告 | - | FAQ_VAC_001, CODE_VAC_001, MANUAL_VAC_001 | CODE_FW_001, FAQ_VAC_001, CODE_PHONE_001, CODE_VAC_001 |
| F1-04 | true | - | 6ff38168288e4794b886a269dd927d24 | F1_故障报告 | - | CODE_VAC_001, FAQ_VAC_001 | CODE_FW_001, FAQ_VAC_001, CODE_VAC_001 |
| F1-05 | true | - | 2a2356881f224b71a8b10bc79223099b | F1_故障报告 | - | MANUAL_WATCH_001, POLICY_WAR_001, POLICY_WAR_002 | CODE_PHONE_001, MANUAL_WATCH_001 |
| F3-03 | true | - | 32657b1df151471eab15852abdd70215 | F3_投诉吐槽 | - | CODE_PHONE_001, POLICY_WAR_001, POLICY_WAR_002 | MANUAL_PHONE_001, CODE_PHONE_001, CODE_FW_001 |
| S1-09 | true | - | 17267dfb2f874947a049fceab76f6474 | S1_选购推荐 | - | GUIDE_BUDS_001, PROD_BUDS_003, PROD_SPK_002 | GUIDE_GIFT_002, PROD_SPK_001, GUIDE_BUDS_001, PROD_SPK_003 |
| S10-02 | true | - | ae38618c707f4d10a13cd3e51088fb2f | S10_APP功能 | - | APP_GUIDE_001 | POLICY_LOG_003, APP_GUIDE_001 |
| S10-04 | true | - | ce55b720dab549b0ae2a62ab42baf403 | S10_APP功能 | - | APP_GUIDE_002 | APP_GUIDE_004, APP_GUIDE_002 |
| S12-02 | true | - | 31ecf1f4fecc460ab69441cf07473f4f | S12_生态联动 | - | AUTO_GUIDE_001, AUTO_GUIDE_002, PROD_LIGHT_001, PROD_LOCK_001 | MANUAL_LOCK_001, AUTO_GUIDE_001, CODE_LOCK_001 |
| S14-05 | true | - | ed26fe9ca2b4464b83fcc95507753aec | S14_售后政策 | - | POLICY_WAR_002, POLICY_WAR_001 | POLICY_WAR_004, POLICY_WAR_002, POLICY_WAR_001 |
| S14-08 | true | - | a87cff0c837c49fd98d934175e39c0bf | S14_售后政策 | - | POLICY_WAR_005, POLICY_WAR_001 | POLICY_WAR_004, POLICY_WAR_005 |
| S15-02 | true | - | cb59b3289f844308ac7448524b8c4a16 | S15_退换货 | - | POLICY_RET_002 | POLICY_RET_001, POLICY_RET_002 |
| S2-03 | true | - | 6b24aea5ba014a17bc69831b8c26c348 | S2_参数咨询 | - | PROD_AIR_003 | PROD_AIR_002, PROD_AIR_003, GUIDE_AIR_001, PROD_AIR_001 |
| S2-06 | true | - | 9c737f4fbb1442ee8ec897ea730ed40d | S2_参数咨询 | - | PROD_WATCH_002, MANUAL_WATCH_001 | PROD_WATCH_001, PROD_WATCH_002, GUIDE_WATCH_001 |
| S2-07 | true | - | 484f849728b04b9e87b775ccaa953fce | S2_参数咨询 | - | PROD_PHONE_003, CODE_PHONE_001 | PROD_WATCH_002, CODE_PHONE_001, PROD_WATCH_003, PROD_LIFE_005, PROD_PHONE_001 |
| S2-09 | true | - | 31ade75897b64e4dbde6d6e221f2bc05 | S2_参数咨询 | - | PROD_PAD_002 | PROD_PAD_003, PROD_PAD_001, PROD_PAD_002 |
| S3-03 | true | - | 5eb581f2bbd44151b4661da900073b0e | S3_对比选购 | - | PROD_PHONE_001, PROD_PHONE_003 | GUIDE_PHONE_004, GUIDE_PHONE_001, GUIDE_PHONE_003, PROD_PHONE_001 |
| S3-06 | true | - | 194506fdc6994adaa03b035fbea8d416 | S3_对比选购 | - | PROD_PHONE_003, PROD_PHONE_004, PRODUCT_MAPPING | GUIDE_PHONE_004, PROD_PHONE_003, PROD_PHONE_004, GUIDE_PHONE_003, GUIDE_PHONE_001 |
| S6-01 | true | - | cb3ff97608e44b62ac8f988a05f67694 | S6_配件兼容 | - | PROD_PHONE_004, MANUAL_PHONE_001 | PROD_BOOK_001, PROD_PHONE_002, PROD_PHONE_004, PROD_PHONE_003, PROD_PHONE_001 |
| S6-03 | true | - | ba6933d78bb347c0b2f26e6e8fb4e559 | S6_配件兼容 | - | PROD_PHONE_003, MANUAL_PHONE_001 | PROD_LIFE_005, PROD_PHONE_003, PROD_PHONE_002, PROD_BOOK_001 |
| S6-05 | true | - | 7ede236a19944f44b36516ea95b37097 | S6_配件兼容 | - | PROD_PHONE_001, PROD_PHONE_004, MANUAL_PHONE_001 | CODE_PHONE_001, PROD_PHONE_001, PROD_PHONE_002, PROD_PHONE_004, PROD_PHONE_005 |
| S7-02 | true | - | 855514f5e1484814bdcbc5cf765f7629 | S7_适用场景 | - | PROD_LOCK_001, MANUAL_LOCK_001 | AUTO_GUIDE_001, FAQ_LOCK_001, MANUAL_LOCK_001, CODE_LOCK_001 |
| S7-05 | true | - | 635f9ca0d0d6482aaf85f16eb3aec07b | S7_适用场景 | - | GUIDE_VAC_002, MANUAL_VAC_002 | GUIDE_VAC_003, GUIDE_VAC_002, GUIDE_VAC_001 |
| S8-02 | true | - | 29fa49132bc34f62bc975afa213e9a07 | S8_操作指引 | - | MANUAL_SPK_001 | PROD_SPK_001, MANUAL_SPK_001 |
| S8-06 | true | - | 160eeff7f8d4481fb9029f8ff73b076f | S8_操作指引 | - | MANUAL_VAC_002, APP_GUIDE_002 | MANUAL_VAC_001, MANUAL_VAC_002, GUIDE_VAC_003 |
| S9-01 | true | - | 20f61c9196f34120ae9d60696173fdd6 | S9_配网连接 | - | NET_GUIDE_001, MANUAL_VAC_001 | PROD_VAC_003, NET_GUIDE_001, MANUAL_VAC_001 |
| S9-03 | true | - | e5742a66998840a7ba5bc3e7c0853788 | S9_配网连接 | - | NET_GUIDE_002, FAQ_NET_001 | PROD_VAC_003, NET_GUIDE_002, FAQ_AIR_001, CODE_FW_001 |
| S9-05 | true | - | 5b9493746a9e4532ba2c64f391d134fb | S9_配网连接 | - | NET_GUIDE_001, NET_GUIDE_003, FAQ_LOCK_001 | CODE_LOCK_001, NET_GUIDE_003, FAQ_LOCK_001, AUTO_GUIDE_001 |
| S9-06 | true | - | c43af67845bc464185840004ecce8feb | S9_配网连接 | - | NET_GUIDE_001, NET_GUIDE_002, FAQ_NET_001, FAQ_VAC_001 | CODE_FW_001, CODE_AIR_001, PROD_VAC_003, FAQ_NET_001, FAQ_AIR_001 |
| S9-07 | true | - | 8e648acd8340443790907c7f677501bd | S9_配网连接 | - | NET_GUIDE_001, FAQ_NET_001, APP_GUIDE_002 | FAQ_AIR_001, NET_GUIDE_003, NET_GUIDE_001, FAQ_NET_001 |

#### Case `F1-01`

- Question: 我的扫地机充不进电了
- Answer: -

#### Case `F1-04`

- Question: 扫地机扫一会就停，提示故障 E5
- Answer: -

#### Case `F1-05`

- Question: 手表充电时发烫得厉害
- Answer: -

#### Case `F3-03`

- Question: 这手机用了 3 个月就卡
- Answer: -

#### Case `S1-09`

- Question: 通勤和线上会议都想用，耳机和音箱怎么搭配买？
- Answer: -

#### Case `S10-02`

- Question: 怎么修改收货地址？
- Answer: -

#### Case `S10-04`

- Question: 怎么把账号关联给家人共用？
- Answer: -

#### Case `S12-02`

- Question: 怎么让灯和门锁联动？
- Answer: -

#### Case `S14-05`

- Question: 电池衰减算保修吗？
- Answer: -

#### Case `S14-08`

- Question: 我在二手平台买的，能享受官方保修吗？
- Answer: -

#### Case `S15-02`

- Question: 怎么申请退货？
- Answer: -

#### Case `S2-03`

- Question: 米家空气净化器 4 Pro 适合多大面积？
- Answer: -

#### Case `S2-06`

- Question: 小米手表 S2 防水吗？能游泳戴吗？
- Answer: -

#### Case `S2-07`

- Question: 小米 14 充电 30 分钟能充多少？
- Answer: -

#### Case `S2-09`

- Question: 小米平板 6 看视频能撑多久？
- Answer: -

#### Case `S3-03`

- Question: 小米 13 和小米 14 哪个值得买？
- Answer: -

#### Case `S3-06`

- Question: 我在小米 14 和 14 Pro 之间纠结，多花 1000 值吗？
- Answer: -

#### Case `S6-01`

- Question: 小米 14 Pro 用什么充电器？
- Answer: -

#### Case `S6-03`

- Question: 我的旧充电线还能给小米 14 用吗？
- Answer: -

#### Case `S6-05`

- Question: 我有小米 13 的 67W 充电器，给小米 14 Pro 用会慢吗？
- Answer: -

#### Case `S7-02`

- Question: 智能门锁停电了能用吗？
- Answer: -

#### Case `S7-05`

- Question: 我家是长条户型，扫地机会乱跑吗？
- Answer: -

#### Case `S8-02`

- Question: 智能音箱怎么调音量？
- Answer: -

#### Case `S8-06`

- Question: 扫地机怎么设置只扫客厅不扫卧室？
- Answer: -

#### Case `S9-01`

- Question: 扫地机怎么连 WiFi？
- Answer: -

#### Case `S9-03`

- Question: 我家是 5G WiFi，扫地机连不上
- Answer: -

#### Case `S9-05`

- Question: 智能门锁离路由器太远连不上怎么办？
- Answer: -

#### Case `S9-06`

- Question: 扫地机一直配网失败，重启也没用
- Answer: -

#### Case `S9-07`

- Question: 蓝牙连上了但 APP 显示离线
- Answer: -

### RETRIEVAL_MISS

| Case | Hit | Route | Trace | Expected Intent | Predicted Intent | Expected Docs | Retrieved Docs |
|---|---|---|---|---|---|---|---|
| S15-05 | false | - | 8e7879d50e9c42f48f3aafd39f4bc9a6 | S15_退换货 | - | POLICY_RET_003, POLICY_RET_002 | - |
| S16-06 | false | - | aa2759e16c0c494da5043c7d3dc4c92a | S16_物流配送 | - | POLICY_LOG_003 | POLICY_RET_003 |
| S2-08 | false | - | 8da47f5e953b476b9d4386f5823b917c | S2_参数咨询 | - | PROD_VAC_003 | - |
| S4-01 | false | - | 81f8733e0e6d48c3a716ae9b2ee393df | S4_价格活动 | - | POLICY_RET_004 | PROD_PHONE_004, PROD_PHONE_003, GUIDE_PHONE_004, PROD_BOOK_001 |
| S4-03 | false | - | 3c6a073926eb4aa086ca3f85e6f1772b | S4_价格活动 | - | POLICY_RET_004, GUIDE_PHONE_001 | - |
| S4-04 | false | - | 9ffcec7ec5e64123a5b876e238b97dfe | S4_价格活动 | - | POLICY_RET_004, POLICY_LOG_001 | GUIDE_VAC_003, GUIDE_VAC_002 |
| S5-01 | false | - | 95d3797aff4441629dc1df0f8c60eeaf | S5_库存到货 | - | POLICY_LOG_001 | PROD_PHONE_004, PROD_PHONE_003, PROD_BOOK_001, PROD_PHONE_002 |
| S5-04 | false | - | 01767e866c3e491fbbca9798c5730bee | S5_库存到货 | - | GUIDE_WATCH_001, POLICY_LOG_001 | - |
| S5-05 | false | - | 8c0b2cf061c140c0be7d9efafd36f785 | S5_库存到货 | - | POLICY_LOG_001 | - |
| S6-02 | false | - | b67b0bc60b6949ae9c2162a4f363a937 | S6_配件兼容 | - | PROD_VAC_001, MANUAL_VAC_003 | - |
| S9-02 | false | - | ff0b29237cd947f68d790f1bf49360e8 | S9_配网连接 | - | NET_GUIDE_001, FAQ_LOCK_001, MANUAL_LOCK_001 | CODE_LOCK_001, NET_GUIDE_003 |

#### Case `S15-05`

- Question: 退货运费谁出？
- Answer: -

#### Case `S16-06`

- Question: 签收时发现包装破损怎么办？
- Answer: -

#### Case `S2-08`

- Question: 石头 G10 在地毯上吸力会下降吗？
- Answer: -

#### Case `S4-01`

- Question: 小米 14 Pro 现在有什么优惠活动？
- Answer: -

#### Case `S4-03`

- Question: 学生有优惠吗？
- Answer: -

#### Case `S4-04`

- Question: 200 元的优惠券能用在扫地机上吗？
- Answer: -

#### Case `S5-01`

- Question: 小米 14 Pro 黑色款有货吗？
- Answer: -

#### Case `S5-04`

- Question: 新款手表什么时候上市？
- Answer: -

#### Case `S5-05`

- Question: 上次缺货那款补货了吗？
- Answer: -

#### Case `S6-02`

- Question: 石头 T7 的滤芯型号是什么？
- Answer: -

#### Case `S9-02`

- Question: 智能门锁配网失败怎么办？
- Answer: -
