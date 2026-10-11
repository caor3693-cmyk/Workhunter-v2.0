# M0 私有验收宿主

任务：W00 / #6，阶段：M0 / #1。允许路径：backend/ 初始模块、frontend/ 最小骨架、ops/preview/、scripts/、tests/、依赖/CI、Site 非秘密身份、启动说明和当前状态文档。接口见 CONTRACTS；M0只读，不提供维护写操作。当前源码已统一M命名；已保存的旧S0候选、当前用户失败和待修复问题以 [STATUS](../../docs/STATUS.md) 为准。源码清理和打包不代表重新发布或恢复Site连接。

原生前端由 `node scripts/build_site.mjs` 嵌入 Worker ESM，输出 `dist/server/index.js` 与 hosting manifest；未迁移 Python、SQLite 或业务判定到 Workers。静态资源放 `/frontend/*`，避免与业务 `/api/*` 冲突。前端提交由构建前的干净 HEAD 取得；源状态先提交再构建、推送和打包。

生产形式的 Sites 平台 URL 在本项目中仅用作 owner-private 阶段验收宿主，受平台登录保护；它与 Workhunter 正式发布及旧站切换分别管理。禁止调用公开访问变更或正式发布 #18。

代理只接受公开 GET 固定路径与公告正整数详情，禁止任意 URL、写方法、维护路径和重定向；超时12秒、JSON响应上限1MiB，不转发平台 Cookie、用户 Authorization、Set-Cookie或内部日志。M2维护Cookie/CSRF接入尚未实现，由W04另行扩展并验证。

本阶段使用临时 Cloudflare HTTPS 开发通道至新服务的本机环回端口。`WH_API_ORIGIN` 和 `WH_API_SERVICE_TOKEN` 放在 Site 服务端配置，令牌标记 secret；前端和源码均不得包含其值。配置该通道的凭据传输须使用届时有效授权。未配置/不可达时代理返回明确503/502，不回落到样例、旧站或缓存快照。当前代理只接受 `*.trycloudflare.com` 固定HTTPS上游；稳定开发宿主的切换需登记受控修改。

这是临时开发连接：需要本机在线及本次API/通道进程持续运行，没有自然调度或可用性保证。重新建立通道会改变上游地址，需受控更新Site配置并部署新的私有候选；Site主URL不变。M1真实采集和M3无人值守运行须分别验证，不从M0推断。

本机自验可使用 `WH_PREVIEW_LOCAL=1 node scripts/preview_site.mjs`，只向环回API传令牌。该模式验证真实新库和页面；它不证明Site HTTPS上游已接通。

CI初始引入范围检查：读取目标提交的TASKS.md，不读实施分支的范围声明；后续PR优先运行目标分支已有检查器。本次目标基线此前没有检查器，CI引入和反例自验属于W00 bootstrap。它不是GitHub分支保护；实际平台保护能力另在STATUS记录。
