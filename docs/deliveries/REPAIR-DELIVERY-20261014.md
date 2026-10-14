# 2026-10-14 修复交付

Refs #17 #42 #43 #47 #48 #49 #52 #15 #31 #12 #50。产品决定 ABAAAAAB、固定十校与已通过历史任务保持。原干净分支 codex/w05-b-feedback-20261014 / 9ce46ceb926657a59616ac1741e498fd2e86820d 保留，无 reset/强制覆盖、旧业务PR合并或正式站切换。

## 本轮实际结果

| Issue | 结果/根因 | 实际路径与状态 |
| --- | --- | --- |
| #47 | 独立治理 #54 与独立DOC #57，经root复核成为真实目标；checker未改 | scopes/test_scope；PRODUCT §5、CONTRACTS、TASKS；Awaiting verification/open |
| #48 | 9665e245是独立Sites源仓提交，非GitHub提交；宿主f8c3a1d未推送；76文件实体映射见只读审计 | 去敏审计/身份材料；旧API声明不能代替宿主HEAD；新版actual Site checkout/API b75d2d0，v6保存未部署 |
| #43 | 已核对运行组件/代理与审查源；管理员浏览器策略阻止用户宿主复现，根因未证实 | 原文源码未改；三校29/304/743×列表/详情×点击/Enter×宿主/常规浏览器矩阵未测，Blocked/open |
| #42 | 同步解除DOM、import、reader、render、reload、sidecar、首页路由 | index.html/home.js/routes.js/frontend_pages测试；PR #53，Awaiting verification/open |
| #49 | 接入已核实的广州公开宣讲/招聘会栏目与同栏目分页，列表事实先落库 | gzhu.py/config/schools.json/test_gzhu_sources；PR #55，真实新增40、详情40成功；Awaiting verification/open |
| #31/#12 | 固定十校逐校诊断已交；只广州本轮增加，新旧日期/相关性口径相同 | 来源报告/统计；其他渠道仍有限或受限，母单保持In progress/open |
| #52 | NCSS忽略元数据、短页数量矛盾与跨轮tail可误认证；逐页数量守卫，offset>1保持partial；明确登录响应分类为restricted | scut.py/test_scut_sources；PR #56，源码修复待验；不改common/policy/API/writer/schema |
| #15 | 旧账本4次scheduled+1次manual均partial保留；候选新增3次manual，其中1次准备中断；本轮NCSS第6页返回请登录后查看，停止 | 前5页14次无变化提交不证明完整范围；M3-04仍Blocked，七自然日未达 |
| #17 | 0.5.1/M3修复候选、当前781快照重新隔离恢复、顺序清单已准备 | review.html/js/version.py/acceptance测试、本文与证据；新私有v6已保存、实际环回API已对账；外部通道自动审批拒绝，授权pending，Blocked/open |
| #50 | 原生GraphQL HTTP200/INSUFFICIENT_SCOPES，缺read:project | 原生字段/选项/条目不可读，零写入；31项精确pending，旧item ID保留，Blocked/open |

## 源码、测试与实际证据

可信治理：2ba101ba68abda9c83ce94f487043141e62dd651（PR #54）。独立DOC实际整合目标：4ea9168c89fabe0902387cb74fdacda6e4ce2203（PR #57）；目标checker/范围与治理相同字节。包声明 REPAIR-20261014-WITH-COMPLETION = LINKS,HOME-SUMMARY,GZHU-20261014,W06,SCUT-COMPLETION；Issue43/42/49/17/52。各包先登记基线/精确路径/接口/原编号再实施，共享文件由root串行整合。没有新增API、岗位实体、数据库迁移、学生账号或全局样式。

独立提交：HOME ddb5f7ee4d591f0ec8371b54d372268ba50de886；GZHU 259419ba1781600d98f21d5b7298e1a0b92aa82f + 文档12aba6c5db467f702b7a63a34396b110d2fef747；SCUT bc5a5e3e5d380d3cadec9050f65c5fe757812532 → ca3327dff4ae8566eadd31cfeca3eb09ee389262 → d7a66a40ad5addcd32e7661951f8dae9c1b685dd → 7684212e6b36a84fd698bdcd6837978df16131e5 → 最终5a23294d8dc516c8ff4222fee7e939567cac71c2。独立CI #53/#54/#55/#56/#57分别回读，完整差分使用实际目标导出的checker，不用候选规则自授权。

最终本机完整Python回归827 passed / 1 skipped（Windows宿主、全新专用临时目录，包含启动器）；完整Node123 passed；来源最终151项与neat后58项复测通过，独立服务11个合成反例通过。保留Starlette/httpx弃用与旧pytest缓存ACL warning，不借此修改依赖或用户缓存。最终源码以实际DOC目标4ea导出的可信checker验证完整25路径，checker/scopes未改。Site clean构建、worker语法与归档结构通过；官方bash打包器在Windows不可用，使用同一官方prepare-site-build.cjs与Windows tar生成检查过的暂存归档。最终源包[CI38544643436](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38544643436)完整通过；整合CI由[PR58当前head checks](https://github.com/caor3693-cmyk/Workhunter-v2.0/pull/58/checks)原生回读，完成时的run/提交见PR正文与交付回执，不拼加不同测试批次。

真实广州 run-f2a1c69f-f0c2-4174-a347-a5496d517c60，manual/fixture=false，4页/40详情、0详情失败/受限，40新身份与40后续解析补全，仍partial且两个栏目下页均3。不把详情补全叫40个额外招聘或官方业务修改；数据库独立学校/来源身份唯一。旧gzhu_jobs首页限制和3条原公告保留，不换source key重复灌简章。

真实NCSS run-617d53a5-b607-447e-b719-7d727115a0f3，manual/fixture=false，5页、14 unchanged、0新增/修改；第6页97字节JSON flag=false且明确要求登录，已停止。第3—5页空但元数据仍指10页，不作verified terminal；未跑第二轮、未绕限制、未手改历史run或时钟。后续分类回归使用合成JSON，只证明代码，不冒充新HTTP。

## 固定口径逐校前后表

冻结前为2026-10-14 16:10的741快照；后为本轮781快照。使用同一服务API的 as_of=2026-10-14 / recent_days=30：官方发布2026-09-15—10-14 ∪ 活动2026-10-14—11-13，scope=electrical（related+unknown）。全库数不等于近期或完整覆盖；全部school_wide=false。

| 学校 | 全库前→后 | 近期电气前→后 | 明确相关前→后 | 未知前→后 | 去重新增 | 未完成/受限原因 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 华南理工 | 101→101 | 12→12 | 6→6 | 6→6 | 0 | NCSS 第六页要求登录已停止；学院补充非全校 |
| 广东工业 | 251→251 | 196→196 | 50→50 | 146→146 | 0 | 公开三栏目有限分页，保留防回归 |
| 华北电力 | 0→0 | 0→0 | 0→0 | 0→0 | 0 | 北京既有限制0请求；保定连接失败 |
| 上海电力 | 100→100 | 66→66 | 16→16 | 50→50 | 0 | 公开简章仍有续页，尚非完整学校范围 |
| 东北电力 | 6→6 | 6→6 | 2→2 | 4→4 | 0 | 首页6条；栏目SSR无列表，不能把200当覆盖 |
| 长沙理工 | 14→14 | 10→10 | 7→7 | 3→3 | 0 | 首页有限；新栏目未获统一来源准入，0请求 |
| 三峡大学 | 240→240 | 146→146 | 46→46 | 100→100 | 0 | 两公开栏目仍有续页，部分详情待补 |
| 广州大学 | 3→43 | 3→24 | 0→7 | 3→17 | 40 | 宣讲/招聘会各2页20详情；旧首页受限保留，页3待续 |
| 湖南大学 | 26→26 | 19→19 | 7→7 | 12→12 | 0 | 本轮入口连接失败；旧可靠数据保留 |
| 中南大学 | 0→0 | 0→0 | 0→0 | 0→0 | 0 | 此前403路径停止，0请求 |

合计全库741→781，近期458→479，related134→141，unknown324→338；去重新增40，仅广州新增。

## 当前快照恢复与运行边界

先对741真实新库做一致SQLite backup/新路径restore，再对完成本轮收录的781当前快照重新做一次。后者采样16:49:53，北京时间；real/schema3/dataset ds-d8962f88-037e-44d9-b38e-ac685b43f1d4，781机会/593材料/3790变更/8run、3905材料适用关系、583写回执。SHA 3ffba39c038ca030260ba30c6f8c13f9dc6bc03f4c15ffbf3fd3c405b2c9bf7d；备份与恢复SHA、全部表计数、完整性和外键一致。没有覆盖旧库，数据库之外的原材料保持只读档案，backup scope=database_only。恢复副本不会自动启用旧路径调度，现有原宿主/任务保留，新版冻结API与新路径自然计划状态分别记录。

最终代码冻结：GitHub 55553fca7fd05a4973950c0305223d21186cc8bb ↔ 独立Site源 b75d2d0b2fd786084f10ec9ff2383b1c9116daf6，全部230 tracked实体按text LF规范化/binary精确相同。后续PR58知识回执提交只改本包报告/状态；文档提交与运行源码分别记录，不能把PR最新docs SHA当已部署版本。

新owner-private Site v6已保存并native逐项回读，version_id=appgprj_6aca4fbe4c1481918047d279e9653ccc~appgver_7c09d6966644819187cd3ac03263fdd3，source=b75d2d0，archive tar/2文件/184320 bytes/provider SHA9a3380a74db70c82c0e6d3765ac8e613402f7425ac57a5a7283153d14ba7f50d。native归档digest与Windows本机tar摘要不等，未取回native归档或部署字节，不声称字节回读通过；本机worker SHA a194db4e284dd3724159af73b27dbdf5103a69dfa59dbee657995af3667f6696，内嵌frontend=b75d2d0。deployment_id=null、新env_revision=null，v6未部署。当前[私有入口](https://workhunter-v2-review.sage-candy-7999.chatgpt.site/)仍是旧v5（旧deployment/env4），不能用于新版本复验。

新API实际加载本机干净Site源checkout b75d2d0，127.0.0.1:8897，health/version授权200、匿名401；0.5.1/M3/schema3/real/dataset ds-d8962f88-037e-44d9-b38e-ac685b43f1d4。7个真实API路由与实际stdio MCP 7工具同身份，781/593/3790/8/796计数与恢复库一致，读前后SHA保持3ffba…bf7d。maintenance29机会/32材料另备份恢复为isolated_fixture，不计覆盖。新路径调度unregistered/not_ready、next_run_at=null；旧4自然/1手工账本和原任务保留。当前候选8 run=4 scheduled+4 manual；新增的3次手工中，首次因Fetcher参数不匹配在采集准备阶段interrupted，记录保留，随后正式广州与NCSS两次均partial。未把准备中断抹去或列为自然成功。当前scut_ncss.failed来自旧实网run：新登录分类只做代码回归，没有手改历史状态。

新Cloudflare验收HTTPS通道启动被automatic approval拒绝（第三方敏感出站未有明确授权），用户授权pending，未启动隧道、未修改Site环境、未部署v6；#17对应远程交付保持Blocked，其余独立工作完成。Site同源代理端到端与浏览器导航未测，不拿环回对账替代远程验收。

## 按原编号顺序人工核验

下列清单待v6接通真实API并部署后执行；当前旧v5不能代替本轮验收。用户结果保持原编号，构建者不代签；旧通过任务保留，只复验受影响项。

| 顺序 | 编号 | 入口/操作 | 预期与当前局限 |
| --- | --- | --- | --- |
| 1 | M1-01 | 首页华工、广工近期；华工29电气工程师、广工304亨通集团详情/原文 | 学校/原标题/本公告电气证据正确；不要求先完成九校扩源 |
| 2 | M1-05 | 三校29/304/743，逐校列表与详情，鼠标和Enter；用户宿主与常规浏览器对照 | 可见正确官方导航；当前构建者浏览器被策略阻止，源码根因未证实，本项仍Block/待验 |
| 3 | M1-06及03/08 | 搜索、清空、翻页、编辑未提交草稿、快速切校；40为历史详情反例：会场大学城校区教2-220/工作地广东省珠海市香洲区，743相关/762未知 | 最新查询胜出、旧响应不覆盖；相关性未知保留；首页不等待摘要 |
| 4（M1后） | M2-01/02/03 | 十校逐一选；广大743/753宣讲和762招聘会，华电/中南状态 | 40真新增可追踪，受限不叫零招聘或全覆盖；校区不猜 |
| 5 | M2-08 | 首页首载/重载/筛选/分页，来源状态，业务维护摘要 | 首页没有最近更新和专用请求；其他摘要/权限保持，分类不相加 |
| 6（M2后） | M3-04 | 本轮NCSS登录限制与广州partial材料；对照完整范围无变化所需证据 | 5页14次无变化不等于完整无变化；本轮仍缺成功真实材料，保持Blocked |
| 7 | M3-05/06 | 当前781恢复后的新API/核验页与七个只读工具回执 | dataset/schema/计数与真实恢复相同，读取不写库；不复用旧292恢复，个人客户端状态另列 |
| 8（前门有效后） | M4-01—08 | 顺序复验反馈→十校→搜索/卡片/详情/原文→手机→维护预览/保存/撤回→摘要/调度→范围→发布/回退材料 | 按MANUAL_QA原步骤；本轮#43/#15仍阻塞，M4未代签，#18正式发布未执行 |

## neat-freak与未完成事项

现有neat-freak 3.0.0已用于每包保行为清理与复测；移除首页测试失效摘要分支，校正公开样本ID和已通过M1-06旧状态，PRODUCT/CONTRACTS/TASKS独立对齐。代码/规则/文档changed-and-verified；运行身份与恢复verified-current；远程Site浏览器/完整无变化/用户Gate pending；原生Project pending/Blocked；记忆not-applicable；正式站及旧资产归档out-of-scope。未删用户文件、worktree、库或原文，不全仓格式化，复核现场保留。

仍需：#17外部验收HTTPS授权、v6部署与代理真实可达性；#43管理员策略允许的用户宿主导航证据与基于证据的修复；#15获准完整范围真实无变化；其他学校合法渠道/续页/待补（逐校表）；新版自然计划与真实触发证明；用户M1→M2→M3→M4原编号确认。原生Project缺read:project权限、31pending，不要求在聊天/Issue粘贴令牌。七自然日未达。正式部署/域名切换/旧库删除/仓库可见性变更均未执行。

按原约定在本次实际软件交付提起 #44 招聘日程表与 #45 AI改简历：保留未来讨论，本轮未开发、未新增提醒。
