---
id: selfboot-query
level: L1
parent: ../flowtable.md
---

# query.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→10 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | parse_range | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ `'pages=40-60'` → `('pages', 40, 60)`；`'sheet=清单'` → `('she… · L66 · 函数 · ⇢ 依赖 semantics.parse_span |
| 模块级 | 03 | in_range | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 这条落在任一范围里吗（`ranges` 为空 = 不筛）。`ordinal` 是该材料内第几条（1 起）。 · L89 · 函数 |
| 模块级 | 04 | matches | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 材料号与关键词两关（都为空 = 不筛）。可搜面来自公共层（与 `parse.py --grep` 同一句）。 · L104 · 函数 · ⇢ 依赖 textquality.element_haystack |
| 模块级 | 05 | loc_text | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ `location` → 一句人能读的位置（页 / 子表!单元格 / 图内坐标 / 实在没有就报"没有出处"）。 · L111 · 函数 |
| 模块级 | 06 | excerpt | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 一条证据的**短摘录**：有正文用正文；表格给"行×列 + 头一行"；都没有就用 id（不装空）。 · L124 · 函数 |
| 模块级 | 07 | select | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | ★ 账本元素 → `(这一批的行, 命中总数)`。顺序 = 账本原序（阅读序），**同输入同输出**。 · L147 · 函数 · 分支：1→in_range 2→matches |
| 模块级 | 08 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 这一批（markdown）+ **游标行**——AI 靠它决定"要不要再要一口"，而不是一次把全部灌进去。 · L158 · 函数 · 分支：1→loc_text 2→excerpt |
| 模块级 | 09 | load_defaults | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 默认值 = 内置 + `dictionary.yaml` 的 `query:` 段（**读取口径只有一处**：`thr… · L173 · 函数 · ⇢ 依赖 thresholds.load |
| 模块级 | 10 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→05｜3→06｜4→07｜5→08｜6→09 | ★ 命令行入口：读账本 → 解析范围 → 取一批 → 打印（或 `--json`）。 · L181 · 函数 · 分支：1→parse_range 2→loc_text 3→excerpt 4→select 5→render 6→load_defaults · ⇢ 依赖 capability.compare、capability.read_json、capability.warn |
| 出口 | 11 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
