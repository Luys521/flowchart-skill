# COHESION-AUDIT.md — 内聚 / 耦合账单与**逐个裁决**

> 状态：**2026-09-19 立（D-125）**，本文件是 `dev/tools/cohesion.py` 三张清单里
> **"单消费方公共函数"那一张**的全量裁决留档，外加两处**结构性重复**（`esc` / 边标签）的终审。
> 读者：**动 `scripts/` 边界的人**。出图时的 AI 不需要读它（维护区，见 `dev/REPO-MAP.md`）。
> 先读：`dev/coding-spec.md` G5（"第二个消费者"判据）与 N3（不抽哪些进公共层）。
> **它不是门禁**：本文件里没有一条会红——`cohesion.py` 只报，"该不该动"是人判。这里记的
> 是**判过之后**的结论与判据，好让下一次不必从零再判一遍（D-120 立这台仪器就是因为上次量完
> 就把脚本删了）。

## 0 怎么复现这张账单

```bash
python dev/tools/cohesion.py                     # 三张表（重复 / 接口面宽度 / 单消费方）
python dev/tools/cohesion.py --single --limit 0  # 本文件 §1 的 46 行，全打
python dev/tools/cohesion.py --cycles            # 允许边上的环（读数；硬判据在面③，D-127）
```

`--limit` 是 D-125 补的：原先只打前 20 行，**仪器打印不出它要审的那张清单**——
裁决 46 条得改代码才能看见全部，那等于没有仪器。三张表各自的阈值都能从命令行调。

**每次读数**（`2026-09-19`，`dev/tools/fn-graph.json` 同版）：重复对 **2** ·
被 import 的公共模块 **31** 个（87 次 import，一次带进来的名字数**中位 1、均值 2.4、最大 10**）·
单消费方公共函数 **46** 个。

**码可以叠加**（如 `K3+K5`）：一个函数同时是"契约里的名字"与"一行转发"时，两句话都成立。

## 1 46 条单消费方公共函数：逐个裁决

**先说这个词的射程**（不先说清，后面每条都会读歪）：`cohesion.py` 数的是
"**只被一个模块 `import`**"，不是"只有一个调用点"。实测两处偏差：

| 偏差 | 读数 |
|---|---|
| **另有同模块调用点** | 46 条里 **17 条**（如 `writeback.branch_conflicts` 同时被 `writeback.write` 用，`scripts/writeback.py:334`） |
| **连 `名字(...)` 调用点都没有** | 3 条：`xml_reader.geometry`（别名调用 `_geom(...)`，`scripts/manifest.py:279`）· `manifest.read_svg` / `manifest.geometry_from_svg`（**消费者是注册表里的一个字符串**，`scripts/build.py:479`） |

第二类是**最要紧的一条读数**：`build.py` 的渲染器注册表按**名字**现查
（`_bind(name) = globals()[name]`，`scripts/build.py:507`），而且要查**两个**反解器
（`ids` 反查节点边、`geom` 反查几何）。所以对这 6 条反解器
（`read_html` / `read_drawio` / `read_svg` / `geometry_from_html` / `geometry_from_drawio` /
`geometry_from_svg`）来说，"单消费方"是**双重误导**：它们不是"只有一个消费者"，
而是"消费者是**插件契约里的一个名字**"——名字没了，那个产物就没人复核（`hygiene` 看不见这类消费者）。

### 1.1 裁决码（封闭五类）

| 码 | 意思 | 并回调用方会怎样 |
|---|---|---|
| **K1** | **判据 / 复核的具名入口** | 同一条判据碎进调用方——两份产物各写一遍，必漂 |
| **K2** | **同一接口的两种实现** | N3 / N21 已判不合并（接口边界，不是重复代码） |
| **K3** | **插件契约的一半**（按名字现查的反解器 / 指纹） | 注册表指空，那个产物失去复核 |
| **K4** | **公共层内部的两半**（两边都在公共层，装配由上层做） | 等于把公共层劈开，或让调用方自己拼 |
| **K5** | **一处收口用的薄壳**（刻意的转发，把"读某个源"收成唯一口径） | 口径又变成 N 份 |
| **K6** | **同一判据的两种输入形态**（摘要器不许把整份 zip 拉进内存 ⇒ 路径版与字节版成对） | 要么摘要器变贵，要么摘要与读者各判一次（必漂） |

### 1.2 全量 46 条

行数 = `cohesion.py` 现算的函数体行数（含文档串）；`消费者的层` 用 `dev/tools/layering.py` 的集合判。

| # | 函数 | 消费者 | 行 | 码 | 判据（为什么不该并回） |
|---|---|---|---|---|---|
| 1 | `writeback.branch_conflicts` | `sync`（编排） | 46 | K1 | 「下个节点」列 vs drawio 实际连线的**方向性**冲突（D-45）唯一判据；并回 `sync` 则 `writeback.write` 那份自纠没法复用 |
| 2 | `flowtable_check.check_evidence` | `table_to_dsl`（模块） | 40 | K1 | H10.1 引用完整的落点；姊妹判据 `intake.check_cards` 各核各的产物，两条都在公共层 |
| 3 | `manifest.check` | `build`（编排） | 35 | K1 | 契约 vs 产物逐项一致的唯一判据（不是"给个总数"） |
| 4 | `semantics.subflow_ref` | `flowtable`（公共） | 29 | K4 | 公共层内部两半：`semantics` 管跨模块文本约定、`flowtable` 管表解析（D-47） |
| 5 | `xml_reader.geometry` | `manifest`（公共） | 24 | K3+K4 | 读回结果 → 几何表；`manifest.geometry_from_drawio` 以别名调它（`scripts/manifest.py:279`） |
| 6 | `flowtable_check.check_nodes` | `clarify`（模块） | 22 | K1 | ① 节点层判据；`clarify` 要"可进流程的节点列表"就得跑**同一条** |
| 7 | `flowtable_colors.resolve_colors` | `table_to_dsl`（模块） | 22 | K4 | 声明 + 向上继承（D-49 / D-59）；消费者是"把配色写进 DSL 的那一步" |
| 8 | `flowtable_layout.assign_slots` | `flowtable_check`（公共） | 22 | K4 | 槽位求解；`table_to_dsl` 走 `flowtable_layout` 的另外几个入口 |
| 9 | `flowtable_layout.reuse_hint` | `table_to_dsl` | 21 | K4 | `--layout` 借用提示；纯算式，出度 0 |
| 10 | `xml_reader.brief` | `sync` | 21 | K1 | 拓扑摘要（人/AI 读）；"改了图先看一眼"的落点 |
| 11 | `flowtable_check.check_header` | `table_to_dsl` | 20 | K1 | H9 表头三区规范（D-59） |
| 12 | `textquality.verdict` | `parse`（编排） | 18 | K1 | 抽取质量门判决（§1.5 手段 0）——三级处置不许由分派器自己发明 |
| 13 | `writeback.write` | `sync` | 18 | K1 | 回写闭环主入口；D-123 后 `xml_reader` 不再碰它 |
| 14 | `geometry.ortho_cross` | `lane_router`（公共） | 17 | K4 | 几何谓词；`router` 用同模块的另外几个 |
| 15 | `flowtable_colors.subject_map` | `table_to_dsl` | 16 | K4 | 按出现顺序 / 按泳道序取色 |
| 16 | `flowtable_layout.apply_swimlane` | `flowtable_check` | 16 | K4 | 泳道布局；`check` 要的是**同一句**"行 = 阶段、列 = 主体" |
| 17 | `manifest.build` | `table_to_dsl` | 15 | K3 | DSL → 契约清单（**写**的那一半；`check` 是核的那一半） |
| 18 | `flowtable_layout.merge_parallel_branches` | `table_to_dsl` | 14 | K4 | 并行分支并排；纯算式 |
| 19 | `manifest.read_html` | `build` | 14 | K3 | 注册表 `ids`：`scripts/build.py:475` |
| 20 | `pptx_text.other_text_parts` | `parse_ooxml`（模块） | 14 | K6 | 摘要器（`recon`）与读者（`parse_ooxml`）**共用同一句**判据的落点 |
| 21 | `writeback.compare_bytes` | `sync` | 14 | K1 | 文件级复核（D-123 换 owner 后归 `sync`） |
| 22 | `flowtable._has_backref` | `flowtable_check` | 13 | K4 | 父表 `⊞` 双向一致（D-58）；解析归 `flowtable` |
| 23 | `pptx_text.scan_cost` | `recon` | 12 | K6 | 护栏按"要读的部件"算（§1.5 手段 1a：42 MB 演示稿那次的教训） |
| 24 | `manifest.geometry_from_html` | `build` | 11 | K3 | 注册表 `geom`：`scripts/build.py:476` |
| 25 | `pptx_text.slides_in_file` | `recon` | 11 | K6 | 摘要侧的按路径读法（与读者的 `slides` 同一句） |
| 26 | `flowtable.parse_next_raw` | `writeback`（公共） | 10 | K4 | `parse_next` 的原样文本版；回写需要 raw（`parse_next` 自己压过） |
| 27 | `geometry.point_seg_dist` | `validate`（模块） | 10 | K4 | 几何谓词；出度 0 的公共层是它们的家 |
| 28 | `textquality.scar` | `parse` | 10 | K1 | 降级留痕挂载（§2.4）；"丢了必须记账"不许散进各适配器 |
| 29 | `xml_reader.diff` | `sync` | 10 | K1 | 结构差异判据（D-123 后只报结构、并指路 `sync`） |
| 30 | `flowtable.header_cells` | `flowtable_check` | 9 | K4 | 表头行 → 列名；与 `parse_table` 同一份列约定 |
| 31 | `manifest.geometry_from_drawio` | `build` | 8 | K3 | 注册表 `geom`：`scripts/build.py:478` |
| 32 | `manifest.read_svg` | `build` | 8 | K3+K5 | **一行转发**到 `read_html`，但它是注册表 `ids` 里的**名字**（`scripts/build.py:479`）；名字不是装饰 |
| 33 | `manifest.source_fingerprint` | `table_to_dsl` | 8 | K3 | 事实源指纹（"表自上次渲染后动过没有"） |
| 34 | `textquality.readout` | `parse` | 8 | K1 | 丢前 / 丢后两次读数**同一句人话**（夹具 52 断言它必须被打出来） |
| 35 | `flowtable_layout.parse_lane_order` | `table_to_dsl` | 7 | K4 | 「- 泳道列序：A → B → C」的解析；分隔符兼容一处写 |
| 36 | `manifest.read_drawio` | `build` | 7 | K3 | 注册表 `ids`：`scripts/build.py:477`；复用 `xml_reader` 已会跳标题/图例/底色 |
| 37 | `pptx_text.other_text_parts_in_file` | `recon` | 7 | K6 | 上一条的按路径版（摘要不许把整份 zip 拉进内存） |
| 38 | `pptx_text.slides` | `parse_ooxml` | 7 | K6 | 读者侧：`pptx` 字节 → 每张一 element |
| 39 | `manifest.dsl_fingerprint` | `table_to_dsl` | 6 | K3 | DSL 指纹（"契约是否已过期"的输入） |
| 40 | `semantics.has_ambiguous_sep` | `flowtable` | 6 | K4 | 「下个节点」里把分号当分隔符用——语义约定归 `semantics` |
| 41 | `textquality.load_thresholds` | `parse` | 6 | K5 | **刻意的两行壳**：读取口径只有一处（`thresholds.load`，D-121），六个模块都留同样的壳 |
| 42 | `writeback.format_conflicts` | `sync` | 6 | K1 | 冲突文案唯一出处；**本轮改掉了它的文档串**（原先写"`sync` / `xml_reader` 共用"，而 `xml_reader` 从 D-123 起不再碰它——注释宣称的消费者必须真的存在） |
| 43 | `flowtable.wrote_route` | `flowtable_check` | 4 | K4 | "写没写内容"（不判对错）——分辨"真没出口"与"编号不存在" |
| 44 | `geometry.rects_overlap` | `validate` | 4 | K4 | 矩形相交（贴边不算）；几何门九项的共同底座 |
| 45 | `semantics.text_width` | `label`（公共） | 4 | K4 | 文本宽度估算（CJK 全角）；SVG 无自动排版，必须自己推进 `x` |
| 46 | `manifest.geometry_from_svg` | `build` | 3 | K3+K5 | 同 #32：一行转发，但注册表 `geom` 的名字（`scripts/build.py:480`） |

**结论：46 / 46 保留，零搬迁、零合并。** 没有一条是"该并回调用方"——
逐一读下来，46 条里每条的"单消费方"都对应一种**已经存在的理由**（判据入口 / 契约名字 /
公共层内部分工 / 刻意的薄壳），而不是"第二个消费者还没出现"。

**这次裁决产出的唯一代码改动**：`scripts/writeback.py` 的 `format_conflicts` 文档串
（第 #42 行那条）——**审计的价值常常不在"改了什么"，而在"把说过的话跟现状对了一遍"**。

**什么时候该回来翻这张表**：某条函数的消费者变成 **2 个以上**时（那就不是"裁决"而是"它成了公共
接口"，按 G5 该给它一个名字与文档串）；或者某个反解器名字从 `build.py` 的注册表里被删掉时
（K3 那 6 条会**静默**失去消费者，而 `hygiene` 看不见）。

## 2 `esc`：三份同名转义——**按 N3 不动**，但补一个落点在产物上的守门人

**读数**（逐字抄自源码，`2026-09-19`）：

| 位置 | 行 | 转义集 |
|---|---|---|
| `scripts/render_html.py:183` `esc` | 3 | `& < > "` |
| `scripts/render_svg.py:64` `_esc` | 3 | `& < > "` |
| `scripts/render_drawio.py:24` `esc` | 6（含注释） | `& < > "` |

三份**逐字同体**（`replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')`），
而 `render_drawio.esc` 的注释**已经**写着"刻意自留一份，不抽公共层"。

**裁决：维持 N3 的"不抽"。** 两条理由，都不是"懒得抽"：

1. **它是 markup 层的东西**，而模块层零横向 `import` 是门⑦底线——要共用就必须上公共层；
2. **抽了要重证 html 的逐字节基线**，而收益是"三处各 1 行变一处 1 行"。按 G5 / ARCHITECTURE 第四节，
   **只有一个消费者（这里是一份产物一个消费者）的抽象先不抽**。

**但 N3 那句判断当年只是一句承诺，没有守门人**：谁都可以在某一份里少转义一个字符，另两份照样出图，
而**没有任何仪器会响**——三份产物各自看都"能打开"，只有把特殊字符喂进去才现形。
`cohesion --dups` 也看不见它（`esc` 只有 1 条语句，低于 `--min-stmts 5`；**这是那台仪器已知的盲区**，
不是它坏了）。

所以 D-125 补的是一条**落在产物上**的判据（`dev/verify/gates.py::_check_escape`，进面②）：

- 自造一张含 `A<B&C"` 的节点名与 `标<签&"→03` 的边标签的表，跑 `build.py`；
- 断言三份产物里**原文串一处都不许原样出现**，且 `&lt;` / `&amp;` **都在**。

**为什么判据落在产物上而不是落在一段公共代码上**：① 产物是真正交付的东西，
"三份同口径"这句话的射程本来就是**产物**；② 落在公共代码上等于**顺手把 N3 推翻**
（要先抽公共层才谈得上守它），而这次要守的恰恰是"不抽也不许漂"；③ 产物级判据对将来
"真抽了公共层"同样成立——**它不预设实现**。

## 3 边标签：三份发射器**不是重复**——N3 原判据站得住

**读数**（函数体行数，`cohesion.py` 现算）：

| 产物 | 标签相关函数 | 行 |
|---|---|---|
| html | `svg_edge` 27 · `svg_label` 9 | 36 |
| svg | `_emit_edge` 14 · `_emit_label` 17 | 31 |
| drawio | `edge_xml` 19 · `edge_style` 20 · `label_html` 10 | 49 |

**裁决：不动，N3 那半**（"边标签发射器不抽公共层"）**继续成立**。判据不是"看着不一样"，而是：

1. **`cohesion --dups` 一对都没报**——这三组里没有任何一组的**结构相似度 ≥0.85 或逐字行 ≥0.6**。
   也就是说它们不是"同一段代码写三遍"，而是**三种格式各自的最短写法**：
   drawio 要管 `edgeStyle` / `endArrow` / 几何折线，SVG 要管 `<path d>` 与 `<tspan>` 的基线，
   html 那份还与 `_display_desc` 耦合（描述要截断成标签）。
2. **这与泳道底图那次的对比才是判据**（D-124）：泳道底图两份 **38 行里 21 行逐字相同**，
   所以"共享的只有几行算术"那句话**对底图不成立**、必须抽"算"；边标签这边**没有任何一对**
   达到那个读数 ⇒ N3 的原始判断在数据上是对的。
3. **它也是"抽了会伤图"的那一类**：D-124 实测过，把发射器参数化（注入 `fmt` / `esc`）会让
   `dev/tools/fn_graph.py` 的 unresolved 从 41 涨到 62（阈值 45）——那张图是 `coverage` 的分母与
   自举表的输入，**图的忠实度比少写几行值钱**。

**和 `esc` 的区别在哪**（这两个不该被混为一谈）：`esc` 是**逐字同体、只有 1 行**，
所以它需要的是"产物级守门人"（§2）；边标签是**结构不同、各自 30—49 行**，
所以它不需要守门人——**它们是三份实现，不是三份拷贝**。

## 4 这次**没有**动的东西（免得下个会话重新提议）

| 没动 | 为什么 |
|---|---|
| 46 条里的任何一条（搬迁 / 合并 / 改名） | §1 逐条判过，理由都成立；同理 `coding-spec` N3 的 `esc` / 边标签两半 |
| `parse_pdf.main ≈ parse_text.main`（结构 0.72） | 两个适配器**同接口两实现**：命令行形状必须一样（都被 `parse.py` 按同一套参数调），相似度来自接口而不是逻辑 |
| `lane_router._hits ≈ router._seg_hits_rects`（结构 0.65） | 同上，N21：`router` ↔ `lane_router` 是同一接口的两种布局实现 |
| `pptx_text` 那 5 个"路径版 / 字节版"成对函数 | K6：摘要器不许把整份 zip 拉进内存，所以同一句判据要有两个入口——**这不是重复，是"同一判据的两种输入形态"** |

**会推翻上面某条的唯一情况**：出现**第二个真有不同需要的消费者**（G5 的字面判据）。
在那之前，这里每一条都按"**刻意的边界**"记着，而不是"还没抽的重复"。

## 5 2026-09-19 的"还能不能更优雅"普查（含**判过不做**的）

`--dups` 只比**函数体**，所以下面三类它**结构上看不见**。这份普查是为它们做的，读数都在本机现跑过。

| 候选 | 读数 | 判决 |
|---|---|---|
| **CLI 样板**（`import argparse` + `def main` + `sys.exit(main())` 三行 × 30 个 CLI ≈ 120 行） | 30 个 CLI **全部**有 `sys.stdout.reconfigure` 与 `__main__` 守卫；`argparse` 30/30；`def main(argv=None)` 24 / `def main()` 5 | **不抽**。它是**形状约定**，不是逻辑：抽成 `cli.py` 要新增一个公共层模块（名册 + 自举表 + 夹具 + 三处口径），换来的是"少写两行"——而**会漂的那半（退出码、编码、argv 签名）恰恰已经各有仪器**（面② 的失败路径用例 + 面③ 的 stderr 编码）。按 G5 的字面判据，这里**没有第二个"真有不同需要的"消费者**，只有一个"大家都一样"的模板 |
| **`main()` 签名分歧**：`def main(argv=None)` 24 vs `def main()` 5（三个渲染器 + `writeback` + `xml_reader`）；收尾 `sys.exit(main())` 26 vs `sys.exit(main(sys.argv[1:]))` 2（`drift` / `query`） | 见上 | **不改**。差别只在"能不能在进程内传 argv"，而**本仓的验证层一律走子进程**（`_lib.run`）⇒ 没有实际收益。**记在这里，免得下次当成"发现了不一致"再查一遍** |
| **`dictionary.yaml` 的读者不止一处** | 3 种读法：`thresholds.load`（6 个模块，默认+覆盖+缺段告警）· `engine._load_yaml`（整份字典，视觉映射）· `manifest._default_shapes`（只取 `shapes` 段，**读不动就静默退回 `{}`**） | **前两种不动**（`thresholds` 是数值段的口径，`engine` 要的是整份视觉映射——两个不同的需求）。**第三种是一个待办**：静默退回 `{}` 与"降级必须留痕"冲突，且缺段时会表现成**下游一堆形状不符**（诊断指错方向）——登记为建议，见下 |
| **`argparse` 的命令行面**：182 个 `add_argument`（30 个模块，平均 6.1 个；`parse` 最多 24 个） | — | **不合并**。它们是**各自的公开接口**，不是重复代码；抽公共选项会造出"看着共享、其实每处语义不同"的假单一真源（`coding-spec` N8 同一取向） |
| **`Path(__file__).resolve().parent` 定位根目录**：只剩 4 个模块直写 | `capability` / `init` / `parse` / `parse_legacy` | **不合并**。布局假设的规矩是"**唯一定义处**"（`dev/_paths.py`），而这 4 处拿到的是"本模块所在目录"（`scripts/` 或 cwd），不是仓库根——**同一个写法，不同的语义**，合并会把它变成假真源 |
| **stderr 编码**：往 stderr 打非 ASCII 的模块 16 个，其中 **14 配了编码、2 个没配**（`drift` / `thresholds`） | 实测 `drift` 的错误分支：stderr 原始字节按 utf-8 解出来是 `\u26a0 ��������ˣ…`（`⚠` 不在 GBK 里 ⇒ 退化） | **已修 + 已上仪器**（D-128）：`drift.py` 补一行（它是 CLI 入口）；`thresholds` 那一处**升格成了公共层收口**（D-129 选 C）：新纯库模块 `console` 出 `warn()`，库不再自己碰 stderr。面③ 三条：CLI 配两个流的编码 · **纯库不裸写 stderr** · **留痕在管道下按 utf-8 解得回原句**（判在原始字节上，不看实现） |

**唯一一条留作待办的，已办**：`manifest._default_shapes()` 读不动/缺段时**静默退回 `{}`**
（症状是下游报一堆"形状不符"、把病因说反）——D-129 用 `console.warn` 补上了三条留痕分支，
并加了面② 一条判据（缺段仍退默认**且**原始 stderr 解得回那句"是字典的问题"）。
