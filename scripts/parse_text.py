# -*- coding: utf-8 -*-
r"""parse_text.py — 纯文本适配器（PIPELINE-SPEC §1.4）：`.md` / `.txt` / `.csv` / `.json` … → `elements[]`。

**这个脚本不负责"让 AI 读懂"**。文本格式（`.md` / `.txt` / `.csv` / `.json` / `.yaml` / `.xml` / `.html`）
宿主模型**能直接读**，而且读得比任何结构识别都好——那是 §1.4 的**加速器**（"宿主模型直读文本"）。
所以这里只剩一件事：**记账**。四条理由全部与"读得懂"无关：

1. **可引用**：账本是唯一事实源（§2.5），流程表「依据」列要引 `M03#p012` 这种 id，**H10 才核得动**；
   模型自己读一遍、记在"心里的上下文"里，是一条无法机器复核的引用。
2. **可复现**：`probe → parse → ledger` 两次**逐字节相同**（§2.4 幂等）——模型读一遍写下的东西做不到。
3. **编码与上限**：GBK 材料、几十万字的 `.txt` 要能读进来并**如实截断记账**（§2.4 降级必须留痕）。
4. **无模型在环也跑得完**（§0 自包含）：能直读的能力是**加速器**，不许成为唯一路径。

所以它**只做两件事**：

- **解码 + 按行打块**：按行拼成 ≤ `--max-chars` 的块，一块一个 element（`extractor=py:text`；
  标记/数据文件记 `py:code`）。**不认结构**——标题 / 列表 / 表格语义是"给模型看懂"的活，工具去认，
  认错了反而让 `kind` 撒谎；这里的"块"只是**引用粒度**。
- **`.csv` / `.tsv` → `table` + `rows`**：这是**表示**不是"理解"——"一行一记录"是这种格式本身的事实。

`kind` 只按扩展名标一下**这一份是文本还是标记/数据**（`.json`/`.yaml`/`.xml`/`.html` → `code`），**不解析内容**。

**归属按内容**：`PK` 容器 / `%PDF` / OLE 头**不是我的**（留给别的适配器）；剩下的且 `probe` 判成 **T1** 的才读。
**编码只认 UTF-8 与带 BOM 的 UTF-16**；`--encoding` 是**显式认领**（见 `decode_text`），不做自动猜测。

退出码：0 = 完成（可能有跳过）；2 = 输入读不了。
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

# 别的适配器的地盘：按魔数判（与 probe 同一套判据，但这里问的是"**该谁读**"，不是"属于哪一档"）
OTHER_MAGIC = ((b'PK', 'OOXML 容器'), (b'%PDF', 'PDF'), (b'\xd0\xcf\x11\xe0', 'OLE（legacy）'))

CSV_EXTS = ('csv', 'tsv')                             # 这两种出 `table` + `rows`
CODE_KINDS = ('json', 'yaml', 'yml', 'xml', 'html', 'htm')   # 这两种只影响 `kind` 标签，不解析内容

# **只在用户显式给 `--encoding` 时**才会用到的一张表：允许去试那些 `probe` 判成 T4 的材料。
# 为什么需要它：GBK 材料在 `probe` 眼里是"魔数不认识，且不是文本"（UTF-8 解不开），于是它进不了
# 本适配器的 T1 门槛 ⇒ `--encoding gbk` 等于没用。而为什么**不能**只凭 `--encoding` 就什么文件都试：
# GBK 几乎能解任何字节对，`.mp3` 也能"解"成一篇乱码——那不是证据，是垃圾。
# 所以这条路的两道门缺一不可：**用户显式认领编码** + **扩展名属于纯文本那一族**。
TEXT_EXTS = ('.md', '.markdown', '.txt', '.text', '.csv', '.tsv', '.json', '.yaml', '.yml',
             '.xml', '.html', '.htm', '.log', '.ini', '.conf')

DEFAULT_MAX_CHARS = 2000        # 一个"块"多大（引用粒度；也是单块截断上限）
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

    **不猜本地编码**：GBK 几乎能解任何字节对，拿它当判据 = 把二进制当文本。
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


def kind_of(path):
    """扩展名 → `'csv'` / `'code'` / `'text'`。**只分这三类**：结构不在本脚本的射程内（见文件头）。"""
    ext = Path(path).suffix.lower().lstrip('.')
    if ext in CSV_EXTS:
        return 'csv'
    return 'code' if ext in CODE_KINDS else 'text'


def _element(mid, prefix, seq, kind, text, path, extractor, max_chars):
    """造一个带正文的 element（`quote` = 原文摘录）；超上限截断并记 `degraded`（§2.4）。"""
    body = text.strip()
    if not body:
        return None
    cut = len(body) > max_chars
    if cut:
        body = body[:max_chars] + '…'                 # 截断处留省略标记（§2.3 不许无声变短）
    seq[prefix] = seq.get(prefix, 0) + 1
    el = {'id': f'{mid}#{prefix}{seq[prefix]:03d}', 'material_id': mid, 'kind': kind, 'text': body,
          'location': {'path': path.as_posix(), 'quote': body},
          'extractor': extractor, 'certainty': 'direct'}
    if cut:
        el['degraded'] = f'正文截断到 {max_chars} 字（单行比块还长）'
    return el


def _blocks(text, mid, path, which, max_chars):
    """文本 → **按行打块**：空行收一块，块满 `max_chars` 也收 → 一块一个 element。

    这里**没有结构判断**（不认标题 / 列表 / 表格）：那是模型直读要干的事。
    "块"只是引用粒度——`kind` 只说明"这份是文本还是标记/数据"（**必须落在 §2.1 的封闭枚举里**：
    文本块记 `paragraph`、标记/数据块记 `code`；`extractor` 记 `py:text` / `py:code`）。
    """
    kind = 'code' if which == 'code' else 'paragraph'
    prefix = 'c' if which == 'code' else 'p'
    extractor = f'py:{which}'
    out, seq, buf, used = [], {}, [], 0

    def flush():
        nonlocal buf, used
        el = _element(mid, prefix, seq, kind, '\n'.join(buf), path, extractor, max_chars)
        if el:
            out.append(el)
        buf, used = [], 0

    for line in text.splitlines():
        if not line.strip():
            flush()                                   # 空行 = 天然的块边界（排版事实，不是语义判断）
            continue
        if buf and used + len(line) + 1 > max_chars:
            flush()                                   # **先收上一块、再放这一行**：块不许超上限
        buf.append(line.rstrip())
        used += len(line) + 1
    flush()
    return out, extractor


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


def parse_text(path, mid, forced, max_chars, max_rows, max_cols):
    """一份材料 → `(elements, extractor, 报错, 内容为空)`。

    三种终局分得清：**不是我的**（`[], '', '', False`，留给别的适配器）、**我的但读不动**（报错非空，
    调用方记 `unreadable` + 原因）、**读出来了**（含"解出来只有空白"→ `empty=True`，记 `skipped`）。
    """
    try:
        blob = path.read_bytes()
    except OSError as e:
        return [], '', f'读不动（{type(e).__name__}: {e}）', False
    who = other_owner(blob)
    if who:
        return [], '', '', False                       # 别人的地盘：**不吭声**（抢着下结论就是双份真值）
    text, _how, err = decode_text(blob, forced)
    if err:
        return [], '', err, False
    if not text.strip():
        return [], '', '', True
    which = kind_of(path)
    try:
        if which == 'csv':
            got, extractor = _csv(text, mid, path, max_rows, max_cols)
        else:
            got, extractor = _blocks(text, mid, path, which, max_chars)
    except (csv.Error, ValueError, TypeError) as e:     # 单份坏不让整批失败（§1.4 硬要求 2）
        return [], '', f'{which} 读法失败（{type(e).__name__}: {e}）', False
    if not got:
        return [], '', '', True                        # 解出来了但没有内容（只有空白 / 空表）
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
    ap = argparse.ArgumentParser(description='纯文本适配器：按行打块 + csv 表格（**不做结构识别**，见文件头）')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--notes', help='材料层补注写到哪里（status / reason / extractor，交给 ledger.py --notes）')
    ap.add_argument('--encoding', default='', help='显式指定编码（如 gbk）；默认只认 UTF-8 与带 BOM 的 UTF-16')
    ap.add_argument('--max-chars', type=int, default=DEFAULT_MAX_CHARS,
                    help='一个块多大（引用粒度，也是单块截断上限）')
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
# - **不认结构，也不做 DOM 转换**：标题 / 列表 / 表格语义 / HTML 正文抽取都是"给模型看懂"的活——
#   模型直读文本（§1.4 的加速器）比工具认得好；工具去认，认错了会让 `kind` 撒谎，而账本是唯一事实源。
#   真需要结构化抽取（例如把 HTML 正文抽成标题层级）就走**转换器**那条路（T2），另立一版适配器。
# - **编码不猜**：只认 UTF-8 与带 BOM 的 UTF-16（GBK 几乎能解任何字节对，拿它当判据 = 把二进制当文本）。
# - **`kind` 只有 paragraph / code / table 三种**：够用即止；引用粒度靠 `id`（分块号），不靠 kind 细分。
