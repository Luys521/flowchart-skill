# -*- coding: utf-8 -*-
r"""parse_ooxml.py — OOXML 解析适配器（PIPELINE-SPEC §1.4）：`.docx` / `.xlsx` → `elements[]`。

**自包含优先**：用 `python-docx` / `openpyxl`（`requirements.txt` 里声明的**必须**依赖）。
宿主 Office SDK / 多模态模型是**加速器**，不属于本脚本（探测到才用的那部分在 spec §1.4）。

**协作走产物**（本仓分层纪律：模块层之间不许互相 import）：本脚本读 `probe.py --json` 的材料层，
产出元素层 JSON，再交给 `ledger.py` — 三段串起来是 `probe → parse_ooxml → ledger`；
`--notes` 另写**材料层补注**（`extractor` 这类"走了哪条路"的记账，§2.1）。

三条边界：**只读材料**（不改、不动）；**不做语义判断**（不猜流程、不合并节点）；
**抽不出不猜**（跳过并记账，不伪造空 element）。

退出码：0 = 完成（可能有跳过）；2 = **缺依赖** 或输入读不了（缺依赖报可执行的错，不静默降级）。
"""
import argparse
import importlib
import json
import sys
import zipfile
from pathlib import Path

DEP_PKG = {'docx': 'python-docx', 'openpyxl': 'openpyxl'}


def _import_dep(name):
    """import 一个必须依赖 → `(模块, 报错文案)`。缺了给**可执行**的提示（§1.4）。"""
    try:
        return importlib.import_module(name), ''
    except ImportError:
        pkg = DEP_PKG[name]
        return None, (f'缺依赖 {pkg}：装 `python -m pip install {pkg}`'
                      f'（或 `python -m pip install -r requirements.txt`）')


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write_notes(notes, path):
    """写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`）。"""
    Path(path).write_bytes((json.dumps(notes, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def container_kind(path):
    """PK 容器 → `'docx'` / `'xlsx'`；不是 OOXML 返回 None。

    这里再判一次容器**不是重复 probe**：probe 回答"这份材料属于哪一档"（档位口径），
    本函数回答"该用哪个 reader 打开"（打开方式）。两者判据不同，且都只读容器目录。
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    if 'word/document.xml' in names:
        return 'docx'
    if 'xl/workbook.xml' in names:
        return 'xlsx'
    return None


def _docx_body(doc):
    """按**文档阅读序**产出 (kind, 对象)：段落与表格交替，顺序不丢（§2.2 第 3 条）。"""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            yield 'p', Paragraph(child, doc)
        elif tag == 'tbl':
            yield 'tbl', Table(child, doc)


def parse_docx(path, mid):
    """`.docx` → `(elements, 报错文案)`。样式名判 heading / list_item（判不出就当 paragraph）。"""
    docx, err = _import_dep('docx')
    if err:
        return None, err
    out, seq = [], {'h': 0, 'l': 0, 'p': 0, 't': 0}
    for tag, obj in _docx_body(docx.Document(str(path))):
        if tag == 'p':
            text = (obj.text or '').strip()
            if not text:
                continue
            style = ''
            try:
                style = (obj.style.name or '').lower()
            except Exception:
                pass
            kind, pre = 'paragraph', 'p'
            if style.startswith('heading'):
                kind, pre = 'heading', 'h'
            elif 'list' in style:
                kind, pre = 'list_item', 'l'
            seq[pre] += 1
            out.append({'id': f'{mid}#{pre}{seq[pre]:03d}', 'material_id': mid, 'kind': kind,
                        'text': text, 'location': {'path': path.as_posix(), 'quote': text},
                        'extractor': 'py:docx', 'certainty': 'direct'})
        else:
            rows = [[(c.text or '').strip() for c in r.cells] for r in obj.rows]
            if not any(any(c for c in r) for r in rows):
                continue
            seq['t'] += 1
            out.append({'id': f'{mid}#t{seq["t"]:03d}', 'material_id': mid, 'kind': 'table',
                        'rows': rows, 'location': {'path': path.as_posix()},
                        'extractor': 'py:docx', 'certainty': 'direct'})
    return out, ''


def parse_xlsx(path, mid, max_rows, max_cols):
    """`.xlsx` → `(elements, 报错文案)`。**一张 sheet 一个 element**（`rows` 承载内容，§2.1）。

    超上限就截断并标 `degraded`（§2.4 降级必须记账）—大表（实测有 72 万字符的测算表）靠这条不炸账本。
    """
    openpyxl, err = _import_dep('openpyxl')
    if err:
        return None, err
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out = []
    try:
        for n, ws in enumerate(wb.worksheets, 1):
            rows, cut = [], False
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows:
                    cut = True
                    break
                if len(row) > max_cols:
                    cut = True
                vals = ['' if v is None else str(v) for v in row[:max_cols]]
                if any(vals):
                    rows.append(vals)
            el = {'id': f'{mid}#s{n:03d}', 'material_id': mid, 'kind': 'sheet',
                  'text': ws.title, 'rows': rows,
                  'location': {'path': path.as_posix(), 'sheet': ws.title},
                  'extractor': 'py:openpyxl', 'certainty': 'direct'}
            if cut:
                el['degraded'] = f'超上限截断（行 > {max_rows} 或列 > {max_cols}）'
            out.append(el)
    finally:
        wb.close()
    return out, ''


def parse_materials(materials, max_rows, max_cols):
    """材料层 → `(elements, 补注, 摘要, 跳过清单, 报错文案)`。非 OOXML / 非 ok 的一律**跳过并记账**。

    **补注**只写"抽到了、走的是哪条路"（§2.1 的 `extractor`）：这一档的跳过全是"**不归我管**"
    （legacy 归 `parse_legacy`、PDF 归 `parse_pdf`），**不在这里下"读不动"的结论**——抢着下就是双份真值。
    """
    elements, notes, done, skipped = [], [], [], []
    for m in materials:
        mid = m.get('id', '?')
        path = Path(m.get('path', ''))
        if m.get('status') != 'ok':
            skipped.append(f'{mid}: status={m.get("status")}（不解析）')
            continue
        kind = container_kind(path)
        if kind is None:
            skipped.append(f'{mid}: 不是 OOXML（tier={m.get("tier")}）')
            continue
        try:
            got, err = (parse_docx(path, mid) if kind == 'docx'
                        else parse_xlsx(path, mid, max_rows, max_cols))
        except Exception as e:
            skipped.append(f'{mid}: 解析失败 {type(e).__name__}: {e}')
            continue
        if err:
            return None, notes, done, skipped, err
        elements += got
        done.append(f'{mid}({kind}) {len(got)}')
        if got:
            notes.append({'material_id': mid, 'extractor': f'py:{kind}'})
    return elements, notes, done, skipped, ''


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')  # 摘要/报错走 stderr，同样要定编码（GBK 控制台会乱码）
    ap = argparse.ArgumentParser(description='OOXML 解析适配器：.docx / .xlsx → elements[]')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--notes', help='材料层补注写到哪里（status / reason / extractor，交给 ledger.py --notes）')
    ap.add_argument('--max-rows', type=int, default=200, help='每张 sheet 的行上限（超了记 degraded）')
    ap.add_argument('--max-cols', type=int, default=50, help='每张 sheet 的列上限')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    elements, notes, done, skipped, err = parse_materials(materials, a.max_rows, a.max_cols)
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
