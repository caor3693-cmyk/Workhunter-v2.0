# Workhunter v2.0 当前状态

更新2026-10-14，Asia/Shanghai；产品决定ABAAAAAB。当前事实与人工结果入口：[M1—M3反馈](deliveries/M1-M3-FEEDBACK-20261014.md)。

## 当前结论

[私有Site v5](https://workhunter-v2-review.sage-candy-7999.chatgpt.site/)真实读取已恢复，用户已确认招聘卡片。应用源码9665e245d200b84398df42636d52321341f67063，0.5.0/M3/schema3，服务器环境修订4的私有部署成功；本轮未重发Site。

用户反馈：首页删除“最近更新”[#42](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/42)、每条原文均不跳[#43](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/43)、广工外九校扩源（沿用[#31](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/31)/#12）。本轮仅完成Issue/管理资料，三项未修。

## 验收与项目管理

用户明确授权未报错已交付项完成标记，实际关闭11项：#22/#29/#30/#33/#34/#35/#32/#10/#13/#14/#16。34个Issue当前19 closed / 15 open，[仓库Board](BOARD.md)与[Roadmap](ROADMAP.md)已更新。

M1-01覆盖与M1-05原文失败，其他M1已交付项通过；M2-01覆盖待扩，M2-02—08原功能通过，#42新展示变更未做；M3-01/02/03/05/06已交付项通过，M3-04整源无变化真实材料仍阻塞。个人MCP客户端未配置、七自然日观察不足、M4未交付，均不标通过。

M0历史通过保留。#2/#3/#4保持Blocked，按M1→M2→M3→M4复验；#15待材料，#17下一轮收尾Ready，#18正式发布Blocked/未执行。PR #38/#39/#40/#41仍draft/open，未合并。

[原生Board](https://github.com/users/caor3693-cmyk/projects/5/views/1) / [原生Roadmap](https://github.com/users/caor3693-cmyk/projects/5/views/2)历史已建，本轮原生字段未同步：无可用Projects/GraphQL/gh授权通道且浏览器清单为空。config保留10-12原生快照及26项待同步（含4新增）；本轮last_verified仅指GitHub Issue/仓库索引。

## 最新真实运行

2026-10-14 11:43本机隔离real dataset ds-da169234-b434-44b1-bce3-4d40abb99e19，622机会/441材料/2911历史/4轮。华工81、广工216、上电80、东北电力6、长沙理工14、三峡200、广大3、湖南22；华电0、中南0。全库数与近期电气视图区分，全部school_wide仍false；限制/失败如实标注，受限路径停止。

自然3轮、手工1轮；9665e24于14日01:03、07:03实际自然重复，结束01:08、07:06，下次登记计划13:03；退出与业务partial分开。七自然日观察未达。历史292恢复副本不能称为当前622恢复证明。

独立验收宿主按用户“验收期间独立运行”授权继续，私有状态文件回读API/tunnel就绪。本轮系统任务读取被沙箱拒绝，不称重读成功，不改变原任务/令牌。维护演练继续隔离。库、材料、日志/凭据不公开；验收结束后停用，结束动作尚未发生。

## 下一轮与后续讨论

[#17](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/17)集中完成首版反馈与材料，再做M4/发布准备；限域登记与顺序见反馈文档。新编号/必要路径先按可信GOV登记。

[#44日程表](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/44)与[#45 AI改简历](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/45)仅未来讨论、暂不开发。用户选择下一轮交付时提醒；当前对话跟进已建立，确认新软件交付后提醒一次并暂停，#17保留提醒条款。

E工作区为独立管理分支codex/w05-b-feedback-20261014，基于PR#41 head 0da12302838f23b59a246abdfbb57b19f1b5ffc1；main引用未改，D验收运行源码分支保持。不切换正式站、不改域名/可见性、不归档或删除旧资产。
