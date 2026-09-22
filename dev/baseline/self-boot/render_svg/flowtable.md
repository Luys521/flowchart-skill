---
id: selfboot-render_svg
level: L1
parent: ../flowtable.md
---

# render_svg.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→12 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _fmt | 任务 | — | — | — | 脚本 | selfboot | — | →13 | L52 · 函数 |
| 模块级 | 03 | _defs | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 本产物的 `<defs>`：只有箭头 marker（没有 html 那份流光模糊——这份产物不带动画）。 · L56 · 函数 · ⇢ 依赖 semantics.arrow_markers |
| 模块级 | 04 | _esc | 任务 | — | — | — | 脚本 | selfboot | — | →13 | L65 · 函数 |
| 模块级 | 05 | _shape_xml | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 形状画在**局部坐标**（以节点中心为 0,0）——`manifest._html_shape` 就是这么读的。 · L70 · 函数 · ⇢ 依赖 geometry.arc_px |
| 模块级 | 06 | _drillable | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 声明了 `▣` 且**子表产物真的存在**的节点 → {节点id}。 · L91 · 函数 · ⇢ 依赖 artifact.artifact_rel、semantics.subflow_target |
| 模块级 | 07 | _emit_node | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→05 | L111 · 函数 · 分支：1→_fmt 2→_esc 3→_shape_xml · ⇢ 依赖 engine.Engine.node_lines、engine.Engine.rect、semantics.pending_style |
| 模块级 | 08 | _emit_edge | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→09 | L151 · 函数 · 分支：1→_fmt 2→_esc 3→_emit_label · ⇢ 依赖 engine.Engine.path、engine.Engine.polarity、geometry.with_hops、hops.plan |
| 模块级 | 09 | _emit_label | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | ★ 边标签（判断节点的分支条件）——与 `render_html.svg_label` **同元素约定**： · L177 · 函数 · 分支：1→_fmt 2→_esc · ⇢ 依赖 engine.Engine.label_box |
| 模块级 | 10 | _emit_lanes | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | ★ 泳道底色：左走廊 + 部门列底色/表头 + 左侧里程碑带。 · L196 · 函数 · 分支：1→_fmt 2→_esc |
| 模块级 | 11 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→06｜5→07｜6→08｜7→10 | ★ DSL → 独立 `.svg`。成功返回 0（统一契约；`ctx` 本渲染器暂不用任何键）。 · L228 · 函数 · 分支：1→_fmt 2→_defs 3→_esc 4→_drillable 5→_emit_node 6→_emit_edge 7→_emit_lanes · ⇢ 依赖 engine.Engine.head_band、engine.Engine.height、engine.Engine.lanes、engine.load |
| 模块级 | 12 | main | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L252 · 函数 |
| 出口 | 13 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
