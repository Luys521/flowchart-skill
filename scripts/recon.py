# -*- coding: utf-8 -*-
r"""recon.py — 侦查器（PIPELINE-SPEC §1.5）：难度排序 + **结构缩样** + 侦查结论表草稿。

**为什么需要**：真实材料里有**工具型文件**（如一张 sheet 就是一台计算器的测算表），能抽出几十万字符，
却**没有过程步骤**。先侦查，再决定解析深度 — 而不是先把账本灌满再发现没用。

**分工（§1.5）**：脚本只给**机器可算**的部分（难度分档 / 规模 / 结构缩样 / 机器建议处置），
"假设角色""含流程"是**语义判断**，由 AI 按 §1.5 的规则补 — 脚本不猜（脚本只执行、不承载判断）。

**自包含优先**：结构缩样用 `python-docx` / `openpyxl`（必须依赖）；宿主 Office SDK 若存在可读更全，
但它只是加速器，本脚本不依赖它。**「转图片」不在本脚本**（自包含侧无渲染能力，见 §7.2）。

**协作走产物**：读 `probe.py --json` 的材料层，不 import 它（模块层不许横向 import）。

退出码：0 = 完成；2 = 缺依赖 或 输入读不了。
"""
import argparse
import importlib
import json
import re
import sys
from pathlib import Path

DEP_PKG = {'docx': 'python-docx', 'openpyxl': 'openpyxl'}
# 难度序：T1 可直读 < T2 需转换器 < T3 需视觉（§1.1）。同档内再按规模排。
DIFF = {'T1': '易', 'T2': '难', 'T3': '最难'}


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


def _scale_docx(path, outline_max):
    """`.docx` → `(规模描述, 大纲行, 报错文案)`：只读结构，不物化全部文字。"""
    docx, err = _import_dep('docx')
    if err:
        return '', [], 0, err
    doc = docx.Document(str(path))
    n_body = sum(1 for _ in doc.element.body.iterchildren())
    outline = []
    for p in doc.paragraphs:
        text = (p.text or '').strip()
        style = ''
        try:
            style = p.style.name or ''
        except Exception:
            pass
        if text and style.lower().startswith('heading'):
            outline.append(f'{style}: {text}')
            if len(outline) >= outline_max:
                break
    scale = f'正文块 {n_body} · 表格 {len(doc.tables)}'
    return scale, outline, n_body + len(doc.tables), ''


def _scale_xlsx(path, sample_rows, sample_cols):
    """`.xlsx` → `(规模描述, 子表行, 报错文案)`：只用 `calculate_dimension()` 读尺寸，不扫单元格。"""
    openpyxl, err = _import_dep('openpyxl')
    if err:
        return '', [], 0, err
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    rows, total = [], 0
    try:
        for ws in wb.worksheets:
            dim = ws.calculate_dimension()          # 例 'A1:P123'；read_only 下也能用
            m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', dim or '')
            n_row = int(m.group(4)) if m else 0
            total += n_row
            rows.append(f'{ws.title}：{dim}（{n_row} 行）')
    finally:
        wb.close()
    return f'子表 {len(rows)} · 合计约 {total} 行', rows, total, ''


def make_rows(materials):
    """材料层 → 侦查行（**先不判断**：难度 / 规模 / 建议由 run 填）。"""
    return [{'id': m.get('id'), 'path': m.get('path'), 'tier': m.get('tier', '?'),
             'status': m.get('status', '?'), 'bytes': m.get('bytes', 0),
             'mtime': m.get('mtime', ''), 'diff': '', 'vol': 0,
             'scale': '', 'structure': [], 'advice': ''} for m in materials]


def advise(row):
    """机器建议处置（§1.5 的"处置三选一"）：**只看档位与内容量**，不做语义判断。"""
    suf = Path(row['path'] or '').suffix.lower()
    if row['status'] != 'ok' or row['tier'] == 'T4':
        return '不参与（读不动，记 T4 + 理由）'
    if row['tier'] == 'T3' or suf in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff', '.webp'):
        return '需视觉（多模态 / OCR）；自包含侧暂不可用'
    if suf in ('.doc', '.xls', '.ppt', '.wps', '.et', '.dps'):
        return '需转换器（soffice）或请用户另存为 OOXML'
    if suf == '.pdf':
        return '需 PDF 文本抽取（自包含可做，见 §1.4 依赖清单）'
    if row['diff'] == '中':
        return '只取摘要（超阈值：先结构缩样再定，**不灌满账本**）'
    return '全量解析'


def render(rows):
    """侦查结论表草稿（markdown）：机器列已填，**假设角色留给 AI**（§1.5 要求落盘）。"""
    lines = ['| # | 材料 | 档位 | 难度 | 规模 | 结构缩样 | 机器建议处置 | 假设角色（AI 填 `⚠`） |',
             '|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(rows, 1):
        struct = r['scale'] or '—'
        if r['structure']:
            head = ' / '.join(r['structure'][:3])
            more = f' …（共 {len(r["structure"])}）' if len(r['structure']) > 3 else ''
            struct = f'{struct}｜{head}{more}'
        lines.append(f'| {i} | `{r["id"]}` {Path(r["path"] or "").name} | {r["tier"]} | {r["diff"]} | '
                     f'{r["bytes"]} B | {struct} | {r["advice"] or advise(r)} |  |')
    return '\n'.join(lines) + '\n'


def run(materials, easy_max, outline_max, sample_rows, sample_cols):
    """结构缩样 → 算难度 → 排序 → 填建议 → `(rows, 跳过清单, 报错文案)`。

    **顺序不可换**：难度排序要用"内容量"，而内容量只能从结构缩样来（§1.5 第 2、3 步）。
    阈值的单位：docx 是"正文块 + 表格"，xlsx 是"合计行"—都是**内容量的近似**，够用且可复现。
    """
    rows = make_rows(materials)
    for r in rows:
        if r['status'] != 'ok' or r['tier'] != 'T1':
            continue
        path = Path(r['path'] or '')
        if path.suffix.lower() == '.docx':
            r['scale'], r['structure'], r['vol'], err = _scale_docx(path, outline_max)
        elif path.suffix.lower() == '.xlsx':
            r['scale'], r['structure'], r['vol'], err = _scale_xlsx(path, sample_rows, sample_cols)
        else:
            err = ''
        if err:
            return None, [], err
    for r in rows:
        if r['status'] != 'ok':
            r['diff'] = '不参与'
        elif r['tier'] == 'T1':
            r['diff'] = '易' if r['vol'] <= easy_max else '中'
        else:
            r['diff'] = DIFF.get(r['tier'], '不参与')
        r['advice'] = advise(r)
    order = {'易': 0, '中': 1, '难': 2, '最难': 3, '不参与': 4}
    rows.sort(key=lambda r: (order.get(r['diff'], 9), r['vol'], r['bytes'], r['path'] or ''))
    return rows, [], ''


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='侦查器：难度排序 + 结构缩样 + 结论表草稿')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout）')
    ap.add_argument('--easy-max', type=int, default=500, help='T1 里"易"的 element 规模参考线（默认 500）')
    ap.add_argument('--outline-max', type=int, default=20, help='每份 docx 最多取多少条大纲')
    ap.add_argument('--sample-rows', type=int, default=5, help='xlsx 采样行数（当前版本只读尺寸）')
    ap.add_argument('--sample-cols', type=int, default=10, help='xlsx 采样列数')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    rows, skipped, err = run(materials, a.easy_max, a.outline_max, a.sample_rows, a.sample_cols)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2

    text = render(rows)
    if a.out:
        Path(a.out).write_bytes(text.encode('utf-8'))
        where = a.out
    else:
        sys.stdout.write(text)
        where = 'stdout'
    counts = {}
    for r in rows:
        counts[r['diff']] = counts.get(r['diff'], 0) + 1
    print('→ 侦查表已写出 ' + where + '：' + ' · '.join(f'{k} {v}' for k, v in counts.items())
          + '（**假设角色 / 含流程 = AI 填，脚本不猜**）', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
