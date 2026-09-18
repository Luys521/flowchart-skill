# -*- coding: utf-8 -*-
r"""parse_text.py — 纯文本解析适配器（PIPELINE-SPEC §1.4）：`.md` / `.txt` / `.csv` / `.json` … → `elements[]`。

**自包含**：只用 Python 标准库（`csv` / `re`），**没有第三方依赖**——这是 §1.4 表里唯一"都没有时"也读得动的一档。

**按扩展名选读法，按内容定归属**：归属不是扩展名说了算——`PK` 容器（OOXML）、`%PDF`、OLE 头**都不是我的**，
留给别的适配器；剩下的、且 `probe` 判成 **T1** 的，才由本脚本读。档位不重判（§1.1：档位的家是 `probe`）。

**编码只认 UTF-8 与带 BOM 的 UTF-16**（`--encoding` 可显式指定，如 `gbk`）：
**不在没有 BOM 时猜本地编码**——GBK 几乎能解任何字节对，拿它当判据会把二进制判成文本，
与 `probe` 的取向一致（判不出不猜）。要读 GBK 材料：显式 `--encoding gbk`，或先转成 UTF-8。

**四种读法**（靠扩展名分，认不出按"段落"）：
- `.md` / `.markdown` → 按行认结构：标题 / 列表项 / 围栏代码 / 竖线表 / 其余段落；
- `.csv` / `.tsv` → `kind=table` + `rows` 二维数组（标准库 `csv`，行 / 列封顶）；
- `.json` / `.yaml` / `.yml` / `.xml` / `.html` / `.htm` → **整份一个 `code` element**（见文件末的边界）；
- 其余（`.txt` / `.log` / 认不出的扩展名）→ 空行分段，一段一个 `paragraph`。

**标记原样留在 `text` 里**（`# 标题` / `- 项`）：账本的 `quote` 是**原文摘录**，剥掉标记就对不上材料了；
`kind` 已经说明它是什么，要"干净标题"的消费方自己剥。

退出码：0 = 完成（可能有跳过）；2 = 输入读不了。
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

# 别的适配器的地盘：按魔数判（与 probe 同一套判据，但这里问的是"**该谁读**"，不是"属于哪一档"）
OTHER_MAGIC = ((b'PK', 'OOXML 容器'), (b'%PDF', 'PDF'), (b'\xd0\xcf\x11\xe0', 'OLE（legacy）'))

MARKDOWN_READER = ('md', 'markdown')
CSV_READER = ('csv', 'tsv')
CODE_READER = ('json', 'yaml', 'yml', 'xml', 'html', 'htm')

HEADING_RE = re.compile(r'^(#{1,6})(\s+.*)?$')
LIST_RE = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+\S')
SEP_CELL_RE = re.compile(r'^:?-{2,}:?$')

# **只在用户显式给 `--encoding` 时**才会用到的一张表：允许去试那些 `probe` 判成 T4 的材料。
# 为什么需要它：GBK 材料在 `probe` 眼里是"魔数不认识，且不是文本"（UTF-8 解不开），于是它进不了
# 本适配器的 T1 门槛 ⇒ `--encoding gbk` 等于没用。而为什么**不能**只凭 `--encoding` 就什么文件都试：
# GBK 几乎能解任何字节对，`.mp3` 也能"解"成一篇乱码——那不是证据，是垃圾。
# 所以这条路的两道门缺一不可：**用户显式认领编码** + **扩展名属于纯文本那一族**。
TEXT_EXTS = ('.md', '.markdown', '.txt', '.text', '.csv', '.tsv', '.json', '.yaml', '.yml',
             '.xml', '.html', '.htm', '.log', '.ini', '.conf')

DEFAULT_MAX_CHARS = 4000
DEFAULT_MAX_ROWS = 200
DEFAULT_MAX_COLS = 50
DEFAULT_MAX_ELEMENTS = 2000


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write_notes(notes, path):
    """写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`）。"""
    Path(path).write_bytes((json.dumps(notes, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def other_owner(blob):
    """前几字节 → 该材料归谁（`'OOXML 容器'` / …）；不是别人的返回空串。"""
    for magic, who in OTHER_MAGIC:
        if blob[:len(magic)] == magic:
            return who
    return ''


def decode_text(blob, forced=''):
    """字节 → `(文本, 依据, 报错)`。顺序：**UTF-8（含 BOM）→ 带 BOM 的 UTF-16 → 用户给的兜底编码**。

    兜底**不是覆盖**：`--encoding gbk` 不该把同一批里**本来是 UTF-8** 的材料读坏——实测踩到过：
    全局覆盖会让它们集体变成"按 gbk 解不开"，一份文件把整批拖成读不动。
    """
    try:                                              # utf-8-sig：BOM 可有无（有就吃掉）
        return blob.decode('utf-8-sig'), 'UTF-8', ''
    except UnicodeDecodeError:
        pass
    if blob[:2] in (b'\xff\xfe', b'\xfe\xff'):        # utf-16 **只在有 BOM 时才试**（无 BOM 会按本机字节序瞎解）
        try:
            return blob.decode('utf-16'), 'UTF-16（BOM）', ''
        except UnicodeDecodeError as e:
            return None, '', f'UTF-16 BOM 但解不开（{type(e).__name__}）'
    if forced:
        try:
            return blob.decode(forced), f'--encoding {forced}', ''
        except (UnicodeDecodeError, LookupError) as e:
            return None, '', (f'按 {forced} 也解不开（{type(e).__name__}）：换个 --encoding，'
                              f'或把材料转成 UTF-8')
    return None, '', ('既不是 UTF-8，也不是带 BOM 的 UTF-16：要读 GBK 等本地编码，'
                      '显式给 --encoding（例如 --encoding gbk），或把材料转成 UTF-8')


def reader_of(path):
    """扩展名 → 读法名（`'markdown'` / `'csv'` / `'code'` / `'plain'`）。认不出按 `plain`（不猜结构）。"""
    ext = Path(path).suffix.lower().lstrip('.')
    if ext in MARKDOWN_READER:
        return 'markdown'
    if ext in CSV_READER:
        return 'csv'
    if ext in CODE_READER:
        return 'code'
    return 'plain'


def _cap(text, limit):
    """超上限就截断 → `(文本, 是否截断)`。截断处留省略标记（§2.3 不许无声变短）。"""
    return (text[:limit] + '…', True) if len(text) > limit else (text, False)


def _element(mid, prefix, seq, kind, text, path, extractor, max_chars, extra=None):
    """造一个带正文的 element（`quote` = 原文摘录）；超上限截断并记 `degraded`（§2.4）。"""
    body, cut = _cap(text.strip(), max_chars)
    if not body:
        return None
    seq[prefix] = seq.get(prefix, 0) + 1
    el = {'id': f'{mid}#{prefix}{seq[prefix]:03d}', 'material_id': mid, 'kind': kind, 'text': body,
          'location': {'path': path.as_posix(), 'quote': body},
          'extractor': extractor, 'certainty': 'direct'}
    if extra:
        el.update(extra)
    if cut:
        el['degraded'] = f'正文截断到 {max_chars} 字'
    return el


def _plain(text, mid, path, max_chars):
    """纯文本 → 空行分段，一段一个 `paragraph`。"""
    out, seq, buf = [], {}, []
    for line in text.splitlines():
        if line.strip():
            buf.append(line.rstrip())
            continue
        el = _element(mid, 'p', seq, 'paragraph', '\n'.join(buf), path, 'py:text', max_chars)
        if el:
            out.append(el)
        buf = []
    el = _element(mid, 'p', seq, 'paragraph', '\n'.join(buf), path, 'py:text', max_chars)
    if el:
        out.append(el)
    return out, 'py:text'


def _markdown(text, mid, path, max_chars):
    """Markdown → 标题 / 列表项 / 围栏代码 / 竖线表 / 段落。**标记原样留在 text 里**（见文件头）。"""
    out, seq, buf, table = [], {}, [], []
    code = None                                       # None = 不在围栏里；list = 围栏里攒的行

    def flush_para():
        nonlocal buf
        el = _element(mid, 'p', seq, 'paragraph', '\n'.join(buf), path, 'py:markdown', max_chars)
        if el:
            out.append(el)
        buf = []

    def flush_table():
        rows = []
        for row in table:
            cells = [c.strip() for c in row.strip().strip('|').split('|')]
            if cells and all(SEP_CELL_RE.match(c) for c in cells if c):
                continue                              # `|---|---|` 是标记行，不是数据
            rows.append(cells)
        if rows:
            seq['t'] = seq.get('t', 0) + 1
            out.append({'id': f'{mid}#t{seq["t"]:03d}', 'material_id': mid, 'kind': 'table',
                        'text': path.stem, 'rows': rows,
                        'location': {'path': path.as_posix()},
                        'extractor': 'py:markdown', 'certainty': 'direct'})
        table.clear()

    for line in text.splitlines():
        if line.lstrip().startswith('```'):            # 围栏：开、闭都靠它
            if code is None:
                flush_para()
                code = []
            else:
                el = _element(mid, 'c', seq, 'code', '\n'.join(code), path, 'py:markdown', max_chars)
                if el:
                    out.append(el)
                code = None
            continue
        if code is not None:
            code.append(line)
            continue
        if table and not line.strip().startswith('|'):
            flush_table()
        if HEADING_RE.match(line):
            flush_para()
            el = _element(mid, 'h', seq, 'heading', line, path, 'py:markdown', max_chars)
            if el:
                out.append(el)
        elif LIST_RE.match(line):
            flush_para()
            el = _element(mid, 'l', seq, 'list_item', line, path, 'py:markdown', max_chars)
            if el:
                out.append(el)
        elif line.strip().startswith('|') and line.count('|') >= 2:
            flush_para()
            table.append(line)
        elif not line.strip():
            flush_para()
        else:
            buf.append(line.rstrip())
    if table:
        flush_table()
    if code is not None:                               # 围栏没闭合：当代码块收下（不丢内容）
        el = _element(mid, 'c', seq, 'code', '\n'.join(code), path, 'py:markdown', max_chars)
        if el:
            el['degraded'] = (el.get('degraded', '') + '；' if el.get('degraded') else '') + '围栏未闭合'
            out.append(el)
    flush_para()
    return out, 'py:markdown'


def _csv(text, mid, path, max_rows, max_cols):
    """CSV / TSV → **一份一个 `table`**（`rows` 承载内容，与 `parse_xlsx` 的"一张 sheet 一个 element"同一取舍）。"""
    delim = '\t' if path.suffix.lower() == '.tsv' else ','
    rows, cut = [], False
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i >= max_rows:
            cut = True
            break
        if len(row) > max_cols:
            cut = True
        vals = [c.strip() for c in row[:max_cols]]
        if any(vals):
            rows.append(vals)
    if not rows:
        return [], 'py:csv'
    el = {'id': f'{mid}#t001', 'material_id': mid, 'kind': 'table', 'text': path.stem, 'rows': rows,
          'location': {'path': path.as_posix()}, 'extractor': 'py:csv', 'certainty': 'direct'}
    if cut:
        el['degraded'] = f'超上限截断（行 > {max_rows} 或列 > {max_cols}）'
    return [el], 'py:csv'


def _code(text, mid, path, max_chars):
    """机器格式（json / yaml / xml / html …）→ **整份一个 `code`**。结构解析是 T2 转换器的活（见文件末）。"""
    el = _element(mid, 'c', {}, 'code', text, path, 'py:code', max_chars)
    return ([el] if el else []), 'py:code'


def parse_text(path, mid, forced, max_chars, max_rows, max_cols):
    """一份材料 → `(elements, extractor, 报错, 内容为空)`。

    三种终局分得清：**不是我的**（`[] , '', '', False`，留给别的适配器）、**我的但读不动**（报错非空，
    调用方记 `unreadable` + 原因）、**读出来了**（含"解出来只有空白"→ `empty=True`，记 `skipped`）。
    """
    try:
        blob = path.read_bytes()
    except OSError as e:
        return [], '', f'读不动（{type(e).__name__}: {e}）', False
    who = other_owner(blob)
    if who:
        return [], '', '', False                       # 别人的地盘：**不吭声**（抢着下结论就是双份真值）
    text, how, err = decode_text(blob, forced)
    if err:
        return [], '', err, False
    if not text.strip():
        return [], '', '', True
    which = reader_of(path)
    try:
        if which == 'csv':
            got, extractor = _csv(text, mid, path, max_rows, max_cols)
        elif which == 'markdown':
            got, extractor = _markdown(text, mid, path, max_chars)
        elif which == 'code':
            got, extractor = _code(text, mid, path, max_chars)
        else:
            got, extractor = _plain(text, mid, path, max_chars)
    except (csv.Error, ValueError, TypeError) as e:     # 单份坏不让整批失败（§1.4 硬要求 2）
        return [], '', f'{which} 读法失败（{type(e).__name__}: {e}）', False
    if not got:
        return [], '', '', True                        # 解出来了但没有内容（只有标记 / 空表）
    return got, extractor, '', ''


def _mark_capped(elements, note):
    """材料级降级说明挂到**该材料的每条**上（与 `parse_pdf` 同一口径：消费方扫任意一条就知道被裁过）。"""
    for e in elements:
        e['degraded'] = (e.get('degraded') + '；' if e.get('degraded') else '') + note


def parse_materials(materials, forced, max_chars, max_rows, max_cols, max_elements):
    """材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。

    **只认 T1**（档位是 `probe` 的家，不在这里重判）：T2/T3/T4 一律不记账——留给别的适配器或澄清。
    """
    elements, notes, done, skipped = [], [], [], []
    for m in materials:
        mid = m.get('id', '?')
        path = Path(m.get('path', ''))
        claimed = m.get('status') == 'ok' and m.get('tier') == 'T1'
        # 显式 `--encoding` = 用户认领了编码：这时才去试 probe 判成 T4 的纯文本材料（两道门见 TEXT_EXTS）
        override = (not claimed and bool(forced) and m.get('status') == 'unreadable'
                    and path.suffix.lower() in TEXT_EXTS)
        if not (claimed or override):
            continue                                   # 不是 T1：不吭声（另有适配器 / 已被 probe 记账）
        got, extractor, err, empty = parse_text(path, mid, forced, max_chars, max_rows, max_cols)
        if err:
            notes.append({'material_id': mid, 'status': 'unreadable', 'reason': err})
            skipped.append(f'{mid}: {err}')
            continue
        if empty:
            notes.append({'material_id': mid, 'status': 'skipped',
                          'reason': '解出来只有空白（空材料）：不进证据账本，也不当它能读'})
            skipped.append(f'{mid}: 内容为空')
            continue
        if not got:
            continue                                   # 不是文本或不是我的：**留给别的适配器**
        if len(got) > max_elements:                    # 单份材料的元素上限（防一份巨大的 txt 灌满账本）
            got = got[:max_elements]
            _mark_capped(got, f'只收前 {max_elements} 个元素（材料还有更多）')
        elements += got
        done.append(f'{mid}({path.suffix.lower() or "无扩展名"}) {len(got)}')
        note = {'material_id': mid, 'extractor': extractor}
        if override:
            # 读出来了 ⇒ 要**改回 ok**（否则账本上是"unreadable 却又有人产出了证据"，
            # 而 probe 那条 reason 会变成陈旧真值；ledger 落补注时会顺手删掉它）
            note['status'] = 'ok'
            done[-1] += f'（按 --encoding {forced} 读出来，覆盖 probe 的 T4 判定）'
        notes.append(note)
    return elements, notes, done, skipped, ''


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='纯文本解析适配器：.md / .txt / .csv / .json … → elements[]')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--notes', help='材料层补注写到哪里（status / reason / extractor，交给 ledger.py --notes）')
    ap.add_argument('--encoding', default='', help='显式指定编码（如 gbk）；默认只认 UTF-8 与带 BOM 的 UTF-16')
    ap.add_argument('--max-chars', type=int, default=DEFAULT_MAX_CHARS, help='单个元素最多多少字（超了截断并记账）')
    ap.add_argument('--max-rows', type=int, default=DEFAULT_MAX_ROWS, help='CSV / TSV 的行上限')
    ap.add_argument('--max-cols', type=int, default=DEFAULT_MAX_COLS, help='CSV / TSV 的列上限')
    ap.add_argument('--max-elements', type=int, default=DEFAULT_MAX_ELEMENTS, help='单份材料的元素上限')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    elements, notes, done, skipped, err = parse_materials(
        materials, a.encoding, a.max_chars, a.max_rows, a.max_cols, a.max_elements)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2

    text = json.dumps(elements, ensure_ascii=False, indent=2) + '\n'
    if a.out:
        Path(a.out).write_bytes(text.encode('utf-8'))
        where = a.out
    else:
        sys.stdout.write(text)
        where = 'stdout'
    if a.notes:
        _write_notes(notes, a.notes)
    print(f'→ 已写出 {where}：元素 {len(elements)} · 解析 {len(done)} 份 · 跳过 {len(skipped)} 份'
          f' · 补注 {len(notes)} 条', file=sys.stderr)
    for s in skipped:
        print(f'  · 跳过 {s}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（要扩就得另立一版适配器，并同样标 extractor）：
# - **HTML / XML 不做 DOM 转换**：那是 T2 转换器的活（抽正文）；现在整份进 `code`。要读"干净的正文"
#   就走转换器那条路，而不是在这里塞一个半吊子的标签剥离——半吊子剥离会让 quote 与材料对不上。
# - **Markdown 不做完整实现**：只认标题 / 列表 / 围栏 / 竖线表四类前缀；嵌套列表、引用块、HTML 块
#   都按普通行落进段落——**宁可少认结构，不可错认**（错认会让 kind 撒谎，而账本是唯一事实源）。
# - **编码不猜**：只认 UTF-8 与带 BOM 的 UTF-16（GBK 几乎能解任何字节对，拿它当判据 = 把二进制当文本）。
