---
id: selfboot-manifest
level: L1
parent: ../flowtable.md
---

# manifest.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→17｜2→18｜3→20｜4→23｜5→30 | 流程起点（结构性节点，不是函数） · 入口：1→read_svg 2→geometry_from_svg 3→artifact_geometry 4→source_stale 5→main |
| 模块级 | 02 | manifest_path_for | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 契约文件与 DSL 同名同目录（flow.yaml → flow.manifest.json）。 · L31 · 函数 |
| 模块级 | 03 | dsl_fingerprint | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ DSL 文件指纹，用来判断"契约是否已过期"。 · L40 · 函数 |
| 模块级 | 04 | source_fingerprint | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 《流程表》指纹：答"事实源自上次渲染后动过没有"。 · L48 · 函数 |
| 模块级 | 05 | _manifest_counts | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 契约计数：节点 / 边 / 按类型 / 带标签边 / 回路 / 待定节点。 · L58 · 函数 · ⇢ 依赖 semantics.is_pending |
| 模块级 | 06 | build | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ DSL → 契约清单。字段都是**可逐项比对**的，不是只给个总数。 · L72 · 函数 |
| 模块级 | 07 | _main_slice | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 多视图单文件（D-52）时只取**主视图**那一段再反解。 · L89 · 函数 |
| 模块级 | 08 | read_html | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 从 flow.html 反解 (节点 id 列表, 边列表)（返回列表而非集合，否则平行边的重数被吞）。 · L104 · 函数 |
| 模块级 | 09 | _default_shapes | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 随包字典里的 `shapes`（type → {shape, …}）——形状反查的唯一依据。 · L120 · 函数 |
| 模块级 | 10 | _compare_shapes | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→13 | ★ 契约里的**类型数量** ←→ 产物里真正画出来的**形状数量**（形状从产物读，见 D-32）。 · L133 · 函数 · 分支：1→_default_shapes 2→_html_nodes |
| 模块级 | 11 | read_drawio | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 从 flow.drawio 反解 (节点 id 列表, 边列表)。复用 xml_reader——它已经会跳过标题/图例… · L163 · 函数 · ⇢ 依赖 xml_reader.read |
| 模块级 | 12 | _html_shape | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 节点组内的形状元素 → (w, h, shape)。形状**从产物读**，不从字典反查类型再映射。 · L173 · 函数 |
| 模块级 | 13 | _html_nodes | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 主视图的节点组 → {id: {rect, shape}}（属性顺序与个数都不假定）。 · L195 · 函数 |
| 模块级 | 14 | _html_edges | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 主视图的边 path → [{from, to, pts}]。 · L215 · 函数 |
| 模块级 | 15 | _html_canvas_bands | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 画布尺寸（viewBox，缺失则按节点外包盒）+ 里程碑带宽 + 泳道底色外包盒。 · L224 · 函数 |
| 模块级 | 16 | geometry_from_html | 任务 | — | — | — | 脚本 | selfboot | — | 1→07｜2→13｜3→14｜4→15 | ★ 从 flow.html 反解几何：节点组（`translate` 中心 + 形状局部尺寸）+ 边的 `d` 折线。 · L245 · 函数 · 分支：1→_main_slice 2→_html_nodes 3→_html_edges 4→_html_canvas_bands |
| 模块级 | 17 | read_svg | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 从 `<流程名>-flow.svg` 反解 (节点 id 列表, 边列表)。 · L258 · 函数 |
| 模块级 | 18 | geometry_from_svg | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 从 `<流程名>-flow.svg` 反解几何。与 `geometry_from_html` 同源（元素约定相同）。 · L268 · 函数 |
| 模块级 | 19 | geometry_from_drawio | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 从 `.drawio` 反解几何。与 `geometry_from_html` 并列——两者都是"产物 → 几何表"的… · L273 · 函数 · ⇢ 依赖 xml_reader.geometry、xml_reader.read |
| 模块级 | 20 | artifact_geometry | 任务 | — | — | — | 脚本 | selfboot | — | 1→16｜2→19 | ★ 产物路径 → 几何表（按扩展名分流）。几何门禁的唯一入口。 · L283 · 函数 · 分支：1→geometry_from_html 2→geometry_from_drawio |
| 模块级 | 21 | _external_refs | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 产物自包含硬检查（D-55，借鉴 byai 的 HAS_EXTERNAL）：单文件交付（D-52）承诺离线可开， · L304 · 函数 |
| 模块级 | 22 | _stale_manifest_error | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 契约新鲜度：给了 yaml_path 就先验指纹，过期返回错误列表（否则空列表）。 · L321 · 函数 |
| 模块级 | 23 | source_stale | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 《流程表》自上次渲染后是否被直改过 → `(state, 说明)`。 · L332 · 函数 |
| 模块级 | 24 | _compare_ids_edges | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 一份产物的节点/边集合 vs 契约 → 错误列表。 · L354 · 函数 |
| 模块级 | 25 | check | 任务 | — | — | — | 脚本 | selfboot | — | 1→07｜2→08｜3→10｜4→11｜5→21｜6→22｜7→24 | ★ 契约 vs 产物 → 错误列表（空 = 逐项一致）。 · L374 · 函数 · 分支：1→_main_slice 2→read_html 3→_compare_shapes 4→read_drawio 5→_external_refs 6→_stale_manifest_error 7→_compare_ids_edges |
| 模块级 | 26 | summary | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ 一行人可读的统计，供 build 打印。 · L411 · 函数 |
| 模块级 | 27 | _manifest_parser | 任务 | — | — | — | 脚本 | selfboot | — | →31 | ★ manifest 的 argparse 定义（build / check 两个子命令）。 · L428 · 函数 |
| 模块级 | 28 | _run_build | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→06｜4→26 | ★ build 子命令：DSL → manifest.json。 · L443 · 函数 · 分支：1→manifest_path_for 2→dsl_fingerprint 3→build 4→summary · ⇢ 依赖 deps.hint |
| 模块级 | 29 | _run_check | 任务 | — | — | — | 脚本 | selfboot | — | 1→25｜2→26 | ★ check 子命令：manifest.json vs 产物。 · L458 · 函数 · 分支：1→check 2→summary |
| 模块级 | 30 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→27｜2→28｜3→29 | L472 · 函数 · 分支：1→_manifest_parser 2→_run_build 3→_run_check |
| 出口 | 31 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
