---
id: selfboot-shot
level: L1
parent: ../flowtable.md
---

# shot.py 函数流程表

> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 `qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 入口 | 01 | 开始 | 开始 | — | — | — | 脚本 | selfboot | — | 1→09 | 流程起点（结构性节点，不是函数） · 入口：1→main |
| 模块级 | 02 | find_browser | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 显式路径也要**验存在**（G55）：原样返回的话，`subprocess.run` 会抛 · L27 · 函数 |
| 模块级 | 03 | build_crop_page | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 把 flow.html 的内联 SVG 裁到 [y0,y1) 区间，保留原 <style>（否则 class 失效全变… · L39 · 函数 |
| 模块级 | 04 | _parse_args | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 解析命令行参数。 · L63 · 函数 |
| 模块级 | 05 | _output_path | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 输出 PNG 路径（默认同目录同名 .shot.png），父目录不存在则先建。 · L74 · 函数 |
| 模块级 | 06 | _parse_crop | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ --crop 形如 0:1200 → (y0, y1)；非法时第三项为错误文案。 · L82 · 函数 |
| 模块级 | 07 | _unlink_quiet | 任务 | — | — | — | 脚本 | selfboot | — | →10 | ★ 删文件；不存在或删不掉都静默忽略。 · L106 · 函数 |
| 模块级 | 08 | _capture_screenshot | 任务 | — | — | — | 脚本 | selfboot | — | →07 | ★ 起无头浏览器对裁剪页截图并轮询等文件落盘；成功返回 True。 · L114 · 函数 |
| 模块级 | 09 | main | 任务 | — | — | — | 脚本 | selfboot | — | 1→02｜2→03｜3→04｜4→05｜5→06｜6→07｜7→08 | L134 · 函数 · 分支：1→find_browser 2→build_crop_page 3→_parse_args 4→_output_path 5→_parse_crop 6→_unlink_quiet 7→_capture_screenshot |
| 出口 | 10 | 结束 | 结束 | — | — | — | 脚本 | selfboot | — | — | 流程终点（结构性节点，不是函数） |
