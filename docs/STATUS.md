# Workhunter v2.0 当前状态

更新日期：2026-10-10，Asia/Shanghai。规范版本：1.1；八项产品选择 `ABAAAAAB` 不变。本文件所属 Git 提交为当前管理基线，只维护当前事实。

## 1. 当前结论

一周开发计划、19 个实际 GitHub Issues、阶段标签、仓库任务看板、路线图与 36 项手工核验要求已建立。新应用尚未实现；下一项是 **S0 / W00，Issue #6**。

**GitHub Projects 原生 Project、Board、Roadmap 尚未创建。** 当前连接有仓库/Issue 写入能力，但没有可调用的 Projects 工具；浏览器安全登录本轮未完成。剩余配置独立跟踪 #19，不能把仓库内文档视图称为原生 Project 已完成。Site 验收入口也须在 W00 实现后才能提供。

## 2. 实际管理入口

| 入口 | 当前内容 / 状态 |
| --- | --- |
| [新仓库](https://github.com/caor3693-cmyk/Workhunter-v2.0) | 准确名称含连字符；本轮核对为公开仓库，没有改变可见性 |
| [全部 Issues](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues) | #1—#19，均 open；12 个实施、5 个 Gate、1 个正式发布、1 个管理配置 |
| [仓库任务看板](BOARD.md) | 可点击的实际 Issue 索引；状态来自 Issue 标签，当前 16 Backlog、1 Ready、2 Blocked、0 Done |
| [一周路线图](ROADMAP.md) | 2026-10-11—10-17，S0—S4、G0—G4；包含计划时间轴及功能映射 |
| [手工核验规则](MANUAL_QA.md) | 36 项，按阶段 6/8/8/6/8；每轮交付填具体场景，用户反馈四态 |
| [Project 初始配置](../config/project.json) | 19 个真实 Issue 编号及期望字段/视图；原生 Project ID/URL 留空 |
| [原生视图配置任务 #19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) | Blocked；仅管理访问条件受阻，不表示 GitHub API 本身不支持视图 |
| [配置接续步骤](PROJECT_SETUP.md) | 使用已授权 API/CLI 或页面建立/复用 Project，回读后填真实链接；本轮不重复发起登录 |

模板 manual-feedback.yml、stage-review.yml 已建立，关联标签已创建。已有 Gate Issue 应更新原单，避免每次提交候选又新建阶段单。

## 3. 一周阶段与真实 Issue

| 阶段 | 目标日期 | 实施 Issue | 手工验收 Issue | 当前实际状态 |
| --- | --- | --- | --- | --- |
| S0 工程与 Site 入口 | 10-11 | [#6](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | [G0 #1](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | 实施 Ready，未开始；G0 未测 |
| S1 两校真实可用 | 10-12—10-13 | [#7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7)、[#8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8)、[#9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9)、[#10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10)、[#11](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | [G1 #2](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | Backlog；G1 未测 |
| S2 十校与维护 | 10-14—10-15 | [#12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12)、[#13](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13)、[#14](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | [G2 #3](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | Backlog；G2 未测 |
| S3 持续运行 | 10-16 | [#15](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15)、[#16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | [G3 #4](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | Backlog；G3 未测 |
| S4 总体验收与准备 | 10-17 | [#17](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | [G4 #5](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | Backlog；G4 未测 |
| 正式发布 | G0—G4 通过后安排 | [#18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | 依赖全部 Gate | Blocked；没有自动发布日期 |

所有 Issue 已标阶段、类型、优先级和初始状态。所有用户核验项保持未测；没有应用测试或用户通过记录。工程期以每天可获得一次反馈为排期假设，实际延迟需记录并顺延；没有设置自动提醒。

## 4. 环境与数据

- 新实现继续用 Python/FastAPI、SQLite、原生前端与独立 worker。开发期先使用 owner-private Site，由薄同源代理连接隔离 HTTPS 开发 API；平台能力和鉴权约束写在 CONTRACTS。
- Site、隔离开发 API/宿主、新业务库、生产服务均未创建或部署。W00 需实际探测接入；G1 起不得以 fixture 或旧站代替真实新库链路。
- 十校入口种子均为 pending，没有执行 v2 真实采集、覆盖统计、浏览器业务验收、性能测试、自然调度或恢复演练。
- 受限来源按 Q5A 标记并支持官方材料补录；开发 API 根本不可达与个别学校受限分开判断。
- 旧只读插件仍不能作为 v2 的运行成绩。W05 对接新服务后必须返回真实项目、代码及数据标识。

## 5. 发布与旧资产

每阶段自验后提交 Site 版本及手工清单，进入待用户核验。负责人按 G0→G1→G2→G3→G4 反馈，失败查重补 Issue、修复、同编号复验。未反馈、自动测试或 PR 合并不能关闭对应待验事项。

全部 Gate 当前有效通过、首版必需反馈修复并复验、候选版本及发布材料齐备后，按 #18 执行正式部署与线上复验。私有 Site 验收运行和正式站点切换分别记录；日期到达不触发上线。

本轮没有修改、清空或归档旧仓库，没有移动、删除、备份或冻结旧数据库/原文，没有改变旧站、定时器、域名或仓库可见性。旧资产继续按已确认只读归档政策留存；真实备份、冻结、GitHub Archived 开关和最终切换各自验证，不把政策记为已执行。

## 6. 下一步

原生 Project 接续任务为 #19；在具备既有授权的环境中完成后，回写实际 Project/Board/Roadmap 链接，并读取平台结果核验。

开发从 #6 的 S0/W00 开始，统一执行指令在 [TASKS.md 第 6 节](TASKS.md#6-可直接交给-codex-的指令)。每阶段维护 Issue 标签/Project 字段、STATUS、Site 候选版本和用户核验结论。实现、用户验收、提交/PR、Site 发布、正式部署、线上复验及真实运营观察分别记录。
