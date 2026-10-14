# SCUT-COMPLETION：NCSS 公开分页与有限范围终点修复（2026-10-14）

Work-Packages: SCUT-COMPLETION
Work-Issues: #52
Refs #15、#17、#31、#12。

- owner：runtime_audit 来源实施者；共享业务/配置/部署仍由 root 整合。
- 分支：codex/scut-completion-20261014。
- base / 实际 PR 目标：2ba101ba68abda9c83ce94f487043141e62dd651，独立治理已由 root 复核。
- 允许产品路径：backend/sources/scut.py、tests/test_scut_sources.py。允许管理路径：本文件及包内去敏证据。
- 接口影响：保留 SourcePage 的既有结构，仅在 NCSS 固定学校来源、固定电气查询、已核实官方 count/total/limit/offset 和可证明分页终点时由 partial 输出 complete_for_channel；不表示 school-wide，不修改 shared common、API、写服务、数据库或其他来源。
- 验收编号：M3-04；回归 M1-01/M1-03/M1-08 与 A05/A08/A11。
- 前置：先用真实目录/JSON/最终URL/全部条目归属和有效性确认终点；没有安全有效的完整范围时继续 partial/失败，不能将未知填零。

拟验证：按官方元数据续页；短中间页/空中间页继续公开同查询页链；仅可信末页/明确零总数空页→有限栏目终点；混校、非法/重复行、异常页长、损坏JSON、错误来源目录/重定向均不能完整；统一 refresh 在真实服务/隔离 fixture 中验证完整轮次、详情失败仍 partial、重复不新增/不换 dataset。Fixture 只证回归；真实两轮检查与用户 M3-04 复验由整合者另交材料。

开工登记完成。实现、自验、neat-freak、可信完整差分、提交/PR 与真实采集结果在完成后更新；此段不预填通过。正式站未切换。

## 实现与自验结果

只改登记的 NCSS discover：读取公开 pagenation，验证整数型 count/total/limit/offset、固定每页10、同请求页码和范围、声明末页的实际条数；官方仍声明后页时不因短页/空页提前停止。目录身份冲突、条目无效/重复/混校、分页元数据损坏或末页条数矛盾不能输出完整范围。缺元数据的旧有限发现保留 partial，不把 fixture 补成实网成功。可信 JSON 空页与未识别 HTML/错误 JSON 分开。统一 refresh、writer、API 和 common 文件未改。

采样中真实两页10/4条都声明total10，已交 root 继续逐页诊断。不会称当前两页完成整源，也未执行外站/改运行库。真实完整无变化、新版 Site 和用户 M3-04 复验仍由 #17 交付；本包代码自验后为 Awaiting verification，#52保持open。

最小/相关回归（2026-10-14）：

~~~text
python -m pytest -q tests/test_scut_sources.py tests/test_sources.py tests/test_discovery.py tests/test_updates.py tests/test_source_policy.py tests/test_material_applicability.py
~~~

首轮140项通过；neat-freak在两文件局部做新增块换行整理，并补混校末页仍保留旧可靠事实的生产refresh反例，复测141项全部通过、退出0。统一真实服务+fixture验证11条两页全范围完成、重复新/改0且dataset不变；详情失败仍partial；坏末页不清旧值。Fixture不作官网覆盖或自然调度证明。git diff --check退出0。完整CI/构建由最终整合者执行并读取本PR CI，结果另记，不将此处141项冒称全量。

neat-freak事实面：代码/规则 verified-current；本包资料 changed-and-verified；真实新运行与用户复验 pending；记忆 not-applicable；全工作区 out-of-scope。无全仓格式化、无删移清场、无授权外写入。

提交与PR由本轮独立分支创建后记录；可信checker必须来自实际目标2ba101b，检查完整PR差分，不修改本分支规则。

## 第6页明确登录限制的分类修正（同 #52）

实施前登记：仍只允许 backend/sources/scut.py、tests/test_scut_sources.py 与本包管理说明；SourcePage/enrich 接口和共享行为不变。新增范围仅为 NCSS 的结构化公开响应 flag=false 且 global[].des 精确为“请登录后查看”时抛出 restricted FetchError，使既有 skip_restricted 能停止该路径；其他失败仍为 failed。不改 common、policy、server、API、writer 或数据库，不加入登录/Cookie绕行。

真实材料由 root 16:46 的一次手工检查取得：第1/2页10/4条，第3—5页空，但metadata仍total10；第6页97字节JSON flag=false、data=null、global说明“请登录后查看”。run真实status/completeness=partial，source历史记录failed，pages5/new0/modified0/unchanged14。该响应只证明明确访问限制，不能证明新采或完整无变化；本包不重发HTTP、不改旧run/库/时钟。root已停止该深页及第二轮；新API候选不绑定其调度，旧两页任务不访问第6页。

#52 源码实现自验后 Awaiting verification，#15/M3-04完整无变化材料Blocked。后续合成JSON用例明确标fixture，验证普通flagfalse失败不误判restricted、精确登录响应restricted、成功/近似文案不误判，以及现有统一refresh持久记录restricted/下一轮skip且保留旧事实。

分类修正自验：同前述六文件回归共146项全部通过；neat-freak仅整理新parametrize块换行，保行为复测与git diff --check再验证。本包不进行第二轮真实HTTP；原run历史failed保持不动，真实M3-04仍Blocked。
