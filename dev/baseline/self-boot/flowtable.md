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
| 循环与漂移 | 05 | 模块 · drift | 任务 | — | — | — | 脚本 | selfboot | — | →06 | 26 个函数 · ⊞ drift/flowtable.md |
| 渲染 | 06 | 模块 · engine | 任务 | — | — | — | 脚本 | selfboot | — | →07 | 26 个函数 · ⊞ engine/flowtable.md |
| 接管与解析 | 07 | 模块 · flowtable | 任务 | — | — | — | 脚本 | selfboot | — | →08 | 27 个函数 · ⊞ flowtable/flowtable.md |
| 结构校验 | 08 | 模块 · flowtable_check | 任务 | — | — | — | 脚本 | selfboot | — | →09 | 29 个函数 · ⊞ flowtable_check/flowtable.md |
| 布局与配色 | 09 | 模块 · flowtable_colors | 任务 | — | — | — | 脚本 | selfboot | — | →10 | 8 个函数 · ⊞ flowtable_colors/flowtable.md |
| 布局与配色 | 10 | 模块 · flowtable_layout | 任务 | — | — | — | 脚本 | selfboot | — | →11 | 21 个函数 · ⊞ flowtable_layout/flowtable.md |
| 渲染 | 11 | 模块 · geometry | 任务 | — | — | — | 脚本 | selfboot | — | →12 | 33 个函数 · ⊞ geometry/flowtable.md |
| 编排入口 | 12 | 模块 · init | 任务 | — | — | — | 脚本 | selfboot | — | →13 | 4 个函数 · ⊞ init/flowtable.md |
| 接管与解析 | 13 | 模块 · intake | 任务 | — | — | — | 脚本 | selfboot | — | →14 | 9 个函数 · ⊞ intake/flowtable.md |
| 渲染 | 14 | 模块 · label | 任务 | — | — | — | 脚本 | selfboot | — | →15 | 9 个函数 · ⊞ label/flowtable.md |
| 渲染 | 15 | 模块 · lane_router | 任务 | — | — | — | 脚本 | selfboot | — | →16 | 35 个函数 · ⊞ lane_router/flowtable.md |
| 层级索引 | 16 | 模块 · layer_index | 任务 | — | — | — | 脚本 | selfboot | — | →17 | 9 个函数 · ⊞ layer_index/flowtable.md |
| 接管与解析 | 17 | 模块 · ledger | 任务 | — | — | — | 脚本 | selfboot | — | →18 | 9 个函数 · ⊞ ledger/flowtable.md |
| 产物审核 | 18 | 模块 · manifest | 任务 | — | — | — | 脚本 | selfboot | — | →19 | 29 个函数 · ⊞ manifest/flowtable.md |
| 接管与解析 | 19 | 模块 · parse | 任务 | — | — | — | 脚本 | selfboot | — | →20 | 15 个函数 · ⊞ parse/flowtable.md |
| 接管与解析 | 20 | 模块 · parse_legacy | 任务 | — | — | — | 脚本 | selfboot | — | →21 | 14 个函数 · ⊞ parse_legacy/flowtable.md |
| 接管与解析 | 21 | 模块 · parse_ooxml | 任务 | — | — | — | 脚本 | selfboot | — | →22 | 11 个函数 · ⊞ parse_ooxml/flowtable.md |
| 接管与解析 | 22 | 模块 · parse_pdf | 任务 | — | — | — | 脚本 | selfboot | — | →23 | 7 个函数 · ⊞ parse_pdf/flowtable.md |
| 接管与解析 | 23 | 模块 · parse_text | 任务 | — | — | — | 脚本 | selfboot | — | →24 | 13 个函数 · ⊞ parse_text/flowtable.md |
| 接管与解析 | 24 | 模块 · plan | 任务 | — | — | — | 脚本 | selfboot | — | →25 | 15 个函数 · ⊞ plan/flowtable.md |
| 接管与解析 | 25 | 模块 · pptx_text | 任务 | — | — | — | 脚本 | selfboot | — | →26 | 8 个函数 · ⊞ pptx_text/flowtable.md |
| 接管与解析 | 26 | 模块 · probe | 任务 | — | — | — | 脚本 | selfboot | — | →27 | 12 个函数 · ⊞ probe/flowtable.md |
| 循环与漂移 | 27 | 模块 · query | 任务 | — | — | — | 脚本 | selfboot | — | →28 | 9 个函数 · ⊞ query/flowtable.md |
| 接管与解析 | 28 | 模块 · recon | 任务 | — | — | — | 脚本 | selfboot | — | →29 | 25 个函数 · ⊞ recon/flowtable.md |
| 渲染 | 29 | 模块 · render_drawio | 任务 | — | — | — | 脚本 | selfboot | — | →30 | 24 个函数 · ⊞ render_drawio/flowtable.md |
| 渲染 | 30 | 模块 · render_html | 任务 | — | — | — | 脚本 | selfboot | — | →31 | 23 个函数 · ⊞ render_html/flowtable.md |
| 接管与解析 | 31 | 模块 · render_pages | 任务 | — | — | — | 脚本 | selfboot | — | →32 | 12 个函数 · ⊞ render_pages/flowtable.md |
| 渲染 | 32 | 模块 · render_svg | 任务 | — | — | — | 脚本 | selfboot | — | →33 | 11 个函数 · ⊞ render_svg/flowtable.md |
| 渲染 | 33 | 模块 · router | 任务 | — | — | — | 脚本 | selfboot | — | →34 | 30 个函数 · ⊞ router/flowtable.md |
| 接管与解析 | 34 | 模块 · semantics | 任务 | — | — | — | 脚本 | selfboot | — | →35 | 17 个函数 · ⊞ semantics/flowtable.md |
| 编排入口 | 35 | 模块 · shot | 任务 | — | — | — | 脚本 | selfboot | — | →36 | 8 个函数 · ⊞ shot/flowtable.md |
| 渲染 | 36 | 模块 · swimlane | 任务 | — | — | — | 脚本 | selfboot | — | →37 | 19 个函数 · ⊞ swimlane/flowtable.md |
| 同步闭环 | 37 | 模块 · sync | 任务 | — | — | — | 脚本 | selfboot | — | →38 | 10 个函数 · ⊞ sync/flowtable.md |
| DSL 装配 | 38 | 模块 · table_to_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →39 | 14 个函数 · ⊞ table_to_dsl/flowtable.md |
| 接管与解析 | 39 | 模块 · textquality | 任务 | — | — | — | 脚本 | selfboot | — | →40 | 8 个函数 · ⊞ textquality/flowtable.md |
| 产物审核 | 40 | 模块 · validate | 任务 | — | — | — | 脚本 | selfboot | — | →41 | 39 个函数 · ⊞ validate/flowtable.md |
| 同步闭环 | 41 | 模块 · writeback | 任务 | — | — | — | 脚本 | selfboot | — | →42 | 21 个函数 · ⊞ writeback/flowtable.md |
| 同步闭环 | 42 | 模块 · xml_reader | 任务 | — | — | — | 脚本 | selfboot | — | →43 | 40 个函数 · ⊞ xml_reader/flowtable.md |
| 出口 | 43 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
