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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→13 | 流程起点（结构性节点，不是函数） · 入口：1→Labeler.__init__ 2→Labeler.label_vertical |
| Labeler | 02 | Labeler.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L16 · 方法 |
| Labeler | 03 | Labeler._node_rects | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 徽章命中判定只要矩形列表（不带节点 id）。 · L24 · 方法 · ⇢ 依赖 geometry.RectCache._all_rects |
| Labeler | 04 | Labeler._point_at | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 按弧长比例 t∈[0,1] 取折线上的点，并返回所在线段下标。 · L30 · 方法 |
| Labeler | 05 | Labeler._badge_w | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L46 · 方法 · ⇢ 依赖 geometry.ceil_to、semantics.text_width |
| Labeler | 06 | Labeler._badge_h | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L51 · 方法 · ⇢ 依赖 geometry.ceil_to |
| Labeler | 07 | Labeler._size | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 徽章盒的 (宽, 高)：竖排时宽高互换（文字转了 90°，沿线的"长"变成盒子的高）。 · L55 · 方法 · 分支：1→Labeler._badge_w 2→Labeler._badge_h |
| Labeler | 08 | Labeler._vert_at | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→05 | ★ 弧长比例 t 处的徽章要不要竖排：所在段是**竖段**，且段长容得下转过来的徽章。 · L60 · 方法 · 分支：1→Labeler._point_at 2→Labeler._badge_w |
| Labeler | 09 | Labeler._box_at | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 取弧长比例 t 处的徽章盒（左上角 x,y,w,h），并沿自由轴吸到细格。 · L75 · 方法 · ⇢ 依赖 geometry.snap |
| Labeler | 10 | Labeler._hits | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L89 · 方法 |
| Labeler | 11 | Labeler._candidate_ts | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 候选弧长比例：中点优先，之后向两侧交替扩散。 · L96 · 方法 |
| Labeler | 12 | Labeler.label_box | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→07｜3→08｜4→09｜5→10｜6→11 | ★ 徽章盒（左上角 x,y,w,h）：沿折线取第一个不压节点的候选比例，全压则回退中点。 · L104 · 方法 · 分支：1→Labeler._node_rects 2→Labeler._size 3→Labeler._vert_at 4→Labeler._box_at 5→Labeler._hits 6→Labeler._candidate_ts |
| Labeler | 13 | Labeler.label_vertical | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 这条边的徽章是不是跟竖线竖排（渲染器照它决定转不转文字）。没算过就先算一次盒。 · L125 · 方法 |
| 出口 | 14 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
