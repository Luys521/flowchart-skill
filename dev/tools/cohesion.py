# -*- coding: utf-8 -*-
r"""cohesion.py — 内聚 / 耦合的**读数**（只报不判红）：三张给人裁的清单。

**为什么要有它**（2026-09-19，D-120）：本仓有四件仪器盯"方向"（`layering`）·"白写"（`hygiene`）·
"画全了没有"（`coverage`）·"行为变没变"（`equiv`），却**没有一件盯"同一个东西写了几遍"**。
2026-09-19 那次人工审计量出四处该收口（`load_thresholds` 五份、范围语法四份、
公共层一个环、泳道底图两份）——**量完就把脚本删了**，下一次要问同样的问题又得重写一遍。
这台工具就是那次脚本的常驻版。`coding-spec` G5 也是同一件事的另半句：
"在 hygiene.py 里报'只被一个模块引用的公共层函数'清单供人裁"（`hygiene` 是门⑧、红绿分明，
把"供人裁"的清单塞进会红的门里是错的，所以单独成一件）。

**它只报，不判红**——这是刻意的：这三张表里没有一条是"错"。
- **跨模块重复**里有真重复（同一逻辑写两遍）也有**假阳性**（结构像、领域不同的两个函数）；
  机器分不出"该抽"和"碰巧像"，所以它给**相似度与行数**，让人看。
- **接口面宽度**宽不等于坏（`flowtable_check` 一次引 9 个名字是它的工作）；
- **只被一个模块引用**更不是错——`label` / `router` / `lane_router` / `swimlane` 各只被
  `engine` 引用，那是**刻意的接口边界**（N3 / N21：同接口两实现 + 装配门面）。

退出码：**恒 0**（读数没有"不过"）；**2** = 读不了输入（这不是读数，是仪器故障）。

用法：

    python dev/tools/cohesion.py                # 三张表
    python dev/tools/cohesion.py --dups         # 跨模块近似重复函数体（--min-sim 调阈值）
    python dev/tools/cohesion.py --width        # 接口面宽度：谁 import 谁、每次带几个名字
    python dev/tools/cohesion.py --single       # 只被一个模块引用的公共层函数（G5 那张清单）
    python dev/tools/cohesion.py --single --limit 0   # 全打（默认 20；逐个裁决时要看全部，D-125）
    python dev/tools/cohesion.py --cycles       # 允许边上的环（公共层互引；D-127）
"""
import argparse
import ast
import difflib
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 布局假设只表述一次（见 dev/_paths.py / D-66）：本文件在 dev/tools/ 下
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import SCRIPTS  # noqa: E402

#: 公共层名册（分层的唯一出处是 `dev/tools/layering.py`；这里**只读它**，不抄第二份）
def _public_roster():
    src = Path(__file__).with_name('layering.py').read_text(encoding='utf-8')
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Set)
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'PUBLIC'):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return set()


def _rosters():
    """`(PUBLIC, MODULE, ORCH)` 三个集合——**仍然只读 `layering.py`**（分层的唯一出处）。"""
    src = Path(__file__).with_name('layering.py').read_text(encoding='utf-8')
    got = {}
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Set)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ('PUBLIC', 'MODULE', 'ORCH')):
            got[node.targets[0].id] = {e.value for e in node.value.elts
                                       if isinstance(e, ast.Constant)}
    return got.get('PUBLIC', set()), got.get('MODULE', set()), got.get('ORCH', set())


def _import_edges():
    """`{源: {目标: {被引用的名字…}}}`——**只收模块级 `import` / `from … import`**，同 `layering` 的口径。"""
    edges = defaultdict(lambda: defaultdict(set))
    for p in sorted(SCRIPTS.glob('*.py')):
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module != p.stem:
                edges[p.stem][node.module].update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name != p.stem:
                        edges[p.stem][a.name].add('')
    return edges


def cycles(edges=None, rosters=None):
    """**允许边上的环**（Tarjan 强连通分量，只报 size ≥ 2）→ `[(层, [模块…]), …]`。

    为什么它是**读数**而不是违规：`layering.py` 的规则明说"公共层可以互相引用（它是最底层，
    彼此之间不设方向约束）"——所以 `A ↔ B` 不违反任何一条**方向**规则，`layering` 永远判它绿。
    **但 D-123 花力气拆掉了公共层里唯一的那个环**（`xml_reader ↔ writeback`，理由是"互引的两件
    要么本来就是一件、要么其中一件站错了层"）——**规则允许、实践当缺陷**，这种落差正是最该被
    量出来的东西。

    而它此前**根本没被量过**：D-123 那条写的"（环消失；`layering` 现算"环：无"）"里，后半句是
    **假的**——`layering.py` 只打印边数与违规，**不查环**（`selfboot_gen._find_cycle` 查的是
    **流程图**的环，不是模块依赖图）。那句结论是当年人工读两条边得出的。这个函数就是把
    那句话变成**随时可现算**的读数（面③ 另有一条不变式钉住"公共层内部无环"）。

    `edges` / `rosters` 可注入（默认读盘）——**"读到 0"与"读不出非 0"是两件事**：面③ 拿一张
    造出来的环去喂它，就是为了证明这台仪器**报得出非零**（不然"环：无"只是装饰）。
    """
    pub, mod, orch = rosters if rosters is not None else _rosters()
    edges = _import_edges() if edges is None else edges
    layer = {}
    for name in pub:
        layer[name] = '公共层'
    for name in mod:
        layer[name] = '模块层'
    for name in orch:
        layer[name] = '编排层'
    # 只走**合法**边（非法边是 `layering` 的活，混进来会把两件事说成一件）
    allowed = defaultdict(set)
    for src, tgts in edges.items():
        ls = layer.get(src)
        if ls is None:
            continue
        for dst in tgts:
            ld = layer.get(dst)
            if ld is None:
                continue
            ok = (ls == '编排层' or (ls == '公共层' and ld == '公共层')
                  or (ls == '模块层' and ld == '公共层'))
            if ok:
                allowed[src].add(dst)

    # Tarjan（迭代版：模块数少，但别为递归深度写一条假设）
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]
    for root in sorted(allowed):
        if root in index:
            continue
        work = [(root, iter(sorted(allowed[root])))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(allowed[w]))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        # 层标签：一个分量里通常是同一层（跨层环本身就是方向违规，归 `layering`）
                        out.append((layer.get(sorted(comp)[0], '?'), sorted(comp)))
    return sorted(out)


def _functions():
    """`[(模块, 函数名, 行数, 语句数, 归一化 token 串, 原文行, 起始行)]`——模块级函数与方法都收。"""
    out = []
    for p in sorted(SCRIPTS.glob('*.py')):
        src = p.read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                raw = ast.get_source_segment(src, node) or ''
                out.append((p.stem, node.name, node.end_lineno - node.lineno + 1,
                            sum(1 for _ in ast.walk(node) if isinstance(_, ast.stmt)),
                            _norm(node), raw, node.lineno))
    return out


def _lines(raw):
    """非空行集合（去缩进）——**逐字相同行**是另一种重复证据，与结构相似度互补。"""
    return {x.strip() for x in raw.splitlines() if x.strip()}


def _line_overlap(a, b):
    x, y = _lines(a), _lines(b)
    return len(x & y) / min(len(x), len(y)) if x and y else 0.0


def _norm(fn):
    """函数体 → **归一化 token 串**：语句种类 + 字面量 + 用到的名字。

    三样都进是有意的：只看语句种类会把"结构像、内容完全不同"的函数配成一对
    （第一版就是这么误报的：`capability.compare` 配上了 `flowtable._resolve_target`）；
    把字面量与名字带上之后，"同一个正则 + 同样两条校验"这种真重复才浮出来，
    而领域不同的两个函数会各自带上自己的标识符与常量、相似度掉下去。
    """
    toks = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            continue                                  # **文档串不进指纹**：写法不同会把真重复压下去
        if isinstance(n, ast.stmt):
            toks.append(type(n).__name__)
        elif isinstance(n, ast.Constant) and isinstance(n.value, (str, int, float, bytes)):
            toks.append(repr(n.value))
        elif isinstance(n, ast.Attribute):
            toks.append('.' + n.attr)
        elif isinstance(n, ast.Name):
            toks.append(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn:
            toks.append('def:' + n.name)
    return ' '.join(toks)


def dups(min_stmts=5, min_sim=0.85, min_lines=0.6):
    """跨模块近似重复 → `[(分数, 结构相似, 逐字行占比, 甲, 乙), …]`（同模块内不算）。

    **两条证据合起来判**（缺一条就会漏掉一整类）：
      · **结构相似**（语句种类 + 字面量 + 名字，去文档串）：抓"逻辑一样、措辞不同"；
      · **逐字行占比**：抓"连注释都抄过去"的那类。
    只认一条会漏：短函数里文档串常占一半篇幅，把它算进结构相似度会**虚高**
    （第一版就这么把 `_head ≈ _read_head` 报成 0.95），去掉之后又**虚低**——
    所以两个数都报，谁高算谁。
    """
    fns = [f for f in _functions() if f[3] >= min_stmts]
    buckets = defaultdict(list)
    for f in fns:
        key = (f[3] // 4, tuple(f[4].split(' ')[:3]))   # 粗分桶：语句数量级 + 头三个 token
        buckets[key].append(f)
    pairs = []
    for group in buckets.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a[0] == b[0]:
                    continue                          # 同一模块内不算"跨模块重复"
                rs = difflib.SequenceMatcher(None, a[4], b[4]).ratio()
                rl = _line_overlap(a[5], b[5])
                if rs >= min_sim or rl >= min_lines:
                    pairs.append((round(max(rs, rl), 2), round(rs, 2), round(rl, 2), a, b))
    pairs.sort(key=lambda x: (-x[0], -max(x[3][3], x[4][3])))
    return pairs


def widths():
    """接口面宽度：`{被 import 的模块: [(消费方, 名字数), …]}`（按消费方数降序）。"""
    got = defaultdict(list)
    for p in sorted(SCRIPTS.glob('*.py')):
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.module:
                got[node.module].append((p.stem, len(node.names)))
    return dict(sorted(got.items(), key=lambda kv: -len(kv[1])))


def single_consumer():
    """公共层里**只被一个模块 import** 的函数 → `[(公共模块, 函数名, 那个模块, 行数), …]`。

    这正是 G5 要的那张"供人裁"的清单。**不是错**：`label`/`router`/`lane_router`/`swimlane`
    只被 `engine` 用，那是同接口两实现 + 装配门面（N3/N21 明确不合并）。
    """
    public = _public_roster()
    importers = defaultdict(set)
    for p in sorted(SCRIPTS.glob('*.py')):
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.module in public and node.module != p.stem:
                for alias in node.names:
                    importers[(node.module, alias.name)].add(p.stem)
    out = []
    for p in sorted(SCRIPTS.glob('*.py')):
        if p.stem not in public:
            continue
        for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
            if isinstance(node, ast.FunctionDef):
                who = importers.get((p.stem, node.name), set())
                if len(who) == 1:
                    out.append((p.stem, node.name, sorted(who)[0],
                                node.end_lineno - node.lineno + 1))
    return sorted(out, key=lambda x: (-x[3], x[0], x[1]))


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='内聚 / 耦合读数：重复 · 接口面宽度 · 单消费方公共函数')
    ap.add_argument('--dups', action='store_true', help='只打跨模块近似重复')
    ap.add_argument('--width', action='store_true', help='只打接口面宽度')
    ap.add_argument('--single', action='store_true', help='只打单消费方公共函数（G5 那张）')
    ap.add_argument('--cycles', action='store_true', help='只打允许边上的环（公共层互引等）')
    ap.add_argument('--min-stmts', type=int, default=5, help='重复检测的语句数下限（默认 5）')
    ap.add_argument('--min-sim', type=float, default=0.85, help='结构相似度下限（默认 0.85）')
    ap.add_argument('--min-lines', type=float, default=0.6, help='逐字行占比下限（默认 0.6）')
    # 默认只打 20 行是给人"扫一眼"的；**逐个裁决**（D-125 那 46 条）要看全部，
    # 原先只能改代码——仪器打印不出它要审的那张清单，等于没有仪器。`--limit 0` = 全打。
    ap.add_argument('--limit', type=int, default=20, help='每张清单最多打几行（0 = 全打；默认 20）')
    a = ap.parse_args(argv)
    if not SCRIPTS.is_dir():
        print(f'⚠ 找不到 scripts/：{SCRIPTS}（这不是读数，是仪器故障）', file=sys.stderr)
        return 2
    all_ = not (a.dups or a.width or a.single or a.cycles)
    cap = a.limit if a.limit > 0 else None  # 0 = 不截断

    if a.dups or all_:
        pairs = dups(a.min_stmts, a.min_sim, a.min_lines)
        print(f'== 跨模块近似重复（语句 ≥{a.min_stmts} · 结构 ≥{a.min_sim} 或 逐字行 ≥{a.min_lines}）：'
              f'{len(pairs)} 对')
        print('   真重复与"结构像、领域不同"的假阳性混在一起——**机器分不出，你来看**')
        for score, rs, rl, x, y in pairs[:cap]:
            print(f'   结构 {rs} · 逐字行 {rl}  {x[0]}.{x[1]}({x[2]}行/{x[3]}句)'
                  f'  ≈  {y[0]}.{y[1]}({y[2]}行/{y[3]}句)')
        if cap is not None and len(pairs) > cap:
            print(f'   …共 {len(pairs)} 对（--min-sim / --min-lines 调阈值）')

    if a.width or all_:
        w = widths()
        print(f'\n== 接口面宽度（{len(w)} 个被 import 的模块 · 按消费方数降序）')
        print('   名字数 = 一次 import 拖进来几个东西；窄接口（中位 1–2）是"用法有约束"的读数')
        for mod, lst in list(w.items())[:cap]:
            ns = sorted(n for _c, n in lst)
            top = max(lst, key=lambda x: x[1])
            print(f'   {mod:<20} {len(lst):>2} 个消费方 · 中位 {ns[len(ns) // 2]:>2} · '
                  f'最大 {top[1]:>2}（{top[0]}）')

    if a.single or all_:
        rows = single_consumer()
        print(f'\n== 公共层里只被一个模块 import 的函数：{len(rows)} 个（G5 那张清单）')
        print('   **不是错**：同接口两实现 / 装配门面（engine）本来就是一对多；')
        print('   要看的是"它到底是刻意的接口边界，还是该并回调用方"')
        for mod, fn, who, ln in rows[:cap]:
            print(f'   {mod}.{fn:<28} ← {who}（{ln} 行）')
        if cap is not None and len(rows) > cap:
            print(f'   …共 {len(rows)} 个（--limit 0 全打）')

    if a.cycles or all_:
        cy = cycles()
        print(f'\n== 允许边上的环：{len(cy)} 组')
        print('   **不是违规**（公共层本来就允许互相引用），但互引的两件要么是一件、要么站错了层')
        if not cy:
            print('   环：无')
        for lyr, comp in cy[:cap]:
            print(f'   {lyr}：' + ' ↔ '.join(comp))
    return 0


if __name__ == '__main__':
    sys.exit(main())
