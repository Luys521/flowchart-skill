---
id: selfboot-clarify
level: L1
parent: ../flowtable.md
---

# clarify.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→14 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | load_nodes | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 流程表 → (title, nodes)。表有硬错误时抛 ValueError。 · L30 · 函数 · ⇢ 依赖 flowtable.parse_table、flowtable_check.check_nodes |
| 模块级 | 03 | pending | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 节点列表 → {'inferred': [...], 'verdict': [...]}。 · L45 · 函数 · ⇢ 依赖 semantics.pending_kind |
| 模块级 | 04 | _verdict_graph | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 待裁决节点之间的依赖图 → (verdict 集合, 前驱表, 环内节点集合)。 · L59 · 函数 · ⇢ 依赖 semantics.pending_kind |
| 模块级 | 05 | frontier | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→15 | ★ 当前可问的 `⚠?` 节点 id 列表（有序，按表序）。 · L95 · 函数 · 分支：1→_verdict_graph 2→frontier.ring_why |
| 模块级 | 06 | hidden | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ 因上游未决而**暂时问不了**的 `⚠?` 节点 id（有序）。 · L138 · 函数 · ⇢ 依赖 semantics.pending_kind |
| 模块级 | 07 | brief | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→05｜4→06 | ★ 汇总：分类计数 + frontier + 暂时问不了的。纯数据，打印与 --json 共用。 · L151 · 函数 · 分支：1→pending 2→_verdict_graph 3→frontier 4→hidden |
| 模块级 | 08 | _add_inferred | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 追加「AI 推断」分节（有依据、无需提问的一类）。 · L177 · 函数 |
| 模块级 | 09 | _add_verdict_head | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 追加「待你裁决」总账行（环内项单算，不并入"等上游"）。 · L185 · 函数 |
| 模块级 | 10 | _add_frontier | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 追加当前 frontier 及每项的走向、材料现状。 · L199 · 函数 |
| 模块级 | 11 | _add_waiting | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 追加「暂时问不了」两栏：等上游 / 环内互为前驱互相等待。 · L210 · 函数 |
| 模块级 | 12 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09｜3→10｜4→11 | ★ 简报 → 人可读文本。**只报状态，不下结论**——"已收敛"不等于"已把关"（见 D-02）。 · L232 · 函数 · 分支：1→_add_inferred 2→_add_verdict_head 3→_add_frontier 4→_add_waiting |
| 模块级 | 13 | _emit_report | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 按 --json 或人可读两种口径打印简报。 · L255 · 函数 |
| 模块级 | 14 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→07｜3→13 | L265 · 函数 · 分支：1→load_nodes 2→brief 3→_emit_report · ⇢ 依赖 flowtable.build_edges |
| frontier | 15 | frontier.ring_why | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 环内节点的阻塞说明：点名它的环内前驱，说明是互相等、不是等上游。 · L113 · 嵌套函数 |
| 出口 | 16 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
