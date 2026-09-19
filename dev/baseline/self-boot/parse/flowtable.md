---
id: selfboot-parse
level: L1
parent: ../flowtable.md
---

# parse.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→16 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 读 JSON（容忍 BOM）。 · L47 · 函数 |
| 模块级 | 03 | _write_json | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L52 · 函数 |
| 模块级 | 04 | _last_line | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 子进程输出 → 最后一行非空（适配器把摘要打在 stderr，取它给人看；整份太吵，`--verbose` 才全给）。 · L57 · 函数 |
| 模块级 | 05 | _adapter_args | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 按适配器给参数——**不认得的选项不硬塞**（argparse 会当场报用法错，那是假故障）。 · L63 · 函数 |
| 模块级 | 06 | _opt | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 把 `(选项, 值)` 对里**有值的那几对**接在 base 后面（空值 = 没收窄，不传）。 · L82 · 函数 |
| 模块级 | 07 | _span | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ `'40-60'` / `'7'` → `(40, 60)` / `(7, 7)`；空 → `None`；**写歪/反… · L91 · 函数 |
| 模块级 | 08 | narrow_materials | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ `--only M03,M15` → `(可选中的那些, 被排除的那些)`。**空集合 = 不筛**（不是"一份都不要… · L111 · 函数 |
| 模块级 | 09 | apply_narrowing | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 抽取后收窄：`--grep` 只留含这个词的片段、`--lines A-B` 只留该材料内第 A–B 条。 · L133 · 函数 · ⇢ 依赖 textquality.element_haystack |
| 模块级 | 10 | run_adapter | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | ★ 跑一个适配器 → `(elements, notes, 摘要行, 报错文案)`。走**子进程 + 产物**（模块层不许… · L165 · 函数 · 分支：1→_read_json 2→_last_line |
| 模块级 | 11 | merge_elements | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ `[(适配器名, elements)]` → `(合并后的 elements, 冲突说明)`。 · L188 · 函数 |
| 模块级 | 12 | apply_quality | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 抽取质量门（§1.5「手段 0」）→ `(留下的元素, 覆盖用的补注, 丢掉的元素 id, 读数行, {M##: 级别… · L207 · 函数 · ⇢ 依赖 textquality.readout、textquality.scar、textquality.verdict |
| 模块级 | 13 | merge_notes | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ `[(适配器名, notes)]` → `(合并后的 notes, 冲突说明)`。 · L257 · 函数 |
| 模块级 | 14 | survey | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 材料层 × 证据 × 补注 → `(每份材料一行, 漏认清单)`。**漏认 = status=ok 却既无元素也无补注… · L275 · 函数 |
| 模块级 | 15 | _print_survey | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 人读摘要：一份材料一行。**没有证据也没有补注的当场标出来**（那是漏认，不是"空材料"）。 · L308 · 函数 |
| 模块级 | 16 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→05｜5→07｜6→08｜7→09｜8→10｜9→11｜10→12｜11→13｜12→14｜13→15 | L324 · 函数 · 分支：1→_read_json 2→_write_json 3→_last_line 4→_adapter_args 5→_span 6→narrow_materials 7→apply_narrowing 8→run_adapter 9→merge_elements 10→apply_quality 11→merge_notes 12→survey 13→_print_survey · ⇢ 依赖 textquality.load_thresholds |
| 出口 | 17 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
