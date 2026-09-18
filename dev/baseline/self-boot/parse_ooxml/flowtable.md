---
id: selfboot-parse_ooxml
level: L1
parent: ../flowtable.md
---

# parse_ooxml.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→11 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _import_dep | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ import 一个必须依赖 → `(模块, 报错文案)`。缺了给**可执行**的提示（§1.4）。 · L31 · 函数 |
| 模块级 | 03 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 读 JSON（容忍 BOM）。 · L41 · 函数 |
| 模块级 | 04 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L46 · 函数 |
| 模块级 | 05 | container_kind | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ PK 容器的**字节** → `'docx'` / `'xlsx'` / `'pptx'`；不是 OOXML 返回 N… · L51 · 函数 |
| 模块级 | 06 | _docx_body | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 按**文档阅读序**产出 (kind, 对象)：段落与表格交替，顺序不丢（§2.2 第 3 条）。 · L72 · 函数 |
| 模块级 | 07 | parse_docx | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→06 | ★ `.docx` **字节** → `(elements, 报错文案)`。样式名判 heading / list_ite… · L84 · 函数 · 分支：1→_import_dep 2→_docx_body |
| 模块级 | 08 | parse_xlsx | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ `.xlsx` **字节** → `(elements, 报错文案)`。**一张 sheet 一个 element**… · L125 · 函数 |
| 模块级 | 09 | parse_pptx | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ `.pptx` **字节** → `(elements, 报错文案)`。**一张幻灯片一个 element**（零依赖… · L162 · 函数 · ⇢ 依赖 pptx_text.slides |
| 模块级 | 10 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→07｜3→08｜4→09 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。非 OOXML / 非 ok 的一律**… · L190 · 函数 · 分支：1→container_kind 2→parse_docx 3→parse_xlsx 4→parse_pptx |
| 模块级 | 11 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→10 | L231 · 函数 · 分支：1→_read_json 2→_write_notes 3→parse_materials |
| 出口 | 12 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
