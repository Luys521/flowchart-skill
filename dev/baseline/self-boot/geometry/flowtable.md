---
id: selfboot-geometry
level: L1
parent: ../flowtable.md
---

# geometry.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→11｜3→12｜4→13｜5→14｜6→15｜7→16｜8→17｜9→18｜10→19｜11→27｜12→28｜13→30｜14→31｜15→34 | 流程起点（结构性节点，不是函数） · 入口：1→arc_px 2→stagger_source_anchors 3→rects_overlap 4→seg_rect_hit 5→seg_overlap 6→ortho_cross 7→point_seg_dist 8→RectCache._all_rects 9→RectCache.invalidate 10→Grid.__init__ 11→Grid.set_head_band 12→Grid.Y 13→Grid.height 14→Grid.legend_rect 15→Grid.port_frac |
| 模块级 | 02 | arc_px | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 圆角半径（像素）：字典 `shapes.*.arc` 是 **drawio 口径的 `arcSize` 百分比**（见… · L12 · 函数 |
| 模块级 | 03 | snap | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 就近吸附到 unit 的倍数（.5 一律进位，避免 Python 银行家舍入造成来回抖动）。 · L31 · 函数 |
| 模块级 | 04 | ceil_to | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 向上吸附到 unit 的倍数（宁可大不可小，避免越吸附越挤）。 · L36 · 函数 |
| 模块级 | 05 | _fit_one | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 吸附到「≡ residue (mod cycle)」且 ≥ v 的最小值。 · L41 · 函数 |
| 模块级 | 06 | fit_size | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ 把形状尺寸吸附到"四边都落格"的合法值，返回 (w, h, 是否改动)；cycle 由调用方给。 · L47 · 函数 |
| 模块级 | 07 | fit_base_height | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 行基线高吸附到 20 mod 40 → 中线落在 20k+10 上。 · L57 · 函数 |
| 模块级 | 08 | _group_outs_by_side | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 把一组出边按**出边所在的侧**分组 → `{侧: [出边, …]}`。 · L265 · 函数 |
| 模块级 | 09 | _place_offset | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 给一条出边挑一个不被占用的错峰量写进 `sdye`，并登记到 `taken` / `touched`。 · L278 · 函数 |
| 模块级 | 10 | _first_leg | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 一条出边的**首段长度**：锚点 → 通道折点的那一段（没有折点则 0）。 · L321 · 函数 |
| 模块级 | 11 | stagger_source_anchors | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09｜3→10 | ★ 出边与入边用同一侧时，锚点会重合 → 出边首段把入边末段**原路画回来**（DECISIONS.md D-15）。 · L335 · 函数 · 分支：1→_group_outs_by_side 2→_place_offset 3→_first_leg |
| 模块级 | 12 | rects_overlap | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 两个矩形是否相交（边贴边不算）。 · L382 · 函数 |
| 模块级 | 13 | seg_rect_hit | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 线段与矩形是否相交。`grow>0` 外扩（留安全间隙）、`grow<0` 内缩（判"穿进内部"）。 · L388 · 函数 |
| 模块级 | 14 | seg_overlap | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 两条轴对齐线段是否**共线重叠**（只认重叠，不认正交穿越）。 · L405 · 函数 |
| 模块级 | 15 | ortho_cross | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 两条轴对齐线段是否**正交交叉**（一横一竖、且交点在两者内部）。 · L421 · 函数 |
| 模块级 | 16 | point_seg_dist | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 点到线段的最短距离。 · L440 · 函数 |
| RectCache | 17 | RectCache._all_rects | 任务 | — | — | — | 脚本 | selfboot | — | →35 | L70 · 方法 |
| RectCache | 18 | RectCache.invalidate | 任务 | — | — | — | 脚本 | selfboot | — | →35 | L75 · 方法 |
| Grid | 19 | Grid.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | 1→20｜2→21｜3→22｜4→23｜5→24｜6→25 | ★ 建流程栅格：读网格与画布配置 → 解列中心 → 解原点与行距 → 吸附尺寸 → 定右通道 → 推行 y。 · L80 · 方法 · 分支：1→Grid._read_base_config 2→Grid._solve_columns 3→Grid._solve_origin_and_gaps 4→Grid._fit_sizes 5→Grid._solve_right_channel 6→Grid._solve_rows |
| Grid | 20 | Grid._read_base_config | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | ★ 读网格刻度与画布宽（未声明则走字典默认），建出最基础的字段与自检提示载体。 · L90 · 方法 · 分支：1→snap 2→ceil_to |
| Grid | 21 | Grid._solve_columns | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 定各列中心 x（声明 col_x 则照用、否则按 col_pitch 展开）并记录吸附提示。 · L106 · 方法 |
| Grid | 22 | Grid._solve_origin_and_gaps | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 定原点 y、标题带高与满/缩两档行间距（全部吸附）。 · L124 · 方法 |
| Grid | 23 | Grid._fit_sizes | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07 | ★ 先算中线/列心余数，再把每个形状的宽高吸附到「四边都落格」的合法值。 · L140 · 方法 · 分支：1→fit_size 2→fit_base_height |
| Grid | 24 | Grid._solve_right_channel | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 定右通道 x：声明则照用，否则取最右列中心 + 右通道偏移。 · L159 · 方法 |
| Grid | 25 | Grid._solve_rows | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 推行顶边 y 与满间距行集合：相邻行主干带标签则走满间距。 · L169 · 方法 |
| Grid | 26 | Grid._build_rows | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 按 origin_y 与逐行间距重算各行顶边 y（切换标题带后调用）。 · L187 · 方法 |
| Grid | 27 | Grid.set_head_band | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→26 | ★ 开关画布顶部的标题带（HTML 版标题在画布外故不预留，drawio 版留在画布内）。 · L194 · 方法 · 分支：1→snap 2→Grid._build_rows |
| Grid | 28 | Grid.Y | 任务 | — | — | — | 脚本 | selfboot | — | →35 | L203 · 方法 |
| Grid | 29 | Grid.MID | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 行中线（所有节点共用一条，落在 20k+10 上——网格规范见 visual-spec §0）。 · L206 · 方法 |
| Grid | 30 | Grid.height | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→29 | L210 · 方法 · 分支：1→ceil_to 2→Grid.MID |
| Grid | 31 | Grid.legend_rect | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 图例带：画布顶部 (0, 0, width, legend_h)，legend_h=0 表示关闭。 · L213 · 方法 |
| Grid | 32 | Grid.rect | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L219 · 方法 |
| Grid | 33 | Grid.anchor | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→32 | ★ 端口锚点。`off` 是**沿这条边的切向**错位量（见 DECISIONS.md D-15/D-17）： · L224 · 方法 · 分支：1→snap 2→Grid.rect |
| Grid | 34 | Grid.port_frac | 任务 | — | — | — | 脚本 | selfboot | — | 1→32｜2→33 | ★ 端口的 (fractionX, fractionY)——drawio 用**外接矩形的比例**表示端口位置。 · L254 · 方法 · 分支：1→Grid.rect 2→Grid.anchor |
| 出口 | 35 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
