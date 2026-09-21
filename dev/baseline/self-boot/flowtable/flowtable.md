---
id: selfboot-flowtable
level: L1
parent: ../flowtable.md
---

# flowtable.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→05｜5→14｜6→22｜7→23｜8→26 | 流程起点（结构性节点，不是函数） · 入口：1→Errors.__init__ 2→Errors.err 3→Errors.warn 4→Errors.ok 5→header_cells 6→build_edges 7→wrote_route 8→find_parent_table |
| Errors | 02 | Errors.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L38 · 方法 |
| Errors | 03 | Errors.err | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L49 · 方法 |
| Errors | 04 | Errors.warn | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L52 · 方法 |
| Errors | 05 | Errors.ok | 任务 | — | — | — | 脚本 | selfboot | — | →29 | L56 · 方法 |
| 模块级 | 06 | _extract_title | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 取首个 `# 标题` → 流程名；没有则用约定的 '流程图'。 · L61 · 函数 |
| 模块级 | 07 | _read_frontmatter | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 解析首部 YAML 身份区 → (meta, body_start)；语法错误记入 meta['__fm_error_… · L66 · 函数 |
| 模块级 | 08 | _locate_main_table | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 定位主表表头行号：第一个含「项目运作阶段」的表头行（配置小节的表没有这一列）；无则 None。 · L95 · 函数 |
| 模块级 | 09 | _read_layout_sections | 任务 | — | — | — | 脚本 | selfboot | — | →16 | ★ 读主表之前的「渲染配置」「主体配色」两个小节 → (cfg, colors, dup_subject)。 · L101 · 函数 |
| 模块级 | 10 | _merge_meta | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 把配置小节归一化并入 meta（键名与插入顺序不变，下游消费方零改动）。 · L117 · 函数 |
| 模块级 | 11 | _is_separator_row | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ GFM 表格分隔行判定：允许 `---` / `:---` / `:---:`（冒号对齐）。 · L129 · 函数 |
| 模块级 | 12 | _read_body_rows | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 读主表数据行：跳表头与分隔行，遇非表格行即停 → rows。 · L134 · 函数 · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 13 | split_row_cells | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 一行单元格 → 补齐/截断到 N_COLS 的列表。列**按位置**读，所以长度先对齐再取值。 · L170 · 函数 |
| 模块级 | 14 | header_cells | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 主表表头行 → 列名列表（找不到返回 None）。 · L176 · 函数 |
| 模块级 | 15 | parse_table | 任务 | — | — | — | 脚本 | selfboot | — | 1→06｜2→07｜3→08｜4→09｜5→10｜6→12 | ★ 返回 (title, meta, rows)。三区结构（D-59）：frontmatter 身份 + 正文配置小节 +… · L187 · 函数 · 分支：1→_extract_title 2→_read_frontmatter 3→_locate_main_table 4→_read_layout_sections 5→_merge_meta 6→_read_body_rows |
| 模块级 | 16 | _read_section | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 在 lines[start:stop] 里找 `## {name}` 小节，返回其表格数据行 [[c1, c2], …… · L206 · 函数 · ⇢ 依赖 semantics.split_table_row |
| 模块级 | 17 | parse_next | 任务 | — | — | — | 脚本 | selfboot | — | →21 | ★ 解析「下个节点」→ [(label, tid, is_loop)]。 · L230 · 函数 |
| 模块级 | 18 | _resolve_target | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ 把一段目标文本解析成节点 id：已知 id 优先整体匹配，字母开头的外部 id 整体返回，否则取数字编号。 · L238 · 函数 |
| 模块级 | 19 | _report_ambiguous_sep | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ H3：分号误用（`通过→05；不通过→06`）会静默丢掉第二条出口——必须拦下，见 DECISIONS.md D-04。 · L251 · 函数 · ⇢ 依赖 semantics.has_ambiguous_sep |
| 模块级 | 20 | _split_route_parts | 任务 | — | — | — | 脚本 | selfboot | — | →18 | ★ 把「下个节点」原文按分支分隔符切开，逐段解析成 (raw, label, tid, is_loop)。 · L258 · 函数 · ⇢ 依赖 semantics.split_branches |
| 模块级 | 21 | parse_next_raw | 任务 | — | — | — | 脚本 | selfboot | — | 1→19｜2→20 | ★ 同 parse_next，但多返回该分支的**原样文本**：[(raw, label, tid, is_loop)]。 · L289 · 函数 · 分支：1→_report_ambiguous_sep 2→_split_route_parts |
| 模块级 | 22 | build_edges | 任务 | — | — | — | 脚本 | selfboot | — | →17 | ★ 按「下个节点」取出边，**不做判定**；返回 (edges, dangling)。 · L301 · 函数 |
| 模块级 | 23 | wrote_route | 任务 | — | — | — | 脚本 | selfboot | — | →29 | ★ "下个节点"单元格里到底写没写内容（不判断写得对不对）——分辨"真没有出口"与"目标编号不存在"。 · L318 · 函数 |
| 模块级 | 24 | _parent_by_declaration | 任务 | — | — | — | 脚本 | selfboot | — | 1→27｜2→28 | ★ 子表 frontmatter 声明了「父表」→ 直接定位并校验回指，O(1)；未声明或校验不过返回 None。 · L325 · 函数 · 分支：1→_has_backref 2→_backref_node |
| 模块级 | 25 | _parent_by_scan | 任务 | — | — | — | 脚本 | selfboot | — | →13 | ★ 未声明的表：沿目录向上扫 `*.md`，找 ▣ 指到 me 的那张父表（一路走到盘根）；找不到 None。 · L336 · 函数 · ⇢ 依赖 semantics.subflow_ref |
| 模块级 | 26 | find_parent_table | 任务 | — | — | — | 脚本 | selfboot | — | 1→15｜2→24｜3→25 | ★ 这张流程表是不是别人的下钻子图？是则返回 (父表 Path, 父节点名)，不是返回 None。 · L365 · 函数 · 分支：1→parse_table 2→_parent_by_declaration 3→_parent_by_scan |
| 模块级 | 27 | _has_backref | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→15 | ★ 父表文件里是否存在一条 ▣ 指回 me（「父表」声明的双向一致性校验，D-58）。 · L392 · 函数 · 分支：1→split_row_cells 2→parse_table · ⇢ 依赖 semantics.subflow_target |
| 模块级 | 28 | _backref_node | 任务 | — | — | — | 脚本 | selfboot | — | 1→13｜2→15 | ★ 父表中指回 me 的那条 ▣ 所在行的节点名（面包屑显示用）。 · L407 · 函数 · 分支：1→split_row_cells 2→parse_table · ⇢ 依赖 semantics.subflow_target |
| 出口 | 29 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
