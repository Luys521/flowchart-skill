---
id: selfboot-sync
level: L1
parent: ../flowtable.md
---

# sync.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→11 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | build_hint | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 把读回结果的 row/col/col_x 打包成 table_to_dsl 的布局提示 · L24 · 函数 · ⇢ 依赖 flowtable_layout.auto_layout |
| 模块级 | 03 | _parse_args | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 解析 sync 的命令行参数。 · L49 · 函数 |
| 模块级 | 04 | _resolve_paths | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 校验 drawio 与原流程表路径，返回 (drawio, 原表, 输出表)；缺文件返回 None。 · L65 · 函数 |
| 模块级 | 05 | _read_back | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 读回 drawio（BOM 兼容）并按需打印摘要与差异；解析失败返回 None。 · L79 · 函数 · ⇢ 依赖 xml_reader.brief、xml_reader.diff、xml_reader.read |
| 模块级 | 06 | _write_back | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 回写《流程表》到预览文件并做逐字节复核；回写失败返回 1。 · L97 · 函数 · ⇢ 依赖 writeback.compare_bytes、writeback.write |
| 模块级 | 07 | _gen_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 写布局提示临时 yaml 并转出 DSL（泳道布局另报文案）；返回 (DSL 路径, 退出码)。 · L124 · 函数 · ⇢ 依赖 artifact.artifact_stem、flowtable.parse_table、table_to_dsl.main |
| 模块级 | 08 | _quality_gate | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 跑质量门禁；未过则报错并返回 1。 · L153 · 函数 · ⇢ 依赖 validate.main |
| 模块级 | 09 | _source_guard | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ 《流程表》自上次渲染后是否被直改过 → `(state, 说明)`。 · L164 · 函数 · ⇢ 依赖 artifact.artifact_name、artifact.artifact_stem、manifest.manifest_path_for、manifest.source_stale |
| 模块级 | 10 | _apply | 任务 | — | — | — | 脚本 | selfboot | — | →12 | ★ --apply：两道覆盖门禁通过后覆盖原表/DSL 并重渲染，返回退出码。 · L176 · 函数 · ⇢ 依赖 artifact.artifact_name、artifact.artifact_stem、build.main、flowtable.parse_table、writeback.branch_conflicts、writeback.format_conflicts |
| 模块级 | 11 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→05｜4→06｜5→07｜6→08｜7→09｜8→10 | L230 · 函数 · 分支：1→_parse_args 2→_resolve_paths 3→_read_back 4→_write_back 5→_gen_dsl 6→_quality_gate 7→_source_guard 8→_apply |
| 出口 | 12 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
