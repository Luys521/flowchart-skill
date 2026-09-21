---
id: selfboot-intake
level: L1
parent: ../flowtable.md
---

# intake.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→10 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | escape | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 单元格转义：ASCII 竖线 → 全角 `｜`（竖线是表格列分隔符，不换就**切错列**——与 `selfboot_g… · L58 · 函数 |
| 模块级 | 03 | duplicate_pairs | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 材料层 → `({M##: 被重复的 M##}, [(原件, 副本), …])`。**判重只看 `sha256`**（… · L63 · 函数 |
| 模块级 | 04 | _line_of | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 一条证据 → 摘要里的一行（表格给行列数，其余给原文节选：压成单行 + 截断）。 · L79 · 函数 |
| 模块级 | 05 | _digest_lines | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 一份材料的线索：证据条数 / 种类分布 / 头几处可引用的原文（填「主题 / 依据」时从这里挑）。 · L93 · 函数 |
| 模块级 | 06 | build_card | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→05 | ★ 账本 → `intake.md` 全文。机器可算的格子已填，语义格子留 `—`（check 会把未填当错）。 · L123 · 函数 · 分支：1→escape 2→duplicate_pairs 3→_digest_lines |
| 模块级 | 07 | parse_cards | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ `intake.md` → `(表头, {M##: {列: 值}}, 报错)`。表头必须逐字对得上（列规范 §3）。 · L163 · 函数 |
| 模块级 | 08 | check_cards | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→09 | ★ 卡片 vs 账本 → 错误清单（空 = 过）。**只报不改**（§3 纪律 1：清点不改账本）。 · L191 · 函数 · 分支：1→escape 2→_check_relation · ⇢ 依赖 flowtable_check.citations |
| 模块级 | 09 | _check_relation | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 版本关系：取值封闭 + **双向一致**（§3 的硬要求，单向声明按错处理）。 · L229 · 函数 |
| 模块级 | 10 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→06｜3→07｜4→08 | L272 · 函数 · 分支：1→duplicate_pairs 2→build_card 3→parse_cards 4→check_cards · ⇢ 依赖 artifact.beside、cells.dump、cells.todo_from_doc |
| 出口 | 11 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
