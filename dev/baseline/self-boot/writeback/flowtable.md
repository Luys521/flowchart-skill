---
id: selfboot-writeback
level: L1
parent: ../flowtable.md
---

# writeback.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→23｜2→24 | 流程起点（结构性节点，不是函数） · 入口：1→compare_bytes 2→main |
| 模块级 | 02 | _cell | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 单元格文本 → 可安全落进 markdown 表格的形态：`｜` 必须转义成 `\｜`（GFM 规范）， · L28 · 函数 |
| 模块级 | 03 | _is_sep_cell | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ GFM 分隔行单元格：`---` / `:---` / `:---:`（与 table_to_dsl.parse_ta… · L34 · 函数 |
| 模块级 | 04 | _row_key | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 行 → 可比对的键：占位符归一（主体/执行者 → `-`，行动所需时间/下个节点 → `—`）。 · L43 · 函数 |
| 模块级 | 05 | _tail | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ token 里编号之后的自由注解：`不齐全→回 01 补件` → ` 补件`。 · L67 · 函数 |
| 模块级 | 06 | orig_tokens | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ 原流程表「下个节点」列 → {节点id: [(raw, label, tid, tail)]}（保留作者顺序与原文）。 · L81 · 函数 · ⇢ 依赖 flowtable.parse_next_raw、flowtable.split_row_cells |
| 模块级 | 07 | new_token | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 生成一条分支文本（仅用于原表里没有对应项的新增/改动分支）。 · L94 · 函数 |
| 模块级 | 08 | build_rows | 任务 | — | — | — | 脚本 | selfboot | — | →07 | L102 · 函数 |
| 模块级 | 09 | branch_conflicts | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 原流程表「下个节点」列 vs drawio 实际连线的**方向性冲突**清单（D-45）。 · L141 · 函数 |
| 模块级 | 10 | format_conflicts | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 冲突清单 → 人读文本（文案只有一份：`sync.py` 与同模块的 `write()` 共用，别两处各写一遍）。 · L189 · 函数 |
| 模块级 | 11 | _read_drawio | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 读回 drawio XML（utf-8-sig 兼容带 BOM 的产物）。 · L203 · 函数 · ⇢ 依赖 xml_reader.read |
| 模块级 | 12 | _read_orig_snapshot | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 原流程表快照：看**字节**判换行符与 BOM，解码出全文与行列表。 · L209 · 函数 |
| 模块级 | 13 | _semantic_snapshot | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 原流程表按 id 的语义快照（阶段/描述/主体/执行者/时间/输入/依据/输出）——id 在原表出现过，语义就以原表为… · L220 · 函数 · ⇢ 依赖 flowtable.split_row_cells |
| 模块级 | 14 | _orig_line_index | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 原行文本（按 id）：未改动的行**整行照抄**，免得"多/少一个空格"这种伪差异混进 diff。 · L233 · 函数 · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 15 | _header_idx | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 主表表头行号：第一个含「节点编号」的 `｜` 行；没有返回 -1。**唯一出处**（G42 起两处共用）。 · L245 · 函数 |
| 模块级 | 16 | _split_table_block | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 定位标准表头与表格块边界 → (前言, 表后内容, 前言与表头之间的间隔, 尾换行)。 · L251 · 函数 |
| 模块级 | 17 | _table_frame | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→15 | ★ 原文的**表头行 / 分隔行** → 能照抄就照抄，否则落 canonical 模板（G42）。 · L280 · 函数 · 分支：1→_is_sep_cell 2→_header_idx · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 18 | _rebuild_rows | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→08 | ★ 逐行重建表格行与表格体（未改动整行照抄），并记下自检所需的 _resolved/_stage。 · L304 · 函数 · 分支：1→_cell 2→_row_key 3→build_rows · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 19 | _keep_after_table | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 表后内容保留：丢掉**混进来的表内散行**，其余（说明章节 / 文档表格等）逐字保留。 · L333 · 函数 · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 20 | _emit_table | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 前言 / 表格体 / 表后内容拼回，按原换行符与编码落盘，并打印回写统计。 · L357 · 函数 |
| 模块级 | 21 | _verify_written | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→10 | ★ 回写后自检（H1–H8），并报警分支走向冲突与缺语义的节点；返回**是否通过**。 · L370 · 函数 · 分支：1→branch_conflicts 2→format_conflicts · ⇢ 依赖 flowtable_check.run_checks |
| 模块级 | 22 | write | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→11｜3→12｜4→13｜5→14｜6→16｜7→17｜8→18｜9→19｜10→20｜11→21 | ★ drawio 读回结果 + 原流程表 → 更新后的流程表（回写闭环主入口）。 · L406 · 函数 · 分支：1→orig_tokens 2→_read_drawio 3→_read_orig_snapshot 4→_semantic_snapshot 5→_orig_line_index 6→_split_table_block 7→_table_frame 8→_rebuild_rows 9→_keep_after_table 10→_emit_table 11→_verify_written · ⇢ 依赖 flowtable.parse_table |
| 模块级 | 23 | compare_bytes | 任务 | — | — | — | 脚本 | selfboot | — | →25 | ★ 回写结果 vs 原文的**文件级**复核 → (是否逐字节一致, unified diff 行列表)。 · L429 · 函数 |
| 模块级 | 24 | main | 任务 | — | — | — | 脚本 | selfboot | — | →22 | L447 · 函数 |
| 出口 | 25 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
