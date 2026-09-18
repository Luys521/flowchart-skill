# -*- coding: utf-8 -*-
r"""recon.py — 侦查器（PIPELINE-SPEC §1.5）：难度排序 + **结构缩样** + 侦查结论表（机器列已填，假设列留 AI）。

**读什么、信什么**：只读 `probe.py --json` 的 `materials[]`，**按 `kind` 与 `tier` 分派**。
**不按扩展名**——2026-09-18 的四路审计实测：同一份字节内容改个文件名就会得到两种互相矛盾的结论
（真 docx 改名 `.doc` → 这里建议"调 soffice 转换"，而 probe 按内容判的是"T1 可直读"）；
"这是什么"的**唯一判据源是 `probe`**（`kind` 字段），本节第一条理由就是"按内容，不按扩展名"。

**两列分开，别混一个轴**（审计：原先"机器建议处置"把两个问题塞进一格，下游无法机械消费）：
- `解析深度` = §1.5 的处置三选一：`全量解析` / `只取摘要` / `不参与`；
- `走哪条路` = §1.1 的档位映射：`直读` / `文本直读` / `PDF 文本抽取` / `转换器(soffice)` /
  `转图片→视觉` / `无 reader：T4 + 提示`。

**难度与规模**：
- **分档用 `bytes`**（跨格式可比、且不依赖任何库、不会因为"这份表读不动"而失真）；
- **结构缩样是尽力而为的参考数字**，读不出就写"结构读不了 + 原因"，
  **绝不让它决定分档、也绝不让它把整批带崩**——审计实测：一份坏材料曾让 15 份零产出、裸栈退 1。
- 阈值住 `dictionary.yaml` 的 `recon:` 段（**数值只有一个家**，§1.2）；产物表头打印**本次用的阈值与
  输入指纹**（不然"共 20"这种歧义事后没法复核）。

**产物与落点**：`-o` 默认 `recon.md`（落**成果根**；名字登记在 `artifact.NON_TABLE_MD`，
否则会被 `layer_index` 判"孤儿表"）。表列 = §1.5 要求的
`材料|假设角色|依据|档位|验证方式|状态`，机器侧另加 `难度|规模|解析深度|走哪条路|读不动`。
**"建议处置"落在这里、不进材料卡片**（§3 的卡片是标注层，只装事实与推断，不装过程性建议）。

`check` 子命令校验 AI 填的那几列（§1.5："假设必须落盘、**被推翻也要留痕**"）：

    python scripts/recon.py build --materials materials.json        # 出草稿（默认 recon.md）
    python scripts/recon.py check recon.md --materials materials.json

退出码：0 = 完成（个别材料结构读不了**不影响整批**，逐份记在「结构缩样」列）；
1 = `check` 发现 AI 填的列不合规；2 = 输入读不了 / 缺依赖。
"""
import argparse
import hashlib
import importlib
import io
import json
import re
import sys
from pathlib import Path

from pptx_text import slides

DEP_PKG = {'docx': 'python-docx', 'openpyxl': 'openpyxl'}

# 难度序（§1.1）：T1 可直读 < T2 需转换器 < T3 需视觉；"不参与"排最后。
# 一张表定死**标签 → 序号**，难度标签与排序键都从它派生（原先分三处各写一份，漏登记就静默垫底）。
DIFF_ORDER = {'易': 0, '中': 1, '难': 2, '最难': 3, '不参与': 4}
DIFF_OF_TIER = {'T1': '易', 'T2': '难', 'T3': '最难'}
DEPTH_FULL, DEPTH_SUMMARY, DEPTH_SKIP = '全量解析', '只取摘要', '不参与'

# 走哪条路：**按 `kind` 查表**（不按扩展名）。`kind` 是 probe 判的（§2.1 封闭枚举）。
PATH_OF_KIND = {
    'docx': '直读（py:docx）',
    'xlsx': '直读（py:openpyxl）',
    'text': '文本直读（py:text）',
    'pdf-text': 'PDF 文本抽取（py:pdfplumber）',
    'pdf-scan': '转图片 → 视觉（render_pages）',
    'image': '转图片 → 视觉（原文件即图片）',
    'ole': '转换器（soffice）或请用户另存为 OOXML',
    'pptx': '直读（py:pptx，零依赖 zip+XML）',
    'unknown': 'T4：读不动（见「读不动」列的原因）',
}
# T1 里"有 reader"的那几种：T1 却不在其中 = **探测说谎**（§1.2 的不变式），老实报出来而不是硬编建议。
T1_WITH_READER = ('docx', 'xlsx', 'pptx', 'text')

DEFAULTS = {                     # 兜底值；`dictionary.yaml` 的 `recon:` 段按名覆盖（数值只有一个家）
    'easy_max_bytes': 1048576,   # 超过它 → 建议"只取摘要"（默认 1 MiB：一个**人给的**圆整默认，不是从样本反推）
    'max_open_bytes': 33554432,  # 超过它**不打开**结构（只记元数据）：防一份 500MB 的 docx 把内存吃光
    'outline_max': 50,           # 大纲最多数多少条（先数后切，表里写"共 K（列前 N）"）
    'outline_show': 3,           # 表里露几条
}
DICT_NAME = 'dictionary.yaml'


def _import_dep(name):
    """import 一个必须依赖 → `(模块, 报错文案)`（缺了给可执行的提示）。"""
    try:
        return importlib.import_module(name), ''
    except ImportError:
        pkg = DEP_PKG[name]
        return None, f'缺依赖 {pkg}：装 `python -m pip install {pkg}`（或 `pip install -r requirements.txt`）'

def _docx_scale(blob, th):
    """`.docx` 字节 → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**只读结构，不物化全部文字**。

    规模 = **非空段数 + 表数**（审计 F2：原先数的是 body 子元素，把 `tbl` 算了两次、还把尾部 `sectPr`
    算成一个块 —— 量与名字不对应，人没法复核）；大纲**先数完再切**，表里写"共 K（列前 N）"，
    不许把截断后的条数写成"共 N"（那等于谎报结构数字，§2.3 同一纪律）。
    """
    docx, err = _import_dep('docx')
    if err:
        return '', [], 0, err
    doc = docx.Document(io.BytesIO(blob))
    paras = sum(1 for p in doc.paragraphs if (p.text or '').strip())
    heads = [f'{(p.style.name or "")}: {(p.text or "").strip()}' for p in doc.paragraphs
             if (p.text or '').strip() and _is_heading(p)]
    return (f'非空段 {paras} · 表格 {len(doc.tables)}', heads[:th['outline_max']], len(heads), '')

def _is_heading(p):
    """样式名判标题（与 `parse_ooxml` 同一句判据；两边都只认 `heading` 前缀）。"""
    try:
        return (p.style.name or '').lower().startswith('heading')
    except Exception:                                # 样式表坏了的文档：判不出就当正文（不猜）
        return False

def _xlsx_scale(blob, th):
    """`.xlsx` 字节 → `(规模描述, 子表行, 子表数, 结构说明)`。用尺寸信息读规模，**不扫单元格**。

    **无 `<dimension>` 的工作表要能活**（审计 R2：`openpyxl` 的 write-only / 第三方导出常没有这个标签，
    原实现直接抛 `Worksheet is unsized` 把整批带崩）：抛了就记"尺寸不可知"，**不让它决定分档**。
    """
    openpyxl, err = _import_dep('openpyxl')
    if err:
        return '', [], 0, err
    wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    rows, total, unknown = [], 0, 0
    try:
        for ws in wb.worksheets:
            try:
                dim = ws.calculate_dimension()       # 例 'A1:P123'
            except Exception:                        # 没有 dimension 标签：**记不可知**，不当失败
                dim, unknown = '尺寸不可知', unknown + 1
            m = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', dim or '')
            n_row = int(m.group(4)) if m else 0
            total += n_row
            rows.append(f'{ws.title}：{dim}' + (f'（{n_row} 行）' if n_row else ''))
    finally:
        wb.close()
    scale = f'子表 {len(rows)} · 声明合计约 {total} 行' + (f'｜{unknown} 张尺寸不可知' if unknown else '')
    return scale, rows, len(rows), ''

def _pptx_scale(blob, th):
    """`.pptx` 字节 → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**这就是那份".pptx 解析摘要"**。

    为什么它值得单独做到位（用户的真实工作方式）：一份几十上百张的演示稿，**先扫摘要看有没有线索**
    （哪一页在讲审批 / 讲分工），再决定要不要点名撬开那几页（§5.3）。没有摘要，那份材料在 AI 眼里
    就等于不存在——它体积最大、却一个字都进不来。
    取文字用公共层 `pptx_text`（与 `parse_ooxml` 的读者**同一句判据**，免得"摘要里看得见、撬开找不到"）。
    """
    got = slides(blob, th['outline_max'])            # 只读前面若干张就够当摘要；读不动返回空
    if not got:
        return '', [], 0, 'pptx 里没抽出文字（空稿 / 全是图）'
    heads = [f'第 {n} 张：{lines[0]}' if lines else f'第 {n} 张：（无文字）' for n, lines in got]
    return f'幻灯片 {len(got)} 张（按序号读前 {th["outline_max"]} 张取标题）', heads, len(got), ''

def _pdf_scale(blob, th):
    """`.pdf` 字节 → `(规模描述, 大纲行, 大纲总条数, 结构说明)`。**零依赖粗数页数**。

    为什么粗数就够：侦查要的是"这份 PDF 值不值得读、要不要只取摘要"（§1.5 的分档只看 `bytes`，
    页数只是**参考数字**）。所以不引 `pdfplumber` 来数——那会把"扫一眼"变成"跑一遍解析"。
    判据是 `/Type /Page` 的出现次数（**不含** `/Pages`，故用负向断言）：导出器花样多，实测偏小是常事，
    所以文案写"**约** N 页"，不假装精确；一个都没数到时说清"页数数不出来"，不写 0（0 会被当成"空文件"）。
    """
    n = len(re.findall(rb'/Type\s*/Page(?![s])', blob))
    if not n:
        return '', [], 0, 'PDF 页数数不出来（结构非标准 / 被压缩）——按体积与档位看即可'
    return f'约 {n} 页（粗数，仅供参考）', [], 0, ''

def _text_scale(blob, th):
    """纯文本 / CSV 字节 → 规模。**行数 + 头几行的开头**——这是文本档唯一有意义的"结构"。

    **不猜编码**（与 `parse_text` 同一条纪律，§1.4）：只认 UTF-8（含 BOM）；解不开就说清
    "编码不是 UTF-8，摘要不可得"并给出下一步（解析时显式 `--encoding`），**不许拿 GBK 硬解出一堆乱码当摘要**——
    那种"摘要"比没有更坏：它会让人以为材料内容就是乱码。
    """
    try:
        text = blob.decode('utf-8-sig')
    except UnicodeDecodeError:
        return '', [], 0, '编码不是 UTF-8（摘要不可得）：解析时按 §1.4 显式给 `--encoding`，或先转成 UTF-8'
    lines = text.splitlines()
    heads = [f'第 {i} 行：{ln.strip()[:60]}' for i, ln in enumerate(lines[:th['outline_max']], 1)
             if ln.strip()]
    return f'行 {len(lines)}', heads, len(heads), ''

def _image_scale(blob, th):
    """图片字节 → `尺寸（像素）`。**Pillow 是可选加速器**：缺了就说清，不硬造数字。"""
    try:
        from PIL import Image
    except ImportError:
        return '', [], 0, '缺 Pillow（读不出图片尺寸）：`python -m pip install Pillow`'
    try:
        with Image.open(io.BytesIO(blob)) as im:
            return f'{im.width}×{im.height} 像素 · {im.format or "?"}', [], 0, ''
    except Exception as e:                           # 图片坏了：记事实，不外溢
        return '', [], 0, f'图片读不出尺寸（{type(e).__name__}）'

def _ole_note():
    """legacy（OLE 复合文档）**没有摘要可给**——这是诚实的极限，不是没做。

    流式读 OLE 里的 Word/Excel 正文等于重写一个解析器（§1.4 明确"没有纯 Python 的可靠读法"），
    所以侦查对它只能给"**走哪条路**"（外部转换器）与"读不动 + 可执行提示"，两条都已在表里。
    这里返回一句说明，好过留一个空格子让人以为"忘了做"。
    """
    return '', [], 0, 'legacy（OLE）：摘要不可得——正文要外部转换器，见「走哪条路」列'

def _note_of(e):
    """异常 → 记在表里的说明。**把"材料的问题"与"我们自己的 bug"分开**：

    逐份 `try/except` 是硬要求（§1.4：一份坏材料不许把整批带崩），但它有个副作用——
    **自己的编程错误也会被伪装成"材料读不了"**（本轮就踩到：一个 `NameError` 被记成了
    "结构读不了"，看起来像材料的问题）。`NameError` / `AttributeError` / `TypeError` 这几类
    几乎不可能是材料造成的，所以显式标成"疑似本工具 bug"，让它在表里刺眼。
    """
    bug = isinstance(e, (NameError, AttributeError, TypeError))
    head = '**疑似本工具 bug（请报）**' if bug else '结构读不了'
    return f'{head}（{type(e).__name__}: {str(e)[:60]}）'


# 有"结构缩样"的 kind：**这份清单只在这里写一次**（`sample_structure` 的分支与 `make_rows` 的开门判据都从它取）。
# 审计教训（2026-09-18 实测踩到）：原先 `make_rows` 里另写了一份 `('docx','xlsx')`，于是给
# `sample_structure` 补上 pptx 之后，**摘要照样是空的**——"支持了"与"用上了"之间隔着一份重复的清单。
# 覆盖面（2026-09-18 收官）：**每一种 kind 都有交代**——能缩样的缩样，缩不了的**说清为什么**
# （`ole` 是诚实的极限；`unknown` 在探测那一步就已经记了读不动原因）。
SCALED_KINDS = ('docx', 'xlsx', 'pptx', 'pdf-text', 'pdf-scan', 'image', 'text', 'ole')

def sample_structure(blob, kind, th):
    """按 `kind` 缩样 → `(规模描述, 结构行, 结构总条数, 说明)`。**读不了不是错**：返回说明，逐份记账。"""
    if kind == 'unknown':
        return '', [], 0, ''
    try:
        if kind == 'docx':
            return _docx_scale(blob, th)
        if kind == 'xlsx':
            return _xlsx_scale(blob, th)
        if kind == 'pptx':
            return _pptx_scale(blob, th)
        if kind in ('pdf-text', 'pdf-scan'):
            return _pdf_scale(blob, th)
        if kind == 'image':
            return _image_scale(blob, th)
        if kind == 'text':
            return _text_scale(blob, th)
        if kind == 'ole':
            return _ole_note()
    except Exception as e:                           # 单份坏不让整批失败（§1.4 硬要求 2）
        return '', [], 0, _note_of(e)
    return '', [], 0, ''


# ----------------------------------------------------------------分档与建议（纯查表，不猜）

def difficulty(row, th):
    """难度：不参与 / 易 / 中 / 难 / 最难。**分档只看 `bytes` 与 `tier`**（kind 只影响"走哪条路"）。"""
    if row['status'] != 'ok' or row['tier'] == 'T4':
        return '不参与'
    base = DIFF_OF_TIER.get(row['tier'], '不参与')
    if base == '易' and row['bytes'] > th['easy_max_bytes']:
        return '中'                                  # T1 但体积大 → 别一上来就全量灌（§2.4）
    return base

def advise_depth(row):
    """解析深度（§1.5 三选一）+ 触发它的数字。**事实与建议要能分开看**：数字随后写进「规模」列。

    **判据是体积，不是档位**（2026-09-18 修）：原先只有"T1 但很大"才降成「只取摘要」，
    于是 T2/T3 走另一条路——一份 50MB 的 legacy 也会被建议"全量解析"，那等于**一上来就全量灌**
    （§2.4 明令不许）。档位说的是"走哪条路"，体积说的才是"读多少"，两个轴不该互相顶替。
    """
    if row['diff'] == '不参与':
        return DEPTH_SKIP
    if row['tier'] == 'T1' and row['kind'] not in T1_WITH_READER:
        return '未定（probe 判 T1 但没有对应 reader —— 属探测说谎，先修 probe）'
    return DEPTH_SUMMARY if row['bytes'] > row['full_max_bytes'] else DEPTH_FULL

def advise_path(row):
    """走哪条路（§1.1 档位映射）：**按 `kind` 查表**，不看扩展名（审计 F3/F6）。"""
    if row['status'] != 'ok':
        return '不解析（status=%s）' % row['status']
    return PATH_OF_KIND.get(row['kind'], '未定（kind 不在封闭枚举内）')

def make_rows(materials, th):
    """材料层 → 侦查行 + 跳过清单。**逐份尽力而为**：结构读不了记在行里，绝不外溢成整批失败。"""
    rows, skipped = [], []
    for m in materials:
        row = {'id': m.get('id', '?'), 'path': m.get('path', ''), 'tier': m.get('tier', '?'),
               'kind': m.get('kind', '?'), 'status': m.get('status', '?'),
               'bytes': m.get('bytes', 0), 'mtime': m.get('mtime', ''),
               'probe': m.get('probe', ''), 'reason': m.get('reason', ''),
               'full_max_bytes': th['easy_max_bytes'],      # 阈值随行带（数值仍只有 dictionary.yaml 一个家）
               'scale': '', 'structure': [], 'structure_total': 0, 'note': ''}
        row['diff'] = difficulty(row, th)
        if row['status'] == 'ok' and row['kind'] in SCALED_KINDS:
            if row['bytes'] > th['max_open_bytes']:
                skipped.append(f"{row['id']}: {row['bytes']} 字节超护栏（{th['max_open_bytes']}），"
                               f'只记元数据不打开结构')
            else:
                try:
                    blob = Path(row['path']).read_bytes()
                except OSError as e:
                    skipped.append(f"{row['id']}: 读不动（{type(e).__name__}）")
                    blob = None
                if blob is not None:
                    (row['scale'], row['structure'],
                     row['structure_total'], row['note']) = sample_structure(blob, row['kind'], th)
                    if row['note']:
                        skipped.append(f"{row['id']}: {row['note']}")
        rows.append(row)
    rows.sort(key=lambda r: (DIFF_ORDER.get(r['diff'], 9), r['bytes'], r['path']))
    return rows, skipped


# ----------------------------------------------------------------渲染与校验

def render(rows, meta):
    """侦查结论表（markdown）。**表头先写输入指纹与阈值**——不然"共 20"这类数字事后没法复核。"""
    lines = [f'> 由 `scripts/recon.py` 从 `{meta["input"]}`（sha256 {meta["sha256"][:12]}）生成：'
             f'机器列已填，**假设角色 / 依据 / 验证方式 / 状态 留给 AI**（§1.5）。',
             f'> 本次阈值：`easy_max_bytes={meta["easy_max_bytes"]}`（超过它 → 只取摘要）· '
             f'`max_open_bytes={meta["max_open_bytes"]}`（超过它不打开结构）· '
             f'`outline_max={meta["outline_max"]}`。改阈值请改 `dictionary.yaml` 的 `recon:` 段。', '',
             '| 材料 | 档位 | 修改时间 | 难度 | 规模（依据数字） | 解析深度 | 走哪条路 | 读不动 | '
             '假设角色（AI 填 `⚠`） | 依据（AI 填） | 验证方式（AI 填） | 状态（AI 填） |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        struct = r['scale'] or ('—' if not r['note'] else r['note'])
        if r['structure']:
            head = ' / '.join(r['structure'][:3])
            more = f' …（共 {r["structure_total"]}）' if r['structure_total'] > 3 else ''
            struct = f'{struct}｜{head}{more}'
        lines.append(f'| `{r["id"]}` {Path(r["path"] or "").name} | {r["tier"]} | '
                     f'{r["mtime"] or "—"} | {r["diff"]} | '
                     f'{struct} | {advise_depth(r)} | {advise_path(r)} | '
                     f'{r["reason"] or "—"} |  |  |  |  |')
    return '\n'.join(lines) + '\n'


CARD_COLUMNS = ('材料', '档位', '修改时间', '难度', '规模（依据数字）', '解析深度', '走哪条路', '读不动',
                '假设角色（AI 填 `⚠`）', '依据（AI 填）', '验证方式（AI 填）', '状态（AI 填）')
STATUSES = ('待验', '已验证', '已推翻')
MD_ID = re.compile(r'`(M\d+)`')

def parse_table(text):
    """`recon.md` → `(表头, {M##: {列: 值}}, 报错)`。表头必须逐字对得上（列规范在代码里只有这一份）。"""
    header, rows = None, {}
    for line in text.splitlines():
        if not line.startswith('|'):
            if header is not None and rows:
                break
            header = None if not rows else header
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if header is None:
            header = cells
            continue
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if len(cells) != len(header):
            return header, rows, f'有一行列数 {len(cells)} ≠ 表头 {len(header)}：{line[:50]}'
        mid = MD_ID.search(cells[0])
        if not mid:
            return header, rows, f'「材料」列里找不到 `M##`：{cells[0][:40]}'
        rows[mid.group(1)] = dict(zip(header, cells))
    if header is None or not rows:
        return header, rows, '没解析到侦查结论表（表头行 + 至少一行数据）'
    if tuple(header) != CARD_COLUMNS:
        return header, rows, f'表头不是本脚本的列规范：{" | ".join(header)}'
    return header, rows, ''

def check_rows(materials, rows):
    """AI 填的列 → 错误清单（空 = 过）。**只报不改**；§1.5"假设必须落盘、被推翻也要留痕"。"""
    errs, mid_of = [], {m.get('id'): m for m in materials}
    for mid in sorted(set(mid_of) - set(rows)):
        errs.append(f'{mid}: 材料层里有，表里没有（材料必须一一对应）')
    for mid in sorted(set(rows) - set(mid_of)):
        errs.append(f'{mid}: 表里有，材料层里没有（`M##` 一律从材料层抄，不许自己编号）')
    ai_cols = ('假设角色（AI 填 `⚠`）', '依据（AI 填）', '验证方式（AI 填）', '状态（AI 填）')
    for mid in sorted(set(rows) & set(mid_of)):
        cell, m = rows[mid], mid_of[mid]
        if cell['档位'] != m.get('tier'):
            errs.append(f'{mid}: 档位 {cell["档位"]!r} ≠ 材料层 {m.get("tier")!r}（只许抄，不许重判）')
        hyp, basis, verify, status = (cell[c] for c in ai_cols)
        if status not in STATUSES:
            errs.append(f'{mid}: 状态 {status!r} 不在 {"/".join(STATUSES)} 内（必填）')
        if not hyp or hyp == '—':
            errs.append(f'{mid}: 假设角色没填（一句话 + `⚠`）')
        elif '⚠' not in hyp:
            errs.append(f'{mid}: 假设角色是语义推断，必须标 `⚠`')
        if not basis or basis == '—':
            errs.append(f'{mid}: 依据没填（写清凭哪个数字 / 哪句引文判的——§1.5 要求人能复核）')
        if not verify or verify == '—':
            errs.append(f'{mid}: 验证方式没填（打算怎么验：读大纲 / 抽前 N 页 / 问用户…）')
        if status == '已推翻' and '→' not in hyp:
            errs.append(f'{mid}: 状态=已推翻，但假设角色里没有留痕（要写成"曾记 X → 现记 Y"）——'
                        f'§1.5：被推翻也要留痕')
    return errs


# ----------------------------------------------------------------入口

def _write(text, path):
    """写盘：UTF-8 / LF（与账本同一套口径；本文件通篇用 `\\n` 拼）。"""
    Path(path).write_bytes(text.encode('utf-8'))

def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def load_thresholds(path=None):
    """阈值 = 默认 + `dictionary.yaml` 的 `recon:` 段（读不到就用默认，**不报错**）。"""
    th = dict(DEFAULTS)
    p = Path(path) if path else Path(__file__).with_name(DICT_NAME)
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            got = (yaml.safe_load(fh) or {}).get('recon') or {}
    except Exception:                                # 缺依赖 / 缺文件 / 坏 YAML：一律退回默认
        return th
    for k, v in got.items():
        if k in th and isinstance(v, int) and not isinstance(v, bool):
            th[k] = v
    return th


# ----------------------------------------------------------------结构缩样（尽力而为，绝不外溢）

def build(a):
    """出侦查结论表草稿 → 退出码。"""
    try:
        raw = Path(a.materials).read_bytes()
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2
    th = load_thresholds()
    rows, skipped = make_rows(materials, th)
    n_missing_kind = [r['id'] for r in rows if r['kind'] == '?']
    if n_missing_kind:
        print(f'⚠ 材料层缺 `kind`（探测的输出）: {"、".join(n_missing_kind)} —— '
              f'请用当前版本的 `probe.py --json` 重出（§2.1）', file=sys.stderr)
    meta = {'input': Path(a.materials).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(),
            **{k: th[k] for k in ('easy_max_bytes', 'max_open_bytes', 'outline_max')}}
    text = render(rows, meta)
    _write(text, a.out)
    counts = {}
    for r in rows:
        counts[r['diff']] = counts.get(r['diff'], 0) + 1
    print(f'→ 侦查表已写出 {a.out}：' + ' · '.join(f'{k} {v}' for k, v in counts.items())
          + '（**假设角色 / 依据 / 验证方式 / 状态 = AI 填，脚本不猜**）')
    for s in skipped:
        print(f'  · {s}', file=sys.stderr)
    print(f'  · 下一步：AI 填完那四列后跑 `python scripts/recon.py check {a.out} '
          f'--materials {Path(a.materials).name}`', file=sys.stderr)
    return 0

def check(a):
    """校验 AI 填好的表 → 退出码 0/1/2。"""
    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 材料层读不了: {e}', file=sys.stderr)
        return 2
    try:
        text = Path(a.card).read_text(encoding='utf-8')
    except OSError as e:
        print(f'⚠ 侦查表读不了: {e}', file=sys.stderr)
        return 2
    header, rows, err = parse_table(text)
    if err:
        print(f'⚠ 侦查表解析不了（仪器故障，不是内容问题）: {err}', file=sys.stderr)
        return 2
    errs = check_rows(materials, rows)
    if errs:
        print(f'✗ 侦查表校验未过（{len(errs)} 条；**只报不改**）：')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1
    print(f'✓ 侦查表校验通过：{len(rows)} 份 · 档位逐字等于材料层 · 假设/依据/验证方式都填了 · '
          f'状态取值合法 · 被推翻的留了痕')
    return 0

def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='侦查器：难度排序 + 结构缩样 + 侦查结论表（机器列已填）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='出草稿（机器列已填，AI 填四列）')
    b.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    b.add_argument('-o', '--out', default='recon.md', help='写到哪里（默认 recon.md，落成果根）')
    c = sub.add_parser('check', help='校验 AI 填好的表（退 1 = 有问题）')
    c.add_argument('card', help='侦查结论表（recon.md）')
    c.add_argument('--materials', required=True, help='材料层 JSON（对照用）')
    a = ap.parse_args(argv)
    return build(a) if a.cmd == 'build' else check(a)


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（写在这里免得下个会话重新提；都来自 2026-09-18 的四路审计）：
# - **不做体积分档的"结构估计"**：`vol`（段数/行数）只作**参考数字**进「规模」列，**不参与分档**——
#   原先拿它当排序键，导致 docx 的"块"和 xlsx 的"行"被直接比大小（量纲混用），
#   而且一旦某份表读不动，它的 vol 就变成 0、难度直接掉到"易"。分档统一用 `bytes`（跨格式可比、零依赖）。
# - **不打开超大文件**：`max_open_bytes` 之外只记元数据（原先 1.15MB 的 docx 峰值 15.7MB，
#   500MB 单份会 OOM；护栏值住 `dictionary.yaml`）。
# - **不猜 .wps/.et/.dps**：这些后缀原先被写死成"需转换器"，但 `parse_legacy` 只认 OLE 流标记、
#   §1.4 还明说 et/dps 不支持——现在一律按 `kind` 说话（真 OLE 才说转换器，合法 xlsx 改名 `.et` 走直读）。
# - **不再有 `--sample-rows/--sample-cols`**：它们是死参数（收了不用），删掉比留着撒谎好。
