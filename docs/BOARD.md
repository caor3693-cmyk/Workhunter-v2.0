# Workhunter v2 任务看板

更新：2026-10-14（Asia/Shanghai）。GitHub原生Issue逐项回读39项（不含PR）：19 closed / 20 open。旧已通过任务保留，不重开。当前执行结果见[修复交付](deliveries/REPAIR-DELIVERY-20261014.md)与[STATUS](STATUS.md)。

#42/#49/#52已实际修复，#48追溯取得实体映射，均待用户原编号复验；#47独立治理/DOC经复核及CI进入可信目标。#43浏览器策略阻塞真实复现，未改原文源码；#15/M3-04在NCSS明确登录限制处停止，仍缺完整范围无变化材料。#17新版私有Site/当前快照整合包正在最终身份回读。#31/#12逐校表已交，母单覆盖仍In progress。

| Backlog | Ready | In progress | Awaiting verification | Blocked | Done |
| --- | --- | --- | --- | --- | --- |
| 3 | 0 | 3 | 5 | 9 | 19 |

[原生Project5](https://github.com/users/caor3693-cmyk/projects/5/views/1) 本轮GraphQL实测INSUFFICIENT_SCOPES（缺read:project），没有取得字段/选项/条目、零写入。#50Blocked，精确31pending见[回执](deliveries/PROJECT-SYNC-EXECUTION-20261014.json)；此表不冒充原生同步。旧config/project.json为10-12历史快照/旧pending，item ID原样保留。

| 阶段 | Issue | 当前实际状态 |
| --- | --- | --- |
| m0 | [#1 [M0] 工程与 Site 入口手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | Done / closed |
| m1 | [#2 [M1] 两校真实招聘流程手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | Blocked / open |
| m2 | [#3 [M2] 十校与维护功能手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | Blocked / open |
| m3 | [#4 [M3] 持续更新与恢复手工验收](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | Blocked / open |
| m4 | [#5 [M4] 首版最终手工验收与上线门禁](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | Backlog / open |
| m0 | [#6 [M0] [PM-W00] 工程骨架、隔离运行边界与 Site 核验入口](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | Done / closed |
| m1 | [#7 [M1] [PM-W01-A] 华工广工列表发现与逐页持久化](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7) | Blocked / open |
| m1 | [#8 [M1] [PM-W01-B] 日期地点证据、去重及核心详情补全](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | Done / closed |
| m1 | [#9 [M1] [PM-W02-A] 最小卡片、公告简要详情与官方原文](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | Blocked / open |
| m1 | [#10 [M1] [PM-W02-B] 学校校区、相关性筛选与一致分页](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | Done / closed |
| m1 | [#11 [M1] [PM-W02-C] 桌面手机、键盘与加载错误状态](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | Done / closed |
| m2 | [#12 [M2] [PM-W03] 固定十校来源扩展与真实范围状态](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | In progress / open |
| m2 | [#13 [M2] [PM-W04-A] 受保护维护页、官方补录纠错与撤回](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | Done / closed |
| m2 | [#14 [M2] [PM-W04-B] 真实更新摘要与来源维护待办](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | Done / closed |
| m3 | [#15 [M3] [PM-W05-A] 自然自动刷新、断点续跑与失败恢复](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | Blocked / open |
| m3 | [#16 [M3] [PM-W05-B] 备份恢复、版本对账与只读 MCP](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | Done / closed |
| m4 | [#17 [M4] [PM-W06] Site 全流程复核与正式发布准备](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | In progress / open |
| release | [#18 [PM-RELEASE] 全部人工 Gate 通过后的正式上线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | Blocked / open |
| m0 | [#19 [M0] [PM-SETUP] 建立 GitHub Project 原生 Board 与 Roadmap](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) | Done / closed |
| m0 | [#21 [M0-02][M0-06] 首页使用成品布局，移出开发说明与核验框](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/21) | Done / closed |
| m0 | [#22 [M0-03][M0-06] Site读取开发API失败，目录与数据身份不可核验](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/22) | Done / closed |
| m0 | [#23 [M0-07] 招聘发现、来源状态与核验改为独立子页面](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/23) | Done / closed |
| m0 | [#24 [M0→M1] 工作包范围校验与可信治理基线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/24) | Done / closed |
| m1 | [#29 [M1-05] 简要详情移除定位证据与内部技术信息](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/29) | Done / closed |
| m1 | [#30 [M1-06] 校区切换后刷新延迟：测量并定位原因](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/30) | Done / closed |
| m1 | [#31 [M1-01][M2-01] 扩大广工以外九校的真实招聘覆盖](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/31) | In progress / open |
| m2 | [#32 [M1→M2] 工作包登记与共享合同可信基线](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/32) | Done / closed |
| m2 | [#33 [M1-01/04] 修复跨轮详情任务饥饿与列表续页停滞](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/33) | Done / closed |
| m2 | [#34 [M1-03/08] 修复电气相关性、工作地点与未披露状态的证据语义](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/34) | Done / closed |
| m2 | [#35 [M1-05][M2-05/06] 修复跨公告材料错绑及后续详情失效](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/35) | Done / closed |
| m2 | [#42 [M2-08] 首页移除“最近更新”区块](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/42) | Awaiting verification / open |
| m1 | [#43 [M1-05] 全站“官方原文”点击无跳转](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/43) | Blocked / open |
| Future | [#44 [未来讨论] 招聘日程表（下轮提醒，暂不开发）](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/44) | Backlog / open |
| Future | [#45 [未来讨论] AI 改简历（下轮提醒，暂不开发）](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/45) | Backlog / open |
| 治理/管理 | [#47 [治理][P1] 登记本轮修复与M4工作包，禁止沿用旧编号自授权](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/47) | Awaiting verification / open |
| 交付 | [#48 [交付核验][P1] 核对Site v5运行提交与可取回源码，修复版本追溯缺口](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/48) | Awaiting verification / open |
| m2 | [#49 [M2][来源子任务] 广州大学从首页有限发现扩展到获准公开招聘列表](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/49) | Awaiting verification / open |
| 治理/管理 | [#50 [项目管理][P2] 补齐Project5待同步条目并逐项回读，禁止把仓库看板当作原生同步](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/50) | Blocked / open |
| m3 | [#52 [M3-04] 华工 NCSS 忽略公开分页元数据，完整范围无法核验](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/52) | Awaiting verification / open |

人工M1→M2→M3→M4依次确认；#18正式发布条件未齐、未执行。修复PR只用Refs。#44/#45仅未来讨论，本次实际软件交付按约提起，未开发、未新增提醒。
