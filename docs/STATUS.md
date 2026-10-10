# Workhunter v2.0 当前状态

更新日期：2026-10-10，Asia/Shanghai。规范版本：1.1；八项产品选择 `ABAAAAAB` 不变。只维护当前事实，工程自验、用户核验、私有 Site 保存与正式发布分别记录。

## 1. 当前结论

**S0 / W00 的工程骨架和私有 Site 候选已交付，等待 G0 用户核验。** [实施 #6](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) 与 [G0 #1](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) 保持 open、Awaiting verification；G0-01—G0-06 全部未测，没有用户通过记录。实际开发、自验与 Site 保存日期为 2026-10-10，原计划目标 10-11 保留。

新库为空库，没有招聘演示或真实招聘记录，十校来源均尚未检查。Python/FastAPI、SQLite 与原生前端已隔离运行；源代码冻结提交、数据集、逐项清单和限制见 [S0 交付包](deliveries/S0.md)。尚未实施真实采集、维护写入或自然调度。

**原生 GitHub Project、Board、Roadmap 仍无已创建并回读核验的入口。** 当前仓库/Issue 通道可用，但没有可调用的 Projects 写入工具；本机 `gh` CLI 已找到，现有认证失效。本轮不重复登录，配置任务 [#19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) 保持 Blocked/open，Project 与视图 ID/URL 保持 `null`。使用仓库 [BOARD](BOARD.md) 和 [ROADMAP](ROADMAP.md) 管理可继续工作，不称其为原生视图。

## 2. 实际入口与候选身份

| 入口 / 身份 | 当前内容 / 状态 |
| --- | --- |
| [新仓库](https://github.com/caor3693-cmyk/Workhunter-v2.0) | 公开仓库；本轮没有改变可见性 |
| [私有 Site](https://workhunter-v2-review.sage-candy-7999.chatgpt.site) | owner-private 阶段验收宿主；部署 succeeded；revision 1 的服务端 secrets 已按用户明确授权配置 |
| 前端 / 后端冻结提交 | `288063243275eeb0530cc9b9743c1d11aa4cfbde`；Site 与后端代码候选使用同一源提交，后续管理文档提交不替代此身份 |
| 数据集 / 数据模式 | `ds-05add5c6-e4e7-43a6-9bc3-89b5e4a4a10e` / `empty`；0 条招聘，十校 pending / not_checked |
| [PR #20](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/20) | draft/open；使用 `Refs #6 #1 #19`，不自动关闭待验 Issue |
| [CI run 38062386958](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38062386958) | succeeded；工程检查通过，不替代用户核验 |
| [全部 Issues](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues) | #1—#19 均 open；12 个实施、5 个 Gate、1 个正式发布、1 个管理配置 |
| [仓库任务看板](BOARD.md) | 15 Backlog、2 Awaiting verification、2 Blocked、0 Done；Ready / In progress 均 0 |
| [一周路线图](ROADMAP.md) | 2026-10-11—10-17 原目标保留；实际进展另列，日期不代替验收 |
| [手工核验规则](MANUAL_QA.md) | 36 项，按阶段 6/8/8/6/8；本轮提供原编号 G0 清单与四态反馈模板 |
| [Project 初始配置](../config/project.json) / [接续步骤](PROJECT_SETUP.md) | 实际原生 ID/URL 留空；#19 仅阻塞管理配置，不阻塞独立开发 |

已有 Gate Issue 更新原单；收到用户失败或阻塞反馈后先查重，再补建或更新关联问题 Issue。没有用户反馈，不把自动测试、Site 保存或 PR 合并写成验收通过。

## 3. 一周阶段与真实 Issue

| 阶段 | 原目标日期 | 实施 Issue | 手工验收 Issue | 当前实际状态 |
| --- | --- | --- | --- | --- |
| S0 工程与 Site 入口 | 10-11 | [#6](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | [G0 #1](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | 10-10 完成工程自验、Site 候选保存及认证同源 HTTP 核验；两单 Awaiting verification/open；G0 六项未测；登录后的 Site 浏览器操作待用户核验 |
| S1 两校真实可用 | 10-12—10-13 | [#7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7)、[#8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8)、[#9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9)、[#10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10)、[#11](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | [G1 #2](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | Backlog；未开始；G1 未测 |
| S2 十校与维护 | 10-14—10-15 | [#12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12)、[#13](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13)、[#14](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | [G2 #3](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | Backlog；未开始；G2 未测 |
| S3 持续运行 | 10-16 | [#15](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15)、[#16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | [G3 #4](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | Backlog；未开始；G3 未测 |
| S4 总体验收与准备 | 10-17 | [#17](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | [G4 #5](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | Backlog；未开始；G4 未测 |
| 正式发布 | G0—G4 通过后安排 | [#18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | 依赖全部 Gate | Blocked；未执行；没有自动发布日期 |

排期仍以每天可获得一次反馈为假设，实际延迟需记录并顺延；没有设置自动提醒。等待 G0 反馈时可以继续不依赖失败部分的独立工作，G1 及以后仍须按顺序由用户核验。

## 4. 实际自验、环境与限制

- 41 项 Python 测试和 3 项代理测试通过；CI 成功。验证覆盖显式初始化与幂等读取、错误数据库、GET 无写入、服务鉴权、分页边界、受控代理和越界路径反例。测试中的合成反例不表示官方采集或覆盖成功。
- 本机原生前端的桌面与 390px 窄屏自验通过；同一冻结前端重新加载及身份核对通过，桌面可视宽度与 scrollWidth 均为 1265px，390px 窄屏均为 375px；真实 HTTPS 开发 API 已返回 200。仅停止本次隔离 API 后重新加载，页面保留上次结果并说明尚未更新；恢复服务后回到原 commit / dataset，数据库散列未变。截图与脱敏回执见 S0 交付包。
- **私有 Site 的真实同源 HTTP 链路已于 2026-10-10T23:22:43+08:00 核验。** 使用 Site 已有服务访问授权，没有新建或轮换令牌；HTML 与六个读取 API 全部 200。HTML 前端与 `/version` 后端均为冻结提交 `288063243275eeb0530cc9b9743c1d11aa4cfbde`，项目正确，六个 API 的 dataset 与 `empty` 数据模式一致；目录十校、十个来源均尚未检查，机会为 0 / `empty_database`，摘要新增为 `null`。真实 Site 的 POST catalog 返回 405、POST admin commit 与任意 URL 代理返回 404。此结果证明同源传输及只读边界，不是用户浏览器操作或 G0 通过。
- 内置浏览器访问真实 Site 时停在平台登录页，没有用户 ChatGPT 平台会话；尚未完成登录后的真实 Site UI 自验。用户应使用自己的已登录浏览器按 G0 原编号操作；平台登录限制与业务读取权限分别判断。
- Python/FastAPI、SQLite 与 worker 保留在隔离开发宿主，Site 只承载原生前端和固定同源代理；没有迁移到 D1 或另建业务栈。本阶段 HTTPS 开发通道依赖本机及当前进程在线，是临时验收连接，不是生产或无人值守运行证明。
- 十校种子均为 pending / not_checked；未执行 v2 官网采集、业务覆盖统计、招聘场景浏览器验收、性能测试、自然调度或恢复演练。未检查的新增/变化为 `null`，不是“今日零新增”。
- `backend.cli refresh` 与独立 worker 明确退出 2，说明尚未实现真实采集；不生成成功运行记录。真实刷新由 W01、自然调度由 W05 交付。
- 范围检查与 CI 已建立，读取目标提交的 TASKS；不将文档或工程检查称为 GitHub 分支保护。原生 Project 权限仍受阻；旧只读插件尚未接入 v2，不能算作新项目运行成绩。

## 5. 用户核验、发布与旧资产

当前用户待验为 [G0 #1](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) 的 G0-01—G0-06，操作与预期见 [S0 交付包](deliveries/S0.md) 和 [MANUAL_QA](MANUAL_QA.md)。逐项反馈“通过 / 失败 / 阻塞 / 未测”；沉默保持待验。失败先查重并记录关联功能、Gate、原编号和允许修改路径，修复后按原编号请用户复验，PR 使用 Refs。

全部 Gate 当前有效通过、首版必需反馈修复并复验、候选版本及发布材料齐备后，才按 [#18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) 执行明确目标的正式部署与线上复验。当前没有正式部署或旧站切换；私有 Site 保存与正式站点发布分别管理。

本轮没有修改、清空或归档旧仓库，没有移动、删除、备份或冻结旧数据库/原文，没有改变旧站、定时器、域名或仓库可见性。旧资产继续按已确认只读归档政策留存；真实备份、冻结、GitHub Archived 开关和最终切换各自验证，不把政策记为已执行。

## 6. 下一步

Site 同源认证 HTTP 自验已补入既有 #6 / #1 的同一交付包；用户使用已登录浏览器按 G0 六项操作反馈。独立开发下一项为 S1 / W01 的 [#7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7)：华工、广工真实基础发现；不会用空库或 fixture 代替真实采集。

#19 继续保留 Blocked；仅在出现现成且已授权的有效 Projects 通道后接续配置并回读真实入口，本轮不重复登录。统一执行指令见 [TASKS.md 第 6 节](TASKS.md#6-可直接交给-codex-的指令)。
