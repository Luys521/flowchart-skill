# -*- coding: utf-8 -*-
r"""parse_pdf.py — PDF **文本层**解析适配器（PIPELINE-SPEC §1.4）：`.pdf`（T2）→ `elements[]`。

**只管有文本层的 PDF**：扫描件（T3）不归它管 — 那是视觉 / OCR 的活（§1.5 手段 2）。
档位由上游 `probe.py` 判（`/Font` 标记），本脚本**不重判** — 只做抽取。

**自包含优先**：用 `pdfplumber`（**纯 Python**，无外部二进制；`requirements.txt` 声明的必须依赖）。

**粒度**：**一页一个 element**（PDF 没有样式信息，"页"就是天然的段落块；与 `parse_xlsx` 的
"一张 sheet 一个 element" 同一取舍）。表格结构不抽 — 已知边界，见文件末。

**采样**：页数超上限就截断，并在**该材料的每个 element 上**标 `degraded`（消费方扫任意一条就知道这份是抽样的）；
单页字数超上限则**只标那一条**——材料级与元素级两档粒度不同，见 `parse_pdf` 的 docstring（§2.4 要求"降级必须记账"）。

**协作走产物**：读 `probe.py --json` 的材料层，产出元素层 JSON → 交给 `ledger.py`。

退出码：0 = 完成（可能有跳过）；2 = **缺依赖** 或输入读不了。
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

DEP_PKG = {'pdfplumber': 'pdfplumber'}


def _import_dep(name):
    """import 一个必须依赖 → `(模块, 报错文案)`（缺了给可执行的提示）。"""
    try:
        return importlib.import_module(name), ''
    except ImportError:
        pkg = DEP_PKG[name]
        return None, f'缺依赖 {pkg}：装 `python -m pip install {pkg}`（或 `pip install -r requirements.txt`）'


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def parse_pdf(path, mid, max_pages, max_chars):
    """`.pdf` → `(elements, 采样说明, 报错文案)`。只抽文本层；空页跳过（不伪造 element）。

    降级记两档，**粒度不同**（§2.4"降级必须留痕"，但留痕要留在对的地方）：
      - **材料级**（页数上限 / 某页抽取失败）：这份材料整体被采样过、或有读不动的页 ⇒ 挂到它的**每条**上
        （消费方扫任意一条就知道这份被降级过）；
      - **元素级**（该页正文超字数被截断）：只挂到**那一条**上 — 挂到别的页上就是假记账。
    """
    pdfplumber, err = _import_dep('pdfplumber')
    if err:
        return None, '', err
    out, shared, cut_pages = [], [], 0
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, 1):
            if pno > max_pages:
                shared.append(f'只取前 {max_pages} 页（共 {total} 页）')
                break
            try:
                text = (page.extract_text() or '').strip()
            except Exception as e:                      # 单页坏不让整份失败
                shared.append(f'第 {pno} 页抽取失败：{type(e).__name__}')
                continue
            if not text:
                continue
            cut = len(text) > max_chars
            if cut:
                text = text[:max_chars] + '…'
                cut_pages += 1
            el = {'id': f'{mid}#p{pno:03d}', 'material_id': mid, 'kind': 'paragraph',
                  'text': text, 'location': {'path': path.as_posix(), 'page': pno, 'quote': text},
                  'extractor': 'py:pdfplumber', 'certainty': 'direct'}
            if cut:
                el['degraded'] = f'第 {pno} 页正文截断到 {max_chars} 字'
            out.append(el)
    note = '；'.join(dict.fromkeys(shared))              # 去重但保序
    if note:
        for e in out:                                   # 材料级说明挂在**该材料的每条**上
            e['degraded'] = (e['degraded'] + '；' if e.get('degraded') else '') + note
    summary = '；'.join(x for x in [note, f'{cut_pages} 页正文截断到 {max_chars} 字' if cut_pages else '']
                        if x)
    return out, summary, ''


def parse_materials(materials, max_pages, max_chars):
    """材料层 → `(elements, 摘要, 跳过清单, 报错文案)`。非 PDF / 非 T2 一律跳过并记账。"""
    elements, notes, skipped = [], [], []
    for m in materials:
        mid = m.get('id', '?')
        path = Path(m.get('path', ''))
        if m.get('status') != 'ok':
            skipped.append(f'{mid}: status={m.get("status")}（不解析）')
            continue
        try:
            with open(path, 'rb') as f:      # 只读前 4 字节：材料可能上百 MB，不为认魔数整份读进内存
                head = f.read(4)
        except OSError:
            skipped.append(f'{mid}: 读不动')
            continue
        if head != b'%PDF':
            skipped.append(f'{mid}: 不是 PDF（tier={m.get("tier")}）')
            continue
        if m.get('tier') == 'T3':
            skipped.append(f'{mid}: 扫描件（T3）走视觉 / OCR，不在这里抽')
            continue
        try:
            got, note, err = parse_pdf(path, mid, max_pages, max_chars)
        except Exception as e:
            skipped.append(f'{mid}: 解析失败 {type(e).__name__}: {e}')
            continue
        if err:
            return None, notes, skipped, err
        elements += got
        notes.append(f'{mid} {len(got)} 页' + (f'（{note}）' if note else ''))
    return elements, notes, skipped, ''


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='PDF 文本层解析适配器：.pdf → elements[]')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--max-pages', type=int, default=50, help='最多抽多少页（超了记 degraded）')
    ap.add_argument('--max-chars', type=int, default=4000, help='单页最多多少字（超了截断并记账）')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    elements, notes, skipped, err = parse_materials(materials, a.max_pages, a.max_chars)
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
    print(f'→ 已写出 {where}：元素 {len(elements)} · 抽取 {len(notes)} 份 · 跳过 {len(skipped)} 份',
          file=sys.stderr)
    for s in skipped:
        print(f'  · 跳过 {s}', file=sys.stderr)
    return 0


# 已知边界：表格结构不抽（pdfplumber 的 extract_tables 可用，但对合并单元格/无线框表格不稳，
# 先把"文本能不能拿到"这条路走通；需要时再单独加一版 table 抽取，并同样标 extractor。

if __name__ == '__main__':
    sys.exit(main())
