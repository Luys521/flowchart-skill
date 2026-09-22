---
id: selfboot-label
level: L1
parent: ../flowtable.md
---

# label.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→17｜3→18 | 流程起点（结构性节点，不是函数） · 入口：1→Labeler.__init__ 2→Labeler.invalidate 3→Labeler.label_rows |
| Labeler | 02 | Labeler.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L16 · 方法 |
| Labeler | 03 | Labeler._node_rects | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 徽章命中判定只要矩形列表（不带节点 id）。 · L24 · 方法 · ⇢ 依赖 geometry.RectCache._all_rects |
| Labeler | 04 | Labeler._point_at | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 按弧长比例 t∈[0,1] 取折线上的点，并返回所在线段下标。 · L30 · 方法 |
| Labeler | 05 | Labeler._padding | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L47 · 方法 |
| Labeler | 06 | Labeler._text_w | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L50 · 方法 · ⇢ 依赖 semantics.text_width |
| Labeler | 07 | Labeler._badge_w | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 一行文字时的徽章宽（向上吸 2×细格）。 · L54 · 方法 · 分支：1→Labeler._padding 2→Labeler._text_w · ⇢ 依赖 geometry.ceil_to |
| Labeler | 08 | Labeler._badge_h | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L58 · 方法 · ⇢ 依赖 geometry.ceil_to |
| Labeler | 09 | Labeler._pitch | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 竖线左右能给标签让出的横向预算 = **本图实际的通道档距**。 · L62 · 方法 · ⇢ 依赖 geometry.lane_step |
| Labeler | 10 | Labeler._rows_for | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07｜3→09 | ★ 这条边的标签排成哪几行：默认一行；**竖段上**且一行宽度超档距 ⇒ 折两排。 · L74 · 方法 · 分支：1→Labeler._text_w 2→Labeler._badge_w 3→Labeler._pitch |
| Labeler | 11 | Labeler._size | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→08 | ★ 徽章盒的 (宽, 高)：宽取最长那一行，高 = 行数 × 行高。 · L94 · 方法 · 分支：1→Labeler._padding 2→Labeler._text_w 3→Labeler._badge_h · ⇢ 依赖 geometry.ceil_to |
| Labeler | 12 | Labeler._box_at | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 取弧长比例 t 处的徽章盒（左上角 x,y,w,h），并沿自由轴吸到细格。 · L99 · 方法 · ⇢ 依赖 geometry.snap |
| Labeler | 13 | Labeler._hits | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L113 · 方法 |
| Labeler | 14 | Labeler._candidate_ts | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 候选弧长比例：中点优先，之后向两侧交替扩散。 · L120 · 方法 |
| Labeler | 15 | Labeler.label_box | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→10｜3→11｜4→12｜5→13｜6→14｜7→16 | ★ 徽章盒（左上角 x,y,w,h）：沿折线取第一个不压节点的候选比例，全压则回退中点。 · L128 · 方法 · 分支：1→Labeler._node_rects 2→Labeler._rows_for 3→Labeler._size 4→Labeler._box_at 5→Labeler._hits 6→Labeler._candidate_ts 7→Labeler._seg_at |
| Labeler | 16 | Labeler._seg_at | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 弧长比例 t 落在哪一段上 → `(a, b)` 两个端点。 · L149 · 方法 |
| Labeler | 17 | Labeler.invalidate | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 缓存全清：整流平（`head_band`）之后，**行数**和矩形一样会失效。 · L154 · 方法 |
| Labeler | 18 | Labeler.label_rows | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 这条边的徽章分几行、每行是什么（渲染器照它画）。没算过就先算一次盒。 · L165 · 方法 |
| 出口 | 19 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
