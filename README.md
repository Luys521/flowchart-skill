# flowchart-skill

> 把流程、SOP、审批链路、合同与白板提炼成流程图，或把已有流程图重建为统一风格：以《流程表》为唯一事实源，过结构校验后渲染 HTML 评审版与 drawio 协作版，支持流程与泳道两种布局。

## 一句话本质

一台「流程表 → 流程图」的渲染机。它**只消费 `flowtable.md`**，产出三份产物。
流程表是唯一事实源，图只是它的视图。**没有流程表，就不渲染。**

定位是「**高级 mermaid**」：AI 独立完成提炼与渲染，**用户只对最终渲染图负责**——
AI 拿不准的地方不写在中间产物里（用户不会打开），而是以 `⚠` 标在流程表，渲染成**图上醒目虚线的节点**。

## 质量由什么保证

**两道机器门禁 + 一道自检留痕 + 一个同步闭环**：

| 环节 | 性质 | 查什么 |
|---|---|---|
| 结构校验 | 机器阻断 | H1–H8 三层：①节点（编号/语义）②类型（起止、出边、分支）③关系（引用、连通、回路） |
| 自检留痕 | AI 自查 | 按检查表自查；推断处 `⚠` 上图（虚线），不设「等用户确认」的卡点 |
| 质量门禁 | 机器阻断 | 八项几何：引用完整 / 节点不重叠 / 边不穿节点 / 边不横穿自身端点 / 边不重叠（正交交叉允许）/ 标签压线 / 画布内 / 网格对齐 |
| 产物审核 | 机器阻断 | 拿 `<流程名>-flow.manifest.json` **反查每份产物**（逐项比集合）+ 反解产物真实坐标跑几何自检 |

产物审核最容易被忽略：前两道检查一个读流程表、一个读 `<流程名>-flow.yaml`，**都不看产物**——
所以「渲染器少画一个节点」它们永远发现不了。审核不过会指出丢了哪个节点，
**exit 1 并把刚写下的产物还原**（盘上不留没审过的交付物）。

## 目录

```text
SKILL.md              主入口：触发方式、标准处理流程、防呆、目录表
scripts/              渲染与校验脚本（46 模块 = 30 个带 CLI 的入口 + 16 个纯库）
  dictionary.yaml     布局/配色/文字的数值字典
references/           出图时按需读的规范（7 份）
templates/            3 份模板（其中 2 份由 init.py 拷进 output/<名称>/：流程表骨架 + 自检清单；
                      另一份 flowtable-template.md 是**格式基准**，与 examples/workflow 逐字一致）
examples/workflow/    **格式基准**（SKILL 把自身工作流画成图，30 节点 / 41 边）
output/               出图产物目录（本地，不进库）
dev/                  **维护分区**——只有改仓库的人进来，出图时不需要读它
  dev/verify/             四个面自检（契约一致 / 门禁拦截 / 不变式 / 端到端）
  dev/tools/              七件仪器 + 一件清场工具（清单见 dev/tools/README.md：fn_graph / coverage / api_audit / equiv / layering / hygiene / aesthetic）
  baseline/           examples 的同构镜像：机器生成的产物（进库，安全网的基准）
  DECISIONS.md  ARCHITECTURE.md  REPO-MAP.md   设计文档
  coding-spec.md      代码质量自检对照表（行业原则 → 本仓库规则 → 拦它的仪器）
  _paths.py           全仓唯一的路径解析点
```

**产品区 / 维护区的分界**：出图时的 AI 会不会读它。会读 → 根下；不会读 → `dev/`。

## 两套完整渲染成果（给人看的标准展示）

`dev/baseline/` 里放着**两套已经跑完的自举出图成果**，克隆下来直接双击 `.html` 就能看，
不必先跑命令——它们是这个 SKILL 画出来的东西长什么样：

| 成果 | 位置 | 规模 |
|---|---|---|
| **工作流自举** | `dev/baseline/workflow/workflow-flow.html` | 30 节点 / 41 边，内嵌 9 张子图 |
| **代码地图自举** | `dev/baseline/self-boot/self-boot-flow.html` | 48 节点 / 47 边，**内嵌 46 张模块子图**（节点 = 该模块的函数，规模现跑现取）、drawio 47 页（1 张根表 + 46 张模块表） |

两份都是**单文件**：点可下钻节点即切视图（`Ctrl/⌘+点击` 另开窗口停在该层），发给别人只发那一个 html。
`dev/baseline/workflow/` 同时是 `verify` 面③的**字节不变基准**（改了渲染器就必须与它对齐）。

> 为什么这份成果必须进库：`output/` 是 .gitignore 的，克隆后什么都没有。
> 而"这套代码自己长什么样"是这个仓库最该被看见的东西——它是自举的成品，也是格式基准的实物。
> 自举代码地图由 `dev/tools/selfboot_gen.py` 生表、`build.py` 出图，收口见 `dev/tools/selfboot_gen.py` 的用法段。

## 快速开始

```bash
python scripts/init.py <名称>                              # 建 output/<名称>/ 并放入模板
# 填 output/<名称>/flowtable.md（列规范见 references/flowtable-spec.md）
python scripts/table_to_dsl.py --check "output/<名称>/flowtable.md"   # 结构校验
python scripts/build.py "output/<名称>/flowtable.md"                   # 一键渲染三份产物
python scripts/shot.py "output/<名称>/<名称>-flow.html"                 # 视觉自检截图
```

Python 需可用 `yaml`。样例只留事实源（`examples/workflow/`），产物在基线区，重跑：

```bash
cp -r examples/workflow/. dev/baseline/workflow/     # 把表铺到产物旁边（build 要求同目录）
python scripts/build.py <基线目录里那张临时表>
```

> 基线里那张 `flowtable.md` 只是构建时的临时表（`examples/` 才是事实源的家），
> 故不写字面路径——面①有一条断言"文档引用的路径都必须存在"。

## 改完东西跑自检

**这一节是"改仓库"的入口**——`SKILL.md` 只写"出图"要做的事，维护动作一律留在这里。

```bash
python dev/verify/run.py              # 四个面全跑（改完脚本/文档/字典/样例就跑这个）
python dev/verify/run.py --only gates # 只跑一个面
```

退出码 0 = 全过；1 = 有面未通过。中间产物落在 `.verify_tmp/`：**全过自动删掉，有失败就保留**。

改之前先读几份（都住 `dev/`）：

| 文件 | 何时读 |
|---|---|
| `dev/verify/README.md` | **改脚本前**——含加用例的约定与源码注释约定 |
| `dev/DECISIONS.md` | **改设计前**——记"曾经是那样、为什么改成这样"，含被否决过的方案 |
| `dev/ARCHITECTURE.md` | 动模块边界/渲染器注册表时 |
| `dev/REPO-MAP.md` | 想知道"每个脚本消费什么、生产什么"时 |
| `dev/PIPELINE-SPEC.md` | 碰"材料→流程表"这一段（L0–L4）时——**契约的唯一出处**；实现与它不一致先改它 |
| `dev/coding-spec.md` | 想知道"某条行业原则在本仓落到哪、谁拦它"时——**规则 ↔ 仪器的对照表**（含"已知不做"清单，**提新方案前先翻它**） |
| `dev/NODE-AUDIT.md` | 想核"节点原则在真材料上到底成不成立"时——盲读复现与逐条对账的原始读数 |
| `dev/AUDIT-FIX-PLAN.md` | 想追溯这一轮加固的**计划与验收判据**时（批 0—批 3 的账，已执行完） |
| `dev/_paths.py` | 动目录布局时——**布局假设只在这一处表述** |

> `dev/tools/fn-graph.json` 是**快照**：代码改了要重跑 `python dev/tools/fn_graph.py`，否则拿旧图裁决新代码。

## 输出契约

每个流程一个独立目录，文件名固定。产物名 = `<流程名>-flow.*`，流程名取**目录名**（表名是约定名 `flowtable` 时）或表名：

```text
output/<名称>/
├── flowtable.md        ← 事实源，也交付（语义变更的唯一入口）
├── checklist.md        ← 自检报告（AI 推断项在此留痕）
├── <名称>-index.md           ← 层级索引（派生物，build 自动刷新）
├── <名称>-flow.yaml           ← 内部中间表示，不交付；几何可手调、语义禁改
├── <名称>-flow.manifest.json  ← 渲染契约（自检产出），供渲染后反查
├── <名称>-flow.html           ← 交付物① 评审语义（**单文件**：有子图时整条层级内嵌在里面）
├── <名称>-flow.drawio         ← 交付物② 微调几何
└── <名称>-flow.svg            ← 交付物③ 朴素可编辑中间态
```

有 `⊞` 子表时，子图**不再单独产出 html**——被内嵌进主 html，点可下钻节点是在同一份文件里切视图。
发给客户就发那一个 html。drawio 仍按每表一份、靠多页承载层级。
**同一个流程的迭代始终在这一个目录内进行**，不要每轮另起新名。

## 最容易踩的几条

- **跳过流程表直接出图** / **跳过校验直接出图** → 绝对禁止
- **在 drawio 里手工调完几何后重跑 `build.py`** → 手工成果会被覆盖；要保住改动走 `sync.py`
- **在 `<流程名>-flow.yaml` 里改语义**（名称 / 主体 / 分支）→ 必须回写流程表后重新生成
- **以为 `validate.py` 全绿、线就一定接在框上** → 它与渲染器共用同一个 router，接歪了会「同错同对」一起通过

完整防呆清单见 `SKILL.md`「常见错误与防呆」。

---

# 附录：仓库来历与开发记录

> **与"怎么用这个 SKILL"无关**——这是仓库**怎么来的**、当年那次开发会话改了什么。**出图不需要读它**；
> 判断"这套代码现在是不是活的"才看这里。保留它是因为它是本包唯一的一手来源记录。

本仓库来自一个 WorkBuddy 资料库**任务分享页**（标题「闲散 与 WorkBuddy 的对话」，`kind=web`，
节点 `VUYPaalbSzFn29oOCdc1aW`）——记录了一次 `flowchart-skill` 开发会话：把验证基线从
「gates / invariants / e2e 三面报红」修到「四面全绿」，另附完整源码压缩包（163 条目）。

> 上面是**当时**的形态（样例还叫 `self-demo`、产物还在样例目录里、`dev/verify/` 还在根）。
> 2026-09-15 的目录重构（D-66）把样例改名 `workflow`、产物移进 `dev/baseline/`、`dev/verify/`+`dev/tools/` 移进 `dev/`。

**当前实测（2026-09-17 原样重跑；用例数随代码增长，以现跑现取为准：`python dev/verify/run.py`）**：

```text
面① 契约一致性   36/36 通过      面③ 不变式      17/17 通过
面② 门禁拦截    383/383 通过     面④ 端到端往返   17/17 通过   → EXIT=0
dev/tools/accept.py  十一道门全过（0 仪器故障）
```

`build.py` 在样例上也已实跑通过，输出见上文「快速开始」。即：**这套代码在本机是活的**——
结构校验、八项质量门禁、产物审核、几何自检、无头截图全部可用。

**那次会话修了什么**（并留一处错记载作警示）：

| 问题 | 根因 | 修法 |
|---|---|---|
| `gates` 134/135：`离格 col_x：吸附 + 提示，不阻断` | `gates.py` 硬编码 `b'  - 400\r\n'`，而生成的 yaml 是 LF，替换命中 0 次 | 改成不依赖换行符的替换 |
| `invariants` 8/11：`build 幂等` 等三项 | `examples/` 产物过期需重生成；第三项与上条同源的 CRLF 测试 bug | 同步修 `invariants.py` 并重生成样例 |
| `e2e` 14/15：`截图自检可用` | 记的根因是「`shot.py` 未带 `--no-sandbox`」——**这个 flag 在代码里从来不存在，是错的** | 见下一行 |
| `e2e` 16/17：同名（**2026 复现**） | 真实根因是**本地化编码**：GBK 控制台下 `shot.py` 截图已成功、PNG 已落盘，却崩在末行 `print('✓ 已截图…')` | 补 `stdout.reconfigure(encoding='utf-8')` + 加断言（D-63） |

> 第三行保留原记载是有意的：**一条描述错根因的记录比没有记录更危险**——照它去改浏览器参数，红点不会动。
