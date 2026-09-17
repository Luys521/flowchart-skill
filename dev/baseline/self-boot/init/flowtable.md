---
id: selfboot-init
level: L1
parent: ../flowtable.md
---

# init.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→05 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _reject_conflict | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ target 被同名文件或非空目录占用时打印原因并返回 True。 · L16 · 函数 |
| 模块级 | 03 | _copy_templates | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 把两份模板复制进 target；模板缺失即返回 False（调用方退 1）。 · L31 · 函数 |
| 模块级 | 04 | _print_summary | 任务 | — | — | — | 脚本 | selfboot | — | →06 | ★ 打印初始化结果与下一步指引。 · L48 · 函数 |
| 模块级 | 05 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04 | L56 · 函数 · 分支：1→_reject_conflict 2→_copy_templates 3→_print_summary |
| 出口 | 06 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
