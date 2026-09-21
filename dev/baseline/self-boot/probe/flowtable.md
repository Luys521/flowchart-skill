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
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→17 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _bmp_ok | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ `BM` 后面那 12 字节像不像真 BMP：**保留域必须为 0、大小域必须等于文件大小**。 · L43 · 函数 |
| 模块级 | 03 | _read_head | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 前 n 字节；读不动就返回空（调用方按 T4 记账，不许崩）。 · L83 · 函数 |
| 模块级 | 04 | _ooxml_kind | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ PK 容器 → `docx` / `xlsx` / `pptx`；不是 OOXML 就返回 None。 · L91 · 函数 |
| 模块级 | 05 | _count_marker | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ **分块**数一个字节标记出现几次 —— 不把整份读进内存（G34）。 · L108 · 函数 |
| 模块级 | 06 | _pdf_tier | 任务 | — | — | — | 脚本 | selfboot | — | →05 | ★ PDF：有字体标记 → 有文本层（T2），否则判扫描件（T3）。依据写成 `/Font` 计数，人可核。 · L126 · 函数 |
| 模块级 | 07 | _decodes | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 这段字节能不能解成 UTF-8。 · L144 · 函数 |
| 模块级 | 08 | _text_tier | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 能按 UTF-8 解码且无 NUL 字节 → 文本（T1）；否则 None。**头尾都要过**。 · L168 · 函数 |
| 模块级 | 09 | sniff | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→06｜5→08｜6→11 | ★ 一个文件 → `(tier, probe, status, reason, kind)`。`probe` 是**判据*… · L190 · 函数 · 分支：1→_bmp_ok 2→_read_head 3→_ooxml_kind 4→_pdf_tier 5→_text_tier 6→_read_tail |
| 模块级 | 10 | _mtime | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 修改时间（ISO 8601 本地时区）；取不到返回空串（不崩）—§3「替代」的末位兜底。 · L241 · 函数 |
| 模块级 | 11 | _read_tail | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 末 n 字节（不足就全给）；读不动返回空（调用方按"没有尾部"处理，不崩）。 · L248 · 函数 |
| 模块级 | 12 | _sha_and_size | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ → `(sha256, 字节数)`，**分块读**（默认 1 MiB 一块）。 · L260 · 函数 |
| 模块级 | 13 | probe_tree | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→10｜3→12 | ★ 路径（文件或目录）→ `materials[]`；目录按**材料路径字典序**编号 `M01`…（PIPELINE-S… · L278 · 函数 · 分支：1→sniff 2→_mtime 3→_sha_and_size |
| 模块级 | 14 | verify_list | 任务 | — | — | — | 脚本 | selfboot | — | 1→12｜2→15 | ★ **陈化检查**：`materials[]` 记的与材料根**当下**还对不对得上（PIPELINE-SPEC §1.… · L308 · 函数 · 分支：1→_sha_and_size 2→_is_artifact_name |
| 模块级 | 15 | _is_artifact_name | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 这份"新文件"是不是**本工具链自己的产物**？（产物名 / `.todo.json` / `.bak` ⇒ 是） · L364 · 函数 |
| 模块级 | 16 | _print_table | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 人读摘要：一行一份材料。 · L376 · 函数 |
| 模块级 | 17 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→14｜3→16 | L385 · 函数 · 分支：1→probe_tree 2→verify_list 3→_print_table |
| 出口 | 18 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
