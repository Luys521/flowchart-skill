# -*- coding: utf-8 -*-
"""layering.py — 分层门禁：谁许依赖谁。

用户 2026-09-14 定的目标架构是两层（外加一层编排）：

    公共层（底层） ←── 模块层（组件） ←── 编排层（入口）

三条规则：
1. **模块只单向依赖公共层**。模块层之间**不许有代码依赖**——它们的协作走**产物**
   （上游产出、下游消费），那是数据流，不是 import。
2. **公共层可以互相引用**（它是最底层，彼此之间不设方向约束），但**不许反向依赖上层**。
3. **编排层**是流水线的驱动者，允许依赖上面两层；反向依赖一律违规。

为什么值得单设一道门禁：`manifest → render_html` 这种"公共层回头拿模块层的一个常量"，
在源码里只是**一行延迟 import**（写在函数体内），读代码几乎看不见、跑测试也不报错；
只有把全部模块的 import 按层摊开比对，方向错了才现形。实测：本门禁上线前有 1 条违规、
修好后 0 条。

退出码：**0** = 无违规；**1** = 有违规；**2** = 输入读不了（图缺失 / 模块没归层）。
输入：`dev/tools/fn-graph.json`（`dev/tools/fn_graph.py` 产出）。**它是快照，代码改了必须重跑。**
"""
import json
import sys
from collections import Counter
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import SCRIPTS, TOOLS  # noqa: E402

GRAPH = TOOLS / 'fn-graph.json'

# ── 分层归属 ────────────────────────────────────────────────────────────────
# 判据不是"名字听起来像哪层"，而是**谁依赖谁**：公共层的成员只被依赖、或只在公共层内互相引用；
# 一旦某个模块反向依赖上层，它就该被重新归位（或者那条依赖该被去掉）。
#
# 公共层：提供纯能力（解析 / 几何 / 文本 / 契约 / 读回），被多方复用，自身不碰流水线编排。
PUBLIC = {
    'semantics',          # 文本语义与跨模块约定常量；出度 0，被 14 个模块依赖
    'geometry',           # 网格 / 吸附 / 线段谓词；出度 0
    'artifact',           # 产物命名的唯一出处；出度 0
    'cells',              # 产物里「AI 格」的填法（待填清单 + 按列名回写）；出度 0
    'textquality',        # 抽取质量判据（§1.5 手段 0）：被分派器复用；出度 0
    'pptx_text',          # .pptx 取文字（zip + ppt/slides/*.xml）：摘要器与读者共用同一句；出度 0
    'flowtable_layout',   # 行列与槽位计算；出度 0
    'flowtable',          # 《流程表》解析
    'flowtable_check',    # 结构校验 H1–H8 三层 + 表头 H9
    'flowtable_colors',   # 执行主体配色与跨层继承
    'router',             # 流程布局布线
    'lane_router',        # 泳道布局布线（与 router 同接口两实现）
    'swimlane',           # 泳道网格（与 geometry.Grid 同接口两实现）
    'label',              # 边标签定位
    'engine',             # 装配门面：把上面几件装成 L.*
    'manifest',           # 渲染契约：定义契约 + 按契约反查产物
    'xml_reader',         # drawio 读回与几何反解
    'writeback',          # 回写与文件级比对
}

# 模块层：流水线上的工位，各有自己的产物；只许依赖公共层。
MODULE = {
    'init',           # → 工作目录 + 两份模板
    'clarify',        # → frontier / 简报（stdout）
    'table_to_dsl',   # → flow.yaml + flow.manifest.json
    'layer_index',    # → <流程名>-index.md
    'render_html',    # → <流程名>-flow.html
    'render_drawio',  # → <流程名>-flow.drawio
    'render_svg',     # → <流程名>-flow.svg（W7b 起；可编辑中间态）
    'validate',       # → 几何报告（stdout / --dump）
    'shot',           # → *.shot.png
    'probe',          # → materials[] 骨架（材料探测分档，PIPELINE-SPEC §1.2）
    'ledger',         # → evidence.json（证据账本，PIPELINE-SPEC §2）
    'parse_ooxml',    # → elements[] JSON（OOXML 解析适配器，PIPELINE-SPEC §1.4）
    'parse_pdf',      # → elements[] JSON（PDF 文本层适配器，PIPELINE-SPEC §1.4）
    'parse_legacy',   # → elements[] JSON（legacy 走外部转换器，PIPELINE-SPEC §1.4）
    'parse_text',     # → elements[] JSON（纯文本：md / txt / csv / json，PIPELINE-SPEC §1.4）
    'render_pages',   # → 每页 PNG + 待填 vlm 骨架（转图片，PIPELINE-SPEC §1.5 手段 2）
    'import_table',   # → flowtable.md（外部节点表 → 契约流程表，PIPELINE-SPEC §4）
    'intake',         # → intake.md（L1 材料卡片 + 卡片校验器，PIPELINE-SPEC §3）
    'plan',           # → plan.md（L2 计划：流程清单 + 澄清申请 + 排除清单，PIPELINE-SPEC §4）
    'recon',          # → 侦查结论表草稿（难度排序 + 结构缩样，PIPELINE-SPEC §1.5）
    'drift',          # → drift.md（漂移清单 + 缺口清单，PIPELINE-SPEC §5 循环的发动机）
    'query',          # → stdout 的一小批证据（点名取子集 + 游标，PIPELINE-SPEC §5.3）
}

# 编排层：驱动整条流水线，允许依赖上面两层。
# `parse` = 解析分派器：按固定顺序跑各适配器（子进程 + 产物，判据不在它那里，见 PIPELINE-SPEC §1.4）。
ORCH = {'build', 'sync', 'parse'}


def short(p):
    return Path(str(p)).stem


def layer_of(name):
    if name in PUBLIC:
        return 'public'
    if name in MODULE:
        return 'module'
    if name in ORCH:
        return 'orch'
    return None


def load_edges(graph_path):
    """{ (src, dst): {被引用的函数名…} }，含函数体内的延迟 import。"""
    g = json.loads(Path(graph_path).read_text(encoding='utf-8'))
    edges = {}
    for f, v in g.get('imports', {}).items():
        src = short(f)
        for tgt, fns in v.items():
            dst = short(tgt)
            if dst != src:
                edges.setdefault((src, dst), set()).update(fns or ())
    return edges


def verdict(src_layer, dst_layer):
    """返回违规原因；None 表示合法。"""
    if src_layer == 'public':
        return None if dst_layer == 'public' else '公共层不许依赖上层（它是比上层更稳定的地基）'
    if src_layer == 'module':
        if dst_layer == 'public':
            return None
        if dst_layer == 'module':
            return '模块层之间不许有代码依赖（协作走产物，不走 import）'
        return '模块层不许依赖编排层'
    return None          # 编排层依赖谁都可以


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    graph = Path(argv[0]) if argv else GRAPH
    if not graph.exists():
        print(f'✗ 读不到依赖图: {graph}')
        print('  → 先跑 python dev/tools/fn_graph.py 生成它（它是快照，代码改了要重跑）')
        return 2
    try:
        edges = load_edges(graph)
    except (OSError, ValueError) as e:
        print(f'✗ 依赖图解析失败: {e}')
        return 2

    known = PUBLIC | MODULE | ORCH
    seen = {short(p) for p in json.loads(graph.read_text(encoding='utf-8')).get('files', {})}
    # **并上磁盘实况**：只靠图的 `files`（快照）会漏掉"新加了模块但还没重跑 fn_graph"——
    # 而那种情况恰恰就是"新模块逃过分层门禁"：实测加 `render_svg` 时本门禁 rc=0 全绿，
    # 因为快照里根本没有它 ⇒ `seen - known` 是空集，"有模块没归层"这条守卫永远不会喊。
    # 与 coverage 那条"分母依赖过期快照"是同一类假绿。
    seen |= ({p.stem for p in SCRIPTS.glob('*.py')} if SCRIPTS.is_dir() else set())
    unknown = sorted(seen - known)
    if unknown:
        print('✗ 有模块没归层（新加的模块要显式放进 PUBLIC / MODULE / ORCH）:')
        for m in unknown:
            print(f'   - {m}')
        return 2

    bad = []
    counts = Counter()
    for (src, dst), fns in sorted(edges.items()):
        ls, ld = layer_of(src), layer_of(dst)
        if ls is None or ld is None:
            continue
        why = verdict(ls, ld)
        if why:
            bad.append((src, ls, dst, ld, sorted(fns), why))
        else:
            counts[f'{ls}→{ld}'] += 1

    print(f'分层门禁：{len(known)} 个模块（公共 {len(PUBLIC)} / 模块 {len(MODULE)} / 编排 {len(ORCH)}）'
          f' · 依赖边 {len(edges)} 条')
    allow = ' · '.join(f'{k} {v} 条' for k, v in sorted(counts.items()))
    print(f'  合法边：{allow}')
    if not bad:
        print('✓ 无违规：模块层没有横向代码依赖，公共层没有反向依赖')
        return 0

    print(f'✗ 违规 {len(bad)} 条：')
    for src, ls, dst, ld, fns, why in bad:
        print(f'   {src}（{ls}）→ {dst}（{ld}）  [{", ".join(fns)}]')
        print(f'      {why}')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
