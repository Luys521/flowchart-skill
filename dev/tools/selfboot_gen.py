# -*- coding: utf-8 -*-
r"""selfboot_gen.py — 自举生成器：把**真实的调用关系**画成流程边，产出 `output/self-boot/` 流程表树。

**为什么**：名字面夹具只能证明"函数都在图上"，证明不了"函数之间怎么调"。本版把
`dev/tools/fn-graph.json` 的 `calls`（模块内部的**已解析**调用边）落成流程表里的真实边，
于是这张图**同时是**：① 覆盖率判据的输入（`dev/tools/coverage.py`），② 调用关系的可读视图。

口径（硬约定，改口径等于改判据）：

  树形 = `<out>/flowtable.md`（根表：模块清单，每行 `⊞ <模块>/flowtable.md`）
         + `<out>/<模块>/flowtable.md`（一张一个模块；**张数不写死在这里**——一张表对应
         `scripts/*.py` 里的一个模块，写死就会随代码增长漂掉，见 dev/coding-spec.md G7）。
         **目录名即模块名**——与 `coverage.py` 的「表↔文件映射」同一口径（D-51 身份在目录上）。

  分组 = 扁平树（根 + 模块表，**不切三层**）。模块的流水线阶段写在**根表的「项目运作阶段」列**
         （`PIPELINE_STAGES`，9 组）：不新开表，也不动 `parent`，分组信息仍在图里有据可查；
         将来若要切三层，这一列就是现成的分层依据。模块→阶段是全覆盖映射，漏一个即报错。

  主体 = 执行主体**收敛成固定三值词汇表** `AI` / `用户` / `脚本`（`SUBJECTS`），本树实际取值
         = **单一 `脚本`**：函数是脚本干的活，`开始`/`结束`/拆环判断也属于这张图的执行体。
         **不再用模块名当主体**——`meta.subjects` 会被主视图图例取并集
         （`render_html._union_subjects`），"一模块一主体"会让图例列出与模块数同阶的项
         （实测改前 **26 项**）。`AI` / `用户` 只作词汇表里的备用值（"要模型判断/生成的步骤"、
         "要人做的步骤"），本树一个都没有；将来要用直接取，**不扩表**。

  产物 = 本脚本只写**流程表**与**由布局提示展开出的几何**（`flowtable.md` / `<表名>-flow.yaml`）。
         **HTML / drawio 由 `build.py` 渲染，本脚本不重渲**。所以改了主体（或任何影响 `meta` 的
         东西）之后，**必须对真树跑一次 `build.py <out>/flowtable.md`**，盘上的
         `self-boot-flow.html` 才会变——图例取的是主体并集，是最容易"改了却看着没生效"的一处
         （作者亲自踩过：只跑生成器 + 验收器，验收器又在仓库外副本上 build，盘上 HTML 一直是旧的）。

  边 = **模块内部的已解析调用边**（`calls` 里 `from_file == to_file == 该模块`，两端都得是
       该模块的函数，按被调者去重）。**跨模块边不画**：表是自包含的，只在描述里写
       `⇢ 依赖 <模块>.<函数>`——否则"每个函数恰好出现在一张表里"就不成立，
       `coverage.py` 的「重复 / 错位」两项判据也就失去意义。
       指向**类**的边同样不画（类是分组边界、不是节点），但**记账不静默**：条数在报告里列出。

  环 = H6 要求"每个回路至少含一个判断节点"。做法不是启发式，而是**迭代拆回溯边**：
       在"删掉所有判断节点后"的子图上反复找环，每轮把 DFS 的**回溯边** `u→v` 摘掉，
       换成结构性判断节点 `D`：`u→D`、`D→(是/否)→…`。每拆一条，无判断子图就少一条边
       → 循环必然终止，终态**无判断子图一定无环**（这正是 `flowtable_check._pruned_adjacency`
       的判据，不是另一套近似）。
       判断节点名按环的形状取：自环=「递归边界？」（是=到底了→收尾，否=没到→继续递归）、
       二节点互调=「再入？」、更长=「还有下一层？」（是=再进去一层，否=收尾）。
       名字含中文与疑问号 → **非标识符** → 不会被 `coverage.py` 误当成函数名判「多余」。

  扇出 = 出边 ≥2 的节点用**序号**做标签（`1`…`N`，绝不触发「标签 >6 字」软提示），并在
       **节点描述末尾**补一行图例 `分支：1→a 2→b`——**映射不许丢**。
       出边只有 1 条时不打标签：单条线无需分辨，打上只是噪声。`开始` **例外**：它的出边
       一律带标签，含义写进 `开始` 的描述（多入口模块要能一眼看出有几个入口、从哪进）。

  叶子 = 不调本模块任何函数的函数 → 一条边指向本表的 `结束`（语义："执行完返回"）。
       **收尾一律用「结束」**：一张图可以有多个「结束」（每个结局一个，见 D-74）——
       模块表里"返回"与"被调用返回"各是各的结局，同一个类型足够。

  头 = 只写 `id` / `level` / `parent`（H9 键封闭，D-59）。根表 `L0` 无 parent；模块表 `L1`
       且 `parent: ../flowtable.md`——根表里那条 `⊞` 就是它的**回指**，声明与扫描认的是
       同一种父子关系（D-58），不许各说各话。

  描述 = `★ <docstring 首行> · L<行号> · <种类> · <分支图例> · ⇢ 依赖 …`。
       `★` 那一段让图自带文档；取不到 docstring 就整段省略，**不编**。

  提示 = 每张表**先**写一份只含 `layout.col_x` 与每个节点 `row`/`col` 的布局提示
       `<out>/<目录>/<目录名>-flow.yaml`，**随即**由产品转换器就地展开成完整几何（见下面的
       「提示落盘后必须…」）。所以你在盘上看到的是一份完整 `flow.yaml`——提示只是中间态：
       这是 SKILL 文档化的几何通道（`build.py` 默认复用已有几何，D-18/D-26），
       `sync.py` 的 `build_hint` 走的是同一条路——**不是绕开产品的私招**。

       `row` = **拓扑序里的位次**（不是表序）。表序是定义序，`01→35` 这类边要横跨 34 行、
       只能挤右通道，于是「穿过节点」「两条线叠成一条」成片出现。拓扑序让**全部边同向**，
       跨节点交叉与叠线直接归零：不写提示 25 张里只有 **11/25** 单独过 `validate`，写提示
       **25/25**（2026-09-14 04:37 快照，口径 `table_to_dsl --write` → `validate.py`）。

       位次再经一趟**相邻交换爬山**（只接受保持无环的交换，固定扫描序，无随机数）。
       目标函数**不是"长跳最短"，而是折返对数**：
           F = Σ_n（入边行差 ≥ 2 的条数）×（出边行差 ≥ 2 的条数）
       依据是坐标级取证：`validate` 报的「掉头折返」全部是「同节点的 jumpR 入边 × jumpR
       出边」在**右边框中点**共线反向（两条线的段坐标逐字重合）。`row`/`col` 只决定边的
       `kind`，决定不了端口的 y（端口 y 是 router 的现场派生量）——所以提示只能"少造这种
       组合"，不能"把它摆好看"。

       **历史快照（已不可复测，只留判据）**：在 2026-09-14 04:19 之前的引擎上实测三个目标
       函数：压长跳 55→**62（更差）**、压折返 55→**44**、放开拓扑性对照反而冒出
       `端点不在框上`。那条引擎后来修了 jumpR 错峰，同一组对比**不再可复现**（当前引擎下
       两个起手都是 25/25、0 条）。数字作废，判据保留：选折返对数，不是"试出一个能过的值"。

       光爬山不够：残留里一大半是「**唯一**入边来自很远的一行」，把它摆到相邻要跨好几行，
       单步交换半路只会先变差，爬山到不了。所以再加一个**路径覆盖起手**——贪心挑一组边
       （每节点至多一条入边、一条出边）拼成链，按链的拓扑序首尾相接，链上的边**一开始就
       相邻**；然后才爬山。两个起手各跑一遍，取代价小的那个。

       **路径覆盖起手（第四轮）的交代**：它与基线起手**同分**——当前引擎下两者都是 25/25、
       0 条，**测不出增量**。保留它只因**构造上不会更差**（取代价字典序较小者，严格不减），
       **不是因为它带来了提升**。同一份提示喂 HEAD 版引擎得 14/25、44 条、喂当前引擎得
       25/25、0 条：那 44 条全是产品侧 jumpR 错峰修的，与起手选择无关。

       两个起手都必须是**真拓扑序**。早先版本把链缩点再拼接，实测 **13 张表出现回退边**
       （最多 28 条）——缩点图上无环**不保证**原图无环。现改为 **Kahn + 优先续链**（刚放下的
       节点，若其链后继已就绪就接着放它），改后全部模块表零回退边。
       （**自查自修，无第三方复核。**）

       `col` **恒为 0**（单列）。`_edge_kind` 只对"同列 + 同列内相邻行"给 spine，把节点撒
       到多列会把边集体逼成 jumpR——实测按"调用深度分层 + 跟着前驱分列"只有 **2/25** 过关
       （同一历史快照，引擎换过之后未重测；结论"分列不划算"保留）。多列这条通道产品有
       （D-37 的 `col_x: []` 空表展开），用在这张图上不划算。
       所以 `col_x` 一律写死首列中心，口径取自 `geometry.DEFAULT_COL_X`（只借不抄）。

       **不写 `kind`**（由 `row`/`col` 经 `auto_layout` 派生，写死等于把推导值复制到盘上）；
       **更不写 `channel`/`gutter`/`gapx`**（router 的现场派生量，落盘只会把过期几何钉死——
       `sync.py:42-43` 已经把这条写进注释）。
       提示**全部由规则算出**：同一份图复跑，提示逐字节相同，没有"试出一个能过的值再写死"。

       **提示落盘后必须就地展开成完整几何**（`_materialize`，照 `build.py:_gen_dsl` 的手法
       `--write --layout <旧几何> -o <旧几何>`）。这一步不是画蛇添足：`<表名>-flow.yaml`
       同时是**子图 DSL**——`render_html.collect_views` 只认这个文件名，文件在就当它是完整
       几何；`build.py:_prepare_child` 也只在它**缺失**时才重生成。只留稀疏提示占住这条路，
       内嵌视图会崩在 `geometry.rect` 的 `KeyError: 'type'`（实测踩到过）。
       row/col 由本脚本给，`channel`/`gutter`/`kind` 由产品现场算——**派生量一个都不手写**。

入口补全：入口集合先按"模块内入度为 0"取；若模块里存在**互相独立的多个环**（环内人人有入边），
       一个入口都挑不出来 → 再按表序补 `开始→<第一个不可达者>`，补到全部可达为止。
       同理，若没有任何叶子、也没有判断走「否→结束」，就补一条 `→结束`。两条补丁都只加
       出边、不引入新环（`开始` 无入边、`结束` 无出边），所以**不影响 H6**。

退出码语义（与 `fn_graph` / `coverage` / `equiv` / `api_audit` 同一套）：

| 码 | 含义 | 触发条件 |
| --- | --- | --- |
| `0` | **生成完成，产物已写出** | 树全部写出、布局提示全部落成几何，且图里所有函数名都是标识符形态 |
| `1` | **跑完了，但有需要人看的东西** | ① 图里有函数名不符合标识符形态（会被 `coverage.py` 当结构性节点**静默吞掉** → 覆盖率虚高）；② `<out>` 下存在**不是本次生成**的 `flowtable.md`（陈旧残留，会让 `coverage.py` 报「多余」） |
| `2` | **仪表失效** | 图读不了 / 结构不对 / 目录写不出去 / **`table_to_dsl` 没能把布局提示展开成几何**（此时树是半成品，明细逐张列出） |

用法：
    python dev/tools/selfboot_gen.py
    python scripts/table_to_dsl.py --check output/self-boot/<模块>/flowtable.md
    python scripts/build.py output/self-boot/flowtable.md          # 出图（本脚本只生表）
    python dev/tools/coverage.py --tables-root output/self-boot

**完整渲染结果要进库**：`output/` 是 .gitignore 的，克隆后看不到。所以收口时把整棵树
（表 + 三份产物）拷进 `dev/baseline/self-boot/`——那是"这套代码自己长什么样"的**标准展示**，
与 `dev/baseline/workflow/` 同一口径（见 D-66/D-67）。
"""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:                        # 提示要落 yaml；没有就晚一点报人话（见 _hint）
    yaml = None

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO as ROOT, SCRIPTS, TOOLS  # noqa: E402

DEFAULT_GRAPH = TOOLS / 'fn-graph.json'
DEFAULT_OUT = ROOT / 'output' / 'self-boot'

# 与 coverage.py 同一口径：方法各算一个函数；class 是分组边界，不是节点。
COUNTED_KINDS = ('function', 'method')

# 与 coverage.py 同一口径的标识符正则（允许多段，方法的 qualname 就带点）。
# 判断节点的名字**必须落在这条正则之外**（中文 + 疑问号），否则会被当成函数名判「多余」。
IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$')

COLUMNS = ('项目运作阶段', '节点编号', '节点名称', '节点类型', '输入', '依据', '输出',
           '执行主体', '执行者', '行动所需时间', '下个节点', '节点描述')

# 多出口分隔符：与 semantics.BRANCH_SEP 同一口径（D-04 定死是 `｜`，不是分号）。
BRANCH_SEP = '｜'

EXECUTOR = 'selfboot'
TIME = '—'
STRUCT_NOTE = '（结构性节点，不是函数）'
MAX_DOC = 60

# 执行主体 = **固定三值词汇表**（用户口径：主体不许"分成很多个"）。
# 规则（生成器必须遵守）：
#   1. **函数节点一律 `脚本`**——函数就是脚本干的活；
#   2. **结构性节点（`开始` / `结束` / 拆环判断）也是 `脚本`**——它们属于这张图的执行体，
#      既不是人也不是模型；
#   3. **绝不用模块名（`validate.py` 这类）当主体**。主体落进 `meta.subjects`，
#      主视图图例取所有内嵌视图主体名的**并集**（`render_html._union_subjects`），
#      所以"一模块一主体"会让图例列出与模块数同阶的几十项——这正是本次要根治的；
#   4. `AI` 与 `用户` 留在词汇表里是给"需要模型判断/生成的步骤"与"需要人做的步骤"备用的：
#      **自举树目前一个都没有**，实际取值 = 单一 `脚本`；将来要加人/模型环节直接取这两个值，
#      不必再扩表（表外取值会被 `flowtable_colors` 当自由文本自动配色，等于没约束）。
SUBJECT = '脚本'
SUBJECTS = ('AI', '用户', SUBJECT)

# 流水线阶段：把 36 个模块按"它在这个项目里干什么"编成 9 组，写进根表的「项目运作阶段」列。
# 扁平 37 张、不切三层时，**分组信息只落在这里**——不复用这一列，分组在图里就没有据可查。
# 元组顺序即流水线顺序；`_root_rows` 按模块查表，查不到就抛错（仪器失效，不静默留空）。
PIPELINE_STAGES = (
    ('接管与解析', ('probe', 'recon', 'parse', 'textquality', 'parse_ooxml', 'parse_pdf',
                    'parse_legacy', 'parse_text', 'ledger', 'intake', 'flowtable', 'semantics',
                    'artifact')),
    ('结构校验', ('flowtable_check',)),
    ('布局与配色', ('flowtable_layout', 'flowtable_colors')),
    ('DSL 装配', ('table_to_dsl',)),
    ('渲染', ('engine', 'geometry', 'swimlane', 'router', 'lane_router', 'label',
              'render_html', 'render_drawio', 'render_svg')),
    ('产物审核', ('manifest', 'validate')),
    ('层级索引', ('layer_index',)),
    ('同步闭环', ('xml_reader', 'writeback', 'sync')),
    ('编排入口', ('build', 'init', 'shot', 'clarify')),
)
STAGE_OF = {m: s for s, ms in PIPELINE_STAGES for m in ms}

# 拆环判断节点的三种读法 → (名字, 「是」分支指向, 「否」分支指向)。
# 'v' = 环的下一跳（被摘掉的回边 u→v 原来的目标），'end' = 本表的结束。
# 自环读作"递归边界"（是=到底了→收尾，否=没到→继续递归）；其余读作"要不要再进去一层"。
CYCLE_KINDS = {
    'self':   ('递归边界？', 'end', 'v'),
    'mutual': ('再入？', 'v', 'end'),
    'long':   ('还有下一层？', 'v', 'end'),
}


class SelfbootError(Exception):
    """输入读不了（图缺失/结构不对/目录写不出去）。"""


# ----------------------------------------------------------------装载图
def _read_graph(path):
    """图 JSON → dict；读不了/结构不对一律抛 SelfbootError（→ 退出码 2）。"""
    p = Path(path)
    if not p.is_file():
        raise SelfbootError(f'函数依赖图不存在: {p}（先用 dev/tools/fn_graph.py 生成）')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        raise SelfbootError(f'函数依赖图无法解析: {p}（{type(e).__name__}: {e}）')
    if not isinstance(data.get('files'), dict):
        raise SelfbootError(f'函数依赖图结构不对: {p} 里没有 files 字典')
    if not isinstance(data.get('calls'), list):
        raise SelfbootError(f'函数依赖图结构不对: {p} 里没有 calls 列表'
                            f'（本版要画真实调用边，缺它就画不成）')
    return data


def _load_modules(data):
    """图 → (模块 → 函数清单, 模块 → 类名集合, 非标识符函数名清单)。

    函数清单按 (行号, 名字) 排（兜底保证确定性）；类不进清单（分组边界不是节点）。
    """
    modules, classes, bad_names = {}, {}, []
    for fpath, fv in sorted(data['files'].items()):
        module = Path(str(fpath)).stem
        fns = modules.setdefault(module, [])
        for fn in (fv or {}).get('functions') or []:
            name = str(fn.get('qualname') or fn.get('name') or '').strip()
            if not name:
                continue
            if fn.get('kind') == 'class':
                classes.setdefault(module, set()).add(name)
                continue
            if fn.get('kind') not in COUNTED_KINDS:
                continue
            if not IDENT_RE.match(name):
                bad_names.append(f'{module}.py::{name}')
            fns.append({'qualname': name, 'kind': fn['kind'], 'lineno': fn.get('lineno') or 0})
        fns.sort(key=lambda x: (x['lineno'], x['qualname']))
    return modules, classes, sorted(bad_names)


def _edges(data, modules, classes):
    """`calls` → (模块内边, 跨模块依赖, 被丢掉的目标计数)。

    模块内边：{模块: {(调用者 qualname, 被调者 qualname)}}
    跨模块依赖：{(模块, 函数): {(对方模块, 对方函数 qualname)}}
    被丢掉的目标：指向**类**或其它非函数节点的边——画不成节点，但**记账不静默**
    （"调用了一个类"与"调用了一个函数"是两回事，不能混进覆盖率的分母）。
    """
    fnset = {(m, f['qualname']) for m, lst in modules.items() for f in lst}
    internal, cross, dropped = {}, {}, {}
    for c in data['calls']:
        kf = (Path(str(c['from_file'])).stem, c['from_fn'])
        kt = (Path(str(c['to_file'])).stem, c['to_fn'])
        if kf not in fnset:
            dropped['调用者不在分母里'] = dropped.get('调用者不在分母里', 0) + 1
            continue
        if kt[1] in classes.get(kt[0], set()):
            key = '目标是类（分组边界，不是节点）'
            dropped[key] = dropped.get(key, 0) + 1
            continue
        if kt not in fnset:
            dropped['目标不在分母里'] = dropped.get('目标不在分母里', 0) + 1
            continue
        if kf[0] == kt[0]:
            internal.setdefault(kf[0], set()).add((kf[1], kt[1]))
        else:
            cross.setdefault(kf, set()).add(kt)
    return internal, cross, dropped


def _clean_doc(doc):
    """docstring 首行 → 一格能放下的行内文本。

    两处必须换字符，都不是洁癖：
      - `|` → `｜`：竖线是表格列分隔符，不换会**切错列**。
      - `⊞` → `▣`：`⊞` 在「节点描述」里是**子表声明语法**（D-47），不是普通字符。本仓的
        docstring 里恰好就有讨论这个标记的句子（`layer_index._visit_subflow` 等 7 处），
        原样搬进描述会被解析成"这里有个下钻子表"，凭空多出 10 条指向不存在文件的声明
        ——`build` 会报一串 `⚠ 子表不存在`，`layer_index` 还会把它们登记成表。
        换成一个形近、无语义的 `▣` 顶替：宁可少一个字符的忠实，也不能让文档**改变图的结构**。
    """
    first = ' '.join(doc.strip().splitlines()[0].split())
    first = first.replace('|', '｜').replace('⊞', '▣')
    return first if len(first) <= MAX_DOC else first[:MAX_DOC - 1] + '…'


def _doc_map(modules):
    """`scripts/<模块>.py` 的 docstring 首行 → {(模块, qualname): 首行}。

    qualname 的拼法与 `fn_graph.py` 同一套（模块级=名字，方法=`类.方法`，嵌套=`外层.内层`）。
    任何一步取不到就**整段省略**，不编——图的自述必须与源码一致。
    """
    out = {}
    for module in sorted(modules):
        p = SCRIPTS / f'{module}.py'
        try:
            tree = ast.parse(p.read_text(encoding='utf-8'))
        except (OSError, SyntaxError, ValueError):
            continue

        def walk(node, prefix):
            for ch in node.body:
                if not isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                q = prefix + [ch.name]
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(ch)
                    if doc and doc.strip():
                        out[(module, '.'.join(q))] = _clean_doc(doc)
                walk(ch, q)

        walk(tree, [])
    return out


# ----------------------------------------------------------------排布
def _order(fns):
    """表序：作用域分组 → 组内行号。返回 [(qualname, owner)]。

    owner 取 qualname 第一段：方法得到类名（`Engine.load` → `Engine`），嵌套函数得到外层函数名
    （`frontier.ring_why` → `frontier`），模块级函数得到 ''。同一个 owner 的函数必然连续，
    读表的人能一眼看出"这段是 Engine 的、那段是模块级工具函数"。
    """
    groups = {}
    for fn in fns:
        owner = fn['qualname'].split('.', 1)[0] if '.' in fn['qualname'] else ''
        groups.setdefault(owner, []).append(fn)
    out = []
    for owner, members in sorted(groups.items(), key=lambda kv: (kv[1][0]['lineno'], kv[0])):
        for fn in members:
            out.append((fn['qualname'], owner))
    return out


def _kind_cn(kind, owner, classes):
    """描述列用的种类名：方法 / 嵌套函数 / 函数。owner 是类名 → 方法；是函数名 → 嵌套函数。"""
    if kind == 'method':
        return '方法'
    return '嵌套函数' if (owner and owner not in classes) else '函数'


# ----------------------------------------------------------------拆环
def _find_cycle(order, live, idx):
    """在 live 边集上找**一个**环 → (环上节点表, 回溯边 (u, v))；无环返回 None。

    深度优先、按表序遍历、邻接表按表序排——三处都按表序，结果才可复现。
    返回的环 = 从灰色祖先 v 到当前 u 的那段 DFS 路径；`u→v` 就是闭合它的**回溯边**。
    """
    adj = {q: [] for q in order}
    for u, v in live:
        adj[u].append(v)
    for q in order:
        adj[q].sort(key=lambda x: idx[x])
    color = dict.fromkeys(order, 0)              # 0 白 1 灰 2 黑
    path = []

    def dfs(u):
        color[u] = 1
        path.append(u)
        for v in adj[u]:
            if color[v] == 1:
                return path[path.index(v):], (u, v)
            if color[v] == 0:
                got = dfs(v)
                if got:
                    return got
        path.pop()
        color[u] = 2
        return None

    for q in order:
        if color[q] == 0:
            got = dfs(q)
            if got:
                return got
    return None


def _break_cycles(order, edges, idx):
    """反复拆回溯边 → (剩下的边, 判断节点列表)。

    **这是 H6 的正解，不是启发式**：H6 的判据是"每个回路至少含一个判断节点"，等价于
    "删掉所有判断节点后的子图无环"。每摘一条 `u→v`，无判断子图就少一条边，换上的
    `u→D` 与 `D→?` 两条都挨着 D（会被剪掉）——所以每轮至少消掉一个环，必然终止，
    且终态**无判断子图一定无环**。
    """
    live = list(edges)
    decisions = []
    while True:
        got = _find_cycle(order, live, idx)
        if not got:
            return live, decisions
        cycle, (u, v) = got
        kind = 'self' if len(cycle) == 1 else ('mutual' if len(cycle) == 2 else 'long')
        live.remove((u, v))
        decisions.append({'from': u, 'to': v, 'kind': kind, 'cycle': cycle})


# ----------------------------------------------------------------单张模块表
def _reachable(out, start):
    """从 start 出发的可达节点集合（用于入口补全）。"""
    seen, stack = {start}, [start]
    while stack:
        cur = stack.pop()
        for _lb, t in out.get(cur, ()):
            if t not in seen:
                seen.add(t)
                stack.append(t)
    return seen


def _fn_key(q):
    return ('fn', q)


def _skeleton(rows, decisions):
    """一张表的**渲染图**（节点 = 行，边 = 行上真正画出来的调用边）→ (keys, succ, pred)。

    回溯边必须摘掉：拆环判断节点 D 就是被拆掉的真边 `u→v` 的替身（`u→v` 换成
    `u→D→是/否→v`），带着 `D→v` 算拓扑序会绕回同一层甚至算成回退 —— 分层的前提是先有一张 DAG。
    两边都按表序建，保证后续每一步都可复现。
    """
    keys = [r['key'] for r in rows]
    drop = {(d['key'], _fn_key(d['to'])) for d in decisions}
    succ = {k: [] for k in keys}
    pred = {k: [] for k in keys}
    for r in rows:
        for _lb, t in r['out']:
            if (r['key'], t) in drop:
                continue
            succ[r['key']].append(t)
            pred[t].append(r['key'])
    return keys, succ, pred


def _topo_order(keys, succ, pred, tie):
    """拓扑序；同层用 `tie`（表序）破平 —— 没有这一步同一张图会有多种排法，就没法逐字节复现。

    摘干净回溯边后骨架无环，队列走完 indeg 应当全 0；真有残留（环没拆净）就按表序顺延。
    宁可层次难看，也不能在这里转不出来——**静默挂起比报错难查得多**。
    """
    indeg = {k: len(pred[k]) for k in keys}
    ready = [k for k in keys if indeg[k] == 0]
    order = []
    while ready:
        ready.sort(key=lambda k: tie[k])
        u = ready.pop(0)
        order.append(u)
        for t in succ[u]:
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
    seen = set(order)
    order.extend(k for k in keys if k not in seen)
    return order


def _uturn_pairs(order, succ, pos):
    """Σ_n（行差 ≥ 2 的入边条数）×（行差 ≥ 2 的出边条数）——「折返」的代价函数。

    单列 + 严格下行时，一条边是 jumpR ⇔ 行差 ≥ 2，而 jumpR 的入段/出段都贴在节点右边框中点，
    所以"同一节点既有 jumpR 入边又有 jumpR 出边"就是折返的来源（取证见模块 docstring 的「提示」段）。
    """
    inj, outj = {}, {}
    for u in order:
        for t in succ[u]:
            if pos[t] - pos[u] >= 2:
                outj[u] = outj.get(u, 0) + 1
                inj[t] = inj.get(t, 0) + 1
    return sum(n * outj.get(k, 0) for k, n in inj.items())


def _jump_span(order, succ, pos):
    """Σ 每条边跨过的节点数 —— 只用来**破平**（折返对数相同才看它），顺带把长跳压短。"""
    return sum(max(0, pos[t] - pos[u] - 1) for u in order for t in succ[u])


def _is_acyclic(order, succ, pos):
    """全部边是否仍同向（拓扑序的判据）。用来挡住"换一下就出来一条回退边"的交换。"""
    return all(pos[u] < pos[t] for u in order for t in succ[u])


def _reduce_uturns(order, succ, pos, max_sweep=20):
    """相邻交换爬山：主目标折返对数，破平看跨节点总数。就地改 `order`/`pos`，返回终态代价。

    固定扫描序（从左到右、每轮从头扫）、只接受**严格变好**的交换、无随机数 → 同一张图
    永远得到同一个排列。交换必须保持无环：放开这条会冒出回退边，实测反而多出
    `端点不在框上`（111 条错、只过 3/25）。
    """
    cur = (_uturn_pairs(order, succ, pos), _jump_span(order, succ, pos))
    for _ in range(max_sweep):
        moved = False
        for i in range(len(order) - 1):
            a, b = order[i], order[i + 1]
            order[i], order[i + 1] = b, a
            pos[a], pos[b] = i + 1, i
            cand = (_uturn_pairs(order, succ, pos), _jump_span(order, succ, pos))
            if cand < cur and _is_acyclic(order, succ, pos):
                cur, moved = cand, True
            else:
                order[i], order[i + 1] = a, b
                pos[a], pos[b] = i, i + 1
        if not moved:                              # 一轮扫完一次都没变好 = 到局部最优
            break
    return order, cur


def _spine_forest(keys, succ, pred, tie):
    """贪心最大权匹配：挑一组边，使**每个节点至多一条入边、一条出边**被选中 → `{u: v}`。

    为什么挑这种结构：被选中的边可以摆成**相邻**（见 `_chain_order`），而相邻的同列前向边
    在 `_edge_kind` 里是 spine（竖直贴上下边框）——它和右侧水平段不可能共线，于是
    **同时消掉该边终点的 INJ 与该边起点的 OUTJ**，也就是消掉折返。

    权 = `入度(u) + 出度(v)`：把 (u,v) 变相邻会把 INJ(v) 与 OUTJ(u) 各减 1，
    折返对数 F=Σ INJ·OUTJ 相应减 `出度(v) + 入度(u)` —— 这是一阶量，没有拍的常数。

    精确解要处理一个不可分的项：同一节点两条槽都占用时 F 会多减 1（节点落在链中间），
    所以这里用贪心匹配、把残差交给后面对**真实目标函数**的爬山去修——简单且可复现。
    """
    indeg = {k: len(pred[k]) for k in keys}
    outdeg = {k: len(succ[k]) for k in keys}
    cand = [(-(indeg[u] + outdeg[v]), tie[u], tie[v], u, v)
            for u in keys for v in succ[u]]
    cand.sort()
    out_free = dict.fromkeys(keys, True)
    in_free = dict.fromkeys(keys, True)
    nxt = {}
    for _w, _tu, _tv, u, v in cand:
        if out_free[u] and in_free[v]:
            out_free[u] = False
            in_free[v] = False
            nxt[u] = v
    return nxt


def _chain_order(keys, succ, pred, tie, nxt):
    """一步一个地排：刚放下的节点若其**链后继已就绪**就接着放它 —— 这条链边就落在相邻行。

    必须是**拓扑序**。上一版想省事，先把链当成超节点做拓扑序再拼接，结果造出回退边
    （实测 13 张表、最多 28 条）：**DAG 收缩一条链不保证无环** —— `A→B→C→A` 这种链间环在
    缩点图上成立、原图上却无环（各链内部顺序把三条边错开了）。回退边比折返更糟（几何走左
    通道、语义上"往上画"），所以这条路直接废掉。

    改成 Kahn + 优先续链，天然保证拓扑性，并且**该拿的相邻一条不丢**：
    节点 v 的入度恰为 1 时，它的唯一前驱一放下、v 立刻"就绪"，此刻优先挑它 → (前驱,v) 相邻。
    而 A 类失败点（唯一入边来自很远的行）正是靠这一步治好的。
    """
    indeg = {k: len(pred[k]) for k in keys}
    ready = [k for k in keys if indeg[k] == 0]
    order, placed, cur = [], set(), None
    while ready:
        want = nxt.get(cur) if cur is not None else None
        pick = want if want in ready else min(ready, key=lambda k: tie[k])
        ready.remove(pick)
        order.append(pick)
        placed.add(pick)
        for t in succ[pick]:
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
        cur = pick
    order.extend(k for k in keys if k not in placed)   # 残留环兜底：绝不原地转不出来
    return order


def _assign_cells(rows, decisions):
    """每个节点 → (row, col)。row = 拓扑序位次（经折返消减），col 恒为 0。

    规则不是口味问题，是对着 `flowtable_layout._edge_kind` 反推、再拿产品真几何
    （`table_to_dsl --write --layout` → `validate.py`）逐轮量出来的：

      - **row 取拓扑序位次**：表序是定义序（谁先定义谁在前），调用图不是定义序的线性化，
        所以一条真实调用边会被摆成"往上画"的回退边（loop）或"跨 30 行"的长跳（jumpR）。
        拓扑序把全部边摆成同向，`validate` 的 `穿过节点` / `两条线叠成一条` / `标签互相重叠`
        三类直接归零（165 → 55 条错）。
      - **压折返**：拓扑序下只剩 `掉头折返` 一类，成因是"同节点 jumpR 入边 × jumpR 出边"。
        目标函数 F = Σ_n（行差 ≥ 2 的入边条数）×（行差 ≥ 2 的出边条数），爬山压它 → 44 条。
      - **路径覆盖起手**（`_spine_forest` + `_chain_order`）：光靠相邻交换到不了最优——
        残留里一大半是"**唯一**入边来自很远的一行"（`main` 靠 `开始`、`check_relations` 靠
        `run_checks`…），要把它摆到相邻得跨好几行，单步交换半路只会先变差。所以先贪心挑一组
        边（每节点至多一入一出）拼成链、再按链的拓扑序拼起来，让这些链的边**一开始就相邻**，
        然后才爬山。两个起手（纯拓扑序 / 路径覆盖）各跑一遍，**取代价小的那个**——保证不比
        上一版差。
      - **col 恒为 0**：`_edge_kind` 只对"同列 + 同列内相邻行"给 spine，把节点撒到多列会把
        边集体逼成 jumpR——实测按"调用深度分层 + 跟着前驱分列"只有 **2/25** 过关，
        比不写提示（3/25）还差。
    """
    keys, succ, pred = _skeleton(rows, decisions)
    tie = {r['key']: i for i, r in enumerate(rows)}          # 破平一律用表序
    starts = [_topo_order(keys, succ, pred, tie),
              _chain_order(keys, succ, pred, tie, _spine_forest(keys, succ, pred, tie))]
    best, best_cost = None, None
    for start in starts:
        order = list(start)
        pos = {k: i for i, k in enumerate(order)}
        order, cost = _reduce_uturns(order, succ, pos)
        if best_cost is None or cost < best_cost:
            best, best_cost = order, cost
    return {k: (i, 0) for i, k in enumerate(best)}


def _hint(rows, decisions):
    """一张表 → 布局提示（`<表名>-flow.yaml` 的几何部分，见 D-18/D-26/D-37）。

    **只写 row / col / col_x，别的什么都不写**，两条理由：

      - `channel`/`gutter`/`gapx` 是 router 依节点与端口**现场规划**的派生量。落盘只会把
        过期几何钉死（换布局后水平段横穿节点）——`sync.build_hint` 早就把这条写进注释了。
      - `kind` 也不写：它由 row/col 经 `auto_layout` 派生（`_edge_kind`）。写死 kind 等于
        把推导值复制一份到盘上，两份迟早不一致；空 `edges` 让 `reuse_hint` 原样保留推导值。

    `col_x` 写死首列中心（单列）：数值的家是 `geometry.DEFAULT_COL_X`，这里只借不抄。
    """
    cell = _assign_cells(rows, decisions)
    return {'layout': {'col_x': [_default_col_x()]},
            'nodes': [{'id': r['id'], 'row': cell[r['key']][0], 'col': cell[r['key']][1]}
                      for r in rows],
            'edges': []}


def _default_col_x():
    """首列中心 x：口径在 `geometry.DEFAULT_COL_X`（**唯一一份**），这里只借不抄。

    原先借的是 `flowtable_layout.DEFAULT_COL_X`——那份副本已按"列口径只许有一个家"合并回
    `geometry`（表→DSL 与生成器都只取它一个数，见 D-84）。
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        from geometry import DEFAULT_COL_X
    except ImportError as e:
        raise SelfbootError(f'读不到 scripts/geometry.py 的首列中心（{e}）——'
                            f'布局提示的列口径必须与渲染器同源，不能自己编一个数')
    return DEFAULT_COL_X


def _module_rows(module, fns, classes, internal, cross, docs):
    """一个模块 → (行列表, 统计)。行已含 id / 标签 / 描述 / 出边，可直接渲染。"""
    pairs = _order(fns)
    order = [q for q, _ow in pairs]
    idx = {q: i for i, q in enumerate(order)}
    info = {f['qualname']: f for f in fns}
    if not order:
        order = []

    edges = sorted(((u, v) for u, v in internal.get(module, ()) if u in idx and v in idx),
                   key=lambda e: (idx[e[0]], idx[e[1]]))
    live, decisions = _break_cycles(order, edges, idx)

    out = {_fn_key(q): [] for q in order}
    for u, v in live:
        out[_fn_key(u)].append((None, _fn_key(v)))

    # 判断节点：u → D；D →(是/否) …（两条分支目标必不相同，否则 H8 报"分了又合"）
    dec_at = {}
    for i, d in enumerate(decisions):
        d['key'] = ('dec', i)
        d['name'] = CYCLE_KINDS[d['kind']][0]
        dec_at.setdefault(d['from'], []).append(d)
    for d in decisions:
        _name, yes_to, no_to = CYCLE_KINDS[d['kind']]
        tgt = _fn_key(d['to'])
        out[_fn_key(d['from'])].append((None, d['key']))
        out[d['key']] = [('是', tgt if yes_to == 'v' else ('end',)),
                         ('否', tgt if no_to == 'v' else ('end',))]

    # 叶子（模块内出度为 0）→ 结束，语义"执行完返回"
    for q in order:
        if not out[_fn_key(q)]:
            out[_fn_key(q)].append((None, ('end',)))

    # 入口：模块内入度为 0 的先接上；万一一个都没有（模块里是互相独立的多个环），按表序补
    indeg = dict.fromkeys(order, 0)
    for q in order:
        for _lb, t in out[_fn_key(q)]:
            if t[0] == 'fn':
                indeg[t[1]] = indeg.get(t[1], 0) + 1
    entries = [q for q in order if indeg[q] == 0] or order[:1]
    out[('start',)] = [(None, _fn_key(q)) for q in entries]
    # 入口不够就补（按表序，可复现），补到全部可达为止——否则 H8 报「不可达」。
    # 每轮至少让一个函数变可达，所以循环次数以函数数为上界（写成 for 而不是 while，
    # 免得将来改坏这里又变成"挂住不报错"——静默挂起比报错难查得多）。
    for _ in range(len(order) + 1):
        seen = _reachable(out, ('start',))
        missing = [q for q in order if _fn_key(q) not in seen]
        if not missing:
            break
        out[('start',)].append((None, _fn_key(missing[0])))
    # 结束必须有人指过来，否则 H8 报「结束节点不可达」
    if not any(t == ('end',) for lst in out.values() for _lb, t in lst):
        if order:
            out[_fn_key(order[-1])].append((None, ('end',)))
        else:                               # 空模块（只有类）：开始直接连结束，仍是合法表
            out[('start',)] = [(None, ('end',))]

    # 行序：开始 → （函数 (+ 紧随其后的拆环判断)）→ 结束
    rows = [{'key': ('start',), 'stage': '入口', 'name': '开始', 'type': '开始'}]
    for q, owner in pairs:
        rows.append({'key': _fn_key(q), 'stage': owner or '模块级', 'name': q,
                     'type': '任务', 'fn': info[q], 'owner': owner})
        for d in sorted(dec_at.get(q, []), key=lambda x: idx[x['to']]):
            rows.append({'key': d['key'], 'stage': '拆环', 'name': d['name'],
                         'type': '判断', 'dec': d})
    rows.append({'key': ('end',), 'stage': '出口', 'name': '结束', 'type': '结束'})

    pos = {r['key']: i for i, r in enumerate(rows)}
    width = max(2, len(str(len(rows))))
    for i, r in enumerate(rows, 1):
        r['id'] = str(i).zfill(width)
        r['exec'] = SUBJECT
        r['executor'] = EXECUTOR
        r['time'] = TIME
        lst = out.get(r['key'], [])
        if r['type'] == '判断':
            r['out'] = list(lst)                    # 标签已定死是/否
        else:
            lst = sorted(set(lst), key=lambda lt: (pos.get(lt[1], 10 ** 6), str(lt[1])))
            n = len(lst)
            labeled = n >= 2 or r['type'] == '开始'
            r['out'] = [(str(i + 1) if labeled else None, t) for i, (_x, t) in enumerate(lst)]

    by_key = {r['key']: r for r in rows}
    for r in rows:
        r['desc'] = _describe(r, module, by_key, cross, docs, classes)
    hint = _hint(rows, decisions)
    stats = {'module': module, 'functions': len(pairs), 'decisions': len(decisions),
             'nodes': len(rows), 'edges': sum(len(r['out']) for r in rows),
             'hint_rows': max(n['row'] for n in hint['nodes']) + 1}
    return rows, stats, hint


def _branch_legend(r, by_key):
    """出边标签 → 目标名 的图例；只有带标签的出边才进图例（单出边不打标签，也就没有图例）。"""
    items = [f'{lb}→{by_key[t]["name"]}' for lb, t in r['out'] if lb]
    if not items:
        return ''
    head = '入口：' if r['type'] == '开始' else '分支：'
    return head + ' '.join(items)


def _split_note(d):
    """拆环判断节点的描述：把"为什么要在这里判断"写成人话（形状决定读法）。"""
    u, v = d['from'], d['to']
    cyc = '→'.join(list(d['cycle']) + [d['cycle'][0]]) if d['cycle'] else f'{u}→{v}'
    if d['kind'] == 'self':
        how = f'{u} 直接递归自己'
    elif d['kind'] == 'mutual':
        how = f'{cyc} 是互调'
    else:
        how = f'{cyc} 构成一个环'
    yes_to, no_to = CYCLE_KINDS[d['kind']][1], CYCLE_KINDS[d['kind']][2]
    yes = f'继续下一层（{v}）' if yes_to == 'v' else '收尾（结束）'
    no = f'走下一跳（{v}）' if no_to == 'v' else '收尾（结束）'
    return f'结构性判断（拆环）：{how}。是 → {yes}；否 → {no}。'


def _describe(r, module, by_key, cross, docs, classes):
    """节点描述：★文档 · 行号/种类 · 分支图例 · 跨模块依赖（都取不到就只剩结构性说明）。"""
    if r['type'] == '开始':
        parts = ['流程起点' + STRUCT_NOTE]
        leg = _branch_legend(r, by_key)
        if leg:
            parts.append(leg)
        return ' · '.join(parts)
    if r['type'] == '结束':
        return '流程终点' + STRUCT_NOTE
    if r['type'] == '判断':
        return _split_note(r['dec'])

    f = r['fn']
    parts = []
    doc = docs.get((module, f['qualname']))
    if doc:
        parts.append('★ ' + doc)
    parts.append(f"L{f['lineno']} · {_kind_cn(f['kind'], r['owner'], classes)}")
    leg = _branch_legend(r, by_key)
    if leg:
        parts.append(leg)
    deps = sorted({f'{tm}.{tf}' for tm, tf in cross.get((module, f['qualname']), ())})
    if deps:
        parts.append('⇢ 依赖 ' + '、'.join(deps))
    return ' · '.join(parts)


# ----------------------------------------------------------------根表
def _root_rows(modules):
    """根表：模块清单。名字写 `模块 · <名>`——**非标识符**，不会被当成函数名判「多余」。

    「项目运作阶段」列（`stage`）填**该模块所属的流水线阶段**（`PIPELINE_STAGES`）：扁平树里
    这是分组信息的唯一落点。模块没被映射到阶段 = 生成器口径漏了 → 抛错，不静默留空。
    """
    missing = sorted(set(modules) - set(STAGE_OF))
    if missing:
        raise SelfbootError(f'模块没有流水线阶段（补 PIPELINE_STAGES）: {"、".join(missing)}')
    rows = [{'key': ('start',), 'stage': '入口', 'name': '开始', 'type': '开始'}]
    for m in sorted(modules):
        rows.append({'key': ('mod', m), 'stage': STAGE_OF[m], 'name': f'模块 · {m}',
                     'type': '任务', 'module': m})
    rows.append({'key': ('end',), 'stage': '出口', 'name': '结束', 'type': '结束'})
    for i, r in enumerate(rows, 1):
        r['id'] = str(i).zfill(2)
        r['exec'] = SUBJECT
        r['executor'] = EXECUTOR
        r['time'] = TIME
        r['out'] = []
    chain = [r['key'] for r in rows]
    for i, r in enumerate(rows[:-1]):
        r['out'] = [(None, chain[i + 1])]
    by_key = {r['key']: r for r in rows}
    for r in rows:
        if r['type'] == '任务':
            r['desc'] = f'{len(modules[r["module"]])} 个函数 · ⊞ {r["module"]}/flowtable.md'
        else:
            r['desc'] = ('模块清单' + STRUCT_NOTE) if r['type'] == '开始' else '流程终点' + STRUCT_NOTE
    return rows, by_key


# ----------------------------------------------------------------渲染
def _render(title, table_id, level, parent, rows, note=''):
    """(标题, id, level, parent, 行, 说明) → flowtable.md 全文；LF 行尾，跨平台可复现。"""
    lines = ['---', f'id: {table_id}', f'level: {level}']
    if parent:
        lines.append(f'parent: {parent}')
    lines += ['---', '', f'# {title}', '']
    if note:
        lines += [note, '']
    lines += ['## 流程表', '',
              '| ' + ' | '.join(COLUMNS) + ' |',
              '| ' + ' | '.join(['---'] * len(COLUMNS)) + ' |']
    by_key = {r['key']: r for r in rows}
    for r in rows:
        route = BRANCH_SEP.join((f'{lb}→{by_key[t]["id"]}' if lb else f'→{by_key[t]["id"]}')
                                for lb, t in r['out']) or '—'
        lines.append('| ' + ' | '.join([r['stage'], r['id'], r['name'], r['type'],
                                        '—', '—', '—', r['exec'],
                                        r['executor'], r['time'], route, r['desc']]) + ' |')
    return '\n'.join(lines) + '\n'


MODULE_NOTE = ('> 由 `dev/tools/selfboot_gen.py` 从 `dev/tools/fn-graph.json` 自举生成：节点 = 该模块的 '
               '`qualname`，边 = **模块内已解析的调用边**；环处插入结构性判断节点（H6）；'
               '跨模块调用**不画边**，只在描述里标 `⇢ 依赖`。改代码后重跑生成器，勿手改。')


# ----------------------------------------------------------------写出
def _write(path, text):
    """写文本：统一 LF（跨平台可复现），失败抛 SelfbootError。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    except OSError as e:
        raise SelfbootError(f'写不出产物: {path}（{type(e).__name__}: {e}）')
    return path


def _stale(out_root, plan):
    """`<out>` 下所有**不是本次生成**的 flowtable.md（陈旧残留会让 coverage.py 报「多余」）。"""
    if not out_root.is_dir():
        return []
    want = {p.resolve() for p in plan}
    return [p for p in sorted(out_root.rglob('flowtable.md')) if p.resolve() not in want]


def _hint_text(hint):
    """布局提示 → yaml 全文（LF、允许中文、键序不排序——`sync.py` 落盘同一套口径）。"""
    if yaml is None:
        raise SelfbootError('缺少依赖 PyYAML：pip install pyyaml（布局提示要落 yaml）')
    return yaml.safe_dump(hint, allow_unicode=True, sort_keys=False)


def _hint_path(dir_path):
    """`<目录>/flowtable.md` 的布局提示路径 = `<目录>/<目录名>-flow.yaml`。

    名字规则与 `scripts/artifact.py:artifact_stem` 同源（约定名 `flowtable` → 退到目录名），
    这里直接用目录名拼——本生成器只产 `flowtable.md` 这一种约定名，没有第二支。
    """
    return dir_path / f'{dir_path.name}-flow.yaml'


def _materialize(out_root, names):
    """把刚落盘的布局提示**就地**交给产品转换器展开成完整几何。返回失败清单。

    为什么不能只写提示就收工：`<表名>-flow.yaml` 不只是"提示"，它**同时是子图的 DSL**——
    `render_html.collect_views` 只认这个文件名，文件在就当它是一份完整的子图几何，
    `build.py` 的 `_prepare_child` 也只在文件**缺失**时才重生成。稀疏提示占住这条路，
    build 就会拿一份缺 `type`/`desc` 的文件去画内嵌视图，**崩在 `geometry.rect` 的
    `KeyError: 'type'`**（这是实测踩到的，不是推演）。上一版就是这样把根 build 从 rc=0 弄成崩栈的。

    收口手法照抄 `build.py:_gen_dsl`：`--write --layout <旧几何> -o <旧几何>`——行列表、
    列信息由本脚本给 `--layout`，`channel`/`gutter`/`gapx`/`kind` 由 router 与 `auto_layout`
    现场算。**本脚本一个派生量都不手写**，也一个都不留在自己的代码里。
    用子进程而不是 import：转换器有自己的退出码与 stderr，隔离跑才不会把它的异常
    和本生成器的异常搅成一条堆栈。
    """
    script = SCRIPTS / 'table_to_dsl.py'
    failed = []
    for name in names:
        md = out_root / name / 'flowtable.md'
        yml = _hint_path(out_root / name)
        r = subprocess.run([sys.executable, str(script), '--write', '--layout',
                            str(yml), str(md), '-o', str(yml)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode != 0:
            tail = ((r.stdout or '') + (r.stderr or '')).strip().splitlines()[-1:]
            failed.append((name, r.returncode, tail[0] if tail else ''))
    return failed


def _build_plan(data, out_root):
    """图 → {路径: 全文} + 统计（写出与陈旧检测共用同一份清单，不会两处口径漂移）。"""
    modules, classes, bad_names = _load_modules(data)
    internal, cross, dropped = _edges(data, modules, classes)
    docs = _doc_map(modules)

    root_rows, _bk = _root_rows(modules)
    plan = {out_root / 'flowtable.md': _render(
        'self-boot — 模块索引', 'selfboot-map', 'L0', None, root_rows,
        '> 本表是自举流程表树的根：一行一个模块，`⊞` 指向该模块的函数流程表。'
        '`coverage.py` 把根表（L0）排除在覆盖率之外——它不是模块。')}
    # 根表每次都跟一张布局提示：根表是一条直链（深度 = 表序），提示与基线逐值相同，
    # 写它只为"每张表都有提示"这条规则不留例外（例外是以后漂移的入口）。
    plan[_hint_path(out_root)] = _hint_text(_hint(root_rows, []))

    stats = []
    for module in sorted(modules):
        rows, st, hint = _module_rows(module, modules[module], classes.get(module, set()),
                                      internal, cross, docs)
        plan[out_root / module / 'flowtable.md'] = _render(
            f'{module}.py 函数流程表', f'selfboot-{module}', 'L1', '../flowtable.md',
            rows, MODULE_NOTE)
        plan[_hint_path(out_root / module)] = _hint_text(hint)
        stats.append(st)
    return plan, stats, bad_names, dropped, modules, classes


# ----------------------------------------------------------------入口
def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='自举生成：函数依赖图 → 流程表树（节点名=qualname，边=模块内真实调用边，'
                    '环处插判断节点）+ 每张表的布局提示（拓扑序压折返）',
        epilog='退出码：0=写出；1=跑完但有需人看的（非标识符函数名 / 陈旧残留表）；'
               '2=输入读不了或写不出去。收敛判据：table_to_dsl --check 每张表 →'
               ' build.py <根表> → coverage.py --tables-root')
    ap.add_argument('--graph', default=str(DEFAULT_GRAPH),
                    help='函数依赖图 JSON（默认 dev/tools/fn-graph.json）')
    ap.add_argument('--out', default=str(DEFAULT_OUT),
                    help='流程表树输出根（默认 output/self-boot）')
    ap.add_argument('--quiet', action='store_true', help='只报错与告警，不报统计')
    a = ap.parse_args(argv)

    out_root = Path(a.out)
    try:
        data = _read_graph(a.graph)
        plan, stats, bad_names, dropped, modules, classes = _build_plan(data, out_root)
    except SelfbootError as e:
        print(f'✗ {e}')
        return 2

    try:
        stale = _stale(out_root, plan)
        for path, text in plan.items():
            _write(path, text)
        failed = _materialize(out_root, [''] + sorted(modules))
    except SelfbootError as e:
        print(f'✗ {e}')
        return 2

    if failed:
        print(f'✗ {len(failed)} 张表的布局提示没能落成几何（tree 是半成品，别拿去跑 build）：')
        for name, rc, msg in failed:
            print(f'    {name or "根表"}  table_to_dsl rc={rc}  {msg}')
        return 2

    if not a.quiet:
        n_fn = sum(len(v) for v in modules.values())
        n_edge = sum(s['edges'] for s in stats)
        n_dec = sum(s['decisions'] for s in stats)
        print(f'✓ 写出 {len(modules)} 张模块表 + 1 张根表，布局提示已由 table_to_dsl 展开成几何 '
              f'→ {out_root.as_posix()}'
              f'    函数 {n_fn} · 类 {sum(len(v) for v in classes.values())}（参考，类不进表）')
        print(f'  模块内边合计 {n_edge} · 拆环判断节点 {n_dec} · '
              f'提示最长 {max(s["hint_rows"] for s in stats)} 行（单列）')
        for s in sorted(stats, key=lambda x: (-x['edges'], x['module'])):
            print(f'    {s["module"]:<20} 节点 {s["nodes"]:>3}  边 {s["edges"]:>3}  '
                  f'函数 {s["functions"]:>3}  判断 {s["decisions"]}  '
                  f'提示 {s["hint_rows"]:>2} 行')
        if dropped:
            print('  · 未画成边的调用目标（记账，不静默）：'
                  + '；'.join(f'{k} {v} 条' for k, v in sorted(dropped.items())))

    if bad_names:
        print(f'⚠ 图里有 {len(bad_names)} 个函数名不符合标识符形态，coverage.py 会把它们当'
              f'结构性节点忽略（覆盖率会虚高）——请先修图，别让它静默过去：'
              + '、'.join(bad_names[:5]))
    if stale:
        print(f'⚠ {out_root} 下有 {len(stale)} 张不是本次生成的 flowtable.md（陈旧残留），'
              f'**没有删除**——它们可能让 coverage.py 报「多余」，请确认无用后手工删：')
        for p in stale[:10]:
            print(f'    {p.as_posix()}')
    return 1 if (bad_names or stale) else 0


if __name__ == '__main__':
    sys.exit(main())
