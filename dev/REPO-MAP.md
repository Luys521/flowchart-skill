# REPO-MAP.md — 仓库数据流地图

> 用途：回答"**每个脚本消费什么、生产什么、发生在哪个环节、谁生成给它、谁消费它、人和 AI 各在哪一步介入**"。
> 与 `ARCHITECTURE.md` 分工：本文写**数据怎么流**，`ARCHITECTURE.md` 写**模块怎么切、为什么这么切**。
> 事实来源：接口面由 `ast` 从 `scripts/*.py` 提取；产物清单由实际落盘文件实证（见第六节复跑方法）。

## 一、主干：一条链 + 一个闭环

```text
flowtable.md ──► <流程名>-flow.yaml ──► <流程名>-flow.html
（事实源）        （内部 DSL）      ├► <流程名>-flow.drawio
                                  └► <流程名>-flow.svg
        ▲                                        │
        └──── sync.py（回写）◄── 人在 drawio 里微调 ─┘
```

三件"可交付中间件"的存在决定了模块边界：**流程表**（人可改）→ **DSL**（几何可手调）→ **三份产物**（可独立复核）。

## 二、七个环节 × 命令 × 执行者 × 输入 × 输出

| 环节 | 命令 | 谁在做 | 消费什么 | 产出什么 |
|---|---|---|---|---|
| 0 承接上下文 | `clarify.py <表>` | **AI** | `flowtable.md`（若已有） | stdout：frontier / 简报（`--json` 结构化）；不落文件 |
| 1 建目录 | `init.py <名称>` | 脚本 | `templates/*.md` 两份模板 | `output/<名称>/flowtable.md` + `checklist.md` |
| 1 落表 | （无命令） | **AI**（人给原始材料） | 合同/散表/白板/已有图 | 填好的 `flowtable.md` |
| 2 结构校验 | `table_to_dsl.py --check <表>` | 脚本（**阻断**） | `flowtable.md` | exit 0/1 + `{message, subject, fix}` |
| 2' 转 DSL | `table_to_dsl.py --write <表>` | 脚本 | `flowtable.md` | `<名>-flow.yaml` + `<名>-flow.manifest.json` |
| 3 自检留痕 | （无命令） | **AI** | `templates/checklist-template.md` | `checklist.md`；表内 `⚠` / `⚠?` 标记 |
| 3 问缺口 | `clarify.py <表>` | **AI 问 → 人答** | 表里的 `⚠?` | 人给的裁决 → 改表 → 重跑直到 frontier 空 |
| 4 渲染 | `build.py <表>` | 脚本（六环全自动） | `flowtable.md`（+ 已有 `.yaml` 几何） | `<名>-flow.html` + `<名>-flow.drawio` + `<名>-flow.svg` + `<名>-index.md` |
| 4' 单环复核 | `validate.py <yaml>` / `--artifact <产物>` | 脚本 | DSL 或产物 | exit 0/1 + 几何表（`--dump`） |
| 4'' 视觉自检 | `shot.py <html>` | 脚本截图 → **AI/人看图** | `<名>-flow.html` | `<名>-flow.shot.png`（中间物，可删） |
| 5 微调 | （人在 drawio 里操作） | **人** | `<名>-flow.drawio` | 改好的 `.drawio` |
| 5 回写 | `sync.py <drawio> <表> [--apply]` | 脚本 | `.drawio` + `flowtable.md` | 预览 `flowtable.sync.md`；`--apply` 后覆盖原表并重渲染 |
| 5' 只读差异 | `xml_reader.py <drawio> --diff <表>` | 脚本 | `.drawio` + `flowtable.md` | stdout 结构差异（**不含**逐字节复核——那条在 `sync.py`，D-123） |
| 入口 B | `xml_reader.py <图>` | 脚本 | 外部 `.drawio` / 图片 | stdout 拓扑摘要 |

**`build.py` 跑起来的六环**（全部脚本自动，AI 不介入）：① 结构校验 → ② 生成 DSL → ③ 碰撞检测（八项）→ ④ 渲染交付物 → ⑤ 产物审核（契约反查）→ ⑥ 产物几何自检。**② 环内**是引擎的分段：节点类型分析 → 关系分析 → 空间规划 → 节点连接。前三环读《流程表》与 DSL、**都不看产物**，所以第 ⑤ 环拿契约反查产物把最后一环焊上。

## 三、产物规范（格式 / 路径 / 命名 / 生成者 / 消费者）

命名规则的**唯一出处**是 `scripts/artifact.py`（`artifact_stem` / `artifact_rel`，见 D-51）——任何地方不许再拼一遍。

| 产物 | 格式 | 路径与命名 | 生成者 | 消费者 | 交付 |
|---|---|---|---|---|---|
| `flowtable.md` | Markdown + frontmatter | `output/<名称>/flowtable.md`（约定名，**身份在目录名**） | `init.py` 拷模板 → **AI 填** | `table_to_dsl` `clarify` `build` `sync` `layer_index` `writeback` | **是**（语义变更唯一入口） |
| `checklist.md` | Markdown | `output/<名称>/checklist.md`（固定名） | **AI** 按模板自查 | 人（留痕，随交付） | **是** |
| `<流程名>-flow.yaml` | YAML | 同目录；`artifact_stem` 取名 | `table_to_dsl --write` | `build` `validate` `render_html` `render_drawio` `render_svg` | 否（几何可手调、语义禁改） |
| `<流程名>-flow.manifest.json` | JSON | 同目录 | `table_to_dsl` | `build`（审核反查）、`manifest.py` 自身 | 否（自检产出） |
| `<流程名>-flow.html` | 单文件 HTML | 同目录 | `render_html` | 人（评审）；作为 `shot.py` 输入 | **是**（交付物①） |
| `<流程名>-flow.drawio` | drawio XML | 同目录 | `render_drawio` | **人**（微调几何）；回给 `sync` / `xml_reader` | **是**（交付物②） |
| `<流程名>-flow.svg` | SVG | 同目录 | `render_svg` | 人（Inkscape / 浏览器直接开） | **是**（交付物③） |
| `<流程名>-index.md` | Markdown | 同目录 | `layer_index` | 人 | 否（派生物） |
| `<流程名>-flow.shot.png` | PNG | 同目录 | `shot.py` | AI/人看图 | 否（自检中间物，可删） |
| `<子表名>-flow.*` | 同上 | `output/<名称>/parts/<子流程名>/` | 各自的生成器 | 同主流程；子图 **html 不单独落盘**（内嵌进主 html，D-52） | 随主交付 |

**命名规则**：表名是约定名（`flowtable.md`）→ 用**目录名**；否则用**表名**；都取不到退回 `flow`。
**写盘纪律**：产物名一旦需要第二处拼装就会漂移，而漂移的后果（链接指向不存在的文件）**不报错、只在用户点开时才暴露**——所以只许引用 `artifact.py`。

**实际落盘实例**（`dev/baseline/workflow/`，主流程 + **7** 张子表，20 个文件；事实源只有 8 张 `flowtable.md`，
住在 `examples/workflow/`——见 D-66）：

```text
workflow-flow.yaml                    workflow-flow.manifest.json
workflow-flow.html                    workflow-flow.drawio
workflow-flow.svg                     workflow-index.md
parts/<子流程名>/<子流程名>-flow.{yaml,manifest.json}     × 7
```

> 子表的 html **不单独落盘**（内嵌进主 html，D-52）；子表也没有自己的 `-index.md` 与 drawio 单页文件
> （层级由主 drawio 的多页承载，见 D-47/D-51）。

## 四、脚本接口面（机器提取）

**46 个模块 = 30 个带 CLI 的入口 + 16 个纯库。**

| 类型 | 模块 |
|---|---|
| 入口命令（有 `__main__`） | `init` `table_to_dsl` `build` `validate` `shot` `sync` `xml_reader` `clarify` `layer_index` `manifest` `render_html` `render_drawio` `render_svg` `writeback` `probe` `parse` `recon` `parse_ooxml` `parse_pdf` `parse_legacy` `parse_text` `render_pages` `intake` `ledger` `drift` `query` `import_table` `plan` `cells` `capability` |
| 纯库（无 CLI，只被 import） | `artifact` `deps` `engine` `flowtable` `flowtable_check` `flowtable_colors` `flowtable_layout` `geometry` `label` `lane_router` `pptx_text` `router` `semantics` `swimlane` `textquality` `thresholds` |

**分层（2026-09-14 定，由 `dev/tools/layering.py` 守住）**：

| 层 | 模块 | 规则 |
|---|---|---|
| **公共层**（21） | `semantics` `geometry` `artifact` `cells` `capability` `thresholds` `deps` `textquality` `pptx_text` `flowtable_layout` `flowtable` `flowtable_check` `flowtable_colors` `router` `lane_router` `swimlane` `label` `engine` `manifest` `xml_reader` `writeback` | 被多方复用的纯能力；**可以互相引用**，但**不许依赖上层** |
| **模块层**（22） | `init` `clarify` `table_to_dsl` `layer_index` `render_html` `render_drawio` `render_svg` `validate` `shot` `probe` `recon` `parse_ooxml` `parse_pdf` `parse_legacy` `parse_text` `render_pages` `import_table` `intake` `plan` `ledger` `drift` `query` | 各有产物；**只许依赖公共层**；彼此之间**没有代码依赖**——协作走产物 |
| **编排层**（3） | `build` `sync` `parse` | 流水线驱动者，允许依赖上面两层（`parse` 按固定顺序跑各解析适配器，判据不在它那里）。**没有批量/并行出图**：起草过一版最小形态，2026-09-19 裁决撤销（`PIPELINE-SPEC` §7 / D-126），多条流程就一条一条跑 `build.py` |

实测（46 模块 / 119 条依赖边）：`module→public` 66 条 · `orch→module` 9 条 · `orch→orch` 1 条 ·
`orch→public` 14 条 · `public→public` 29 条 · **违规 0 条**（数字随代码增长，现跑现取：`python dev/tools/layering.py`）。
**这一行曾经悄悄漂过**：`public→public` 在 D-123 拆掉公共层那个环时从 30 掉到 29，而这里一直写着 30 / 120
（2026-09-19 用 `git show <旧提交>:scripts/` 现算对出来的）——**面① 只核模块数与三层名册，不核依赖边数**
（原因见上：边数来自 `fn-graph.json` 快照），所以这个数字是**没人守的**，改代码时顺手对一眼。
**这张名册由面① 现算对账**（`dev/verify/contract.py`：模块数 / CLI 数 / 三层名册逐个核）——
2026-09-19 实测它曾漂过四个模块（写 40 个、实为 44 个，漏了 `cells` `plan` `import_table` `capability`），
而当时的门禁全绿；依赖边数**不归面①**（它来自 `fn-graph.json` 快照，快照旧了归门⑦）。

**归层的判据不是"名字听起来像哪层"，而是"谁依赖谁"**——只被依赖、或只在公共层内互引的，才够格进公共层。三条容易看错的地方：`engine` 对外只 1 个函数（`load`）却依赖 6 个，是**装配门面**；`router`↔`lane_router`、`render_html`↔`render_drawio`↔`render_svg`、`geometry`↔`swimlane` 是**同一接口的多种实现**（按「输出布局」二选一、按产物类型三选一，不是重复代码）；`manifest` / `xml_reader` / `writeback` 看着像"工序"，但它们提供的是被多方复用的纯能力，属公共层。**模块层不许横向 import 这条曾被破过一次**：`manifest` 为了取一个字符串常量反向 import 了模块层的 `render_html`（一行函数体内的延迟 import，读代码看不见）——已修，现在由门禁守住。

**接口面的两条判据**（来自 `ARCHITECTURE.md` 第四节）：产物出现**第二个消费者**时不许合并（会被逼出第二份实现）；**文档承诺过的公开命令**（`table_to_dsl --check` / `validate.py --artifact` / `manifest.py check`）所在模块不许并进入口脚本，否则用户失去"只跑一环"的能力。

## 五、人与 AI 的介入点

| 环节 | AI | 脚本（机器阻断） | 人 |
|---|---|---|---|
| 0 承接上下文 | **复述业务事实**（不等回复就往下走） | — | 可当场纠正 |
| 1 建目录 | — | `init.py` | — |
| 1 落表 | **填表**（主动提问、补缺失项） | — | 提供原始材料 |
| 2 校验 | 按报错改表 | **`table_to_dsl --check` 阻断** | — |
| 3 自检 | **打 `⚠`（有依据的推断，不问）/ `⚠?`（推不出，必须问）** | — | — |
| 3 问缺口 | **问一句**（每问必附推荐答案，人只需否决） | `clarify.py` 排 frontier | **答** |
| 4 渲染 | 不介入 | **`build.py` 六环全自动** | — |
| 4'' 视觉自检 | **看图判断**（交叉是否碍眼、标签是否压线） | `shot.py` 出图 | 看图 |
| 5 微调 | — | — | **独占**：drawio 里拖几何、双击改节点名 |
| 5 回写 | 解释差异 | `sync.py` 回写并重渲染 | 确认差异后才 `--apply` |
| 5 冲突 | 说明冲突点 | **`sync.py` 默认拦截（exit 1）** | **裁决**：确如图对才 `--force` |
| 最终验收 | — | — | **独占**：只对最终渲染图负责 |

两条设计意图：**"不逐条审流程表"**（用户不会打开中间产物）与**"推不出的决策必须问一句"**并不矛盾——前者省掉人对中间产物的负担，后者把 AI 的不确定性逼到**图上**（`⚠` 节点渲染成醒目虚线框），落在用户唯一会看的那个东西上。

## 六、怎么复跑这份地图

```text
# 接口面（CLI 参数 / 公开函数 / 模块依赖）——从代码提取，不手写
python - <<'PY'
import ast, os, json
# 逐文件 ast.parse：扫 argparse 的 add_argument 字面量、模块级公开函数、
# __main__ 入口；模块依赖取 dev/tools/fn-graph.json 的 imports
PY

# 产物清单——看真实落盘，不看文档自述
ls dev/baseline/workflow/ dev/baseline/workflow/parts/*/

# 图与代码是否同步（本文的地图依赖它）
python dev/tools/fn_graph.py && python dev/tools/coverage.py --tables-root output/self-boot
```

> **注意**：`dev/tools/fn-graph.json` 是**快照**。代码改了必须重跑 `fn_graph.py` 与 `selfboot_gen.py`，
> 否则拿旧图裁决新代码——实测过一次：图比代码旧一个提交时，`coverage.py` 报 100%，重跑后立刻变成"缺失 1"。
> 这条顺序**目前只有前半段有仪器**（门⑦ `graph_is_stale` 比对 `scripts/*.py` ↔ 图的指纹），
> 后半段（重跑生成器）靠人记——见 `dev/coding-spec.md` 第三节 G1。
