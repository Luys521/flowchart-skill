# -*- coding: utf-8 -*-
r"""ledger.py — 证据账本写入器（PIPELINE-SPEC §2）：把 `materials[]` / `elements[]` 组装成 `evidence.json`。

**为什么单独一步**：账本是**下游唯一的事实源**（§2.5：下游只许引用 id，不许回头读原文件），
所以它的写盘契约必须可复现 — 同输入两次必须**同字节**（幂等）、键序固定、**降级必须留痕**。

**协作走产物**（本仓分层纪律：模块层之间不许互相 import）：本脚本**不 import probe.py**，
而是读它输出的 JSON：`python scripts/probe.py <路径> --json | ...` → `ledger.py --materials <那个 JSON>`。

退出码：0 = 写出；1 = **校验不过**（输入不符合 §2 的模型，不落盘）；2 = 输入读不了。
"""
import argparse
import json
import sys
from pathlib import Path

SCHEMA = 'evidence/1'
KINDS = ('heading', 'paragraph', 'list_item', 'table', 'figure', 'caption', 'code', 'sheet', 'cell')
TIERS = ('T1', 'T2', 'T3', 'T4')
STATUSES = ('ok', 'unreadable', 'skipped')
CERTAINTIES = ('direct', 'inferred')

# §2.1 的键序**写死在这里**：键序固定是"幂等"的一半（另一半是不依赖输入顺序做决策）。
MATERIAL_KEYS = ('id', 'path', 'sha256', 'bytes', 'mtime', 'tier', 'probe', 'status', 'reason', 'extractor')
ELEMENT_KEYS = ('id', 'material_id', 'kind', 'text', 'rows', 'location', 'extractor', 'certainty', 'degraded')
LOCATION_KEYS = ('path', 'page', 'sheet', 'cell', 'bbox', 'quote')


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
        for k in ('id', 'path', 'sha256', 'bytes', 'mtime', 'tier', 'probe', 'status'):
            if k not in m:
                errs.append(f'{where}: 缺必填字段 {k}')
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
            e['degraded'] = f'quote 截断到 {limit} 字'
            n += 1
    return n


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
    ap.add_argument('--elements', help='证据层 JSON（解析适配器的输出；没有就写空表）')
    ap.add_argument('--task', default='', help='任务名（一般取成果根名）')
    ap.add_argument('-o', '--out', default='evidence.json', help='写到哪里（默认 evidence.json）')
    ap.add_argument('--quote-limit', type=int, default=200, help='quote 截断上限（默认 200 字）')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
        elements = _read_json(a.elements) if a.elements else []
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list) or not isinstance(elements, list):
        print('⚠ 输入必须是 JSON 数组（materials[] / elements[]）', file=sys.stderr)
        return 2

    errs = check_materials(materials) + check_elements(elements, {m.get('id') for m in materials})
    if errs:
        print('⚠ 账本校验未过（先修输入，**不落盘**）:')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1

    n = degrade(elements, a.quote_limit)
    size = dump(assemble(a.task, materials, elements), a.out)
    tail = f' · 降级 {n} 条' if n else ''
    print(f'→ 已写出 {a.out}：材料 {len(materials)} · 证据 {len(elements)}{tail} · {size} 字节')
    return 0


if __name__ == '__main__':
    sys.exit(main())
