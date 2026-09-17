# -*- coding: utf-8 -*-
"""writeback.py — 同步闭环回写：.drawio 读回结果 + 原《flowtable.md》→ 更新后的《flowtable.md》。

用法：python writeback.py flow.drawio flowtable.md [-o 更新流程表.md]

两条不许违反的底线（细则与原因见 references/drawio-loop.md 第 2 节）：
  1. 语义列只有**《流程表》**一个来源——图里压根不写它们（D-73）；图里新增的节点这几列留空，
     由结构校验（H7）报缺，而不是从图里"兜底"出一份半真半假的值
  2. 未改动的分支逐字回填原文——否则回写 diff 出伪差异，`--apply` 前那道复核就失效了

第三条底线（D-45）：**「下个节点」列也是语义列，同样受底线 1 管辖**。
它的值必然由 drawio 的边重建（表里那条边的目标就是图里的连线），所以无法像 stage/subject 那样
"直接取原表"；但**冲突必须报出来**，不能静默取图。见 `branch_conflicts()`。
"""
import argparse
import re
import sys
from pathlib import Path

from xml_reader import read
from flowtable import parse_table, parse_next_raw
from semantics import BRANCH_SEP, split_table_row, TYPE_EN_ZH
from flowtable import (C_DESC, C_EXECUTOR, C_NEXT, C_STAGE, C_SUBJECT, C_TIME, N_COLS, split_row_cells)
from flowtable import C_BASIS, C_ID, C_INPUT, C_OUTPUT, COLUMNS


def _cell(v):
    r"""单元格文本 → 可安全落进 markdown 表格的形态：`|` 必须转义成 `\|`（GFM 规范），
    否则一行被竖线断列。解析侧由 split_table_row 负责还原，往返稳定。"""
    return str(v).replace('|', '\\|')


def _is_sep_cell(s):
    """GFM 分隔行单元格：`---` / `:---` / `:---:`（与 table_to_dsl.parse_table 同一判据）。"""
    return bool(re.fullmatch(r':?-+:?', s))


# 占位符的等价类：与 table_to_dsl.parse_next_raw / 校验口径一致（空、`-`、`—`、`无` 都表示"没有"）
_PLACEHOLDERS = {'-', '—', '无'}


def _row_key(cells):
    """行 → 可比对的键：占位符归一（主体/执行者 → `-`，行动所需时间/下个节点 → `—`）。

    原表写「无」或留空、回写按约定统一成 `—`/`-` 时**语义没变**，逐格比却判成整行改动，
    于是"什么都没动"的 sync 也会冒出伪 diff——而 diff 是 --apply 前唯一要复核的界面（D-12）。
    """
    cs = list(cells) + [''] * (N_COLS - len(cells))
    key = list(cs)
    for idx in (C_INPUT, C_BASIS, C_OUTPUT, C_TIME, C_NEXT):
        v = (cs[idx] or '').strip()
        key[idx] = '—' if (v == '' or v in _PLACEHOLDERS) else v
    for idx in (C_SUBJECT, C_EXECUTOR):
        v = (cs[idx] or '').strip()
        key[idx] = '-' if (v == '' or v in _PLACEHOLDERS) else v
    return key


def _tail(raw, tid):
    """token 里编号之后的自由注解：`不齐全→回 01 补件` → ` 补件`。

    表达不进 (label, tid)，只能从原文取；改了标签的分支也要沿用同一目标的原注解，
    否则用户只是把「不齐全」改成「否」，「补件」就凭空消失了。"""
    # 只认**箭头之后**的那一个编号：注解里若再出现同一编号
    # （`不齐全→回 01 参照 01 重审`），rfind 会命中注解里的那份，把 tail 截成「 重审」。
    m = re.search(r'(?:→|->)\s*(?:回\s*)?' + re.escape(tid), raw)
    if m:
        return raw[m.end():]
    i = raw.find(tid)
    return raw[i + len(tid):] if i >= 0 else ''


def orig_tokens(orig_rows, known):
    """原流程表「下个节点」列 → {节点id: [(raw, label, tid, tail)]}（保留作者顺序与原文）。"""
    out = {}
    for cells in orig_rows:
        cells = split_row_cells(cells)
        nid = cells[1].strip()
        if not nid:
            continue
        out[nid] = [(raw, lb, tid, _tail(raw, tid))
                    for raw, lb, tid, _lp in parse_next_raw(cells[C_NEXT], None, known)]
    return out


def new_token(e, order, src):
    """生成一条分支文本（仅用于原表里没有对应项的新增/改动分支）。
    `回` 用"目标节点在图中靠前"作判据——只在没有原文可比时兜底，不用于覆盖原文。"""
    pre = (e['label'] + '→') if e.get('label') else '→'
    is_back = order.get(e['to'], 999) < order.get(src, 999)
    return pre + ('回 ' if is_back else '') + e['to']


def build_rows(data, orig=None):
    order = {n['id']: i for i, n in enumerate(data['nodes'])}
    by_from = {}
    for e in data['edges']:
        by_from.setdefault(e['from'], []).append(e)
    rows = []
    for n in data['nodes']:
        pool = list((orig or {}).get(n['id'], []))
        taken = [False] * len(pool)
        want = {(e['to'], e.get('label') or '') for e in by_from.get(n['id'], [])}
        # 只从"不会被精确匹配占用"的原 token 里取注解，免得把别的分支的注解搬过来
        spare = {}
        for raw, lb, tid, tl in pool:
            if (tid, lb) not in want:
                spare.setdefault(tid, tl)
        branches = []
        for e in by_from.get(n['id'], []):     # 文档顺序 = 作者书写顺序，不按编号推
            hit = None
            for i, (raw, lb, tid, _tl) in enumerate(pool):
                if not taken[i] and tid == e['to'] and lb == (e.get('label') or ''):
                    taken[i] = True
                    hit = raw
                    break
            branches.append(hit if hit else new_token(e, order, n['id']) + spare.get(e['to'], ''))
        nxt = f' {BRANCH_SEP} '.join(branches) if branches else '—'
        rows.append({'id': n['id'], 'name': n['name'],
                     'type': TYPE_EN_ZH.get(n['type'], n['type']),
                     'stage': '',          # 图里没有语义列（D-73）：这几项一律由 _rebuild_rows 定
                     'subject': '', 'executor': '', 'time': '', 'next': nxt, 'desc': '',
                     'input': '', 'basis': '', 'output': ''})
    return rows


def branch_conflicts(data, orig_rows) -> list:
    """原流程表「下个节点」列 vs drawio 实际连线的**方向性冲突**清单（D-45）。

    为什么需要单列这一步：「下个节点」是语义列，却不可能像 stage/subject 那样"直接取原表"——
    表里那个值就是图里那条边的目标，重建是必然的。所以它的兜底方式只能是**冲突时报警**，
    而不是静默取图。否则「改了流程表但没重跑 build」会在 sync 时被静默回退（D-01 描述的那类错），
    且报错文案看起来还像用户自己改的。

    判据（只报**方向性**冲突，不报纯新增/删除）：
      原表说 A 的某条分支去 B，而图里该分支（按 标签 配对）去了 C，B≠C → 冲突。
    纯新增（图里多一条边）、纯删除（图里少一条边）不算冲突——那是用户在 drawio 里
    增删节点的正当操作，`diff()` 已经会报出来。把这两类也当冲突会淹没真正的信号。

    返回 [{'id', 'label', 'table', 'drawio'}]，按节点编号排序。
    """
    known = {c[1].strip() for c in orig_rows if len(c) >= 2 and c[1].strip()}
    tokens = orig_tokens(orig_rows, known)

    by_from = {}
    for e in data['edges']:
        by_from.setdefault(e['from'], []).append(e)

    out = []
    for n in data['nodes']:
        nid = n['id']
        pool = tokens.get(nid, [])
        if not pool:
            continue
        # 原表按 (label) → 目标集合；图按 (label) → 目标集合
        tbl = {}
        for _raw, lb, tid, _tl in pool:
            tbl.setdefault(lb or '', set()).add(tid)
        dia = {}
        for e in by_from.get(nid, []):
            dia.setdefault(e.get('label') or '', set()).add(e['to'])
        # 只在**同一标签**下比对：标签本身变了是"改标签"，不是"改走向"（`_check_writeback_labels` 覆盖那类）
        for lb, targets in tbl.items():
            if lb not in dia:
                continue                     # 该标签在图里没了 → 纯删除，交给 diff()
            moved = targets - dia[lb]
            added = dia[lb] - targets
            if moved and added:
                out.append({'id': nid, 'label': lb,
                            'table': '、'.join(sorted(moved)),
                            'drawio': '、'.join(sorted(added))})
    return sorted(out, key=lambda x: x['id'])


def format_conflicts(conflicts) -> str:
    """冲突清单 → 人读文本（`sync.py` / `xml_reader.py` 共用一份文案，别两处各写一遍）。"""
    return '\n'.join(
        f"⚠ 节点 {c['id']} 分支「{c['label'] or '(无标签)'}」走向冲突："
        f"流程表 → {c['table']} ｜ 图 → {c['drawio']}"
        for c in conflicts)


def _read_drawio(flow_drawio):
    """读回 drawio XML（utf-8-sig 兼容带 BOM 的产物）。"""
    # utf-8-sig：带 BOM 的 drawio 按裸 utf-8 读，第一个字符是 \ufeff，ET.fromstring 直接抛解析错
    return read(Path(flow_drawio).read_text(encoding='utf-8-sig'))


def _read_orig_snapshot(orig_ft):
    """原流程表快照：看**字节**判换行符与 BOM，解码出全文与行列表。"""
    # 换行符与 BOM 必须看**字节**：Path.read_text 的通用换行会把 CRLF 归一成 LF，
    # 按文本判断会永远判成 LF，于是 CRLF 的原文整份"变成改动"。写回时用 newline='' 关掉翻译。
    raw = Path(orig_ft).read_bytes()
    nl = '\r\n' if b'\r\n' in raw else '\n'
    enc = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
    orig_text = raw.decode(enc)
    return nl, enc, orig_text, orig_text.splitlines()


def _semantic_snapshot(orig_rows):
    """原流程表按 id 的语义快照（阶段/描述/主体/执行者/时间/输入/依据/输出）——id 在原表出现过，语义就以原表为准。"""
    default = {}
    for cells in orig_rows:
        cells = split_row_cells(cells)
        default[cells[C_ID].strip()] = {
            'stage': cells[C_STAGE].strip(), 'desc': cells[C_DESC].strip(),
            'subject': cells[C_SUBJECT].strip(), 'executor': cells[C_EXECUTOR].strip(),
            'time': cells[C_TIME].strip(), 'input': cells[C_INPUT].strip(),
            'basis': cells[C_BASIS].strip(), 'output': cells[C_OUTPUT].strip()}
    return default


def _orig_line_index(orig_lines):
    """原行文本（按 id）：未改动的行**整行照抄**，免得"多/少一个空格"这种伪差异混进 diff。"""
    orig_line = {}
    for l in orig_lines:
        if not l.startswith('|'):
            continue
        cs = split_table_row(l)
        if len(cs) >= 2 and cs[1] and cs[1] != '节点编号' and not _is_sep_cell(cs[1]):
            orig_line[cs[1]] = l
    return orig_line


def _split_table_block(orig_lines, orig_text, orig_ft):
    """定位标准表头与表格块边界 → (前言, 表后内容, 前言与表头之间的间隔, 尾换行)。"""
    # 保留原文件表头**之前**的全部前言（标题/项目元信息/小标题）；表头与本工具统一生成。
    # 找不到标准表头（含「节点编号」列）时无从界定"表格在哪"，硬猜只会把全文与新表拼一起、节点全量重复。
    header_idx = next((i for i, l in enumerate(orig_lines)
                       if l.startswith('|') and '节点编号' in l), -1)
    if header_idx < 0:
        raise ValueError(f'原流程表缺少标准表头（须含「节点编号」列的 12 列表头）：{orig_ft}')
    # 表格块 = 表头起**连续**的 | 行；表格之后的全部内容（如「## 列填写规范」整节）原样保留——
    # 回写只重建表格本身，丢表后内容等于一次 --apply 删掉半份文档。
    end_idx = header_idx
    while end_idx < len(orig_lines) and orig_lines[end_idx].startswith('|'):
        end_idx += 1
    head = '\n'.join(orig_lines[:header_idx])
    after = orig_lines[end_idx:]
    # 前言与表头之间的空行原样保留（少一行也算 diff 噪声）
    # 表头前**连续几个**空行就留几个：只看紧邻一行的话，原文有两个空行回写后只剩一个，
    # 于是"没改任何节点"也会冒出一行 diff——而 diff 正是 --apply 该不该落盘的判据。
    _k = 0
    _i = header_idx - 1
    while _i >= 0 and not orig_lines[_i].strip():
        _k += 1
        _i -= 1
    # 表头就在文件第 0 行时没有前言可接，gap 必须是空——否则凭空多一个前导空行，
    # "没改任何节点"也会冒出一行伪 diff（裸表流程表正是这个形态）
    gap = '\n' * (_k + 1) if header_idx > 0 else ''
    tail = '\n' if orig_text.endswith('\n') else ''
    return head, after, gap, tail


def _rebuild_rows(data, tokens, default, orig_line):
    """逐行重建表格行与表格体（未改动整行照抄），并记下自检所需的 _resolved/_stage。"""
    rows = build_rows(data, tokens)
    tpl = '| ' + ' | '.join(COLUMNS) + ' |'
    body = [tpl, '| ' + ' | '.join(['---'] * N_COLS) + ' |']
    for r in rows:
        d = default.get(r['id'], {})
        # 语义列只有两个来源：原《流程表》按 id 命中，或**空**（图里新增的节点，D-73）。
        # 图这一面不存语义，所以没有第三种来源，也用不着比较优先级。
        st, desc = d.get('stage', ''), d.get('desc', '')
        subj, execu, tm = d.get('subject', ''), d.get('executor', ''), d.get('time', '')
        inp, bas, out = d.get('input', ''), d.get('basis', ''), d.get('output', '')
        line = (f'| {_cell(st)} | {_cell(r["id"])} | {_cell(r["name"])} | {_cell(r["type"])} |'
                f' {_cell(inp or "—")} | {_cell(bas or "—")} | {_cell(out or "—")} |'
                f' {_cell(subj or "-")} | {_cell(execu or "-")} | {_cell(tm or "—")} |'
                f' {_cell(r["next"])} | {_cell(desc)} |')
        old = orig_line.get(r['id'])
        # 占位符不同的同一行算"未改动"（见 _row_key）：否则 `无` / 空被归一成 `—` 就整行重写
        if old is not None and _row_key(split_table_row(old)) == _row_key(split_table_row(line)):
            body.append(old)                  # 未改动：整行照抄原文
        else:
            body.append(line)
        r['_resolved'] = (subj, execu, tm)
        r['_io'] = (inp, bas, out)
        r['_stage'] = st                  # 下面回写后自检要用：必须与写进文件的 stage 同一个值
        r['_desc'] = desc
    return rows, body


def _keep_after_table(after, rows):
    """表后内容保留：丢掉混进来的表内散行，其余（说明章节等）逐字保留。"""
    # 表后内容里混进的「表内行」（表格中段被空行隔开的散行）不算表后章节：body 已按 drawio
    # 重建全部节点，原样保留会出现同一节点两行。散行丢弃、其余内容（说明章节等）逐字保留——
    # 没有散行时 after 必须原样拼回，否则"无改动"场景做不到逐字节一致。
    body_ids = {r['id'] for r in rows}
    kept_after = []
    for l in after:
        if l.startswith('|'):
            cs = split_table_row(l)
            if len(cs) >= 2 and (cs[1] in body_ids or cs[1] == '节点编号' or _is_sep_cell(cs[1])):
                continue
        kept_after.append(l)
    return kept_after


def _emit_table(out_path, head, gap, body, kept_after, tail, nl, enc, rows, default):
    """前言 / 表格体 / 表后内容拼回，按原换行符与编码落盘，并打印回写统计。"""
    out = head.rstrip('\n') + gap + '\n'.join(body)
    if kept_after:
        out += '\n' + '\n'.join(kept_after)
    out += tail
    Path(out_path).write_text(out.replace('\n', nl), encoding=enc, newline='')
    print(f'✓ 已回写流程表: {out_path}  节点:{len(rows)}'
          f'  新增节点:{sum(1 for r in rows if r["id"] not in default)}')


def _verify_written(rows, data, orig_rows):
    """回写后自检（H1–H8），并报警分支走向冲突与缺语义的节点；返回**是否通过**。"""
    # 走 table_to_dsl 的统一入口，别另抄一份调用清单——漏一层就出现"回写放行、build 拦住"的缺口。
    from flowtable_check import run_checks
    # 与写入文件保持一致的占位符（图里新增的节点无语义时用 -/— 占位，交由自检留痕确认，
    # 而非被 H7 卡死——缺什么由下面那句点名，不靠硬错误把人堵在回写这一步）
    cells = [
        # stage / desc 用**写进文件**的那两个值（原表优先、否则空），不能重新取 default——
        # 新增节点不在 default 里，那样会按空值自检，泳道布局下 stage 就是泳道归属，
        # 于是"文件里是 A 泳道、自检按空泳道跑"，结论与产物不符。
        [r['_stage'], r['id'], r['name'], r['type'],
         r['_io'][0] or '—', r['_io'][1] or '—', r['_io'][2] or '—',
         r['_resolved'][0] or '-', r['_resolved'][1] or '-', r['_resolved'][2] or '—',
         r['next'], r['_desc']]
        for r in rows
    ]
    _nodes, _edges, errs = run_checks(cells)
    if errs.hard:
        print('✗ 回写结果未过结构校验：\n   ' + '\n   '.join(errs.hard))
    else:
        print('✓ 回写结果通过结构校验（H1–H8）')    # D-45：分支走向冲突必须显式报警。"下个节点"是语义列，但它的值必然由图重建，
    # 没法像其他语义列那样直接取原表——只能把冲突摆到台面上，让人裁决。
    for line in format_conflicts(branch_conflicts(data, orig_rows)).splitlines():
        print(line)
    miss = [r['id'] for r in rows
            if r['_resolved'][0] in ('', '-') or r['_resolved'][1] in ('', '-')]
    if miss:
        print(f'⚠ 缺主体/执行者的节点 {len(miss)} 个：{"、".join(miss[:20])}'
              + ('…' if len(miss) > 20 else '')
              + '（图里新增的节点没有语义，须补进《流程表》并以 ⚠ 标出）')
    # **自检不过要影响退出码**：上面那句 ✗ 是"这份 .sync.md 不能当成品"的判词，而它同时是
    # `--apply` 要原样覆盖过去的东西——打了 ✗ 却退 0，编排层（与 shell 的 `&&`）就会把它
    # 当成可用产物接着往下走（实测：`sync --apply` 靠这个返回值拦下覆盖）。
    return not errs.hard


def write(flow_drawio, orig_ft, out_path):
    """drawio 读回结果 + 原流程表 → 更新后的流程表（回写闭环主入口）。

    返回**自检是否通过**（见 `_verify_written`）——文件已经写出来了（预览要看得到），
    但调用方必须拿这个返回值决定"能不能当成品用"。
    """
    data = _read_drawio(flow_drawio)
    nl, enc, orig_text, orig_lines = _read_orig_snapshot(orig_ft)
    _title, _meta, orig_rows = parse_table(orig_text)
    # 原流程表默认值（阶段 / 描述）按 id 保留；头部与元信息原样保留
    default = _semantic_snapshot(orig_rows)
    tokens = orig_tokens(orig_rows, set(default))
    orig_line = _orig_line_index(orig_lines)
    head, after, gap, tail = _split_table_block(orig_lines, orig_text, orig_ft)
    rows, body = _rebuild_rows(data, tokens, default, orig_line)
    kept_after = _keep_after_table(after, rows)
    _emit_table(out_path, head, gap, body, kept_after, tail, nl, enc, rows, default)
    return _verify_written(rows, data, orig_rows)


def compare_bytes(orig_ft, out_ft):
    """回写结果 vs 原文的**文件级**复核 → (是否逐字节一致, unified diff 行列表)。

    结构 diff 是集合比较，看不见分支顺序/自由注解/「回」/换行符与 BOM，而回写 diff 是 `--apply` 前唯一要复核的界面。
    """
    before = Path(orig_ft).read_bytes()
    after = Path(out_ft).read_bytes()
    if before == after:
        return True, []
    import difflib
    old_l = Path(orig_ft).read_text(encoding='utf-8', errors='replace').splitlines()
    new_l = Path(out_ft).read_text(encoding='utf-8', errors='replace').splitlines()
    return False, list(difflib.unified_diff(old_l, new_l, 'flowtable.md',
                                           Path(out_ft).name, n=0, lineterm=''))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='drawio 回读结果 → 更新流程表')
    ap.add_argument('drawio_path')
    ap.add_argument('orig_ft', help='原 flowtable.md')
    ap.add_argument('-o', '--out', help='输出更新流程表路径')
    a = ap.parse_args()
    for p in (Path(a.drawio_path), Path(a.orig_ft)):
        if not p.exists():
            print(f'✗ 找不到文件: {p}')
            return 1
    orig = Path(a.orig_ft)
    out = a.out or str(orig.parent / (orig.stem + '.sync.md'))
    try:
        ok = write(a.drawio_path, a.orig_ft, out)
    except ValueError as e:
        print(f'✗ {e}')
        return 1
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
