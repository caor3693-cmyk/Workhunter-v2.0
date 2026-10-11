# R0 / #24：可信工作包治理交付

日期：2026-10-11，Asia/Shanghai。实施入口 `87bab4932ae34b15cf699c2a5b1b4566c4e0cb19`；本包只建立治理，不改变 M0 用户结论、Site、数据集或业务实现。提交/PR/CI 和实际目标完整 SHA 由整合者在同步后回读留证，不以未生成的 SHA 自证。

## 1. 修改与责任边界

允许变更只有 `.github/workflows/checks.yml`、`scripts/check_scope.py`、`scripts/work_package_scopes.json`、`tests/test_scope.py` 和本文。首批不改 AGENTS、TASKS、CONTRACTS；STATUS/看板由主整合者更新。

机器表为独立审查后的目标授权，业务分支修改本地表不能扩大权限。R0 是 GOV 的别名；W01/R3 是 W01-R3 的别名，W02/R4 是 W02-R4 的别名。W00 不在新表中，没有业务兜底权限。

| 包 | 必须声明的 Issue | 分支前缀 | 限定目的 |
| --- | --- | --- | --- |
| GOV / R0 | #24 | `codex/gov-`、`codex/r0-` | checker、机器表、CI、对应测试 |
| DOC | #24 | `codex/doc-` | TASKS 路径与 M1 必要接口合同；不改产品选择 |
| R1 | #22 | `codex/r1-` | 真实读取、代理、启动与错误诊断 |
| R2 | #21、#23 | `codex/r2-` | 三个独立主页面及构建/固定路由 |
| W01-R3 | #7、#8 | `codex/w01-`、`codex/r3-` | 两校来源、证据、统一写入口及必要存储 |
| W02-R4 | #9、#10 | `codex/w02-`、`codex/r4-` | 查询投影、卡片、详情、客户端状态和局部样式 |
| R5 | #11 | `codex/r5-` | 桌面/390px、键盘、错误恢复及原编号材料 |

详细文件范围和允许关联 Issue 仅维护在机器表。W01-R3 只登记华工/广工及指定共享、写入、存储文件，没有整个 sources/domain/services/storage 目录权限；不取得首页、全局样式、访客 API 或 `backend/services/queries.py`。R3 所需目录/来源/摘要最低读取接入由 W02-R4 的共享后端整合者完成。共享文件仍同一时间只有一个整合者；机器检查不代替接口或产品语义审查。

同时最多两个**活跃实施包**是执行纪律；完成后同一 PR 可以显式集成多个已登记包，不能据此增加并行实施数。跨包集合仅接受：M0 = R1/R2；M1 = W01-R3/W02-R4/R5；M0-M1 = R1/R2/W01-R3/W02-R4/R5。DOC 和 GOV 不与业务包隐式叠加。

## 2. 两步引入，避免用候选规则证明自身

1. 第一次治理提交只包含 checker、机器表、对应测试与本文，暂时保留旧 workflow。实际 PR base 必须是含 `87bab493…` 旧 checker/TASKS 的 `codex/s0-w00-site-foundation`，不能仍指向缺 checker 的旧 main。冻结并执行该 base 的旧 checker，核对**完整首治理 PR**差异；独立审查新规则与正反例并完成旧 CI。W00 只用于这次已登记 GOV 引入，且未触发旧 workflow 的本地 checker fallback。
2. 将已独立审查的首治理完整 SHA 建立为专用实际目标，然后另交 GOV PR 修改动态 workflow。从该目标导出可信 checker，并从同一 base SHA 读取机器表，核对完整第二治理 PR；缺 checker、缺表或缺包直接失败。新 workflow 没有本地 fallback，没有固定 W00 或默认历史 base SHA。
3. DOC 从已审治理目标单独提交必要合同/路径差异，经可信检查后进入后续真实目标。业务分支从该目标切出；M0/M1 集成候选保持独立于 main，不以建立治理合并未验收产品。

旧 checker 的冻结来源是 `87bab4932ae34b15cf699c2a5b1b4566c4e0cb19:scripts/check_scope.py`，SHA-256 `7d35df14fe66a1921d968a54bb24263c138083f7fbd9882cadb223c819cab93c`。提交前已用它检查本包五个登记路径，结果通过；这次是路径诊断，**不代替提交后实际 base/head 全 PR 检查**。

## 3. PR/CI 声明与可信本地检查

PR 正文必须有且只有一行 `Work-Packages:` 和 `Work-Issues:`。单包例：

```text
Work-Packages: R1
Work-Issues: 22,1,6

Refs #22
```

跨包例（实际 head 使用 `codex/m0-m1-integration-` 前缀）：

```text
Work-Packages: R1,R2,W01-R3,W02-R4,R5
Work-Issues: 21,22,23,7,8,9,10,11,1,2,6
Integration: M0-M1

Refs #21, Refs #22, Refs #23, Refs #7, Refs #8, Refs #9, Refs #10, Refs #11
```

CI 的 base/head/ref 来自实际 PR 事件；正文编辑同样触发检查。手动 dispatch 必须显式提供 base/head/branch/packages/issues，并核对 `refs/remotes/origin/<branch>` 等于 head；缺 ref、伪造 head 或非法 branch 失败。

本地使用 Python 按字节从实际目标导出 checker（避免 PowerShell 重定向改写编码/换行），再执行：

```text
python <exported-base-checker.py> --base <actual-base-sha> --head <actual-head-sha> --package R1 --issue 22 --branch codex/r1-reading-20261011
```

checker 还校验执行文件内容与 base blob 一致；从同一 actual base 读取表，完整输出 base/head/diff_base/branch/包/Issue/文件清单。PR 路径从实际 base/head 的 merge-base 到 head 核对，与 GitHub 三点差异一致；目标分支独立前进不会误报为候选删除。`--paths` 仅为显著标记的诊断模式，CI 禁止用它替换完整 PR。重命名按 NUL 分隔状态记录核对旧、新两个路径；早期提交的越界改动不会被最后一个正常提交隐藏。

## 4. 验证与收尾

隔离临时 Git 仓库覆盖：W01 必要写链路通过；首页/全局样式/无关 API/查询/规则自授权/运行库拒绝；W02 已登记查询/CSS/README 通过；缺包、未知包/W00、Issue/分支错配、缺可信 checker/表/包、损坏表、跨包未登记、旧/新 rename 出界、早期提交越界、目标分支独立前进、PR 声明缺失/重复、LF/CRLF 正文和 dispatch 伪造身份。测试结果以本批实际运行回执为准。

最终定稿范围套件实际运行 **48 项通过**；独立审阅者另外对 merge-base、dispatch、精确 R3 目录边界及完整差异/rename 核心反例执行 10 项复验通过，并用冻结旧 checker 核对四个首步文件通过。`git diff --check` 通过；这些结论不替代后续真实 base/head CI 与用户复验。

首次测试的系统默认临时目录被 sandbox 拒绝 Git 配置写入；改为项目内 `.runtime/scope-final` 后执行，不为该环境失败改业务逻辑或跳过反例。本轮可再生临时材料为 `.runtime/scope-tests`、`.runtime/scope-final`、`.runtime/scope-final-mergebase`、`.runtime/scope-final-exact`、`.runtime/r0-governance`，未提交；由主整合者在最终回执后按当前授权清理。

实际 neat-freak 来源 `C:/Users/曹睿/.codex/skills/neat-freak/SKILL.md`，声明版本 **3.0.1**，SHA-256 `fb645274f18473740b389efb89b51ef4e58ddefaf26a4b1b43a9d82e4c848b31`；完整读取 SKILL 及 agent-paths、governance、verification、sync-matrix 四参考。本批局部源码清理移除了自然语言路径解析和 W00 兜底，没有无关格式化/依赖升级。

| 事实面 | 状态与证据 |
| --- | --- |
| 代码 | changed-and-verified；治理源码与针对性范围反例，实际提交/远端回执待整合者完成 |
| 运行 | out-of-scope；未更新 Site/API/数据库，保留 M0 当前失败/阻塞 |
| 文档 | changed-and-verified；本文与机器表一致，当前 STATUS/看板由整合者同步 |
| 规则 | changed-and-verified；既有 AGENTS→STATUS→FEEDBACK_CLOSEOUT 入口不变；可信目标建立及第二步 CI 尚须真实回读 |
| 记忆 | out-of-scope；只用本轮现役项目上下文，无长期记忆写入 |
| 工作区 | verified-current；仅登记治理路径修改；隔离样例/临时目录不冒充业务或官方来源 |

分支保护/required checks 的平台设置未在本包读到，状态未知；上述工作流是可执行检查，不声称已获得平台强制保护。工程通过不关闭 #24、M0/M1 功能或用户 Gate；未复验结论继续保留。

## 5. 实际同步回执（主整合者）

首治理完整 SHA `d7679d00788d15b07b0dab39c6c055b28e537092`，PR [#25](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/25)，实际 base `87bab4932ae34b15cf699c2a5b1b4566c4e0cb19`。冻结旧 checker 检查四路径完整差异，CI [38115465474](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38115465474) success。

动态 CI SHA `f3cb6ef0f8c734fb0d5a67972292812003aa3bc4`，PR [#26](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/26)，实际 base `d7679d00788d15b07b0dab39c6c055b28e537092`。可信目标 checker 核对完整单文件差异，CI [38115546980](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38115546980) success。

专用目标 `codex/m0-m1-governance-20261011` 随已审提交前进，业务实际目标将包含独立 DOC 合同后固定完整 SHA。2026-10-11 GitHub API 回读该目标分支保护返回 404 Branch not protected；当前是工程检查，并非平台 required checks 强制保护。GitHub 在专用目标快进后自动将 PR #26/#27 记为 MERGED（均保留 draft 属性）；PR #25 仍 open/draft。没有合并 main 或 PR #20，没有关闭 #24 或改写用户结论。此处的目标集成是已审治理/合同，不是产品 Gate 或正式发布。
