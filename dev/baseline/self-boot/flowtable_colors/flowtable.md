---
id: selfboot-flowtable_colors
level: L1
parent: ../flowtable.md
---

# flowtable_colors.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→05｜2→09 | 流程起点（结构性节点，不是函数） · 入口：1→resolve_colors 2→subject_map |
| 模块级 | 02 | _next_free | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 从色板里取**第一个还没被占用**的颜色。 · L32 · 函数 |
| 模块级 | 03 | _color_map | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 「主体配色」表解析出的 {主体: hex} → ({主体: {'fill','stroke'}}, errs)（D-5… · L46 · 函数 |
| 模块级 | 04 | _inherit_colors | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 沿父表链向上找**第一个**声明了配色的祖先 → (祖先映射, 祖先 Path)（找不到返回 ({}, None)）。 · L73 · 函数 · ⇢ 依赖 flowtable.find_parent_table、flowtable.parse_table |
| 模块级 | 05 | resolve_colors | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | ★ 本表声明 + 向上继承 → ({主体: {'fill','stroke'}}, [硬错误…])。见 D-49/D-59。 · L103 · 函数 · 分支：1→_color_map 2→_inherit_colors |
| 模块级 | 06 | _declare_subjects | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 显式声明过的主体直接占座（即便本表没用到也保留，图例与主图同构）→ 新字典。 · L127 · 函数 |
| 模块级 | 07 | _assign_lane_colors | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 显式泳道序里的主体按泳道序取色；空泳道同样占一档（它要画，没颜色会与其他列割裂）。 · L135 · 函数 |
| 模块级 | 08 | _assign_node_colors | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 节点「执行主体」列里还没占座的主体按出现顺序取色；占位符（-/—/空）不算主体。 · L142 · 函数 |
| 模块级 | 09 | subject_map | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07｜3→08 | ★ 按出现顺序给「执行主体」分配调色板；给了显式泳道序则**按泳道序**取色。 · L152 · 函数 · 分支：1→_declare_subjects 2→_assign_lane_colors 3→_assign_node_colors |
| 出口 | 10 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
