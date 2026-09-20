# -*- coding: utf-8 -*-
"""flowtable.py — 《flowtable.md》解析层：三区结构 → (title, meta, rows) + 语义取出边。

只取值、不判定：解析 frontmatter 身份区 / 正文「渲染配置」「主体配色」小节 / 主流程表，
并把「下个节点」取成边。判对错归 flowtable_check，布局归 flowtable_layout，配色归 flowtable_colors。

父表链（`find_parent_table` 及两只私有助手）也放在这里：它只依赖解析结果，且配色继承
（flowtable_colors）与 build 的面包屑共用同一棵树——父子关系的判据只此一份。

`Errors` 也放在这里：它是解析层取边时就在用的错误收集器，校验层（flowtable_check）继续复用同一类。
"""
import re
from pathlib import Path

from artifact import NON_TABLE_MD

try:
    import yaml
except ImportError:
    yaml = None

from semantics import (split_branches, has_ambiguous_sep, BRANCH_SEP,
                       split_table_row, subflow_ref, subflow_target,
                       Finding)

ID_RE = re.compile(r'(\d+[a-zA-Z]?)')

COLOR_KEY = '执行主体配色'


class Errors:
    """结构校验的错误收集器：hard 阻断渲染，soft 只提示。

    err/warn 可选带 `subject`（节点/行定位）与 `fix`（建议修法）：正文以
    `Finding(str)` 落表（见 D-55），打印与 gates 断言不变；`--json` 透出结构化字段。
    """

    def __init__(self):
        self.hard = []
        self.soft = []
        # H10 的**启用记账**（§6；由 `flowtable_check.check_evidence` 落，D-108）：
        # 这一层这次跑没跑、用的是哪本账（**相对本表目录**的写法，给人看）、没跑是因为什么。
        # 写在**类里**而不是调用方用 `getattr` 兜：漏掉一个字段时 `getattr` 会**静默**给出 False，
        # 而那个 False 会被打印成"没有账本"——本仓最不能忍的就是"仪器没跑，结论却像跑过了"。
        self.evidence_checked = False
        self.evidence_ledger = ''
        self.evidence_skip = ''

    def err(self, m, subject=None, fix=None):
        self.hard.append(Finding(m, subject, fix) if (subject or fix) else m)

    def warn(self, m, subject=None, fix=None):
        self.soft.append(Finding(m, subject, fix) if (subject or fix) else m)

    @property
    def ok(self):
        return not self.hard


# ----------------------------------------------------------------解析（只取值，不判定）
def _extract_title(lines):
    """取首个 `# 标题` → 流程名；没有则用约定的 '流程图'。"""
    return next((l[2:].strip() for l in lines if l.startswith('# ')), '流程图')


def _read_frontmatter(lines):
    """解析首部 YAML 身份区 → (meta, body_start)；语法错误记入 meta['__fm_error__'] 交给 H9。"""
    meta = {}
    body_start = 0
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if end is not None:
            body_start = end + 1
            fm = '\n'.join(lines[1:end])
            loaded = None
            if fm.strip():
                if yaml is None:
                    meta['__fm_error__'] = '缺少 PyYAML，无法解析 frontmatter'
                else:
                    try:
                        loaded = yaml.safe_load(fm)
                    except yaml.YAMLError as e:
                        meta['__fm_error__'] = str(e).splitlines()[0]
            if isinstance(loaded, dict):
                meta.update(loaded)
            elif loaded is not None:
                meta['__fm_error__'] = f'frontmatter 应为键值映射，实际是 {type(loaded).__name__}'
    return meta, body_start


def _locate_main_table(lines, body_start):
    """定位主表表头行号：第一个含「项目运作阶段」的表头行（配置小节的表没有这一列）；无则 None。"""
    return next((i for i in range(body_start, len(lines))
                 if lines[i].startswith('|') and '项目运作阶段' in lines[i]), None)


def _read_layout_sections(lines, body_start, main_hdr):
    """读主表之前的「渲染配置」「主体配色」两个小节 → (cfg, colors, dup_subject)。"""
    cfg, colors, dup_subject = {}, {}, []
    if main_hdr is None:
        return cfg, colors, dup_subject
    for r in _read_section(lines, body_start, main_hdr, '渲染配置'):
        if len(r) >= 2 and r[0]:
            cfg[r[0]] = r[1]
    for r in _read_section(lines, body_start, main_hdr, '主体配色'):
        if len(r) >= 2 and r[0]:
            if r[0] in colors:
                dup_subject.append(r[0])       # 同一主体声明两行 → H9（D-59）
            colors[r[0]] = r[1].replace('\\#', '#').strip()
    return cfg, colors, dup_subject


def _merge_meta(meta, cfg, colors, dup_subject):
    """把配置小节归一化并入 meta（键名与插入顺序不变，下游消费方零改动）。"""
    if '输出布局' in cfg:
        meta['输出布局'] = cfg['输出布局']
    if '泳道列序' in cfg:
        meta['泳道列序'] = cfg['泳道列序']
    if colors:
        meta[COLOR_KEY] = colors
    if dup_subject:
        meta['__color_dup__'] = dup_subject


def _is_separator_row(cells):
    """GFM 表格分隔行判定：允许 `---` / `:---` / `:---:`（冒号对齐）。"""
    return all(re.fullmatch(r':?-+:?', c) for c in cells if c != '')


def _read_body_rows(lines, main_hdr):
    """读主表数据行：跳表头与分隔行，遇非表格行即停 → rows。"""
    rows, in_tbl = [], False
    if main_hdr is None:
        return rows
    for l in lines[main_hdr + 1:]:
        if not l.startswith('|'):
            break                   # 主表结束（空行/下一个节）
        cells = split_table_row(l)
        if not in_tbl:              # 第一行是表头，已由 main_hdr 定位
            in_tbl = True
            continue
        # 分隔行：GFM 允许 `---` / `:---` / `:---:`（冒号对齐），只认裸短横线会把它当数据行报假 H7
        if _is_separator_row(cells):
            continue
        rows.append(cells)
    return rows


# ----------------------------------------------------------------列结构（唯一事实源）
# 顺序即 ICOM：一个节点 = 一个盒子 + 四支箭头（拿什么 → 凭什么叫 → 交出什么 → 谁在做），
# 之后才是度量（行动所需时间）与去向（下个节点），最后是补充说明。
# 「依据」是 ICOM 的 Control：不被消耗、只决定"能不能做、做到什么程度"（条款/标准/判据）。
# **全仓的列下标都从这里取**：以前 `9` 与 `cells[7]`/`cells[8]` 散在 6 个文件的十几处，
# 改一次列结构要改一整片、还容易漏——漏了就是数据串列，而串列不报错。
# 字段的层级/来源/显性判定/渲染去向/校验见 references/flowtable-spec.md §2 的字段登记表。
COLUMNS = ('项目运作阶段', '节点编号', '节点名称', '节点类型', '输入', '依据', '输出',
           '执行主体', '执行者', '行动所需时间', '下个节点', '节点描述')
(C_STAGE, C_ID, C_NAME, C_TYPE, C_INPUT, C_BASIS, C_OUTPUT,
 C_SUBJECT, C_EXECUTOR, C_TIME, C_NEXT, C_DESC) = range(len(COLUMNS))
N_COLS = len(COLUMNS)

# 「显性判定」用的空值：这几栏全表都是它 ⇒ 本表对该字段是隐性（不要求填、不进悬浮框）
BLANK = ('—', '-', '－', '无', '')


def split_row_cells(cells):
    """一行单元格 → 补齐/截断到 N_COLS 的列表。列**按位置**读，所以长度先对齐再取值。"""
    out = list(cells)[:N_COLS]
    return out + [''] * (N_COLS - len(out))


def header_cells(md: str):
    """主表表头行 → 列名列表（找不到返回 None）。

    列按位置读，表头写错就是把数据放进错列——所以表头必须逐字等于 `COLUMNS`（由 H9 判）。
    """
    for line in md.splitlines():
        if line.lstrip().startswith('|') and '节点编号' in line:
            return [c.strip() for c in line.strip().strip('|').split('|')]
    return None


def parse_table(md: str):
    """返回 (title, meta, rows)。三区结构（D-59）：frontmatter 身份 + 正文配置小节 + 主流程表。

    - frontmatter：id / level / parent / refs / description（身份区，键封闭由 H9 判）
    - 正文小节「## 渲染配置」（键值表：输出布局/泳道列序…）与「## 主体配色」（执行主体/颜色 hex 表）
      解析后**并入 meta**（键名不变），下游消费方（resolve_colors / parse_lane_order / sync）零改动
    - rows = 「项目运作阶段」主表的数据行（正文里可能有别的表，主表按表头特征定位）
    frontmatter 语法错误记入 meta['__fm_error__']，由 check_header 报 H9。
    """
    lines = [l.rstrip('\n') for l in md.splitlines()]
    title = _extract_title(lines)
    meta, body_start = _read_frontmatter(lines)
    main_hdr = _locate_main_table(lines, body_start)
    cfg, colors, dup_subject = _read_layout_sections(lines, body_start, main_hdr)
    _merge_meta(meta, cfg, colors, dup_subject)
    rows = _read_body_rows(lines, main_hdr)
    return title, meta, rows


def _read_section(lines, start, stop, name):
    """在 lines[start:stop] 里找 `## {name}` 小节，返回其表格数据行 [[c1, c2], …]（无则 []）。"""
    out, in_sec, in_tbl = [], False, False
    for l in lines[start:stop]:
        s = l.strip()
        if s.startswith('## '):
            if in_sec:
                break
            in_sec = s[3:].strip() == name
            in_tbl = False
            continue
        if not in_sec or not s.startswith('|'):
            continue
        cells = split_table_row(s)
        if not in_tbl:                  # 小节表头（如「键 | 值」）
            in_tbl = True
            continue
        if _is_separator_row(cells):
            continue
        out.append([c.strip() for c in cells])
    return out


# ----------------------------------------------------------------取边（②③ 的输入，只解析不判定）
def parse_next(nxt: str, errs, known=None):
    """解析「下个节点」→ [(label, tid, is_loop)]。

    known 传已有 id 集合时优先整体匹配，以兼容外部 drawio 的非数字 id（n1），免得被 ID_RE 截成 "1"。
    """
    return [(lb, tid, lp) for _raw, lb, tid, lp in parse_next_raw(nxt, errs, known)]


def _resolve_target(target, known):
    """把一段目标文本解析成节点 id：已知 id 优先整体匹配，字母开头的外部 id 整体返回，否则取数字编号。"""
    raw = re.sub(r'^回\s*', '', target).strip()
    if known and raw in known:
        return raw
    # 字母开头且带数字（n1 / S1 / node-3）= 外部 id 风格：整体返回，让 H3 指认原文，
    # 别被 ID_RE 截成 "1" 连错节点（编号规则同理，见 check_nodes）。
    if raw[:1].isalpha() and any(ch.isdigit() for ch in raw):
        return raw
    tm = ID_RE.search(raw)
    return tm.group(1) if tm else None


def _report_ambiguous_sep(nxt, errs):
    """H3：分号误用（`通过→05；不通过→06`）会静默丢掉第二条出口——必须拦下，见 DECISIONS.md D-04。"""
    if has_ambiguous_sep(nxt) and errs is not None:
        errs.err(f'H3 「下个节点」里出现了分号，但分号是内容字符、不是分隔符："{nxt}"'
                 f'（多个出口之间请用 `{BRANCH_SEP}` 分隔；若分号本属于标签的一部分，请改写措辞）')


def _split_route_parts(nxt, errs, known):
    """把「下个节点」原文按分支分隔符切开，逐段解析成 (raw, label, tid, is_loop)。"""
    parts = split_branches(nxt)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m = re.match(r'^(.*?)(?:→|->)(.+)$', p)
        if not m:
            tid = _resolve_target(p, known)
            if tid:
                out.append((p, '', tid, False))
            else:
                if errs is not None:
                    errs.err(f'无法解析「下个节点」段: "{p}"')
            continue
        label = m.group(1).strip()
        target = m.group(2).strip()
        # 「回」是目标**前缀**标记（resolve 只剥行首的回）；在任意位置 search 会把
        # `→05 驳回重报` 这类注解含"回"字的正向边误判成回环、渲染成虚线。
        is_loop = target.startswith('回')
        tid = _resolve_target(target, known)
        if tid:
            out.append((p, label, tid, is_loop))
        else:
            if errs is not None:
                errs.err(f'节点分支 "{p}" 无法解析目标编号')
    return out


def parse_next_raw(nxt: str, errs=None, known=None):
    """同 parse_next，但多返回该分支的**原样文本**：[(raw, label, tid, is_loop)]。

    `raw` 供 writeback 逐字回填未改动的分支——分支顺序、「回」标记、编号后的自由注解
    都表达不进 (label, tid) 二元组，只能从原文取。
    """
    if not nxt or nxt.strip() in ('—', '-', '无'):
        return []
    _report_ambiguous_sep(nxt, errs)
    return _split_route_parts(nxt, errs, known)


def build_edges(nodes, errs):
    """按「下个节点」取出边，**不做判定**；返回 (edges, dangling)。

    dangling（目标不存在的 (起点, 目标)）只记不报，也不放进 edges——放进去后按 id 建邻接表会 KeyError；判定归 ③。
    """
    by_id = {n['id']: n for n in nodes}
    known = set(by_id)
    edges, dangling = [], []
    for n in nodes:
        for label, tid, is_loop in parse_next(n['route'], errs, known):
            if tid not in by_id:
                dangling.append((n['id'], tid))
                continue
            edges.append({'from': n['id'], 'to': tid, 'label': label, 'is_loop': is_loop})
    return edges, dangling


def wrote_route(n):
    """"下个节点"单元格里到底写没写内容（不判断写得对不对）——分辨"真没有出口"与"目标编号不存在"。
    """
    return (n.get('route') or '').strip() not in ('', '—', '-', '无')


# ----------------------------------------------------------------父表链（配色继承与面包屑共用，D-58）
def _parent_by_declaration(ft, me, meta):
    """子表 frontmatter 声明了「父表」→ 直接定位并校验回指，O(1)；未声明或校验不过返回 None。"""
    declared = str(meta.get('parent') or '').strip()
    if not declared:
        return None
    pft = ft.parent / declared
    if pft.exists() and _has_backref(pft, me):
        return pft.resolve(), _backref_node(pft, me)
    return None


def _parent_by_scan(me):
    """未声明的表：沿目录向上扫 `*.md`，找 ⊞ 指到 me 的那张父表（一路走到盘根）；找不到 None。"""
    d = me.parent
    while d != d.parent:                 # 一路走到盘根为止
        for parent_ft in sorted(d.glob('*.md')):
            if parent_ft.resolve() == me:
                continue
            if parent_ft.name in NON_TABLE_MD:
                continue        # 伴生文档不是表（见 artifact.NON_TABLE_MD / PIPELINE-SPEC §8.2）
            try:
                text = parent_ft.read_text(encoding='utf-8-sig')
            except OSError:
                continue
            for line in text.splitlines():
                if not line.lstrip().startswith('|'):
                    continue
                raw = [c.strip() for c in line.strip().strip('|').split('|')]
                if not raw:
                    continue
                ref = subflow_ref(split_row_cells(raw)[C_DESC])
                if not ref:
                    continue
                # 父表里的路径相对**父表目录**解析，指到本表才算父子关系。
                if (d / ref).with_suffix('.md').resolve() == me:
                    return parent_ft, split_row_cells(raw)[C_NAME]
        d = d.parent
    return None


def find_parent_table(ft):
    """这张流程表是不是别人的下钻子图？是则返回 (父表 Path, 父节点名)，不是返回 None。

    两级查找（D-58）：① 子表 frontmatter 声明了「父表」→ 直接定位并校验回指，O(1)，
    不再从本表目录扫到盘根；② 未声明（主表 / 未迁移的表）→ 沿目录向上扫 `*.md`（原有逻辑）。
    两条路认的是**同一种父子关系**——父表里必须有 ⊞ 恰好指向本表，声明与扫描永不各说各话。

    **扫 `*.md` 而不是钉死 `flowtable.md`**：约定名只管"产物叫什么"（`flow.*`），
    不管父表自己叫什么。子表常被命名成语义名（`parts/渲染.md`），父表同理也可能叫
    `主流程.md`；钉死一个文件名会让"换个名字就断掉回程路"，而断掉的那一头用户看不见
    （子图看起来只是"少了个面包屑"），排查成本极高。

    为什么要自动找而不是加个 `--parent` 参数：加参数就得**每次手工写对**，写错就少一条回程路
    （下钻进去出不来，比不下钻还糟）。这里的信息在流程表里本来就有，没理由让人再抄一遍。
    找不到就返回 None（本表就是顶层主图，不渲染面包屑）——静默，不报错。
    """
    me = ft.resolve()
    try:
        _t, meta, _r = parse_table(ft.read_text(encoding='utf-8-sig'))
    except OSError:
        return None
    found = _parent_by_declaration(ft, me, meta)
    if found:
        return found
    return _parent_by_scan(me)


def _has_backref(parent_ft, me):
    """父表文件里是否存在一条 ⊞ 指回 me（「父表」声明的双向一致性校验，D-58）。"""
    try:
        _t, _m, rows = parse_table(Path(parent_ft).read_text(encoding='utf-8-sig'))
    except OSError:
        return False
    pdir = Path(parent_ft).parent
    for cells in rows:
        cells = split_row_cells(cells)
        ref = subflow_target(cells[C_DESC])
        if ref and (pdir / ref).resolve() == me:
            return True
    return False


def _backref_node(parent_ft, me):
    """父表中指回 me 的那条 ⊞ 所在行的节点名（面包屑显示用）。"""
    try:
        _t, _m, rows = parse_table(Path(parent_ft).read_text(encoding='utf-8-sig'))
    except OSError:
        return ''
    pdir = Path(parent_ft).parent
    for cells in rows:
        cells = split_row_cells(cells)
        ref = subflow_target(cells[C_DESC])
        if ref and (pdir / ref).resolve() == me:
            return cells[C_NAME].strip()
    return ''
