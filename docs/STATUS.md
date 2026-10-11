# Workhunter v2.0 当前状态

更新日期：2026-10-11，Asia/Shanghai。管理版本 **1.3**；基础产品1.1、工程合同1.2，产品选择 ABAAAAAB 不变。本文件维护当前事实；历史自验、用户结果、代码提交和运行候选分别保留。

**执行入口：开始开发、处理用户验收反馈或提交新候选前，必须读取 [本轮 R0—R5 执行计划](deliveries/M0-M1-EXECUTION-20261011.md) 和 [反馈、neat-freak 与 GitHub 收尾规则](deliveries/FEEDBACK_CLOSEOUT.md)。** 这延续既有 AGENTS→STATUS 必读链，不放宽工作包边界。

## 1. 当前结论

**M0 修复候选已实际部署并发出七项复验；用户原结论保留。M1 已完成两校真实采集与读取查询工程，R5 正在补齐最终验收材料和同一 Site 候选。** 当前业务 PR 为 [#28](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/28)，实际治理目标 `codex/m0-m1-governance-20261011` / `ae261c856761f84904430211b82ac7a42f689e4e`。完整集成声明 R1/R2/W01-R3/W02-R4/R5，后续不再按 W00 检查。

M0 修复源码 `ce6d41f82eeda7f08ecbd9f522a9562af137b1c5`，CI [38116927372](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38116927372) success；私有 Site 保存版本2，六个公开读取路径均200。实际浏览器三页导航/直接访问/刷新/后退、390px及本轮独立上游停启恢复通过工程自验。七项已发 [#1 回执](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1#issuecomment-6106136453)，材料见 [M0复验包](deliveries/M0-RETEST-20261011.md)。#6/#21/#22/#23/#24 为 Awaiting verification/open；#1仍Blocked/open。

M1 新独立候选库 schema2 / real，dataset `ds-171a2a00-d21e-448f-9f6c-ee236af1bc2f`，真实记录132条（华工28、广工104）。14:39—14:41 两轮有限采集，每轮4栏目/8列表页/48详情；二刷新增0/修改0。未知字段首次补全记解析完善，官方变化0；本轮早期错误分类的独立库和历史保留，未改写为最终证据。[实际材料、哈希和样本](deliveries/evidence/M1-REAL-SOURCES-20261011.json) 与隔离样例分别记录。华工统一入口受限，仅学院补充公开栏目；广工三个公开栏目部分覆盖，其余八校尚未采集。#7—#11 实施中/open，M1八项全部未测，Gate待M0前门。

R0治理与独立DOC证据见 [R0](deliveries/R0-GOVERNANCE-20261011.md)。PR #26/#27 随专用目标快进被GitHub标记merged；main与PR #20未合并。平台分支保护查询404，不宣称已有保护强制。最多两个实施包，共享文件由单一整合者负责。

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

## 3. 仓库、运行与数据身份（原审查现场）

| 对象 | 当前可核验事实 |
| --- | --- |
| [仓库 / PR #20](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/20) | 应用源码在 `codex/s0-w00-site-foundation`；PR draft/open。本次计划和规则追加到该分支；最终提交/CI 回执以 PR 实际 head 为准 |
| 审查应用基线 | `241fa66d7ed12269a3d953dd846d4e073c23b31c`，M0-W00 / 0.1.0；原审查未修改应用代码 |
| 默认 main | 审查时为 `19b9cef559f503feec2e0347cf27f2b1fea5b037`，仍是旧计划，不能在该版本误审“最新实现” |
| [私有 Site](https://workhunter-v2-review.sage-candy-7999.chatgpt.site) | 保存版本 1，源码 `288063243275eeb0530cc9b9743c1d11aa4cfbde`；本轮只读探测，未发布 |
| 实时后端 / 数据 | 六路失败，当前 backend commit、dataset 和 data_mode 未取得 |
| 原交付数据身份 | `ds-05add5c6-e4e7-43a6-9bc3-89b5e4a4a10e` / empty，仅为历史空库身份，不代表当前现场回读成功 |
| [仓库看板](BOARD.md) / [路线图](ROADMAP.md) / [配置](../config/project.json) | 23 个实际 Issue：15 Backlog、4 Ready、4 Blocked，其他列 0，全部 open；PR 不计 Issue 数量 |
| 原生 GitHub Projects | 当前可用连接没有 Projects 工具，ID/URL 仍 null；[#19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) Blocked，不把仓库索引当成原生视图 |

上表仅保留原审查现场。当前M0 Site版本2与新M1工程库分别见第1节；二者此时不是同一运行数据。M0 empty/schema1原库保留，M1候选通过只读备份到新路径再显式迁移。服务令牌留在服务端；旧项目、用户业务库及原始证据未写入或清理。

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

R1/R2：37项Node、3项Windows启动检查与干净构建通过，Site实际正常→断连→旧结果/错误→恢复另有回执。R3：来源/写服务63项通过；R4：Node65项通过，读取边界针对真实材料ID/链接/归属、缺观察、跨午夜、整数上界和日期排序补反例。最终整批、Site与CI结果将随同一候选回执补齐，不沿用历史41项替代新增反例。

本机宿主与临时HTTPS通道需保持运行，不是M3自然调度。附件仅取得本条HTML披露的链接，其正文尚未解析；岗位片段限于本公告公开文本，无独立岗位实体。华工受限入口未绕过，有限分页不累计缺失或推断取消。实际neat-freak 3.0.1按四参考与六面核对，唯一材料/数据库/备份/凭据保留；长期记忆未写入。

## 6. 持续反馈与历史证据

每次新反馈执行：查重定位→限域修复→局部源码清理→neat-freak 六类事实对齐→相关回归→提交/推送并回读→原编号复验，完整规则见 [FEEDBACK_CLOSEOUT](deliveries/FEEDBACK_CLOSEOUT.md)。已授权的常规清理同步无需另起确认；唯一证据/数据库/未合并工作不随清理删除。

历史证据保留：[10-10 初版交付](deliveries/S0.md)、[10-11 用户反馈](deliveries/M0-FEEDBACK-20261011.md)、[此前源码收尾与已授权重复截图清理](deliveries/M0-NEAT-20261011.md)。它们是对应时点的事实，不替代当前失败/阻塞。发布仍须全部 M0—M4 有效用户通过、必需反馈复验、版本/数据/备份与发布准备齐备。
