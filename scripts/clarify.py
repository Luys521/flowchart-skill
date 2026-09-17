# -*- coding: utf-8 -*-
"""clarify.py — 澄清阶段：从《流程表》算出「现在该问用户什么」。

**为什么需要**：`⚠` 现在只有一个标记，担了两种语义——"AI 有依据的推断"与"AI 推不出、
必须业务方拍板的决策"。两者混在一起导致 `⚠` **没有收敛条件**：它可以永远留在图上、
跟着流程一路交付出去（见 D-46）。拆开之后，`⚠?` 这类必须问，本脚本负责算出**问的顺序**。

**它不渲染、不进 build 六环**。消费方是 AI 在对话里——它是"开口问之前的准备工作"，
不是渲染管线的一环。所以它只做三件纯事：分拣 / 算 frontier / 打印简报。

用法：
    python clarify.py "output/<名称>/flowtable.md"          # 简报
    python clarify.py "output/<名称>/flowtable.md" --json   # 机器可读（供 AI 组装提问）

退出码：0 = 已收敛（frontier 为空）；1 = 仍有待问项（不阻断渲染，只表示"还没问完"）；
2 = 表不存在或没读过结构校验（硬错误，与"未收敛"分开——前者是这份表还不能问）。
"""

import argparse
import json
import sys
from pathlib import Path

from semantics import pending_kind
from flowtable import parse_table, build_edges, Errors
from flowtable_check import check_nodes


# ----------------------------------------------------------------解析（复用 table_to_dsl，不重写）
def load_nodes(table_path):
    """流程表 → (title, nodes)。表有硬错误时抛 ValueError。

    **刻意不重写解析**：结构校验的报错口径（H2/H7）是既有资产，抄一份出来迟早漂移。
    这里只取"能建出节点"的程度——编号与类型的问题归结构校验管，本脚本不越界判它。
    """
    md = Path(table_path).read_text(encoding='utf-8-sig')
    title, _meta, rows = parse_table(md)
    errs = Errors()
    nodes = check_nodes(rows, errs)
    if not errs.ok:
        raise ValueError('流程表未过结构校验：' + '；'.join(errs.hard[:3]))
    return title, nodes


def pending(nodes):
    """节点列表 → {'inferred': [...], 'verdict': [...]}。

    两类都带 desc 原文，供 AI 组装提问时引用"材料里说了什么"。
    """
    out = {'inferred': [], 'verdict': []}
    for n in nodes:
        k = pending_kind(n.get('desc'))
        if k:
            out[k].append(n)
    return out


# ----------------------------------------------------------------frontier
def _verdict_graph(nodes, edges):
    """待裁决节点之间的依赖图 → (verdict 集合, 前驱表, 环内节点集合)。

    三样一起算，是为了让 frontier 与简报共用**同一份**"谁在环里"的判断：
    两处各判一次迟早漂移，漂移的表现正是"报告里说它等上游、其实它在环里"。
    """
    verdict = {n['id'] for n in nodes if pending_kind(n.get('desc')) == 'verdict'}
    preds = {i: set() for i in verdict}
    for e in edges:
        f, t = e['from'], e['to']
        # 只保留"两边都是待裁决"的依赖：一边已定就构不成阻塞。
        # 回环（is_loop）同样计入——「回 03 修正」意味着 03 的走向会反过来影响本节点，
        # 它是真实依赖，不能因为标了"回"就当没这条边（D-04 说的是分隔符，不是依赖语义）。
        if f in verdict and t in verdict and f != t:
            preds[t].add(f)

    # 环内 = 顺着依赖走出去还能走回自己。环的下游不算：它确实在等别人定，不是互相等。
    succ = {i: set() for i in verdict}
    for t, ps in preds.items():
        for p in ps:
            succ[p].add(t)
    cycle = set()
    for i in verdict:
        stack, seen = list(succ[i]), set()
        while stack:
            x = stack.pop()
            if x == i:
                cycle.add(i)
                break
            if x in seen:
                continue
            seen.add(x)
            stack.extend(succ[x])
    return verdict, preds, cycle


def frontier(nodes, edges):
    """当前可问的 `⚠?` 节点 id 列表（有序，按表序）。

    规则（见 DESIGN-澄清阶段 §2.1）：
        frontier = { 标记 ⚠? 的节点 n | n 的全部前驱中没有任何一个也标记 ⚠? }
    理由：前驱若是未决项，n 这个问题**本身可能不成立**——上游改了走向，n 可能压根不存在，
    或该问的东西完全不同。跨依赖层问了也是白问。

    边界——环：自环、或两个 ⚠? 互为前驱时，朴素规则会把整块判成"谁都不可问"，
    于是**静默卡死**。这里退化为"环内按表序取第一个"，并在 blocked 里说明原因，
    由调用方告知用户"先定这一个，其余才问得下去"。
    """
    verdict, preds, cycle = _verdict_graph(nodes, edges)
    if not verdict:
        return [], []

    ready = [n['id'] for n in nodes if n['id'] in verdict and not preds[n['id']]]

    def ring_why(i, tail):
        """环内节点的阻塞说明：点名它的环内前驱，说明是互相等、不是等上游。"""
        others = sorted(preds[i] & cycle)
        return f'与 {"、".join(others)} 互为未决（环内互相等待）{tail}'

    blocked = []
    if not ready:
        # 环兜底：剩下的 verdict 节点全在环里（或环的下游）。取表序第一个破环。
        left = [n['id'] for n in nodes if n['id'] in verdict]
        if left:
            pick = left[0]
            ready = [pick]
            blocked = [{'id': i,
                        'why': (ring_why(i, f'，先定 {pick} 才能问它')
                                if i in cycle else
                                f'前驱未决（环的下游），先定 {pick} 才能问它')}
                       for i in left[1:]]
    else:
        # ready 非空时环兜底不触发，可环内节点照样进 waiting——此时还说"等上游"是误导：
        # 它们的上游不会先定，用户会一直等。这里补一条说明，把环内项从"等上游"里摘出来。
        blocked = [{'id': n['id'], 'why': ring_why(n['id'], '：先定其中一个才能问它')}
                   for n in nodes if n['id'] in cycle]
    return ready, blocked


def hidden(nodes, edges):
    """因上游未决而**暂时问不了**的 `⚠?` 节点 id（有序）。

    和 frontier 互补：这些不是"不用问"，是"现在还问不了"。分开是为了让简报能说
    「另有 N 处要等上游定了才问」——不说清楚，用户会以为被漏掉了。
    """
    ready, _blocked = frontier(nodes, edges)
    ready_set = set(ready)
    return [n['id'] for n in nodes
            if pending_kind(n.get('desc')) == 'verdict' and n['id'] not in ready_set]


# ----------------------------------------------------------------简报
def brief(nodes, edges):
    """汇总：分类计数 + frontier + 暂时问不了的。纯数据，打印与 --json 共用。"""
    p = pending(nodes)
    ready, blocked = frontier(nodes, edges)
    by_id = {n['id']: n for n in nodes}
    _v, _pr, cycle = _verdict_graph(nodes, edges)
    waiting = []
    for i in hidden(nodes, edges):
        w = {'id': i, 'name': by_id[i]['name']}
        # 只给环内项加标记：没环的表，--json 输出与加标记之前逐字节一致。
        if i in cycle:
            w['cycle'] = True
        waiting.append(w)
    return {
        'converged': not p['verdict'],
        'counts': {'inferred': len(p['inferred']), 'verdict': len(p['verdict']),
                   'ready': len(ready), 'waiting': len(hidden(nodes, edges))},
        'inferred': [{'id': n['id'], 'name': n['name'],
                      'desc': (n.get('desc') or '').strip()} for n in p['inferred']],
        'frontier': [{'id': i, 'name': by_id[i]['name'], 'route': by_id[i]['route'],
                      'desc': (by_id[i].get('desc') or '').strip()} for i in ready],
        'waiting': waiting,
        'blocked': blocked,
    }


def _add_inferred(lines, b):
    """追加「AI 推断」分节（有依据、无需提问的一类）。"""
    c = b['counts']
    lines.append(f'· AI 推断（有依据，无需提问）：{c["inferred"]} 处')
    for n in b['inferred']:
        lines.append(f'    {n["id"]} {n["name"]}：{n["desc"][:60]}')


def _add_verdict_head(lines, b):
    """追加「待你裁决」总账行（环内项单算，不并入"等上游"）。"""
    c = b['counts']
    ring_n = sum(1 for w in b['waiting'] if w.get('cycle'))
    hold = []
    if c['waiting'] - ring_n:
        hold.append(f'{c["waiting"] - ring_n} 处要等上游定了才问')
    if ring_n:
        hold.append(f'{ring_n} 处在环内互相等待')
    lines.append(f'· 待你裁决：{c["verdict"]} 处（其中现在可问 {c["ready"]} 处'
                 + (f'，另有 {"、".join(hold)}' if hold else '') + '）')
    lines.append('')


def _add_frontier(lines, b):
    """追加当前 frontier 及每项的走向、材料现状。"""
    c = b['counts']
    if b['frontier']:
        lines.append(f'当前 frontier（{c["ready"]} 处，一次问完）：')
        for i, n in enumerate(b['frontier'], 1):
            lines.append(f'    Q{i} · {n["id"]} {n["name"]}')
            lines.append(f'         走向 {n["route"]}')
            lines.append(f'         材料现状：{n["desc"][:80]}')


def _add_waiting(lines, b):
    """追加「暂时问不了」两栏：等上游 / 环内互为前驱互相等待。"""
    if not b['waiting']:
        return
    joined = lambda ws: '、'.join(f'{w["id"]} {w["name"]}' for w in ws)
    upstream = [w for w in b['waiting'] if not w.get('cycle')]
    ring = [w for w in b['waiting'] if w.get('cycle')]
    # 两栏分开：环内项说成"等上游"会让人一直等一个永远不会先定的前驱。
    if upstream:
        lines.append('')
        lines.append('暂时问不了（等上游定了才进 frontier）：')
        lines.append('    ' + joined(upstream))
    if ring:
        lines.append('')
        lines.append('暂时问不了（不是等上游：环内互为前驱、互相等待）：')
        lines.append('    ' + joined(ring))


def render(b):
    """简报 → 人可读文本。**只报状态，不下结论**——"已收敛"不等于"已把关"（见 D-02）。"""
    c = b['counts']
    lines = []
    if not c['inferred'] and not c['verdict']:
        return '✓ 无待决项：全部语义已有材料依据，未产生澄清问题。'

    if c['inferred']:
        _add_inferred(lines, b)

    if not c['verdict']:
        lines.append('✓ 无待裁决项：澄清已收敛（frontier 为空）。')
        return '\n'.join(lines)

    _add_verdict_head(lines, b)
    _add_frontier(lines, b)
    _add_waiting(lines, b)
    for bl in b['blocked']:
        lines.append(f'    ⚠ {bl["id"]}：{bl["why"]}')
    return '\n'.join(lines)


# ----------------------------------------------------------------CLI
def _emit_report(b, title, as_json):
    """按 --json 或人可读两种口径打印简报。"""
    if as_json:
        print(json.dumps(b, ensure_ascii=False, indent=1))
    else:
        # title 由 parse_table 返回时**已带书名号**，此处不再包一层，否则会打印成《《…》》。
        print(title)
        print(render(b))


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='澄清阶段：算出当前该问用户什么（frontier）')
    ap.add_argument('table', help='流程表路径，如 output/<名称>/flowtable.md')
    ap.add_argument('--json', action='store_true', help='输出 JSON（供 AI 组装提问）')
    a = ap.parse_args(argv)

    src = Path(a.table)
    if not src.exists():
        print(f'✗ 找不到流程表: {src}')
        return 2
    try:
        title, nodes = load_nodes(src)
    except ValueError as e:
        print(f'✗ {e}')
        return 2

    errs = Errors()
    edges, _dangling = build_edges(nodes, errs)

    b = brief(nodes, edges)
    _emit_report(b, title, a.json)
    return 0 if b['converged'] else 1


if __name__ == '__main__':
    sys.exit(main())
