# Workhunter v2 任务看板

更新：2026-10-14（Asia/Shanghai）。本轮索引由PR #46的34项已回读Issue快照，加上本轮实际创建的#47—#50组成：38项Issue（不含PR），19 closed / 19 open；原有已验收项未重开。#42/#43已补充对抗式复核；#31/#12通过#49关联具体来源子任务。

当前入口：[对抗式审查与执行计划](deliveries/ADVERSARIAL-AUDIT-20261014.md) · [Codex执行提示词](deliveries/CODEX-REPAIR-20261014.md) · [本轮Roadmap](ROADMAP.md)。管理分支`codex/qa-m1-adversarial-20261014`只修改管理资料，产品修复尚未实施。

**原生同步边界：** [Project5 Board](https://github.com/users/caor3693-cmyk/projects/5/views/1)历史已建，但本轮没有可用Projects读写动作，未同步原生字段。#50为Blocked；[增量清单](deliveries/PROJECT-SYNC-20261014.json)不是成功回执。旧`config/project.json`保留上一轮快照/26项pending，不是本轮38项完整索引；以本表为本轮仓库管理状态，恢复原生权限后先对账再写回。不得改写旧Project item ID或伪造同步时间。

| Backlog | Ready | In progress | Awaiting verification | Blocked | Done |
| --- | --- | --- | --- | --- | --- |
| 3 | 6 | 2 | 1 | 7 | 19 |

Ready表示可开始对应调查/准备，不表示前置范围登记已经完成；例如#43/#42编码须先#47，真实运行核验须先#48。#17仍可准备，但M4交付不能跳过相应修复。

## 当前工作队列

| 批次/优先级 | Issue | 状态 | 执行关系与离开条件 |
| --- | --- | --- | --- |
| R0 / P1 | [#47 本轮工作包与M4治理](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/47) | Ready / open | 独立登记新编号/路径；受信目标正反测试；不改产品 |
| R0 / P1 | [#48 运行源码与部署追溯](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/48) | Ready / open | 核实9665...不可解析原因；不把9ce46...管理基线当运行版本 |
| R1 / P1 | [#43 全站官方原文](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/43) | Ready / open | 先#47范围登记；#48后真实导航矩阵，根因不预判 |
| R1 / P2必需 | [#42 首页移除最近更新](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/42) | Ready / open | 同一前端整合者在#43后处理；DOM/请求/渲染一起解除 |
| R2 / P1 | [#31 广工外九校覆盖](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/31) | In progress / open | 逐校漏斗与同口径真实前后表；不靠总量/历史/fixture凑数 |
| R2 / P1 | [#12 固定十校来源](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | In progress / open | 承接来源实施；配置由一人整合；受限校不替换 |
| R2 / P1 | [#49 广州大学列表发现子任务](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/49) | Ready / open | 父#31/#12；首页有限发现已定位，公开完整列表可达性待核实 |
| R3 | [#15 自然调度与无变化材料](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | Awaiting verification / open | M3-04缺真实完整范围无变化材料，其余既有通过保留 |
| R3/R4 | [#17 首版整合与发布准备](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | Ready / open | 汇总#43/#42/#31/#15/#48；新私有Site与当前快照恢复，#47先登记W06 |
| 并行 / P2 | [#50 原生Project待同步](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/50) | Blocked / open | 原生通道不可用；旧pending与新增项逐项回读前不称已同步 |

最多两条独立实施线；共享文件单一整合者。修复PR用Refs，自验后Awaiting verification，用户按原编号通过才Done。七自然日不足如实披露，不擅自增设额外硬Gate。

## 完整Issue索引

| 阶段 | Issue | 状态 | 当前依据 |
| --- | --- | --- | --- |
| M0 | [#1 工程与Site验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | Done / closed | M0历史通过 |
| M1 | [#2 两校手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | Blocked / open | #31中的M1两校部分及#43；不要求先做完M2九校 |
| M2 | [#3 十校与维护验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | Blocked / open | M1前门、覆盖#31及首页#42 |
| M3 | [#4 持续更新与恢复验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | Blocked / open | 前门及M3-04真实材料 |
| M4 | [#5 最终手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | Backlog / open | M4未交付，不能沿用旧默认通过 |
| M0 | [#6 工程骨架与隔离边界](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | Done / closed | 历史通过 |
| M1 | [#7 华工广工列表发现](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7) | Blocked / open | 发现已实现，当前覆盖反馈沿用#31 |
| M1 | [#8 核心事实与去重](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | Done / closed | 历史通过 |
| M1 | [#9 卡片/详情/原文](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | Blocked / open | 详情子项通过，原文#43失败 |
| M1 | [#10 筛选与一致分页](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | Done / closed | v5已交付项默认通过 |
| M1 | [#11 桌面手机/键盘/错误](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | Done / closed | 历史通过；真实导航另核#43 |
| M2 | [#12 固定十校来源](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | In progress / open | 本轮扩源与#49 |
| M2 | [#13 受保护维护/补录/纠错](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | Done / closed | v5已交付项默认通过 |
| M2 | [#14 更新摘要与待办](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | Done / closed | 原功能通过；首页变更#42独立 |
| M3 | [#15 自然刷新与恢复](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | Awaiting verification / open | 缺整源无变化材料 |
| M3 | [#16 备份恢复与只读MCP](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | Done / closed | 旧恢复结果通过；个人客户端未配置不冒称已配 |
| M4 | [#17 Site整合与发布准备](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | Ready / open | 新修复集成后交付，不先切正式站 |
| RELEASE | [#18 正式上线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | Blocked / open | 有效Gate/必需反馈条件未齐 |
| M0 | [#19 原生Project创建](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) | Done / closed | 历史创建完成；当前同步另列#50 |
| M0 | [#21 首页布局](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/21) | Done / closed | 历史通过 |
| M0 | [#22 Site读取链路](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/22) | Done / closed | 卡片恢复已确认；非当前故障证据 |
| M0 | [#23 独立页面](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/23) | Done / closed | 历史通过 |
| M0 | [#24 可信范围治理](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/24) | Done / closed | 旧机制完成；本轮增量#47 |
| M1 | [#29 详情移除技术信息](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/29) | Done / closed | 历史通过，不因#43重开 |
| M1 | [#30 切校区刷新延迟](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/30) | Done / closed | v5已交付项默认通过，保留回归 |
| M1 | [#31 广工外九校覆盖](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/31) | In progress / open | 同口径逐校扩源，含#49子任务 |
| M2 | [#32 M2可信范围/合同](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/32) | Done / closed | 历史通过，不冒名给新功能授权 |
| M2 | [#33 队列饥饿/续页](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/33) | Done / closed | 历史通过，无新复现不重开 |
| M2 | [#34 字段/相关性语义](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/34) | Done / closed | 历史通过，扩源回归反例 |
| M2 | [#35 跨公告材料错绑](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/35) | Done / closed | 历史通过，保留适用性回归 |
| M2 | [#42 首页移除最近更新](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/42) | Ready / open | 已补依赖清理与回归要求，未改代码 |
| M1 | [#43 全站官方原文](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/43) | Ready / open | 已补真实导航与版本定位，未确认根因 |
| Future | [#44 招聘日程表](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/44) | Backlog / open | 下次实际软件交付时讨论，本轮不开发 |
| Future | [#45 AI改简历](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/45) | Backlog / open | 同上，不创建重复提醒 |
| 治理 | [#47 本轮工作包增量](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/47) | Ready / open | 本轮新增，先独立治理后功能实施 |
| 交付 | [#48 运行版本追溯](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/48) | Ready / open | 本轮新增，404/422原因待核实 |
| M2 | [#49 广州大学列表发现](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/49) | Ready / open | 本轮新增，有限首页发现子任务 |
| 管理 | [#50 Project原生同步](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/50) | Blocked / open | 本轮新增，当前无原生写通道 |

v5人工原始结果保留于[上一轮反馈](deliveries/M1-M3-FEEDBACK-20261014.md)。本轮文档交付不是软件修复或新Site验收通过。
