---
id: selfboot-recon
level: L1
parent: ../flowtable.md
---

# recon.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→25 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _docx_scale | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ `.docx` → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**只读结构，不物化全部文字**。 · L80 · 函数 · ⇢ 依赖 deps.import_dep |
| 模块级 | 03 | _is_heading | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 样式名判标题（与 `parse_ooxml` 同一句判据；两边都只认 `heading` 前缀）。 · L97 · 函数 |
| 模块级 | 04 | _xlsx_scale | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ `.xlsx` 字节 → `(规模描述, 子表行, 子表数, 结构说明)`。用尺寸信息读规模，**不扫单元格**。 · L104 · 函数 · ⇢ 依赖 deps.import_dep |
| 模块级 | 05 | _pptx_scale | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ `.pptx` → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**这就是那份".pptx 解析摘要"**。 · L132 · 函数 · ⇢ 依赖 pptx_text.other_text_parts_in_file、pptx_text.slides_in_file |
| 模块级 | 06 | _pdf_scale | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ `.pdf` → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**零依赖粗数页数**。 · L160 · 函数 |
| 模块级 | 07 | _text_scale | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 纯文本 / CSV → 规模。**行数 + 头几行的开头**——这是文本档唯一有意义的"结构"。 · L175 · 函数 |
| 模块级 | 08 | _image_scale | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 图片 → `尺寸（像素）`。**Pillow 是可选加速器**：缺了就说清，不硬造数字。 · L197 · 函数 · ⇢ 依赖 deps.hint |
| 模块级 | 09 | _ole_note | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ legacy（OLE 复合文档）**没有摘要可给**——这是诚实的极限，不是没做。 · L209 · 函数 |
| 模块级 | 10 | _note_of | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 异常 → 记在表里的说明。**把"材料的问题"与"我们自己的 bug"分开**： · L218 · 函数 |
| 模块级 | 11 | sample_structure | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04｜3→05｜4→06｜5→07｜6→08｜7→09｜8→10 | ★ **收路径**按 `kind` 缩样 → `(规模描述, 结构行, 结构总条数, 说明)`。 · L238 · 函数 · 分支：1→_docx_scale 2→_xlsx_scale 3→_pptx_scale 4→_pdf_scale 5→_text_scale 6→_image_scale 7→_ole_note 8→_note_of |
| 模块级 | 12 | difficulty | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 难度：不参与 / 易 / 中 / 难 / 最难。**分档只看 `bytes` 与 `tier`**（kind 只影响"… · L272 · 函数 |
| 模块级 | 13 | advise_depth | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 解析深度（§1.5 三选一）+ 触发它的数字。**事实与建议要能分开看**：数字随后写进「规模」列。 · L281 · 函数 |
| 模块级 | 14 | advise_path | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 走哪条路（§1.1 档位映射）：**按 `kind` 查表**，不看扩展名（审计 F3/F6）。 · L294 · 函数 |
| 模块级 | 15 | make_rows | 任务 | — | — | — | 脚本 | selfboot | — | 1→11｜2→12 | ★ 材料层 → 侦查行 + 跳过清单。**逐份尽力而为**：结构读不了记在行里，绝不外溢成整批失败。 · L300 · 函数 · 分支：1→sample_structure 2→difficulty · ⇢ 依赖 pptx_text.scan_cost |
| 模块级 | 16 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→14 | ★ 侦查结论表（markdown）。**表头先写输入指纹与阈值**——不然"共 20"这类数字事后没法复核。 · L333 · 函数 · 分支：1→advise_depth 2→advise_path |
| 模块级 | 17 | parse_table | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ `recon.md` → `(表头, {M##: {列: 值}}, 报错)`。表头必须逐字对得上（列规范在代码里只有这… · L379 · 函数 |
| 模块级 | 18 | check_rows | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ AI 填的列 + 脚本列 → 错误清单（空 = 过）。**只报不改**；§1.5"假设必须落盘、被推翻也要留痕"。 · L412 · 函数 |
| 模块级 | 19 | _write | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 写盘：UTF-8 / LF（与账本同一套口径；本文件通篇用 `\n` 拼）。 · L465 · 函数 |
| 模块级 | 20 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 读 JSON（容忍 BOM）。 · L469 · 函数 |
| 模块级 | 21 | load_thresholds | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 阈值 = 内置默认 + `dictionary.yaml` 的 `recon:` 段（**读取口径只有一处**：`th… · L473 · 函数 · ⇢ 依赖 thresholds.load |
| 模块级 | 22 | check_materials_shape | 任务 | — | — | — | 脚本 | selfboot | — | →26 | ★ 材料层**形状体检** → 报错文案（空 = 过）。 · L483 · 函数 |
| 模块级 | 23 | build | 任务 | — | — | — | 脚本 | selfboot | — | 1→15｜2→16｜3→19｜4→20｜5→21｜6→22 | ★ 出侦查结论表草稿 → 退出码。 · L501 · 函数 · 分支：1→make_rows 2→render 3→_write 4→_read_json 5→load_thresholds 6→check_materials_shape · ⇢ 依赖 cells.dump、cells.todo_from_doc |
| 模块级 | 24 | check | 任务 | — | — | — | 脚本 | selfboot | — | 1→17｜2→18｜3→20｜4→21 | ★ 校验 AI 填好的表 → 退出码 0/1/2。 · L543 · 函数 · 分支：1→parse_table 2→check_rows 3→_read_json 4→load_thresholds |
| 模块级 | 25 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→23｜2→24 | L569 · 函数 · 分支：1→build 2→check · ⇢ 依赖 artifact.beside |
| 出口 | 26 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
