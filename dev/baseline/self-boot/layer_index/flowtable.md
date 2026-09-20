---
id: selfboot-layer_index
level: L1
parent: ../flowtable.md
---

# layer_index.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→10 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _rel | 任务 | — | — | — | 脚本 | selfboot | — | →13 | L28 · 函数 |
| 模块级 | 03 | _visit_subflow | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | ★ 深度优先走一遍 ▣ 派生树，把每张表的层级信息登记进 tables（就地修改）。 · L39 · 函数 · 分支：1→_rel 2→递归边界？ · ⇢ 依赖 artifact.artifact_stem、flowtable.parse_table、flowtable.split_row_cells、semantics.subflow_target |
| 拆环 | 04 | 递归边界？ | 判断 | — | — | — | 脚本 | selfboot | — | 是→13｜否→03 | 结构性判断（拆环）：_visit_subflow 直接递归自己。是 → 收尾（结束）；否 → 走下一跳（_visit_subflow）。 |
| 模块级 | 05 | _find_orphans | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 目录树里可达集之外的 .md → 孤儿表警告（生成物与说明文档不算表）。 · L68 · 函数 · ⇢ 依赖 artifact.artifact_stem |
| 模块级 | 06 | _check_identity | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 身份一致性（D-59）：id 全树唯一；level 声明与 ▣ 推导深度一致 → 警告列表。 · L82 · 函数 |
| 模块级 | 07 | _build_order | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 层级降序（自底向上）排构建顺序，并收集"多条路径到达"的歧义警告 → (order, notes)。 · L100 · 函数 |
| 模块级 | 08 | build_layer_index | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→05｜4→06｜5→07 | ★ 主流程表路径 → {'tables': {相对路径: 层级信息}, 'order': [构建顺序], 'notes':… · L112 · 函数 · 分支：1→_rel 2→_visit_subflow 3→_find_orphans 4→_check_identity 5→_build_order |
| 模块级 | 09 | format_index_md | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 层级索引 → markdown（<流程名>-index.md 的正文）。 · L126 · 函数 |
| 模块级 | 10 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09 | L157 · 函数 · 分支：1→build_layer_index 2→format_index_md · ⇢ 依赖 artifact.artifact_stem |
| format_index_md | 11 | format_index_md.tree | 任务 | — | — | — | 脚本 | selfboot | — | →12 | L133 · 嵌套函数 |
| 拆环 | 12 | 递归边界？ | 判断 | — | — | — | 脚本 | selfboot | — | 是→13｜否→11 | 结构性判断（拆环）：format_index_md.tree 直接递归自己。是 → 收尾（结束）；否 → 走下一跳（format_index_md.tree）。 |
| 出口 | 13 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
