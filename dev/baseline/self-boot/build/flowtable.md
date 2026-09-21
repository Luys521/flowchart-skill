---
id: selfboot-build
level: L1
parent: ../flowtable.md
---

# build.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→21｜2→26 | 流程起点（结构性节点，不是函数） · 入口：1→build_registry 2→main |
| 模块级 | 02 | _ids | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 读 flow.yaml 里的节点 id 集合；读不动（文件坏/不存在/缺 id 键）返回空集。 · L42 · 函数 |
| 模块级 | 03 | _rollback | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 审核未过 → 把刚写下的产物还原成审核前的样子（原本不存在的就删掉）。 · L53 · 函数 |
| 模块级 | 04 | _rollback_manifest | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 渲染契约跟产物**同进同退**：失败时还原成上一版（原本不存在的就删掉）。见 D-81。 · L66 · 函数 · ⇢ 依赖 manifest.manifest_path_for |
| 模块级 | 05 | _prepare_child | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 给一张后代子表补上 DSL（结构校验 → 转 DSL）。见 D-52。 · L81 · 函数 · ⇢ 依赖 artifact.artifact_stem、table_to_dsl.main |
| 模块级 | 06 | _gate_child_view | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 对一张**会内嵌的子表**跑几何门禁；只警告不阻断（见 D-52）。 · L108 · 函数 · ⇢ 依赖 engine.load、validate.check |
| 模块级 | 07 | _find_parent | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 这张流程表是不是别人的下钻子图？是则返回 (父图相对链接, 父节点名)，不是返回 None。 · L131 · 函数 · ⇢ 依赖 artifact.artifact_stem、flowtable.find_parent_table |
| 模块级 | 08 | _parse_args | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 解析 build 的命令行参数。 · L148 · 函数 |
| 模块级 | 09 | _check_structure | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 跑结构校验；未过则报错并返回 1。 · L164 · 函数 · ⇢ 依赖 table_to_dsl.main |
| 模块级 | 10 | _gen_dsl | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 生成 DSL（可复用已有 flow.yaml 几何）；复用时提示新增节点，失败返回 1。 · L174 · 函数 · ⇢ 依赖 table_to_dsl.main |
| 模块级 | 11 | _validate_geometry | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 跑碰撞检测；未过则报错并返回 1。 · L201 · 函数 · ⇢ 依赖 validate.main |
| 模块级 | 12 | _prepare_views | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ 备齐后代子表的 DSL（BFS 至多 5 轮），报告内嵌/缺失并返回视图计划。 · L212 · 函数 · 分支：1→_prepare_child 2→_gate_child_view · ⇢ 依赖 render_html.collect_views |
| 模块级 | 13 | _render_products | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→23｜3→25 | ★ 按**注册表**渲染全部产物；任一失败即还原旧产物并返回 None。 · L273 · 函数 · 分支：1→_rollback 2→_renderer 3→_render_ctx |
| 模块级 | 14 | _audit_contract | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→22 | ★ 拿自检产出的契约反查**注册表里的每一份产物**；不过则还原产物并返回 1。 · L310 · 函数 · 分支：1→_rollback 2→_bind · ⇢ 依赖 manifest.check、manifest.manifest_path_for、manifest.summary |
| 模块级 | 15 | _lane_source | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 底稿是不是泳道布局。 · L349 · 函数 · ⇢ 依赖 engine.load |
| 模块级 | 16 | _audit_geometry | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→22 | ★ 反解**注册表里每一份产物**的真实坐标再跑几何门禁；不过则还原产物并返回 1。 · L359 · 函数 · 分支：1→_rollback 2→_bind · ⇢ 依赖 manifest.artifact_geometry、validate.check_artifact |
| 模块级 | 17 | _write_layer_index | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 从各表 ▣ 声明派生层级索引，写 <stem>-index.md 并报告表数与层级。 · L384 · 函数 · ⇢ 依赖 layer_index.build_layer_index、layer_index.format_index_md |
| 模块级 | 18 | _product_note | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 每类产物在交付清单里那句"它是干嘛的"（与 `_render_ctx` 同理：每类一处，集中放）。 · L400 · 函数 |
| 模块级 | 19 | _report_receipt | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 留存被覆盖旧版为 .bak，并打印交付清单与 sha256 回执。 · L412 · 函数 |
| 模块级 | 20 | _report_pending | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 汇总图上 AI 推断处（虚线标出），提醒用户重点核对。 · L440 · 函数 · ⇢ 依赖 semantics.is_pending、semantics.pending_kind |
| 模块级 | 21 | build_registry | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 按**可用性**装注册表，返回 `(RENDERERS, 缺的可选件, 缺的必需件)`。 · L498 · 函数 |
| 模块级 | 22 | _bind | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 按名字现查 `globals()` 取函数——渲染器与两个**反解器**都走这里。 · L521 · 函数 |
| 模块级 | 23 | _renderer | 任务 | — | — | — | 脚本 | selfboot | — | →22 | ★ 按注册表取渲染器实例。**调用时现查 `globals()`**（理由见上面 RENDERERS 的注释）。 · L534 · 函数 |
| 模块级 | 24 | _product_paths | 任务 | — | — | — | 脚本 | selfboot | — | →27 | ★ 产物路径由注册表派生（W5）：`<流程名>-flow<ext>`。 · L539 · 函数 |
| 模块级 | 25 | _render_ctx | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 每类渲染器自己的私有选项（经 `ctx` 传，见 ARCHITECTURE.md 第九节）。 · L548 · 函数 · ⇢ 依赖 render_drawio.discover_pages |
| 模块级 | 26 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04｜3→08｜4→09｜5→10｜6→11｜7→12｜8→13｜9→14｜10→15｜11→16｜12→17｜13→19｜14→20｜15→24 | L562 · 函数 · 分支：1→_rollback 2→_rollback_manifest 3→_parse_args 4→_check_structure 5→_gen_dsl 6→_validate_geometry 7→_prepare_views 8→_render_products 9→_audit_contract 10→_lane_source 11→_audit_geometry 12→_write_layer_index 13→_report_receipt 14→_report_pending 15→_product_paths · ⇢ 依赖 artifact.artifact_stem、manifest.manifest_path_for |
| 出口 | 27 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
