# Workhunter v2.0 当前状态

更新2026-10-14，Asia/Shanghai。产品决定ABAAAAAB与固定十校保留。当前唯一入口为[本轮实际修复交付](deliveries/REPAIR-DELIVERY-20261014.md)、[BOARD](BOARD.md)、[ROADMAP](ROADMAP.md)。审查/交接为PR #51，已执行修复，非再次规划。

## 实际实现与追溯

独立治理PR #54（2ba101b）与独立DOC PR #57（4ea9168）已独立复核、CI通过，作为本轮整合真实目标，checker未改。首页#42同步删DOM和专用请求/渲染/协调依赖，PR #53；广州#49接入公开宣讲/招聘会分页，PR #55；新发现#52 NCSS逐页数量守卫和跨轮tail反例已修；offset>1终页保持partial，明确登录JSON分类为restricted（旧failed run未改），PR #56。版本0.5.1/M3/schema3；没有新API、岗位实体、写服务、迁移或全局样式。

#48确认v5的9665e245属于独立Sites源仓，不是GitHub提交；旧API宿主HEAD f8c3a1d本地存在但未推到GitHub，旧启动器将API声明写为Site SHA。76文件实体映射、声明和本地HEAD分别记录，未只改版本字符串。新版代码冻结GitHub55553fca；独立Site源/实际API干净checkout b75d2d0；230实体规范化一致，后续PR58文档提交只记录回执。

## 本轮运行数据与限制

2026-10-14本轮冻结real dataset ds-d8962f88-037e-44d9-b38e-ac685b43f1d4：781机会/593材料/3790变更/8run，26登记来源。相比16:10真实741快照，广州去重新增40，近期电气视图3→24（明确相关7/未知17）；十校同口径全表见交付及evidence/REPAIR-COVERAGE-20261014.json。其他校数保持，不用历史622、fixture、宽日期或换校凑数；全部school_wide=false。

当前781快照于16:49:53重新一致备份、恢复到新隔离路径，SHA/所有表计数/关系/完整性/外键一致。旧库/原文/原宿主任务保留；恢复副本不会自动启用原路径调度，实际API 127.0.0.1:8897从干净Site源运行，7路由/实际7类stdio MCP与781恢复库身份、计数、只读SHA一致。新路径自然计划未登记/not_ready、无下次时间。维护演练29条另恢复为isolated_fixture。

旧自然账本4 scheduled+1 manual均partial；当前候选另增3次manual（1准备interrupted、广州/NCSS各1partial），合计8 run=4 scheduled+4 manual。进程退出0不代表完整。NCSS实网第6页明确“请登录后查看”，已停止深页，前5页14 unchanged不代表完整无变化，#15/M3-04仍Blocked。华电北京/中南既有限制0请求，保定/湖南本轮连接失败，其他有限栏目继续保留事实。七自然日未达。

## Site、人工Gate与发布

新owner-private Site v6已保存并native回读（source b75d2d0，version_id见交付），尚无deployment/env revision。当前私有URL仍是旧v5；不能把旧v5用于新修复复验。新Cloudflare验收HTTPS通道启动被automatic approval以第三方敏感出站明确授权不足拒绝，用户授权pending；未启动新隧道、未改Site环境、未部署v6，#17保持Blocked。管理员浏览器策略明确阻止当前Site操作，#43三校列表/详情×鼠标/Enter×宿主/常规浏览器矩阵未执行，根因未证实，未猜测修改_blank。API与构建证据不冒充真实点击。

旧19项closed历史保持，#22/#29/#30/#33/#34/#35等不重开；新修复自验仅Awaiting verification/open。M0通过，M1→M2→M3→M4按原编号等待用户当前有效确认；#43/#15与剩余覆盖阻塞相应Gate，#18正式发布未执行。#17已完成源码整合、当前恢复/API对账和新v6保存；远程连接与部署Blocked，整体门禁未解锁。

## 原生Project与后置

#50真实原生GraphQL查询HTTP200/INSUFFICIENT_SCOPES，缺read:project；字段/选项/条目不可读，零写入/零回读成功。精确31pending（旧26+本轮47—50+52，按URL去重），旧item IDs保留，回执PROJECT-SYNC-EXECUTION-20261014.json不是同步成功证明。#50Blocked，不自行增加产品发布技术门禁。

#44日程表/#45 AI改简历在本次实际软件交付按约提起未来讨论，本轮未开发、未新增提醒。正式站、域名、仓库可见性、旧库/资产归档或删除均未执行。复核现场保留。
