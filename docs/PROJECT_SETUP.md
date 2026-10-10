# GitHub Projects 接续配置

核验日期：2026-10-10。本文件规定项目管理配置的接续方法；本轮已复查可用通道，以下 Project 写入示例尚未执行。

## 当前状态与边界

**原生 GitHub Project、Board 和 Roadmap 仍无已创建并回读核验的入口。** 当前连接器可维护仓库与 Issues，但未提供可调用的 Projects 接口。本机 `gh` CLI 已找到，现有认证失效；只读授权检查没有形成有效的 Projects 通道。本轮不重复发起已拒绝的登录，不创建或写入未获授权的原生项目。

这属于当前会话的授权通道阻塞。GitHub 官方 GraphQL 已支持 `createProjectV2View`、`updateProjectV2View`、`deleteProjectV2View`，不能记录成“GitHub API 不支持视图”。见[官方 Projects schema](https://docs.github.com/en/graphql/reference/projects#createprojectv2view)。

目标配置以 [config/project.json](../config/project.json) 为准：owner 为 `caor3693-cmyk`，项目名为 `Workhunter v2.0｜一周重建`，关联本仓库；目标共 19 项，包括 18 个业务/验收 Issue 与 1 个 `PM-SETUP` 管理阻塞 Issue。实际 Project ID、URL 和视图 ID 在成功读回前保持 `null`。

仓库中的 [BOARD](BOARD.md) / [ROADMAP](ROADMAP.md) 用于继续开发排期，但不代表原生平台视图已就绪。[#19](https://github.com/caor3693-cmyk/Workhunter-v2.0/issues/19) 保持 Blocked/open，实际 Project 与视图 ID/URL 保持 `null`。S0 的代码、自验和私有 Site 候选已于 10-10 保存，#6 / G0 #1 进入 Awaiting verification/open；这些事实不解除 #19，也不表示 G0 已通过。管理配置阻塞、Site 用户核验和正式部署分别记录，详见 [STATUS](STATUS.md) 与 [S0 交付包](deliveries/S0.md)。

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

1. 读取配置与真实 Issue 索引，确认目标仓库及 19 项期望集合；`PM-SETUP` 使用配置中的实际 Issue，不再次创建同名 Issue。
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
- 分页核对目标 19 个 Issue 都有真实项目项且无重复；复用项目有其他项时分别记录，不以总数等于 19 强制清理。
- 逐项读回五个目标字段的实际值；状态符合当前证据，排期对应 ROADMAP，计划起始日期不晚于目标日期。
- 读回 Board/Roadmap 的名称、ID、number、layout；视图筛选没有意外隐藏目标任务。分组、日期绑定和条目显示由平台 UI 核实并记录结果。
- 从原生 Project 打开抽查 Issue，确认落到本仓库的真实条目；记录检查日期和 Project/视图入口，不推测 URL。
- 再次运行接续检查只报告差异，不重复新建项目、字段、视图或 Issue；只有全部目标核实后才完成 `PM-SETUP`。

若目前仍无可用授权通道，保留 ID/URL 为 `null`、管理阻塞 Issue 为 open，并继续可独立推进的开发与文档工作。完成项目管理配置不等于完成任何 Site Gate，也不构成正式部署的验收记录。
