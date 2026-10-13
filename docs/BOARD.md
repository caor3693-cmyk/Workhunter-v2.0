# Workhunter v2 任务看板

核对日：2026-10-12。30个Issue、21open/9closed，状态来自原生Project5回读；用户历史通过/失败保留。候选工程完成不自动关闭业务Issue。

2026-10-13增量：#15/#16的自然调度、备份恢复与只读MCP已实现并自验，#12新增纯符号地点修复；neat-freak收尾后已上传[治理#39](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/39)、[来源#40](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/40)、[M3#41](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/41)三份draft PR。以下原生状态是10-12快照，本轮未修改业务Issue/Project字段；PR上传不冒充状态变更。M3六项用户未测，详见[M3核验包](deliveries/M3-REVIEW-20261013.md)及[收尾回执](deliveries/M3-NEAT-20261013.md)。

| Backlog | Ready | In progress | Awaiting verification | Blocked | Done |
| --- | --- | --- | --- | --- | --- |
| 5 | 0 | 9 | 1 | 6 | 9 |

| 阶段 | Issue | 状态 | 原目标 | 当前依据 |
| --- | --- | --- | --- | --- |
| M0 | [#1 [M0] 工程与 Site 入口手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | Done / closed | 2026-10-11 | 第二轮用户通过，历史结果保留 |
| M1 | [#2 [M1] 两校真实招聘流程手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | Blocked / open | 2026-10-13 | M1修复已实现；Site交付与用户复验待完成 |
| M2 | [#3 [M2] 十校与维护功能手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | Blocked / open | 2026-10-15 | M2工程完整；前序M1 Gate及Site交付待完成 |
| M3 | [#4 [M3] 持续更新与恢复手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | Backlog / open | 2026-10-16 | 本机证据已按六项列明；M3-04整源无变化样本/Site待补，用户及前序Gate未确认；远端未改 |
| M4 | [#5 [M4] 首版最终手工验收与上线门禁](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | Backlog / open | 2026-10-17 | 历史结果保留；后续阶段以实际证据与Gate为准 |
| M0 | [#6 [M0] [PM-W00] 工程骨架、隔离运行边界与 Site 核验入口](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | Done / closed | 2026-10-11 | 第二轮用户通过，历史结果保留 |
| M1 | [#7 [M1] [PM-W01-A] 华工广工列表发现与逐页持久化](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7) | Blocked / open | 2026-10-12 | 队列/两校真实样本完成；等待对应M1复验 |
| M1 | [#8 [M1] [PM-W01-B] 日期地点证据、去重及核心详情补全](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | Done / closed | 2026-10-13 | 第二轮用户通过，历史结果保留 |
| M1 | [#9 [M1] [PM-W02-A] 最小卡片、公告简要详情与官方原文](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | Blocked / open | 2026-10-13 | 简洁详情/材料适用完成；等待M1-05复验 |
| M1 | [#10 [M1] [PM-W02-B] 学校校区、相关性筛选与一致分页](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | Blocked / open | 2026-10-13 | 独立加载/一致分页及本机测量完成；远程性能待测 |
| M1 | [#11 [M1] [PM-W02-C] 桌面手机、键盘与加载错误状态](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | Done / closed | 2026-10-13 | 第二轮用户通过，历史结果保留 |
| M2 | [#12 [M2] [PM-W03] 固定十校来源扩展与真实范围状态](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | In progress / open | 2026-10-15 | 固定十校有限实现，四校最低样本成立；Site待交付 |
| M2 | [#13 [M2] [PM-W04-A] 受保护维护页、官方补录纠错与撤回](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | In progress / open | 2026-10-15 | 受保护维护与隔离生产流程已实现，用户未测 |
| M2 | [#14 [M2] [PM-W04-B] 真实更新摘要与来源维护待办](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | In progress / open | 2026-10-15 | 真实摘要/维护分组/处理历史已实现，用户未测 |
| M3 | [#15 [M3] [PM-W05-A] 自然自动刷新、断点续跑与失败恢复](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | Backlog / open | 2026-10-16 | 本机实现/审查、r3真实自然运行完成；r4下次17:29，长期观察待完成；远端未改 |
| M3 | [#16 [M3] [PM-W05-B] 备份恢复、版本对账与只读 MCP](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | Backlog / open | 2026-10-16 | 本机新路径恢复重启/API/实际stdio完成；独立raw依赖已核验，Site/用户待验；远端未改 |
| M4 | [#17 [M4] [PM-W06] Site 全流程复核与正式发布准备](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | Backlog / open | 2026-10-17 | 历史结果保留；后续阶段以实际证据与Gate为准 |
| Release | [#18 [PM-RELEASE] 全部人工 Gate 通过后的正式上线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | Blocked / open | None | 历史结果保留；后续阶段以实际证据与Gate为准 |
| M0 | [#19 [M0] [PM-SETUP] 建立 GitHub Project 原生 Board 与 Roadmap](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) | Done / closed | 2026-10-11 | native_project_fields_views_and_all_items_verified |
| M0 | [#21 [M0-02][M0-06] 首页使用成品布局，移出开发说明与核验框](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/21) | Done / closed | 2026-10-11 | 第二轮用户通过，历史结果保留 |
| M0 | [#22 [M0-03][M0-06] Site读取开发API失败，目录与数据身份不可核验](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/22) | Done / closed | 2026-10-11 | 第二轮用户通过，历史结果保留 |
| M0 | [#23 [M0-07] 招聘发现、来源状态与核验改为独立子页面](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/23) | Done / closed | 2026-10-11 | 第二轮用户通过，历史结果保留 |
| M0 | [#24 [M0→M1] 工作包范围校验与可信治理基线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/24) | Done / closed | 2026-10-11 | trusted_governance_technical_review |
| M1 | [#29 [M1-05] 简要详情移除定位证据与内部技术信息](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/29) | In progress / open | 2026-10-13 | 内部技术证据移出访客详情；390px本机通过 |
| M1 | [#30 [M1-06] 校区切换后刷新延迟：测量并定位原因](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/30) | In progress / open | 2026-10-13 | 真实本机60次分段测量已归档；远程待测 |
| M1 | [#31 [M1-01] 下一轮提供多校电气相关真实验收样本](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/31) | In progress / open | 2026-10-15 | M1两校及M2四校最低材料分别成立；Gate分段确认 |
| M2 | [#32 [M1→M2] 工作包登记与共享合同可信基线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/32) | Awaiting verification / open | 2026-10-13 | GOV36/DOC37独立审查与可信CI完成；不代表产品Gate |
| M2 | [#33 [M1-01/04] 修复跨轮详情任务饥饿与列表续页停滞](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/33) | In progress / open | 2026-10-13 | 跨轮公平详情及续页反例通过 |
| M2 | [#34 [M1-03/08] 修复电气相关性、工作地点与未披露状态的证据语义](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/34) | In progress / open | 2026-10-13 | 字段/相关性语义及真实定向修订完成 |
| M2 | [#35 [M1-05][M2-05/06] 修复跨公告材料错绑及后续详情失效](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/35) | In progress / open | 2026-10-13 | 材料适用、隔离迁移与撤回边界通过 |

[当前状态](STATUS.md) · [M1复验](deliveries/M1-SITE-RECHECK-20261012.md) · [M2完整包](deliveries/M2-REVIEW-20261012.md)。Gate按M0→M1→M2→M3→M4。#31两校M1与三校M2分别核验，不形成阶段循环依赖；#18仍Blocked。

本机M3业务实施已冻结，QA-M3由root收尾；任何时刻最多两个实施包，共享文件单一整合。既有原生Board/Roadmap和Done项保留，本轮未外发更新。
