# Workhunter v2.0 当前状态

更新日期：2026-10-11，Asia/Shanghai。管理版本 **1.3**；基础产品/工程合同仍为 1.1，产品选择 ABAAAAAB 不变。本文件维护当前事实；历史自验、用户结果、代码提交和运行候选分别保留。

**执行入口：开始开发、处理用户验收反馈或提交新候选前，必须读取 [本轮 R0—R5 执行计划](deliveries/M0-M1-EXECUTION-20261011.md) 和 [反馈、neat-freak 与 GitHub 收尾规则](deliveries/FEEDBACK_CLOSEOUT.md)。** 这延续既有 AGENTS→STATUS 必读链，不放宽工作包边界。

## 1. 当前结论

**M0 用户验收未通过；R0 可信治理工程完成，R1—R5 开始实施。** 两步治理 PR #25/#26 与 CI 均已核对，后续按真实目标包检查，不再使用 W00。独立 DOC 先固定 M1 写入/时间窗口合同；Site 尚是旧候选，应用修复与真实采集结果待下一批回执。治理证据见 [R0](deliveries/R0-GOVERNANCE-20261011.md)，原故障证据保留 [审查](deliveries/M0-M1-AUDIT-20261011.md)。

M0 三项 P1 [#21 主页成品布局](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/21)、[#22 开发 API 读取失败](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/22)、[#23 独立子页面](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/23) 仍 Ready/open；[#1 用户 Gate](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) 和 [#6 工程交付](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) 仍 Blocked/open。新增 [#24 工作包范围与可信治理基线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/24)，Ready/P1，先于新业务实现处理。

北京时间 2026-10-11 12:59:54 开始的真实 Site 只读检查：首页 200；health/version/目录/招聘/更新摘要/来源状态六路均 **502 `upstream_unavailable`**。已部署代理的对应分支表示上游 Content-Type 不含 `application/json`；尚不能区分失效通道、错误 origin 或异常 API 响应。日志中的 Worker outcome=ok 仅表示它正常返回了错误。不能把此现象写成正常空库；不能用旧 dataset 补作实时身份。详见 [脱敏现场证据](deliveries/evidence/M0-AUDIT-SITE-20261011.json)。

p4 禁用控件属于 M0 占位；真正的采集、非空卡片、详情与筛选由已有 M1 #7—#11 实现。带参数请求被客户端拒绝、跨午夜分页漏项、整数溢出和排序等审查发现已纳入对应执行包，不重复创建同功能 Issue。

## 2. 稳定编号与用户结果

阶段统一 M0—M4，检查点使用 Mx-yy；旧 S/G 按 [命名映射](deliveries/M_NAMING.md) 追溯，PM/W/F/D/O 标识不改。当前 [手工清单](deliveries/MANUAL_QA_M.md) 共 37 项，分阶段 7/8/8/6/8。

| 检查点 | 当前用户结论 | 下一轮操作 |
| --- | --- | --- |
| M0-01 | 未测 | 补测实际入口 |
| M0-02 | 失败 | #21 修复后原编号复验 |
| M0-03 | 阻塞 | #22 恢复后核对真实模式/身份 |
| M0-04 | 未测 | 补测刷新与重开 |
| M0-05 | 未测 | 补测手机/390px |
| M0-06 | 阻塞 | 独立核验页及真实身份材料 |
| M0-07 | 失败 | #23 三个独立页面复验 |

M1 八项全部未测。修复、自验或提交计划不改变用户结论；未复验的 Issue/Gate 保持 open。用户原话及 p1—p5 见 [原反馈汇报](deliveries/M0-FEEDBACK-20261011.md)。

## 3. 仓库、运行与数据身份

| 对象 | 当前可核验事实 |
| --- | --- |
| [仓库 / PR #20](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/20) | 应用源码在 `codex/s0-w00-site-foundation`；PR draft/open。本次计划和规则追加到该分支；最终提交/CI 回执以 PR 实际 head 为准 |
| 审查应用基线 | `241fa66d7ed12269a3d953dd846d4e073c23b31c`，M0-W00 / 0.1.0；本轮不修改应用代码 |
| 默认 main | 审查时为 `19b9cef559f503feec2e0347cf27f2b1fea5b037`，仍是旧计划，不能在该版本误审“最新实现” |
| [私有 Site](https://workhunter-v2-review.sage-candy-7999.chatgpt.site) | 保存版本 1，源码 `288063243275eeb0530cc9b9743c1d11aa4cfbde`；本轮只读探测，未发布 |
| 实时后端 / 数据 | 六路失败，当前 backend commit、dataset 和 data_mode 未取得 |
| 原交付数据身份 | `ds-05add5c6-e4e7-43a6-9bc3-89b5e4a4a10e` / empty，仅为历史空库身份，不代表当前现场回读成功 |
| [仓库看板](BOARD.md) / [路线图](ROADMAP.md) / [配置](../config/project.json) | 23 个实际 Issue：15 Backlog、4 Ready、4 Blocked，其他列 0，全部 open；PR 不计 Issue 数量 |
| 原生 GitHub Projects | 当前可用连接没有 Projects 工具，ID/URL 仍 null；[#19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) Blocked，不把仓库索引当成原生视图 |

原开发环境、隔离业务库和旧资产不在本轮写入/清理范围；当前 Site 配置与服务凭据未更改。运行宿主是否在线以及上游原始状态须在 #22 下一轮继续核验。

## 4. 下一轮顺序与排程

| 执行包 | 对应 Issue | 目标 |
| --- | --- | --- |
| R0 | #24 | 先建立实际工作包、可信目标规则及共享文件边界 |
| R1 | #22 | 恢复真实数据库→API→HTTPS→Site 读取，补错误与就绪诊断 |
| R2 | #21/#23 | 同一页面整合者完成成品主页、来源页、核验页及构建/路由；提交 M0 七项复验 |
| R3 | #7/#8 | 华工/广工真实来源、逐页提交、证据、去重/变更及 dataset 维护 |
| R4 | #9/#10 | 卡片、详情、官方原文、真实筛选、草稿/已提交状态与一致分页 |
| R5 | #11、#1/#2 | 真实两校到 Site 全链路、桌面/390px和故障恢复；M0 七项/M1 八项材料 |

目标沿用 M0 10-11、M1 10-12—10-13；R0 与现场恢复耗时是新增前置，实际开始后更新预估与依赖顺延。未发生的完成日/复验日保持空，不以目标日自动完成。
M0 发出复验后继续独立 M1；同时最多两个实施包，共享文件由一个整合者负责。M0→M1 人工顺序不变。
M2 10-14—15、M3 10-16、M4 10-17 为原后续目标，本轮不实施；正式发布 [#18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) 仍 Blocked。

## 5. 已完成验证与实际限制

本次在审查基线的隔离环境重新完成 **41 项 Python、3 项代理测试**；干净源码构建及生成 Worker 语法检查通过。故障注入另外证实客户端错误归类、路由/带参拒绝、跨午夜/整数/排序、写入约束及范围校验缺口；现有绿色测试没有覆盖这些反例。依赖弃用提示保留，不为本轮计划升级依赖。

真实 Site HTTP 结果为上文六路 502；本次没有执行浏览器用户登录、桌面/手机视觉验收，也没有取得开发宿主进程日志、实时数据库或真实官网采集结果。仅在一次性合成库验证结构反例，没有读写用户业务库。

资料修改检查与 GitHub 提交/CI 回读在本轮同步时完成，具体回执见 PR #20。本次不把应用清理或修复计划记为已经执行。

## 6. 持续反馈与历史证据

每次新反馈执行：查重定位→限域修复→局部源码清理→neat-freak 六类事实对齐→相关回归→提交/推送并回读→原编号复验，完整规则见 [FEEDBACK_CLOSEOUT](deliveries/FEEDBACK_CLOSEOUT.md)。已授权的常规清理同步无需另起确认；唯一证据/数据库/未合并工作不随清理删除。

历史证据保留：[10-10 初版交付](deliveries/S0.md)、[10-11 用户反馈](deliveries/M0-FEEDBACK-20261011.md)、[此前源码收尾与已授权重复截图清理](deliveries/M0-NEAT-20261011.md)。它们是对应时点的事实，不替代当前失败/阻塞。发布仍须全部 M0—M4 有效用户通过、必需反馈复验、版本/数据/备份与发布准备齐备。
