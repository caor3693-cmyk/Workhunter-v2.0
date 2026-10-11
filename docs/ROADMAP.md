# Workhunter v2.0 一周路线图与阶段验收

**计划版本：1.4；规划日：2026-10-10；时区：Asia/Shanghai**
**开发目标窗口：2026-10-11—2026-10-17，共七天**
**仓库：[caor3693-cmyk/Workhunter-v2.0](https://github.com/caor3693-cmyk/Workhunter-v2.0)**

以下日期保留原开发目标。10-11曾收到M0失败/阻塞并修复，第二轮M0七项已通过；历史反馈与原工程日期保留。统一M命名，旧S/G仅为历史映射。
Issue索引见[BOARD](BOARD.md)，当前验收与未解决反馈见[第二轮报告](deliveries/M0-M1-FEEDBACK2-20261011.md)。原生Project5及原26项已核对，新#32—35原生五字段已同步回读；仓库30项已登记。R0—R5工程齐备；M0通过，M1-01/05/06失败，其余五项通过。本轮完成[对抗审查](deliveries/M1-M2-AUDIT-20261011.md)和[下一轮计划](deliveries/M1-M2-EXECUTION-20261011.md)，反馈与新缺陷未修复，Site未重发。

## 1. 本轮交付范围

首版包含 F01—F10、D01—D08、O01—O03：学校招聘发现、准确核心字段、简要详情、更新摘要、维护网页与持续运行。
独立岗位库/搜索、全国企业直采、完整名单工程继续后置；不恢复学生账号或待遇筛选。
开发期首先在 Site 提供可使用、可反馈的版本，每个阶段完成后交付一份手工核验清单。
负责人按 M0 → M1 → M2 → M3 → M4 顺序反馈；发现问题后补建修复 Issue，修复后回到原检查项复验。
只有五个阶段均人工通过，才允许执行正式上线任务；日期到达不触发自动发布。
已修复、自动测试已通过或 PR 已合并，都不等于负责人已核验。

## 2. D1—D7 目标安排

| 日程 | 日期 | 阶段/工作包 | 当日可交付结果 | 人工核验安排 |
| --- | --- | --- | --- | --- |
| D1 | 10-11 | M0 / W00 | 工程与数据边界、最小运行入口、Site 检查入口及版本说明 | 提交 M0 清单，核对能打开、身份清楚、未完成功能标识 |
| D2 | 10-12 | M1 / W01 | 华工、广工基础发现，日期/地点证据、去重与详情补全基础 | 开发自测与进度预览；暂不宣布 M1 通过 |
| D3 | 10-13 | M1 / W02 | 两校卡片、筛选、相关性、简要详情、原文与手机可用流程 | 提交 M1 清单；反馈转修复 Issue |
| D4 | 10-14 | M2 / W03、W04 | 十校来源登记与适配、真实受限状态、维护页主要流程 | 提供进度预览；处理 M1 回归 |
| D5 | 10-15 | M2 / W03、W04 | 十校状态、补录/纠错/撤回、真实更新摘要可核验 | 提交 M2 清单 |
| D6 | 10-16 | M3 / W05 | 自然调度、断点与失败恢复、备份恢复、只读 MCP | 提交 M3 清单及真实运行证据 |
| D7 | 10-17 | M4 / W06 | Site 全流程回归、逐校说明、已知问题和正式发布准备材料 | 提交 M4 总清单；全部通过后才解锁正式上线 |

工作日期是排程目标；阶段完成当天提供版本与核验包。排期假设开发日内能获得一次集中反馈，具体时刻由负责人实际安排。
这里规定交付流程，没有设置定时提醒，也不要求负责人每天在线；无阶段交付的日期只提供进度。
每份阶段清单控制在可逐条操作的范围，建议一次 15—30 分钟；技术证据另附，避免让用户阅读原始日志。
若反馈晚到、缺陷未修好或实际工作超期，记录原目标、延迟原因与新的预计日期，后续依赖日期顺延。
没有反馈就保持“待验收”，不能以超时、沉默或日历日期代替通过。
等待反馈时继续不依赖失败部分的工作，不把整个项目无条件停住，也不跳过人工 Gate。

## 2.1 路线图视图

以下为仓库内的计划时间轴；[原生Roadmap](https://github.com/users/caor3693-cmyk/projects/5/views/2)现已建立，Stage分组、Start date/Target date已实际保存。正式发布是 Gate 条件解锁项，不画成日历自动开始的任务。

```mermaid
gantt
    title Workhunter v2 一周开发目标
    dateFormat YYYY-MM-DD
    axisFormat %m-%d
    section 开发阶段
    M0 工程与Site入口 :s0, 2026-10-11, 1d
    M1 两校真实可用 :s1, 2026-10-12, 2d
    M2 十校与维护 :s2, 2026-10-14, 2d
    M3 持续运行 :s3, 2026-10-16, 1d
    M4 总体验收准备 :s4, 2026-10-17, 1d
    section 用户核验目标
    M0 :milestone, g0, 2026-10-11, 0d
    M1 :milestone, g1, 2026-10-13, 0d
    M2 :milestone, g2, 2026-10-15, 0d
    M3 :milestone, g3, 2026-10-16, 0d
    M4 :milestone, g4, 2026-10-17, 0d
```

## 2.2 实际进展

| 阶段 | 原目标 | 工程/候选实际进展 | 当前用户/技术结论 |
| --- | --- | --- | --- |
| M0 | 10-11 | 初版10-10，10-11修复并发布复验，历史与当前候选分别保留 | 本轮七项通过，#1/#6/#21/#22/#23完成 |
| M1 | 10-12—10-13 | 10-11完成R3—R5、132条有限真实记录/98材料、Site4与原编号操作包 | 五项通过；M1-01/05/06失败，#2/#7/#9/#10受新反馈阻塞 |
| 治理#24 | 10-11 | 可信base ae261c8、独立治理与DOC审阅/CI、完整PR五包检查 | 技术复核完成 |
| 管理#19 | 10-11 | 本轮建立私有Project5，Board/Roadmap与26项字段实际对账 | 技术配置完成 |
| M2—M4 | 10-14—10-17 | 原计划保留，本轮未实施 | 未测 |

### 2.3 当前迭代安排

当前活动实施包0；本轮三项只登记未解决、分析与对策。下一批A由单一整合者诊断延迟并修详情，B独立补两校电气真实材料，最多两个包。更多学校仍归后续#12/W03，目标与完成条件见第10节，不提前启动M2。

## 3. 五个阶段完成门槛

| Gate | 阶段 | 提交人工核验前 | 用户要实际确认的结果 |
| --- | --- | --- | --- |
| M0 | M0 工程与 Site 入口 | W00 自测通过，提供可访问入口、版本与数据模式 | Site 可打开；新项目身份明确；真实/演示/尚未接通内容准确标明；无访客写入口 |
| M1 | M1 两校真实可用 | W01、W02 自测通过，M0 已人工通过 | 华工、广工流程可核验；已有时间地点正确；无岗位仍可见；学校/校区/分页不串；标题进简要详情，原文正确跳转，手机可用 |
| M2 | M2 十校状态与维护 | W03、W04 自测通过，M1 已人工通过 | 十校可选且状态真实；受限校不假报零招聘；维护预览/提交/纠错/撤回可用；更新数字与实际变化一致 |
| M3 | M3 持续运行 | W05 自测通过，M2 已人工通过 | 至少一次真实自然调度可对账；失败不抹数据；重启/恢复有证据；只读 MCP 身份、版本、数据与新项目一致 |
| M4 | M4 全量复核与准备 | W06 集成自测通过，M0—M3 均有效通过 | Site 上全部首版流程复核；各校限制清楚；已报告问题修复并复验；备份、切换和回退材料可执行 |

阶段通过还要求：该阶段必需功能达到合同，相关 P0/P1 失败与回归均已解决并获用户复验。
受限校按已确认 Q5A 明示，可通过“限制说明及补录能力”对应检查；不能把受限写成自动接通，也不能把未实现代码写成外部限制。
两校真实流程与十校可用结论必须有对应来源证据；fixture 仅能验证交互或边界，不能替代真实采集。
七天开发期与七个自然日运营观察分开：M3 验证真实自动运行链，长期观察按实际发生天数继续累计。

每次提交 Gate，必须在阶段验收 Issue 中提供：

1. Site URL、可核验版本/提交与数据标识、核验时间及哪些内容为真实数据。
2. 稳定检查编号，例如 M1-01；逐项写点击路径、应看到什么、需要核对的样本或原文。
3. 前置条件、正常/异常/未知样例；维护操作另说明权限及如何恢复。
4. 开发自测结果、已知限制，以及上次失败项的修复 Issue 和复验入口。
5. 简短反馈格式：`M1-01 通过；M1-02 失败：实际现象……`。
6. 用户逐项反馈和阶段结论；提交新候选版本时保留先前失败记录。

## 4. 初始 Issue 拆分

交付范围共 18 项：12 个实施项、5 个阶段人工验收项、1 个正式发布项，均已创建为实际 Issue。另以 [PM-SETUP #19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) 保留原生 Project 视图配置的已完成技术记录；本轮新增四项导入由#32跟踪。
建 Issue 时把 PM-ID 写进正文并关联实际编号；不得把 PM-ID 冒充原生 sub-issue 或依赖关系。

| PM-ID | 建议标题 | 工作包/阶段 | 优先级 | 目标日期 |
| --- | --- | --- | --- | --- |
| [PM-W00 #6](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6) | 工程骨架、运行边界与 Site 核验入口 | W00 / M0 | P1 | 10-11 |
| [PM-W01-A #7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7) | 华工广工列表发现与逐页持久化 | W01 / M1 | P1 | 10-12 |
| [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | 日期地点证据、去重及核心详情补全 | W01 / M1 | P1 | 10-13 |
| [PM-W02-A #9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | 最小卡片、简要详情与官方原文 | W02 / M1 | P1 | 10-13 |
| [PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | 学校校区、相关性筛选与一致分页 | W02 / M1 | P1 | 10-13 |
| [PM-W02-C #11](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | 桌面手机与加载错误状态 | W02 / M1 | P1 | 10-13 |
| [PM-W03 #12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | 固定十校来源扩展与真实范围状态 | W03 / M2 | P1 | 10-15 |
| [PM-W04-A #13](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | 受保护维护页、补录纠错与撤回 | W04 / M2 | P1 | 10-15 |
| [PM-W04-B #14](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | 真实更新摘要与来源维护待办 | W04 / M2 | P1 | 10-15 |
| [PM-W05-A #15](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | 自然自动刷新、续跑与失败恢复 | W05 / M3 | P1 | 10-16 |
| [PM-W05-B #16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | 备份恢复、版本对账与只读 MCP | W05 / M3 | P1 | 10-16 |
| [PM-W06 #17](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17) | Site 全流程复核与正式发布准备 | W06 / M4 | P1 | 10-17 |
| [PM-G0 #1](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/1) | M0 手工核验：工程与 Site 入口 | M0 | P1 | 10-11 |
| [PM-G1 #2](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/2) | M1 手工核验：两校真实可用 | M1 | P1 | 10-13 |
| [PM-G2 #3](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/3) | M2 手工核验：十校状态与维护 | M2 | P1 | 10-15 |
| [PM-G3 #4](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/4) | M3 手工核验：持续运行 | M3 | P1 | 10-16 |
| [PM-G4 #5](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/5) | M4 手工核验：全量复核与发布准备 | M4 | P1 | 10-17 |
| [PM-RELEASE #18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | 全部人工 Gate 通过后的正式上线 | Release | P1 | 条件解锁后安排 |

正式发布项当前为 Blocked，不纳入“七天到期即上线”的承诺。
缺陷按用户反馈增补 Issue，不能为了保持初始数量而把不同原因的问题混成一个任务。

## 5. 功能追踪

| 功能 ID | 必需成果 | 实施 Issue | 首次人工 Gate |
| --- | --- | --- | --- |
| F01 | 学校与校区选择 | [PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10)、[PM-W03 #12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | M1；十校扩展 M2 |
| F02 | 招聘发现列表 | [PM-W01-A #7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7)、[PM-W02-A #9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9)、[PM-W03 #12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | M1；十校扩展 M2 |
| F03 | 最小卡片 | [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8)、[PM-W02-A #9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | M1 |
| F04 | 搜索与筛选 | [PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | M1 |
| F05 | 近期、临近与历史 | [PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | M1 |
| F06 | 官方原文与适用附件 | [PM-W02-A #9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | M1 |
| F07 | 真实更新摘要 | [PM-W04-B #14](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14) | M2 |
| F08 | 手机与桌面使用 | [PM-W02-C #11](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/11) | M1 |
| F09 | 相关、未知与全部招聘 | [PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10) | M1 |
| F10 | 本公告简要详情 | [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8)、[PM-W02-A #9](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/9) | M1 |
| D01 | 官方来源登记 | [PM-W01-A #7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7)、[PM-W03 #12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12) | M1；十校扩展 M2 |
| D02 | 列表发现与持久化 | [PM-W01-A #7](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/7) | M1 |
| D03 | 核心详情补全 | [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | M1 |
| D04 | 字段证据和缺失状态 | [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8) | M1 |
| D05 | 去重与变更 | [PM-W01-B #8](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/8)、[PM-W04-A #13](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | M1；人工更正 M2 |
| D06 | 定时与增量 | [PM-W05-A #15](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | M3 |
| D07 | 官方材料补录纠错 | [PM-W04-A #13](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/13) | M2 |
| D08 | 页面/API/诊断一致读取 | [PM-W00 #6](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/6)、[PM-W02-B #10](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/10)、[PM-W05-B #16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | M0 基础；M1/G3 扩展 |
| O01 | 来源状态与待办 | [PM-W03 #12](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/12)、[PM-W04-B #14](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/14)、[PM-W05-A #15](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/15) | M2；调度 M3 |
| O02 | 发布与数据恢复 | [PM-W05-B #16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16)、[PM-W06 #17](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17)、[PM-RELEASE #18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) | M3 恢复；M4 准备 |
| O03 | 只读 MCP | [PM-W05-B #16](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/16) | M3 |

M4 对上述功能做最终回归；早期 Gate 通过不是后续改动免检的理由。
O02 的真实生产切换归 [PM-RELEASE #18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18)，M4 只核验准备完成，不提前宣称正式上线。

## 6. 开发依赖与并行

主路径：W00 → W01 → W02；W01 的来源合同稳定后可并行 W03。
W04 可在 W00 的存储/服务合同稳定后推进；W05 依赖实际写入口与刷新服务；W06 汇总 W00—W05。
人工验收路径严格为 M0 → M1 → M2 → M3 → M4 → [PM-RELEASE #18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18)。
先稳定共享合同，再并行不同来源或互不冲突页面；同时最多两个实施包，共享文件由一个整合者负责。

每个 Issue 写明允许路径、功能 ID、依赖、验收用例与所属 Gate。
P0/P1 缺陷阻塞当前阶段验收和依赖该缺陷的功能；其它独立工作可继续。
某校受限只影响该源的实际能力结论；维护页等独立工作继续，不能擅自换校。
不能通过改全局页面、放宽身份/证据规则、删测试或新增后置模块来“消除阻塞”。

## 7. 状态、优先级与关闭规则

| Project Status | 含义 | GitHub Issue 状态 |
| --- | --- | --- |
| Backlog | 尚未开始或条件尚未具备 | open |
| Ready | 范围、依赖与输入已具备，可实施 | open |
| In progress | 正在编码、验证或修复 | open |
| Awaiting verification | 开发验证已完成，等待对应用户手工核验 | open |
| Blocked | 明确阻塞原因及解除条件 | open |
| Done | 对应人工检查已通过，证据与阶段关系已回写 | closed |

若 Project 已有等价字段值，采用映射并保留原字段；不能为套表重建整个项目。
Gate Issue 由负责人实际反馈决定通过；开发者不能代签、把 PR 合并当通过或自动勾完清单。
实现 Issue 在进入待验后保持 open；用户通过对应检查并达到 DoD 后才关闭。
未完成人工核验的 PR 用 `Refs`，避免自动关闭 Issue 的关键字提前结案。

优先级规则：

- **P0：** 数据丢失、越权写入或整个核心流程不可用；立即处理，停止受影响链路。
- **P1：** 必需功能不正确或不可用，例如时间/地点错误、来源跳错、筛选串页、补录失败；阻塞当前 Gate。
- **P2：** 不妨碍合同内核心使用的改善；有具体影响与处理决定，不能用 P2 掩盖必需功能缺失。

反馈失败后，记录检查项、版本/数据、操作、预期/实际结果、影响、优先级和对应功能。
同一根因复用现有修复 Issue；不同根因分别立项，标题带 `[Mx-yy]` 便于回到原检查点。
修复后返回 Awaiting verification，附同一路径复验步骤；未经用户复验不改 Done。
后续出现回归则重开对应 Issue，标明受影响 Gate；在再验证前该 Gate 不能满足发布条件。
P2 若拟后置，需负责人在阶段反馈中明确接受并保留任务；没有答复仍保持开放。

## 8. Board 与 Roadmap 的目标配置

Project 只管理本新仓库的本轮 Issue，使用实际平台对象，不在文档中伪称视图已配置。
最小字段为 Status、Stage、Priority、Start date、Target date；PM-ID、功能 ID、Gate 与依赖可放 Issue 正文。
Stage 使用 M0、M1、M2、M3、M4、Release；阶段日期采用第 2 节目标。
Board 按 Status 分列，卡片显示 Stage/Priority，保留按 Stage 筛选入口。
Roadmap 使用 Start/Target date 并按 Stage 分组；显示原目标及调整后的预计日期，超期不隐藏。
五个 Gate 各自形成可打开的 Issue；功能项链接到所属 Gate，反馈修复项链接到原检查编号。
平台支持原生依赖/子项时实际建立并核实；否则使用清楚的正文关系，不冒充原生关联。
当前链接、字段映射与核对时间记入STATUS/config；既有26项已导入Project5、视图已配置。本轮Issue总数30，新#32—35原生导入/字段尚待同步，不将仓库索引冒称原生回执。

## 9. Site 优先与正式上线门禁

Site 是开发期交付和人工核验入口；只有已提供并实际打开的地址才能写“可用”。
每次交付标明代码版本、数据时间、真实数据范围和当前可操作功能；静态演示不能证明采集/维护/调度已完成。
后台、持久化、维护权限、定时和 MCP 按实际获准运行环境核验，不能只凭 Site 页面截图判通过。
Site 技术接入按对应合同执行，普通页面修复不更换全局架构或影响旧站。

[PM-RELEASE #18](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/18) 开始前必须同时满足：M0—M4 当前有效通过；无未复验的阻塞缺陷；确切候选版本与验证一致；持久数据、备份、切换和回退准备齐备。
随后仅执行已明确授权的正式发布范围，并核对上线后的版本、数据、核心流程和调度。
正式生产验证失败则记录事故/修复项，按预定回退条件处理；不能把“已部署”直接写成“已验收”。
上线不包含删除旧库、历史、备份或任意旧资源；旧资产继续按已确认的只读归档政策处理。



## 10. 当前验收与下一轮执行

M0七项通过；M1-01/05/06失败，其余五项按第二轮明确授权通过。历史通过保留，下一候选受影响项另行定向回归。完整根因、范围、合同、反例、实施指令见[本轮计划](deliveries/M1-M2-EXECUTION-20261011.md)，替换此前初步A/B安排。

| 顺序 | 原目标/本轮目标 | 执行安排 | 完成判据 |
| --- | --- | --- | --- |
| GOV/DOC | 10-11—12 | #32独立治理可信起步，登记反馈号/M2包；冻结来源/材料/写入/维护/摘要合同 | 实际base完整检查和独立审阅，新规则成为可信目标 |
| CORE + UI | 10-12—13 | #33/#34/#35共享修复，与#29/#30限定前端并行 | 队列公平及到期复查、语义和材料反例转回归；详情/状态/性能证据 |
| M1先行复验 | 原10-13 | #31补两校当前明确电气样本，交M1-01/05/06及受影响回归 | 真实Site/数据/原文、同编号步骤；用户结论另记 |
| W03 + W04 | 原10-14—15 | 一条线#12固定十校，另一条#13维护后接#14摘要 | 十校真实状态、至少三校当前电气样本、维护/撤回/摘要和M2八项 |
| 缺口修正 | 必要时M2缓冲10-16 | 记录原目标、缺口、实际预计，后续阶段相应调整预计 | 证据不足保持待验/受阻，日历不自动通过 |

表中前置是对应合同/工程交付，不要求先关闭仍待用户复验的Issue。最多两个活动实施包；共享服务/API/迁移/代理/资料单一整合。先交M1复验后继续独立M2工程，人工Gate仍顺序通过。#31的两校M1部分与三校M2部分分别判定，不反向制造循环依赖。

原生Project5已建立，新#32—35四项导入和五字段已通过既有获准gh通道写入并回读，#19不重开。源码限域清理、实际neat-freak、必要验证、GitHub推送/SHA/PR/CI回读与原编号复验一起交付。M2业务尚未实现，M3/M4与正式发布仍按各自Gate执行。

本轮执行：GOV #36及CI成功已进入隔离可信目标f1d4d88，DOC-M2串行冻结合同，随后CORE-M2/M1-UI并行。原目标和用户Gate结果保留，华工当前样本仍是实网材料缺口；不以日期或工程通过代替用户确认。
