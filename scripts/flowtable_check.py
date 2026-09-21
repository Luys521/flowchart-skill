# -*- coding: utf-8 -*-
"""flowtable_check.py — 结构校验：H1–H8 三层（① 节点 → ② 类型 → ③ 关系）+ H9 表头 + 标签长度。

`run_checks` 是**唯一入口**：main（`table_to_dsl --check/--write`）与 writeback 都走这里，
顺序只写一份——否则加一层时漏改一处就出现"build 拦得住、回写拦不住"。

取边/父表链取自 `flowtable`，泳道的行列与槽位取自 `flowtable_layout`（`run_checks` 在泳道模式下
要先摆位才能查关系），错误收集器 `Errors` 也来自 `flowtable`。
"""
import re
from pathlib import Path

from flowtable import (Errors, build_edges, wrote_route, find_parent_table,
                       _has_backref, COLOR_KEY, COLUMNS,
                       header_cells, split_row_cells)
from flowtable_layout import apply_swimlane, assign_slots
from semantics import TYPE_ZH_EN, pending_kind


# ② 类型层的规则表：每种节点类型"自己必须满足什么"。加一条类型约束改这里，别在 check_by_type 里堆 if。
#   min_count  全图至少几个（H1）        out  出边要求：'need' 必须有 / 'forbid' 不许有 / None 不管
#   min_branch 带标签分支下限（H4，仅判断有意义）
#
# **只有四种类型**（《类型登记表》见 flowtable-spec §2）。这里多一条都不加：
#   · 「旁支终点」不设 —— 一张图可以有多个「结束」（每个结局一个），不必再分主次；
#   · 「并行」不设 —— 它是**出口标签的有无**（无标签=全都走，带标签=选一条），不是节点；
#   · 子流程 / 输入输出 / 文档 / 数据库 / 延时… 不设 —— 它们由 `⊞`、列、或拓扑承载。
# 表里**故意没有"入边要求"**，别顺手补上——理由与被否决的方案见 DECISIONS.md D-07。
# dev/verify/gates.py「同一个节点只被点一次名」那条断言守着它。
TYPE_RULES = {
    'start':    {'cn': '开始', 'min_count': 1, 'out': 'need',   'min_branch': 0},
    'end':      {'cn': '结束', 'min_count': 1, 'out': 'forbid', 'min_branch': 0},
    'task':     {'cn': '任务', 'min_count': 0, 'out': 'need',   'min_branch': 0},
    'decision': {'cn': '判断', 'min_count': 0, 'out': 'need',   'min_branch': 2},
}


# ----------------------------------------------------------------① 节点层：一行自己写得对不对
def _split_row_cells(cells):
    """补齐到 N_COLS 并按 ICOM 序切成
    (阶段, 编号, 名称, 类型, 输入, 依据, 输出, 主体, 执行者, 时间, 下个节点, 描述)。"""
    return tuple(split_row_cells(cells))


def _check_node_id(id_, seen, errs):
    """H2：编号重复与编号格式校验，合法与否都记入 seen（跨行查重）。

    编号格式：**主干用纯数字**（`01` / `01a`），数字开头却不止一位后缀（如 `10aa`）会被 ID_RE
    静默截成 10a、连错节点，必须拦下。**字母开头的编号**（`n1` / `node-3`）是外部 drawio 导入的
    原样 id，一律放行——它们走精确匹配。**这两者之外的形状（中文 / 符号开头）直接拦**
    （G36）：原先只判"数字开头"，于是 `材料` 这种编号一路放行，直到取边阶段才以
    "无法解析「下个节点」段"报错——错误位置指向**别的列**，读者找不着北。
    """
    if id_ in seen:
        errs.err(f'H2 编号重复: 节点 "{id_}" 出现在多行', subject=id_,
                 fix='重命名其中一个，或合并两行')
    if id_[0].isdigit() and not re.fullmatch(r'\d+[a-zA-Z]?', id_):
        errs.err(f'H2 编号非法: "{id_}"（数字开头时只允许 数字 + 至多一个字母后缀，如 01 / 01a；'
                 f'10 与 11 之间的第 2 个插入项应叫 10b，不是 10aa）',
                 subject=id_, fix='改成 数字+至多一个字母后缀（如 10b）')
    elif not id_[0].isdigit() and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.\-]*', id_):
        errs.err(f'H2 编号非法: "{id_}"（编号主干用**纯数字**，如 01 / 01a；'
                 f'字母开头的 id 只保留给外部 drawio 导入的原样编号）',
                 subject=id_, fix='改成数字编号（如 01）；导入件请走 references/import-existing.md')
    seen[id_] = True


def _check_node_semantics(id_, name, subj, typ, who, when, errs):
    """H7：名称/执行主体/节点类型/执行者/行动所需时间；类型非法兜底成「任务」并返回该类型。

    「行动所需时间」的**格式软提示**见 `_check_time_format`（G35：字段登记表写了这条校验，
    代码一直没有——两处脱节）。
    """
    if not name:
        errs.err(f'H7 节点 {id_}: 缺节点名称', subject=id_, fix='补「节点名称」')
    if not subj:
        errs.err(f'H7 节点 {id_}: 缺执行主体', subject=id_, fix='补「执行主体」')
    t = TYPE_ZH_EN.get(typ.strip())
    if t is None:
        errs.err(f'H7 节点 {id_}: 未知节点类型 "{typ.strip()}"'
                 f'（应为 {" / ".join(TYPE_ZH_EN)}）',
                 subject=id_, fix='类型改为 ' + ' / '.join(TYPE_ZH_EN) + ' 之一')
        t = 'task'          # 兜底，让 ②③ 仍能把它当普通节点查下去，一次报全
    if not who:
        errs.warn(f'H7(软) 节点 {id_}: 缺执行者', subject=id_, fix='补「执行者」')
    if not when.strip():
        errs.warn(f'H7(软) 节点 {id_}: 缺行动所需时间', subject=id_, fix='补「行动所需时间」')
    else:
        _check_time_format(id_, when, errs)
    return t


# 占位符等价类（**本模块自己一份**，与 `writeback._PLACEHOLDERS` 同口径、刻意不收敛：
# 见 `coding-spec` N8——那几处回答的不是同一个问题，合并会造出假的单一真源）。
_TIME_EMPTY = ('', '-', '—', '无')
# 时间写法：`数字[+单位]`，可带一个区间（`1-2 天` / `5-30 秒` / `3个工作日` / `2 小时`）。
# **刻意宽松**：单位是自由文本（秒/天/工作日/小时都合法），管的是"填的是不是一个量"，
# 不是"单位写没写规范"——软提示，不阻断。
_TIME_RE = re.compile(r'^\d+(?:\.\d+)?\s*(?:[-–~]\s*\d+(?:\.\d+)?)?\s*\S{1,8}$')


def _check_time_format(id_, when, errs):
    """H7(软)：「行动所需时间」有值却不像一个量（如 `尽快` / `3` / `两天`）→ 软提示。

    为什么值得有（G35）：字段登记表 §2 的「校验」列写着"格式 `min-max 单位` 或 `—`"，
    而代码只查了非空——**规范宣称的判据没实现**，等于那句话没人执行。做成**软提示**：
    它是可读性诉求（悬浮框第三行要能一眼看懂），不是结构约束，不该阻断渲染。
    """
    v = when.strip()
    if v in _TIME_EMPTY or _TIME_RE.match(v):
        return
    errs.warn(f'H7(软) 节点 {id_}: 「行动所需时间」"{v}" 不像一个量'
              f'（形如 `1-2 天` / `3 小时` / `5个工作日`，或填 —）',
              subject=id_, fix='写成 数字+单位（可带区间），或填 —')


def _check_basis(id_, typ, basis, desc, errs):
    """「依据」与 `⚠` 的咬合（字段登记表见 flowtable-spec §2）：判断节点要么写清判据，要么标 `⚠`。

    **只对判断节点报**——"凭什么这样分"是全表最该被追问的一处；普通任务不报，
    否则每行都挨一条软提示，提示本身就成了噪音。
    """
    if typ != 'decision' or str(basis).strip() != '' or pending_kind(desc):
        return
    errs.warn(f'H7(软) 判断节点 {id_}: 缺「依据」——写清凭什么这样分，或按 ⚠ 留痕',
              subject=id_, fix='在「依据」列写判据的出处，或在「节点描述」以 ⚠ 开头说明这是推断')


def check_nodes(rows, errs):
    """① 节点层：逐行检查编号与语义列，返回可进流程的节点列表。

    编号为空的行跳过；类型非法的行兜底成「任务」继续走，好让 ②③ 一次报全（顺序的理由见 flowtable-spec §3）。
    """
    nodes, seen = [], {}
    for i, cells in enumerate(rows, 1):
        (stage, id_, name, typ, inp, basis, out,
         subj, who, when, nxt, desc) = _split_row_cells(cells)
        id_ = id_.strip()
        if not id_:
            errs.err(f'H2 行{i}: 缺节点编号（这一行建不出节点，请补上编号或删掉整行）',
                     subject=f'row{i}', fix='补上编号，或删除整行')
            continue
        _check_node_id(id_, seen, errs)
        t = _check_node_semantics(id_, name, subj, typ, who, when, errs)
        _check_basis(id_, t, basis, desc, errs)
        nodes.append({'row': i - 1, 'col': 0, 'stage': stage, 'id': id_, 'name': name,
                      'type': t, 'subject': subj, 'executor': who, 'time': when,
                      'input': inp, 'basis': basis, 'output': out,
                      'route': nxt, 'desc': desc})
    return nodes


# ----------------------------------------------------------------② 类型层：每种类型各自的约束
def _build_adjacency(ids, edges):
    """按 id 建出/入边邻接表 → (out_e, in_e)，②③ 两层共用。"""
    out_e = {i: [] for i in ids}
    in_e = {i: [] for i in ids}
    for e in edges:
        out_e[e['from']].append(e)
        in_e[e['to']].append(e)
    return out_e, in_e


def _check_min_count(nodes, errs):
    """H1：每种类型的节点总数不得低于 TYPE_RULES 声明的 min_count。"""
    for t, rule in TYPE_RULES.items():
        n = sum(1 for x in nodes if x['type'] == t)
        if n < rule['min_count']:
            errs.err(f'H1 缺少「{rule["cn"]}」节点'
                     f'（节点类型列里须有至少 {rule["min_count"]} 个「{rule["cn"]}」）',
                     fix=f'在类型列补一行「{rule["cn"]}」')


def _check_out_rule(nd, out_e, in_e, errs):
    """H5/H8：单个节点的出边要求——forbid 却有出边报 H5，need 却无出边且被指过报死胡同。"""
    i, t = nd['id'], nd['type']
    rule = TYPE_RULES[t]
    if rule['out'] == 'forbid' and out_e[i]:
        tgts = '、'.join(sorted({e['to'] for e in out_e[i]}))
        errs.err(f'H5 {rule["cn"]}节点 {i}: 不应有出边（「下个节点」应为 —，现在指向 {tgts}）',
                 subject=i, fix='「下个节点」改为 —（结束不外连）')
    elif rule['out'] == 'need' and not out_e[i]:
        # 写了内容却解析不出边 → 归 H3；再说"死胡同"会与提示自相矛盾（让位规则见 flowtable-spec §3）。
        if in_e[i] and not wrote_route(nd):
            errs.err(f'H8 死胡同节点 {i}: 没有出边，也不是「结束」——走进去就出不来'
                     f'（「下个节点」填 — 只在「结束」上合法）',
                     subject=i, fix='补「下个节点」；确需收尾就把类型改为「结束」')


def _check_decision_branches(nd, out_e, errs):
    """H4/H8：判断节点自身——分支下限、缺标签、分支指向同一目标、分支标签重复。"""
    if nd['type'] != 'decision':
        return
    i = nd['id']
    rule = TYPE_RULES['decision']
    k, no_label = len(out_e[i]), sum(1 for e in out_e[i] if not e['label'])
    if k < rule['min_branch']:
        # 文案只说**数量**（G37）：判据数的是全部出边，原先写成"需 ≥N 个**带标签**分支"，
        # 于是"1 条分支且它带标签"时读者看到"仅 1 个分支，需 ≥2 个带标签分支"——自相矛盾。
        # 缺标签是另一条判据（下面的 elif），两件事不在一条里说。
        errs.err(f'H4 判断节点 {i}: 仅 {k} 个分支，需 ≥{rule["min_branch"]} 个'
                 f'（补全每个可能结果）',
                 subject=i, fix='补全每个可能结果的分支')
    elif no_label:
        errs.err(f'H4 判断节点 {i}: {no_label} 个分支缺标签'
                 f'（判断的每条出边都要写走它的条件，如 是/否/通过/不通过，'
                 f'否则图上两条线长得一样、无法分辨）',
                 subject=i, fix='给每条出边写条件（是/否/通过/不通过）')
    tgts = [e['to'] for e in out_e[i]]
    if len(set(tgts)) < len(tgts):
        errs.err(f'H8 判断节点 {i}: {len(tgts)} 条分支指向同一目标 {sorted(set(tgts))}'
                 f'——分了又合，判断没有意义（要么并成一条边，要么补上真正的另一条路）',
                 subject=i, fix='并成一条边，或补上真正的另一条路')
    labs = [e['label'] for e in out_e[i]]
    if len(set(labs)) < len(labs):
        errs.err(f'H8 判断节点 {i}: 分支标签重复 {labs}'
                 f'——图上两条线长得一样，读者无法分辨该走哪条',
                 subject=i, fix='语义相同就合并分支，否则改用可区分的标签')


def check_by_type(nodes, edges, errs):
    """② 类型层：执行文件顶部的 TYPE_RULES——只看这个节点自身与它的出边。

    逐节点依次跑"出边规则"与"判断分支"，报错顺序与旧实现逐条一致。
    """
    ids = [n['id'] for n in nodes]
    out_e, in_e = _build_adjacency(ids, edges)
    _check_min_count(nodes, errs)
    for nd in nodes:
        _check_out_rule(nd, out_e, in_e, errs)
        _check_decision_branches(nd, out_e, errs)


# ----------------------------------------------------------------③ 关系层：要看着别的节点才能判
def _check_dangling(dangling, errs):
    """H3：引用完整——「下个节点」指向的目标必须真实存在。"""
    for fid, tid in dangling:
        errs.err(f'H3 节点 {fid}: 引用了不存在的目标 "{tid}"',
                 subject=fid, fix=f'核对 "{tid}" 是否笔误；若确有此节点，把它补进表里')


def _reachable_from_starts(ids, typ, out_e):
    """从所有「开始」节点做一次可达性扩散 → 可达 id 集合。"""
    seen = {i for i in ids if typ[i] == 'start'}
    stack = list(seen)
    while stack:
        cur = stack.pop()
        for e in out_e[cur]:
            if e['to'] not in seen:
                seen.add(e['to'])
                stack.append(e['to'])
    return seen


def _check_node_reach(i, typ, out_e, in_e, seen, by_id, errs):
    """H8：单个节点的连通判定——一个节点只报最可操作的一条（让位规则见 flowtable-spec §3）。

    结束节点先报「不可达」，死胡同跳过；「开始」有入边只给软提示。
    """
    if typ[i] == 'end':
        if not in_e[i] or i not in seen:
            errs.err(f'H8 结束节点 {i} 不可达: 没有任何可达路径指向它——流程无法终止在这里',
                     subject=i, fix='查上游分支是否漏了指向「结束」的一路')
        return
    if not in_e[i] and not out_e[i]:
        if wrote_route(by_id[i]):
            return          # 写了个不存在的目标 → 上方的 H3 已经说清楚了
        errs.err(f'H8 孤立节点 {i}: 既无入边也无出边（完全脱离流程'
                 f'——多半是漏填「下个节点」，或这行本该删掉）',
                 subject=i, fix='补「下个节点」，或删除该行')
    elif not in_e[i]:
        if typ[i] == 'start':
            return          # 「开始」本就该没有入边
        errs.err(f'H8 孤儿节点 {i}: 没有任何节点指向它，也不是「开始」——流程永远走不到'
                 f'（查查是不是有谁漏写了 →{i}）',
                 subject=i, fix=f'找到上游节点，补上 →{i}')
    elif not out_e[i] and not wrote_route(by_id[i]):
        return              # 死胡同：② 类型层已报
    elif i not in seen:
        errs.err(f'H8 不可达节点 {i}: 从「开始」出发走不到它'
                 f'（多半是上游某条分支漏了这一路）',
                 subject=i, fix='查上游分支，补上通向它的一路')
    if typ[i] == 'start' and in_e[i]:
        src = '、'.join(sorted({e['from'] for e in in_e[i]}))
        errs.warn(f'H8(软) 开始节点 {i} 有入边（来自 {src}）'
                  f'：回路回到起点属正常，可忽略；否则多半是编号写反了', subject=i)


def check_relations(nodes, edges, dangling, errs):
    """③ 关系层：引用完整（H3）、逻辑连通（H8）、回路有出口（H6）。

    判"节点之间"的事——没人指、走不到、目标不存在。判据见 references/flowtable-spec.md 第 3 节。
    """
    _check_dangling(dangling, errs)
    ids = [n['id'] for n in nodes]
    typ = {n['id']: n['type'] for n in nodes}
    out_e, in_e = _build_adjacency(ids, edges)
    seen = _reachable_from_starts(ids, typ, out_e)
    by_id = {n['id']: n for n in nodes}
    for i in ids:
        _check_node_reach(i, typ, out_e, in_e, seen, by_id, errs)
    check_deadloop(nodes, edges, errs)


# 三色 DFS 的颜色标记：白=未访问、灰=在递归栈上（再遇即回路）、黑=已回溯完成
_DFS_WHITE, _DFS_GRAY, _DFS_BLACK = 0, 1, 2


def _pruned_adjacency(by_id, edges):
    """删掉所有判断节点（及其邻接边）后的子图邻接表——只剩纯任务/起止之间的边。"""
    adj = {}
    for e in edges:
        if by_id[e['from']]['type'] != 'decision' and by_id[e['to']]['type'] != 'decision':
            adj.setdefault(e['from'], []).append(e['to'])
    return adj


def _walk_cycle(u, path, adj, color, reported, errs):
    """三色 DFS 的一步：沿 adj 下探，遇灰节点（返祖边）就报一条回路，回溯时标黑。"""
    color[u] = _DFS_GRAY
    path.append(u)
    for v in adj.get(u, []):
        if color[v] == _DFS_GRAY:                  # 返祖边 → 一条回路
            cyc = path[path.index(v):]
            key = frozenset(cyc)
            if key not in reported:
                reported.add(key)
                errs.err(f'H6 死循环无出口（回路内无判断节点）: '
                         f'{"→".join(cyc + [cyc[0]])}',
                         subject=cyc[0], fix='在回路中加入判断节点，或删掉一条回边')
        elif color[v] == _DFS_WHITE:
            _walk_cycle(v, path, adj, color, reported, errs)
    path.pop()
    color[u] = _DFS_BLACK


def check_deadloop(nodes, edges, errs):
    """H6：每个有向回路至少含 1 个判断节点。

    等价判定：删掉所有判断节点（及其邻接边）后，剩余子图**不含任何有向回路**——
    含判断的回路本来就不该报。在剪枝后的子图上做标准三色 DFS 找环。
    （旧实现"逐起点 DFS + 全局 seen_edges 剪枝"会漏报：当回路存在绕过判断的
    并联捷径（04→判断→05 与 04→05 并存）时，回路某段先被别的路径消耗，纯任务回路查不出来。）
    """
    by_id = {n['id']: n for n in nodes}
    adj = _pruned_adjacency(by_id, edges)
    color = {n['id']: _DFS_WHITE for n in nodes}
    reported = set()
    for nid in color:
        if color[nid] == _DFS_WHITE:
            _walk_cycle(nid, [], adj, color, reported, errs)


# ----------------------------------------------------------------软提示
def check_label_length(edges, errs):
    """分支标签过长 → 软提示。标签画在连线上，过长会撑爆徽章底框、挤占版面。"""
    for e in edges:
        lb = (e.get('label') or '').strip()
        if len(lb) > 6:
            errs.soft.append(f'节点 {e["from"]} 的分支标签「{lb}」{len(lb)} 字过长：'
                             f'建议精简到 4 字内（是/否/通过/不通过），详情写进该节点的「节点描述」')


# ----------------------------------------------------------------表头规范（H9，D-56/D-59）
# 三区结构（D-59）：YAML=身份（键封闭）；正文配置区=呈现（渲染配置键封闭 + 主体配色表）；流程表=逻辑。
META_KEYS = ('id', 'level', 'parent', 'refs', 'description')
CONFIG_KEYS = ('输出布局', '泳道列序')
# 这些"键"是 ⊞ 声明的派生量：手写必与 layer_index 的推导漂移，单独给文案指路。
# 「parent」不在派生禁列（D-58）：它是子表的自描述声明，由 H9 与父表的 ⊞ 做双向一致性校验。
DERIVED_META_KEYS = ('层级', '层级号', '子表', '构建顺序')


def _derived_level(ft_path):
    """沿 parent/⊞ 链向上数跳数 → 派生层级（L0=主流程）。环与断链按已走跳数计。"""
    cur = Path(ft_path).resolve()
    seen = {cur}
    hops = 0
    while hops <= 16:
        r = find_parent_table(cur)
        if not r:
            break
        cur = r[0].resolve()
        if cur in seen:
            break
        seen.add(cur)
        hops += 1
    return hops


def _check_meta_keys(meta, errs):
    """身份区键封闭：未知键报 H9，⊞ 派生量键（层级/子表/构建顺序）单独给文案（D-56）。"""
    for k in meta:
        # __color_dup__ / __fm_error__ 是 parse_table 自己注入的内部键，不是用户写的元信息，
        # 不走"未知键"判定（否则重复声明配色会额外挨一条指错方向的 H9）
        if k in META_KEYS or k in CONFIG_KEYS or k == COLOR_KEY or k in ('__fm_error__', '__color_dup__'):
            continue
        if k in DERIVED_META_KEYS or any(d in str(k) for d in ('层级', '子表')):
            errs.err(f'H9 表头「{k}」是派生量，不要写进表头：层级关系由节点描述的 ⊞ 声明推导，'
                     f'索引由 layer_index.py 派生（D-56）',
                     subject=f'表头.{k}', fix='删除该键；子流程用节点描述里的 ⊞ 声明')
        else:
            errs.err(f'H9 未知元信息键「{k}」——静默忽略会整条丢失语义',
                     subject=f'表头.{k}', fix='改为 ' + ' / '.join(META_KEYS) + ' 之一')


def _check_header_entries(ft_path, errs):
    """表头区（frontmatter 之后、主表之前）不放 `- 条目` 式元信息（D-57）。"""
    text = Path(ft_path).read_text(encoding='utf-8-sig')
    lines = text.splitlines()
    fm_end = -1
    if lines and lines[0].strip() == '---':
        fm_end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), -1)
    for l in lines[fm_end + 1:]:
        if l.startswith('|'):
            break
        # 只拦真正的列表条目（`- ` / `* ` 后跟空格）：`**加粗**：` 段落与 `---` 分隔线不算
        if re.match(r'^[-*]\s+\S', l.strip()):
            errs.err('H9 表头区不放条目（D-57）：机器消费的元信息写进 frontmatter，'
                     '布局与配色写进对应小节表',
                     subject='表头', fix='删除该条目行')


def _check_level(meta, ft_path, errs):
    """level：声明与 ⊞ 推导双向校验（L0=主流程，D-59）——格式须为 L0/L1/L2…，且与推导一致。"""
    lv = meta.get('level')
    if lv is None:
        return
    lvs = str(lv).strip()
    if not re.fullmatch(r'L\d+', lvs):
        errs.err(f'H9 level 格式应为 L0/L1/L2…，实际「{lvs}」', subject='表头.level',
                 fix='L0=主流程，子流程从 L1 递增')
        return
    derived = _derived_level(ft_path)
    if int(lvs[1:]) != derived:
        errs.err(f'H9 level 声明「{lvs}」与 ⊞ 推导的 L{derived} 不一致',
                 subject='表头.level',
                 fix='按 ⊞ 嵌套深度修正 level（L0=主流程），或补全父链的 ⊞ 与 parent 声明')


def _check_parent(meta, ft_path, errs):
    """parent：双向一致（D-58）——非空则文件须存在，且父表里要有 ⊞ 指回本表。"""
    par = meta.get('parent')
    if par is not None and not str(par).strip():
        errs.err('H9 parent 为空（L0 主流程不写 parent，可整行删除）', subject='表头.parent')
    if str(par or '').strip():
        pft = Path(ft_path).parent / str(par).strip()
        me = Path(ft_path).resolve()
        if not pft.exists():
            errs.err(f'H9 parent 指向的文件不存在: {str(par).strip()}', subject='表头.parent',
                     fix='核对路径（相对本流程表目录）；父表改名/移动后要同步更新子表声明')
        elif not _has_backref(pft, me):
            errs.err(f'H9 parent「{str(par).strip()}」里没有指回本表的 ⊞ 声明——双向不一致',
                     subject='表头.parent',
                     fix='在父表对应节点的描述里补 ⊞ 指向本表，或修正/删除本表的 parent 声明')


def _check_refs(meta, ft_path, errs):
    """refs：依赖路径必须真实存在（单条字符串按单元素列表处理）；**写了键就不能是空值**（G38）。

    空值这一半原先漏了：`if item and not …exists()` 把空串整个跳过，于是 `refs: ['']` 静默通过，
    而同一组规则的 parent / level / id 空值都拦了（spec §3「H9 空值」把四者并列）。
    """
    refs = meta.get('refs')
    if refs is not None and not isinstance(refs, list):
        refs = [str(refs)]
    for item in (refs or []):
        item = str(item).strip()
        if not item:
            errs.err('H9 refs 有空条目（写了键就不能是空值）', subject='表头.refs',
                     fix='删掉空条目；整份依赖清单都不要就把 refs 整行删掉')
            continue
        if not (Path(ft_path).parent / item).exists():
            errs.err(f'H9 refs 依赖不存在: {item}', subject='表头.refs',
                     fix='核对路径（相对本流程表所在目录），或删除该条')


def _check_meta_id(meta, errs):
    """id：写了却为空 → H9（缺省取文件 stem，可整行删除）。"""
    i_ = meta.get('id')
    if i_ is not None and not str(i_).strip():
        errs.err('H9 id 为空（缺省取文件 stem，可整行删除）', subject='表头.id')


def _check_color_dup(meta, errs):
    """同一主体在「主体配色」里声明了两种不同的颜色 → H9。"""
    for who in meta.get('__color_dup__', []):
        errs.err(f'H9 主体配色：主体「{who}」被声明了两种不同的颜色', subject=f'表头.{who}',
                 fix='同一主体只保留一行颜色声明')


def _check_table_columns(ft_path, errs):
    """H9：主表的列名必须逐字等于 `flowtable.COLUMNS`。

    **列是按位置读的**，表头写错（少一列、换序、旧版 9 列）就是把数据放进错列——
    而"串列"不会自己报错，只会让图悄悄画错。所以这里硬拦。
    """
    try:
        md = Path(ft_path).read_text(encoding='utf-8-sig')
    except OSError:
        return
    hdr = header_cells(md)
    if hdr is None or hdr == list(COLUMNS):
        return                      # 没有表头行：`table_to_dsl` 另有"找不到流程表"的报错，不在这里叠一条
    miss = [c for c in COLUMNS if c not in hdr]
    extra = [c for c in hdr if c not in COLUMNS]
    detail = '；'.join(x for x in (
        f'缺 {"、".join(miss)}' if miss else '',
        f'多 {"、".join(extra)}' if extra else '',
        '列序与标准不一致' if not miss and not extra else '') if x)
    errs.err(f'H9 主表列名不合标准：{detail}', subject='流程表表头',
             fix='表头逐字用：| ' + ' | '.join(COLUMNS) + ' |')


def check_header(meta, ft_path, errs):
    """H9 表头规范（D-59，三区结构）：YAML=身份（键封闭、level/parent 双向校验、refs 存在）；
    正文配置区=渲染配置（键封闭）+ 主体配色（hex 格式与跨层一致在 resolve_colors 判）；
    表头区不放条目，背景散文退场（判断依据由节点 ⚠/⚠? 留痕承载，D-58）。

    依次调用各条独立校验，报错顺序与旧实现逐条一致。
    """
    fm_err = meta.get('__fm_error__')
    if fm_err:
        errs.err(f'H9 frontmatter 无法解析: {fm_err}', subject='表头',
                 fix='修正 YAML 语法（缩进用空格；冒号后加空格；列表用 - 项）')
        return
    _check_meta_keys(meta, errs)
    _check_table_columns(ft_path, errs)
    _check_header_entries(ft_path, errs)
    _check_level(meta, ft_path, errs)
    _check_parent(meta, ft_path, errs)
    _check_refs(meta, ft_path, errs)
    _check_meta_id(meta, errs)
    _check_color_dup(meta, errs)


# ----------------------------------------------------------------H10 证据完整性（PIPELINE-SPEC §6）
# **只在这一条上落地机器核**：引用完整性（H10.1）。§6 原稿还列了 H10.2 / H10.3 两条，
# 2026-09-18 逐条查过**现行实现**后判定它们与已发口径打架，故**不重复设判据**（理由写进 §6 与 G20）：
#   · H10.2「描述以 ⚠ 开头 ⇒ 依据非空」与 `flowtable-spec` §2 的「依据 / ⚠ **二选一**」相反，
#     而已发的是后者（`_check_basis` 那条软提示，见上）；
#   · H10.3「⚠? 节点必须在**澄清申请**里有条目」——`plan.md` 的澄清申请表**没有承载节点编号的列**
#     （列是 编号/问题/推荐答案/指向，指向的是 `M##`），而"⚠? 有没有账"早已由 `clarify.py` 的
#     frontier（前驱已定的 ⚠?）覆盖 ⇒ 判据无处安放，且需求已被满足。
ID_RE = re.compile(r'\bM\d{2,}#[A-Za-z]+\d+\b')


def find_task_ledger(start):
    """从某个产物所在目录**向上**找 `evidence.json`（任务级产物住成果根）→ `(账本或 None, 找过的最高目录)`。

    **一路找到盘根，不再只找 4 层**（2026-09-19 改，D-108）：原实现留着 `LEDGER_SEARCH_UP = 4`，
    理由是"成果根与流程目录平级、最多几层"——可**子表的子表**（`parts/<甲>/parts/<乙>/`）正好比它多一层，
    于是"我够不着"被报成了"**这次任务没有账本**"（那句是给人和 AI 看的结论），而 `--json` 那份
    连跳没跳都不说。**同一个词说两件事，比不说更坏**。

    判据仍然是"**最近的先赢**"：一路向上遇到的**第一份** `evidence.json` 就是它（同名文件不会有两个
    都在同一路径上）。第二项是**找不到时的话**：一路找到哪儿为止——不报这个，"没有账本"与
    "我把边界设窄了"这两种处境的结论长得一模一样。
    """
    d = Path(start)
    if d.is_file():
        d = d.parent
    while True:
        c = d / 'evidence.json'
        if c.is_file():
            return c, d
        if d.parent == d:                      # 到盘根（`C:\` / `/`）了，再往上还是它自己
            return None, d
        d = d.parent


def ledger_display(led, ft_path):
    """账本的**相对**写法（相对本表目录）——一眼看出它住在上面几层，而不是只报个文件名。"""
    import os
    try:
        return os.path.relpath(led, Path(ft_path).parent if Path(ft_path).is_file()
                               else Path(ft_path)).replace('\\', '/')
    except (ValueError, OSError):              # 跨盘符之类：退回原样，别为了好看把路径弄丢
        return str(led)


def ledger_element_ids(path):
    """账本里的 element id 集合；**读不动返回 `None`**（＝无从判断，不许当成"表写错了"）。"""
    try:
        import json
        got = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    els = got.get('elements') if isinstance(got, dict) else None
    if not isinstance(els, list):
        return None
    return {e.get('id') for e in els if isinstance(e, dict) and e.get('id')}


def citations(text):
    """文本里出现的 element id（按出现顺序，去重）。id 是**封闭语法**（§2.2），正则认得出来。"""
    out, seen = [], set()
    for m in ID_RE.finditer(text or ''):
        if m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(m.group(0))
    return out


def check_evidence(text, ft_path, errs):
    """**H10.1 引用完整**：产物里出现的每个 element id 都必须在账本里存在。

    **启用条件**（§6 最要紧的一条）：**这次任务有账本**（`evidence.json` 够得着）时才启用——
    纯口头需求、示例表、自举树都没有账本 ⇒ 跳过、不报错（新判据不许误伤合法的旧表）。

    两种失败分得清：
      · 引了不存在的 id ⇒ **硬错误**（点名是哪个 id、且它不在账本里）；
      · 账本**读不动**却又引了 id ⇒ 也是硬错误，但话不一样（"无从判断"不是"你写错了"，
        只是**不可追溯的引用不许交付**）；一句 id 都没引 ⇒ 不报（没有引用就没有可追溯性可谈）。
    """
    led, top = find_task_ledger(ft_path)
    # 记账：这一层**这次到底跑没跑**（调用方要如实打印，不许默默不用）。**三种处境分开**（D-108）：
    # 跑了 / 一路到盘根都没有账本 / 账本在但读不动（下面那支）。不记 `skip`，调用方就只能把
    # 后两种都说成"附近没有账本"——那正是"同一个词说两件事"。
    errs.evidence_checked = bool(led)
    errs.evidence_ledger = ledger_display(led, ft_path) if led else ''   # 相对本表目录的写法（给人看）
    errs.evidence_skip = ('' if led else
                          f'从本表目录一路向上找到 {top}（盘根）都没有 evidence.json')
    if not led:
        return False
    ids = ledger_element_ids(led)
    cited = citations(text)
    if ids is None:
        if cited:
            errs.err(f'H10 账本读不动，无法核对 {len(cited)} 处引用（{led.name}）：'
                     f'先修账本或重新解析材料，再校验',
                     subject='证据完整性',
                     fix=f'检查 {led} 是不是合法 JSON；重跑 `probe → parse → ledger` 生成新账本')
            return True
        return False
    miss = [i for i in cited if i not in ids]
    if miss:
        errs.err(f'H10 引用了账本里不存在的 element id：{"、".join(miss[:6])}'
                 f'{f"（共 {len(miss)} 个）" if len(miss) > 6 else ""}'
                 f'—— 账本 {led.name} 里共 {len(ids)} 条证据',
                 subject='证据完整性',
                 fix='改成账本里真实存在的 id（`query.py <账本> --grep 关键词` 找回它），'
                     '或把这条依据降级成 ⚠ 推断')
    return True


# ----------------------------------------------------------------入口
def run_checks(rows, mode='flow', errs=None, lane_order=None, notes=None):
    """按 ① → ② → ③ 跑完整套结构校验；返回 (nodes, edges, errs)。

    main 与 writeback 都走这里——顺序只写一份，否则加一层时漏改一处就出现"build 拦得住、回写拦不住"。

    `lane_order` 是元信息「泳道列序」解析出的显式列序；给了它就**同时启用槽位模式**
    （行从阶段号细化为槽位号）——列序是槽位求解的输入，两者只能一起定（见 swimlane-spec §2.1 / §3.1）。
    槽位求解的提示（如"含回路退回表序"）通过 `notes` 列表带回，不污染 errs 的硬/软错误。
    """
    errs = Errors() if errs is None else errs
    nodes = check_nodes(rows, errs)                  # ① 节点层
    if mode == 'swimlane':
        apply_swimlane(nodes, lane_order)
    edges, dangling = build_edges(nodes, errs)       # 取边
    if mode == 'swimlane' and lane_order:
        slots, slot_notes = assign_slots(nodes, edges)
        for n in nodes:
            n['row'] = slots[n['id']]
        if notes is not None:
            notes.extend(slot_notes)
    check_by_type(nodes, edges, errs)                # ② 类型层
    check_relations(nodes, edges, dangling, errs)    # ③ 关系层
    check_label_length(edges, errs)                  # 软提示
    return nodes, edges, errs
