---
id: selfboot-parse_pdf
level: L1
parent: ../flowtable.md
---

# parse_pdf.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→07 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _import_dep | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ import 一个必须依赖 → `(模块, 报错文案)`（缺了给可执行的提示）。 · L35 · 函数 |
| 模块级 | 03 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 读 JSON（容忍 BOM）。 · L44 · 函数 |
| 模块级 | 04 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L49 · 函数 |
| 模块级 | 05 | parse_pdf | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ `.pdf` → `(elements, 采样说明, 报错文案)`。只抽文本层；空页跳过（不伪造 element）。 · L54 · 函数 |
| 模块级 | 06 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。非 PDF / 非 T2 一律跳过并记账。 · L98 · 函数 |
| 模块级 | 07 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→06 | L140 · 函数 · 分支：1→_read_json 2→_write_notes 3→parse_materials |
| 出口 | 08 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
