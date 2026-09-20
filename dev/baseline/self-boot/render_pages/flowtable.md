---
id: selfboot-render_pages
level: L1
parent: ../flowtable.md
---

# render_pages.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→13 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _read_json | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 读 JSON（容忍 BOM）。 · L48 · 函数 |
| 模块级 | 03 | _write_json | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`… · L53 · 函数 |
| 模块级 | 04 | _is_pdf | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 只看 4 字节魔数：**不重判档位**（档位从账本抄）。 · L58 · 函数 |
| 模块级 | 05 | _skeleton | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 一页 → 一条**待填**的 vlm 证据骨架（`text` 空着等 AI 填）。 · L67 · 函数 |
| 模块级 | 06 | render_pdf | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→07 | ★ PDF → `(骨架元素, 渲染出的 (页号, PNG 路径) 清单, 说明)`。**单页渲不出不让整份失败**。 · L81 · 函数 · 分支：1→_skeleton 2→_import_pdfplumber |
| 模块级 | 07 | _import_pdfplumber | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ import 必须依赖 → `(模块, 报错文案)`（**提示只有一处**：`deps.import_dep`，D-1… · L107 · 函数 · ⇢ 依赖 deps.import_dep |
| 模块级 | 08 | targets | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 材料层 → 该渲哪些 → `(要渲染的, 已是图片的, 不归本工具管的)`。**按 `probe` 记的档位分派，不重… · L112 · 函数 |
| 模块级 | 09 | build | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→05｜4→06｜5→08 | ★ 渲图 + 出骨架（`--elements` 给了才写）。返回退出码。 · L133 · 函数 · 分支：1→_read_json 2→_write_json 3→_skeleton 4→render_pdf 5→targets · ⇢ 依赖 artifact.beside |
| 模块级 | 10 | _check_id | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ id 形态：`<M##>#v<页号3位><可选字母>`（同一页要拆多条时用字母后缀，如 `M15#v004b`）。 · L179 · 函数 |
| 模块级 | 11 | check_elements | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ AI 填好的骨架 → 错误清单（空 = 过）。**"没填"必须当错**（否则空骨架也能过）。 · L190 · 函数 |
| 模块级 | 12 | check | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→11 | ★ 校验填好的骨架 + 写材料层补注（`status=ok` + `extractor=vlm`）。 · L226 · 函数 · 分支：1→_read_json 2→_write_json 3→check_elements |
| 模块级 | 13 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→12 | L260 · 函数 · 分支：1→build 2→check |
| 出口 | 14 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
