---
id: selfboot-map
level: L0
---

# self-boot — 模块索引

> 本表是自举流程表树的根：一行一个模块，`⊞` 指向该模块的函数流程表。`coverage.py` 把根表（L0）排除在覆盖率之外——它不是模块。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | →02 | 模块清单（结构性节点，不是函数） |
| 接管与解析 | 02 | 模块 · artifact | 任务 | — | — | — | 脚本 | selfboot | — | →03 | 2 个函数 · ⊞ artifact/flowtable.md |
| 编排入口 | 03 | 模块 · build | 任务 | — | — | — | 脚本 | selfboot | — | →04 | 25 个函数 · ⊞ build/flowtable.md |
| 编排入口 | 04 | 模块 · clarify | 任务 | — | — | — | 脚本 | selfboot | — | →05 | 14 个函数 · ⊞ clarify/flowtable.md |
| 渲染 | 05 | 模块 · engine | 任务 | — | — | — | 脚本 | selfboot | — | →06 | 26 个函数 · ⊞ engine/flowtable.md |
| 接管与解析 | 06 | 模块 · flowtable | 任务 | — | — | — | 脚本 | selfboot | — | →07 | 27 个函数 · ⊞ flowtable/flowtable.md |
| 结构校验 | 07 | 模块 · flowtable_check | 任务 | — | — | — | 脚本 | selfboot | — | →08 | 29 个函数 · ⊞ flowtable_check/flowtable.md |
| 布局与配色 | 08 | 模块 · flowtable_colors | 任务 | — | — | — | 脚本 | selfboot | — | →09 | 8 个函数 · ⊞ flowtable_colors/flowtable.md |
| 布局与配色 | 09 | 模块 · flowtable_layout | 任务 | — | — | — | 脚本 | selfboot | — | →10 | 21 个函数 · ⊞ flowtable_layout/flowtable.md |
| 渲染 | 10 | 模块 · geometry | 任务 | — | — | — | 脚本 | selfboot | — | →11 | 33 个函数 · ⊞ geometry/flowtable.md |
| 编排入口 | 11 | 模块 · init | 任务 | — | — | — | 脚本 | selfboot | — | →12 | 4 个函数 · ⊞ init/flowtable.md |
| 渲染 | 12 | 模块 · label | 任务 | — | — | — | 脚本 | selfboot | — | →13 | 9 个函数 · ⊞ label/flowtable.md |
| 渲染 | 13 | 模块 · lane_router | 任务 | — | — | — | 脚本 | selfboot | — | →14 | 35 个函数 · ⊞ lane_router/flowtable.md |
| 层级索引 | 14 | 模块 · layer_index | 任务 | — | — | — | 脚本 | selfboot | — | →15 | 9 个函数 · ⊞ layer_index/flowtable.md |
| 接管与解析 | 15 | 模块 · ledger | 任务 | — | — | — | 脚本 | selfboot | — | →16 | 7 个函数 · ⊞ ledger/flowtable.md |
| 产物审核 | 16 | 模块 · manifest | 任务 | — | — | — | 脚本 | selfboot | — | →17 | 29 个函数 · ⊞ manifest/flowtable.md |
| 接管与解析 | 17 | 模块 · parse_ooxml | 任务 | — | — | — | 脚本 | selfboot | — | →18 | 8 个函数 · ⊞ parse_ooxml/flowtable.md |
| 接管与解析 | 18 | 模块 · probe | 任务 | — | — | — | 脚本 | selfboot | — | →19 | 8 个函数 · ⊞ probe/flowtable.md |
| 渲染 | 19 | 模块 · render_drawio | 任务 | — | — | — | 脚本 | selfboot | — | →20 | 24 个函数 · ⊞ render_drawio/flowtable.md |
| 渲染 | 20 | 模块 · render_html | 任务 | — | — | — | 脚本 | selfboot | — | →21 | 23 个函数 · ⊞ render_html/flowtable.md |
| 渲染 | 21 | 模块 · render_svg | 任务 | — | — | — | 脚本 | selfboot | — | →22 | 11 个函数 · ⊞ render_svg/flowtable.md |
| 渲染 | 22 | 模块 · router | 任务 | — | — | — | 脚本 | selfboot | — | →23 | 30 个函数 · ⊞ router/flowtable.md |
| 接管与解析 | 23 | 模块 · semantics | 任务 | — | — | — | 脚本 | selfboot | — | →24 | 17 个函数 · ⊞ semantics/flowtable.md |
| 编排入口 | 24 | 模块 · shot | 任务 | — | — | — | 脚本 | selfboot | — | →25 | 8 个函数 · ⊞ shot/flowtable.md |
| 渲染 | 25 | 模块 · swimlane | 任务 | — | — | — | 脚本 | selfboot | — | →26 | 19 个函数 · ⊞ swimlane/flowtable.md |
| 同步闭环 | 26 | 模块 · sync | 任务 | — | — | — | 脚本 | selfboot | — | →27 | 10 个函数 · ⊞ sync/flowtable.md |
| DSL 装配 | 27 | 模块 · table_to_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →28 | 14 个函数 · ⊞ table_to_dsl/flowtable.md |
| 产物审核 | 28 | 模块 · validate | 任务 | — | — | — | 脚本 | selfboot | — | →29 | 39 个函数 · ⊞ validate/flowtable.md |
| 同步闭环 | 29 | 模块 · writeback | 任务 | — | — | — | 脚本 | selfboot | — | →30 | 21 个函数 · ⊞ writeback/flowtable.md |
| 同步闭环 | 30 | 模块 · xml_reader | 任务 | — | — | — | 脚本 | selfboot | — | →31 | 40 个函数 · ⊞ xml_reader/flowtable.md |
| 出口 | 31 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
