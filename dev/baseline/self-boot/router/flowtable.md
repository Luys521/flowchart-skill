---
id: selfboot-router
level: L1
parent: ../flowtable.md
---

# router.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→29 | 流程起点（结构性节点，不是函数） · 入口：1→Router.__init__ 2→Router.polarity 3→Router._assign_group_dyes._rank |
| Router | 02 | Router.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →32 | L15 · 方法 |
| Router | 03 | Router.ports | 任务 | — | — | — | 脚本 | selfboot | — | →32 | L21 · 方法 |
| Router | 04 | Router.polarity | 任务 | — | — | — | 脚本 | selfboot | — | →32 | L25 · 方法 |
| Router | 05 | Router._dedup | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 去掉连续重复的退化折点（L 形候选的通道值=锚点 x 时首/尾会出现）。 · L30 · 方法 |
| Router | 06 | Router.path | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→05｜3→07｜4→27 | L38 · 方法 · 分支：1→Router.ports 2→Router._dedup 3→Router._resolve_channel_x 4→Router._ensure_gutters · ⇢ 依赖 geometry.snap |
| Router | 07 | Router._resolve_channel_x | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 定这条边要走的横向专用通道 x（已吸细格）；没有专用通道时返回 None。 · L57 · 方法 · ⇢ 依赖 geometry.snap |
| Router | 08 | Router._hs | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 边的竖直跨度（两水平段所在 y 的 min..max），供通道重叠判定。 · L70 · 方法 · ⇢ 依赖 geometry.Grid.anchor |
| Router | 09 | Router._halfw | 任务 | — | — | — | 脚本 | selfboot | — | →32 | L78 · 方法 |
| Router | 10 | Router._col_gap | 任务 | — | — | — | 脚本 | selfboot | — | →09 | ★ 第 c 列与其右邻列之间的空隙中心 x（两列节点边沿的中点）。 · L82 · 方法 |
| Router | 11 | Router._cross_adj | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 是否需要走相邻列之间的空隙：同行直线(horiz)除外。 · L87 · 方法 |
| Router | 12 | Router._anchor_taken | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ nid 的 side 端口（切向偏移 off）是否会被**其他边**占用——按显式字段或 kind 默认端口推。 · L95 · 方法 |
| Router | 13 | Router._alt_xs | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 以 start 为中心左右交替展开的候选 x（窄空隙里也能榨出多条通道）。 · L113 · 方法 |
| Router | 14 | Router._clean_l_cands | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 前向对角的干净 L 候选（右下=右出顶入、左下=底出右入）；端口被别的边占了就跳过。 · L121 · 方法 |
| Router | 15 | Router._cross_gap_cands | 任务 | — | — | — | 脚本 | selfboot | — | 1→10｜2→13 | ★ 列间通道候选（Z 形，L 走不通时的次选，折点取两列空隙中心）。 · L137 · 方法 · 分支：1→Router._col_gap 2→Router._alt_xs · ⇢ 依赖 geometry.snap |
| Router | 16 | Router._col_edge | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 第 col 列的**最外沿** → `(左沿, 右沿)`。没有节点时退回该列的配置中心。 · L145 · 方法 |
| Router | 17 | Router._right_family_cands | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 右族长跳候选：以本边涉及列中更靠右列的**右沿**为局部基准，只向外展开（D-91）。 · L157 · 方法 · ⇢ 依赖 geometry.snap |
| Router | 18 | Router._mirror_left_cands | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 左族：以本边涉及列的**左沿**为局部基准向左展开（D-92「臂」的另一半）。 · L165 · 方法 · ⇢ 依赖 geometry.snap |
| Router | 19 | Router._candidates | 任务 | — | — | — | 脚本 | selfboot | — | 1→11｜2→13｜3→14｜4→15｜5→17｜6→18 | ★ 按优先级返回候选 (exit, entry, x)：干净 L（前向对角）→ 列间通道 → 左通道（单列回路）→ 右通道… · L182 · 方法 · 分支：1→Router._cross_adj 2→Router._alt_xs 3→Router._clean_l_cands 4→Router._cross_gap_cands 5→Router._right_family_cands 6→Router._mirror_left_cands · ⇢ 依赖 geometry.RectCache._all_rects、geometry.snap |
| Router | 20 | Router._seg_hits_rects | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 轴向线段是否穿过某节点矩形。矩形**外扩** m 像素：通道与节点边沿至少留 m 的间隙。 · L233 · 方法 · ⇢ 依赖 geometry.RectCache._all_rects、geometry.seg_rect_hit |
| Router | 21 | Router._hsegs | 任务 | — | — | — | 脚本 | selfboot | — | →32 | L243 · 方法 |
| Router | 22 | Router._seg_crosses_own | 任务 | — | — | — | 脚本 | selfboot | — | →32 | ★ 折线是否横穿自身源/目标节点的**内部**（矩形内缩 m）。判据见 visual-spec 第 4 项。 · L247 · 方法 · ⇢ 依赖 geometry.seg_rect_hit |
| Router | 23 | Router._chan_conflict | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→20｜3→21｜4→22 | ★ 通道 ch 是否可用。四类约束，缺一条就出叠线或穿节点： · L254 · 方法 · 分支：1→Router._hs 2→Router._seg_hits_rects 3→Router._hsegs 4→Router._seg_crosses_own · ⇢ 依赖 geometry.Grid.anchor |
| Router | 24 | Router._replay_gutter_hints | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 把已落盘的通道提示（gapx/gutter/channel）用同一套冲突规则复检，过期的丢掉重规划。 · L284 · 方法 · ⇢ 依赖 geometry.snap |
| Router | 25 | Router._fallback_channel | 任务 | — | — | — | 脚本 | selfboot | — | 1→16｜2→23 | ★ 候选全冲突时的兜底：从本边局部右基准最后一档向外找不冲突通道；再失败只避已占通道。 · L320 · 方法 · 分支：1→Router._col_edge 2→Router._chan_conflict · ⇢ 依赖 geometry.snap |
| Router | 26 | Router._route_pending_edges | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→19｜3→23｜4→25 | ★ 给还没通道的 loop/jumpR 边按候选优先级择优分配通道，全冲突时向外兜底。 · L342 · 方法 · 分支：1→Router._hs 2→Router._candidates 3→Router._chan_conflict 4→Router._fallback_channel |
| Router | 27 | Router._ensure_gutters | 任务 | — | — | — | 脚本 | selfboot | — | 1→24｜2→26｜3→31 | ★ 一次性通道分配：跨相邻列走列间通道、单列回路走左、长跳走右；**跨度小的先排**（占内道）。 · L365 · 方法 · 分支：1→Router._replay_gutter_hints 2→Router._route_pending_edges 3→Router._stagger_target_dyes · ⇢ 依赖 geometry.stagger_source_anchors |
| Router | 28 | Router._assign_group_dyes | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→30 | ★ 给同一目标同一入口的一批入边在 ±avail 内错开入场 dye：近源先拿靠源一侧的槽位。 · L391 · 方法 · 分支：1→Router.ports 2→Router._side_used_slots · ⇢ 依赖 geometry.Grid.anchor、geometry.snap |
| Router | 29 | Router._assign_group_dyes._rank | 任务 | — | — | — | 脚本 | selfboot | — | →06 | L423 · 函数 |
| Router | 30 | Router._side_used_slots | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 该侧**出边**已占的锚点槽位（自动与手填都算）——入边错峰必须整片避开（见 `_assign_group_dyes`… · L442 · 方法 |
| Router | 31 | Router._stagger_target_dyes | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→28 | ★ 同一目标**同一入口**的入边：在 ±avail 内错开入场 dye，否则尾段会重合纠缠。 · L452 · 方法 · 分支：1→Router.ports 2→Router._assign_group_dyes · ⇢ 依赖 geometry.snap |
| 出口 | 32 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
