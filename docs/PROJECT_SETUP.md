# GitHub Projects 接续配置

<!-- current-project-sync-20261014 -->
## 本轮同步事实：2026-10-14

原生Project5/Board/Roadmap历史已创建。本轮无可用Projects/GraphQL连接器或gh授权通道，浏览器清单为空；原生字段未写。GitHub Issue及仓库Board/Roadmap已更新并回读。

config/project.json保留10-12原生快照和26待同步编号，#42—45为新条目。恢复既有授权后确认可写性，再新增/更新字段与回读；Future不造Stage选项/首版日期。不读取或输出凭据、不改变权限/登录或其它项目。下文为历史创建资料，不表示本轮原生同步已完成。
<!-- /current-project-sync-20261014 -->


管理命名/反馈同步日期：2026-10-11；授权通道本轮实际核验为2026-10-11。本文件规定项目管理配置的接续方法；下方示例用于后续维护，本轮实际写入与回读见当前状态。

## 当前状态与边界

**2026-10-11当前已完成。** 现有授权gh/GraphQL通道实际可用，viewer为caor3693-cmyk，创建前完整回读4个现有项目且没有v2同名项目。建立独立私有[Workhunter v2.0｜一周重建 Project5](https://github.com/users/caor3693-cmyk/projects/5)，仅关联caor3693-cmyk/Workhunter-v2.0，没有改旧Workhunter/Creator项目。

实际Project ID `PVT_kwHOD1jk9s4BmirN`；[Board](https://github.com/users/caor3693-cmyk/projects/5/views/1)为`PVTV_lAHOD1jk9s4BmirNzgMAiVw`/BOARD_LAYOUT；[Roadmap](https://github.com/users/caor3693-cmyk/projects/5/views/2)为`PVTV_lAHOD1jk9s4BmirNzgMAiek`/ROADMAP_LAYOUT。Status六选项、Stage/Priority、Start date/Target date和26项字段逐一核对；Board按Status分列并显示阶段/优先级，Roadmap通过实际UI保存Stage分组及起止日期。#19技术配置已完成/closed，完整ID映射在[config](../config/project.json)，证据在[本轮回执](deliveries/evidence/M0-M1-FEEDBACK2-20261011.json)。

旧“通道受阻/ID为null”是10-10—10-11此前现场，历史见git与原报告，现已被实际成功回读替代。未登录或扩权，没有用户提供新令牌；仓库和项目私密策略保持。M0七项通过、M1三项失败和新#29/#30/#31未解决分别登记，管理配置完成不表示M1通过或正式上线。

本轮 M1-M2 执行补入 #32—35，现有30项保留；新增四项的 Status、Stage、Priority、Start date、Target date 已逐项回读。2026-10-12实际回读：#29/#30为M1/In progress，#33—35为M2/In progress，#32为M2/Awaiting verification；#12/#13/#14/#31为In progress，#3为Blocked。原目标日期和历史结果保留，真实item ID在config。GOV PR36及DOC PR37进入隔离可信目标6cb4723；工程候选不代表Site交付或用户Gate完成。

下面为后续幂等维护参考，不再新建第二个同名项目；使用已登记ID，先读后写并回读。

## 授权前提

- 仅接续已有且经授权的 Projects API/CLI 通道；先只读确认当前账号、授权范围与目标资源。不得自动扩权，不要求用户把令牌粘贴到聊天。
- 官方指南要求读取使用 `read:project`、修改使用 `project` scope；同时必须拥有目标 Project 的实际写入权限。仓库 push 权限不能替代 Project 权限。新建个人项目时核对当前账号就是目标 owner；复用项目时核对 `viewerCanUpdate`。见[API 权限指南](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)及[项目访问权限](https://docs.github.com/en/issues/planning-and-tracking-with-projects/managing-your-project/managing-access-to-your-projects)。
- 官方文档仍将“访问用户账号拥有的 Projects”列为 fine-grained PAT 的限制；不要假定仓库细粒度授权已覆盖此目标。已授权的 CLI OAuth 或其他受支持通道须实际核对。见[PAT 限制](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations)。
- 若采用 GitHub App，另核对 Projects 权限及仓库关联所需权限；官方指出 `createProjectV2` 使用 `repositoryId` 时还需要仓库 Contents 权限。权限不足只登记阻塞，不擅自改账号、权限或仓库可见性。

## 已核实的视图 API

端点为 `POST https://api.github.com/graphql`，JSON 请求体由 `query` 与 `variables` 组成。身份验证使用既有通道，不在文件中写入凭据。

| Mutation | 必填 input | 本任务使用方式 |
| --- | --- | --- |
| `createProjectV2View` | `projectId: ID!`、`name: String!`、`layout: ProjectV2ViewLayout!` | 缺失视图才创建 |
| `updateProjectV2View` | `viewId: ID!` | 可更新 `name`、`layout`、`filter`、`configuration` |
| `deleteProjectV2View` | `viewId: ID!` | 仅核实能力；正常接续不删除既有视图 |

布局枚举包含 `BOARD_LAYOUT`、`ROADMAP_LAYOUT` 和 `TABLE_LAYOUT`。当前公开的 `ProjectV2ViewConfigurationInput` 仅列 `visibleFieldIds: [ID!]`；不可凭空添加分组、排序或时间轴字段绑定参数。见[输入与枚举定义](https://docs.github.com/en/graphql/reference/projects#createprojectv2viewinput)。

最小创建请求的 `query`：

```graphql
mutation CreateView($projectId: ID!, $name: String!, $layout: ProjectV2ViewLayout!) {
  createProjectV2View(input: {
    projectId: $projectId,
    name: $name,
    layout: $layout
  }) {
    projectV2View { id number name layout }
  }
}
```

Board 的 `variables`：

```json
{"projectId":"<已读回的 Project node ID>","name":"Board","layout":"BOARD_LAYOUT"}
```

Roadmap 使用同一请求，变量改为 `name: "Roadmap"`、`layout: "ROADMAP_LAYOUT"`。传入 GraphQL node ID，不用项目数字编号或仓库 ID 代替。

`gh project` 当前未列专用的创建视图命令；`gh project view` 用于查看项目。已有授权且 CLI 可用时，可将完整 JSON 请求体交给 `gh api graphql --input request.json`，不需要虚构 `gh project view-create`。见[gh project](https://cli.github.com/manual/gh_project)与[gh api](https://cli.github.com/manual/gh_api)。

## 接续顺序

1. 读取配置与真实 Issue 索引，确认目标仓库及当前配置的30项期望集合；`PM-SETUP` 使用配置中的实际 Issue，不再次创建同名 Issue。
2. 完成上述只读权限检查。对目标 owner 的项目分页读取，按完整标题精确匹配，并核对 owner、关联仓库、记录的 ID/URL；不要只依赖模糊搜索或第一页结果。
3. 已有唯一匹配且可写的项目就复用；多个同名结果先登记歧义，不能猜选或新建重复项目。确认不存在后才调用 `createProjectV2`，使用已核对的 owner ID 和标题；随后关联本仓库并读回实际 ID/URL。
4. 分页读取现有字段，按名称和类型复用 `Status`、`Stage`、`Priority`、`Start date`、`Target date`。前三者按配置使用单选选项，后两者使用日期；仅创建缺失字段。选项和字段 ID 必须读回，不能用名称代替 ID 写值。
5. 逐一核对目标 Issue 的仓库、编号和 node ID；读取现有项目项，仅用 `addProjectV2ItemById` 补齐缺失关联。关联已有 Issue，不生成替代 draft，也不删除项目中无关的既有内容。
6. 依据配置及 ROADMAP 写入每项的阶段、优先级、状态和日期；使用 `updateProjectV2ItemFieldValue`。计划日期不代表实际完成，人工 Gate 未通过不得写为 Done。不要覆盖用户已更新的进度，遇到差异先核对 Issue 的最新证据。
7. 分页读取视图，按名称和已记录 ID 复用 Board/Roadmap；仅补缺或修正本任务的布局。保存真实 view ID、number 与布局；不要批量删除默认或其他视图。
8. 完成下节验证后更新配置与 STATUS；只将已经实际配置并核实的能力写为完成。权限、视图细节或读回失败分别登记在 `PM-SETUP`。

## 原生视图细节与完成判据

期望 Board 按 `Status` 分列；Roadmap 使用 `Start date` 与 `Target date` 显示日期区间，并按 `Stage` 组织。当前核实的视图输入未公开这些分组/日期绑定字段；若届时 schema 仍无对应输入，须在已有授权的 GitHub 平台 UI 配置并保存，不能用未经文档支持的参数试写。

GitHub 会尝试选用已有日期/迭代字段，因此创建 `ROADMAP_LAYOUT` 成功不能单独证明时间轴绑定正确。须检查 Date fields 中的起止字段，见[官方 Roadmap 配置说明](https://docs.github.com/en/issues/planning-and-tracking-with-projects/customizing-views-in-your-project/customizing-the-roadmap-layout)。UI 通道仍不可用时记录“布局已创建，分组/日期绑定待验证”，不重复请求本轮已经拒绝的登录。

- 读回 Project 的 owner、标题、URL、仓库关联及可写状态，与配置一致。
- 分页核对当前配置30个Issue都有真实项目项且无重复；复用项目有其他项时分别记录，不以总数等于30强制清理。
- 逐项读回五个目标字段的实际值；状态符合当前证据，排期对应 ROADMAP，计划起始日期不晚于目标日期。
- 读回 Board/Roadmap 的名称、ID、number、layout；视图筛选没有意外隐藏目标任务。分组、日期绑定和条目显示由平台 UI 核实并记录结果。
- 从原生 Project 打开抽查 Issue，确认落到本仓库的真实条目；记录检查日期和 Project/视图入口，不推测 URL。
- 再次运行接续检查只报告差异，不重复新建项目、字段、视图或 Issue；只有全部目标核实后才完成 `PM-SETUP`。

若目前仍无可用授权通道，保留 ID/URL 为 `null`、管理阻塞 Issue 为 open，并继续可独立推进的开发与文档工作。完成项目管理配置不等于完成任何 Site Gate，也不构成正式部署的验收记录。


## 当前导入状态更新

2026-10-12实际回读：30个本仓库Issue，21open/9closed；Backlog 5, Ready 0, In progress 9, Awaiting verification 1, Blocked 6, Done 9。本轮仅同步实施进展与阻塞，保留原字段、视图、用户Done、Gate开闭和日期。#19历史技术完成保留；#29/#30是M1，#32—35是M2。最新事实见[STATUS](STATUS.md)和config，历史26项导入记录仍可追溯。
