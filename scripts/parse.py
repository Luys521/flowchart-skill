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

**冲突与漏认都退 1**（两条都是"仪器发现真问题"，不是可忽略的噪声）：
- **冲突**：同一个 element id 被两个适配器产出（判档重叠），或两份补注对同一材料给出不同的
  `status`/`reason`/`extractor`——静默取一个会让账本里出现"没人知道哪来的"记录；
- **漏认**：`probe` 说这份 status=ok，却**既没有元素、也没有补注**（例如纯文本 `.txt` 至今没有适配器）
  ——那正是上一轮补掉的洞（"能读却没内容"），不许再让它静默流进账本。

退出码：0 = 跑完（**可能有读不动的材料**，补注里逐份给了原因）；1 = 冲突 / 漏认（不写产物）；
2 = 输入读不了 / 适配器起不来 / 适配器报错。
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# 分派表：**只有顺序，没有判据**（判据在各适配器内部，它们各自认领、各自跳过）。
# 顺序 = 产物顺序的一部分，改它等于改账本字节，所以它是常量、不随环境变。
ADAPTERS = ('parse_ooxml', 'parse_pdf', 'parse_legacy')


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
        return ['--max-rows', str(a.max_rows), '--max-cols', str(a.max_cols)]
    if name == 'parse_pdf':
        return ['--max-pages', str(a.max_pages), '--max-chars', str(a.max_chars)]
    if name == 'parse_legacy':
        args = ['--timeout', str(a.timeout)]
        return args + (['--soffice', a.soffice] if a.soffice else [])
    return []


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


def survey(materials, elements, notes):
    """材料层 × 证据 × 补注 → `(每份材料一行, 漏认清单)`。**漏认 = status=ok 却既无元素也无补注。**"""
    counts, note_of = {}, {}
    for e in elements:
        counts[e.get('material_id')] = counts.get(e.get('material_id'), 0) + 1
    for n in notes:
        note_of[n.get('material_id')] = n
    rows, gaps = [], []
    for m in materials:
        mid, n = m.get('id'), note_of.get(m.get('id'), {})
        status = n.get('status') or m.get('status')
        row = {'id': mid, 'tier': m.get('tier'), 'status': status,
               'extractor': n.get('extractor') or m.get('extractor') or '',
               'elements': counts.get(mid, 0), 'reason': n.get('reason') or m.get('reason') or ''}
        rows.append(row)
        if status == 'ok' and not row['elements'] and not note_of.get(mid):
            gaps.append(mid)
    return rows, gaps


def _print_survey(rows, gaps, verbose):
    """人读摘要：一份材料一行。**没有证据也没有补注的当场标出来**（那是漏认，不是"空材料"）。"""
    print(f'{"材料":<5}{"档":<4}{"状态":<11}{"谁产的":<22}{"元素":>5}  原因')
    for r in rows:
        mark = ' ⚠' if r['id'] in gaps else ''
        print(f'{r["id"]:<5}{r["tier"]:<4}{r["status"]:<11}{r["extractor"] or "-":<22}'
              f'{r["elements"]:>5}  {r["reason"][:56]}{mark}')
    if gaps:
        print(f'⚠ 漏认 {len(gaps)} 份（probe 说能读，却没有适配器认领，也没有补注说明）：{"、".join(gaps)}')
        if verbose:
            print('  处置：给这一类材料补一个适配器，或在补注里如实记 unreadable + 原因——'
                  '不许让它带着 status=ok / 零证据进账本（§1.3）。')


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
    ap.add_argument('--max-pages', type=int, default=50, help='[parse_pdf] 最多抽多少页')
    ap.add_argument('--max-chars', type=int, default=4000, help='[parse_pdf] 单页最多多少字')
    ap.add_argument('--soffice', help='[parse_legacy] 显式指定转换器命令')
    ap.add_argument('--timeout', type=int, default=180, help='[parse_legacy] 单份材料转换 / 抽取超时秒数')
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
    with tempfile.TemporaryDirectory(prefix='parse_dispatch_') as td:
        for name in ADAPTERS:
            elements, notes, brief, err = run_adapter(name, a.materials, td, _adapter_args(name, a))
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

    rows, gaps = survey(materials, elements, notes)
    if a.verbose:
        for line in briefs:
            print(f'  · {line}', file=sys.stderr)
    _print_survey(rows, gaps, a.verbose)
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
