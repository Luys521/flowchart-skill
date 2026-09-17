# -*- coding: utf-8 -*-
r"""hygiene.py — 「有什么是白写的」静态裁决器：没人用的 import 与没人调的私有函数。

## 它回答什么、不回答什么（先读这条，否则会把结论用错）

回答：**① 没被引用的 import 绑定；② 没有任何调用者、且不属于"静态图必有假缺口"那几类的模块级函数。**

**不回答**：方法（`X.f`）的死活、类的死活、任何"设计是否合理"。原因不是偷懒，是**静态调用图在本仓
结构上必然漏报**，实测三类硬缺口：

  ① `__init__`：图中**指向 `__init__` 的调用边为 0 条**——它不建这条边，所以每个构造器看起来都"没人调"。
  ② **门面装配**（D-19 的 `engine.load`）：`L.width` / `L.grid.Y` 这类属性在 `Engine.__init__` 里
     动态挂上，静态求值解不出接收者，`self.grid.Y()` 落进 `unresolved`。
  ③ **按名查表**：`build.RENDERERS` 用**字符串**指定反解器（`'ids': 'read_svg'`、
     `'geom': 'geometry_from_svg'`），函数确实被调到，但调用点在静态图里不可见。

因此本工具**只判"方法之外的模块级函数"**，并把上述三类**整类排除**——宁可漏报，不可把
`Grid.Y`、`read_svg` 这种真在用的东西报成死代码（实测：不加这条纪律，510 个函数里会误报 40 个）。

## 与邻居的分工（不许互相替代）

  `coverage.py`   函数→流程表**画全了没有**（分母来自依赖图）
  `layering.py`   模块间**依赖方向**对不对
  `api_audit.py`  重构前后**函数面丢没丢**（要一个 git 底本）
  `hygiene.py`←本  **没人用的东西有哪些**（只看当前工作树，不需要底本）

退出码：**0** = 干净；**1** = 有发现；**2** = 输入读不了（依赖图缺失 / 不是合法 JSON）。
依赖图是快照：**代码改了先跑 `python dev/tools/fn_graph.py`**。
"""
import argparse
import ast
import collections
import json
import sys
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO as ROOT, SCRIPTS, TOOLS  # noqa: E402

GRAPH = TOOLS / 'fn-graph.json'

#: 整类排除的花名册（判据写在模块 docstring 的 ①②③；加名字前先想清"图为什么不建这条边"）。
EXCLUDE_QUALNAME_SUFFIX = ('__init__', '__new__', '__call__', '__enter__', '__exit__',
                           '__iter__', '__next__', '__repr__', '__str__', '__eq__', '__hash__')


class HygieneError(Exception):
    """输入读不了（依赖图缺失 / 不是合法 JSON）——属仪器故障，不是"发现了问题"。"""


def load_graph(path):
    p = Path(path)
    if not p.exists():
        raise HygieneError(f'依赖图不存在: {p}（先跑 python dev/tools/fn_graph.py）')
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise HygieneError(f'依赖图读不动: {p}（{e}）')


def used_names(tree):
    """文件里**被真正读取过**的名字集合。

    只收 `Name(Load)` 与 `Attribute` 的根名字：`from x import f` 之后写 `f()` 记 `f`，
    写 `f.g()` 也记 `f`。**刻意不收注解**——注解里出现 `X` 不代表运行时用了 `X`，
    按名字记会掩盖真实未用；宁可漏报。
    """
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            cur = n
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                out.add(cur.id)
    return out


def string_literals(tree):
    """文件里出现过的字符串字面量集合。

    **为什么必须收这个**：本仓的渲染器/反解器是**按名现查**的——`build._RENDERER_SPECS`
    把函数名写成字符串（`'ids': 'read_svg'`），`_renderer()` 再 `globals()[name]` 取出来。
    这是**故意的**：`dev/verify/gates.py` 靠替换 `build.render_html` 这个模块级名字来证明
    "渲染器写空壳时 build 会退 1"，注册表若固化函数对象，那条用例就变成假绿（见 build.py 注释）。
    所以"名字以字符串出现在同文件里"= 该 import 是**有意保留的动态出口**，不是死代码。
    实测：漏掉这条会把 13 处误报成未用（真未用只有 3 处）。
    """
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _binding_names(node):
    """一条 import 语句绑定的局部名字（含 `as` 别名；`import a.b` 绑定 `a`）。"""
    names = []
    if isinstance(node, ast.Import):
        for a in node.names:
            names.append(a.asname or a.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            if a.name == '*':
                continue          # 星号导入不产生可判定的绑定，跳过
            names.append(a.asname or a.name)
    return names


def find_unused_imports(path, tree):
    """(行号, 绑定名, 语句原文) 列表：import 了但整文件既没读那个名字、也没把它当字符串提过。"""
    used = used_names(tree) | string_literals(tree)
    src = path.read_text(encoding='utf-8').splitlines()
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _binding_names(node):
                if name not in used:
                    raw = src[node.lineno - 1].strip() if node.lineno <= len(src) else ''
                    out.append((node.lineno, name, raw))
    return out


def call_indegree(graph):
    """依赖图里的被调次数（按 (文件, qualname)）。"""
    ind = collections.Counter()
    for c in graph.get('calls') or []:
        if c.get('to_file') and c.get('to_fn'):
            ind[(c['to_file'], c['to_fn'])] += 1
    return ind


def _is_lookup_only(graph):
    """被**字符串**提到过的函数名（注册表 / 按名查表）——这类整类排除。"""
    names = set()
    for c in graph.get('calls') or []:
        for k in ('expr', 'via'):
            v = c.get(k)
            if isinstance(v, str):
                names.add(v.strip("'\""))
    for u in graph.get('unresolved') or []:
        v = u.get('expr')
        if isinstance(v, str):
            names.add(v.strip("'\""))
    return names


def _registry_names(scripts_dir):
    """全仓 `scripts/*.py` 里出现过的**字符串字面量**名集合。

    按名查表的调用点（`globals()[name]`、`_RENDERER_SPECS` 的 `'ids'` / `'geom'`）在静态调用图里
    看不见，只有字符串留下痕迹。凡是名字进过这张表的函数，**整类排除**——它可能真被调到。
    """
    names = set()
    for p in sorted(Path(scripts_dir).glob('*.py')):
        try:
            tree = ast.parse(p.read_text(encoding='utf-8'))
        except (OSError, SyntaxError):
            continue
        names |= string_literals(tree)
    return names


def find_dead_functions(graph, scripts_dir):
    """模块级函数里"没人调"的（已按 docstring 的 ①②③ 整类排除）。

    返回 [(文件, qualname, 行号, 行数)]，按文件、行号排序。
    """
    ind = call_indegree(graph)
    lookup = _is_lookup_only(graph) | _registry_names(scripts_dir)
    out = []
    for f, v in (graph.get('files') or {}).items():
        p = ROOT / f
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(encoding='utf-8'))
        except (OSError, SyntaxError):
            continue
        # 只取**模块级** def；方法（在 class 里）与嵌套 def 一律不看（见 docstring）
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            q = node.name
            if q.endswith(EXCLUDE_QUALNAME_SUFFIX) or q in lookup:
                continue
            if ind[(f, q)] == 0:
                span = (node.end_lineno or node.lineno) - node.lineno + 1
                out.append((f, q, node.lineno, span))
    return sorted(out)


def _fmt_file(f):
    return f.replace('scripts/', '').replace('dev/tools/', 'dev/tools/')


def report(graph, scripts_dir):
    """打印报告；返回发现总数。"""
    unused, dead = [], []
    for p in sorted(Path(scripts_dir).glob('*.py')):
        try:
            tree = ast.parse(p.read_text(encoding='utf-8'))
        except (OSError, SyntaxError) as e:
            print(f'⚠ 跳过（解析失败）{p.name}: {e}')
            continue
        rel = f'scripts/{p.name}'
        for lineno, name, raw in find_unused_imports(p, tree):
            unused.append((rel, lineno, name, raw))
    dead = find_dead_functions(graph, scripts_dir)

    print('卫生检查（只看 scripts/*.py；判据与排除项见本文件 docstring）')
    print(f'  依赖图：{_fmt_file(str(GRAPH.relative_to(ROOT)))}'
          f'  函数/方法 {sum(len(v.get("functions") or []) for v in graph.get("files", {}).values())} 个')
    print()
    print(f'── ① 没人引用的 import：{len(unused)} 处 ──')
    if unused:
        for rel, lineno, name, raw in unused:
            print(f'   {_fmt_file(rel)}:{lineno}  `{name}`   ← {raw}')
    else:
        print('   （无）')
    print()
    print(f'── ② 没人调的模块级函数：{len(dead)} 个 ──')
    if dead:
        for f, q, lineno, span in dead:
            print(f'   {_fmt_file(f)}:{lineno}  {q}()  ({span} 行)')
    else:
        print('   （无）')
    print()
    print('说明：方法与"类"不在判据内——静态图对 `__init__` / `engine.load` 门面 / 按名查表'
          '（RENDERERS）三类必然漏报，整类排除，宁可漏报不误报。')
    return len(unused) + len(dead)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='白写检查：没人引用的 import + 没人调的模块级函数',
        epilog='退出码：0 干净 / 1 有发现 / 2 仪器故障（依赖图缺失或读不动）')
    ap.add_argument('--graph', default=str(GRAPH), help=f'依赖图（默认 {GRAPH.name}）')
    ap.add_argument('--json', action='store_true', help='以 JSON 透出（供自动化消费）')
    a = ap.parse_args(argv)

    try:
        graph = load_graph(a.graph)
    except HygieneError as e:
        print(f'✗ {e}')
        return 2

    if a.json:
        unused = []
        for p in sorted(SCRIPTS.glob('*.py')):
            try:
                tree = ast.parse(p.read_text(encoding='utf-8'))
            except (OSError, SyntaxError):
                continue
            for lineno, name, raw in find_unused_imports(p, tree):
                unused.append({'file': f'scripts/{p.name}', 'line': lineno,
                               'name': name, 'source': raw})
        dead = [{'file': f, 'fn': q, 'line': ln, 'span': s}
                for f, q, ln, s in find_dead_functions(graph, SCRIPTS)]
        print(json.dumps({'unused_imports': unused, 'dead_functions': dead},
                         ensure_ascii=False, indent=1))
        return 0 if not (unused or dead) else 1

    return 0 if report(graph, SCRIPTS) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
