---
id: selfboot-serve
level: L1
parent: ../flowtable.md
---

# serve.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→11｜2→12｜3→13 | 流程起点（结构性节点，不是函数） · 入口：1→main 2→_http.health 3→_http.invoke |
| 模块级 | 02 | _jsonable | 任务 | — | — | — | 脚本 | selfboot | — | →03 | ★ 把 Path / 嵌套容器转成可 JSON 序列化的普通值。 · L38 · 函数 |
| 拆环 | 03 | 递归边界？ | 判断 | — | — | — | 脚本 | selfboot | — | 是→14｜否→02 | 结构性判断（拆环）：_jsonable 直接递归自己。是 → 收尾（结束）；否 → 走下一跳（_jsonable）。 |
| 模块级 | 04 | load_registry | 任务 | — | — | — | 脚本 | selfboot | — | →14 | ★ 加载插件：--plugin 指定时只加载并强制启用这些插件；否则按配置/环境（默认全关）。 · L49 · 函数 · ⇢ 依赖 plugin.discover |
| 模块级 | 05 | _act_source | 任务 | — | — | — | 脚本 | selfboot | — | →02 | L59 · 函数 |
| 模块级 | 06 | _act_publish | 任务 | — | — | — | 脚本 | selfboot | — | →02 | L68 · 函数 |
| 模块级 | 07 | _act_build | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L77 · 函数 |
| 模块级 | 08 | run_request | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06｜3→07 | L97 · 函数 · 分支：1→_act_source 2→_act_publish 3→_act_build |
| 模块级 | 09 | _single | 任务 | — | — | — | 脚本 | selfboot | — | 1→04｜2→08 | L111 · 函数 · 分支：1→load_registry 2→run_request |
| 模块级 | 10 | _http | 任务 | — | — | — | 脚本 | selfboot | — | →04 | L125 · 函数 |
| 模块级 | 11 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→09｜2→10 | L158 · 函数 · 分支：1→_single 2→_http |
| _http | 12 | _http.health | 任务 | — | — | — | 脚本 | selfboot | — | →14 | L139 · 嵌套函数 |
| _http | 13 | _http.invoke | 任务 | — | — | — | 脚本 | selfboot | — | →08 | L143 · 嵌套函数 |
| 出口 | 14 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
