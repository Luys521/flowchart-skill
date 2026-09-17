---
id: selfboot-validate
level: L1
parent: ../flowtable.md
---

# validate.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→34｜2→36｜3→37｜4→38｜5→39 | 流程起点（结构性节点，不是函数） · 入口：1→cli 2→_ArtifactL.__init__ 3→_ArtifactL.rect 4→_ArtifactL.path 5→_ArtifactL.height |
| 模块级 | 02 | check_refs | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 1. 引用完整：端点存在、端口合法、列号与类型在字典范围内。 · L31 · 函数 · ⇢ 依赖 engine.Engine.ports |
| 模块级 | 03 | check_overlap | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 2. 节点互不重叠 · L64 · 函数 · ⇢ 依赖 geometry.rects_overlap |
| 模块级 | 04 | check_edge_through_nodes | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 3. 边不穿过无关节点（矩形内缩 2px：贴边不算穿） · L77 · 函数 · ⇢ 依赖 geometry.seg_rect_hit |
| 模块级 | 05 | _on_border | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 点是否落在该形状的**可视边界**上。 · L93 · 函数 |
| 模块级 | 06 | _seg_in_shape | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 折线是否穿进该形状的**内部**（按形状判，`margin` 向内收）。 · L119 · 函数 |
| 模块级 | 07 | check_edge_own_nodes | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 4. 边的**端点必须落在源/目标节点的边框上**，且不横穿该节点内部（内缩 6px）。 · L147 · 函数 · 分支：1→_on_border 2→_seg_in_shape · ⇢ 依赖 geometry.seg_rect_hit |
| 模块级 | 08 | _segment_paths | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 每条边的折线 → 线段列表（相邻折点成段），供两两比对。 · L192 · 函数 |
| 模块级 | 09 | _edge_overlap_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 两两共线重叠的边（共享端点的分叉/合流豁免）→ 错误列表。 · L197 · 函数 · ⇢ 依赖 geometry.seg_overlap |
| 模块级 | 10 | _edge_uturn_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 出边把入边末段原路画回来的「掉头折返」→ 错误列表（DECISIONS.md D-15）。 · L216 · 函数 · ⇢ 依赖 geometry.seg_overlap |
| 模块级 | 11 | check_edge_overlap | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09｜3→10 | ★ 5. 边不重叠（允许正交交叉、允许共享端点的出/入段）。 · L243 · 函数 · 分支：1→_segment_paths 2→_edge_overlap_errors 3→_edge_uturn_errors |
| 模块级 | 12 | _label_box_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 逐边标签盒：中心压线 / 不压节点 / 不越界 → (错误列表, 标签盒清单)。 · L252 · 函数 · ⇢ 依赖 geometry.point_seg_dist、geometry.rects_overlap |
| 模块级 | 13 | _label_pair_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 两个标签盒互相重叠 → 错误列表。 · L276 · 函数 · ⇢ 依赖 geometry.rects_overlap |
| 模块级 | 14 | check_labels | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→13 | ★ 6. 标签：中心压线（距所属折线 < 6px）、不压节点、不越界、不压别的标签。 · L289 · 函数 · 分支：1→_label_box_errors 2→_label_pair_errors |
| 模块级 | 15 | check_grid | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 8. 网格对齐：矩形类节点四边守粗格，非矩形格位与折点/通道/标签盒守细格 · L298 · 函数 |
| 模块级 | 16 | check_canvas | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 7. 画布内 · L330 · 函数 |
| 模块级 | 17 | _run_geometry_checks | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→07｜4→11｜5→14｜6→15｜7→16 | ★ 按依赖顺序跑七项几何检查（引用已验通过）→ 错误列表。 · L350 · 函数 · 分支：1→check_overlap 2→check_edge_through_nodes 3→check_edge_own_nodes 4→check_edge_overlap 5→check_labels 6→check_grid 7→check_canvas · ⇢ 依赖 engine.Engine.rect |
| 模块级 | 18 | check | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→17 | ★ 八项检查 → (errors, notes)。纯函数：不打印、不退出，便于被其他脚本复用。 · L359 · 函数 · 分支：1→check_refs 2→_run_geometry_checks |
| 模块级 | 19 | _artifact_lane_expected | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 这份产物该不该有泳道底图：**调用方知道就照它判**，不知道（None）才按产物自称判。 · L414 · 函数 |
| 模块级 | 20 | _artifact_band_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 泳道左侧里程碑带：**必须存在**（没带＝底图没画），且折点不得落进标注区。 · L429 · 函数 |
| 模块级 | 21 | _artifact_short_segment_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 每段至少一格粗格：更短就是"微残段"，转角挤在箭头上（D-40）。 · L445 · 函数 |
| 模块级 | 22 | _artifact_lane_errors | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 泳道底色**必须存在**，且必须盖住所有节点：没盖住就是"底图没铺满"（D-41）。 · L459 · 函数 |
| 模块级 | 23 | check_artifact | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→07｜4→11｜5→15｜6→16｜7→19｜8→20｜9→21｜10→22 | ★ 对**产物里真实写下的坐标**跑一遍几何门禁 → 错误列表（空 = 逐项通过）。 · L476 · 函数 · 分支：1→check_overlap 2→check_edge_through_nodes 3→check_edge_own_nodes 4→check_edge_overlap 5→check_grid 6→check_canvas 7→_artifact_lane_expected 8→_artifact_band_errors 9→_artifact_short_segment_errors 10→_artifact_lane_errors |
| 模块级 | 24 | _side_ports | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 可接端点：四条边的中点。菱形/椭圆的上下左右顶点与矩形边中点重合，故共用一套。 · L504 · 函数 |
| 模块级 | 25 | geometry_table | 任务 | — | — | — | 脚本 | selfboot | — | 1→24｜2→40 | ★ 几何表：节点（中心 / 尺寸 / 形状 / 可接端点）+ 边（起点 / 终点 / 端口比例 / 折线）。 · L510 · 函数 · 分支：1→_side_ports 2→geometry_table.r |
| 模块级 | 26 | _write_geometry_dump | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ --dump：把几何表写成 JSON；写不出去返回 1，成功返回 None。 · L541 · 函数 |
| 模块级 | 27 | artifact_main | 任务 | — | — | — | 脚本 | selfboot | — | 1→23｜2→26 | ★ 读产物 → 几何表 → 复核。`--artifact` 的入口。 · L554 · 函数 · 分支：1→check_artifact 2→_write_geometry_dump · ⇢ 依赖 manifest.artifact_geometry |
| 模块级 | 28 | report | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L577 · 函数 · ⇢ 依赖 engine.Engine.height |
| 模块级 | 29 | structured | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ 报错列表 → 结构化回执（D-55）：subject/fix 供 AI 修复循环直接消费。 · L596 · 函数 · ⇢ 依赖 semantics.findings_receipt |
| 模块级 | 30 | _showcase_blocks | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ showcase 档门禁：网格吸附提示非零即阻断（D-55）；应阻断时返回 True。 · L601 · 函数 |
| 模块级 | 31 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→18｜2→28｜3→30 | ★ 供 build.py / sync.py 调用：加载 → 检查 → 打印 → 退出码。 · L610 · 函数 · 分支：1→check 2→report 3→_showcase_blocks · ⇢ 依赖 engine.load |
| 模块级 | 32 | _cli_parser | 任务 | — | — | — | 脚本 | selfboot | — | →41 | ★ cli 的 argparse 定义（模型侧门禁 / 产物几何自检）。 · L619 · 函数 |
| 模块级 | 33 | _cli_json | 任务 | — | — | — | 脚本 | selfboot | — | 1→18｜2→29 | ★ --json：结构化结果（message/subject/fix，见 D-55）→ 退出码。 · L633 · 函数 · 分支：1→check 2→structured · ⇢ 依赖 engine.load |
| 模块级 | 34 | cli | 任务 | — | — | — | 脚本 | selfboot | — | 1→27｜2→31｜3→32｜4→33 | ★ 命令行入口。**必须显式给路径**——缺参数时绝不能退回校验某个样例并报"全部通过"， · L642 · 函数 · 分支：1→artifact_main 2→main 3→_cli_parser 4→_cli_json |
| check_grid | 35 | check_grid.chk | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L305 · 嵌套函数 |
| _ArtifactL | 36 | _ArtifactL.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L389 · 方法 |
| _ArtifactL | 37 | _ArtifactL.rect | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L404 · 方法 |
| _ArtifactL | 38 | _ArtifactL.path | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L407 · 方法 |
| _ArtifactL | 39 | _ArtifactL.height | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L410 · 方法 |
| geometry_table | 40 | geometry_table.r | 任务 | — | — | — | 脚本 | selfboot | — | →41 | L517 · 嵌套函数 |
| 出口 | 41 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
