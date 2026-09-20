---
id: selfboot-semantics
level: L1
parent: ../flowtable.md
---

# semantics.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→05｜5→07｜6→08｜7→10｜8→13｜9→14｜10→15｜11→16｜12→18｜13→19 | 流程起点（结构性节点，不是函数） · 入口：1→Finding.__new__ 2→findings_receipt 3→split_table_row 4→arrow_markers 5→parse_span 6→has_ambiguous_sep 7→pending_style 8→subflow_target 9→is_pending 10→text_width 11→Syntax.__init__ 12→Syntax.route_text 13→Syntax.node_lines |
| Finding | 02 | Finding.__new__ | 任务 | — | — | — | 脚本 | selfboot | — | →20 | L24 · 方法 |
| 模块级 | 03 | findings_receipt | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 报错/提示列表 → 结构化回执（纯 dict 列表，供 --json 输出）。 · L31 · 函数 |
| 模块级 | 04 | split_table_row | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ markdown 表格行 → 单元格列表。 · L86 · 函数 |
| 模块级 | 05 | arrow_markers | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 箭头 marker 串（SVG 的 `<defs>` 内容）——html 与 svg 两份产物共用一份（见 D-89）。 · L97 · 函数 |
| 模块级 | 06 | split_branches | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 「下个节点」列 → 出口文本列表（只认 `｜`，兼容 `<br>` 与真换行——见 flowtable-spec §2… · L120 · 函数 |
| 模块级 | 07 | parse_span | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ `'40-60'` / `'7'` → `(40, 60)` / `(7, 7)`；空 → `None`；**写歪或反… · L126 · 函数 |
| 模块级 | 08 | has_ambiguous_sep | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 「下个节点」列里，把分号当成了分隔符用（`通过→05；不通过→06`）。 · L154 · 函数 |
| 模块级 | 09 | pending_kind | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 节点描述的标记 → None / 'inferred' / 'verdict'（判据与收敛条件见 D-46、flowt… · L162 · 函数 |
| 模块级 | 10 | pending_style | 任务 | — | — | — | 脚本 | selfboot | — | →09 | ★ 节点描述 → 留痕外观 `{'stroke', 'dash', 'note'}`；不是 `⚠` 开头则返回 `{}`。 · L181 · 函数 |
| 模块级 | 11 | _normalize_subflow_path | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 子表相对路径规范化：越界（绝对路径 / 逃出目录）一律返回 None。 · L200 · 函数 |
| 模块级 | 12 | subflow_ref | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 节点描述 → 子表相对路径（无则 None）。见 D-47。 · L220 · 函数 |
| 模块级 | 13 | subflow_target | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 节点描述 → **子表流程表**的相对路径（无则 None）。见 D-47 / D-51。 · L251 · 函数 |
| 模块级 | 14 | is_pending | 任务 | — | — | — | 脚本 | selfboot | — | →09 | ★ 节点描述**以 ⚠ 开头**（含 `⚠?`）= 留痕节点，渲染时必须画虚线（约定见 flowtable-spec §2… · L268 · 函数 |
| 模块级 | 15 | text_width | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 文本宽度估算：CJK/带圈数字按全角宽，其余按半角宽（SVG 无自动排版，必须自己推进 x）。 · L278 · 函数 |
| Syntax | 16 | Syntax.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →20 | L285 · 方法 |
| Syntax | 17 | Syntax.route_names | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 路由文本：节点编号→节点名（仅替换 →/回 引导的编号，避开 30日、10MW 等） · L288 · 方法 |
| Syntax | 18 | Syntax.route_text | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→17 | ★ 路由文本：编号→名称，多个出口换成真正的换行。 · L295 · 方法 · 分支：1→split_branches 2→Syntax.route_names |
| Syntax | 19 | Syntax.node_lines | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ 节点显示行：判断节点只放名称；其余 名称行+执行者+行动所需时间(可选) · L304 · 方法 |
| 出口 | 20 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
