# 2026-10-14 运行身份与 M3-04 只读审计

采样：2026-10-14 16:23:50，Asia/Shanghai。Refs #48、#15、#17；后续精确来源缺陷 #52。状态是构建者证据，用户结果保持待复验。

本包只读对账，允许写入本报告及同名去敏 JSON；未更改源码、库、时钟、宿主、调度、凭据或站点。完整读取 #51 两份交接、该管理分支 STATUS/BOARD/ROADMAP/PROJECT-SYNC，以及实际审查基线 AGENTS/PRODUCT/CONTRACTS/TASKS/MANUAL_QA/范围规则，使用既有 neat-freak 收束本包事实。固定源码基线为 9ce46ceb926657a59616ac1741e498fd2e86820d，管理资料提交为 dbe317438106c64f1cb8fd760f05e54bcf4dde30。

## #48：SHA 分属不同源码仓，后端声明不能代替宿主 HEAD

Sites 原生元数据回读确认 [私有 Site v5](https://workhunter-v2-review.sage-candy-7999.chatgpt.site/) 保存源码为 9665e245d200b84398df42636d52321341f67063，部署 appgdep_6ace4fcc461c8191814c364e697ed5af 成功，环境修订 4，访问为 owner custom/外部访问者 0。本轮取回的独立 Sites 源码仓 HEAD 正是此 SHA，工作树干净；它不是 GitHub 仓库中的应用提交。GitHub 连接器无法解析它不能据此断言源码遗失或部署错误。

实际隔离 API 宿主源码 HEAD 为 f8c3a1df80e0912fca80336b5c9fcf2973d45456，分支 codex/site-review-20261013，工作树干净。宿主 origin 仍指向本 GitHub 仓库；本轮按该分支 fetch 返回 remote ref 不存在，按该 SHA fetch 返回 not our ref。这证明当前 GitHub 远端不能提供该宿主提交，未把它写成已推送。

| 事实面 | 实际身份 / 结果 |
| --- | --- |
| 可审查 GitHub 源码 | 9ce46ceb926657a59616ac1741e498fd2e86820d |
| Sites v5 独立源码 | 9665e245d200b84398df42636d52321341f67063 |
| API 宿主本地 Git | f8c3a1df80e0912fca80336b5c9fcf2973d45456；远端不可 fetch |
| API /health 与 /version | 均 HTTP 200，0.5.0 / M3 / real；声明 backend_commit 为 Site SHA |
| 实际库 | schema3，dataset ds-c3c10b6e-f5d4-4ccf-9242-7ca9ce466cc3 |
| 库数量 | 741 机会 / 545 材料 / 3583 变更 / 5 run |

运行启动器 .runtime/run_review_api.py 直接覆盖 Settings.backend_commit 为 Site SHA；/version 的该值是配置声明，不能独立证明宿主 Git HEAD。没有只改版本字符串来消除差异。

固定 Git blob 与两个干净运行源码树共核对 76 个文件，以 CRLF→LF 归一后的 SHA-256 比较，避免把并行实施中的当前工作树当旧基线。41 个 backend 文件、11 个 ops 文件、实际学校/运行配置及全部访客主流程源码一致。73 个文件三处一致；差异只有 config/project.json 的管理快照，以及 frontend/pages/review.html、review.js 的本机新库样本和 M3 核验材料。宿主与 Sites 源码的 76 个文件归一后全部一致。这是有范围的源码映射，不是全仓安全认证。

历史本地构建 gzip 内含两个文件，20 项内嵌前端资产与取回的 v5 Sites 源码在替换构建标记和归一行尾后全部一致。原生保存归档摘要为 sha256:a8ac4f219e0f4564b07ff5e8807d0b1da039396fd4718384a893d81245d70506；本地历史 gzip 及解压 tar 摘要均不同，所以不声称本地文件就是原生保存归档。原生保存版本→源码→成功部署链已确认，部署字节/用户浏览器链路本包未直接回读。远程浏览器访问仍按既有 blocked 记录，不绕过宿主策略。

下一次交付必须分别列 Github source、Site source、host Git、API declaration、deployment/env、schema/dataset 和采样时间；实现源码应从已推送的新基线继续，不回退工作树。本轮原版本追溯问题已给出原因和实体映射，最终新版运行身份由整合者在 #17 更新。

## #15：本轮账本确有四次自然执行，尚无完整范围无变化样例

| 真实 run（北京时间） | trigger | 新收录 / 修改 / 无变化提交 | 业务结果 |
| --- | --- | ---: | --- |
| 10-13 19:03:05—19:05:26 | scheduled | 292 / 117 / 2 | partial |
| 10-13 23:22:55—23:27:22 | manual | 130 / 100 / 172 | partial |
| 10-14 01:03:10—01:08:04 | scheduled | 94 / 62 / 152 | partial |
| 10-14 07:03:06—07:06:09 | scheduled | 106 / 68 / 193 | partial |
| 10-14 13:03:11—13:05:39 | scheduled | 119 / 82 / 175 | partial |

以上直接来自实际库 runs 与 operations_schedule 账本，fixture 均 false；自然 4 次、手工 1 次。子进程和调度退出均为 0，业务 completeness 全部 partial。每轮 15 个登记来源，没有 source status=complete 的条目；存在重复无变化提交不等于整源 checked_no_changes。下一次登记计划为 10-14 19:03:01，仅是计划；本包没有重新读取 OS 任务，登记 readback 时间仍为历史 10-13 19:14。

NCSS 华工电气有限查询出现 next_cursor=null、pending_details=0、detail_failures=0，仍全部 partial。补读已保存的真实公开 JSON 后发现首页 10 条、第二页 4 条，但二者 pagenation 均声明 count=100、total=10、limit=10，offset 分别为 1/2；4 条不是已证实终点。ncss_discover 仅按记录长度决定续页，忽略官方分页元数据，而且从未输出 complete_for_channel。discovery 只有完整性声明、无待补和无失败同时成立时才记 source success。原有结果不能手改为成功。该窄缺陷由 #52 登记，不重开旧 #33/#34/#35，不修改 common 来使所有来源自动成功。

M3-04 的文字要求没有把该无变化样例限定为自然触发；真实手工完整有限范围检查可以补该状态材料，必须明确 trigger=manual，并与已有自然调度证据分开。建议由正式来源代码严格校验 NCSS 的固定目录、JSON、count/total/limit/offset、全部条目与真实末页，再沿官方同查询页链完成两轮真实统一 refresh；仅在第二轮明确有限范围全部完成、无 pending/失败/受限、业务 new/modified 均 0 且 dataset 不变时给出材料。仍保留 school_wide=false，不能称整个学校或全部 15 源无变化。不得运行期篡改 flag、改库/时钟、fixture 或用“没有新增”替代范围完整。

当前采样时 M3-04 缺口仍在，#15 不标 Done；后续真正取得的材料由 #52/#17 的独立证据覆盖，报告不把未来计划写成已完成。自然运营跨两个日期、持续不足一自然日，七自然日建议观察仍未达。

## 16:50 后续只读诊断：第 6 页为官方登录限制

整合者已在独立真实候选接入 #52 修复并执行一次手工 selected-source refresh。本包随后只读查看该 run 及已归档材料，没有发送外站 HTTP、改库或扩展来源政策。

- run：run-617d53a5-b607-447e-b719-7d727115a0f3，manual，2026-10-14 16:46:21—16:46:26。page_budget=10 / detail_budget=100，fixture=false。
- 业务结果：run status=partial / completeness=partial；source status=failed，已提交 5 页，details=0；new=0 / modified=0 / unchanged=14，续页游标保留 offset=6。单轮无业务变化不等于完整范围无变化。
- 第 1/2 页分别为 10/4 条，第 3—5 页均为空列表；它们的公开 pagenation 都仍声明 count=100、total=10、limit=10 和相应页码。不能将短页或这三页空列表当作已证实全范围终点。
- 第 6 页取得可校验 hash 的 97 字节 JSON：flag=false、data=null、errors=[]，global 的公开说明为“请登录后查看”。该失败由 _ncss_json 在 flag 检验处产生，分类为通用 failed；准确访问原因是官方登录限制。不是游标 cap、public_paths、预算耗尽，也不代表没有招聘。
- 16:50:29 候选库数量为 781 机会 / 593 材料 / 3790 变更 / 8 run，real/schema3，dataset ds-d8962f88-037e-44d9-b38e-ac685b43f1d4；这是新的候选身份，不代替前节旧运行 Site v5 身份。该 NCSS 轮次未产生新/改业务事实，没有将 100 的分页元数据当作学校招聘总数或近期覆盖分母。

#52 的公开分页代码已提交，141 项局部回归、可信完整差分及 [PR #56 完整 CI](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38537284662) 成功；实现结果为 Awaiting verification。M3-04 的真实完整无变化材料仍 Blocked，不能因此把 #15 标 Done。

最小后续是停止该 NCSS 受限深页路径并准确登记原因，不执行第二轮或通过自然调度重试已知登录限制，不使用登录 Cookie/代理绕过。root 随后明确授权在同 #52 已登记的两文件范围内补源内“明确登录 JSON → restricted”分类，追加提交 ca3327dff4ae8566eadd31cfeca3eb09ee389262 已推送至草稿 PR #56。分类仅匹配 flag=false 与 global[].des 精确“请登录后查看”，普通失败仍 failed；146项相关回归/neat复测和可信完整差分通过；最新 [完整CI run 38538552467](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38538552467) 已逐步回读 success，包含完整pytest、Node测试、构建、产物语法、可信差分与运行材料检查。没有修改 common 或扩大共享服务器政策，没有重新HTTP，也没有将真实历史 source.failed 手改为 restricted。分类修复不能将本轮 partial 改为完整无变化。其他独立来源和 #17 准备继续，完整公开来源材料尚未取得时如实交付 M3-04 缺口。原始响应仍仅留私有运行材料，公开报告只保留上述状态和最少数字。

## #17、验证边界与 neat-freak 收束

本包只读 SQL 使用 mode=ro 并在一致读事务中取得 metadata/runs/数量，API 请求复用既有 service token 的内存 Authorization，不输出秘密；Sites 调用只读版本、访问和部署。git fetch 只取得身份信息，失败结果照录。本包未执行外站采集、构建、全量测试、备份或恢复，故不替代实施包测试与整合者本轮 741 条当前快照恢复回执，更不复用历史 292 条恢复证明。

| 知识面 | 收束状态 |
| --- | --- |
| 源码映射/实际合同/规则 | verified-current |
| 本报告与去敏证据 | changed-and-verified |
| 当前部署浏览器链与新版身份 | pending，交 #17 整合；未替用户核验 |
| 记忆 | not-applicable，未写入 |
| 全工作区/清场 | out-of-scope，无删移停服 |

证据：[RUNTIME-REPAIR-AUDIT-20261014.json](evidence/RUNTIME-REPAIR-AUDIT-20261014.json)。本包仅上述两个文件新增；私有库、原材料、日志、token 与内部路径未进入公开材料。复核现场保留，正式站未切换。
