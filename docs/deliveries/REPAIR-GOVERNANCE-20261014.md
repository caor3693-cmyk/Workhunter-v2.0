# 2026-10-14 独立范围治理与 Project 通道核查

Issue：Refs #47、Refs #50。治理分支 `codex/r0-governance-20261014`；实际 base `9ce46ceb926657a59616ac1741e498fd2e86820d`，origin 为 `https://github.com/caor3693-cmyk/Workhunter-v2.0.git`。根工作树原分支和未提交用户内容保留；本包在独立 worktree 中完成，不改产品代码。

本包只允许 `scripts/work_package_scopes.json`、`tests/test_scope.py` 及既有管理路径；此次实际交付另含本文件与 `PROJECT-SYNC-EXECUTION-20261014.json`。`docs/TASKS.md`、`docs/CONTRACTS.md` 与 PRODUCT §5 首页摘要文字的同步必须使用独立 DOC 包，不混入治理或首页功能 PR。PRODUCT 的这处更新依据用户 #42 对首页摘要撤去的明确要求，八项产品选择和来源/维护摘要保留。当前 base 的旧 `GOV/#24` 声明只用于检验独立治理机制兼容性，实际新工作为 #47，已关闭 #24/#32 不重开、不冒称再次修复。

## 工作包与交接

| 包 | 实际 Issue | 精确允许路径 | 接口/共享 owner | 验收 |
| --- | --- | --- | --- | --- |
| GOV-20261014 | #47 | scopes、scope 测试及既有管理路径 | 不改 checker、workflow 或产品；独立复核后进入实际功能目标 | 正确管理变更通过；功能/文档混入被拒；候选规则不能自授权 |
| DOC-20261014 | #47，关联 #42/#43/#49/#17/#15/#48 | TASKS、CONTRACTS、PRODUCT 及既有管理路径 | 仅任务/合同解释和 §5 首页摘要撤去的已授权文字同步；不改变八项产品决定 | 文档与受审范围一致；产品实现仍拒绝 |
| LINKS | #43，关联 #9/#2/#48 | cards.js、dom.js、test_cards.mjs、verify_official_navigation.mjs | 同一前端整合者；HTTP(S)安全规则保留；先定位真实导航原因 | M1-05：三校，列表/详情，鼠标/Enter，用户宿主与常规浏览器；受限与按钮失败分开 |
| HOME-SUMMARY | #42，关联 #14/#3 | frontend/index.html、home.js、routes.js、frontend_pages/page_routes/query_state/api_client 测试、test_home_summary.mjs | 同一前端整合者在链接调查后处理；无后端 API 合同变化 | M2-08、M1-06：首页无专用摘要请求/渲染/协调依赖；来源和维护摘要保留；筛选/分页/晚响应回归 |
| GZHU-20261014 | #49，关联 #31/#12 | gzhu.py、本校测试/fixtures；必要 registry.py、config/schools.json | 来源接口冻结；两个共享配置路径只由 root 整合，只改广州公开来源登记 | M2-01、M1-01：公开栏目/分页/终点/失败与去重；同口径逐校覆盖；不把 fixture 当覆盖 |
| SCUT-COMPLETION | #52，关联 #15/#17/#31/#12 | scut.py、test_scut_sources.py | 只修已证实的 NCSS 终页 completeness；不改公共 common/policy/discovery/写服务或其他学校 | M3-04：可证完整有限栏目与部分/循环/分页不明反例；真实无变化另交证据 |
| W06 | #17，关联 #5/#15/#48/#2/#3/#4 | version.py、build_site.mjs、preview worker、review 页面、verify_m0_m1/verify_m2、ops/verify_m3.py、限定验收测试、README、MANUAL_QA、.openai/hosting.json | 单一 root 整合者；只处理身份、已证实代理原因、私有 Site/恢复材料；保留 hosting project | R-VERSION、M3-04、M4：真实源码/构建/部署/API 区分，当前快照隔离恢复，人工 Gate 顺序保持 |

完整机器路径以本治理候选规则为审查对象；只有独立复核后进入**实际 PR 目标**才成为受信输入。登记 `FRONTEND-20261014 = LINKS,HOME-SUMMARY`，分支 `codex/frontend-repair-`；仅修 #42 可使用 `HOME-SUMMARY` 单包与 `codex/home-summary-`，无需声称 #43 已修。总整合分别登记不含 W03 的 `REPAIR-20261014`、包含 W03 的 `REPAIR-W03-20261014`，以及原组合加 `SCUT-COMPLETION` 的 `REPAIR-20261014-WITH-COMPLETION`；精确组合不得互换，整合分支 `codex/repair-integration-`。W03 仅增加 #49 为关联号，既有来源边界保留。#52 在本轮真实材料审查中新建，原 #33 历史完成保持。

普通来源包无法取得 API、domain/policy、services、writer、迁移/schema、首页或检查器权限。GZHU 对上述路径显式禁止；HOME-SUMMARY 不允许修改其他页面摘要或后端摘要；LINKS 不获得代理或首页权限，代理已证实联动归 W06。W06 不允许 API/query/schema 或生产切换，也不成为全仓库兜底。

## Project 5 实际结果

2026-10-14 16:07:33.559（Asia/Shanghai）使用既有 Git Credential Manager 授权，以原生 GraphQL **只读**查询 `caor3693-cmyk` 的 Project 5 身份、字段/选项和条目。HTTP 200，但 GraphQL 返回 `INSUFFICIENT_SCOPES`：既有授权 scopes 为 `gist, repo, workflow`，`projectV2` 需要 `read:project`。Project 结果为空，未取得字段/选项/条目，也没有实施原生写入或写后回读。没有输出/落盘凭据，没有扩大权限。

#50 保持 Blocked/open。这是当前实测权限不足，不把旧 `NOT_FOUND` 记录冒称本次结果。原生 field/item ID 的10月12日快照继续保留，不能用于未经当前回读的写入。

`PROJECT-SYNC-EXECUTION-20261014.json` 合并旧 `config/project.json` 26项 pending、本轮 #47—#50 的4项新增及执行中新建 #52，按标准 Issue URL 去重为**31项**；#42/#43/#31/#12/#15/#17 的增量不重复计数，旧 item ID 全部原值保留。该清单是待办与实际读取失败回执，**不是原生同步成功回执**。未来可用授权通道恢复后，先读取真实字段/选项和所有现有条目，按 URL 幂等写入，再逐项回读；仅成功回读项可清除 pending。管理通道不足本身不新增产品发布门禁。

## 自验与状态

- 当前固定 CI 依赖在本 worktree 隔离虚拟环境中安装；没有修改系统 Python。环境为 bundled Python 3.12、Node 24；正式 CI 为 Python 3.11、Node 22，该差异如实记录。
- 首次 `pytest tests/test_scope.py -q`：166 passed，0 failed；之后 DOC 精确文档增量的本轮52项全部通过；neat-freak 收尾及 #52 新增包后，本轮64项正反回归全部通过。最终 scope 收集180项，未改变的历史用例不重复运行，未把最终180项写成一次完整运行结果。
- `node --test tests/*.mjs`：122 passed，0 failed。
- `git diff --check`：通过。构建器明确拒绝未提交源码，首次治理提交 `262b624525915fc906810b1448de3d87131e7f20` 后构建与生成 worker 语法检查通过；未放宽构建器。
- 完整 Python 回归由主整合者对同一产品基线统一执行；本包只改规则与范围测试，其他产品代码未改。此前重复的本地完整回归进程按整合协调停止，不记作通过。
- 使用实际 base SHA 导出的 checker 检查完整治理 PR 差分：`262b624525915fc906810b1448de3d87131e7f20` 对 base `9ce46ceb926657a59616ac1741e498fd2e86820d` 的四路径完整差分通过（GOV 旧机制兼容声明）。不执行候选规则为同批功能授权。主整合者已独立逐行审阅规则和新测试，未发现阻塞；该复核与治理提交后方可建立功能 PR 目标。

按本轮用户要求使用现有 neat-freak 3.0.0 做治理包内保行为知识收尾：机械枚举本树 Markdown/规则/配置，核对实际规则来源、受影响文档与可信目标；规则、测试和交付说明为 changed-and-verified；Project 原生运行面 pending；产品运行面 out-of-scope；记忆 not-applicable；工作树/隔离测试环境保留供复核。收尾后重跑本轮64项正反测试及差分检查，没有全仓格式化、删除用户文件、删 worktree、停服或改正式站。

本包自验完成只进入 Awaiting verification。功能实现、原文真实浏览器复现、私有 Site、人工 M1→M2→M3→M4、当前快照恢复与正式发布由各自包另交证据；本治理文档不代签通过、不自动关闭 Issue。
