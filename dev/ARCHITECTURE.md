# ARCHITECTURE.md — 模块地图与拆分方案

> 用途：把「流程步骤 → 命令 → 模块 → 产物」这条链完整摊开，作为**拆分的依据**与**合并的判据**。
> 与 `DECISIONS.md` 分工：本文写"现在是什么结构、准备怎么改"；改动的取舍理由写进 DECISIONS（D-60 起）。

## 一、完整流程链（SKILL 五步 → 命令 → 模块 → 产物）

| 步 | 命令（对外接口） | 参加的模块 | 产物 |
|---|---|---|---|
| 0 承接上下文 | `clarify.py <flowtable.md>` | clarify → semantics（标记分拣）+ table_to_dsl（parse_table / build_edges） | stdout：frontier / 简报（`--json` 结构化） |
| 1 建目录落表 | `init.py <名称>` | init（拷两份模板） | `output/<名称>/flowtable.md` + `checklist.md` |
| 2 结构校验 | `table_to_dsl.py --check <flowtable.md>` | table_to_dsl（parse / 三层校验 / H9 表头） + semantics（分隔符与标记） | exit 0/1 + `{message,subject,fix}` |
| 2' 转内部 DSL | `table_to_dsl.py --write …` | table_to_dsl（布局 / 配色 / 命名） | `<名称>-flow.yaml` + `<名称>-flow.manifest.json` |
| 3 自检留痕 | （无命令，AI 按 checklist 自查） | clarify（复核是否收敛） | `checklist.md` |
| 4 渲染 | `build.py <flowtable.md>` | build（编排六环）→ table_to_dsl → validate → render_html / render_drawio / render_svg → manifest → layer_index | `<名称>-flow.html` + `<名称>-flow.drawio` + `<名称>-flow.svg` + `<名称>-index.md` |
| 4' 单环复核 | `validate.py <yaml>` / `validate.py --artifact <产物>` | validate（模型侧八项 / 产物侧九项） | exit 0/1 + 几何表（`--dump`） |
| 4'' 视觉自检 | `shot.py <html>` | shot（无头浏览器截图） | `flow.shot.png`（中间物） |
| 5 同步闭环 | `sync.py <drawio> <flowtable.md> [--apply]` | sync（编排）→ xml_reader（读回）→ writeback（回写）→ table_to_dsl → validate | `flowtable.sync.md` 预览／覆盖后重渲染 |
| 5' 只读差异 | `xml_reader.py <drawio> --diff <flowtable.md>` | xml_reader + writeback.compare_bytes | stdout 差异 |
| 入口 B 已有图 | `xml_reader.py <图>` | xml_reader（拓扑摘要） | stdout |

**数据的三种"可交付中间件"**（它们的存在决定了模块边界）：
`flowtable.md`（事实源，人可改）→ `flow.yaml`（几何可手调，build 复用，D-18/D-26）→ `html/drawio/svg`（交付物，可独立复核）。

> 上表是**按数据流**排的。它与模块的**依赖分层**是两个正交维度，见第八节。
> 产物是**注册表驱动的集合**（第九节 W5–W7）：`build.RENDERERS` 里一行一个渲染器，
> 每行自带产物扩展名与两个反解器；所以"第 4 步产什么"这份表要与注册表一起看。

## 二、模块职责与耦合现状

**现状的唯一出处是 `dev/REPO-MAP.md` 第四节**（37 模块的接口面与三层层归属，由 `dev/tools/layering.py`
逐次实测）。本文不再复写那张表——复写过一次，结果是它在拆分完成后**整表停在拆分前**（列着已删除的
`model.py`、缺 6 个现存模块、行数与消费者数差一个量级），而没有任何仪器看得见（2026-09-17 审查发现）。

**本节保留的是拆分当时的实测快照**（`python dev/tools/coverage.py` 分母 296 → 拆分后逐模块落地），
它的用处只有一个：`dev/DECISIONS.md` 与第三、四节的拆分/合并判据拿它当依据。

| 模块（拆分前） | 行数 | 被谁 import | 判读 |
|---|---|---|---|
| `semantics.py` | 217 | 11 个模块 | 共享文本层（标记 / 分隔符 / 类型映射）→ **绝不能并进任何一方** |
| `geometry.py` | 344 | 8 个模块 | 网格 + 吸附 + 线段谓词库（布线/门禁同源，D-31）→ 保持 |
| `table_to_dsl.py` | **1186** | 7 个模块 | **一个文件干了 7 件事**（见第三节）→ 拆 |
| `engine.py` | 177 | 3（两个 renderer + validate） | 门面：把 model/grid/router/label 装配成 `L.*` → 保持 |
| `xml_reader.py` | 557 | 2（sync / writeback） | 读回 → 保持 |
| `writeback.py` | 316 | 2（sync / xml_reader 的 `--diff`） | 回写 → 保持 |
| `validate.py` | 547 | 2（build / sync） | 几何门禁 → 保持 |
| `render_html.py` | 672 | 1（build）+ 自有 CLI | 视图生成 → 保持 |
| `render_drawio.py` | 389 | 1（build）+ 自有 CLI | 视图生成 → 保持 |
| `manifest.py` | 286 | 1（build）+ 自有 CLI | 产物审核 → 保持 |
| `layer_index.py` | 156 | 1（build）+ 自有 CLI | 派生物 → 保持 |
| `model.py` | 30 | 1（engine） | **纯构造，该并入 engine**（已并入） |
| `label.py` | 86 | 1（engine） | D-19 缓存三件套之一（router/lane_router/label 对称）→ 保持 |
| `router.py` / `lane_router.py` | 351 / 536 | 1（engine） | 同接口两实现（流程 / 泳道）→ 保持 |
| `swimlane.py` | 226 | 1（engine） | 同上 → 保持 |
| `build.py` / `sync.py` / `clarify.py` / `init.py` / `shot.py` | 275/157/194/58/121 | 0 | **入口命令（编排），不是黑盒**→ 保持 |

## 三、`table_to_dsl.py` 的七件事（拆分方案）

| 现职责 | 内容 | 去向 |
|---|---|---|
| ① 解析 | `parse_table` / `_read_section` / `Errors` | `flowtable.py` |
| ② 语义桥接 | `parse_next` / `parse_next_raw` / `build_edges` / `wrote_route` / `ID_RE` | `flowtable.py` |
| ③ 校验三层 | `check_nodes` / `check_by_type` / `check_relations` / `check_deadloop` / `TYPE_RULES` / `check_label_length` / `run_checks` | `flowtable_check.py` |
| ④ 表头 H9 | `check_header` / `_derived_level` / `META_KEYS` / `CONFIG_KEYS` / `DERIVED_META_KEYS` | `flowtable_check.py` |
| ⑤ 配色 | `COLOR_NAMES` / `PALETTE_ORDER` / `SUBJECT_PALETTE` / `_color_map` / `resolve_colors` / `subject_map` / `_next_free` + 父表链 `find_parent_table` / `_has_backref` / `_backref_node` | `flowtable_colors.py`（父表链留 `flowtable.py`，供 build 的面包屑共用） |
| ⑥ 布局 | `parse_lane_order` / `apply_swimlane` / `_topo_order` / `assign_slots` / `merge_parallel_branches` / `auto_layout` / `reuse_hint` / `DEFAULT_COL_X` | `flowtable_layout.py` |
| ⑦ 命名 | `artifact_stem` / `artifact_rel` | `artifact.py`（**7 个消费者跨 6 个文件**，本来就不该住在解析器里） |
| 剩余 | `build_dsl_nodes` + `main`（`--check` / `--write` CLI） | `table_to_dsl.py` 保留为**装配器与公开命令**（文件名是文档承诺，不能改） |

目标：最大的文件 ≈ 350 行；每个文件一个黑盒。

## 四、合并判定（用户判据的补强版）

用户的原理：**一个脚本 = 一个黑盒，消费上游数据、生产下游数据；若本身是线性的，就该合并。**
补两条判据——"线性"不是充分条件：

1. **产物有几个消费者？** 第二个消费者出现时，"合并"就不成立（会被逼出第二份实现，历史教训：D-12 的 `compare_bytes` 就是抽出来消掉两份实现的）。
2. **它是不是公开接口？** 文档承诺了命令（`table_to_dsl --check`、`validate.py --artifact`、`manifest.py check`）的模块不能并进入口脚本，否则用户失去"只跑一环"的能力。

**净动作结论**：
- **合并 1 处**：`model.py` → `engine.py`（30 行、单消费者、无 CLI、纯构造）。
- **不合并**（判据 1/2 反对）：`geometry↔swimlane`、`router↔lane_router`、`render_html↔render_drawio` 是同一接口的两种实现（按 `输出布局` 二选一）；`label.py` 并入 engine 会破坏 D-19 的缓存失效对称；`semantics.py` 11 个消费者；入口命令是编排不是黑盒。
- **拆分 1 处（本方案的量）**：`table_to_dsl.py` → 5 个模块（第三节）。

## 五、执行波次与验收

| 波次 | 动作 | 验收 |
|---|---|---|
| W1 | `artifact.py` 抽取（6 个引用方改指向）+ `model.py` 并入 `engine.py` | 四面全绿；产物字节不变 |
| W2 | `flowtable_layout.py` + `flowtable_colors.py` 抽取 | 同上 |
| W3 | `flowtable.py` + `flowtable_check.py` 抽取；`dev/verify/contract.py` 的函数定位断言改指新家；`clarify.py` / `writeback.py` / `layer_index.py` 的 import 改指向 | 同上 |
| W4 | 独立验证（另一 worker 复跑 + 手验边界）+ 文档同步（README 模块数、SKILL.md 目录表补新模块） | 四面全绿 + CLI 冒烟 |

**施工纪律**（沿用 D-53/D-55 的教训）：
- 同一文件的编辑串行执行，改完 grep 复核再报"已完成"。
- 每波跑一次 `dev/verify/run.py`（并发时各用 `--tmp` 隔离）。
- 产物字节不变式（invariants 面）与幂等不变式是这轮重构的安全网——**任何产物变化都视为失败**。
- 不做"顺手改行为"：本方案只挪位置、不改语义。

## 六、原子化拆分（2026-09-14 起）

### 判据（唯一）
函数体内存在 **≥2 个可以起名字的顺序阶段**（相邻语句组，各自完成一件可独立描述的事）→ 拆成 `_` 前缀的私有阶段函数，**每个阶段函数就是流程图上的一个节点**。
编排器（`main` / `write` / `render`）是最典型的拆分对象：它们不是"一件大事"，是"一串小事"。

### 铁律（每包都适用）
1. **不改任何现有函数名 / 签名 / 返回值结构**；只新增私有阶段函数。
2. **绑定名不许动**：`build.py` 的 `render_html` / `render_drawio` 等名字被 `dev/verify/gates.py` 的 monkeypatch 断言盯着（改了就假绿）。
3. 早退（`return`/`continue`/`break`）必须显式改写为"被提函数返回值 + 调用方判断"，且语义等价；拿不准就别拆，并在报告里说明。
4. 不改任何字符串输出 / 异常类型 / 报错文案。
5. 验收 = 四面全绿 **且** 产物（或报错 stdout）逐字节不变。

### 依据数据（`dev/tools/fn_graph.py`，2026-09-14 实测）
25 文件 / **296 函数**（107 方法、12 嵌套、12 类）/ 272 同文件边 / 201 跨文件边 / 44 缺口（34 条已确认假缺口）+ 16 条真歧义（`Grid`↔`SwimGrid`、`Router`↔`LaneRouter` 运行期二选一）。
分组：89 组（58 个单点组）。三条硬结论：`geometry` 的 8 个单点组 = **无依赖共享工具层**（被 8 个文件依赖、自身出度 0）；`engine` 的 13 个门面方法全是单点组 = **多流水线汇合点**；`lane_router` 的 25 个函数是**一个 286 行强连通整体**（要按内部子流程边界切，不能按函数边界切）。

### 批次与进度

| 包 | 文件 | 主要目标（拆前行数） | 状态 |
|---|---|---|---|
| A | `render_html.py` / `render_drawio.py` | `render` 238 / `_page_xml` 77 | ✅ `render` 238→17、`_page_xml` 77→36；4 面绿，19 产物逐字节相同 |
| B | `build.py` / `sync.py` / `table_to_dsl.py` | `main` 183 / 111 / 129 | ✅ 183→40 / 111→29 / 129→24；33 用例差分对拍 + AST 绑定名计数全等 |
| C | `flowtable.py` / `flowtable_check.py` / `flowtable_layout.py` / `flowtable_colors.py` | `check_header` 77 / `check_relations` 59 / `parse_table` 67 | ✅ 77→19 / 59→14 / 67→17；**14 张表报错输出逐字节相同**，嵌套函数清零（+48 函数） |
| D | `validate.py` / `xml_reader.py` / `writeback.py` / `manifest.py` | `write` 124 / `main` 63 / `_parse_nodes` 52 / `diff` 51 | 进行中 |
| E | `geometry.py` / `swimlane.py` / `router.py` / `lane_router.py` / `engine.py` / `label.py` | `SwimGrid.__init__` 93 / `_ensure_gutters` 86 / `_candidates` 52 / `_cands` 59 | ✅ `Grid.__init__` 66→9、`SwimGrid.__init__` 93→11、`_ensure_gutters` 86→15、`_cands` 59→25（+38 函数）+ **自造泳道样例 4 件产物逐字节相同** |
| F | `clarify.py` / `layer_index.py` / `init.py` / `shot.py` / `semantics.py` | `build_layer_index` 69 / `shot.main` 59 | ✅ 69→12 / 59→28；clarify 文本与 `--json` 10/10 逐字节相同 |

**每包的共同验收**：四面全绿（29/263/11/17）+ 产物（或报错输出）**逐字节不变** + 不改函数名/签名。
**注意**：`examples/workflow/`（产物在 `dev/baseline/workflow/`）是会被手工微调的目录——**比对一律整目录复制到仓库外再跑**（D-20），只读命令才可直接在工作树上用。

### 画图口径（定稿，2026-09-14）
- **节点名 = `qualname`**：普通函数写 `parse_table`；**方法写 `Grid.anchor`**；**嵌套函数写 `outer.inner`**（当前图里带点的名字有 119 个）。写成裸名会同时被判"缺失 + 多余"——`dev/tools/coverage.py` 按 qualname 精确比对。
- **类 = 分组边界，不是节点**：类若被画成节点会被判"多余"（coverage 的 `kind=class` 不进分母）。
- **表 ↔ 文件 = 目录名**：`output/self-boot/<模块>/flowtable.md` ↔ `scripts/<模块>.py`（与 D-51「身份在目录上」一致，**不新增表头键**——H9 是键封闭的）。L0 主表不是模块，映射不上不算失败但会被单列。
- **每个函数恰好出现在一张表里**：全局按 `(文件, 函数名)` 配对；跨文件同名（真实图里有 5 个，如三个文件都有 `_parse_args`）靠文件归属区分，不算重复。
- **收敛判据**：`python dev/tools/coverage.py --tables-root output/self-boot` —— 分母 = 依赖图的函数 + 方法（**数字随代码增长，必须现跑现取**；基线 296 → 拆分中快照 477 → 第 4–5 步收口 498 → 以后以重生成的图为准），分子 = 各表节点名集合。**exit 0（100% 且无多余/无重复/无错位）才算画全**；否则按清单补图再跑，循环到 0。
  选项名是 `--tables-root`（指**流程表目录树**），与 `equiv.py` / `api_audit.py` 的 `--root`（指**代码工作树根**）不是一回事；旧名 `--root` 保留为隐藏别名。

### `dev/tools/coverage.py` 的能力边界（别把"工具说 100%"当成"图一定对"）
- **语义合并判不出**：两个函数画成一个节点名 → 两个都算缺失；一个函数拆成两个名字 → 一个算多余。
- **放错表默认判不出**（覆盖率是全局按名字算的）→ 已加"错位"检查：函数出现在别的模块表里、而它自己的模块表存在 → 判错位。
- **节点名与 qualname 不一致**是最容易首跑炸出来的问题（见上）。
- **图的盲区即工具的盲区**：`fn-graph.json` 的 `unresolved` / `ambiguity` 原样继承，工具不做二次推断。

## 七、自举流程表：分层与生成规则（定稿）

**目标**：用这台机器画出它自己——**每个函数都出现在某张表的某个节点上**，且这张图是**生成**出来的（不是手写）。

### 为什么用生成器
手写几十张表意味着"代码一变、图就作废"。生成器让循环闭合：`改代码 → 重跑生成器 → table_to_dsl --check → build → coverage.py → 按缺口改生成规则`，一轮一条命令。生成器输入 = `dev/tools/fn-graph.json`（函数与调用边）+ `dev/tools/fn-groups.json`（模块内分组）+ `dev/tools/fn-deps.json`（模块间依赖）。

### 结构：**两层**（定稿，已撤销曾提出过的三层方案）

实际交付并在验收中的结构是**两层、39 张表**（1 张根表 + 38 张模块表，一个模块一张）：

| 层 | 文件 | 节点 | 边 | 说明 |
|---|---|---|---|---|
| **L0 根表** | `output/self-boot/flowtable.md` | 38 个**模块**，名字写 ``模块 · flowtable`` | 模块间依赖（`fn-deps.json`） | 每行 `⊞ <模块>/flowtable.md`；**每行的「项目运作阶段」列填流水线阶段**（分组信息在这里，不另建一层） |
| **L1 模块表** | `output/self-boot/<模块>/flowtable.md` | 该模块的**函数**，名字 = `qualname`（`parse_table` / `Grid.anchor`） | 模块内调用边（`fn-graph.json`），按 `fn-groups.json` 分组 | **只有这一层的节点进覆盖率分母**；目录名即模块名（覆盖率的映射靠它，任意深度都成立） |

**为什么撤销三层**：三层（根=阶段链 → 阶段表 → 模块表，共 1+9+26）唯一目的是给"流水线分组"一个视觉层，而
① 用户第 5 条"庞大就该有子流程"**已由现有两层满足**（每个模块一张子表，节点 = 该模块的函数；规模现跑现取）；
② 分组信息用**「项目运作阶段」列**就能承载，不必新增 9 张表再冒一遍 `parent` 双向一致性的风险；
③ 阶段层是**可读性诉求、不是功能要求**，为它付 9 张表的维护成本不划算。
将来若要切三层：`coverage.py` 的映射在**任意深度**都按"目录名即模块名"成立，且阶段归属已经在阶段列里，随时可派生。

**九个流水线阶段与模块归属**（写进根表的阶段列）：
`接管与解析`[flowtable, semantics, artifact] · `结构校验`[flowtable_check] · `布局与配色`[flowtable_layout, flowtable_colors] · `DSL 装配`[table_to_dsl] · `渲染`[engine, geometry, swimlane, router, lane_router, label, render_html, render_drawio, render_svg] · `产物审核`[manifest, validate] · `层级索引`[layer_index] · `同步闭环`[xml_reader, writeback, sync] · `编排入口`[build, init, shot, clarify]

### 节点/边构造规则（生成器必须遵守）
1. **根表的模块节点名必须非标识符**（``模块 · flowtable``）——否则 `flowtable` 这种名字符合标识符正则，会被 `coverage.py` 当成函数名判"多余"。
2. **模块表节点名 = `qualname` 原样**（含点）；**节点描述 = `★ <函数 docstring 首行>`**（图自带文档），跨模块调用追加 `⇢ 依赖 <模块>.<函数>`。
3. **叶子函数**（不调用任何本模块函数）→ 指一条边到本表的 `结束`（语义："执行完返回"）。收尾一律用 `结束`——一张图可以有多个结束（每个结局一个，D-74）。
4. **多入口模块**（如 `xml_reader` 的 `read`/`brief`/`diff`/`main`）：`开始` 节点各发一条**带标签**出边（标签 ≤4 字，如 `read`、`brief`、`diff`、`main`）。
5. **判断节点**（若某函数有 ≥2 个被调分支）可画成本模块的 `判断`，分支标签 ≤4 字；分支多于 4 个时**不拆判断**，改为顺序任务链（避免标签超长触发软提示）。
6. **跨模块边不画**（表是自包含的）：只在描述里标 `⇢ 依赖 …`。这样"每个函数恰好出现在一张表里"，`coverage.py` 的"重复"才有意义。
7. **表头**：`id` = 模块名（`flowtable`）、`level` = 0（根表）/ 1（模块表）、`parent` 指向父表（D-58 双向一致，parent 里必须有 ⊞ 指回本表）。**不新增任何元信息键**（H9 键封闭）。

### 必须满足的机器规则（H1–H8 三层 + 表头 H9，生成器要用 `table_to_dsl --check` 自证）
每表至少一个 `开始` 与一个 `结束`（结束**可以有多个**：每个结局一个）；无孤儿、无死胡同、无不可达；判断节点 ≥2 带标签分支；分支标签 ≤4 字；`结束` 不许有出边；节点描述里的 `⊞` 至多一个。

### 收敛判据（循环终止条件）
```text
python dev/tools/selfboot_gen.py            # 生成两层：根表 + 每个模块一张表
python table_to_dsl.py --check <每张表>  # 结构校验必须全过（H1–H8 三层 + 表头 H9）
python build.py output/self-boot/flowtable.md   # 自举出图（这一步就是"用它自己画自己"）
python dev/tools/coverage.py --tables-root output/self-boot  # 四类差异必须全零 → exit 0
```
`coverage.py` 报缺口 → 改**生成规则**（不是手改表）→ 重跑四条命令。**exit 0 才算收敛。**

### 七件仪器（`dev/tools/`，**清单的唯一出处**是 `dev/tools/README.md`；下表只列与自举链直接相关的四件）
| 仪器 | 回答什么 | 退出码 |
|---|---|---|
| `fn_graph.py` | 函数之间谁调谁（**事实源**，`coverage` 与门⑦的"旧快照"判据拿它当输入） | 0 完成 / 1 有未解析需人看 / 2 仪器故障 |
| `coverage.py` | 每个函数都画进表了吗（缺失/多余/重复/错位） | 0 收敛 / 1 有缺口 / 2 输入读不了 |
| `api_audit.py` | 原有函数名/签名/嵌套关系丢没丢（**分母钉在 git 底本**） | 0 无丢失无签名变更 / 1 有 / 2 仪器故障 |
| `equiv.py` | 我这次改动改变可观测行为了吗（**逐字节**比 stdout/stderr/退出码/产物） | 0 全同 / 1 有不同 / 2 仪器故障 |

**互补关系**：`coverage` 与 `api_audit` 都是静态的、缺一不可——前者的分母**来自当前代码**，所以"代码和表一起改掉"时它没有信号；后者的分母钉在 git 底本上，不随工作树漂移。`equiv` 是动态的，但**只验跑过的路径**（没被用例触发的分支等于没验）。三者都盖不住"没跑到的分支 + 没对上的重构"。
- **节点 = 函数**。**方法也各成节点**（名字写 `类.方法`）；**类作分组边界**（相当于天然的泳道/子流程框），**不是节点**。
- **两层**：根表（37 个模块 + 阶段列）→ 每模块一张表（节点 = 该模块的函数）。**层级与节点/边规则的唯一权威是第七节**，本节只列结论。
- **共享工具层不重复画**：`geometry` / `semantics` / `artifact` 是出度 0 的叶子表，其他模块表在节点描述里写 `⇢ 依赖 geometry.snap` 这类标注（`dev/tools/fn-deps.json` 提供），保证**每个函数恰好出现在一张表里**。
- **机器判定"画全了没有"**：`dev/tools/coverage.py` —— 分母是依赖图的函数 + 方法，分子是各表节点名集合，报缺失/多余/重复/**错位**，exit code 即循环终止条件（判据与边界见上一节）。

### 图分析的已知边界（`fn_graph.py` 口径，别当缺陷）
- 局部变量调方法（`p.read_text()`、`ap.add_argument()`）判为外部对象，不计边也不进缺口账本（否则 stdlib 噪音淹没真缺口）。
- `Engine` 门面可达性靠一条**有界零猜测**规则补上：仅当函数所有 `return` 都构造同一个项目类时（本项目唯一：`engine.load`）才认定类型，并把该类型沿裸名字实参传播（最多 8 轮）。它把 13 个假孤儿变成 12 个真可达，且不往两本账加噪音。
- `@property`（如 `Engine.width`）与 `__init__`（构造边落在类节点上）入度 0 是正确值，不是漏画。

## 八、四阶段数据流视图（2026-09-15 定，与三层**并列**）

### 为什么单列一节：阶段与层是两个正交维度

- **层**回答「谁许 import 谁」——依赖方向，由 `dev/tools/layering.py` 机器守着（公共 / 模块 / 编排，实测违规 0）。
- **阶段**回答「谁生产谁消费」——数据流，由 `build.py` 在走。

**同一模块在两维里的位置可以不同**，所以不能用一维去覆盖另一维：
`geometry` 在**阶段**上属「布局渲染」，在**层**上是「公共地基」——它被布局与视觉**两个阶段共用**。
硬把阶段当目录，就等于要求"每个模块只属于一个阶段"，而被两阶段共用的地基无处安放。

### 四个阶段

| 阶段 | 输入产物 | 输出产物 | 主要模块 | 这一段的不变量 |
|---|---|---|---|---|
| ① 流程表制作 | 人写的 `flowtable.md` | `flowtable.md`（校验过）+ `flow.yaml` | `init` `clarify` `flowtable` `flowtable_check` `table_to_dsl` | 结构与语义先过 H1–H8 + 表头 H9；**语义只从表来** |
| ② 布局渲染 | `flow.yaml`（语义 + 几何） | 同一份 yaml 落定几何 | `engine` `geometry` `flowtable_layout` `swimlane` `router` `lane_router` `label` | 八项几何门禁：零重叠 / 零穿节点 / 画布内 / 网格对齐 … |
| ③ 视觉渲染 | yaml + `dictionary.yaml` | `html` / `drawio` / `svg` 的图元内容 | `render_html` `render_drawio` `render_svg` `flowtable_colors` | 语义→视觉映射**只从字典来**；三产物共享字典，互相之间**零代码依赖**（协作走产物） |
| ④ 成果生成 | 渲染结果 | 落盘的产物六件套 + 审核回执 | `artifact` `manifest` `layer_index` `build` `sync` `validate` `xml_reader` `writeback` | 产物与契约逐项一致；**审核不过不留产物** |

### 装不进这四格的，显式列出来（别让它们变成"随便塞"

```text
共享地基   geometry / semantics / artifact / dictionary.yaml
           —— 被 ≥2 个阶段共用，归任何一个阶段都会让那个阶段变成别阶段的上游
自检仪器   shot（截图自检）、以及 dev/tools/ 下七件仪器（清单见 dev/tools/README.md）
           —— 它们不生产交付物，只回答"做得对不对"，不属于任何交付阶段
```

**已知错位**：`shot.py` 现在住在 `scripts/`（产品运行时）里。它是自检仪器，按上面的划分该属"仪器"，
但它又不适合直接搬去 `dev/tools/`——`dev/tools/` 不许被 `scripts/` 依赖，而 `dev/verify/e2e.py` 会调它。
⇒ 记为一处待处理的边界问题，不在本次改造范围内。

### 阶段之间的接口（本次改造要落的东西）

现状：阶段之间**没有显式契约**，靠"产物 = yaml / html / drawio"这种隐式约定，
`build.py` 里顺序调过去。两个渲染器**已经具备插件形态**（平级、零代码依赖、吃同一份 DSL），
但签名没统一：

```text
render_html.render(dsl_path, out_path, parent=None)
render_drawio.render(dsl_path, out_path, pages=None, page_id=…, page_name=…)
```

⇒ 第 1 步目标：**把渲染器统一成 `render(dsl_path, out_path, ctx) -> receipt`**，
在 `build.py`（编排层）里用注册表调用：

```python
RENDERERS = {'html': render_html.render, 'drawio': render_drawio.render}
```

**判据**：新增第三种渲染器（svg / pdf / mermaid）只需**加一个文件 + 注册一行**，
不改 `build.py` 的阶段逻辑、不改别的渲染器、不动字典。

## 九、接口整改方案（2026-09-15 定，分四波）

### 9.0 目标与非目标

**目标**：让阶段之间从"隐式约定"变成**显式契约**，让两个渲染器成为**真插件**。

**非目标（本次明确不做，做了算越界）**：

| 不做 | 理由 |
|---|---|
| 不动目录、不动文件的层归属 | `dev/tools/fn_graph.py` 用 `SCRIPTS.glob("*.py")`（**非递归**）且硬编码 `scripts/<名>.py` 为边标识；挪文件 ⇒ 函数总数崩 ⇒ `coverage` 误报 ⇒ 自举链断。`dev/tools/layering.py` 的层归属也是硬编码集合。**收益不抵成本，且接口稳定后再迁移返工率更低。** |
| 不改任何函数的**绑定名** | `build.py` 的 `render_html` / `render_drawio` / `validate_main` 被 `dev/verify/gates.py` 用 monkeypatch 盯着；改名即红。 |
| 不改产物格式 | 视觉与几何已有门禁守；本次只动"怎么调"，不动"画成什么"。 |
| 不实现第三种渲染器 | 只把接口腾出来；真做第三者是后续独立任务。 |

### 9.1 契约形状（第一处要钉的）

现状（**签名不同构**，这是"契约未定"的直接证据）：

```text
render_html.render(dsl_path, out_path, parent=None)
render_drawio.render(dsl_path, out_path, pages=None, page_id='flow-1', page_name='流程图')
```

**目标形状**：

```text
render(dsl_path, out_path, ctx=None) -> receipt
```

| 项 | 规定 |
|---|---|
| `dsl_path` / `out_path` | 位置参数，语义固定：一份 DSL → 一个产物文件 |
| `ctx` | 渲染器私有选项的**唯一**入口（`None` 时必须等价于旧行为）。html 的 `parent`、drawio 的 `pages`/`page_id`/`page_name` 都收进它 |
| `receipt` | 统一回执：`{'path': str, 'sha256': str, 'bytes': int}`（`build` 末尾的产物回执已在打印这些字段，只是没有统一结构） |
| **绑定名** | `render` 这个名字与 `build.py` 里 `import render_html` 的用法都**不许动** |

**兼容策略（把风险压到最低的改法）**：**只加关键字参数，不改名、不删参数**。
`ctx=None` 时走旧参数路径 ⇒ 老调用方（`dev/verify/e2e.py`、CLI）零改动即可继续工作。

### 9.2 注册表放哪（第二处要钉的）

**放在编排层 `build.py`**，不放契约层：

```python
RENDERERS = {'html': render_html.render, 'drawio': render_drawio.render}
```

理由：注册表是**编排的职责**。若放进契约层，契约层就要 import 阶段实现，而分层门禁规定
**契约层不许依赖上层** —— 会直接违规。

### 9.3 阶段骨架（第三处要钉的）

在 `build.py` 里把阶段写成**只读声明**（本波只声明，不改调用逻辑）：

```text
STAGES = [
  ('流程表', <输入产物>, <输出产物>, <本段不变量>),
  ('几何',   …), ('视觉', …), ('成果', …),
]
```

它不驱动执行，只做三件事：① 让"四阶段"在代码里有个可被引用的出处；② 给后续把编排函数化留好落点；
③ 让 `--stage` 这类按段运行的能力将来加得进来。

### 9.4 四波执行（每波独立可验收、可回退）

| 波 | 内容 | 风险 | 验收 |
|---|---|---|---|
| **W1** | 本方案落文档 + `STAGES` / `RENDERERS` 以**只读常量**写进 `build.py`（**不改任何调用**） | 极低 | 四面全绿 **且产物逐字节不变**（没改逻辑就该零变化） |
| **W2** | 两个 `render` 加 `ctx=None`（新参数映射到旧参数）；`build` 改走 `RENDERERS` | 中 | 四面全绿 **且 `html`/`drawio` 逐字节不变**（同输入必同字节） |
| **W3** | 把 `parent` / `pages` / `page_id` / `page_name` 从公开签名退进 `ctx`（留一层兼容 shim）；同步 CLI 与 `dev/verify/e2e.py` | 中 | 四面全绿；CLI 参数名**只增不改** ⇒ 文档同步后 `--only contract` 仍 29/29 |
| **W4** | `gates` 加**可插拔证明**：注册一个只写空产物的 stub 渲染器，断言"加渲染器只需注册一行" | 低 | 新断言通过；反向控制（去掉注册那行应红） |

**W5（可选，本次不做）**：`shot.py` 归位、层名整理等目录级动作 —— 等 W1–W4 稳定后另开一波评估。

### 9.5 风险与对策

| 风险 | 对策 |
|---|---|
| 改签名连带 `gates` 的 monkeypatch | 绑定名不动，只加 `ctx` 关键字参数，`ctx=None` 等价旧行为 |
| 产物字节变化 ⇒ `invariants` 的基准比对红 | W1/W2 的验收就是"**逐字节不变**"；**若某波确实变了**，同波内**重钉 `dev/baseline/workflow/` 基准**（按 D-20：复制到仓库外 build、只拷回变化的文件） |
| `dev/verify/e2e.py` 直接调 CLI | CLI 的 argparse **参数名只增不改**；改完同步 `SKILL.md` / `references/`，再跑 `--only contract` |
| 文档契约失配 | 每波末尾跑 `python dev/verify/run.py --only contract`，看 `29/29`（或新增后的 N/N） |
| 仪器受影响 | 本次不动文件与层归属 ⇒ `fn_graph`/`layering`/`self-boot` 链**不受影响**（这正是把目录后置换来的收益） |

### 9.6 验收口径（与既有纪律一致）

- 判据看**面级结论**（`【面①】N/N` + 汇总四行 ✓），**不看退出码** —— 收尾清理临时目录会被环境安全钩子拦下，rc=1 属预期。
- 每波**单独一个提交**，提交前 `git status --short` 复核现场。
- 本机 git 会毁 ref（见 D-60）——**原写法是"走 `.workbuddy/bin/safe_git.py`"，但那是记录者的本机工具，
  不在本包内，照做只会找不到文件**。现在按 D-60 的结论直接做：任何 git 写操作后显式复核
  `git rev-parse HEAD`；ref 没落盘就用 `git rev-parse <短哈希>` 取全哈希再补写 `.git/refs/heads/<branch>`。
- 动 ref 前先做整目录备份。

### 9.7 执行结果（2026-09-15，四波全部完成）

| 波 | commit | 动到的文件 |
|---|---|---|
| W1 | `12b22c6` | `build.py`（只加 `STAGES` / `RENDERERS` 声明，调用逻辑未动） |
| W2 | `22f3e80` | `build.py` `render_html.py` `render_drawio.py` `gates.py` |
| W3 | `5226003` | `render_html.py` `render_drawio.py` `gates.py` |
| W4 | `670590f` | `gates.py`（+`_check_renderer_registry`，门禁 278 → 283） |

四波每波验收均为四面全绿，且 W1–W3 **产物逐字节不变**
（html `4188f65772d0` / drawio `2d20590be7e3`，与已提交的完全一致）。

**执行中发现的两件事（都已写进代码注释，避免后来人重踩）**：

1. **注册表必须存「名字」而不是函数对象**（W2 的偏离）。
   `dev/verify/gates.py` 是靠替换 `build` 的**模块级名字** `build.render_html` 来 monkeypatch 的；
   若注册表在导入时就把函数对象固化下来，替换会落空 ⇒ 那条用例变成**永远绿的假绿**。
   故 `RENDERERS` 存名字、`_renderer()` 在**调用时**现查 `globals()`。
2. **改了渲染器签名，替身要同步**（W2 踩到、由门禁抓出，非静默）。
   `gates` 的替身 `fake_html` 原先没写 `**kwargs`，build 传 `ctx` 直接 TypeError，
   该面按"面内未预期异常"计失败 —— 而它自己的注释早已预言：
   "签名必须与真渲染器同步……少一个参数会让退出码 1 是**崩出来的**不是**审出来的**"。
   ⇒ **改渲染器签名时必须同步所有替身**；W3 又同步了一次。

**一处诚实的边界**：注册表现在是"**换**渲染器只需改一行"，而"**新增**第三种渲染器"
还需要在 `build` 里补一处调用点（`build` 目前只渲染 html + drawio 两种固定的产物）。
把 build 做成"遍历注册表全渲染"是后续独立任务，不在本次范围。

### 9.8 W5 + W6 执行结果（2026-09-15）：注册表真的能装第三类产物

**目标**：把 9.7 末尾那条"诚实的边界"消掉——让"新增渲染器"真的只是"加一个文件 + 注册一行"。

| 项 | 内容 |
|---|---|
| W5 | 注册表升级为**描述符**（`fn` / `ext`）；产物路径由 `_product_paths` 从注册表派生；`_render_products` **遍历注册表**渲染；`_render_ctx` 集中放"每类自己的私有选项"；回滚/回执/几何自检一并改为遍历 `products` 字典 |
| W6 | 描述符再加**两个反解器**：`ids`（反解出节点/边集合，供**契约反查**）与 `geom`（反解出真实坐标，供**几何自检**）；`manifest.check` 增加通用入口 `products={kind: {path, ids, label}}`；抽出 `geometry_from_drawio`；`artifact_geometry(path, reader=None)` 接受外部反解器（不传仍按扩展名兜底） |

**反解器是插件契约的另一半**——这是 W6 的核心结论：只注册渲染器、不注册反解器，
那个产物就没人复核。旧的 `artifact_geometry` 兜底是"非 `.html` 一律当 drawio XML"，第三种格式进来会被**按错误格式解析**、静默绕过整套几何门禁。

**执行中发现的两处（都由门禁抓出，非静默）**：

1. **`render_drawio.render` 原本不返回东西**（`None`），而 `render_html.render` 返回 rc —— 两个渲染器**成败信号不一致**。
   旧编排只检查 html 的 rc、不检查 drawio 的，所以一直没暴露；一旦被放进同一个循环，`None != 0` 就被误判成失败。
   ⇒ 统一契约：**成功必须显式 `return 0`**；失败仍用非零 rc 或抛异常。
2. **注册表从"映射到名字"变成"映射到描述符"是结构变更，所有替身要跟着改**。
   `gates` 里 W4 的替身原先把 `RENDERERS['html']` 整体设成一个字符串，改成描述符后
   `_product_paths` 取 `meta['ext']` 直接 TypeError。⇒ 与 W2→W3 的"改签名要同步替身"**是同一类问题**：
   **改注册表结构 = 改契约，替身/门禁必须同步**。

**验收**：四面全绿 `29/289/11/17`；两份产物与已提交**逐字节一致**（html `4188f65772d0` / drawio `2d20590be7e3`）。
新增门禁 `_check_registry_scales` 6 条断言（门禁 283 → **289**），它**真的注册第三类产物**并证明：

```text
✓ 第三类产物真的落盘了（渲染循环遍历了注册表）   registry2-flow.stub.html
✓ 第三类被纳入契约反查（不是静默跳过）           ['drawio', 'html', 'stub']
✓ 第三类用它自己声明的反解器跑几何自检            html→geometry_from_html
                                               drawio→geometry_from_drawio
                                               stub.html→geometry_from_html
```

**由此，"新增渲染器"的真实成本被钉死为**：

```text
① 新写一个模块：def render(dsl_path, out_path, ctx=None) -> 0（成功必须返回 0）
② 若格式是全新的：再给它写两个反解器（ids / geom），并挂到 build 的命名空间上
③ 在 RENDERERS 里加一条描述符
④ 需要私有选项的话，在 _render_ctx 里加一条分支
⑤ 更新 dev/baseline/workflow 基准（产物变了）
```

**一条硬提醒**（给将来加渲染器的人）：**反解器不是可选项**。
不注册反解器的产物，会静默绕过两道反查——`ids` 决定它进不进契约反查，`geom` 决定它进不进几何门禁。

### 9.9 W7a 执行结果（2026-09-15）：降级能力——关掉可选模块也照出 html

**要保的性质**（用户提出）：**主干必须能独立产出可用的 html；其它模块关掉只是变朴素。**

实测过两个层次，结论不同：

| 层次 | 结论 |
|---|---|
| **渲染器级** | ✅ **成立**（W5/W6 挣来的）。注册表里只留 `html`，build 仍成功出 html，两道反查与交付回执只审它自己。 |
| **模块级** | ❌ 原本**不成立**：`build.py` 顶部硬 `import render_drawio`，把文件删掉连 html 都出不来。 |

**W7a 的做法**：

- 注册表由 `_RENDERER_SPECS` + **`build_registry()`** 按**可用性**装载，返回 `(RENDERERS, 缺的可选件, 缺的必需件)`；
- `html` 标 `required: True`（硬 import）；其余渲染器 `try/except ImportError` ⇒ 模块不在就不进注册表；
- **两条纪律**：**必需件缺失 = 硬失败**（`main` 里报一句人话并退出，不静默少一个产物）；**可选件缺失要明说**（`MISSING_RENDERERS` 打进交付清单，并把"几何改动后 sync"那条提示一并省掉——降级中不该给一条走不通的路）。

**验收**：四面全绿 `29/296/11/17`；两份产物与已提交**逐字节一致**。
新增 `_check_degrade`（门禁 289 → **296**）**两个方向都验**：

```text
✓ 装齐时注册表是 html + drawio，无缺件        ['drawio', 'html'] miss=() absent=()
✓ 可选件不在 → 从注册表消失，并被记进"缺的可选件"
✓ 只有 html 渲染器时 build 仍成功并出 html     rc=0 html=True      ← 降级成立
✓ 降级时确实没有 drawio 产物                  drawio=False
✓ 必需件缺失被识别为 absent（不是"可选缺失"）  absent=('html',)
✓ 必需件缺失 → build 硬失败且不产出 html       rc=1 html=False     ← 反向控制
```

**写这条用例时自己踩了一坑（由门禁抓出）**：我删了 html 就断言"降级时没有 drawio"，
可**前置那次 build 已经把 drawio 生成了** ⇒ 量到的是上一次的遗留物，断言成了永远绿的假绿。
⇒ 凡"断言某产物**不该**存在"，**必须先把该产物删掉**再跑——与"逐字节比对要先删产物"是同一条教训。

**`.svg` 的定位据此确定**：**可选兄弟产物**（`required: False`，从 yaml 渲染，与 html/drawio 平级），
**不是枢纽**——这与已定的 **X**（yaml 是几何事实源）一致。让 `render_html` 消费 svg 会把 svg 变成
html 的事实输入，等于 **Y 的变体**，与 X 冲突，属单独决策，不混进 W7。

### 9.10 第 4–5 步执行结果（2026-09-15）：svg 补泳道底图；「该不该有底图」交给知道底稿的一层

#### 4) `render_svg` 补画 `<g class="lanes">`

两处：

- **画布口径对齐 html**：`head_band(False)` + `W = L.width` + `H = round(L.height())`，
  与 `render_html._view_svg` 一字不差。**这一步不是可选的**：泳道底图画到 `L.height()`（430），
  而改前的 viewBox 只有 400 ⇒ 底图被裁掉 30px（实测）。切带必须在 `L.lanes()` **之前**——
  `legend_h` 会改写 `origin_y`/`rowy`，顺序反了量到的是带标题带的那一套坐标。
- **自己发射底图**（不 `import render_html`：模块层零代码依赖，分层门禁会拦）。元素约定与
  `render_html.svg_lanes` 成对：`<rect x="0" …>` 提供 `band`，`<g class="lanes">` 里的 `<rect>`
  提供底色外包盒。**组内不许再嵌 `<g>`**——`manifest._html_canvas_bands` 的正则是非贪婪匹配到
  第一个 `</g>`，嵌一层就把外层截断、底色盒少一块（静默少数据）。

同一份泳道源、三份产物的几何表（实测，改前 svg 那行是 `0.0 / None`）：

```text
html    canvas=(960, 350)  band=120.0  lanes=(0, 0, 960, 350)
drawio  canvas=(980, 430)  band=120.0  lanes=(0, 80, 960, 430)
svg     canvas=(960, 350)  band=120.0  lanes=(0, 0, 960, 350)   ← 本次补上
```

流程源的 svg 画布也随之变化（`1180×470 → 1180×390`，顶部那条从没人用的空带消失），
这是**画布口径统一**的必然结果，不是缺陷。

#### 5) 两条泳道判据不再"输入缺失就自我跳过"

原状：`_artifact_band_errors` 里 `if not band: return []`、`_artifact_lane_errors` 里 `if not lb: return []`。

**为什么当初会写成自我跳过**（实测，这才是根因）：**"流程布局的产物"与"泳道源但底图没画"的产物
在几何表上完全同形**——都是 `band=0 / lanes=None`。`examples/workflow` 就是流程布局，三份产物实测
全是 `0/None`；只看产物，这两件事分不开，于是只能跳过。而跳过就意味着**"泳道源被渲染成流程样"永远绿**。

**改法**：`check_artifact(geom, …, expect_lanes=None)`，语义收在一个函数里：

| 调用方 | `expect_lanes` | 行为 |
|---|---|---|
| `build._audit_geometry`（**手里有 yaml**） | `_lane_source(yaml_path)` = `L.lanes() is not None` | 拍板：该有就必须有 |
| `validate.py --artifact <产物>`（拿不到底稿） | `None` | 退化为**按产物自称**：`band` 或 `lanes` 任一存在即视为泳道产物、全强度查 |

⇒ **这是明说的弱化，不是静默**：CLI 单跑抓得到"画了一半"（有带无底色 / 有底色无带 / 底色没铺满），
抓不到"两边全缺"；那一格只有 `build` 能抓（它有 yaml）。

**两个方向都报错**：该有而没有 → `没有里程碑带宽 / 没有泳道底色盒`；不该有却画了 → `布局判错了`。

#### 门禁同步（`gates` 296 → 308）

新增 `_check_lane_expectation`：6 条单元断言（含 `expect_lanes=None` 那条**弱化本身**也被钉住）
+ 端到端 4 条。**写这条用例时自己踩了两个坑，都由门禁当场抓出**：

1. **替身挂上了但没生效**：`run('build.py', ft)` 起的是**子进程**，在 `gates` 进程里改
   `build.render_svg` 对子进程无效 ⇒ 报"命中 0 次"。必须**同进程**调 `_b.main([…])`
   （与 `_check_build_rollback` 同一套路）。
2. **拿 `render_html` 当"漏画底图"的替身等于没模拟**：泳道源在 html 里**本来就画底色**，
   交出来的产物照样有 `lanes` ⇒ build 正常退 0、用例白跑。正确姿势是**先正常出图、再把
   `<g class="lanes">…</g>` 摘掉**，并当场断言"交出去的确实没有 lanes"（产物被 rollback 还原后，
   盘上那份已经看不出替身交过什么）。

```text
✓ 泳道源、产物没画底图：报"没有里程碑带宽"           ← 产物自称永远判不出来的一格
✓ 泳道源只画了里程碑带、没画底色盒：报"没有泳道底色盒"
✓ 流程源、产物却画了底图：报"布局判错了"             ← 反方向
✓ 流程源、产物没有底图：放行                        ← workflow 就是这一类
✓ 拿不到底稿（expect_lanes=None）：按产物自称，同形即放行
✓ 前置：替身渲染器真的被 build 调到（导入方式一改这条先红）
✓ 泳道源渲染成流程样：build 拦下（不是崩掉）
✓ 拦下后三份产物都还原成上一版（不留没审过的交付物）
```

#### 验收

- `dev/verify/run.py` 四面全绿 **29/308/11/17**；`dev/tools/accept.py` 七门全过；`coverage 498/498 (100%)`。
- 自举链按序重跑：`fn_graph.py`（495 → **498** 函数）→ `selfboot_gen.py` → `coverage.py`。
- **产物变化只有一处**：`examples/self-demo/self-demo-flow.svg`（7591 → 7586 字节）。
  按 D-20 在仓库外重建（**目录名必须与样例同名**，否则产物名随目录名走、比对全落空；
  **先删掉六件产物**再 build，否则 rollback 会把原件还原回来、量到的是遗留物），
  逐文件 md5 比对后**只拷回这一个**。`invariants` 由 9/11 回到 11/11。

