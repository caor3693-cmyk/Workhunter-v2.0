# Workhunter v2.0

面向电气与自动化应届求职者的十校招聘发现工具：按学校找到近期公告和活动，看清时间、举办地点、工作地点，并跳转官方原文。

本仓库承接独立重建。首版目标包括招聘发现、简要详情、站内更新摘要、受保护的维护网页和持续采集；当前仍为 M0 工程骨架，用户验收未通过，实际状态见 [STATUS](docs/STATUS.md)。独立岗位库、全国企业直采、完整参会名单工程后置。

## 开发入口

1. [当前状态](docs/STATUS.md)：当前实际完成情况、用户结论、发布状态及下一步。
2. [产品规格](docs/PRODUCT.md)：已确认范围、八项产品决定、功能清单。
3. [数据与工程合同](docs/CONTRACTS.md)：字段证据、API、卡片和模块职责。
4. [执行任务](docs/TASKS.md)：工作包顺序、允许改动范围、验收与 Codex 指令。

项目排期与追踪见 [任务看板](docs/BOARD.md)、[一周路线图](docs/ROADMAP.md)，每阶段使用当前 [M 版手工核验清单](docs/deliveries/MANUAL_QA_M.md)。阶段及检查点统一 M0—M4 / Mx-yy，旧 S/G 按 [命名映射](docs/deliveries/M_NAMING.md) 追溯。实际 Issue 和原生 Project 状态统一登记在 STATUS；原生视图仍受 [配置任务 #19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) 阻塞。先在私有 Site 交付，M0—M4 逐项验收后才正式上线。

开发者先读 [AGENTS.md](AGENTS.md) 和 STATUS。基础产品/工程合同版本为 1.1，当前阶段管理版本为 1.2；八项产品范围保持不变。产品名称中的 v2.0 与规范版本不是同一编号。

## 启动说明

M0/W00 已有独立 API、空库和原生页面骨架。当前源码使用 M0 命名；已保存 Site 仍为旧候选，两者构建身份分别记录在 STATUS。以下命令从本仓库运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m backend.cli init --db .runtime/dev/workhunter-v2.sqlite3
.\.venv\Scripts\python.exe -m backend.cli serve --db .runtime/dev/workhunter-v2.sqlite3 --port 8766
```

`init` 是唯一建库入口；已有不兼容库会明确失败，不修复或覆盖。`serve` 先验证新库，不自动初始化，校验失败退出 2。默认只监听本机；读取接口遇到缺库、结构残缺、损坏或项目身份不匹配时返回可解释的 503。初始化只有十校待核验种子，没有招聘记录。

必要工程检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/test_preview_proxy.mjs
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

打开 `http://127.0.0.1:8767/`。此模式的令牌只发送至本机环回 API，不能作为远程 HTTPS 连接证明。私有 Site 的固定代理与运行要求见 [验收宿主说明](ops/preview/README.md)；实际 Site/提交/dataset 和用户结论以 [STATUS](docs/STATUS.md) 及当前 Gate 为准。

M0 尚未实现采集刷新。`python -m backend.cli refresh` 和 `python -m backend.worker` 都明确返回退出码 2，不写业务库或生成成功记录。真实手动刷新和自然调度分别由 W01/W05交付；不能将这些占位入口当作完成能力。

## 数据与公开材料

[十校入口种子](config/schools.json)用于启动官方来源核验。登记入口不代表自动采集可用、字段完整或覆盖完成。

源码仓库保存代码、公开配置、合同和少量经核验的脱敏测试样例。运行数据库、原始响应、备份、私有日志和凭据保留在各自运行环境。维护者可补充合法取得的官方公开材料，新业务库从近期官方来源重新采集。
