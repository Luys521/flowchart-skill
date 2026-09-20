---
id: selfboot-render_html
level: L1
parent: ../flowtable.md
---

# render_html.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→24 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _defs_block | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 整篇文档共用的资源：箭头 marker + 流光模糊。**必须放在所有视图之外**（见 D-90）。 · L62 · 函数 · ⇢ 依赖 semantics.arrow_markers |
| 模块级 | 03 | esc | 任务 | — | — | — | 脚本 | selfboot | — | →25 | L183 · 函数 |
| 模块级 | 04 | fmt | 任务 | — | — | — | 脚本 | selfboot | — | →25 | L188 · 函数 |
| 模块级 | 05 | _display_desc | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 悬浮框里显示的「节点描述」：剥掉行首的标记语法本身（`⚠…` / `▣ 路径；…`）。 · L192 · 函数 |
| 模块级 | 06 | _sub_ring | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 可下钻节点的**内衬线**（见 D-78）：同形状、向内缩 `SUB_INSET` 的一圈细线。 · L206 · 函数 · ⇢ 依赖 geometry.arc_px |
| 模块级 | 07 | svg_node | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→06 | L228 · 函数 · 分支：1→esc 2→fmt 3→_sub_ring · ⇢ 依赖 engine.Engine.node_lines、engine.Engine.rect、geometry.arc_px、semantics.pending_style |
| 模块级 | 08 | _node_row | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 节点所在行 —— 用作流光的错峰序号（光顺着流程一段段亮过去）。 · L287 · 函数 |
| 模块级 | 09 | svg_edge | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→08｜4→10 | L298 · 函数 · 分支：1→esc 2→fmt 3→_node_row 4→svg_label · ⇢ 依赖 engine.Engine.path、engine.Engine.polarity |
| 模块级 | 10 | svg_label | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | L327 · 函数 · 分支：1→esc 2→fmt · ⇢ 依赖 engine.Engine.label_box |
| 模块级 | 11 | svg_lanes | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | ★ 泳道背景：顶部部门带 + 左侧阶段带 + 部门列底色（画在边与节点之前，规则见 swimlane-spec §6）。 · L338 · 函数 · 分支：1→esc 2→fmt · ⇢ 依赖 engine.Engine.height |
| 模块级 | 12 | html_head | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 标题模块：标题 + 图例色块合成一个 `position: fixed` 的条（滚动不离视窗）。 · L379 · 函数 |
| 模块级 | 13 | collect_views | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 主 DSL → 内嵌视图计划（BFS，按**表**去重，防环）。见 D-52。 · L399 · 函数 · ⇢ 依赖 artifact.artifact_stem、engine.load、semantics.subflow_target |
| 模块级 | 14 | _union_subjects | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 跨层配色并集：[(来源, 配色表)…] → (并集表, [冲突…])。见 D-52 / D-49。 · L505 · 函数 |
| 模块级 | 15 | _view_svg | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→07｜3→09｜4→11 | ★ 一张图 → (svg 字符串, tips 字典, 画布高)。 · L529 · 函数 · 分支：1→_display_desc 2→svg_node 3→svg_edge 4→svg_lanes · ⇢ 依赖 engine.Engine.height、engine.Engine.lanes、engine.Engine.route_text、semantics.pending_style、semantics.subflow_target |
| 模块级 | 16 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→17｜3→18｜4→19｜5→20｜6→21｜7→22｜8→23 | ★ DSL → 独立 HTML。按阶段装配：上下文 → 视图块 → 页头/正文 → 整页 → 落盘。 · L578 · 函数 · 分支：1→html_head 2→_load_render_context 3→_assemble_view_blocks 4→_serialize_tips 5→_build_crumbs 6→_build_page_body 7→_build_html_document 8→_write_html_output |
| 模块级 | 17 | _load_render_context | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→15 | ★ 加载主 DSL、收集内嵌视图计划并渲染主视图，返回渲染上下文 dict。 · L608 · 函数 · 分支：1→collect_views 2→_view_svg · ⇢ 依赖 engine.Engine.head_band、engine.Engine.height、engine.load |
| 模块级 | 18 | _assemble_view_blocks | 任务 | — | — | — | 脚本 | selfboot | — | 1→14｜2→15 | ★ 装配主视图与各内嵌子视图的 (key, 标题, svg, 宽, 高) 块，并归并跨层图例。 · L625 · 函数 · 分支：1→_union_subjects 2→_view_svg · ⇢ 依赖 engine.Engine.head_band、engine.load |
| 模块级 | 19 | _serialize_tips | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 把悬浮提示表序列化成可安全内联进 <script> 的 JS JSON 字面量。 · L652 · 函数 |
| 模块级 | 20 | _build_crumbs | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 生成面包屑 HTML 与标题模块附加类；顶层主图无回程路时两者皆空。 · L663 · 函数 |
| 模块级 | 21 | _build_page_body | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 生成 body 内的视图容器：多视图每个视图一块 `.chart-container`，单视图只有主图。 · L685 · 函数 |
| 模块级 | 22 | _build_html_document | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 把标题/视图/提示数据套进整页 HTML 模板，并注入多视图 CSS/JS 与点击行为。 · L697 · 函数 · 分支：1→_defs_block 2→esc |
| 模块级 | 23 | _write_html_output | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 落盘 HTML 并打印一行摘要，返回退出码 0。 · L941 · 函数 |
| 模块级 | 24 | main | 任务 | — | — | — | 脚本 | selfboot | — | →16 | L953 · 函数 |
| 出口 | 25 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
