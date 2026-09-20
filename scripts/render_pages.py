# -*- coding: utf-8 -*-
r"""render_pages.py — 把材料**渲染成图**，交给会看图的模型去识别（PIPELINE-SPEC §1.5 手段 2）。

**为什么需要**（实测，不是推演）：有些材料的文字**只在像素里**——扫描件（T3）根本没有文本层；
还有些材料**有文本层但文本层是坏的**（质量门 `garbled` / `noisy`，见 §1.5 手段 0）。
这两类自包含侧都读不动，而**宿主模型能直接看图**——那就把材料渲成图给它看。实测：`pdfplumber` +
`pypdfium2`（pdfplumber 的依赖，**纯 Python 栈、无外部二进制**）渲染一页 0.3~1.9 秒。

**分工**（脚本只执行、判断在 AI 侧）：
- **脚本渲图**：PDF → 每页一张 PNG；**图片材料本来就是图**（`probe` 已记 T3 + 图片魔数），直接用原文件；
- **AI 识别**：`read_image` 读那些 PNG，把读到的内容填进本工具给的**骨架**（`--elements` 那个 JSON）；
- **脚本校验**：`check` 子命令验 AI 填的骨架（id 形态 / kind 枚举 / 正文非空 / 出处 / bbox / 两档标记），
  顺带写**材料层补注**（`status=ok` + `extractor=vlm`）——这就是 §1.3 说的"T3 也必须有证据"。

**证据口径**（§1.3 / §2.3，硬要求）：
- element 一律 `extractor: vlm` + `certainty: inferred`（**视觉读数是推断，不许伪装成直取**）；
- `location` = **原材料路径** + `page` + `bbox`（**归一化 0~1**，与渲染 DPI 无关：`[x, y, w, h]`）；
  图是中间物，出处必须指向用户给的那份材料（与 `parse_legacy` 的转换副本同一条纪律）；
- 引它的流程表节点按推断档走（`⚠` / H10.2），**不许把视觉读数当逐字引用**。

**已知边界**：
- **只渲 PDF**。Office 系（docx/xlsx/pptx）要转换器（`soffice`，本机通常没有）——本版不做，
  按 §1.5 记"不可行 + 进澄清"；纯文本更不需要（模型直读，要记账走 `parse_text`）。
- **有预算**：`--max-pages` 封顶（默认 20 页/份），被截断的在骨架里写进 `degraded`——
  否则一份 200 页扫描件会把上下文烧光（§1.5：先侦查、再决定解析深度）。

用法：
    python scripts/render_pages.py build --materials materials.json --out-dir shots [--only M13,M15]
    # ↑ AI 用 read_image 读那些 PNG，把内容填进 shots/vision.json 的 text 字段
    python scripts/render_pages.py check shots/vision.json --notes shots/vision-notes.json

退出码：0 = 干完了；1 = `check` 发现骨架有问题（**不写补注**）；2 = 输入读不了 / 起不来。
"""
import argparse
import json
import sys
from pathlib import Path

import artifact
import deps

PDF_MAGIC = b'%PDF'
# 骨架里每个元素都能用的 kind（§2.1 封闭枚举）。默认给 paragraph——AI 按实际内容改。
KINDS = ('heading', 'paragraph', 'list_item', 'table', 'figure', 'caption', 'code', 'sheet', 'cell')
BUDGET_PAGES = 20


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write_json(obj, path):
    """写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`）。"""
    Path(path).write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _is_pdf(path):
    """只看 4 字节魔数：**不重判档位**（档位从账本抄）。"""
    try:
        with open(path, 'rb') as fh:
            return fh.read(4) == PDF_MAGIC
    except OSError:
        return False


def _skeleton(mid, path, page, cap_note=''):
    """一页 → 一条**待填**的 vlm 证据骨架（`text` 空着等 AI 填）。

    `location.path` 一律写成**材料路径**（正斜杠形式）：图是中间物，出处必须指向用户给的那份材料
    （与 `parse_legacy` 的转换副本同一条纪律，§2.3）。
    """
    el = {'id': f'{mid}#v{page:03d}', 'material_id': mid, 'kind': 'paragraph', 'text': '',
          'location': {'path': Path(path).as_posix(), 'page': page, 'bbox': [0, 0, 1, 1]},
          'extractor': 'vlm', 'certainty': 'inferred'}
    if cap_note:
        el['degraded'] = cap_note
    return el


def render_pdf(path, mid, out_dir, max_pages, dpi):
    """PDF → `(骨架元素, 渲染出的 (页号, PNG 路径) 清单, 说明)`。**单页渲不出不让整份失败**。"""
    pdfplumber, err = _import_pdfplumber()
    if err:
        return None, [], err
    shots, out = [], []
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        keep = min(total, max_pages)
        cap = f'只渲染前 {keep} 页（共 {total} 页）' if keep < total else ''
        for i, page in enumerate(pdf.pages[:keep], 1):
            png = Path(out_dir) / f'{mid}-p{i:03d}.png'
            try:
                page.to_image(resolution=dpi).save(str(png))
            except Exception as e:                     # 单页坏不让整份失败（§1.4 硬要求 2）
                out.append(f'{mid} 第 {i} 页渲染失败：{type(e).__name__}')
                continue
            shots.append((i, png))
            out.append(_skeleton(mid, path, i, cap))
        if keep < total:
            out_note = f'{mid}: {total} 页，只渲染前 {keep} 页（--max-pages {max_pages}）'
        else:
            out_note = f'{mid}: {total} 页全渲染'
    return out, shots, out_note


def _import_pdfplumber():
    """import 必须依赖 → `(模块, 报错文案)`（**提示只有一处**：`deps.import_dep`，D-122）。"""
    return deps.import_dep('pdfplumber')


def targets(materials, only):
    """材料层 → 该渲哪些 → `(要渲染的, 已是图片的, 不归本工具管的)`。**按 `probe` 记的档位分派，不重判**。"""
    want, images, skip = [], [], []
    for m in materials:
        mid = m.get('id', '?')
        if only and mid not in only:
            continue
        path = Path(m.get('path', ''))
        if m.get('status') != 'ok':
            skip.append(f'{mid}: status={m.get("status")}（不渲染）')
            continue
        if _is_pdf(path):
            want.append(m)
        elif m.get('tier') == 'T3':
            images.append(m)                           # 扫描件/照片：**它本来就是图**，直接读原文件
        else:
            skip.append(f'{mid}: {m.get("tier")} 不是 PDF/图片'
                        f'（Office 系要转换器，见文件头边界；纯文本直读即可）')
    return want, images, skip


def build(a):
    """渲图 + 出骨架（`--elements` 给了才写）。返回退出码。"""
    # 默认落盘跟着输入走（D-119）：`shots/` 是任务级产物、住成果根（§1.5 手段 2），
    # 而 `--materials` 也在那儿。原先默认 `shots/` 落 cwd：在仓库根跑一次就把图撒进仓库根。
    a.out_dir = a.out_dir or str(artifact.beside(a.materials, 'shots'))
    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 材料层读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 材料层必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2
    only = {x.strip() for x in a.only.split(',') if x.strip()} if a.only else set()
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    want, images, skip = targets(materials, only)
    elements, lines = [], []
    for m in want:
        mid, path = m.get('id'), Path(m.get('path', ''))
        got, shots, note = render_pdf(path, mid, out_dir, a.max_pages, a.resolution)
        if got is None:
            print(f'⚠ {note}', file=sys.stderr)
            return 2
        elements += got
        lines.append(f'{mid} {path.name} → {note}')
        for page, png in shots:
            lines.append(f'  · p{page:03d}  {png.as_posix()}')
    for m in images:
        mid, path = m.get('id'), Path(m.get('path', ''))
        elements.append(_skeleton(mid, path.as_posix(), 1))
        lines.append(f'{mid} {path.name} → **已经是图片**（{m.get("probe", "")}）：直接读原文件，不用渲')
    for s in skip:
        lines.append(f'（跳过）{s}')

    for line in lines:
        print(line)
    if a.elements:
        _write_json(elements, a.elements)
        print(f'→ 骨架已写出 {a.elements}：{len(elements)} 条待填元素'
              f'（读图后填 `text`；`bbox` 请收紧到实际读到的那块，别整页留 [0,0,1,1]）')
    print(f'→ 渲染 {len(want)} 份 PDF · 已是图片 {len(images)} 份 · 跳过 {len(skip)} 份 · 输出目录 {out_dir}')
    return 0


def _check_id(eid, mid):
    """id 形态：`<M##>#v<页号3位><可选字母>`（同一页要拆多条时用字母后缀，如 `M15#v004b`）。"""
    head, _, tail = str(eid).partition('#')
    if head != mid or not tail.startswith('v'):
        return f'id 形态不对（要 `{mid}#v<页号3位>` 或加字母后缀）：{eid!r}'
    body = tail[1:]
    if not (len(body) >= 3 and body[:3].isdigit() and (len(body) == 3 or body[3:].isalpha())):
        return f'id 里的页号不是 3 位数字：{eid!r}'
    return ''


def check_elements(items):
    """AI 填好的骨架 → 错误清单（空 = 过）。**"没填"必须当错**（否则空骨架也能过）。"""
    errs = []
    for i, e in enumerate(items):
        where = e.get('id') or f'elements[{i}]'
        if not isinstance(e, dict):
            errs.append(f'elements[{i}]: 不是对象')
            continue
        mid = str(e.get('material_id') or '')
        if not mid:
            errs.append(f'{where}: 缺 material_id')
        elif e.get('id'):
            bad = _check_id(e['id'], mid)
            if bad:
                errs.append(f'{where}: {bad}')
        if not str(e.get('text') or '').strip():
            errs.append(f'{where}: `text` 是空的——**没读出来的页就删掉这条**，别把空骨架交上来')
        if e.get('kind') not in KINDS:
            errs.append(f'{where}: kind 不在 §2.1 的封闭枚举内（{e.get("kind")!r}）')
        if e.get('extractor') != 'vlm':
            errs.append(f'{where}: extractor 必须是 `vlm`（视觉读数是推断档，不许挂别的来源）')
        if e.get('certainty') != 'inferred':
            errs.append(f'{where}: certainty 必须是 `inferred`（§1.3：视觉推断不许伪装成直取）')
        loc = e.get('location')
        if not isinstance(loc, dict) or not loc.get('path'):
            errs.append(f'{where}: location 必须是对象且含 path（指向**原材料**）')
            continue
        if not isinstance(loc.get('page'), int) or loc['page'] < 1:
            errs.append(f'{where}: location.page 必须是 ≥1 的整数')
        box = loc.get('bbox')
        if not (isinstance(box, list) and len(box) == 4
                and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in box)):
            errs.append(f'{where}: bbox 要是 4 个 0~1 的数（归一化，与渲染 DPI 无关）')
    return errs


def check(a):
    """校验填好的骨架 + 写材料层补注（`status=ok` + `extractor=vlm`）。"""
    try:
        items = _read_json(a.filled)
    except (OSError, ValueError) as e:
        print(f'⚠ 骨架读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(items, list):
        print('⚠ 骨架必须是 JSON 数组（elements[]）', file=sys.stderr)
        return 2
    errs = check_elements(items)
    if errs:
        print(f'✗ vlm 证据骨架没填对（{len(errs)} 条；**不写补注**）：')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1

    mids = sorted({e.get('material_id') for e in items})
    notes = [{'material_id': mid, 'status': 'ok', 'extractor': 'vlm'} for mid in mids]
    if a.notes:
        _write_json(notes, a.notes)
    wide = sum(1 for e in items if e.get('location', {}).get('bbox') == [0, 0, 1, 1])
    for mid in mids:
        mine = [e for e in items if e.get('material_id') == mid]
        pages = sorted({e.get('location', {}).get('page') for e in mine})
        print(f'  · {mid}: {len(mine)} 条 · 覆盖页 {pages[0]}~{pages[-1]}（{len(pages)} 页）')
    print(f'✓ vlm 证据过了：{len(items)} 条 · {len(mids)} 份材料（{", ".join(mids)}）'
          + (f' · 补注已写 {a.notes}' if a.notes else ''))
    if wide:
        print(f'  ⚠ 其中 {wide} 条 bbox 是整页 [0,0,1,1]：能收，但复核的人得自己找位置'
              f'——建议收紧到实际读到的那块')
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='把材料渲成图交给会看图的模型（§1.5 手段 2）+ 校验它填的证据')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='渲图 + 出待填骨架')
    b.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    b.add_argument('--out-dir', help='PNG 落在哪里（默认：与 --materials 同目录的 shots/）')
    b.add_argument('--elements', help='待填骨架写到哪里（不给就只渲图）')
    b.add_argument('--only', help='只渲这几份（逗号分隔的 M##，如 M13,M15）')
    b.add_argument('--max-pages', type=int, default=BUDGET_PAGES, help=f'每份最多渲多少页（默认 {BUDGET_PAGES}）')
    b.add_argument('--resolution', type=int, default=110, help='渲染 DPI（默认 110；太高只烧内存不影响判读）')
    c = sub.add_parser('check', help='校验 AI 填好的骨架 + 写材料层补注')
    c.add_argument('filled', help='填好的骨架 JSON')
    c.add_argument('--notes', help='材料层补注写到哪里（交给 ledger.py --notes）')
    a = ap.parse_args(argv)
    return build(a) if a.cmd == 'build' else check(a)


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（要扩就得另立一版，并同样标 extractor）：
# - **只渲 PDF**：Office 系（docx/xlsx/pptx）要 `soffice` 之类的转换器（本机通常没有，且仓库里
#   `parse_legacy` 已经在管"legacy → OOXML"那条路）——真需要时先转 PDF 再喂给本工具，
#   或者把转换器探测抽到公共层复用（现在抽 = 为一个还没出现的需求加一层抽象，不做）。
# - **不做 OCR**：识别是模型的事（§1.4 的加速器），脚本只把像素准备好。装了 tesseract 之后
#   要接的是"另一条自包含路径"，不是改这里。
# - **不管 bbox 的坐标系换算**：一律归一化 0~1，与 DPI 解耦；AI 自己按图估。
