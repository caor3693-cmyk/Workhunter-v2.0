# 2026-10-14 独立文档同步

工作包 `DOC-20261014`；Refs #47、Refs #42、Refs #43、Refs #49、Refs #52、Refs #17、Refs #15、Refs #48。分支 `codex/doc-20261014-repair`，实际 base 为已独立复核的治理提交 `2ba101ba68abda9c83ce94f487043141e62dd651`。origin 为 `https://github.com/caor3693-cmyk/Workhunter-v2.0.git`。独立 worktree 与 root 的产品整合文件隔离，保留 root 未提交工作。

允许/实际修改仅 `docs/PRODUCT.md` §5、`docs/TASKS.md`、`docs/CONTRACTS.md` 和本管理交付文件；不修改规则、产品代码、数据库、运行材料或部署。机器声明 `Work-Packages: DOC-20261014`，`Work-Issues: 47,42,43,49,17,15,48`；#52 在正文关联，未修改受信 Issue 映射。

本包只把用户 #42 已明确要求的首页摘要撤去及本轮受审工作包写入现役规范。业务接口/字段、固定十校、近30天与未来30天窗口、八项选择 ABAAAAAB 保持；F07 摘要继续在来源/维护入口提供，公共摘要 API 保留。验收对应 M2-08、M1-06 与本轮包的 M1-05、M1-01/M2-01、M3-04、M4 原编号；本包不代签人工通过。

自验：逐文件完整diff查看；本轮七包全部精确路径/分支前缀与可信2ba治理表一致；15处相对文档链接存在；相关scope/project/schools JSON解析通过，固定十校仍为10；PRODUCT §5之外的字节归一比较一致，公开GET路由集合不变，规则表未改；`git diff --check`通过。提交后继续使用实际base导出的checker检查完整四文件DOC差分；源码无改动，不新增镜像实现的测试或重复占用整合全量测试。

按现有 neat-freak 3.0.0 做本包知识同步：旧CORE/M1-UI当前执行文字改为历史归属，本轮精确范围成为任务入口；首页摘要相关Product/Contract/Task矛盾消除；再次检查diff、链接与JSON。代码/规则verified-current（未改），文档changed-and-verified，产品运行态pending由W06交付，Project原生pending由#50，记忆not-applicable；工作树保留复核现场，没有全仓格式化或删除用户文件。

首页 PR #53 的实际 head 为 `ddb5f7ee4d591f0ec8371b54d372268ba50de886`，实际 base 为 `2ba101ba68abda9c83ce94f487043141e62dd651`，状态 draft/open；正式 [CI run 38535263008](https://github.com/caor3693-cmyk/Workhunter-v2.0/actions/runs/38535263008) 已回读 success，真实目标范围、完整 Python/Node、构建、worker语法和运行材料检查各步骤均 success。该结果证明工程自验，不表示已发布 Site 或用户 M2-08/M1-06 通过。

独立 DOC 提交经 root 复核后可作为后续功能整合 PR 的实际目标；root 串行合入此分支后，以该 DOC SHA 与整合 head 的 merge-base 检查完整差分，文档已属于共同基线，不通过扩大 W06 权限夹带 PRODUCT 修改。当前自验完成后进入 Awaiting verification/open，不合并 main、不切正式站、不自动关闭反馈。
