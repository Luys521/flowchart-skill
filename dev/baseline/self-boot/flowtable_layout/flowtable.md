---
id: selfboot-flowtable_layout
level: L1
parent: ../flowtable.md
---

# flowtable_layout.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→09｜4→15｜5→18｜6→22 | 流程起点（结构性节点，不是函数） · 入口：1→parse_lane_order 2→apply_swimlane 3→assign_slots 4→merge_parallel_branches 5→auto_layout 6→reuse_hint |
| 模块级 | 02 | parse_lane_order | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 「- 泳道列序：A → B → C」→ ['A', 'B', 'C']（兼容 `,` `，` `、` 分隔）。 · L13 · 函数 |
| 模块级 | 03 | apply_swimlane | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 泳道布局：行 = 项目运作阶段、列 = 执行主体。 · L22 · 函数 |
| 模块级 | 04 | _topo_order | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ Kahn 拓扑序；有环（回路）返回 None，调用方退回表序（见 swimlane-spec §3.1）。 · L40 · 函数 |
| 模块级 | 05 | _resolve_slot_order | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 定槽位推导用的节点顺序：Kahn 拓扑序；有环退回表序，并把提示写进 notes。 · L63 · 函数 |
| 模块级 | 06 | _incoming_sources | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 每个节点的入边来源表（自环边略过）→ {id: [起点, …]}。 · L72 · 函数 |
| 模块级 | 07 | _solve_slots | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ DP 求每个节点的槽号 → {id: 槽号}（多入边取最深的一条）。 · L81 · 函数 |
| 模块级 | 08 | _compact_slots | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 分支可能跳过某个槽号 → 压缩掉空槽，层数才是真实层数。 · L98 · 函数 |
| 模块级 | 09 | assign_slots | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→07｜4→08 | ★ 槽位求解：把 row 从「阶段号」细化为「槽位号」，返回 (slots, notes)。 · L105 · 函数 · 分支：1→_resolve_slot_order 2→_incoming_sources 3→_solve_slots 4→_compact_slots |
| 模块级 | 10 | _forward_successors | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 只留「行号递增」的前向边 → {起点: {后继, …}}。 · L129 · 函数 |
| 模块级 | 11 | _merge_branch_group | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 把一组汇聚到同一点的分支并到同一行的相邻列（首分支留在原位，其余向右排）。 · L138 · 函数 |
| 模块级 | 12 | _merge_parallel_rows | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 按「后继集合完全相同且非空」分组，逐组把并行分支并排到同一行。 · L153 · 函数 |
| 模块级 | 13 | balance_arms | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 并行分支按**墨迹重量**分挂主轴两侧，把主轴摆到中轴上（D-92「臂」）。 · L168 · 函数 |
| 模块级 | 14 | _apply_row_remap | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 把腾空的层压掉（重排行号），并把 row/col 写回节点。 · L206 · 函数 |
| 模块级 | 15 | merge_parallel_branches | 任务 | — | — | — | 脚本 | selfboot | — | 1→10｜2→12｜3→13｜4→14 | ★ 并行分支并排：同一节点分出的多条前向分支若**汇聚到同一点**，把它们并到一行、占相邻列。 · L214 · 函数 · 分支：1→_forward_successors 2→_merge_parallel_rows 3→balance_arms 4→_apply_row_remap |
| 模块级 | 16 | _between_in_col | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 同一列里 c 之外是否已有节点夹在行 a 与 b 之间（判断两节点是否"相邻"）。 · L230 · 函数 |
| 模块级 | 17 | _edge_kind | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 按行列位置推导一条边的 kind：同行 horiz / 回退 loop / 同列相邻 spine / 其余 jumpR。 · L235 · 函数 |
| 模块级 | 18 | auto_layout | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 基线布局：row=表序，col=0 单主列；由位置推导 kind；通道交 `router` 现场规划（见 dsl-sp… · L247 · 函数 |
| 模块级 | 19 | _index_hints | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 把布局提示的边按 (from, to) 建索引 → {(from, to): [提示边, …]}。 · L267 · 函数 |
| 模块级 | 20 | _pick_hint | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 按「label 相同 > kind 相同 > 任意」挑一条提示边并从池子里消耗掉它；挑不到返回 None。 · L275 · 函数 |
| 模块级 | 21 | _apply_hint | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 把提示边的手调 kind 与几何键借给 DSL 边（label / polarity 一律来自流程表，不被覆盖）。 · L291 · 函数 |
| 模块级 | 22 | reuse_hint | 任务 | — | — | — | 脚本 | selfboot | — | 1→19｜2→20｜3→21 | ★ --layout 提示：借用几何键（gutter / channel / gapx / dye / exit / en… · L302 · 函数 · 分支：1→_index_hints 2→_pick_hint 3→_apply_hint |
| 出口 | 23 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
