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
| 模块级 | 02 | _docx_body | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 按**文档阅读序**产出 (kind, 对象)：段落与表格交替，顺序不丢（§2.2 第 3 条）。 · L33 · 函数 |
| 模块级 | 03 | parse_docx | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ `.docx` **字节** → `(elements, 报错文案)`。样式名判 heading / list_ite… · L44 · 函数 · ⇢ 依赖 deps.import_dep |
| 模块级 | 04 | parse_xlsx | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ `.xlsx` **字节** → `(elements, 报错文案)`。**一张 sheet 一个 element**… · L84 · 函数 · ⇢ 依赖 deps.import_dep |
| 模块级 | 05 | _span | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 范围语法 → `(起, 止)`；**语法与校验只有一处**（`semantics.parse_span`，D-122）。 · L144 · 函数 · ⇢ 依赖 semantics.parse_span |
| 模块级 | 06 | parse_pptx | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ `.pptx` **字节** → `(elements, 报错文案)`。**一张幻灯片一个 element**（零依赖… · L149 · 函数 · ⇢ 依赖 pptx_text.other_text_parts、pptx_text.slides |
| 模块级 | 07 | container_kind | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ PK 容器的**字节** → `'docx'` / `'xlsx'` / `'pptx'`；不是 OOXML 返回 N… · L200 · 函数 |
| 模块级 | 08 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→06｜4→07 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。非 OOXML / 非 ok 的一律**… · L220 · 函数 · 分支：1→parse_docx 2→parse_xlsx 3→parse_pptx 4→container_kind |
| 模块级 | 09 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 读 JSON（容忍 BOM）。 · L283 · 函数 |
| 模块级 | 10 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L287 · 函数 |
| 模块级 | 11 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→08｜3→09｜4→10 | L291 · 函数 · 分支：1→_span 2→parse_materials 3→_read_json 4→_write_notes |
| 出口 | 12 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
