---
id: selfboot-render_drawio
level: L1
parent: ../flowtable.md
---

# render_drawio.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→26 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | esc | 任务 | — | — | — | 脚本 | selfboot | — | →27 | L25 · 函数 |
| 模块级 | 03 | attr | 任务 | — | — | — | 脚本 | selfboot | — | →02 | L33 · 函数 |
| 模块级 | 04 | label_html | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 节点标签 HTML：名称粗体 / 执行者灰 / 行动所需时间橙 · L37 · 函数 · ⇢ 依赖 engine.Engine.node_lines |
| 模块级 | 05 | shape_style | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 形状段——**三种形状的唯一出处**（节点本体与子流程叠影共用，别各写一份）。 · L49 · 函数 |
| 模块级 | 06 | _stroke_of | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 节点的描边色与线型 —— **⚠ 两档的唯一出处**（节点本体与叠影卡共用，别各算一份）。 · L62 · 函数 · ⇢ 依赖 semantics.pending_style |
| 模块级 | 07 | node_style | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | L74 · 函数 · 分支：1→shape_style 2→_stroke_of |
| 模块级 | 08 | sub_ring_style | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 内衬线的 style（见 D-78）：同形状、**无填充**、1px、55% 不透明，落在节点框内。 · L87 · 函数 · 分支：1→shape_style 2→_stroke_of |
| 模块级 | 09 | sub_ring_xml | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→08 | ★ 内衬线 cell：同形状、向内缩 SUB_INSET（几何与 html/svg 同一口径）。 · L99 · 函数 · 分支：1→esc 2→sub_ring_style · ⇢ 依赖 engine.Engine.rect |
| 模块级 | 10 | edge_style | 任务 | — | — | — | 脚本 | selfboot | — | →27 | L109 · 函数 · ⇢ 依赖 engine.Engine.label_vertical、engine.Engine.polarity、engine.Engine.ports、hops.plan |
| 模块级 | 11 | node_xml | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→07｜5→09 | ★ 节点 → `<object>`（可下钻时**前面再压一张背面卡**，见 D-75）。`sub_pages` 是 {ni… · L145 · 函数 · 分支：1→esc 2→attr 3→label_html 4→node_style 5→sub_ring_xml · ⇢ 依赖 engine.Engine.rect |
| 模块级 | 12 | edge_xml | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→10 | L175 · 函数 · 分支：1→esc 2→attr 3→edge_style · ⇢ 依赖 engine.Engine.path |
| 模块级 | 13 | lane_cells | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 泳道背景：顶部部门表头 + 角标 + 左侧阶段带 + 部门列底色。 · L196 · 函数 · ⇢ 依赖 engine.Engine.height |
| 模块级 | 14 | render | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ DSL → `.drawio`。`ctx['pages']` 是 [(page_id, page_name, dsl_… · L247 · 函数 |
| 模块级 | 15 | _page_xml | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→16｜3→17｜4→18｜5→19｜6→20｜7→22 | ★ 渲染**一页**（含它自己的子页），返回 (xml 全文, 节点数, 边数, 画布宽, 画布高)。 · L272 · 函数 · 分支：1→lane_cells 2→_build_title_cell 3→_collect_node_cells 4→_collect_edge_cells 5→_wrap_diagram 6→_collect_sub_diagrams 7→_sub_pages · ⇢ 依赖 engine.Engine.height、engine.Engine.lanes、engine.load |
| 模块级 | 16 | _build_title_cell | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 装配「标题 + 图例说明」cell（合成一个，拖动时标题与图例不会互相错位）。 · L310 · 函数 · 分支：1→esc 2→attr · ⇢ 依赖 engine.Engine.legend_rect、engine.Engine.legend_width |
| 模块级 | 17 | _collect_node_cells | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 按 DSL 节点顺序生成每个节点的 `<object>` cell。 · L335 · 函数 |
| 模块级 | 18 | _collect_edge_cells | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 生成每条边的 cell；边 id 与节点/结构 id 共用命名空间，撞名则加后缀避让。 · L340 · 函数 |
| 模块级 | 19 | _wrap_diagram | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 把 cells 包进 `<diagram>` / `<mxGraphModel>` / `<root>` 外壳。 · L358 · 函数 · 分支：1→esc 2→attr |
| 模块级 | 20 | _collect_sub_diagrams | 任务 | — | — | — | 脚本 | selfboot | — | →21 | ★ 递归渲染并拼接各子页的 `<diagram>` 段（本页之后，保持 pages 顺序）。 · L368 · 函数 |
| 拆环 | 21 | 再入？ | 判断 | — | — | — | 脚本 | selfboot | — | 是→15｜否→27 | 结构性判断（拆环）：_page_xml→_collect_sub_diagrams→_page_xml 是互调。是 → 继续下一层（_page_xml）；否 → 收尾（结束）。 |
| 模块级 | 22 | _sub_pages | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 本页里可下钻的节点 → {nid: page_id}。键是 **dsl 路径**（`discover_pages` 产… · L382 · 函数 · ⇢ 依赖 artifact.artifact_rel、semantics.subflow_target |
| 模块级 | 23 | page_id_for | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 子表 dsl 的**相对路径** → 稳定的页 id（内容无关的固定规则，父子两侧算得一样）。 · L405 · 函数 |
| 模块级 | 24 | _rel_to | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ target 相对 base 的 posix 路径；算不出（跨盘/越界）就退回绝对路径。 · L418 · 函数 |
| 模块级 | 25 | discover_pages | 任务 | — | — | — | 脚本 | selfboot | — | 1→23｜2→24 | ★ 从本表出发，顺着 `▣` 找出**直接子表** → [(page_id, 页名, 子表 dsl 路径), …]。 · L432 · 函数 · 分支：1→page_id_for 2→_rel_to · ⇢ 依赖 artifact.artifact_rel、engine.load、semantics.subflow_target |
| 模块级 | 26 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→14｜2→25 | L479 · 函数 · 分支：1→render 2→discover_pages |
| 出口 | 27 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
