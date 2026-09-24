---
id: selfboot-plugin
level: L1
parent: ../flowtable.md
---

# plugin.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→05｜4→06｜5→07｜6→08｜7→09｜8→10｜9→14 | 流程起点（结构性节点，不是函数） · 入口：1→Registry.__init__ 2→Registry.register 3→Registry.get 4→Registry.meta 5→Registry.has 6→Registry.all 7→Registry.names 8→Registry.snapshot 9→discover |
| Registry | 02 | Registry.__init__ | 任务 | — | — | — | 脚本 | selfboot | — | →15 | L39 · 方法 |
| Registry | 03 | Registry.register | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 注册一个扩展实现。重复注册以最后一次为准（允许插件覆盖）。 · L42 · 方法 |
| Registry | 04 | Registry._resolve | 任务 | — | — | — | 脚本 | selfboot | — | →15 | L49 · 方法 |
| Registry | 05 | Registry.get | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 取一个扩展 callable；不存在抛 KeyError。 · L56 · 方法 |
| Registry | 06 | Registry.meta | 任务 | — | — | — | 脚本 | selfboot | — | →15 | L60 · 方法 |
| Registry | 07 | Registry.has | 任务 | — | — | — | 脚本 | selfboot | — | →15 | L63 · 方法 |
| Registry | 08 | Registry.all | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 返回 {name: callable}（已解析）。 · L66 · 方法 |
| Registry | 09 | Registry.names | 任务 | — | — | — | 脚本 | selfboot | — | →15 | L70 · 方法 |
| Registry | 10 | Registry.snapshot | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ {point: [names]}，用于打印与自检。 · L73 · 方法 |
| 模块级 | 11 | _read_manifest | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 读插件清单 plugin.yaml → dict（PyYAML 已为核心依赖）。 · L78 · 函数 |
| 模块级 | 12 | _check_requirements | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 自检插件依赖。返回缺失项列表 [{import, pip}]；全部满足返回 []。 · L87 · 函数 |
| 模块级 | 13 | _load_entry | 任务 | — | — | — | 脚本 | selfboot | — | →15 | ★ 加载插件入口并调用 register()。 · L98 · 函数 |
| 模块级 | 14 | discover | 任务 | — | — | — | 脚本 | selfboot | — | 1→11｜2→12｜3→13 | ★ 扫描 integrations/ 加载已启用插件。 · L125 · 函数 · 分支：1→_read_manifest 2→_check_requirements 3→_load_entry · ⇢ 依赖 config.plugin_config、config.plugin_enabled、console.warn |
| 出口 | 15 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
