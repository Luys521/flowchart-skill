---
id: selfboot-probe
level: L1
parent: ../flowtable.md
---

# probe.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→10 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_head | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 前 n 字节；读不动就返回空（调用方按 T4 记账，不许崩）。 · L63 · 函数 |
| 模块级 | 03 | _mtime | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 修改时间（ISO 8601 本地时区）；取不到返回空串（不崩）—§3「替代」的末位兜底。 · L72 · 函数 |
| 模块级 | 04 | _ooxml_kind | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ PK 容器 → `docx` / `xlsx` / `pptx`；不是 OOXML 就返回 None。 · L80 · 函数 |
| 模块级 | 05 | _pdf_tier | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ PDF：有字体标记 → 有文本层（T2），否则判扫描件（T3）。依据写成 `/Font` 计数，人可核。 · L98 · 函数 |
| 模块级 | 06 | _text_tier | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 能按 UTF-8 解码且无 NUL 字节 → 文本（T1）；否则 None。 · L114 · 函数 |
| 模块级 | 07 | sniff | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→05｜4→06 | ★ 一个文件 → `(tier, probe, status, reason, kind)`。`probe` 是**判据*… · L135 · 函数 · 分支：1→_read_head 2→_ooxml_kind 3→_pdf_tier 4→_text_tier |
| 模块级 | 08 | probe_tree | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→07 | ★ 路径（文件或目录）→ `materials[]`；目录按**材料路径字典序**编号 `M01`…（PIPELINE-S… · L179 · 函数 · 分支：1→_mtime 2→sniff |
| 模块级 | 09 | _print_table | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 人读摘要：一行一份材料。 · L207 · 函数 |
| 模块级 | 10 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09 | L217 · 函数 · 分支：1→probe_tree 2→_print_table |
| 出口 | 11 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
