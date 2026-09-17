---
id: selfboot-lane_router
level: L1
parent: ../flowtable.md
---

# lane_router.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→10｜4→22｜5→32｜6→36 | 流程起点（结构性节点，不是函数） · 入口：1→LaneRouter.__init__ 2→LaneRouter.invalidate 3→LaneRouter._span 4→LaneRouter.polarity 5→LaneRouter.release 6→LaneRouter.path |
| LaneRouter | 02 | LaneRouter.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →37 | L35 · 方法 · ⇢ 依赖 geometry.stagger_source_anchors |
| LaneRouter | 03 | LaneRouter.invalidate | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 丢矩形缓存（父类）+ 折线解——切标题带会把整图 y 平移（D-19）， · L51 · 方法 |
| LaneRouter | 04 | LaneRouter._dir_ok | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 该段方向是否沿端口法线：出边朝外（点积>0）、入边朝内（点积<0）。 · L61 · 方法 |
| LaneRouter | 05 | LaneRouter._bad_ends | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 端点段不沿端口法线的条数（0/1/2）。 · L67 · 方法 |
| LaneRouter | 06 | LaneRouter._legs_ok | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 每一段都不短于一个粗格（`MIN_LEG × 细格` = 20px）。 · L87 · 方法 |
| LaneRouter | 07 | LaneRouter._hits | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 折线是否碰到无关节点（外扩 HIT_MARGIN 留间隙）。 · L96 · 方法 · ⇢ 依赖 geometry.RectCache._all_rects、geometry.seg_rect_hit |
| LaneRouter | 08 | LaneRouter._count_conflicts | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 数候选折线与其余各折线的共线重叠数、正交交叉数 → (重叠, 交叉)。 · L107 · 方法 · ⇢ 依赖 geometry.ortho_cross、geometry.seg_overlap |
| LaneRouter | 09 | LaneRouter._cost | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→08 | ★ 候选的代价（越小越好）。`others` 是其余边**当前**的折线列表。 · L120 · 方法 · 分支：1→LaneRouter._bad_ends 2→LaneRouter._count_conflicts |
| LaneRouter | 10 | LaneRouter._span | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 边的"跨度"（行差 + 列差）。长边最受约束，先路由。 · L133 · 方法 |
| LaneRouter | 11 | LaneRouter._chan_pts | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 给定左右族通道 x 与端口，拼出那条 Z 形折线。 · L138 · 方法 |
| LaneRouter | 12 | LaneRouter._far_cands | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 画布**最外侧**的远通道候选（所有节点左沿之外 / 右沿之外），分层排布。 · L145 · 方法 · ⇢ 依赖 geometry.snap |
| LaneRouter | 13 | LaneRouter._side_cands | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 贴列**侧沿**的通道候选（左右两侧都出，D-30）。 · L178 · 方法 · ⇢ 依赖 geometry.ceil_to、geometry.snap |
| LaneRouter | 14 | LaneRouter._diag_l_cands | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 回环也吃"顺路的对角 L"：目标在上 → 从顶顶点出去；在左 → 从右侧顶点接进。 · L205 · 方法 |
| LaneRouter | 15 | LaneRouter._direct_cands | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→13｜3→18｜4→19 | ★ 非回环边的直连候选：直线、对向端口的 Z 形、两条 L 形、行内空带绕行、同列贴沿/外缘。 · L231 · 方法 · 分支：1→LaneRouter._far_cands 2→LaneRouter._side_cands 3→LaneRouter._cands.add 4→LaneRouter._z_cands |
| LaneRouter | 16 | LaneRouter._prune_cands | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07 | ★ 硬约束筛选：先取"不穿无关节点且每段不短于一个粗格"的；没有再退一步只保证不穿节点。 · L268 · 方法 · 分支：1→LaneRouter._legs_ok 2→LaneRouter._hits |
| LaneRouter | 17 | LaneRouter._cands | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→13｜3→14｜4→15｜5→16 | ★ 这条边的**全部**候选（纯几何，不依赖别的边选了哪条）。 · L279 · 方法 · 分支：1→LaneRouter._far_cands 2→LaneRouter._side_cands 3→LaneRouter._diag_l_cands 4→LaneRouter._direct_cands 5→LaneRouter._prune_cands |
| LaneRouter | 18 | LaneRouter._cands.add | 任务 | — | — | — | 脚本 | selfboot | — | →37 | L293 · 函数 |
| LaneRouter | 19 | LaneRouter._z_cands | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 对向端口的 Z 形候选：两端沿端口法线进出，中段在两锚点之间折一次。 · L305 · 方法 · ⇢ 依赖 geometry.snap |
| LaneRouter | 20 | LaneRouter._row_blocked | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 同行的 a→b 是否**两条 L 形都走不通**（要绕空带）——那才值得换端口。 · L324 · 方法 · ⇢ 依赖 geometry.Grid.anchor |
| LaneRouter | 21 | LaneRouter.ports | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 端口按源与目标的相对位置选，**不能写死 bottom→top**——原因与后果见 swimlane-spec §4。 · L336 · 方法 |
| LaneRouter | 22 | LaneRouter.polarity | 任务 | — | — | — | 脚本 | selfboot | — | →37 | L358 · 方法 |
| LaneRouter | 23 | LaneRouter._spread_contended_ports | 任务 | — | — | — | 脚本 | selfboot | — | →21 | ★ 非矩形节点的同一侧挤了多条出边时，把多余的挪到**空着的垂直侧**去。 · L361 · 方法 |
| LaneRouter | 24 | LaneRouter._drop_orphan_offsets | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 清掉"成了孤儿"的错峰量，返回是否有改动。 · L396 · 方法 |
| LaneRouter | 25 | LaneRouter._others | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 其余边当前选择的折线（坐标下降里"固定不动"的那部分）。 · L422 · 方法 |
| LaneRouter | 26 | LaneRouter._pick | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→17｜3→25 | ★ 在候选里挑代价最低的（其余边固定为当前选择）。 · L426 · 方法 · 分支：1→LaneRouter._cost 2→LaneRouter._cands 3→LaneRouter._others |
| LaneRouter | 27 | LaneRouter._align_anchors | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 微折点消除：两锚点在端口**切向**只差 ≤1 细格时，把目标锚点对齐到源锚点。 · L434 · 方法 |
| LaneRouter | 28 | LaneRouter._greedy_seed | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 贪心初始解（1）：按跨度降序逐边取当前最优候选，长边最受约束、先占道。 · L459 · 方法 |
| LaneRouter | 29 | LaneRouter._descend | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→25｜3→26 | ★ 坐标下降（2）：每次只重选一条边、其余固定，仅接受代价严格下降的改动，不降即停。 · L465 · 方法 · 分支：1→LaneRouter._cost 2→LaneRouter._others 3→LaneRouter._pick |
| LaneRouter | 30 | LaneRouter._solve | 任务 | — | — | — | 脚本 | selfboot | — | 1→28｜2→29 | ★ 贪心初始解 + **坐标下降**，解写进 `self._choice`（输入是 `self._orig_ports`）。 · L479 · 方法 · 分支：1→LaneRouter._greedy_seed 2→LaneRouter._descend |
| LaneRouter | 31 | LaneRouter._commit | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 定案：写回端口与折线缓存。 · L486 · 方法 |
| LaneRouter | 32 | LaneRouter.release | 任务 | — | — | — | 脚本 | selfboot | — | →33 | ★ 把写进边对象的几何改写（端口 / `dye` / 被挪到空闲侧的端口 / **本趟自动设下的 `sdye`**）还回去。 · L497 · 方法 |
| LaneRouter | 33 | LaneRouter._reset | 任务 | — | — | — | 脚本 | selfboot | — | →37 | ★ 还原上一轮留下的端口改写与 dye 对齐（invalidate 后重解的前提）。 · L516 · 方法 |
| LaneRouter | 34 | LaneRouter._resolve_orphan_offsets | 任务 | — | — | — | 脚本 | selfboot | — | 1→21｜2→24｜3→30｜4→31 | ★ 端口定案后复查孤立偏移：有漂移就冻结端口、只让偏移归零，再干净重解一趟（D-31）。 · L540 · 方法 · 分支：1→LaneRouter.ports 2→LaneRouter._drop_orphan_offsets 3→LaneRouter._solve 4→LaneRouter._commit |
| LaneRouter | 35 | LaneRouter._pre_route | 任务 | — | — | — | 脚本 | selfboot | — | 1→21｜2→23｜3→27｜4→30｜5→31｜6→33｜7→34 | ★ 两步求解（D-30）：贪心初始解 + **坐标下降**；再清一遍"孤立偏移"重解（D-31）。 · L548 · 方法 · 分支：1→LaneRouter.ports 2→LaneRouter._spread_contended_ports 3→LaneRouter._align_anchors 4→LaneRouter._solve 5→LaneRouter._commit 6→LaneRouter._reset 7→LaneRouter._resolve_orphan_offsets |
| LaneRouter | 36 | LaneRouter.path | 任务 | — | — | — | 脚本 | selfboot | — | →35 | ★ 折线（定案后即缓存）。path 会被渲染器与 validate 反复调用，必须稳定同一条。 · L573 · 方法 |
| 出口 | 37 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
