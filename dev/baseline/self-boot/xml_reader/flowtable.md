---
id: selfboot-xml_reader
level: L1
parent: ../flowtable.md
---

# xml_reader.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→26｜2→40 | 流程起点（结构性节点，不是函数） · 入口：1→geometry 2→main |
| 模块级 | 02 | _text | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 属性文本直取。ET.fromstring 已按 XML 规范解码过一次实体（&amp; → & 等）， · L36 · 函数 |
| 模块级 | 03 | _strip_html | 任务 | — | — | — | 脚本 | selfboot | — | →42 | L42 · 函数 |
| 模块级 | 04 | _label_text | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 节点/边标签 → 纯文本：<br> 先换空格，再剥标签，最后压空白 · L46 · 函数 · 分支：1→_text 2→_strip_html |
| 模块级 | 05 | _label_first_line | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 节点框内可见文字 → 第一行（= 节点名称）。 · L54 · 函数 · 分支：1→_text 2→_strip_html |
| 模块级 | 06 | _geom | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 取元素的 mxGeometry → (x, y, w, h)；缺失返回全 0 · L69 · 函数 |
| 模块级 | 07 | _style_type | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ style → 类型。端点符（胶囊/椭圆）分不出起止，返回待定标记，后续按入/出边判定。 · L85 · 函数 |
| 模块级 | 08 | _shape_of | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ style → 形状名（rounded / rhombus / ellipse）。几何自检按它判"端点落在哪条边界上"… · L100 · 函数 |
| 模块级 | 09 | _frac | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 从 style 取 `exitX=0.5` 这类端口比例；缺省或非数返回 None · L115 · 函数 |
| 模块级 | 10 | _num | 任务 | — | — | — | 脚本 | selfboot | — | →42 | L126 · 函数 |
| 模块级 | 11 | _median | 任务 | — | — | — | 脚本 | selfboot | — | →42 | L133 · 函数 |
| 模块级 | 12 | _node | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 节点字典。**语义列一律为空**——drawio 里不写它们（见 D-73），语义只住在《流程表》。 · L141 · 函数 |
| 模块级 | 13 | _native_nodes | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→07｜4→12 | ★ 自家格式节点：`<object>` 包裹的 `<mxCell>`。返回 (节点列表, 已认领 id 集合)。 · L159 · 函数 · 分支：1→_label_first_line 2→_geom 3→_style_type 4→_node |
| 模块级 | 14 | _external_nodes | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→07｜4→12 | ★ 外部标准格式节点：裸 `<mxCell vertex="1">`，跳过标题/图例/泳道底色等装饰元素。 · L191 · 函数 · 分支：1→_label_first_line 2→_geom 3→_style_type 4→_node |
| 模块级 | 15 | _parse_nodes | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→14 | ★ 解析节点：先 <object>（自有格式），再 <mxCell vertex=1>（外部标准格式） · L221 · 函数 · 分支：1→_native_nodes 2→_external_nodes |
| 模块级 | 16 | _lanes_bbox | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 泳道底色的外包盒（所有带 `flowchartSkillBg=1` 的单元格），没有则 None。 · L228 · 函数 |
| 模块级 | 17 | _band_width | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 左侧里程碑带宽度 = 所有 `x=0` 的 vertex 单元格里最宽的那个。 · L244 · 函数 |
| 模块级 | 18 | _parse_edges | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→09｜3→10 | L260 · 函数 · 分支：1→_label_text 2→_frac 3→_num |
| 模块级 | 19 | _finalize_types | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 端点符节点定起止（胶囊或椭圆，见 `_style_type`）： · L289 · 函数 |
| 模块级 | 20 | _cluster | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 把一维坐标聚成层：返回 {索引: 层号}（按坐标升序） · L314 · 函数 |
| 模块级 | 21 | assign_grid | 任务 | — | — | — | 脚本 | selfboot | — | 1→11｜2→20 | ★ 按中心坐标聚类推断 row/col 与列中心 col_x（容差：行 0.6×高中位数、列 0.9×宽中位数）。 · L326 · 函数 · 分支：1→_median 2→_cluster · ⇢ 依赖 geometry.snap |
| 模块级 | 22 | _root_model | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ XML 文本 → (mxGraphModel 元素, root 元素, 页数)。解析不了抛 ValueError（带原… · L357 · 函数 |
| 模块级 | 23 | _order_nodes_and_edges | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 外部图按几何从上到下、从左到右重排，自有图按原始顺序；并丢掉两端不存在的边。 · L391 · 函数 |
| 模块级 | 24 | read | 任务 | — | — | — | 脚本 | selfboot | — | 1→10｜2→15｜3→16｜4→17｜5→18｜6→19｜7→21｜8→22｜9→23 | ★ 解析 drawio XML → {title, nodes, edges, source, grid, pages}。… · L404 · 函数 · 分支：1→_num 2→_parse_nodes 3→_lanes_bbox 4→_band_width 5→_parse_edges 6→_finalize_types 7→assign_grid 8→_root_model 9→_order_nodes_and_edges |
| 模块级 | 25 | _frac_pt | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 端口比例 → 绝对坐标。drawio 的 exitX/exitY 是**外接矩形的比例**，缺省即边中点。 · L425 · 函数 |
| 模块级 | 26 | geometry | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 读回结果 → 几何表 {nodes: {id: {rect, shape}}, edges: [{from, to, … · L432 · 函数 |
| 模块级 | 27 | _brief_index | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 节点序号表 + 出边索引（摘要按文档顺序、分支按目标序号排）。 · L459 · 函数 |
| 模块级 | 28 | _brief_node_lines | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 一行一节点（判断/多分支缩进列出各分支）。 · L468 · 函数 |
| 模块级 | 29 | brief | 任务 | — | — | — | 脚本 | selfboot | — | 1→27｜2→28 | ★ AI/人可读的拓扑摘要：一行一节点，判断/多分支节点缩进列出各分支。 · L490 · 函数 · 分支：1→_brief_index 2→_brief_node_lines |
| 模块级 | 30 | _next_of | 任务 | — | — | — | 脚本 | selfboot | — | →42 | L514 · 函数 |
| 模块级 | 31 | _target_id | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 从「回 10 重编」「n2」这类文本里取出目标节点 id： · L523 · 函数 |
| 模块级 | 32 | _parse_next_cell | 任务 | — | — | — | 脚本 | selfboot | — | →31 | L537 · 函数 · ⇢ 依赖 semantics.split_branches |
| 模块级 | 33 | _diff_table_rows | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 现有流程表 → {节点id: {name, type, next}}。 · L551 · 函数 · ⇢ 依赖 flowtable.parse_table、flowtable.split_row_cells |
| 模块级 | 34 | _diff_added_removed | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ 新增 / 删除节点清单；新增的节点只有名称与连线，缺的语义列在这里点名。 · L567 · 函数 |
| 模块级 | 35 | _diff_changed | 任务 | — | — | — | 脚本 | selfboot | — | 1→30｜2→32 | ★ 共有节点的差异清单：名称、类型、分支走向——图里只有这三样可动（D-73）。 · L585 · 函数 · 分支：1→_next_of 2→_parse_next_cell |
| 模块级 | 36 | diff | 任务 | — | — | — | 脚本 | selfboot | — | 1→33｜2→34｜3→35 | ★ 读回结果 vs 现有流程表 → 差异清单 · L609 · 函数 · 分支：1→_diff_table_rows 2→_diff_added_removed 3→_diff_changed |
| 模块级 | 37 | _print_json | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ --json：输出结构化 JSON。 · L622 · 函数 |
| 模块级 | 38 | _print_grid | 任务 | — | — | — | 脚本 | selfboot | — | →42 | ★ --grid：输出坐标推断的 row/col。 · L627 · 函数 |
| 模块级 | 39 | _cmd_diff | 任务 | — | — | — | 脚本 | selfboot | — | →36 | ★ --diff：只报**结构差异**（拓扑层面的：节点/边/标签）。 · L634 · 函数 |
| 模块级 | 40 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→24｜2→29｜3→37｜4→38｜5→39 | L662 · 函数 · 分支：1→read 2→brief 3→_print_json 4→_print_grid 5→_cmd_diff |
| _geom | 41 | _geom.f | 任务 | — | — | — | 脚本 | selfboot | — | →42 | L77 · 嵌套函数 |
| 出口 | 42 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
