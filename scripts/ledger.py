# -*- coding: utf-8 -*-
r"""ledger.py — 证据账本写入器（PIPELINE-SPEC §2）：把 `materials[]` / `elements[]` 组装成 `evidence.json`。

**为什么单独一步**：账本是**下游唯一的事实源**（§2.5：下游只许引用 id，不许回头读原文件），
所以它的写盘契约必须可复现 — 同输入两次必须**同字节**（幂等）、键序固定、**降级必须留痕**。

**协作走产物**（本仓分层纪律：模块层之间不许互相 import）：本脚本**不 import probe.py**，
而是读它输出的 JSON：`python scripts/probe.py <路径> --json | ...` → `ledger.py --materials <那个 JSON>`。

**材料层补注（`--notes`）**：材料层由 `probe.py` 起头（档位 / 魔数依据），但"这份到底读没读出来、
走的是哪条路"只有**解析阶段**知道——`probe` 看到的 legacy 与"能读的 legacy"长得一模一样。
所以适配器另写一份补注（`{material_id, status?, reason?, extractor?}`），由本脚本落到材料层：
`extractor` 记走了哪条路（`py:docx` / `soffice+py:docx` / `vlm`），读不动的记 `status=unreadable` +
**可执行**原因（§1.3 的 T4 记账）。补注**只许改这三个字段**（键封闭），且落完**再校一次**。

退出码：0 = 写出；1 = **校验不过**（输入不符合 §2 的模型，不落盘）；2 = 输入读不了。
"""
import argparse
import json
import sys
from pathlib import Path

import capability
import artifact

SCHEMA = 'evidence/1'
KINDS = ('heading', 'paragraph', 'list_item', 'table', 'figure', 'caption', 'code', 'sheet', 'cell')
TIERS = ('T1', 'T2', 'T3', 'T4')
STATUSES = ('ok', 'unreadable', 'skipped')
CERTAINTIES = ('direct', 'inferred')

# §2.1 的键序**写死在这里**：键序固定是"幂等"的一半（另一半是不依赖输入顺序做决策）。
# `root` 在 `mtime` 后（§2.1 字段序）——2026-09-21 补：漏了它，`evidence.json` 就丢"材料根"，
# `probe --verify` 的"根下多了没入账的新文件"半条判据随之静默跳过（G28）。
MATERIAL_KEYS = ('id', 'path', 'sha256', 'bytes', 'mtime', 'root', 'tier', 'kind', 'probe',
                 'status', 'reason', 'extractor')
ELEMENT_KEYS = ('id', 'material_id', 'kind', 'text', 'rows', 'location', 'extractor', 'certainty', 'degraded')
LOCATION_KEYS = ('path', 'page', 'sheet', 'cell', 'bbox', 'quote')
# 材料类型（§2.1 封闭枚举）：**与 `probe.py` 的 `KINDS` 同一份口径**——改一处必须改另一处，
# 所以这里只做校验，不在这里重新推导。
MATERIAL_KINDS = ('docx', 'xlsx', 'pptx', 'ole', 'pdf-text', 'pdf-scan', 'image', 'text', 'unknown')
# 材料层补注（解析阶段对现场事实的记账）：只许改这三个字段——补注不是"重写材料卡片"。
NOTE_KEYS = ('material_id', 'status', 'reason', 'extractor')


def _read_json(path):
    """读 JSON（容忍 BOM — PowerShell 的 `Out-File -Encoding utf8` 会写 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def check_materials(items):
    """材料层校验 → 错误清单（空 = 过）。逐条说清**哪里错了**，不返回布尔。"""
    errs, seen = [], set()
    for i, m in enumerate(items):
        if not isinstance(m, dict):
            errs.append(f'materials[{i}]: 不是对象')
            continue
        where = m.get('id') or f'materials[{i}]'
        for k in ('id', 'path', 'sha256', 'bytes', 'mtime', 'root', 'tier', 'kind', 'probe', 'status'):
            if k not in m:
                errs.append(f'{where}: 缺必填字段 {k}')
        if m.get('kind') not in MATERIAL_KINDS:
            errs.append(f'{where}: kind 只能是 {"/".join(MATERIAL_KINDS)}，实际 {m.get("kind")!r}'
                        f'（材料类型由 `probe.py` 判一次，别处不许按扩展名重判）')
        if m.get('id') in seen:
            errs.append(f'{where}: id 重复')
        seen.add(m.get('id'))
        if m.get('tier') not in TIERS:
            errs.append(f'{where}: tier 只能是 {"/".join(TIERS)}，实际 {m.get("tier")!r}')
        if m.get('status') not in STATUSES:
            errs.append(f'{where}: status 只能是 {"/".join(STATUSES)}，实际 {m.get("status")!r}')
        if m.get('status') == 'unreadable' and not m.get('reason'):
            errs.append(f'{where}: status=unreadable 必须给 reason')
    return errs


def check_elements(items, material_ids):
    """证据层校验 → 错误清单。`kind` 是**封闭枚举**（§2.1），扩枚举要先改规范。"""
    errs, seen = [], set()
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            errs.append(f'elements[{i}]: 不是对象')
            continue
        where = e.get('id') or f'elements[{i}]'
        for k in ('id', 'material_id', 'kind', 'location', 'extractor', 'certainty'):
            if k not in e:
                errs.append(f'{where}: 缺必填字段 {k}')
        if e.get('id') in seen:
            errs.append(f'{where}: id 重复')
        seen.add(e.get('id'))
        if e.get('kind') not in KINDS:
            errs.append(f'{where}: kind 不在封闭枚举内（{e.get("kind")!r}）')
        if e.get('certainty') not in CERTAINTIES:
            errs.append(f'{where}: certainty 只能是 {"/".join(CERTAINTIES)}，实际 {e.get("certainty")!r}')
        if e.get('extractor') == 'vlm' and e.get('certainty') != 'inferred':
            # §1.3：视觉读数是**推断**，不许伪装成直取——这条能机器拦，就别只写在规范里
            errs.append(f'{where}: extractor=vlm 必须 certainty=inferred（视觉推断不许伪装成直取）')
        if e.get('material_id') not in material_ids:
            errs.append(f'{where}: material_id {e.get("material_id")!r} 不在 materials[] 里')
        loc = e.get('location')
        if not isinstance(loc, dict) or 'path' not in loc:
            errs.append(f'{where}: location 必须是对象且含 path')
    return errs


def degrade(elements, limit):
    """§2.4 的降级：`quote` 超限就截断 + 标 `degraded`（**不许静默截断**）。返回降级条数。"""
    n = 0
    for e in elements:
        loc = e.get('location')
        quote = loc.get('quote') if isinstance(loc, dict) else None
        if isinstance(quote, str) and len(quote) > limit:
            loc['quote'] = quote[:limit] + '…'
            # **追加**，不许覆盖：上游（解析适配器）可能已经标过采样/截断
            e['degraded'] = (e.get('degraded') + '；' if e.get('degraded') else '') + f'quote 截断到 {limit} 字'
            n += 1
    return n


def check_notes(items, material_ids):
    """材料层补注校验 → 错误清单。**键封闭**：补注只许改 `status` / `reason` / `extractor` 三个字段。"""
    errs = []
    for i, n in enumerate(items):
        if not isinstance(n, dict):
            errs.append(f'notes[{i}]: 不是对象')
            continue
        mid = n.get('material_id')
        if not mid:
            errs.append(f'notes[{i}]: 缺 material_id')
        elif mid not in material_ids:
            errs.append(f'notes[{i}]: material_id {mid!r} 不在 materials[] 里')
        for k in n:
            if k not in NOTE_KEYS:
                errs.append(f'notes[{i}]({mid}): 不许写字段 {k}（补注只能改 {"、".join(NOTE_KEYS[1:])}）')
        if n.get('status') is not None and n['status'] not in STATUSES:
            errs.append(f'notes[{i}]({mid}): status 只能是 {"/".join(STATUSES)}，实际 {n["status"]!r}')
        if n.get('status') == 'unreadable' and not n.get('reason'):
            errs.append(f'notes[{i}]({mid}): status=unreadable 必须给 reason（读不动不给理由 = 静默降级）')
    return errs


def apply_notes(materials, notes):
    """把补注落到材料层（**就地改**）→ `(改了几条, 读不动几份, 覆盖清单)`。

    为什么要有这一手：`probe.py` 只能给**档位**（T2 的 legacy 与"能读的 legacy"在探测阶段长得一样），
    "这份到底读没读出来、走的是哪条路"只有解析阶段知道（§1.4 的 `extractor`、§1.3 的 T4 记账）。
    补注是**唯一**把这条现场事实送回账本的路——没有它，读不动的材料在账本上就是"tier=T2 / status=ok /
    零证据"，看着像能读却没内容。

    **后一条覆盖前一条，但覆盖要报出来**：流水线顺序是"机器抽取 → 视觉补证"，
    所以视觉那条把 `unreadable` 改成 `ok` 是**预期**的；可如果只按命令行顺序静默覆盖，
    换个参数次序结论就变了——那是"没人知道哪来的记录"的另一种形态。所以**补注之间**的覆盖逐条记下
    （probe 给的初值被第一条补注改写不算覆盖，那是正常路径）。
    """
    by_id = {m.get('id'): m for m in materials}
    n_unreadable, overrides, touched = 0, [], set()
    for note in notes:
        m = by_id.get(note.get('material_id'))
        if m is None:
            continue
        mid, before = m.get('id'), m.get('status')
        for k in NOTE_KEYS[1:]:
            if k in note and note[k] is not None:
                m[k] = note[k]
        if m.get('status') == 'ok' and 'reason' in m:
            del m['reason']                         # 补注把状态改回 ok ⇒ 旧的 reason 就是陈旧真值，删掉
        if mid in touched and before != m.get('status'):
            overrides.append(f'{mid}: {before} → {m.get("status")}'
                             f'（{note.get("extractor") or "补注"}）')
        touched.add(mid)
        if m.get('status') == 'unreadable':
            n_unreadable += 1
    return len(notes), n_unreadable, overrides


def assemble(task, materials, elements):
    """按 §2.1 的键序组装账本：**多余的键一律丢弃**（模型封闭，不许夹带）。"""
    out_elems = []
    for e in elements:
        o = {k: e[k] for k in ELEMENT_KEYS if k in e}
        if isinstance(o.get('location'), dict):
            o['location'] = {k: o['location'][k] for k in LOCATION_KEYS if k in o['location']}
        out_elems.append(o)
    return {
        'schema': SCHEMA,
        'task': task,
        # **能力指纹**（2026-09-19 补，§2.1）：这本账是哪一版机制产的。机制一改而账本没重跑，
        # 账本**一个字节都不变**——消费端（`query` / `plan`）靠这个字段才喊得出来。
        'capability': capability.stamp(),
        'materials': [{k: m[k] for k in MATERIAL_KEYS if k in m} for m in materials],
        'elements': out_elems,
    }


def dump(ledger, path):
    """写盘契约（§2.4）：UTF-8 / **LF** / 缩进 2 / 中文不转义 / 末尾一个换行。返回字节数。"""
    text = json.dumps(ledger, ensure_ascii=False, indent=2) + '\n'
    data = text.encode('utf-8')          # json 用 \n；用 write_bytes 躲开平台的 CRLF 转换
    Path(path).write_bytes(data)
    return len(data)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')  # 摘要/报错走 stderr，同样要定编码（GBK 控制台会乱码）
    ap = argparse.ArgumentParser(description='L0 证据账本写入器（PIPELINE-SPEC §2）')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('--elements', action='append', default=[],
                    help='证据层 JSON（解析适配器 / vlm 骨架的输出；多份可重复给，逐份按序合并）')
    ap.add_argument('--notes', action='append', default=[],
                    help='材料层补注 JSON（解析适配器的 --notes 输出；多份可重复给，逐份按序落）')
    ap.add_argument('--task', default='', help='任务名（一般取成果根名）')
    ap.add_argument('-o', '--out', help='写到哪里（默认：与 --materials 同目录的 evidence.json）')
    ap.add_argument('--quote-limit', type=int, default=200, help='quote 截断上限（默认 200 字）')
    a = ap.parse_args(argv)
    # **默认落盘跟着输入走**（D-119）：账本住成果根，而 `--materials` 也在那儿（见 `artifact.beside`）。
    a.out = a.out or str(artifact.beside(a.materials, 'evidence.json'))

    try:
        materials = _read_json(a.materials)
        elements = []
        for p in a.elements:                    # 证据可以来自多条路（机器适配器 + vlm），逐份合并
            got = _read_json(p)
            if not isinstance(got, list):
                print(f'⚠ 证据必须是 JSON 数组（elements[]）: {p}', file=sys.stderr)
                return 2
            elements += got
        notes = []
        for p in a.notes:                       # 每份补注**单独校形状**：拿对象冒充数组会在下面变成
            got = _read_json(p)                 # "notes[0]: 不是对象"这种把真正的错因藏起来的报错
            if not isinstance(got, list):
                print(f'⚠ 补注必须是 JSON 数组（notes[]）: {p}', file=sys.stderr)
                return 2
            notes += got
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    mids = {m.get('id') for m in materials}
    errs = (check_materials(materials) + check_elements(elements, mids) + check_notes(notes, mids))
    if errs:
        print('⚠ 账本校验未过（先修输入，**不落盘**）:')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1

    n_applied, n_unreadable, overrides = apply_notes(materials, notes)
    errs = check_materials(materials)                       # 补注之后**再校一次**：unreadable 必须有 reason
    if errs:
        print('⚠ 补注把材料层改坏了（先修补注，**不落盘**）:')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1

    n = degrade(elements, a.quote_limit)
    total_deg = sum(1 for e in elements if e.get('degraded'))
    size = dump(assemble(a.task, materials, elements), a.out)
    # **两个数分开报**（2026-09-18 修）：`n` 只是"本次因 quote 超限被截断"的条数，而账本里带
    # `degraded` 留痕的元素还包括上游适配器与 vlm 通道给的（真实材料集实测：文件里 22 条，
    # 而这一行只报 13 —— 读的人会以为"全账本只有 13 条降级"，那是**读数说谎**）。
    tail = f' · 本次 quote 截断 {n} 条' if n else ''
    note = f' · 材料补注 {n_applied} 条（读不动 {n_unreadable} 份）' if n_applied else ''
    print(f'→ 已写出 {a.out}：材料 {len(materials)} · 证据 {len(elements)}'
          f' · 带降级留痕 {total_deg} 条{tail}{note} · {size} 字节')
    for x in overrides:                             # 覆盖**必须报**：不报就等于结论取决于命令行次序
        print(f'  · 补注覆盖 {x}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
