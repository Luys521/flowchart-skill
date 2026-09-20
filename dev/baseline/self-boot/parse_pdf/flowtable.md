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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→09 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 读 JSON（容忍 BOM）。 · L36 · 函数 |
| 模块级 | 03 | _write_notes | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L41 · 函数 |
| 模块级 | 04 | _page_span | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 范围语法 → `(起, 止)`；**语法与校验只有一处**（`semantics.parse_span`，D-122）。 · L46 · 函数 · ⇢ 依赖 semantics.parse_span |
| 模块级 | 05 | load_thresholds | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 阈值 = 内置默认 + `dictionary.yaml` 的 `pdf_text_layer:` 段（**读取口径只… · L56 · 函数 · ⇢ 依赖 thresholds.load |
| 模块级 | 06 | thin_note | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ **尺子二**（§1.6）：`"抽出来太少"` → 一句降级说明；不判薄返回空串。 · L61 · 函数 |
| 模块级 | 07 | parse_pdf | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ `.pdf` → `(elements, 采样说明, 报错文案)`。只抽文本层；空页跳过（不伪造 element）。 · L82 · 函数 · 分支：1→load_thresholds 2→thin_note · ⇢ 依赖 deps.import_dep |
| 模块级 | 08 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。非 PDF / 非 T2 一律跳过并记账。 · L135 · 函数 |
| 模块级 | 09 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→08 | L185 · 函数 · 分支：1→_read_json 2→_write_notes 3→_page_span 4→parse_materials |
| 出口 | 10 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
