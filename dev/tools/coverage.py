# -*- coding: utf-8 -*-
r"""coverage.py — 「画全了没有」的机器裁决器：函数依赖图的成员 vs 流程表的节点名。

**为什么**：这套工作的验收标准不是"图看着挺全"，而是**每个函数都能在流程图上找到**。
这条必须机器判定，才有资格当重构循环的终止条件——否则"看起来画完了"永远收不了口。

口径（硬约定，改口径等于改判据，别顺手改）：

  分母 = `dev/tools/fn-graph.json` 里 `files[*].functions[*]` 中 `kind ∈ {function, method}` 的项。
         **方法各算一个函数**，名字取 `qualname`（如 `Grid.anchor`）；`kind == class` **不计入分母**
         ——类在图里是**分组边界**，不是节点，只作参考数字单列。三个数字分开报：函数数 / 方法数 / 类数。

  分子 = `--tables-root` 下所有 `flowtable.md`（含 `parts/` 层级）的「节点名称」列，去空白后**原样**比对。
         解析**必须走产品自身的实现**（`flowtable.parse_table`）：验证要验的就是那份解析器，
         另写一个 markdown 解析器等于验了个假的。

  表↔文件映射 = **目录名即模块名**：`<tables-root>/<模块>/flowtable.md` → `<script-dir>/<模块>.py`
         （与 D-51「身份在目录上」一致，不新增任何表头键——H9 是键封闭的）。
         `parts/` 下的子表同理（取所在目录名）。**与 `--tables-root` 同级的 flowtable.md 视为 L0 主表**
         （不是模块）→ 跳过并在报告里单列，**不算失败**。
         真实产物树是**三层**（L0 流水线阶段 / L1 阶段内模块清单 / L2 每模块一张），其中只有
         L2 的目录名是模块名；L0 与 L1（`parts/<阶段名>/…`）的目录名都不是 → 和 L0 一样走
         「表映射不到任何图文件」提示，同样是**非失败**。所以递归逻辑在**任意深度**都成立，不用改。

  四类差异分开列：
    缺失 = 图里有、**所有表里都没出现**；
    多余 = 表里有、但图里从没有这个概念（多半是旧名残留或写错）；
    重复 = 同一个函数出现在**多张表**里（约定是"每个函数恰好出现在一张表"）；
    错位 = **该模块自己的表存在**时，它的函数却出现在了**别的模块**的表里。
         "放错表"也是没体现（用户要的是"在流程中完整体现"）：`shot.py` 的函数画进 `engine` 的表，
         全局按名字看是"覆盖了"，其实那张图里根本没有它。**错位计入缺口**，但**不算作缺失**
         ——它确实画了，只是画错地方，两类要分开看见。
         该模块**自己没有表**时不算错位（还没画，按缺失报）；同一函数同时在正确表与错误表里
         → 错位与重复**两条都报**。
    名字**歧义**：不同文件可能有同名私有函数（`_parse_args` 在三个文件里都有），
    所以判定按 **(文件, 函数名)** 配对；**只有在同一文件内**才算同名冲突；跨文件同名无法归属时
    单列提示，**不计入重复、也不计入错位**（归属不了就不能说人家画错了）。

  结构性节点**不算差异、也不进分母**：节点名不像 Python 标识符的（`开始` / `结束` / `哪个入口？`）
  视为**结构性节点**，单列一个区块，**不影响退出码**。**这不是放水**：流程表按 SKILL 规则画必然
  需要这类节点——H1 要求每张表恰好一个「开始」一个「结束」，入口分派也要一个判断节点 + ≥2 条
  带标签分支才过得了 H4。它们承载的是**流程语义**（起止、分派），不是代码实体；覆盖率要回答的是
  "**每个函数**有没有被画到"，结构性节点既不是函数、也不该被当成函数来计数。
  判据是严格标识符正则（**允许多段**，方法的 qualname 就带点）：
  `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$`。
  代价要看清：**真·函数名若写成了非标识符（中文命名、带空格）也会被归进 structural 而漏判**——
  所以它只对"名字像函数名"的东西负责。正因为这条口径会把"名字不像函数名"的东西整个摘出去，
  反向也必须防：图里若真有函数名不合标识符形态，它会被**静默**吞掉 → 覆盖率虚高。为此
  `_load_graph` 顺带自检，命中就在报告顶部打一行
  `⚠ 图里有 N 个函数名不符合标识符形态，会被当作结构性节点忽略（…）：<前 5 个>`，
  `--json` 里对应 `graph_name_warnings`。**它是"图的配置有问题"的告警，不是覆盖率缺口，
  所以不影响退出码**；但必须在 stdout 上看得见——宁可吵，也不许"显示 100% 其实漏了人"。

  **它与 `dev/tools/api_audit.py` 互补、不可替代**：本工具的分母来自依赖图，而依赖图来自**当前代码**
  ——所以"代码和流程表一起被改掉"时，它**没有任何信号**（分子分母同时漂移）。"函数面有没有丢"
  必须由 `api_audit.py` 独立回答（它的分母钉死在 git 底本上，不随工作树漂移）。反过来，
  `api_audit` 不看图，所以"函数都还在、但没画进表"只有本工具能发现。

退出码：**0** = 100% 覆盖且无多余无重复无错位；**1** = 有缺口；**2** = 输入读不了（图缺失 / 目录不存在 / 解析失败）。

用法：
    python dev/tools/coverage.py --tables-root output/self-boot
    python dev/tools/coverage.py --tables-root output/self-boot --json
    python dev/tools/coverage.py --tables-root output/self-boot --allow dev/tools/coverage-fixtures/ok/allow.txt

（`--root` 是 `--tables-root` 的**隐藏别名**，为兼容既有命令保留；新写的命令请用 `--tables-root`。）

白名单文件每行一条 `模块.py::函数名`（如 `shot.py::main`），`#` 开头与空行忽略；
被豁免的条目**不计入分母**，但会在报告里单列——**不许静默忽略**，豁免也是要人看得见的决定。
白名单文件**由调用方自己提供**，仓库里只有夹具样例（`dev/tools/coverage-fixtures/ok/allow.txt`）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import SCRIPTS, TOOLS  # noqa: E402

# 计入分母的 kind：方法各算一个函数。class 是分组边界，不是节点。
COUNTED_KINDS = ('function', 'method')

# 结构性节点的判据：节点名**不像 Python 标识符**的（`开始` / `结束` / `哪个入口？` …）就不是函数。
# 必须允许多段——方法的 qualname 本身就带点（`Grid.anchor`、`build_layer_index.visit`）。
IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$')


def _is_ident(name):
    """节点名像个 Python 标识符（函数/方法名）吗？否则视为结构性节点。"""
    return bool(IDENT_RE.match(name))


class CoverageError(Exception):
    """输入读不了（图缺失/结构不对/目录不存在）。"""


# ----------------------------------------------------------------装载
def _load_parse_table():
    """拿产品自身的流程表解析器（不达标就退 2，不自己抄一个）。"""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        from flowtable import parse_table
    except Exception as e:
        raise CoverageError(f'无法导入产品解析器 flowtable.parse_table（{type(e).__name__}: {e}）')
    return parse_table


def _load_graph(graph_path):
    """fn-graph.json → {'callables': [...], 'name_index': {...}, 'counts': {...}, 'collisions': [...]}。"""
    p = Path(graph_path)
    if not p.is_file():
        raise CoverageError(f'函数依赖图不存在: {p}（先用 dev/tools/fn_graph.py 生成）')
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        raise CoverageError(f'函数依赖图无法解析: {p}（{type(e).__name__}: {e}）')
    files = data.get('files')
    if not isinstance(files, dict):
        raise CoverageError(f'函数依赖图结构不对: {p} 里没有 files 字典')

    callables, counts, per_file_names = [], {'function': 0, 'method': 0, 'class': 0}, {}
    for fpath, fv in files.items():
        fpath = str(fpath).replace('\\', '/')
        names = per_file_names.setdefault(fpath, [])
        for fn in (fv or {}).get('functions', []) or []:
            kind = fn.get('kind')
            if kind in counts:
                counts[kind] += 1
            if kind not in COUNTED_KINDS:
                continue
            name = str(fn.get('qualname') or fn.get('name') or '').strip()
            if not name:
                continue
            names.append(name)
            callables.append({'file': fpath, 'name': name, 'kind': kind,
                              'lineno': fn.get('lineno')})
    name_index = {}
    for e in callables:
        name_index.setdefault(e['name'], [])
        if e['file'] not in name_index[e['name']]:
            name_index[e['name']].append(e['file'])
    for v in name_index.values():
        v.sort()
    # 同一文件内同名 = 真冲突（跨文件同名是允许的，各文件各自有私有函数）
    collisions = []
    for fpath, names in sorted(per_file_names.items()):
        seen = {}
        for n in names:
            seen[n] = seen.get(n, 0) + 1
        for n, k in sorted(seen.items()):
            if k > 1:
                collisions.append({'file': fpath, 'name': n, 'count': k})
    file_bases = {Path(str(f)).name for f in files}
    # 防静默：结构性节点口径会把"不像标识符"的名字从缺失/多余里摘出去。如果**图里的函数**长的
    # 就是那个样子（中文命名、含空格/连字符……），它会被同一口径顺手吞掉 → 覆盖率虚高。这是**图的
    # 配置问题、不是覆盖率问题**：只显式告警，不影响退出码，但一定要在 stdout 上看得见。
    name_warnings = [{'file': e['file'], 'name': e['name'], 'lineno': e['lineno']}
                     for e in callables if not _is_ident(e['name'])]
    name_warnings.sort(key=lambda e: (e['file'], e['lineno'] or 0, e['name']))
    # **解析失败的文件要浮上来**：`fn_graph` 遇到读不动的文件只记一条 `stats.parse_errors`，
    # 那个文件的函数**一个都不进分母**——于是"删掉一个文件的语法"能让覆盖率反而变好看（实测：
    # 把一个模块改成语法错误，coverage 照样报 100% 通过）。这不是覆盖缺口，是**仪器坏了**：
    # 下游按退 2（输入读不了）处理，与"图/目录都不存在"同一档（见 D-81 的姊妹条 D-83）。
    parse_errors = list((data.get('stats') or {}).get('parse_errors') or [])
    return {'callables': callables, 'name_index': name_index, 'counts': counts,
            'collisions': collisions, 'file_bases': file_bases,
            'name_warnings': name_warnings, 'parse_errors': parse_errors}


def _collect_tables(root, script_dir):
    """--tables-root 下所有 flowtable.md → 表清单（含模块名、节点名集合、是否 L0、映射到的脚本）。"""
    parse_table = _load_parse_table()
    root = Path(root).resolve()
    tables = []
    for ft in sorted(root.rglob('*.md')):
        if ft.name.lower() != 'flowtable.md':
            continue
        md = ft.read_text(encoding='utf-8-sig')
        _title, _meta, rows = parse_table(md)
        names = set()
        for cells in rows:
            cells = list(cells)
            while len(cells) < 9:
                cells.append('')
            name = str(cells[2]).strip()
            if name:
                names.add(name)
        is_l0 = ft.parent == root
        module = None if is_l0 else ft.parent.name
        tables.append({
            'table': ft.as_posix(),
            'rel': ft.relative_to(root).as_posix(),
            'module': module,
            'l0': is_l0,
            'names': names,
            'script': (str(Path(script_dir) / f'{module}.py').replace('\\', '/')
                       if module else None),
        })
    return tables


def _load_allow(allow_path, graph):
    """白名单文件 → ({(文件, 函数名)}, 没匹配上的原文行)。每行 `模块.py::函数名`。"""
    if not allow_path:
        return set(), []
    p = Path(allow_path)
    if not p.is_file():
        raise CoverageError(f'白名单文件不存在: {p}')
    stems = {}
    for e in graph['callables']:
        stems.setdefault(Path(e['file']).name, set()).add(e['file'])
    allowed, unmatched = set(), []
    for raw in p.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '::' not in line:
            unmatched.append(raw)
            continue
        file_part, name_part = (x.strip() for x in line.split('::', 1))
        matched = False
        for e in graph['callables']:
            if e['name'] != name_part:
                continue
            if e['file'] == file_part or Path(e['file']).name == file_part \
                    or e['file'].endswith('/' + file_part):
                allowed.add((e['file'], e['name']))
                matched = True
        if not matched:
            unmatched.append(raw)
    return allowed, unmatched


# ----------------------------------------------------------------裁决
def _build_report(graph, tables, allowed, unmatched_allow, graph_path, root):
    """图 / 表 / 白名单 → 结构化裁决报告（人读与 --json 共用）。"""
    entries = graph['callables']
    name_index = graph['name_index']
    l0_tables = [t for t in tables if t['l0']]
    mod_tables = [t for t in tables if not t['l0']]

    denominator = [e for e in entries if (e['file'], e['name']) not in allowed]

    # 结构性节点：节点名不像 Python 标识符的（开始/结束/哪个入口？）——不是函数，是流程语义。
    # 它们不参与缺失/多余/重复/错位的任何一侧，只单列出来让人看得见。
    structural = []
    for t in mod_tables:
        for n in sorted(t['names']):
            if not _is_ident(n):
                structural.append({'table': t['rel'], 'name': n})

    covered_names = set()
    for t in mod_tables:
        covered_names |= {n for n in t['names'] if _is_ident(n)}

    missing = [e for e in denominator if e['name'] not in covered_names]
    covered = len(denominator) - len(missing)

    extra = []
    for t in mod_tables:
        for n in sorted(t['names']):
            if _is_ident(n) and n not in name_index:
                extra.append({'table': t['rel'], 'name': n})

    tables_with_name = {}
    for t in mod_tables:
        for n in t['names']:
            if _is_ident(n):
                tables_with_name.setdefault(n, []).append(t['rel'])
    duplicate, ambiguous = [], []
    for n, tbls in sorted(tables_with_name.items()):
        if len(tbls) < 2:
            continue
        nfiles = name_index.get(n)
        if not nfiles:
            continue                      # 图里没有 → 已在 extra 里报过
        if len(nfiles) == 1:
            duplicate.append({'name': n, 'file': nfiles[0], 'tables': sorted(tbls)})
        else:
            ambiguous.append({'name': n, 'files': nfiles, 'tables': sorted(tbls)})

    # 错位：该模块**自己的表存在**时，它的函数却出现在别的模块的表里。
    # 全局按名字判覆盖率会说"覆盖了"，可那张图里根本没有它——放错表等于没体现。
    file_set = {e['file'] for e in entries}
    bases = {}
    for f in file_set:
        bases.setdefault(Path(f).name, set()).add(f)
    own_tables = {}                       # 图里文件 → 它自己的表（parts 拆分时可能不止一张）
    for t in mod_tables:
        of = None
        if t['script']:
            of = t['script'] if t['script'] in file_set else None
            if of is None:
                cand = bases.get(Path(t['script']).name)
                of = next(iter(cand)) if cand and len(cand) == 1 else None
        if of:
            own_tables.setdefault(of, []).append(t['rel'])
    misplaced, seen_pairs = [], set()
    for f, own in sorted(own_tables.items()):
        own_set = set(own)
        for e in entries:
            n = e['name']
            if e['file'] != f or (f, n) in seen_pairs:
                continue
            # 跨文件同名无法归属：归属不了就不能断言人家画错了（已在 ambiguous 里提示）
            if len(name_index.get(n, [])) != 1:
                continue
            foreign = sorted(t for t in tables_with_name.get(n, []) if t not in own_set)
            if foreign:
                seen_pairs.add((f, n))
                misplaced.append({'file': f, 'name': n, 'lineno': e['lineno'],
                                  'correct_tables': sorted(own_set), 'tables': foreign})

    unmapped = [{'table': t['rel'], 'module': t['module'], 'script': t['script']}
                for t in mod_tables
                if Path(t['script']).name not in graph['file_bases']]

    total = len(denominator)
    pct = (covered * 100.0 / total) if total else None
    return {
        'graph': Path(graph_path).as_posix(),
        'root': Path(root).as_posix(),
        'counts': {'functions': graph['counts']['function'], 'methods': graph['counts']['method'],
                   'classes': graph['counts']['class']},
        'denominator': total,
        'covered': covered,
        'coverage_pct': (round(pct, 1) if pct is not None else None),
        'missing': sorted(missing, key=lambda e: (e['file'], e['lineno'] or 0, e['name'])),
        'extra': extra,
        'duplicate': duplicate,
        'misplaced': sorted(misplaced, key=lambda e: (e['file'], e['lineno'] or 0, e['name'])),
        'structural': sorted(structural, key=lambda e: (e['table'], e['name'])),
        'ambiguous': ambiguous,
        'graph_name_warnings': graph['name_warnings'],
        'name_collisions': graph['collisions'],
        'allowed': [{'file': f, 'name': n} for f, n in sorted(allowed)],
        'allowed_unmatched': unmatched_allow,
        'l0_tables': [t['rel'] for t in l0_tables],
        'unmapped_tables': unmapped,
        'tables': [{'table': t['rel'], 'module': t['module'], 'script': t['script'],
                    'l0': t['l0'], 'nodes': len(t['names'])} for t in tables],
        'converged': not (missing or extra or duplicate or misplaced),
    }


# ----------------------------------------------------------------输出
def _print_human(r):
    c = r['counts']
    pct = f"{r['coverage_pct']:.1f}%" if r['coverage_pct'] is not None else 'n/a（分母为空）'
    print(f"覆盖率 = {r['covered']}/{r['denominator']} ({pct})"
          f"    函数 {c['functions']} · 方法 {c['methods']} · 类 {c['classes']}（参考）")

    # 防静默告警：图里的函数名若不像标识符，会被结构性节点口径吞掉 → 覆盖率会虚高。
    # 这是图的配置问题、不是覆盖率问题 → 不进退出码，但必须在 stdout 上响亮地出现。
    if r['graph_name_warnings']:
        uniq = sorted({e['name'] for e in r['graph_name_warnings']})
        print(f"\n⚠ 图里有 {len(uniq)} 个函数名不符合标识符形态，"
              f"会被当作结构性节点忽略（请检查是否是中文命名/含特殊字符）："
              + '、'.join(uniq[:5]))

    if r['missing']:
        print(f"\n── 缺失（图里有、表里没有）：{len(r['missing'])} ──")
        by_file = {}
        for e in r['missing']:
            by_file.setdefault(e['file'], []).append(e)
        for f, es in by_file.items():
            print(f'  {f}')
            for e in es:
                print(f"    {e['name']}  (L{e['lineno']})")

    if r['extra']:
        print(f"\n── 多余（表里有、图里没有）：{len(r['extra'])} ──")
        by_table = {}
        for e in r['extra']:
            by_table.setdefault(e['table'], []).append(e['name'])
        for t, names in by_table.items():
            print(f'  {t}')
            for n in names:
                print(f'    {n}')

    if r['structural']:
        uniq = sorted({e['name'] for e in r['structural']})
        tables_n = len({e['table'] for e in r['structural']})
        print(f"\n── 结构性节点（不像 Python 标识符，不算函数、不判多余）："
              f"{len(r['structural'])} 条 / {len(uniq)} 个名字 / 分布在 {tables_n} 张表 ──")
        print('  样例：' + '、'.join(uniq[:8]))

    if r['duplicate']:
        print(f"\n── 重复（同一函数出现在多张表）：{len(r['duplicate'])} ──")
        for e in r['duplicate']:
            print(f"  {e['name']} → {e['file']}   出现在 {len(e['tables'])} 张表："
                  + '、'.join(e['tables']))

    if r['misplaced']:
        print(f"\n── 错位（画在别的模块的表里）：{len(r['misplaced'])} ──")
        by_file = {}
        for e in r['misplaced']:
            by_file.setdefault(e['file'], []).append(e)
        for f, es in by_file.items():
            print(f'  {f}')
            for e in es:
                print(f"    {e['name']}  (L{e['lineno']})  应画在 " + '、'.join(e['correct_tables'])
                      + '，实际出现在 ' + '、'.join(e['tables']))

    if r['allowed']:
        print(f"\n── 豁免（--allow，不计入分母）：{len(r['allowed'])} ──")
        for e in r['allowed']:
            print(f"  {e['file']}::{e['name']}")

    if r['l0_tables']:
        print(f"\n── L0 主表（不是模块，不计入）：{len(r['l0_tables'])} ──")
        for t in r['l0_tables']:
            print(f'  {t}')

    notes = []
    if r['ambiguous']:
        notes.append(f"跨文件同名、无法归属（不计入重复、也不计入错位）：{len(r['ambiguous'])}")
        for e in r['ambiguous']:
            notes.append(f"    {e['name']} —— 图里 {len(e['files'])} 个文件都有："
                         + '、'.join(e['files']) + f"；出现在 {len(e['tables'])} 张表")
    if r['name_collisions']:
        notes.append(f"同一文件内同名（图本身的歧义）：{len(r['name_collisions'])}")
        for e in r['name_collisions']:
            notes.append(f"    {e['file']}::{e['name']} × {e['count']}")
    if r['allowed_unmatched']:
        notes.append(f"白名单里没匹配上的行（写错了？）：{len(r['allowed_unmatched'])}")
        for line in r['allowed_unmatched']:
            notes.append(f'    {line.strip()}')
    if r['unmapped_tables']:
        notes.append(f"表映射不到任何图文件（目录名对不上？）：{len(r['unmapped_tables'])}")
        for e in r['unmapped_tables']:
            notes.append(f"    {e['table']} → {e['script']}（图里没有）")
    if notes:
        print('\n── 提示（不影响退出码）──')
        for n in notes:
            print(f'  {n}')

    if r['converged']:
        print('\n✓ 100% 覆盖，且无多余、无重复、无错位')
    else:
        print(f"\n✗ 有缺口（缺失 {len(r['missing'])} · 多余 {len(r['extra'])}"
              f" · 重复 {len(r['duplicate'])} · 错位 {len(r['misplaced'])}）")


# ----------------------------------------------------------------入口
def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='覆盖率裁决：函数依赖图的成员是否都能在自己的模块流程表里找到'
                    '（画全了没有：缺失/多余/重复/错位）')
    # 树根必填，但 `--root` 要当**隐藏别名**收着（`--help` 里不露脸）——互斥组正好能表达
    # "二者至少给一个"，且 usage 里只显示 `--tables-root`。
    rootg = ap.add_mutually_exclusive_group(required=True)
    rootg.add_argument('--tables-root', dest='tables_root', metavar='TABLES_ROOT',
                       help='流程表目录树根（如 output/self-boot）')
    # 隐藏别名：`--root` 与 equiv/api_audit 的「代码工作树根」同名不同义，容易踩坑，
    # 所以只作兼容保留。
    rootg.add_argument('--root', dest='tables_root', help=argparse.SUPPRESS)
    ap.add_argument('--graph', default=str(TOOLS / 'fn-graph.json'),
                    help='函数依赖图 JSON（默认 dev/tools/fn-graph.json）')
    ap.add_argument('--script-dir', default='scripts',
                    help='模块名 → 脚本路径的目录（默认 scripts）')
    ap.add_argument('--allow', help='豁免白名单文件，每行 模块.py::函数名')
    ap.add_argument('--json', action='store_true', help='输出 JSON（供循环裁决消费）')
    a = ap.parse_args(argv)

    try:
        graph = _load_graph(a.graph)
        root = Path(a.tables_root)
        if not root.is_dir():
            raise CoverageError(f'目录不存在: {root}')
        tables = _collect_tables(root, a.script_dir)
        allowed, unmatched_allow = _load_allow(a.allow, graph)
    except CoverageError as e:
        print(f'✗ {e}')
        return 2

    if graph['parse_errors']:
        print(f'✗ 函数依赖图**不完整**：{len(graph["parse_errors"])} 个文件解析失败，'
              '它们的函数一个都没进分母——覆盖率在此刻是虚的')
        for e in graph['parse_errors'][:8]:
            print(f'    · {e.get("file")}：{e.get("error")}')
        print('  修好语法后重跑 dev/tools/fn_graph.py，再跑本工具')
        return 2

    report = _build_report(graph, tables, allowed, unmatched_allow, a.graph, a.tables_root)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        _print_human(report)
    return 0 if report['converged'] else 1


if __name__ == '__main__':
    sys.exit(main())
