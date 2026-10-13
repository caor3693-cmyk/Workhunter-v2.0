# Workhunter v2.0 当前状态

核对日：2026-10-13，Asia/Shanghai。产品1.1、合同1.3、执行计划1.4及 ABAAAAAB 范围保持。这里是唯一当前入口，历史细节留在原交付包。

[M1先行复验](deliveries/M1-SITE-RECHECK-20261012.md) → [M2操作包](deliveries/M2-REVIEW-20261012.md) → [M3运行与恢复](deliveries/M3-REVIEW-20261013.md)；本轮知识及GitHub收尾见[M3 neat-freak记录](deliveries/M3-NEAT-20261013.md)。

## 当前实现与运行

W05-A #15 / W05-B #16 本机实现、自验和独立审查完成，涵盖真实自然调度、失败/中断恢复、一致备份、新路径恢复重启及实际stdio MCP。运行与前后端构建为8057f1ad8d02e467471a0e60d54ca1dfa74de148，0.5.0/M3/schema3/real，dataset ds-170fe490-ca02-4441-ab88-ac5344645f78；445机会/517材料/1985历史/17运行。文档提交不替换已运行的源码身份。

r3于2026-10-13 11:29:35自然启动、11:35:34完成，运行源码6f71f3d；collector/scheduler/宿主退出0，业务和覆盖均partial。新增148，官方变化17、解析改进84、材料冲突13，分类重叠不可相加。后续W03修复及423定向语义修订0 HTTP/0新材料，旧值/材料保留，另记semantic_revision=1；r2失败历史保留。

[本机招聘页](http://127.0.0.1:8891/)、[来源状态](http://127.0.0.1:8891/sources)、[构建核验](http://127.0.0.1:8891/review)及[隔离恢复页](http://127.0.0.1:8893/)在本轮再次确认HTTP可读。六小时任务r4 Ready、绑定8057，下一次2026-10-13 17:29:34（北京时间）；当前构建尚未自然触发，只观察1自然日，未满6h后续周期或7日运营。

DB备份database_only，恢复副本ID/版本一致，旧调度not_ready不自启。另行只读raw归档375材料行/373文件全部SHA一致；跨宿主重放需显式索引映射，没有自动旧路径resolver。主库和恢复库API/实际stdio MCP同源同dataset，读取未改数量/ID；用户MCP客户端未配置。

原主工作区用户改动、M1独立先行142条候选和M2原库均保留。M2历史297机会/246材料/1333历史/15运行，dataset ds-3ceedaa1-97f2-4625-b180-35d7f162668a；原机会1—297与原库SHA未变。完整换代、恢复、测试、来源限制见[M3包及脱敏证据](deliveries/M3-REVIEW-20261013.md)。

## 外部交付与用户门槛

用户要求neat-freak清理后上传GitHub，代码及脱敏证据已正常推送并创建[治理#39](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/39)、[来源#40](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/40)、[M3#41](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/41)三份draft PR；实际分支与回读见[收尾回执](deliveries/M3-NEAT-20261013.md)。最终CI以PR当前检查为准，不合并、不force push、不关闭业务Issue。

现有[私有Site](https://workhunter-v2-review.sage-candy-7999.chatgpt.site)本轮只读回核仍版本4、custom owner范围、0外部访客；没有更新。此前真实API HTTPS通道被自动审批拒绝，本轮GitHub授权不扩展到外部API/Site更新。整源checked_no_changes真实样本、持续观察、Site及用户Gate保持待验证；#18正式发布仍Blocked。

| 编号 | 历史用户结果 | 当前候选 |
| --- | --- | --- |
| M0-01—07 | 通过 | 保留 |
| M1-01/05/06 | 失败 | 修复已实现，Site交付及原编号复验待确认 |
| M1-02/03/04/07/08 | 通过 | 历史保留，受影响项仍需回归 |
| M2-01—08 | 未测 | 工程/材料已备，须在M1 Gate后确认 |
| M3-01—06 | 未测 | 本机工程证据列明，M3-04整源样本/Site/前序Gate待完成 |
| M4 / #18 | 未测 / 发布Blocked | 尚未进入，不按日期自动发布 |

## 规则与历史索引

阶段统一M0→M4，AGENTS/PRODUCT/CONTRACTS/TASKS/MANUAL_QA的S/G编号依照[M命名映射](deliveries/M_NAMING.md)理解，不执行两套Gate。规则真身为AGENTS.md，范围checker从实际目标导出，未为清除审计发现放宽规则。长期生成记忆只读，本轮未写。

[M1/M2历史收尾与CI](deliveries/M1-M2-CLOSEOUT-20261012.md)、[真实十校样本](deliveries/evidence/M2-REAL-SOURCES-20261012.json)、[原用户结果](deliveries/M0-M1-FEEDBACK2-20261011.md)、[反馈收尾约定](deliveries/FEEDBACK_CLOSEOUT.md)。历史M2冻结26060f8及其CI不代表M3候选CI。

仓库[Board](BOARD.md)与[Roadmap](ROADMAP.md)保留原计划及用户结果；原生Project5的30项/21open/9closed、Backlog5/In progress9/Awaiting verification1/Blocked6/Done9为2026-10-12快照，本轮未修改Project字段或业务Issue状态。
