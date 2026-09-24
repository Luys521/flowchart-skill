---
id: selfboot-env_probe
level: L1
parent: ../flowtable.md
---

# env_probe.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→07 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | _feishu_cfg | 任务 | — | — | — | 脚本 | selfboot | — | →08 | L54 · 函数 · ⇢ 依赖 config.plugin_config |
| 模块级 | 03 | _app_id_source | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 返回 (来源标签, 值)；都没有则 (None, None)。**只报来源，不回显敏感值**。 · L58 · 函数 |
| 模块级 | 04 | _secret_present | 任务 | — | — | — | 脚本 | selfboot | — | →02 | L71 · 函数 |
| 模块级 | 05 | probe | 任务 | — | — | — | 脚本 | selfboot | — | 1→03｜2→04 | ★ 探测并返回结构化结论。`verbose` 让插件发现打印它自己的那几行。 · L77 · 函数 · 分支：1→_app_id_source 2→_secret_present · ⇢ 依赖 config.plugin_enabled、plugin.discover |
| 模块级 | 06 | _render | 任务 | — | — | — | 脚本 | selfboot | — | →08 | ★ 人读版：LLM 可以直接照念，所以**一句话说清"我是谁、能做什么、该怎么交付"**。 · L134 · 函数 |
| 模块级 | 07 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | L151 · 函数 · 分支：1→probe 2→_render |
| 出口 | 08 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
