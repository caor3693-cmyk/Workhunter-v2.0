# 首页更新区块修复（2026-10-14）

Refs #42。工作包 HOME-SUMMARY，单一前端整合者 root；base `262b624525915fc906810b1448de3d87131e7f20`，分支 `codex/home-summary-20261014`。#47 治理由独立实施者提交，root 逐行审阅后作为实际功能目标；功能包不修改 checker 或范围规则。

允许且计划修改：`frontend/index.html`、`frontend/pages/home.js`、`frontend/pages/routes.js`、`tests/test_frontend_pages.mjs` 和本交付文档。无公共 API、存储、来源或后端摘要接口变化。验收 M2-08（首页去除更新区块及专用请求）、M1-06（首载/重载、十校/校区、筛选、日期视图、分页和迟到响应）。来源页和维护页摘要保留。

#43 优先调查已经核对 Site v5 源码、组件和代理身份；管理员浏览器策略拒绝私有 Site 操作，真实三校导航矩阵仍 Blocked，不预设 `_blank` 原因、不改链接或安全规则。该限制只阻塞对应运行验收，继续本独立首页修复。

实际修改上述 4 个实现/测试文件：移除 HTML 区块、摘要 import/reader/render/reload/sidecar，首页读路由现在仅目录与机会。测试 DOM 对已删除节点返回 null，首载/重载断言仅两种请求；慢目录、失败保留、dataset 协调、草稿、日期、分页和迟到请求继续回归。没有改样式、卡片、原文链接或其他页面摘要。

清理前最小相关回归 92 passed；neat-freak 范围内清理删除测试中已失效的首页摘要响应分支，复测完整 Node 122 passed，0 failed/skip。`git diff --check` 通过。完整 Python 基线已实际执行：Windows 本机启动器场景遇到沙箱进程回收权限失败，其他场景完成；此失败与首页代码无关，正按隔离宿主用户重测，不能先写全绿。提交后构建器与 worker 语法检查、实际目标导出的完整差分检查另行记录。

neat-freak 事实面：代码 changed-and-verified；文档 changed-and-verified（本文件），PRODUCT §5 旧摘要描述将由独立 DOC 包按 #42 同步；规则 verified-current（来自独立治理目标）；运行/Site pending；记忆 not-applicable；工作区保留复核现场，无删除或全仓格式化。自验完成进入 Awaiting verification，用户 M2-08/M1-06 原编号复验前不 Done，不关闭反馈 Issue。
