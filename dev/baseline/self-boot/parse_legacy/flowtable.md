---
id: selfboot-parse_legacy
level: L1
parent: ../flowtable.md
---

# parse_legacy.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→14 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 读 JSON（容忍 BOM）。 · L62 · 函数 |
| 模块级 | 03 | _head | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 前 n 字节；读不动返回空（调用方按读不动记账，不崩）。 · L67 · 函数 |
| 模块级 | 04 | ole_kind | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ OLE 复合文档 → `'docx'` / `'xlsx'` / `'pptx'`；不是 OLE 或判不出返回 Non… · L76 · 函数 |
| 模块级 | 05 | _argv_of | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ `--soffice` 的取值 → argv 前缀。**存在就整条当路径**（躲开 `C:\Program Files… · L89 · 函数 |
| 模块级 | 06 | _decode | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 外部转换器的输出 → 文本。**不能假定它说 UTF-8**：Windows 上的 soffice 往管道里写本地编码 · L109 · 函数 |
| 模块级 | 07 | _runs | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 跑一次 `<转换器> --version` → `(退出码, 输出)`；起不来返回 (None, 原因)。 · L124 · 函数 |
| 模块级 | 08 | find_converter | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→07 | ★ 探测外部转换器 → `(argv 前缀, 版本说明, 报错文案)`。 · L134 · 函数 · 分支：1→_argv_of 2→_runs |
| 模块级 | 09 | convert | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ `<转换器> --headless --convert-to <target> --outdir <dir> <材料>… · L157 · 函数 |
| 模块级 | 10 | extract_via_ooxml | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 子进程调 `parse_ooxml.py` 抽转换产物 → `(elements, 报错文案)`；出处改回原材料。 · L185 · 函数 |
| 模块级 | 11 | parse_legacy | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→09｜3→10 | ★ 一份 legacy 材料 → `(elements, 材料补注, 跳过说明, 报错文案)`。 · L214 · 函数 · 分支：1→ole_kind 2→convert 3→extract_via_ooxml |
| 模块级 | 12 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 材料层 → `(elements, 材料补注, 摘要, 跳过清单, 报错文案)`。只认 OLE；别的材料**不归我管*… · L242 · 函数 |
| 模块级 | 13 | _write_json | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 ledger.dump）。 · L268 · 函数 |
| 模块级 | 14 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→08｜3→12｜4→13 | L273 · 函数 · 分支：1→_read_json 2→find_converter 3→parse_materials 4→_write_json |
| 出口 | 15 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
