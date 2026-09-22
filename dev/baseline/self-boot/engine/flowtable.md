---
id: selfboot-engine
level: L1
parent: ../flowtable.md
---

# engine.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→13｜4→14｜5→15｜6→16｜7→17｜8→18｜9→19｜10→20｜11→21｜12→22｜13→23｜14→24｜15→25｜16→26｜17→27 | 流程起点（结构性节点，不是函数） · 入口：1→Model.__init__ 2→Engine.__init__ 3→Engine.width 4→Engine.rect 5→Engine.path 6→Engine.polarity 7→Engine.ports 8→Engine.label_box 9→Engine.label_rows 10→Engine.node_lines 11→Engine.route_text 12→Engine.legend_rect 13→Engine.legend_width 14→Engine.lanes 15→Engine.head_band 16→Engine.height 17→load |
| Model | 02 | Model.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →28 | L22 · 方法 |
| Engine | 03 | Engine.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→05 | ★ 组装引擎：建模型与语法 → 暴露旧 Layout 属性接口 → 按布局建栅格与布线器。 · L36 · 方法 · 分支：1→Engine._expose_attrs 2→Engine._build_layout |
| Engine | 04 | Engine._expose_attrs | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 直接暴露旧 Layout 的属性接口。 · L44 · 方法 |
| Engine | 05 | Engine._build_layout | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→11 | ★ 按布局建栅格与布线器：泳道走"探布 → 量走廊 → 定案"两趟，流程一趟到位。 · L52 · 方法 · 分支：1→Engine._build 2→Engine._reserve_left_corridor |
| Engine | 06 | Engine._release_router | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 把上一趟写进边对象的几何改写还回去，这一趟才是干净重解。 · L60 · 方法 · ⇢ 依赖 lane_router.LaneRouter.release |
| Engine | 07 | Engine._make_grid_router | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 按布局造栅格与布线器（泳道专属参数只在泳道模式下用）。 · L66 · 方法 |
| Engine | 08 | Engine._expose_grid_metrics | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 建标签器，并把吸附后的尺寸与列中心转发给渲染器。 · L75 · 方法 |
| Engine | 09 | Engine._build | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07｜3→08 | ★ 重建栅格与布线器。泳道要走"探布 → 量走廊 → 定案"两趟，流程一趟到位。 · L84 · 方法 · 分支：1→Engine._release_router 2→Engine._make_grid_router 3→Engine._expose_grid_metrics |
| Engine | 10 | Engine._corridor_users | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 数出探布时**真落进里程碑带**的边；结构已坏（列号越界 / 类型未知）时返回 None。 · L90 · 方法 |
| Engine | 11 | Engine._reserve_left_corridor | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→10 | ★ 左侧走廊的宽度**量**出来，不估（DECISIONS.md D-39）。 · L98 · 方法 · 分支：1→Engine._build 2→Engine._corridor_users · ⇢ 依赖 geometry.ceil_to |
| Engine | 12 | Engine._measure_edge_need | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 量出所有折线 x 的最大值；结构已坏（如列号越界 / 节点类型未知）时返回 None。 · L117 · 方法 |
| Engine | 13 | Engine.width | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 画布宽 = max(配置宽, 最外侧通道 + 边距)，吸附粗格。 · L127 · 方法 · ⇢ 依赖 geometry.ceil_to |
| Engine | 14 | Engine.rect | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L144 · 方法 |
| Engine | 15 | Engine.path | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L147 · 方法 |
| Engine | 16 | Engine.polarity | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L150 · 方法 |
| Engine | 17 | Engine.ports | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L153 · 方法 |
| Engine | 18 | Engine.label_box | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L156 · 方法 · ⇢ 依赖 label.Labeler.label_box |
| Engine | 19 | Engine.label_rows | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 边标签分几行、每行是什么（一行放不下时折两排，见 `label.py`）。 · L159 · 方法 · ⇢ 依赖 label.Labeler.label_rows |
| Engine | 20 | Engine.node_lines | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L163 · 方法 · ⇢ 依赖 semantics.Syntax.node_lines |
| Engine | 21 | Engine.route_text | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L166 · 方法 · ⇢ 依赖 semantics.Syntax.route_text |
| Engine | 22 | Engine.legend_rect | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L169 · 方法 |
| Engine | 23 | Engine.legend_width | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 标题/图例块的**宽**（画布顶部居中那块，默认 600）。 · L172 · 方法 |
| Engine | 24 | Engine.lanes | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 泳道背景信息；流程布局返回 None（渲染器据此决定画不画泳道带）。 · L180 · 方法 · ⇢ 依赖 swimlane.SwimGrid.lanes |
| Engine | 25 | Engine.head_band | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 画布顶部是否预留标题带（HTML 版标题在画布外，故不预留）。 · L185 · 方法 · ⇢ 依赖 label.Labeler.invalidate |
| Engine | 26 | Engine.height | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L199 · 方法 |
| 模块级 | 27 | load | 任务 | — | — | — | 脚本 | selfboot | — | →28 | ★ 加载 DSL(yaml) + 默认字典 → Engine。 · L203 · 函数 |
| 模块级 | 28 | _load_yaml | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L228 · 函数 |
| 出口 | 29 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
