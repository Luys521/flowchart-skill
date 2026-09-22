---
id: selfboot-flowtable_check
level: L1
parent: ../flowtable.md
---

# flowtable_check.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→31｜2→36｜3→37 | 流程起点（结构性节点，不是函数） · 入口：1→check_header 2→check_evidence 3→run_checks |
| 模块级 | 02 | _split_row_cells | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 补齐到 N_COLS 并按 ICOM 序切成 · L39 · 函数 · ⇢ 依赖 flowtable.split_row_cells |
| 模块级 | 03 | _check_node_id | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H2：编号重复与编号格式校验，合法与否都记入 seen（跨行查重）。 · L45 · 函数 |
| 模块级 | 04 | _check_node_semantics | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ H7：名称/执行主体/节点类型/执行者/行动所需时间；类型非法兜底成「任务」并返回该类型。 · L68 · 函数 |
| 模块级 | 05 | _check_time_format | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H7(软)：「行动所需时间」有值却不像一个量（如 `尽快` / `3` / `两天`）→ 软提示。 · L102 · 函数 |
| 模块级 | 06 | _check_basis | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 「依据」与 `⚠` 的咬合（字段登记表见 flowtable-spec §2）：判断节点要么写清判据，要么标 `⚠`。 · L117 · 函数 · ⇢ 依赖 semantics.pending_kind |
| 模块级 | 07 | check_nodes | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→06 | ★ ① 节点层：逐行检查编号与语义列，返回可进流程的节点列表。 · L129 · 函数 · 分支：1→_split_row_cells 2→_check_node_id 3→_check_node_semantics 4→_check_basis |
| 模块级 | 08 | _build_adjacency | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 按 id 建出/入边邻接表 → (out_e, in_e)，②③ 两层共用。 · L154 · 函数 |
| 模块级 | 09 | _check_min_count | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H1：每种类型的节点总数不得低于 TYPE_RULES 声明的 min_count。 · L164 · 函数 |
| 模块级 | 10 | _check_out_rule | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H5/H8：单个节点的出边要求——forbid 却有出边报 H5，need 却无出边且被指过报死胡同。 · L174 · 函数 · ⇢ 依赖 flowtable.wrote_route |
| 模块级 | 11 | _check_decision_branches | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H4/H8：判断节点自身——分支下限、缺标签、分支指向同一目标、分支标签重复。 · L190 · 函数 |
| 模块级 | 12 | check_by_type | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09｜3→10｜4→11 | ★ ② 类型层：执行文件顶部的 TYPE_RULES——只看这个节点自身与它的出边。 · L221 · 函数 · 分支：1→_build_adjacency 2→_check_min_count 3→_check_out_rule 4→_check_decision_branches |
| 模块级 | 13 | _check_dangling | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H3：引用完整——「下个节点」指向的目标必须真实存在。 · L235 · 函数 |
| 模块级 | 14 | _reachable_from_starts | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 从所有「开始」节点做一次可达性扩散 → 可达 id 集合。 · L242 · 函数 |
| 模块级 | 15 | _check_node_reach | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H8：单个节点的连通判定——一个节点只报最可操作的一条（让位规则见 flowtable-spec §3）。 · L255 · 函数 · ⇢ 依赖 flowtable.wrote_route |
| 模块级 | 16 | _check_subflow_decl | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H9：`▣` 声明的两条约束——一格至多一个、路径必须落在本表目录内（G76/G77）。 · L289 · 函数 · ⇢ 依赖 semantics.subflow_ref |
| 模块级 | 17 | check_relations | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→13｜3→14｜4→15｜5→20 | ★ ③ 关系层：引用完整（H3）、逻辑连通（H8）、回路有出口（H6）。 · L316 · 函数 · 分支：1→_build_adjacency 2→_check_dangling 3→_reachable_from_starts 4→_check_node_reach 5→check_deadloop |
| 模块级 | 18 | _pruned_adjacency | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 删掉所有判断节点（及其邻接边）后的子图邻接表——只剩纯任务/起止之间的边。 · L336 · 函数 |
| 模块级 | 19 | _walk_cycle | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 三色 DFS（**显式栈**，G72）：沿 adj 下探，遇灰节点（返祖边）就报一条回路，回溯时标黑。 · L345 · 函数 |
| 模块级 | 20 | check_deadloop | 任务 | — | — | — | 脚本 | selfboot | — | 1→18｜2→19 | ★ H6：每个有向回路至少含 1 个判断节点。 · L377 · 函数 · 分支：1→_pruned_adjacency 2→_walk_cycle |
| 模块级 | 21 | check_label_length | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 分支标签过长 → 软提示。标签画在连线上，过长会撑爆徽章底框、挤占版面。 · L395 · 函数 |
| 模块级 | 22 | _derived_level | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 沿 parent/▣ 链向上数跳数 → 派生层级（L0=主流程）。环与断链按已走跳数计。 · L413 · 函数 · ⇢ 依赖 flowtable.find_parent_table |
| 模块级 | 23 | _check_meta_keys | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 身份区键封闭：未知键报 H9，▣ 派生量键（层级/子表/构建顺序）单独给文案（D-56）。 · L430 · 函数 |
| 模块级 | 24 | _check_header_entries | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 表头区（frontmatter 之后、主表之前）不放 `- 条目` 式元信息（D-57）。 · L446 · 函数 |
| 模块级 | 25 | _check_level | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ level：声明与 ▣ 推导双向校验（L0=主流程，D-59）——格式须为 L0/L1/L2…，且与推导一致。 · L463 · 函数 |
| 模块级 | 26 | _check_parent | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ parent：双向一致（D-58）——非空则文件须存在，且父表里要有 ▣ 指回本表。 · L480 · 函数 · ⇢ 依赖 flowtable._has_backref |
| 模块级 | 27 | _check_refs | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ refs：依赖路径必须真实存在（单条字符串按单元素列表处理）；**写了键就不能是空值**（G38）。 · L497 · 函数 |
| 模块级 | 28 | _check_meta_id | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ id：写了却为空 → H9（缺省取文件 stem，可整行删除）。 · L517 · 函数 |
| 模块级 | 29 | _check_color_dup | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 同一主体在「主体配色」里声明了两种不同的颜色 → H9。 · L524 · 函数 |
| 模块级 | 30 | _check_table_columns | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ H9：主表的列名必须逐字等于 `flowtable.COLUMNS`。 · L531 · 函数 · ⇢ 依赖 flowtable.header_cells |
| 模块级 | 31 | check_header | 任务 | — | — | — | 脚本 | selfboot | — | 1→23｜2→24｜3→25｜4→26｜5→27｜6→28｜7→29｜8→30 | ★ H9 表头规范（D-59，三区结构）：YAML=身份（键封闭、level/parent 双向校验、refs 存在）； · L554 · 函数 · 分支：1→_check_meta_keys 2→_check_header_entries 3→_check_level 4→_check_parent 5→_check_refs 6→_check_meta_id 7→_check_color_dup 8→_check_table_columns |
| 模块级 | 32 | find_task_ledger | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 从某个产物所在目录**向上**找 `evidence.json`（任务级产物住成果根）→ `(账本或 None, 找过… · L587 · 函数 |
| 模块级 | 33 | ledger_display | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 账本的**相对**写法（相对本表目录）——一眼看出它住在上面几层，而不是只报个文件名。 · L611 · 函数 |
| 模块级 | 34 | ledger_element_ids | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 账本里的 element id 集合；**读不动返回 `None`**（＝无从判断，不许当成"表写错了"）。 · L621 · 函数 |
| 模块级 | 35 | citations | 任务 | — | — | — | 脚本 | selfboot | — | →38 | ★ 文本里出现的 element id（按出现顺序，去重）。id 是**封闭语法**（§2.2），正则认得出来。 · L634 · 函数 |
| 模块级 | 36 | check_evidence | 任务 | — | — | — | 脚本 | selfboot | — | 1→32｜2→33｜3→34｜4→35 | ★ **H10.1 引用完整**：产物里出现的每个 element id 都必须在账本里存在。 · L644 · 函数 · 分支：1→find_task_ledger 2→ledger_display 3→ledger_element_ids 4→citations |
| 模块级 | 37 | run_checks | 任务 | — | — | — | 脚本 | selfboot | — | 1→07｜2→12｜3→16｜4→17｜5→21 | ★ 按 ① → ② → ③ 跑完整套结构校验；返回 (nodes, edges, errs)。 · L687 · 函数 · 分支：1→check_nodes 2→check_by_type 3→_check_subflow_decl 4→check_relations 5→check_label_length · ⇢ 依赖 flowtable.build_edges、flowtable_layout.apply_swimlane、flowtable_layout.assign_slots |
| 出口 | 38 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
