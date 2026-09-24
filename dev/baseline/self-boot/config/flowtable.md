---
id: selfboot-config
level: L1
parent: ../flowtable.md
---

# config.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→05｜2→06 | 流程起点（结构性节点，不是函数） · 入口：1→plugin_enabled 2→env_or_config |
| 模块级 | 02 | _read_yaml | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 读一个 yaml → dict；文件不存在返回 {}；读不动留痕并返回 {}。 · L30 · 函数 · ⇢ 依赖 console.warn |
| 模块级 | 03 | global_config | 任务 | — | — | — | 脚本 | selfboot | — | →02 | ★ 技能根全局配置（含 `integrations: {name: {enabled: ...}}` 开关）。 · L46 · 函数 |
| 模块级 | 04 | plugin_config | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03 | ★ 插件私有配置：`integrations/<name>/config.yaml`，再叠全局里该插件的段与环境变量。 · L51 · 函数 · 分支：1→_read_yaml 2→global_config |
| 模块级 | 05 | plugin_enabled | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 该插件是否启用。**默认关闭**（缺省即 False，保证零凭证可跑、不误连平台）。 · L64 · 函数 |
| 模块级 | 06 | env_or_config | 任务 | — | — | — | 脚本 | selfboot | — | →04 | ★ 插件取一个值：先环境变量（keys 依次试），再配置 dict，最后默认。 · L86 · 函数 |
| 出口 | 07 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
