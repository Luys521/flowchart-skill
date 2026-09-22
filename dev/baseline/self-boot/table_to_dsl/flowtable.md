---
id: selfboot-table_to_dsl
level: L1
parent: ../flowtable.md
---

# table_to_dsl.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→16 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | build_dsl_nodes | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 流程表节点 → DSL 节点。row/col 优先取布局提示（手调值），语义字段一律来自流程表。 · L34 · 函数 |
| 模块级 | 03 | _parse_args | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 解析 table_to_dsl 的命令行参数。 · L54 · 函数 |
| 模块级 | 04 | _load_flowtable | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 校验流程表存在与 PyYAML 可用，解析出 (标题, 元信息, 行)；任一缺失返回 None。 · L72 · 函数 · ⇢ 依赖 deps.hint、flowtable.parse_table |
| 模块级 | 05 | _run_checks | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 跑 H1–H9 结构校验与配色解析，返回 (模式, 列序, 配色, 节点, 边, 错误集, 槽位备注)。 · L88 · 函数 · ⇢ 依赖 flowtable_check.check_evidence、flowtable_check.check_header、flowtable_check.run_checks、flowtable_colors.resolve_colors、flowtable_layout.parse_lane_order |
| 模块级 | 06 | _report_checks | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 打印校验结果（--json 走结构化，否则走人类可读文本）。 · L108 · 函数 · ⇢ 依赖 semantics.findings_receipt |
| 模块级 | 07 | _enforce_showcase | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ showcase 档要求零软提示；有软提示则阻断并返回 1。 · L144 · 函数 |
| 模块级 | 08 | _load_hint | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 读布局提示 yaml（泳道布局不借提示）；文件不存在时告警并返回 None。 · L153 · 函数 |
| 模块级 | 09 | _assemble_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 按布局提示或泳道/流程分派组装 DSL，返回 dsl 字典。 · L165 · 函数 · ⇢ 依赖 flowtable_colors.subject_map、flowtable_layout.auto_layout、flowtable_layout.merge_parallel_branches、flowtable_layout.reuse_hint、geometry.snap |
| 模块级 | 10 | _emit_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 落盘 DSL 并打印下一步提示，返回 DSL 路径。 · L220 · 函数 · ⇢ 依赖 artifact.artifact_name、artifact.artifact_stem |
| 模块级 | 11 | _emit_manifest | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 与 DSL 同刻产出渲染契约（供下游渲染后反查产物，见 DECISIONS.md D-11）。 · L233 · 函数 · ⇢ 依赖 manifest.build、manifest.dsl_fingerprint、manifest.manifest_path_for、manifest.source_fingerprint、manifest.summary |
| 模块级 | 12 | _run_fresh | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ `--fresh`：只答一句"这张表自上次渲染后有没有被直改过"，不校验、不产出。 · L249 · 函数 · ⇢ 依赖 artifact.artifact_name、artifact.artifact_stem、manifest.manifest_path_for、manifest.source_fingerprint、manifest.source_stale |
| 模块级 | 13 | _derive_channel_step | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 按**这张图最宽的标签**定通道档距，写进 `layout`（派生量，与 `width` / `origin_x` 同… · L284 · 函数 · ⇢ 依赖 geometry.ceil_to、semantics.text_width、thresholds.load |
| 模块级 | 14 | _center_canvas | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 流程布局：把画布**贴合内容**、并让内容横向居中（泳道布局不动——它的宽度本来就由列宽算出）。 · L317 · 函数 · ⇢ 依赖 engine.Engine.label_box、engine.Engine.legend_width、engine.Engine.path、engine.Engine.rect、engine.load、geometry.ceil_to、geometry.snap |
| 模块级 | 15 | _write_dsl | 任务 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09｜3→10｜4→11｜5→14 | ★ --write 路径：读布局提示 → 组装 DSL → 量一次并居中画布 → 落盘 DSL 与渲染契约；返回退出码。 · L361 · 函数 · 分支：1→_load_hint 2→_assemble_dsl 3→_emit_dsl 4→_emit_manifest 5→_center_canvas |
| 模块级 | 16 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→05｜4→06｜5→07｜6→12｜7→15 | L379 · 函数 · 分支：1→_parse_args 2→_load_flowtable 3→_run_checks 4→_report_checks 5→_enforce_showcase 6→_run_fresh 7→_write_dsl |
| 出口 | 17 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
