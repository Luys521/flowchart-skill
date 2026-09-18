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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→13 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 读 JSON（容忍 BOM）。 · L55 · 函数 |
| 模块级 | 03 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L60 · 函数 |
| 模块级 | 04 | other_owner | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 前几字节 → 该材料归谁（`'OOXML 容器'` / …）；不是别人的返回空串。 · L65 · 函数 |
| 模块级 | 05 | decode_text | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 字节 → `(文本, 依据, 报错)`。顺序：**UTF-8（含 BOM）→ 带 BOM 的 UTF-16 → 用户给… · L73 · 函数 |
| 模块级 | 06 | kind_of | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 扩展名 → `'csv'` / `'code'` / `'text'`。**只分这三类**：结构不在本脚本的射程内（见… · L99 · 函数 |
| 模块级 | 07 | _element | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 造一个带正文的 element（`quote` = 原文摘录）；超上限截断并记 `degraded`（§2.4）。 · L107 · 函数 |
| 模块级 | 08 | _blocks | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 文本 → **按行打块**：空行收一块，块满 `max_chars` 也收 → 一块一个 element。 · L124 · 函数 |
| 模块级 | 09 | _csv | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ CSV / TSV → **一份一个 `table`**（`rows` 承载内容，与 `parse_xlsx` 的"一… · L155 · 函数 |
| 模块级 | 10 | parse_text | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→05｜3→06｜4→08｜5→09 | ★ 一份材料 → `(elements, extractor, 报错, 内容为空)`。 · L177 · 函数 · 分支：1→other_owner 2→decode_text 3→kind_of 4→_blocks 5→_csv |
| 模块级 | 11 | _mark_capped | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 材料级降级说明挂到**该材料的每条**上（与 `parse_pdf` 同一口径：消费方扫任意一条就知道被裁过）。 · L208 · 函数 |
| 模块级 | 12 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | 1→10｜2→11 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。 · L214 · 函数 · 分支：1→parse_text 2→_mark_capped |
| 模块级 | 13 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→12 | L256 · 函数 · 分支：1→_read_json 2→_write_notes 3→parse_materials |
| _blocks | 14 | _blocks.flush | 任务 | — | — | — | 脚本 | selfboot | — | →07 | L136 · 嵌套函数 |
| 出口 | 15 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
