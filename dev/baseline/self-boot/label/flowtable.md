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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→10 | 流程起点（结构性节点，不是函数） · 入口：1→Labeler.__init__ 2→Labeler.label_box |
| Labeler | 02 | Labeler.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L12 · 方法 |
| Labeler | 03 | Labeler._node_rects | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 徽章命中判定只要矩形列表（不带节点 id）。 · L19 · 方法 · ⇢ 依赖 geometry.RectCache._all_rects |
| Labeler | 04 | Labeler._point_at | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 按弧长比例 t∈[0,1] 取折线上的点，并返回所在线段下标。 · L25 · 方法 |
| Labeler | 05 | Labeler._badge_w | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L41 · 方法 · ⇢ 依赖 geometry.ceil_to、semantics.text_width |
| Labeler | 06 | Labeler._badge_h | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L46 · 方法 · ⇢ 依赖 geometry.ceil_to |
| Labeler | 07 | Labeler._box_at | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 取弧长比例 t 处的徽章盒（左上角 x,y,w,h），并沿自由轴吸到细格。 · L50 · 方法 · ⇢ 依赖 geometry.snap |
| Labeler | 08 | Labeler._hits | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L64 · 方法 |
| Labeler | 09 | Labeler._candidate_ts | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 候选弧长比例：中点优先，之后向两侧交替扩散。 · L71 · 方法 |
| Labeler | 10 | Labeler.label_box | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→05｜3→06｜4→07｜5→08｜6→09 | ★ 徽章盒（左上角 x,y,w,h）：沿折线取第一个不压节点的候选比例，全压则回退中点。 · L79 · 方法 · 分支：1→Labeler._node_rects 2→Labeler._badge_w 3→Labeler._badge_h 4→Labeler._box_at 5→Labeler._hits 6→Labeler._candidate_ts |
| 出口 | 11 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
