---
id: selfboot-swimlane
level: L1
parent: ../flowtable.md
---

# swimlane.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→04｜2→15｜3→16｜4→17｜5→19｜6→20｜7→21 | 流程起点（结构性节点，不是函数） · 入口：1→SwimGrid.__init__ 2→SwimGrid.set_head_band 3→SwimGrid.Y 4→SwimGrid.MID 5→SwimGrid.legend_rect 6→SwimGrid.rect 7→SwimGrid.lanes |
| 模块级 | 02 | _align_half | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 向上取到「≡ unit/2 (mod unit·2)」的最小值（unit=20 → 20/60/100…）。 · L11 · 函数 · ⇢ 依赖 geometry.ceil_to |
| 模块级 | 03 | lane_bands | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 泳道底图 → **纯数据**（几何 / 颜色 / 文字位置）：左走廊 + 部门列 + 阶段带。 · L262 · 函数 |
| SwimGrid | 04 | SwimGrid.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→07｜4→08｜5→09｜6→10｜7→11｜8→14 | ★ 建泳道栅格：读配置 → 吸附尺寸 → 定行列预算 → 算列宽与坐标 → 铺行名/泳道名。 · L24 · 方法 · 分支：1→SwimGrid._read_configs 2→SwimGrid._fit_sizes 3→SwimGrid._collect_cells 4→SwimGrid._solve_col_widths 5→SwimGrid._solve_row_heights 6→SwimGrid._solve_col_positions 7→SwimGrid._assign_lane_names 8→SwimGrid._build_rows |
| SwimGrid | 05 | SwimGrid._read_configs | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 读网格刻度与泳道参数（`grid` 段 + 顶层 `lane:` 段），定下与尺寸无关的配置字段。 · L37 · 方法 · ⇢ 依赖 geometry.snap |
| SwimGrid | 06 | SwimGrid._fit_sizes | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 把每个形状的宽高向上吸附到细格，并记录改动提示。 · L73 · 方法 · ⇢ 依赖 geometry.ceil_to |
| SwimGrid | 07 | SwimGrid._collect_cells | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 按 (行,列) 归集节点 id，并定出行数、列数与最大行号。 · L84 · 方法 |
| SwimGrid | 08 | SwimGrid._solve_col_widths | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 每列宽取该列最宽节点 + 左右各 pad，向上吸细格。 · L97 · 方法 · ⇢ 依赖 geometry.ceil_to |
| SwimGrid | 09 | SwimGrid._solve_row_heights | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→12 | ★ 每行高：槽位模式等距 pitch，阶段行模式按该行最厚摞 + 上下 vpad 取半格余数。 · L108 · 方法 · 分支：1→_align_half 2→SwimGrid._stack_h |
| SwimGrid | 10 | SwimGrid._solve_col_positions | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 从阶段带右侧起逐列推列中心 x，画布宽取整列宽之和与下限 400 的较大者。 · L124 · 方法 · ⇢ 依赖 geometry.ceil_to、geometry.snap |
| SwimGrid | 11 | SwimGrid._assign_lane_names | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 按显式列序先铺一遍空泳道名，再由节点覆盖成行阶段名与列主体名。 · L134 · 方法 |
| SwimGrid | 12 | SwimGrid._stack_h | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L146 · 方法 |
| SwimGrid | 13 | SwimGrid._snap_unit | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 该格摞顶对哪一级刻度负责：含矩形类节点 → 粗格（四边守粗格）；全是非矩形 → 细格。 · L149 · 方法 |
| SwimGrid | 14 | SwimGrid._build_rows | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→13 | ★ 按标题带 + 表头带 + 逐行高重算各行顶边 y（切换标题带后调用），并预算各格的**摞顶**。 · L162 · 方法 · 分支：1→SwimGrid._stack_h 2→SwimGrid._snap_unit · ⇢ 依赖 geometry.snap |
| SwimGrid | 15 | SwimGrid.set_head_band | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 开关画布顶部的标题带（同 `geometry.Grid.set_head_band`）。 · L197 · 方法 · ⇢ 依赖 geometry.snap |
| SwimGrid | 16 | SwimGrid.Y | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L203 · 方法 |
| SwimGrid | 17 | SwimGrid.MID | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 阶段行的参考 y（行垂直中心）。泳道下一行有多个节点，此值只作兜底。 · L206 · 方法 |
| SwimGrid | 18 | SwimGrid.height | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L210 · 方法 · ⇢ 依赖 geometry.ceil_to |
| SwimGrid | 19 | SwimGrid.legend_rect | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L213 · 方法 |
| SwimGrid | 20 | SwimGrid.rect | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L216 · 方法 |
| SwimGrid | 21 | SwimGrid.lanes | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→18 | ★ 泳道背景信息。流程模式的 `Grid` **没有**这个方法——渲染器据此判断该画哪种背景。 · L234 · 方法 · 分支：1→lane_bands 2→SwimGrid.height |
| 出口 | 22 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
