---
id: selfboot-render_mermaid
level: L1
parent: ../flowtable.md
---

# render_mermaid.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→08｜2→09 | 流程起点（结构性节点，不是函数） · 入口：1→read_mermaid 2→main |
| 模块级 | 02 | _mid | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ DSL id → Mermaid 节点 id：清洗后统一加 n 前缀（保证字母开头、唯一、可逆）。 · L16 · 函数 |
| 模块级 | 03 | _unmid | 任务 | — | — | — | 脚本 | selfboot | — | →11 | L21 · 函数 |
| 模块级 | 04 | _txt | 任务 | — | — | — | 脚本 | selfboot | — | →11 | ★ 文本放进双引号里；转义井号与双引号（Mermaid 实体写法）。 · L25 · 函数 |
| 模块级 | 05 | _node | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | L30 · 函数 · 分支：1→_mid 2→_txt |
| 模块级 | 06 | _edge | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→04 | L39 · 函数 · 分支：1→_mid 2→_txt |
| 模块级 | 07 | render | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | ★ DSL → .mmd。成功返回 0（统一契约；ctx 本渲染器不用）。 · L47 · 函数 · 分支：1→_node 2→_edge · ⇢ 依赖 engine.load |
| 模块级 | 08 | read_mermaid | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→10 | ★ 从自产 .mmd 反解 (节点 id 列表, 边列表)；id 去掉 n 前缀还原为 DSL id。 · L58 · 函数 · 分支：1→_unmid 2→read_mermaid.add |
| 模块级 | 09 | main | 任务 | — | — | — | 脚本 | selfboot | — | →07 | L83 · 函数 |
| read_mermaid | 10 | read_mermaid.add | 任务 | — | — | — | 脚本 | selfboot | — | →03 | L66 · 嵌套函数 |
| 出口 | 11 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
