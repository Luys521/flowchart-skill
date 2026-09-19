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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→26 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | no_converter_reason | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 缺转换器时的**按族给话**：这份是什么、最省事的下一步是什么。 · L87 · 函数 |
| 模块级 | 03 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 读 JSON（容忍 BOM）。 · L99 · 函数 |
| 模块级 | 04 | _head | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 前 n 字节；读不动返回空（调用方按读不动记账，不崩）。 · L104 · 函数 |
| 模块级 | 05 | ole_kind | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ OLE 复合文档 → `'docx'` / `'xlsx'` / `'pptx'`；不是 OLE 或判不出返回 Non… · L113 · 函数 |
| 模块级 | 06 | _argv_of | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ `--soffice` 的取值 → argv 前缀。**存在就整条当路径**（躲开 `C:\Program Files… · L126 · 函数 |
| 模块级 | 07 | _decode | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 外部转换器的输出 → 文本。**不能假定它说 UTF-8**：Windows 上的 soffice 往管道里写本地编码 · L146 · 函数 |
| 模块级 | 08 | _runs | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 跑一次 `<转换器> --version` → `(退出码, 输出)`；起不来返回 (None, 原因)。 · L161 · 函数 |
| 模块级 | 09 | find_converter | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→08 | ★ 探测外部转换器 → `(argv 前缀, 版本说明, 报错文案)`。 · L171 · 函数 · 分支：1→_argv_of 2→_runs |
| 模块级 | 10 | convert | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ `<转换器> --headless --convert-to <target> --outdir <dir> <材料>… · L194 · 函数 |
| 模块级 | 11 | extract_via_ooxml | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 子进程调 `parse_ooxml.py` 抽转换产物 → `(elements, 报错文案)`；出处改回原材料。 · L222 · 函数 |
| 模块级 | 12 | load_thresholds | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 阈值 = 内置默认 + `dictionary.yaml` 的 `legacy_text:` 段（读不到就用默认，**… · L252 · 函数 |
| 模块级 | 13 | _is_text_unit | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 这个字符**像正文**吗（拿它当 run 的粘合剂）。 · L272 · 函数 |
| 模块级 | 14 | _is_word | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 算不算"字"（判 run 像不像正文用）：中日韩 + 字母 + 数字。 · L287 · 函数 |
| 模块级 | 15 | _word_ratio | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L293 · 函数 |
| 模块级 | 16 | _low0_ratio | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 码位**低字节恒为 0** 的比例——这是"单字节二进制被当成 UTF-16LE 读"的指纹。 · L297 · 函数 |
| 模块级 | 17 | _is_common | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ "常用字面"：ASCII / 拉丁补充 / 常用标点 / 中日韩与全角——**真正文几乎全落在这一片里**。 · L308 · 函数 |
| 模块级 | 18 | _common_ratio | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 常用字面占比——用来丢"字符撒在几十个文种里"的高熵噪声（那些也是二进制，只是碰巧合了法）。 · L317 · 函数 |
| 模块级 | 19 | _emit | 任务 | — | — | — | 脚本 | selfboot | — | 1→15｜2→16｜3→18 | ★ 一条 run 收尾：**够长 · 够"像正文" · 不是错位读的怪字 · 不是多种文字混在一起的高熵噪声**才留。 · L326 · 函数 · 分支：1→_word_ratio 2→_low0_ratio 3→_common_ratio |
| 模块级 | 20 | _runs_at | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→19 | ★ 按 `shift` 字节对齐扫一遍 → `[(字节偏移, 文本)]`。 · L336 · 函数 · 分支：1→_is_text_unit 2→_emit |
| 模块级 | 21 | runs_of | 任务 | — | — | — | 脚本 | selfboot | — | →20 | ★ OLE 原始字节 → `(run 列表, 说明)`。**两种对齐都扫**：正文 run 未必从偶数字节开始。 · L351 · 函数 |
| 模块级 | 22 | fallback_elements | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ run 列表 → `elements[]`：**并相邻 run → 按 `max_chars` 切块 → 每条挂降级说… · L374 · 函数 |
| 模块级 | 23 | parse_legacy | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→05｜3→10｜4→11｜5→21｜6→22 | ★ 一份 legacy 材料 → `(elements, 材料补注, 跳过说明, 报错文案)`。 · L410 · 函数 · 分支：1→no_converter_reason 2→ole_kind 3→convert 4→extract_via_ooxml 5→runs_of 6→fallback_elements |
| 模块级 | 24 | parse_materials | 任务 | — | — | — | 脚本 | selfboot | — | →23 | ★ 材料层 → `(elements, 材料补注, 摘要, 跳过清单, 报错文案)`。只认 OLE；别的材料**不归我管*… · L448 · 函数 |
| 模块级 | 25 | _write_json | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 ledger.dump）。 · L475 · 函数 |
| 模块级 | 26 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→09｜3→12｜4→24｜5→25 | L480 · 函数 · 分支：1→_read_json 2→find_converter 3→load_thresholds 4→parse_materials 5→_write_json |
| 出口 | 27 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
