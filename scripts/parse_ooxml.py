# -*- coding: utf-8 -*-
r"""parse_ooxml.py — OOXML 解析适配器（PIPELINE-SPEC §1.4）：`.docx` / `.xlsx` / `.pptx` → `elements[]`。

**自包含优先**：`.docx` 用 `python-docx`、`.xlsx` 用 `openpyxl`（`requirements.txt` 里声明的**必须**依赖）；
**`.pptx` 零依赖**——它是 zip，正文在 `ppt/slides/slideN.xml` 的 `<a:t>` 里，取文字的活由公共层的
`pptx_text` 干（与 `recon` 的摘要**同一句判据**，免得"摘要里看得见、撬开却找不到"）。
宿主 Office SDK / 多模态模型是**加速器**，不属于本脚本（探测到才用的那部分在 spec §1.4）。

**协作走产物**（本仓分层纪律：模块层之间不许互相 import）：本脚本读 `probe.py --json` 的材料层，
产出元素层 JSON，再交给 `ledger.py` — 三段串起来是 `probe → parse_ooxml → ledger`；
`--notes` 另写**材料层补注**（`extractor` 这类"走了哪条路"的记账，§2.1）。

三条边界：**只读材料**（不改、不动）；**不做语义判断**（不猜流程、不合并节点）；
**抽不出不猜**（跳过并记账，不伪造空 element）。

退出码：0 = 完成（可能有跳过）；2 = **缺依赖** 或输入读不了（缺依赖报可执行的错，不静默降级）。
"""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

from pptx_text import other_text_parts, slides
import deps
import semantics

# **函数顺序按调用方向排**（助手紧跟调用者，CLI 压尾）：自举表是**单列函数流**，一条跨十个节点的
# 调用边会把门⑨ 的绕行读数顶上去（G12）。实测：加 `parse_pptx` 后本模块绕行 66%（超 60% 阈值），
# 按调用方向重排后 33%——**顺序是布局的输入**，改函数位置前先跑 `dev/tools/aesthetic.py`。

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

def parse_docx(blob, path, mid):
    """`.docx` **字节** → `(elements, 报错文案)`。样式名判 heading / list_item（判不出就当 paragraph）。

    收字节而不是收路径，是为了**不让扩展名投票**：`python-docx` 打开 zip 时不看后缀，但
    `openpyxl` 会（见 `parse_xlsx`）——两者都改成从内存读，材料叫什么名字就不影响能不能读
    （§1.2"按内容，不按扩展名"要贯彻到**读者**这一步，不能只在探测那一步）。
    """
    docx, err = deps.import_dep('docx')
    if err:
        return None, err
    out, seq = [], {'h': 0, 'l': 0, 'p': 0, 't': 0}
    for tag, obj in _docx_body(docx.Document(io.BytesIO(blob))):
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

def parse_xlsx(blob, path, mid, max_rows, max_cols, sheet='', rows_span=None):
    """`.xlsx` **字节** → `(elements, 报错文案)`。**一张 sheet 一个 element**（`rows` 承载内容，§2.1）。

    超上限就截断并标 `degraded`（§2.4 降级必须记账）—大表（实测有 72 万字符的测算表）靠这条不炸账本。
    `sheet=` / `rows_span=` 是 `--sheet` / `--rows` 的收窄：**只要一张子表、只要其中几行**——
    一张十万行的"计算器"表，侦查说「只取摘要」时靠它落地（同样逐条记 `degraded`）。
    **从内存打开（`BytesIO`）**：`openpyxl.load_workbook` 收路径时**按扩展名投票**——审计实测
    "合法 xlsx 改名 `.et`" 会被它 `InvalidFileException` 拒绝，于是没人认领、整条链判漏认退 1。
    内容对就该读得动，名字不该决定这件事。
    """
    openpyxl, err = deps.import_dep('openpyxl')
    if err:
        return None, err
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    out, empty_sheets = [], []
    try:
        for n, ws in enumerate(wb.worksheets, 1):
            if sheet and ws.title != sheet:
                continue
            rows, cut = [], False
            for i, row in enumerate(ws.iter_rows(values_only=True), 1):
                if rows_span and not (rows_span[0] <= i <= rows_span[1]):
                    continue
                if len(rows) >= max_rows:
                    cut = True
                    break
                if len(row) > max_cols:
                    cut = True
                vals = ['' if v is None else str(v) for v in row[:max_cols]]
                if any(vals):
                    rows.append(vals)
            if not rows:
                # **空 sheet 不交空骨架**（G31）：`rows: []` 的 element 是"认出了杯子、杯子是空的"，
                # 而账本要的是"倒了多少水"——空 element 会变成零证据的证据（§1.3 空骨架不许过）。
                # 丢条数由材料级说明报（与"没抽出文字"同一档），不静默。
                empty_sheets.append(ws.title)
                continue
            el = {'id': f'{mid}#s{n:03d}', 'material_id': mid, 'kind': 'sheet',
                  'text': ws.title, 'rows': rows,
                  'location': {'path': path.as_posix(), 'sheet': ws.title},
                  'extractor': 'py:openpyxl', 'certainty': 'direct'}
            note = '；'.join(x for x in (
                f'超上限截断（行 > {max_rows} 或列 > {max_cols}）' if cut else '',
                f'本轮 --rows 只要第 {rows_span[0]}–{rows_span[1]} 行' if rows_span else '',
                f'本轮 --sheet 只要「{sheet}」' if sheet else '') if x)
            if note:
                el['degraded'] = note
            out.append(el)
    finally:
        wb.close()
    if empty_sheets:
        # 丢条数要说出来（G31）：与"超上限截断"同一档的材料级说明，挂到**抽到的每条**上——
        # 整份全空时 out 为空，这条说明随"零证据"进调用方的记账分支。
        tell = (f'丢掉 {len(empty_sheets)} 张空表'
                f'（{"、".join(empty_sheets[:3])}{"…" if len(empty_sheets) > 3 else ""}）：'
                f'空表不交空骨架（§1.3）')
        for el in out:
            el['degraded'] = (el['degraded'] + '；' if el.get('degraded') else '') + tell
    return out, ''

def _span(spec):
    """范围语法 → `(起, 止)`；**语法与校验只有一处**（`semantics.parse_span`，D-122）。"""
    return semantics.parse_span(spec, '范围', '行/张')


def parse_pptx(blob, path, mid, max_slides, slides_span=None):
    """`.pptx` **字节** → `(elements, 报错文案)`。**一张幻灯片一个 element**（零依赖，见 `pptx_text`）。

    **一张一个**（而不是一页拆成标题 + 若干段落）：幻灯片是"一屏一屏"读的，页码就是它天然的坐标，
    所以 `location.page` = 幻灯片序号——于是 `query.py --range pages=40-60` 对 PPT 也成立
    （§5.3 的取子集语法**不为格式分叉**）。
    超上限先记账（`degraded` 写在**抽到的每条**上，与 `parse_pdf` 同一套做法）：不吭声地少几页，
    下游只会以为"这份材料本来就这么点内容"（§2.4）。
    """
    got, failed = slides(blob, max_slides)
    if slides_span:                                  # `--slides`：只要这几张（收窄，逐条记账）
        got = [(n, lines) for n, lines in got if slides_span[0] <= n <= slides_span[1]]
    blank = [n for n, lines in got if not lines]     # **纯图片页**：没有 `<a:t>`，抽出来就是空
    got = [(n, lines) for n, lines in got if lines]
    if not got and not failed:
        return [], ''                                 # 真空稿：**由调用方统一记"没抽出文字"**，不当致命错
    out, cut = [], []
    for n, lines in got:
        text = ' / '.join(lines)
        el = {'id': f'{mid}#p{n:03d}', 'material_id': mid, 'kind': 'paragraph',
              'text': text, 'location': {'path': path.as_posix(), 'page': n, 'quote': text},
              'extractor': 'py:pptx', 'certainty': 'direct'}
        out.append(el)
    # **没读到的部件要说出来**：幻灯片之外的文字（图表 / SmartArt / 备注页）不在账本里，
    # 静默漏掉是 §2.4 明令不许的。这里只记账、不读（读它们要连带解决"属于哪一页"，见 G14）。
    others = other_text_parts(blob)
    if others:
        cut.append('另有含文字的部件**本读者不读**（' + ' · '.join(f'{k} {v}' for k, v in others.items())
                   + '）：那几处的文字不在账本里')
    if failed:
        # **读不动的页要报出来**（原先是两个方向都错：别的异常穿透出去把整份判成读不动、
        # 或 CRC 坏的页被静默吞掉）。这里逐页记名 + 原因，挂到**留下的每条**上。
        cut.append(f'{len(failed)} 张幻灯片读不动（第 '
                   + '、'.join(f'{n}（{why}）' for n, _name, why, _msg in failed[:5])
                   + '）：那几页的内容不在账本里')
    if blank:
        # **空元素不是证据**（实测真稿：19 张里有 3 张是纯图片，原先被抽成 `text: ""` 的 element，
        # 既占着账本、又让"19 张都进来了"这句话变成假的）。丢掉它们，并把这件事挂到**留下的每条**上：
        # 那几页的内容**确实没进账本**，要它得走视觉（`render_pages`）——这正是 §1.3 那条路。
        cut.append(f'{len(blank)} 张幻灯片没有文字层（第 {"、".join(str(n) for n in blank)} 张，纯图片）：'
                   f'那几页的内容不在账本里，要它得走视觉（render_pages）')
    if slides_span:
        cut.append(f'本轮 --slides 只要第 {slides_span[0]}–{slides_span[1]} 张')
    if max_slides and len(got) + len(blank) >= max_slides:
        cut.append(f'只取前 {max_slides} 张（按序号）')
    note = '；'.join(cut)
    if note:
        for e in out:
            e['degraded'] = note
    return out, ''

def container_kind(blob):
    """PK 容器的**字节** → `'docx'` / `'xlsx'` / `'pptx'`；不是 OOXML 返回 None。

    判据与 `probe._ooxml_kind` **同一句**（都认 `word/document.xml` / `xl/workbook.xml` / `ppt/presentation.xml`）——
    审计抓到过精度不一致的后果：probe 按目录前缀判、这里按确切部件判，于是"有 word/ 没 document.xml"
    的包被判 T1 可直读却没人认领，整条链判"漏认"退 1。**探测与读者的射程必须对齐。**
    """
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = set(z.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if 'word/document.xml' in names:
        return 'docx'
    if 'xl/workbook.xml' in names:
        return 'xlsx'
    if 'ppt/presentation.xml' in names:
        return 'pptx'
    return None

def parse_materials(materials, max_rows, max_cols, max_slides, sheet='', rows_span=None,
                    slides_span=None):
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
        try:
            blob = path.read_bytes()
        except OSError as e:
            skipped.append(f'{mid}: 读不动（{type(e).__name__}）')
            continue
        kind = container_kind(blob)
        if kind is None:
            skipped.append(f'{mid}: 不是 OOXML（tier={m.get("tier")}）')
            continue
        try:
            if kind == 'docx':
                got, err = parse_docx(blob, path, mid)
            elif kind == 'xlsx':
                got, err = parse_xlsx(blob, path, mid, max_rows, max_cols, sheet, rows_span)
            else:
                got, err = parse_pptx(blob, path, mid, max_slides, slides_span)
        except Exception as e:                       # 单份坏不让整批失败（§1.4 硬要求 2）
            skipped.append(f'{mid}: 解析失败 {type(e).__name__}: {e}')
            # **容器认出来了、正文却是坏的 ⇒ 必须补注读不动**：不然它在账本上就是
            # "status=ok 却零证据"，分派器当场判漏认、整条链退 1（夹具实测：垃圾 xlsx / 垃圾 docx）。
            notes.append({'material_id': mid, 'status': 'unreadable',
                          'reason': f'{kind} 容器的内容坏了（{type(e).__name__}: {str(e)[:70]}）'
                                    f'——重新导出，或另存为 .docx / .xlsx'})
            continue
        if err:
            return None, notes, done, skipped, err
        if not got:
            if slides_span or rows_span or sheet:
                # **收窄读空 ≠ 材料是空的**（审计实测：原先一律记 `unreadable`「空文档 / 只有图片」，
                # 下一轮 AI 会照这条把好材料判死；`--slides` 越界与 `--sheet` 不存在都落这里）。
                what = '、'.join(x for x in (
                    f'--slides {slides_span[0]}-{slides_span[1]}' if slides_span else '',
                    f'--rows {rows_span[0]}-{rows_span[1]}' if rows_span else '',
                    f'--sheet {sheet}' if sheet else '') if x)
                notes.append({'material_id': mid, 'status': 'skipped',
                              'reason': f'本轮收窄未取：`{what}` 在这一份里没命中任何内容'
                                        f'（不是读不动，也不是材料为空）'})
                skipped.append(f'{mid}: {what} 未命中')
                continue
            notes.append({'material_id': mid, 'status': 'unreadable',
                          'reason': f'{kind} 里没抽出任何文字（空文档 / 只有图片）——'
                                    f'确属空材料就写进清点，别让它悬着'})
            skipped.append(f'{mid}: 抽出 0 条')
            continue
        elements += got
        done.append(f'{mid}({kind}) {len(got)}')
        notes.append({'material_id': mid, 'extractor': f'py:{kind}'})
    return elements, notes, done, skipped, ''

def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def _write_notes(notes, path):
    """写材料层补注：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`）。"""
    Path(path).write_bytes((json.dumps(notes, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))

def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')  # 摘要/报错走 stderr，同样要定编码（GBK 控制台会乱码）
    ap = argparse.ArgumentParser(description='OOXML 解析适配器：.docx / .xlsx / .pptx → elements[]')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--notes', help='材料层补注写到哪里（status / reason / extractor，交给 ledger.py --notes）')
    ap.add_argument('--max-rows', type=int, default=200, help='每张 sheet 的行上限（超了记 degraded）')
    ap.add_argument('--max-cols', type=int, default=50, help='每张 sheet 的列上限')
    ap.add_argument('--max-slides', type=int, default=200, help='pptx 最多读多少张幻灯片（超了记 degraded）')
    ap.add_argument('--slides', help='pptx 只要这几张（A-B，1 起）；收窄逐条记 degraded')
    ap.add_argument('--sheet', default='', help='xlsx 只要这个子表（逐字相等）')
    ap.add_argument('--rows', help='xlsx 每张子表只要这几行（A-B，1 起）')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2
    try:                                             # 范围写歪 ⇒ 退 2 说人话（不许静默按全量走）
        rows_span, slides_span = _span(a.rows), _span(a.slides)
    except ValueError as e:
        print(f'⚠ {e}', file=sys.stderr)
        return 2

    elements, notes, done, skipped, err = parse_materials(materials, a.max_rows, a.max_cols,
                                                          a.max_slides, a.sheet,
                                                          rows_span, slides_span)
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
