# -*- coding: utf-8 -*-
r"""parse.py — 解析分派器（**编排层**；PIPELINE-SPEC §1.4）：材料层 → `elements[]` + 材料层补注。

**为什么要有它**：§1.4 说"分派是查表，不是判断"。但**判档不在这里**——每个适配器只认自己那一类
（PK 容器 / `%PDF` / OLE 头），认不出的材料**不记账**（留给别的适配器）。所以这张表只说
"**有哪些适配器、按什么顺序跑**"，**不是又抄一份格式清单**：手写清单必漂（§1.2 第 1 条），
而"什么材料归谁"这件事已经有**三个**真值源了（`probe` 的档位、各适配器自己的认领判据），
再抄一份就是第四份。

**为什么顺序固定**：同输入两次必须同产物（§2.4 幂等）。顺序 = 表里的顺序；元素合并后按
`material_id` **稳定排序**（各适配器内部的阅读序原样保留，只按材料归位）——账本里 M01…M15 是连着的，
人翻账本不用在三个适配器的输出之间来回跳。

**三道关，缺一不可**（都在这一层，因为只有它同时看得见"谁产的"与"整份材料长什么样"）：

- **质量门**（§1.5「手段 0」）：`probe` 说"有文本层"、适配器说"抽到了"——两边都真，但那条文本层可能是
  竖排 / 字距碎裂的水印碎片（实测 M15：单字行 62%）。判据在 `textquality`（阈值在 `dictionary.yaml`）：
  `ok` 照收 · `noisy` 丢**纯碎片**元素、留下的每条挂 `degraded` · `garbled` 整份**不入账** + 建议处置。
  **丢元素一律记账**：不吭声地少几条，下游只会以为"这份材料本来就这么点内容"。
- **冲突**：同一个 element id 被两个适配器产出（判档重叠），或两份补注对同一材料给出不同的
  `status`/`reason`/`extractor`——静默取一个会让账本里出现"没人知道哪来的"记录；
- **漏认**（**现在是"探测说谎"的代名词**）：`probe` 说这份 `status=ok`，却**既没有元素、也没有补注**
  ——§1.2 的不变式是"**`tier=T1` ⇒ 必须有人认领**"，做不到就是**探测的声明比读者的射程宽**，
  该改的是 `probe` 的判据（例：`.pptx` 没有读取器却曾判 T1、OOXML 曾按目录前缀判而非确切部件），
  不是在下游加特例。报错会点名材料与它的 `kind`，方便直接回去修探测。

退出码：0 = 跑完（**可能有读不动的材料**，补注里逐份给了原因）；1 = 冲突 / 漏认（不写产物）；
2 = 输入读不了 / 适配器起不来 / 适配器报错。质量门**不改退出码**：材料读不动是数据事实，不是仪器故障。
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from textquality import element_haystack, load_thresholds, scar, verdict

SCRIPTS = Path(__file__).resolve().parent

# 分派表：**只有顺序，没有判据**（判据在各适配器内部，它们各自认领、各自跳过）。
# 顺序 = 产物顺序的一部分，改它等于改账本字节，所以它是常量、不随环境变。
ADAPTERS = ('parse_ooxml', 'parse_pdf', 'parse_legacy', 'parse_text')


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write_json(obj, path):
    """写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 `ledger.dump`）。"""
    Path(path).write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _last_line(text):
    """子进程输出 → 最后一行非空（适配器把摘要打在 stderr，取它给人看；整份太吵，`--verbose` 才全给）。"""
    lines = [ln for ln in (text or '').splitlines() if ln.strip()]
    return lines[-1] if lines else ''


def _adapter_args(name, a):
    """按适配器给参数——**不认得的选项不硬塞**（argparse 会当场报用法错，那是假故障）。"""
    if name == 'parse_ooxml':
        return _opt(['--max-rows', str(a.max_rows), '--max-cols', str(a.max_cols),
                     '--max-slides', str(a.max_slides)],
                    ['--slides', a.slides, '--sheet', a.sheet, '--rows', a.rows])
    if name == 'parse_pdf':
        return _opt(['--max-pages', str(a.max_pages), '--max-chars', str(a.max_chars)],
                    ['--pages', a.pages])
    if name == 'parse_legacy':
        args = ['--timeout', str(a.timeout)]
        return args + (['--soffice', a.soffice] if a.soffice else [])
    if name == 'parse_text':
        args = ['--max-chars', str(a.max_chars), '--max-rows', str(a.max_rows),
                '--max-cols', str(a.max_cols)]
        return args + (['--encoding', a.encoding] if a.encoding else [])
    return []


def _opt(base, pairs):
    """把 `(选项, 值)` 对里**有值的那几对**接在 base 后面（空值 = 没收窄，不传）。"""
    out = list(base)
    for i in range(0, len(pairs), 2):
        if pairs[i + 1]:
            out += [pairs[i], str(pairs[i + 1])]
    return out


def _span(spec):
    """`'40-60'` / `'7'` → `(40, 60)` / `(7, 7)`；空 → `None`；**写歪/反区间要报错，不许静默按全量走**。

    "歪了就按全量走"本身就是猜（把"我要第 3 条"执行成"全都要"），而且会让下游以为收窄生效了。
    与 `query.py` 的同一句声明保持一致：那边是抛错退 2，这边也退 2（审计实测两处曾相反）。
    """
    if not str(spec or '').strip():
        return None
    m = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', str(spec))
    if not m:
        raise ValueError(f'范围写法不认：{spec!r}（应为 N 或 A-B，1 起，闭区间）')
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if a < 1:
        raise ValueError(f'范围 {spec!r}：起点要 ≥1（页码/条数是 1 起）')
    if b < a:
        raise ValueError(f'范围 {spec!r}：上界小于下界')
    return (a, b)


def narrow_materials(materials, only):
    """`--only M03,M15` → `(可选中的那些, 被排除的那些)`。**空集合 = 不筛**（不是"一份都不要"）。

    **点名了却一个都没匹配上 ⇒ 报错退 2**：否则整批被静默记成"本轮未取"、还退 0，
    唯一的线索是理由句里的一个空括号（审计实测）。大小写敏感是有意的：`M##` 是本仓的编号写法，
    认小写等于默许两种写法并存（而 `--grep` 的大小写不敏感是**文本匹配**，两回事）。
    """
    want = {x.strip() for x in str(only or '').split(',') if x.strip()}
    if not want:
        return materials, []
    known = {m.get('id') for m in materials}
    missing = sorted(want - known)
    if not (want & known):
        raise ValueError(f'--only 点名的材料一个都不在材料层里：{"、".join(missing)}'
                         f'（材料层现有 {"、".join(sorted(x for x in known if x)) or "空"}）')
    if missing:
        raise ValueError(f'--only 里有材料层没有的编号：{"、".join(missing)}'
                         f'（材料层现有 {"、".join(sorted(x for x in known if x))}）')
    return ([m for m in materials if m.get('id') in want],
            [m for m in materials if m.get('id') not in want])


def apply_narrowing(elements, grep, lines):
    """抽取后收窄：`--grep` 只留含这个词的片段、`--lines A-B` 只留该材料内第 A–B 条。

    **每一条被丢掉的都要记账**（挂在该材料**留下**的每条上）：不记的话，下游只会以为
    "这份材料本来就这么点内容"（§2.4 不许静默截断）。返回 `(留下的, [(材料, 丢了几条, 说明)])`。
    """
    if not grep and not lines:
        return elements, []
    keep, dropped = [], {}
    seen = {}
    for el in elements:
        mid = el.get('material_id')
        seen[mid] = seen.get(mid, 0) + 1
        hit_word = not grep or grep.lower() in element_haystack(el)
        hit_line = True
        if lines:
            a, b = lines
            hit_line = a <= seen[mid] <= b
        if hit_word and hit_line:
            keep.append(el)
        else:
            dropped[mid] = dropped.get(mid, 0) + 1
    how = '；'.join(x for x in (
        f'只保留含「{grep}」的片段' if grep else '',
        f'只保留本材料第 {lines[0]}–{lines[1]} 条' if lines else '') if x)
    for el in keep:
        n = dropped.get(el.get('material_id'), 0)
        el['degraded'] = ((el['degraded'] + '；') if el.get('degraded') else '') + \
                         f'本轮收窄：{how}' + (f'（同材料另 {n} 条未入账）' if n else '')
    return keep, sorted((mid, n) for mid, n in dropped.items())


def run_adapter(name, materials, workdir, extra):
    """跑一个适配器 → `(elements, notes, 摘要行, 报错文案)`。走**子进程 + 产物**（模块层不许横向 import）。"""
    script = SCRIPTS / f'{name}.py'
    out, nts = Path(workdir) / f'{name}.elements.json', Path(workdir) / f'{name}.notes.json'
    cmd = [sys.executable, str(script), '--materials', str(materials),
           '-o', str(out), '--notes', str(nts)] + extra
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except (OSError, subprocess.SubprocessError) as e:
        return None, None, '', f'{name} 起不来 {type(e).__name__}: {e}'
    brief = _last_line(r.stderr) or _last_line(r.stdout)
    if r.returncode != 0 or not out.is_file():
        return None, None, brief, f'{name} 退 {r.returncode}：{brief}'
    try:
        elements = _read_json(out)
        notes = _read_json(nts) if nts.is_file() else []
    except (OSError, ValueError) as e:
        return None, None, brief, f'{name} 的产物读不了（{type(e).__name__}）：{e}'
    if not isinstance(elements, list) or not isinstance(notes, list):
        return None, None, brief, f'{name} 的产物不是数组（elements / notes 都必须是 JSON 数组）'
    return elements, notes, brief, ''


def merge_elements(per_adapter):
    """`[(适配器名, elements)]` → `(合并后的 elements, 冲突说明)`。

    排序：**按 `material_id` 稳定排序**（同材料内部保序 = 该适配器的阅读序）。id 重复说明两个适配器
    都认领了同一份材料——**这是 bug，不是可选的取舍**，所以报错并说清是谁和谁撞了。
    """
    seen, owner = set(), {}
    for name, elements in per_adapter:
        for e in elements:
            eid = e.get('id')
            if eid in seen:
                return None, f'元素 id 重复：{eid}（{owner.get(eid)} 与 {name} 都产出了它——判档重叠）'
            seen.add(eid)
            owner[eid] = name
    merged = [e for _n, els in per_adapter for e in els]      # 保序展开，再稳定排序
    merged.sort(key=lambda e: str(e.get('material_id', '')))
    return merged, ''


def apply_quality(elements, materials, adapter_notes, th):
    """抽取质量门（§1.5「手段 0」）→ `(留下的元素, 覆盖用的补注, 丢掉的元素 id, 读数行, {M##: 级别})`。

    **为什么门要设在这里**：`probe` 说"有文本层"、适配器说"抽到了"——两边都真，但那条文本层可能是
    竖排 / 字距碎裂的水印碎片（实测 M15：单字行 62%）。不设门，账本就把碎片当 `direct` 证据收下，
    下游「依据」列引一堆读不出意思的东西，而且**没有任何仪器看得见**。

    三级处置（判据在 `textquality.verdict`，阈值在 `dictionary.yaml`）：
    `ok` 照收；`noisy` 丢掉**纯碎片**元素、留下的每条挂 `degraded`（降级留痕 §2.4）；`garbled` 整份不入账。
    **丢元素必须记账**：不吭声地少几条，下游只会以为"这份材料本来就这么点内容"。
    """
    by_mid, kept, notes, frozen, lines, level_of = {}, [], [], [], [], {}
    for e in elements:
        by_mid.setdefault(e.get('material_id'), []).append(e)
    for m in materials:
        mid = m.get('id')
        mine = by_mid.get(mid) or []
        if not mine:
            continue
        level, why, drop = verdict(mine, th)
        level_of[mid] = (level, why)
        if level == 'garbled':
            old = next((n for n in adapter_notes if n.get('material_id') == mid), {})
            note = {'material_id': mid, 'status': 'unreadable',
                    'reason': f'抽取质量不过关（{why}）：建议转图片 → 视觉识别（`render_pages`）、'
                              f'装 OCR，或人工核对后进澄清'}
            if old.get('extractor'):
                note['extractor'] = old['extractor']      # 记下"谁抽的、抽成这样"，排障要看
            notes.append(note)
            frozen += [e.get('id') for e in mine]
            lines.append(f'{mid} garbled：{why} → 该材料 {len(mine)} 条元素一律不入账')
            continue
        # 元素级丢碎片：**各级都做**（整份判干净，也可能夹着一页纯水印碎片——那条本身没有可用内容）
        kill = set(drop)
        keep = [e for e in mine if e.get('id') not in kill]
        kept += keep
        frozen += drop
        if level == 'noisy':
            scar(keep, why)
            lines.append(f'{mid} noisy：{why}'
                         + (f' → 丢掉纯碎片 {len(drop)} 条，其余每条挂 degraded' if drop else ' → 每条挂 degraded'))
        elif drop:
            lines.append(f'{mid} ok（整份判据干净）：丢掉纯碎片 {len(drop)} 条'
                         f'（那几条自己就是一页水印/碎片，留进账本只会让「依据」引到读不出意思的东西）')
    return kept, notes, frozen, lines, level_of


def merge_notes(per_adapter):
    """`[(适配器名, notes)]` → `(合并后的 notes, 冲突说明)`。

    同一材料被两份补注写到**不同的值**就是冲突（谁对？没人知道——所以不猜）；写到相同的值则去重。
    """
    by_mid, src = {}, {}
    for name, notes in per_adapter:
        for n in notes:
            mid = n.get('material_id')
            if mid in by_mid:
                if by_mid[mid] != n:
                    return None, (f'补注冲突：{mid} 被 {src[mid]} 与 {name} 写成不同的值'
                                  f'（{by_mid[mid]} vs {n}）')
                continue
            by_mid[mid], src[mid] = n, name
    return [by_mid[mid] for mid in by_mid], ''


def survey(materials, elements, notes, quality=None):
    """材料层 × 证据 × 补注 → `(每份材料一行, 漏认清单)`。**漏认 = status=ok 却既无元素也无补注。**

    **T3（需视觉）不算漏认**（2026-09-18 夹具实测补的一条）：视觉路是 `render_pages.py` 的活，
    本链（文本抽取）**本来就不该认领**它——所以"零证据"在这里是**正确行为**，不是漏认。
    把它算成漏认会让整链退 1，而实际上什么都没错（夹具里那张 4×4 的 PNG 就是这么暴露出来的）。
    它也不是没人管：`render_pages.py` 才是它的 owner，表里那一行会写明"转图片 → 视觉"。
    """
    counts, note_of = {}, {}
    for e in elements:
        counts[e.get('material_id')] = counts.get(e.get('material_id'), 0) + 1
    for n in notes:
        note_of[n.get('material_id')] = n
    rows, gaps = [], []
    for m in materials:
        mid, n = m.get('id'), note_of.get(m.get('id'), {})
        status = n.get('status') or m.get('status')
        # 状态已改成 ok 时**不许再回落到 probe 的旧 reason**：那是陈旧真值（补注说了能读，
        # 表上却还印着"魔数不认识"——ledger 落补注时会把这条 reason 删掉，两处必须一致）
        reason = n.get('reason') or (m.get('reason') if status != 'ok' else '') or ''
        row = {'id': mid, 'tier': m.get('tier'), 'kind': m.get('kind', '?'), 'status': status,
               'extractor': n.get('extractor') or m.get('extractor') or '',
               'elements': counts.get(mid, 0), 'reason': reason}
        q = (quality or {}).get(mid)
        if q and q[0] == 'noisy':                     # 有保留：**表上也要看得见**（别让人以为这份是干净的）
            row['reason'] = f'⚠ 抽取质量有保留：{q[1]}'
        rows.append(row)
        if (status == 'ok' and not row['elements'] and not note_of.get(mid)
                and m.get('tier') != 'T3'):
            gaps.append(mid)
    return rows, gaps


def _print_survey(rows, gaps, verbose):
    """人读摘要：一份材料一行。**没有证据也没有补注的当场标出来**（那是漏认，不是"空材料"）。"""
    print(f'{"材料":<5}{"档":<4}{"类型":<10}{"状态":<11}{"谁产的":<22}{"元素":>5}  原因')
    for r in rows:
        mark = ' ⚠' if r['id'] in gaps else ''
        print(f'{r["id"]:<5}{r["tier"]:<4}{r["kind"]:<10}{r["status"]:<11}'
              f'{r["extractor"] or "-":<22}{r["elements"]:>5}  {r["reason"][:56]}{mark}')
    if gaps:
        who = '、'.join(f'{r["id"]}({r["kind"]})' for r in rows if r['id'] in gaps)
        print(f'⚠ **探测说谎** {len(gaps)} 份：probe 判"可直读"，却没有任何适配器认领 → {who}')
        if verbose:
            print('  这不是"缺个适配器"那么简单——§1.2 的不变式是「tier=T1 ⇒ 必须有人认领」。'
                  '要么 probe 的判据收紧到与 reader 同源（例：pptx 没有读取器就不许判 T1、'
                  'OOXML 要按确切部件判），要么补一个适配器；**不许在下游加特例绕过**。')


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='解析分派器：材料层 → elements[] + 材料层补注（固定顺序跑各适配器）')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--elements', default='elements.json', help='元素层写到哪里（默认 elements.json）')
    ap.add_argument('--notes', default='notes.json', help='材料层补注写到哪里（默认 notes.json）')
    ap.add_argument('--ledger', help='给了就接着跑 ledger.py 写账本（把这条链一次跑完）')
    ap.add_argument('--task', default='', help='账本的任务名（--ledger 时用）')
    ap.add_argument('--quote-limit', type=int, default=200, help='账本的 quote 截断上限')
    ap.add_argument('--max-rows', type=int, default=200, help='[parse_ooxml] 每张 sheet 行上限')
    ap.add_argument('--max-cols', type=int, default=50, help='[parse_ooxml] 每张 sheet 列上限')
    ap.add_argument('--max-slides', type=int, default=200, help='[parse_ooxml] pptx 最多读多少张幻灯片')
    ap.add_argument('--max-pages', type=int, default=50, help='[parse_pdf] 最多抽多少页')
    ap.add_argument('--max-chars', type=int, default=4000, help='[parse_pdf] 单页最多多少字')
    ap.add_argument('--soffice', help='[parse_legacy] 显式指定转换器命令')
    ap.add_argument('--timeout', type=int, default=180, help='[parse_legacy] 单份材料转换 / 抽取超时秒数')
    ap.add_argument('--encoding', default='', help='[parse_text] 显式指定编码（如 gbk）；默认只认 UTF-8 / UTF-16')
    ap.add_argument('--only', default='', help='只解析这几份（逗号分隔的 M##）；其余记「本轮未取」，不当漏认')
    ap.add_argument('--grep', default='', help='只保留含这个词的片段（可搜面与 query.py --grep 同一句）')
    ap.add_argument('--lines', help='只保留每份材料内第 A-B 条元素（1 起，闭区间；与 query.py 的 lines= 同义）')
    ap.add_argument('--pages', help='[parse_pdf] 只要这几页（A-B，1 起）')
    ap.add_argument('--slides', help='[parse_ooxml] pptx 只要这几张（A-B，1 起）')
    ap.add_argument('--sheet', default='', help='[parse_ooxml] 只要这个子表（逐字相等）')
    ap.add_argument('--rows', help='[parse_ooxml] 每张 sheet 只要这几行（A-B，1 起）')
    ap.add_argument('--verbose', action='store_true', help='把各适配器的完整输出也打出来')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 材料层读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 材料层必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    per_elements, per_notes, briefs = [], [], []
    try:
        picked, left_out = narrow_materials(materials, a.only)
    except ValueError as e:                          # 点名了却没有/写错编号 ⇒ 退 2 说人话
        print(f'⚠ {e}', file=sys.stderr)
        return 2
    try:                                             # 范围写歪 ⇒ 退 2（不许静默按全量走）
        lines_span = _span(a.lines)
    except ValueError as e:
        print(f'⚠ {e}', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='parse_dispatch_') as td:
        # `--only` 时**换材料层给适配器**（省掉不该读的那几份的解析代价）；账本仍然按**全量**材料落，
        # 被排除的那几份在下面补注成 `skipped`——不补的话它们在账本上就是"status=ok 却零证据"，
        # 那正是分派器要拦的"漏认"（把"我有意没读"说成"读不出来"是两回事）。
        mats_path = a.materials
        if left_out:
            mats_path = Path(td) / 'materials.only.json'
            _write_json(picked, mats_path)
        for name in ADAPTERS:
            elements, notes, brief, err = run_adapter(name, mats_path, td, _adapter_args(name, a))
            if err:
                print(f'⚠ {err}', file=sys.stderr)
                if briefs and a.verbose:
                    print('\n'.join(briefs), file=sys.stderr)
                return 2
            per_elements.append((name, elements))
            per_notes.append((name, notes))
            briefs.append(f'{name}: {brief}')

    elements, err = merge_elements(per_elements)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 1
    notes, err = merge_notes(per_notes)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 1

    # 抽取质量门（§1.5）：先过门再记账——"抽出来了"不等于"抽对了"
    elements, q_notes, frozen, q_lines, q_of = apply_quality(
        elements, materials, notes, load_thresholds())
    if q_notes:                                        # 质量门的补注**覆盖**适配器那条（谁抽的仍记着）
        killed = {n.get('material_id') for n in q_notes}
        notes = [n for n in notes if n.get('material_id') not in killed] + q_notes

    # **"未取"不许顶掉"读不动"**（审计实测的阻断）：这两类补注是在别的补注之后追加的，
    # 而 `ledger` 对同一材料**后写覆盖先写**——于是一份"缺转换器 / 容器损坏"的材料，
    # 只要它这一轮被 `--only` 排除或被 `--grep` 滤空，账本上的结论就会从 `unreadable`
    # 变成 `skipped`，理由句还反过来断言"这不是读不动"——**账本开始说假话**。
    # 读不动是材料的属性，不随本轮读不读它而改变；所以这两处补注都要**避开已经确定读不动的材料**：
    # ① 补注里写了 `unreadable` 的（适配器 / 质量门判的）；② **材料层本身就是 `unreadable`/`skipped` 的**
    # （`probe` 判的 T4 / 不参与）——后者没有补注，光看 notes 会漏掉（审计实测：`--only M01` 把
    # 一份 probe 判"容器损坏"的材料改写成了 `skipped` +"这不是读不动"）。
    pinned = {n.get('material_id') for n in notes if n.get('status') == 'unreadable'}
    pinned |= {m.get('id') for m in materials if m.get('status') not in (None, 'ok')}

    # 收窄在**质量门之后**：门判的是"这份材料抽得干不干净"（按整份统计），先滤后判会让统计失真
    elements, dropped = apply_narrowing(elements, a.grep, lines_span)
    if a.grep or a.lines:
        print(f'本轮收窄：' + ' · '.join(x for x in (
            f'只保留含「{a.grep}」的片段' if a.grep else '',
            f'只保留每份第 {a.lines} 条' if a.lines else '') if x)
            + (f' · 丢掉 {sum(n for _m, n in dropped)} 条（**已逐条记账**，见元素的 degraded）'
               if dropped else ''))
        # **整份被滤空**的材料：留痕没地方挂（`degraded` 挂在留下的元素上）⇒ 改记材料级 `skipped`。
        # 不记的话它在账本上就是"status=ok 却零证据"——读的人分不清"本来就没有"与"被我滤掉了"。
        emptied = [(m, n) for m, n in dropped
                   if not any(e.get('material_id') == m for e in elements) and m not in pinned]
        if emptied:
            notes += [{'material_id': m, 'status': 'skipped',
                       'reason': f'本轮未取（收窄把它原有的 {n} 条片段全滤掉了）：'
                                 f'{"、".join(x for x in (f"--grep {a.grep}" if a.grep else "", f"--lines {a.lines}" if a.lines else "") if x)}'
                                 f'；放宽条件重跑即可'}
                      for m, n in emptied]
            print(f'  · {len(emptied)} 份材料被滤空（记「本轮未取」，不是漏认）：'
                  f'{"、".join(m for m, _n in emptied)}')
    if left_out:
        rest = [m for m in left_out if m.get('id') not in pinned]
        notes += [{'material_id': m['id'], 'status': 'skipped',
                   'reason': f'本轮 --only 未取（只要了 {"、".join(sorted(x["id"] for x in picked))}）；'
                             f'下一轮补上'}
                  for m in rest]
        print(f'本轮 --only：解析 {len(picked)} 份 · 其余 {len(rest)} 份记「未取」（不是漏认）'
              + (f' · 其中 {len(left_out) - len(rest)} 份保持原本的「读不动」（读不动不随本轮读不读它而变）'
                 if len(rest) != len(left_out) else ''))

    rows, gaps = survey(materials, elements, notes, q_of)
    if a.verbose:
        for line in briefs:
            print(f'  · {line}', file=sys.stderr)
    _print_survey(rows, gaps, a.verbose)
    if q_lines:
        n_flag = sum(1 for lv, _w in q_of.values() if lv != 'ok')
        print(f'抽取质量门（§1.5）：{n_flag} 份没过"干净"这一档'
              + (f' · 丢弃元素 {len(frozen)} 条（**已记账**，不是静默少几条）' if frozen else ''))
        for line in q_lines:
            print(f'  · {line}')
    if gaps:
        return 1

    _write_json(elements, a.elements)
    _write_json(notes, a.notes)
    n_unreadable = sum(1 for r in rows if r['status'] == 'unreadable')
    print(f'→ 已写出 {a.elements}（元素 {len(elements)}）与 {a.notes}（补注 {len(notes)} 条，'
          f'其中读不动 {n_unreadable} 份）：材料 {len(materials)} 份 · 解析器 {" → ".join(ADAPTERS)}')

    if a.ledger:
        cmd = [sys.executable, str(SCRIPTS / 'ledger.py'), '--materials', a.materials,
               '--elements', a.elements, '--notes', a.notes, '--task', a.task,
               '--quote-limit', str(a.quote_limit), '-o', a.ledger]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        except (OSError, subprocess.SubprocessError) as e:
            print(f'⚠ ledger 起不来 {type(e).__name__}: {e}', file=sys.stderr)
            return 2
        if r.returncode != 0:
            print(f'⚠ ledger 退 {r.returncode}：{_last_line(r.stderr) or _last_line(r.stdout)}',
                  file=sys.stderr)
            return 2
        print(f'  · {_last_line(r.stdout) or _last_line(r.stderr)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
