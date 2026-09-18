---
id: selfboot-parse_text
level: L1
parent: ../flowtable.md
---

# parse_text.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→16 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 读 JSON（容忍 BOM）。 · L57 · 函数 |
| 模块级 | 03 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L62 · 函数 |
| 模块级 | 04 | other_owner | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 前几字节 → 该材料归谁（`'OOXML 容器'` / …）；不是别人的返回空串。 · L67 · 函数 |
| 模块级 | 05 | decode_text | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 字节 → `(文本, 依据, 报错)`。顺序：**UTF-8（含 BOM）→ 带 BOM 的 UTF-16 → 用户给… · L75 · 函数 |
| 模块级 | 06 | reader_of | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 扩展名 → 读法名（`'markdown'` / `'csv'` / `'code'` / `'plain'`）。认不… · L100 · 函数 |
| 模块级 | 07 | _cap | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 超上限就截断 → `(文本, 是否截断)`。截断处留省略标记（§2.3 不许无声变短）。 · L112 · 函数 |
| 模块级 | 08 | _element | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 造一个带正文的 element（`quote` = 原文摘录）；超上限截断并记 `degraded`（§2.4）。 · L117 · 函数 |
| 模块级 | 09 | _plain | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 纯文本 → 空行分段，一段一个 `paragraph`。 · L133 · 函数 |
| 模块级 | 10 | _markdown | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→17｜3→18 | ★ Markdown → 标题 / 列表项 / 围栏代码 / 竖线表 / 段落。**标记原样留在 text 里**（见文件… · L150 · 函数 · 分支：1→_element 2→_markdown.flush_para 3→_markdown.flush_table |
| 模块级 | 11 | _csv | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ CSV / TSV → **一份一个 `table`**（`rows` 承载内容，与 `parse_xlsx` 的"一… · L221 · 函数 |
| 模块级 | 12 | _code | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 机器格式（json / yaml / xml / html …）→ **整份一个 `code`**。结构解析是 T2 … · L243 · 函数 |
| 模块级 | 13 | parse_text | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→05｜3→06｜4→09｜5→10｜6→11｜7→12 | ★ 一份材料 → `(elements, extractor, 报错, 内容为空)`。 · L249 · 函数 · 分支：1→other_owner 2→decode_text 3→reader_of 4→_plain 5→_markdown 6→_csv 7→_code |
| 模块级 | 14 | _mark_capped | 任务 | — | — | — | 脚本 | selfboot | — | →19 | ★ 材料级降级说明挂到**该材料的每条**上（与 `parse_pdf` 同一口径：消费方扫任意一条就知道被裁过）。 · L284 · 函数 |
| 模块级 | 15 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→14 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。 · L290 · 函数 · 分支：1→parse_text 2→_mark_capped |
| 模块级 | 16 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→15 | L332 · 函数 · 分支：1→_read_json 2→_write_notes 3→parse_materials |
| _markdown | 17 | _markdown.flush_para | 任务 | — | — | — | 脚本 | selfboot | — | →08 | L155 · 嵌套函数 |
| _markdown | 18 | _markdown.flush_table | 任务 | — | — | — | 脚本 | selfboot | — | →19 | L162 · 嵌套函数 |
| 出口 | 19 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
