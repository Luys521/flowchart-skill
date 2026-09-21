# -*- coding: utf-8 -*-
"""flowtable_layout.py — 流程表节点 → 布局（row/col 与边的 kind）。

只算几何、不看对错：流程布局（`auto_layout` / `merge_parallel_branches` / `reuse_hint`）
与泳道布局（`apply_swimlane` / `assign_slots`）都在这里。校验归 flowtable_check，解析归 flowtable。

本模块不依赖 flowtable / semantics / geometry：它只吃节点与边这些已经是纯数据的入参。
"""
import collections
import re


def parse_lane_order(s):
    """「- 泳道列序：A → B → C」→ ['A', 'B', 'C']（兼容 `,` `，` `、` 分隔）。

    空泳道（如白板上全空的「财务部」）也是合法项——列序一旦显式声明就照单全收，
    不受"谁先出现在表里"摆布（列序与槽位的关系见 swimlane-spec §2.1 / §3.1）。
    """
    return [p.strip() for p in re.split(r'[→>,，、]', s or '') if p.strip()]


def apply_swimlane(nodes, lane_order=None):
    """泳道布局：行 = 项目运作阶段、列 = 执行主体。

    列号优先取显式 `lane_order`（元信息「泳道列序」），未声明的泳道按首次出现追加在其后；
    没给 lane_order 时退回「各按首次出现」。
    """
    rows, cols = {}, {}
    for s in (lane_order or []):
        cols.setdefault(s, len(cols))
    for n in nodes:
        st = n.get('stage') or '未分组'
        sb = n.get('subject') or '未分组'
        rows.setdefault(st, len(rows))
        cols.setdefault(sb, len(cols))
        n['row'] = rows[st]
        n['col'] = cols[sb]


def _topo_order(ids, edges):
    """Kahn 拓扑序；有环（回路）返回 None，调用方退回表序（见 swimlane-spec §3.1）。"""
    indeg = {i: 0 for i in ids}
    outs = {i: [] for i in ids}
    for e in edges:
        if e['from'] == e['to']:
            continue
        outs[e['from']].append(e['to'])
        indeg[e['to']] += 1
    # **用 deque 而不是 list.pop(0)**（G71）：后者是 O(n) 的搬移，整趟退化成 O(n²)——
    # 本仓的图表（几百节点）感觉不到，但它是白拿的，与"单列函数流"那条纪律同一取向。
    q = collections.deque(i for i in ids if indeg[i] == 0)
    order = []
    while q:
        cur = q.popleft()
        order.append(cur)
        for v in outs[cur]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    return order if len(order) == len(ids) else None


def _resolve_slot_order(ids, edges, notes):
    """定槽位推导用的节点顺序：Kahn 拓扑序；有环退回表序，并把提示写进 notes。"""
    order = _topo_order(ids, edges)
    if order is None:
        notes.append('流程图含回路，槽位退回按表序推导')
        return ids                        # 有环：退回表序，槽号仅供布局参考
    return order


def _incoming_sources(ids, edges):
    """每个节点的入边来源表（自环边略过）→ {id: [起点, …]}。"""
    ins = {i: [] for i in ids}
    for e in edges:
        if e['from'] != e['to']:
            ins[e['to']].append(e['from'])
    return ins


def _solve_slots(order, ins, col, stg):
    """DP 求每个节点的槽号 → {id: 槽号}（多入边取最深的一条）。"""
    slot, occ = {}, {}
    for nid in order:
        best = 0
        for u in ins[nid]:
            if u not in slot:             # 回边的源尚未定槽（环）→ 略过，不让它把槽号搅乱
                continue
            lo, hi = sorted((col[u], col[nid]))
            blocked = any(lo < c < hi for c in occ.get(slot[u], ()))
            same = (stg[u] == stg[nid]) and (col[nid] > col[u]) and not blocked
            best = max(best, slot[u] + (0 if same else 1))
        slot[nid] = best
        occ.setdefault(best, set()).add(col[nid])
    return slot


def _compact_slots(slot):
    """分支可能跳过某个槽号 → 压缩掉空槽，层数才是真实层数。"""
    used = sorted(set(slot.values()))
    remap = {v: i for i, v in enumerate(used)}
    return {k: remap[v] for k, v in slot.items()}


def assign_slots(nodes, edges):
    """槽位求解：把 row 从「阶段号」细化为「槽位号」，返回 (slots, notes)。

    规则（与用户手改版逐条验证一致，见 swimlane-spec §3.1）：

        主链上相邻两节点 u→v，若 stage 相同 **且** col(v) > col(u)（泳道向右移）→ v 与 u 同槽；
        否则 v 开新槽。

    **加一条**：向右交棒还得"中间没人" —— 同槽里若已站着夹在两列之间的节点，合并就会让这条边
    横跨那个节点（实测 17→18 跨过 16a，图上只能贴着框绕、还与别的线交叉）。此时另开一槽。

    DP 取 max 而非顺序递推，天然处理分支/汇聚（多入边取最深的那条）。
    用 Kahn 拓扑序而不是表序：回路边的源可能排在后面，表序会把槽号算浅。
    """
    ids = [n['id'] for n in nodes]
    col = {n['id']: n['col'] for n in nodes}
    stg = {n['id']: (n.get('stage') or '未分组') for n in nodes}
    notes = []
    order = _resolve_slot_order(ids, edges, notes)
    ins = _incoming_sources(ids, edges)
    slot = _solve_slots(order, ins, col, stg)
    return _compact_slots(slot), notes


def _forward_successors(row, edges):
    """只留「行号递增」的前向边 → {起点: {后继, …}}。"""
    succ = {}
    for e in edges:
        if e['from'] in row and e['to'] in row and row[e['to']] > row[e['from']]:
            succ.setdefault(e['from'], set()).add(e['to'])
    return succ


def _merge_branch_group(grp, row, col, moved):
    """把一组汇聚到同一点的分支并到同一行的相邻列（首分支留在原位，其余向右排）。"""
    grp = sorted(grp, key=lambda x: row[x])
    base_r = row[grp[0]]
    # `default` 取**本行现有列号的最大值**（G72）：原先是 `col[grp[0]]`，当 base 行上没有别的
    # 节点时它未必是最右列，新列可能压在左侧已有节点上（随后 `balance_arms` 重编号兜住了，
    # 但"先造一个重叠再靠后面修"不该是设计）。`col.values()` 为空时退回 0（+1 得 1）。
    nxt = max((c for i, c in col.items() if row[i] == base_r),
              default=max(col.values(), default=0)) + 1
    for k in grp[1:]:
        row[k], col[k] = base_r, nxt
        nxt += 1
        moved.add(k)


def _merge_parallel_rows(row, col, succ):
    """按「后继集合完全相同且非空」分组，逐组把并行分支并排到同一行。"""
    moved = set()
    for u, kids in succ.items():
        if len(kids) < 2:
            continue
        groups = {}
        for k in kids:
            groups.setdefault(frozenset(succ.get(k, ())), set()).add(k)
        for tail, grp in sorted(groups.items(), key=lambda kv: min(row[i] for i in kv[1])):
            if len(grp) < 2 or not tail or (grp & moved):
                continue
            _merge_branch_group(grp, row, col, moved)


def balance_arms(row, col):
    """并行分支按**墨迹重量**分挂主轴两侧，把主轴摆到中轴上（D-92「臂」）。

    为什么需要它：列号原本是「主轴恒为 col 0、分支只往右排」（`auto_layout` 的基线），
    于是**主轴永远是最左那一列**——侧支表的主轴偏心实测 0.37~0.43，图整体偏右、读起来是"左重右轻"。
    这一条只改"哪个节点坐哪一列"，**列数与列距一个都不动**（x 的集合不变，主轴上中轴）。

    判据与取舍：
      · **主轴 = 「开始」那个节点所在的列**——流程图里主链总是从它出发，不必另找 `col == 0` 的魔法值；
      · 分支列按重量（该列节点数，同分按原列序）**从重到轻**依次发给"当前更轻"的一侧——经典贪心配平，
        重的先落座，两侧墨迹差最小；
      · 每侧内部**重的靠近主轴**（外侧留给轻的）：重的内容贴着轴，图才紧凑；
      · 只有 0/1 条分支列时**什么都不做**——没有两侧可分，单列产物因此逐字节不变。
    """
    cols = sorted(set(col.values()))
    if len(cols) < 3:
        return
    spine = col[min(row, key=lambda i: row[i])]
    weight = {c: sum(1 for v in col.values() if v == c) for c in cols}
    order = sorted((c for c in cols if c != spine), key=lambda c: (-weight[c], c))
    left, right, wl, wr = [], [], 0, 0
    for c in order:
        if wl <= wr:
            left.append(c)
            wl += weight[c]
        else:
            right.append(c)
            wr += weight[c]
    new = {}
    for i, c in enumerate(sorted(left, key=lambda c: (weight[c], c))):    # 左臂：x 升序 → 轻的排最左、重的贴轴
        new[c] = i
    new[spine] = len(left)
    for i, c in enumerate(sorted(right, key=lambda c: (-weight[c], c))):  # 右臂：靠轴的一档给重的
        new[c] = len(left) + 1 + i
    for nid in col:
        col[nid] = new[col[nid]]


def _apply_row_remap(nodes, row, col):
    """把腾空的层压掉（重排行号），并把 row/col 写回节点。"""
    remap = {v: i for i, v in enumerate(sorted(set(row.values())))}
    for n in nodes:
        n['row'] = remap[row[n['id']]]
        n['col'] = col[n['id']]


def merge_parallel_branches(nodes, edges):
    """并行分支并排：同一节点分出的多条前向分支若**汇聚到同一点**，把它们并到一行、占相邻列。

    行/列的基线是"表序 × 单列"——谁该并排没人管，只能人调（`workflow` 的 `03`/`03b` 就是这样
    留在 yaml 里的一列）。判据保守：分支节点的**后继集合完全相同且非空**才合并——那是"判断走 A
    还是 B、两条都汇到同一点"这一形态；后继不同的普通分叉一律不动。合并后把腾空的层压掉，
    否则图会白留一层。
    """
    row = {n['id']: n['row'] for n in nodes}
    col = {n['id']: n['col'] for n in nodes}
    succ = _forward_successors(row, edges)
    _merge_parallel_rows(row, col, succ)
    balance_arms(row, col)                    # 并行分支分挂主轴两侧（D-92）
    _apply_row_remap(nodes, row, col)


def _between_in_col(c, a, b, row, col):
    """同一列里 c 之外是否已有节点夹在行 a 与 b 之间（判断两节点是否"相邻"）。"""
    return any(x != c and col[x] == col[c] and a < row[x] < b for x in row if x not in (c,))


def _edge_kind(s, t, row, col):
    """按行列位置推导一条边的 kind：同行 horiz / 回退 loop / 同列相邻 spine / 其余 jumpR。"""
    sr, tr, sc = row[s], row[t], col[s]
    if tr == sr:
        return 'horiz'
    if tr < sr:
        return 'loop'
    if sc == col[t] and not _between_in_col(s, sr, tr, row, col):
        return 'spine'
    return 'jumpR'


def auto_layout(nodes, edges):
    """基线布局：row=表序，col=0 单主列；由位置推导 kind；通道交 `router` 现场规划（见 dsl-spec §3）。
    相邻同列前向=spine；其余前向（跨列/跨多行长跳）= jumpR(右通道) 避开中间节点；
    回退=loop(左通道)。判据：同列但中间夹着节点时算 jumpR 而非 spine（见 `_edge_kind`）。
    多分支前向分叉会占用同一右通道，几何可再手调/用 --layout 提示。
    **只返回边**：原先还回一个 `[DEFAULT_COL_X]`，但三个调用点都只取 `[0]`（列中心的家在
    `geometry.DEFAULT_COL_X`，本模块不许再抄一份——它连 cfg 都看不到，抄了就必然分叉）。"""
    row = {n['id']: n['row'] for n in nodes}
    col = {n['id']: n['col'] for n in nodes}
    out = []
    for e in edges:
        s, t = e['from'], e['to']
        k = _edge_kind(s, t, row, col)
        d = {'from': s, 'to': t, 'kind': k, 'polarity': ('negative' if e['is_loop'] or k == 'loop' else 'main')}
        if e['label']:
            d['label'] = e['label']
        out.append(d)
    return out


def _index_hints(hint):
    """把布局提示的边按 (from, to) 建索引 → {(from, to): [提示边, …]}。"""
    geo = {}
    for h in hint.get('edges', []):
        geo.setdefault((h.get('from'), h.get('to')), []).append(h)
    return geo


def _pick_hint(cands, e):
    """按「label 相同 > kind 相同 > 任意」挑一条提示边并从池子里消耗掉它；挑不到返回 None。

    同 (from,to) 多条边（并联出口）逐条消耗提示，免得两条边抢同一条；
    label 在流程表改过也不至于把整条边的几何丢掉。
    """
    h = next((c for c in cands if c.get('label') == e.get('label')), None)
    if h is None:
        h = next((c for c in cands if c.get('kind') == e.get('kind')), None)
    if h is None and cands:
        h = cands[0]
    if h:
        cands.remove(h)
    return h


def _apply_hint(d, h):
    """把提示边的手调 kind 与几何键借给 DSL 边（label / polarity 一律来自流程表，不被覆盖）。"""
    if h.get('kind'):
        d['kind'] = h['kind']
        if h['kind'] == 'loop':
            d['polarity'] = 'negative'   # loop 自动为 negative（dsl-spec §3）
    for kk in ('gutter', 'channel', 'gapx', 'dye', 'sdye', 'exit', 'entry'):
        if kk in h:
            d[kk] = h[kk]


def reuse_hint(edges, hint):
    """--layout 提示：借用几何键（gutter / channel / gapx / dye / exit / entry）与手调 kind。

    label / polarity 一律来自流程表，**禁止被提示覆盖**——否则改流程表后标签不生效，事实源失效。
    kind 按 dsl-spec §4 属可手调字段：同一 (from, to) 的边以提示里的 kind 为准
    （未手调时它与几何推导值相同，无副作用；手改过 kind 也不再被静默重置）。
    """
    geo = _index_hints(hint)
    ret = []
    for e in edges:
        d = {kk: e[kk] for kk in ('from', 'to', 'kind') if kk in e}
        if 'polarity' in e:
            d['polarity'] = e['polarity']
        if 'label' in e:
            d['label'] = e['label']
        cands = geo.get((e.get('from'), e.get('to')), [])
        h = _pick_hint(cands, e)
        if h:
            _apply_hint(d, h)
        ret.append(d)
    return ret
