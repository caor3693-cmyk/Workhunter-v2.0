# Workhunter v2.0

面向电气与自动化应届求职者的十校招聘发现工具：按学校找到近期公告和活动，看清时间、举办地点、工作地点，并跳转官方原文。

本仓库承接独立重建。当前已修复 M0 读取与独立页面，并实现 M1 两校有限真实采集、证据、卡片详情与查询链路；用户原结论保留，工程与私有 Site 的实际身份见 [STATUS](docs/STATUS.md)。M2维护网页、真实摘要与十校有限来源工程已实现；自然调度与正式发布仍按后续阶段执行。独立岗位库、全国企业直采、完整参会名单工程后置。

本轮资料：[M1先行复验包](docs/deliveries/M1-SITE-RECHECK-20261012.md)、[M2完整操作包](docs/deliveries/M2-REVIEW-20261012.md)、[M3运行与恢复核验包](docs/deliveries/M3-REVIEW-20261013.md)。M3 新增隔离宿主调度、受管理备份/恢复和只读 stdio MCP；实际运行与审批边界按 STATUS 及交付包记录。本机候选不当作 Site 交付。

## 开发入口

1. [当前状态](docs/STATUS.md)：当前实际完成情况、用户结论、发布状态及下一步。
2. [产品规格](docs/PRODUCT.md)：已确认范围、八项产品决定、功能清单。
3. [数据与工程合同](docs/CONTRACTS.md)：字段证据、API、卡片和模块职责。
4. [执行任务](docs/TASKS.md)：工作包顺序、允许改动范围、验收与 Codex 指令。
5. [M1 修复与 M2 执行计划](docs/deliveries/M1-M2-EXECUTION-20261011.md)：本轮可信GOV、共享修复、两条实施线与M2完整交付；配套 [对抗审查](docs/deliveries/M1-M2-AUDIT-20261011.md)。已完成的R0—R5见[历史计划](docs/deliveries/M0-M1-EXECUTION-20261011.md)。
6. [反馈与清理同步规则](docs/deliveries/FEEDBACK_CLOSEOUT.md)：收到验收反馈后，限域修复、源码清理、neat-freak 对齐、回归及 GitHub 回读必须一起完成。

项目排期与追踪见 [任务看板](docs/BOARD.md)、[一周路线图](docs/ROADMAP.md)，每阶段使用当前 [M 版手工核验清单](docs/deliveries/MANUAL_QA_M.md)。阶段及检查点统一 M0—M4 / Mx-yy，旧 S/G 按 [命名映射](docs/deliveries/M_NAMING.md) 追溯。实际 Issue 和原生 Project 状态统一登记在 STATUS；原生[Board](https://github.com/users/caor3693-cmyk/projects/5/views/1)和[Roadmap](https://github.com/users/caor3693-cmyk/projects/5/views/2)已建立，#19技术配置完成。当前M0通过，M1三项反馈已进入修复候选、仍等用户复验；本轮新增#33队列/#34字段/#35材料归属P1和#32实施前置，共享CORE及两校修复已完成，M2维护、摘要和十校整合工程已冻结，实际297条候选与四校最低电气样本成立，用户尚未复验。原生30项状态已回读，历史结果保留。用户结论详见[第二轮结果](docs/deliveries/M0-M1-FEEDBACK2-20261011.md)。先在私有 Site 交付，M0—M4 逐项验收后才正式上线。

开发者先读 [AGENTS.md](AGENTS.md) 和 STATUS。基础产品版本为 1.1，工程合同为 1.3，当前执行计划版本为 1.4；八项产品范围保持不变。产品名称中的 v2.0 与规范版本不是同一编号。

## 启动说明

当前修复候选独立 API 使用 schema 3；Site、源码与数据身份分别记录在 STATUS。以下命令从本仓库运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m backend.cli init --db .runtime/dev/workhunter-v2.sqlite3
.\.venv\Scripts\python.exe -m backend.cli serve --db .runtime/dev/workhunter-v2.sqlite3 --port 8766
```

`init` 显式建库，初始化只有十校待核验种子，没有招聘记录。已识别的 v2 schema 1/2 库使用 `backend.cli migrate --db <path>` 显式迁移，先保留 SQLite 备份再事务升级；外来、不兼容或损坏库明确拒绝。`serve` 和 GET 不建库、不迁移，校验失败退出 2 或返回可解释的 503。默认只监听本机。

必要工程检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.mjs
node scripts/build_site.mjs
node --check dist/server/index.js
```

本机页面预览使用下面的带令牌启动方式。如果上面的检查实例仍占用 8766，先在其终端停止该实例；启动脚本会报告端口冲突。构建要求已提交、干净的源码：

```powershell
node scripts/build_site.mjs
.\scripts\start_local_api.ps1
$env:WH_PREVIEW_LOCAL = '1'
node scripts/preview_site.mjs
```

打开 `http://127.0.0.1:8767/`，来源页为 `/sources`，核验页为 `/review`。启动器核对 health/version、数据身份和本次进程的实际监听端口后才写入就绪记录。端口已占用时保留现有进程。此模式的令牌只发送至本机环回 API，不能作为远程 HTTPS 连接证明。私有 Site 的固定代理与运行要求见 [验收宿主说明](ops/preview/README.md)；实际 Site/提交/dataset 和用户结论以 [STATUS](docs/STATUS.md) 及当前 Gate 为准。

M1 手动刷新使用已显式初始化的独立库：

```powershell
.\.venv\Scripts\python.exe -m backend.cli refresh --db .runtime/dev/workhunter-v2.sqlite3 --pages 2 --details 12
```

可用 `--school scut` / `--school gdut` 限定学校，`--resume <run_id>` 接续持久游标和待补任务。`backend.worker` 是同一入口的单次执行，没有设置自然调度。每个栏目最多检查指定页数与详情数；预算结束、正文未取得、受限或重复分页均保留部分覆盖，不推断官方取消或完整零结果。网络读取在事务外，逐页短事务提交；失败保留此前可靠事实。新收录、解析补全、官方变化和未裁定材料冲突分别记账，重复采集不制造变化。

当前华工统一就业入口受限，实施学院公开补充栏目；广工实施宣讲、双选与招聘公告三个公开栏目。另外六校已有有限真实材料；华电北京/中南历史受限路径停止，华电保定网络失败，范围与限制见STATUS。字段与片段必须绑定实际取得材料，未披露、未取得、待核实、不适用和冲突按独立状态显示。合同要求会场与工作地分开、不得凭发布时间补活动年份；本轮审查发现若干字段语义反例，按#34定向修复和回归。

## M3 隔离运行

`config/operations.json` 固定默认 6 小时周期、单源 90 秒、整轮 1200 秒、2 页/12 条详情、48 请求/1 次重试，保留最近 50 个执行回执。健康来源 24 小时未复核进入维护待办，48 小时明确陈旧；失败和受限仍保留原状态及此前可靠内容。访客 GET 与 MCP 都不启动采集。

Windows 当前用户任务通过以下入口显式注册；已有同名任务会被拒绝，原站任务不变：

```powershell
.\ops\install_scheduler.ps1 -PythonPath .venv/Scripts/python.exe -DatabasePath .runtime/m3-real/workhunter-v2.sqlite3 -BackupDirectory .runtime/m3-backups
.\.venv\Scripts\python.exe -m ops.scheduler status --db .runtime/m3-real/workhunter-v2.sqlite3
```

首个未来启动为真实 bootstrap 排程，后续间隔 6 小时；必须等宿主实际触发才记自然运行。任务独立于 Codex 和浏览器，但当前用户必须已登录、电脑开启；这不是远程常驻宿主证据。Linux 用户级 service/timer 模板位于 `ops/systemd/`，未安装，启用前须核对实际路径、任务身份与计划。来源页读取已登记的下次计划，计划逾期或恢复到另一路径时不猜未来时间。

每轮采集后取得一致 SQLite 备份，最多保留 7 个已验证受管理副本和 256 MiB，预留 128 MiB 空闲容量；新副本完整性、外键、业务计数和 SHA 校验后才轮转冗余副本。损坏、未管理的文件和唯一有效副本不会被清理。独立手工备份默认只预检，需显式 `--apply-retention` 才执行同一受管理轮转。

```powershell
.\.venv\Scripts\python.exe -m ops.backup backup --db .runtime/m3-real/workhunter-v2.sqlite3 --directory .runtime/m3-backups --retain-count 7 --byte-cap 268435456 --min-free-bytes 134217728
.\.venv\Scripts\python.exe -m ops.backup verify --backup <已核验备份>
.\.venv\Scripts\python.exe -m ops.backup restore --backup <已核验备份> --target <已存在的新隔离目录>/restored.sqlite3 --expected-dataset-id <实际dataset>
.\.venv\Scripts\python.exe -m ops.mcp --db .runtime/m3-real/workhunter-v2.sqlite3
```

恢复拒绝覆盖、原业务路径和原调度绑定路径；新隔离路径上的旧调度不会自行启用。备份只包含数据库，manifest 明确指出原始材料需要另行保留的只读归档，不能声称同时备份了完整原文。MCP 固定 7 类只读工具，其中诊断必须在启动进程时独立指定 `--allow-diagnostics`，不采用业务维护口令；16 KiB 请求、64 KiB 响应、最多 50 条分页、每分钟 60 次调用。客户连接配置、实际 stdio 调用、远程 Site 和用户 Gate 分别记录。

`python -m ops.verify_m3 --db <隔离库> --api http://127.0.0.1:<实际API端口> --output <新的证据文件>` 对账实际 API 与 stdio MCP，拒绝覆盖已有证据，不会替用户填写通过。

隔离边界材料使用显式新目录，命令拒绝覆盖已有内容：

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_acceptance prepare --output .runtime/isolated-review-new --isolated
.\.venv\Scripts\python.exe -m scripts.prepare_acceptance serve --bundle .runtime/isolated-review-new/manifest.json
node scripts/verify_m0_m1.mjs --fixture-preview .runtime/isolated-review-new/manifest.json
```

两个服务在不同终端运行，固定API 8788 / 页面8789，仅环回；页面醒目标为本机合成，阻止占位原文/附件外访，不接真实Site通道。主库始终分开。`node scripts/verify_m0_m1.mjs` 只生成工程回归材料，浏览器视觉、真实采集、Site身份与用户验收另行核对。原编号七项/八项操作见 [当前完整包](docs/deliveries/M0-M1-REVIEW-20261011.md)。

## 数据与公开材料

[十校入口种子](config/schools.json)用于启动官方来源核验。登记入口不代表自动采集可用、字段完整或覆盖完成。

源码仓库保存代码、公开配置、合同和少量经核验的脱敏测试样例。运行数据库、原始响应、备份、私有日志和凭据保留在各自运行环境。维护者可补充合法取得的官方公开材料，新业务库从近期官方来源重新采集。

M2维护需要独立业务口令会话；平台登录不代替业务授权。材料先预览再明确提交，纠错/撤回有回执和历史。固定隔离库供演练，禁止占位链接写入真实环境或访问外网。演练入口由 `scripts.prepare_m2_acceptance` 显式生成全新目录，口令只存本机私有文件；`scripts.verify_m2` 保持八项用户结果未测。
