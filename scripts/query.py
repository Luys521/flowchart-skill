# -*- coding: utf-8 -*-
r"""query.py — **点名取子集**（PIPELINE-SPEC §5.3）：在**已抽取**的账本上按"哪份材料、哪一片、含哪个词"
取一小批证据，**只回这一批 + 下一批的游标**。

**它解决什么**：§5 的循环里，AI 常处在"我知道缺口在 `M06`，但它的 30 条证据一条都不能整份灌进上下文"。
`drift.py` 的缺口清单只说"要哪一片"，**真正去取那一片的手**就是本脚本。三件事一起做到：
**看得到**（每条都带 `id` 与出处）、**看得少**（`--batch` 一批一小口，末尾给 `--skip` 游标）、
**不打乱事实源**（只读账本，不重解析、不改任何产物——同输入同输出）。

**这一版只查不抽**（刻意的）：抽取侧的范围限制（`parse.py --pages/--rows`）是另一件事，
它省的是**解析代价**；而本文省的是**上下文窗口**，两者不是一回事——账本再大也在盘上，
真正稀缺的是"这次给模型看几条"。所以：**先能点名，再谈抽取时收窄**。

**坐标与范围的语法**（`--range`，可重复给，多个之间是"或"）：

| 写法 | 含义 | 谁有 |
|---|---|---|
| `pages=40-60` / `pages=7` | `location.page`（1 起，闭区间） | PDF（`parse_pdf`） |
| `lines=100-200` | **该材料内第 N 条元素**（1 起，按账本里的阅读序） | 全部（通用兜底） |
| `sheet=清单` | `location.sheet`（子表名，逐字相等） | xlsx（`parse_ooxml`） |
| `rows=100-200` | **只影响显示**：表格类证据只打这几行（选择仍是整条） | `kind=sheet` / `table` 的证据 |

`rows=` 与另外三个**分工不同**：另外三个决定"哪几条被选中"，它决定"选中的那条里给哪几行"——
一张 10 万行的测算表是一条证据，不裁行就等于把整张表倒进上下文。它**不参与选择**，所以
只给 `--range rows=…` 时不会把命中数筛成 0。

`--grep` 在 `text` / `rows` 全部单元格 / `location.quote` 上做**朴素子串匹配**（大小写不敏感）——
不做分词、不做模糊匹配：判语义是 AI 的事，脚本只保证"给的这批里确实含这个词"（对齐 §0 责任边界）。

用法：
    python scripts/query.py evidence.json --material M06 --batch 10
    python scripts/query.py evidence.json --material M06 --grep 审批 --batch 5 --skip 10
    python scripts/query.py evidence.json --range pages=40-60 --chars 300
    python scripts/query.py evidence.json --material M06 --json      # 给子代理/管道吃

**账本上的能力指纹要核**（§1.2）：账本记着"这是哪一版机制产的"，对不上就在最前面喊一句
（`--json` 时进 `capability` 字段）——机制改了而账本没重跑，账本**一个字节都不变**，不喊就没人知道。
**只喊不拦**：拦着读等于不让人取证（"我明知它旧，偏要看一眼"是合法需求）；要硬拦用
`python scripts/capability.py check evidence.json`。

退出码：0 = 查完（**0 条命中也是 0**：那是结论，不是错误）；2 = 账本读不了 / 参数不合语法。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from textquality import element_haystack
import capability
from semantics import DICT_NAME

# 默认值 = "人给的圆整默认"，`dictionary.yaml` 的 `query:` 段按名覆盖（数值只有一个家，§1.2）。
DEFAULTS = {
    'batch': 20,     # 一次给几条（"渐进式批量"的那一口）
    'chars': 120,    # 每条摘录截到多少字（够认出"是不是我要找的"，不够就再点名要全文）
}
COLUMNS = ('id', '材料', '种类', '位置', '摘录')
RANGE_RE = re.compile(r'^(pages|lines|sheet|rows)=(.*)$')
SEL_KINDS = ('pages', 'lines', 'sheet')       # 决定"哪几条被选中"；`rows` 只管显示（见 docstring）


# ----------------------------------------------------------------逐条取字段（都在一处，免得各写一份口径）
def parse_range(spec):
    """`'pages=40-60'` → `('pages', 40, 60)`；`'sheet=清单'` → `('sheet', '清单', '清单')`。

    语法错就抛 `ValueError`（**不猜**）：范围写歪了还照跑，等于静默换了口径。
    """
    m = RANGE_RE.match(str(spec or '').strip())
    if not m:
        raise ValueError(f'范围写法不认：{spec!r}（应为 pages=40-60 / lines=1-50 / sheet=清单）')
    kind, val = m.group(1), m.group(2).strip()
    if kind == 'sheet':
        if not val:
            raise ValueError('sheet= 后面要给子表名')
        return kind, val, val
    m2 = re.fullmatch(r'(\d+)(?:-(\d+))?', val)
    if not m2:
        raise ValueError(f'{kind}= 后面应为 N 或 A-B（1 起，闭区间），实际 {val!r}')
    a = int(m2.group(1))
    b = int(m2.group(2)) if m2.group(2) else a
    if b < a:
        raise ValueError(f'{kind}={a}-{b}：上界小于下界')
    return kind, a, b


def in_range(el, ordinal, ranges):
    """这条落在任一范围里吗（`ranges` 为空 = 不筛）。`ordinal` 是该材料内第几条（1 起）。"""
    if not ranges:
        return True
    loc = el.get('location') or {}
    for kind, a, b in ranges:
        if kind == 'lines' and a <= ordinal <= b:
            return True
        if kind == 'pages' and isinstance(loc.get('page'), int) and a <= loc['page'] <= b:
            return True
        if kind == 'sheet' and str(loc.get('sheet') or '') == a:
            return True
    return False


def matches(el, material, grep):
    """材料号与关键词两关（都为空 = 不筛）。可搜面来自公共层（与 `parse.py --grep` 同一句）。"""
    if material and el.get('material_id') not in material:
        return False
    return not grep or grep.lower() in element_haystack(el)


def loc_text(el):
    """`location` → 一句人能读的位置（页 / 子表!单元格 / 图内坐标 / 实在没有就报"没有出处"）。"""
    loc = el.get('location') or {}
    bits = []
    if loc.get('sheet'):
        bits.append(f'表「{loc["sheet"]}」' + (f'!{loc["cell"]}' if loc.get('cell') else ''))
    if isinstance(loc.get('page'), int):
        bits.append(f'第 {loc["page"]} 页')
    if loc.get('bbox'):
        bits.append('图内 ' + ','.join(f'{float(x):.2f}' for x in loc['bbox']))
    return ' · '.join(bits) or '—'


def excerpt(el, limit, rwin=None):
    """一条证据的**短摘录**：有正文用正文；表格给"行×列 + 头一行"；都没有就用 id（不装空）。

    `rwin=(a, b)` 是**表格的显示窗口**（`--range rows=…`）：只打这几行，并写明"共几行、这是第几段"——
    不写就会让人以为这张表只有这么几行（§2.3"截断处必须留省略标记"同一条）。
    """
    rows = el.get('rows') or []
    text = str(el.get('text') or '').strip()
    if rows and rwin:
        a, b = max(1, rwin[0]), rwin[1]
        part = rows[a - 1:b]
        body = ' ⏎ '.join(' / '.join(str(c) for c in (r if isinstance(r, list) else [r])) for r in part)
        text = f'共 {len(rows)} 行，本批第 {a}–{min(b, len(rows))} 行：{body}'
    elif not text and rows:
        head = ' / '.join(str(c) for c in (rows[0] if isinstance(rows[0], list) else [rows[0]]))
        text = f'{len(rows)} 行 × {len(rows[0]) if isinstance(rows[0], list) else 1} 列：{head}'
    if not text:
        text = str(el.get('id') or '')
    text = ' '.join(text.split())                     # 压成单行：表格单元格里的换行会撕表
    return text[:limit] + ('…' if len(text) > limit else '')


# ----------------------------------------------------------------筛选与渲染
def select(els, material, grep, ranges, skip, batch):
    """账本元素 → `(这一批的行, 命中总数)`。顺序 = 账本原序（阅读序），**同输入同输出**。"""
    rows, seen = [], {}
    for el in els:
        mid = el.get('material_id')
        seen[mid] = seen.get(mid, 0) + 1
        if matches(el, material, grep) and in_range(el, seen[mid], ranges):
            rows.append((mid, seen[mid], el))
    return rows[skip:skip + batch], len(rows)


def render(rows, total, meta, limit, rwin=None):
    """这一批（markdown）+ **游标行**——AI 靠它决定"要不要再要一口"，而不是一次把全部灌进去。"""
    out = [f'# 取子集：{meta["what"]}', '',
           f'> `scripts/query.py` 从 `{meta["ledger"]}`（sha256 {meta["sha"]}）取子集：'
           f'命中 {total} 条，本次给第 {meta["skip"] + 1}–{meta["skip"] + len(rows)} 条'
           f'（每批 {meta["batch"]} 条，摘录截到 {limit} 字）。**只看这一批就够判断吗？**', '',
           '| ' + ' | '.join(COLUMNS) + ' |', '|' + '---|' * len(COLUMNS)]
    for mid, ordinal, el in rows:
        out.append(f'| `{el.get("id")}` | `{mid}` #{ordinal} | {el.get("kind")} | '
                   f'{loc_text(el)} | {excerpt(el, limit, rwin)} |')
    nxt = meta['skip'] + len(rows)
    out += ['', f'▶ 下一批：`--skip {nxt}`' if nxt < total else '▶ 已到末尾（这一批就是全部命中）']
    return '\n'.join(out) + '\n'


def load_defaults(path=None):
    """默认值 = 内置 + `dictionary.yaml` 的 `query:` 段（读不到就用内置，**不报错**）。"""
    th = dict(DEFAULTS)
    p = Path(path) if path else Path(__file__).with_name(DICT_NAME)
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            got = (yaml.safe_load(fh) or {}).get('query') or {}
    except Exception:                                # 缺依赖 / 缺文件 / 坏 YAML：一律退回内置
        return th
    for k, v in got.items():
        if k in th and isinstance(v, int) and not isinstance(v, bool) and v > 0:
            th[k] = v
    return th


def main(argv=None):
    """命令行入口：读账本 → 解析范围 → 取一批 → 打印（或 `--json`）。"""
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='点名取子集：在账本上按材料/范围/关键词取一小批（PIPELINE-SPEC §5.3）')
    ap.add_argument('ledger', help='证据账本 evidence.json')
    ap.add_argument('--material', help='只要这几份（`M03` 或 `M03,M15`）')
    ap.add_argument('--grep', default='', help='朴素子串匹配（正文 / 表格单元格 / 出处摘录）')
    ap.add_argument('--range', action='append', default=[], dest='ranges',
                    help='范围，可重复：pages=40-60 · lines=100-200 · sheet=清单 · rows=100-200（只见显示）')
    ap.add_argument('--skip', type=int, default=0, help='从第几条开始（配合上一批打印的游标；0 起数）')
    ap.add_argument('--batch', type=int, help=f'这一批给几条（默认 {DEFAULTS["batch"]}）')
    ap.add_argument('--chars', type=int, help=f'每条摘录截到多少字（默认 {DEFAULTS["chars"]}）')
    ap.add_argument('--dict', help='dictionary.yaml（默认取 scripts/ 下那份）')
    ap.add_argument('--json', action='store_true', help='输出 JSON（给子代理 / 管道吃）')
    a = ap.parse_args(argv)

    th = load_defaults(a.dict)
    # 「没给」与「给了 0」是两回事：用 `or` 会把 `--batch 0` 悄悄换成默认值，下面那句守卫就永远轮不到
    batch = th['batch'] if a.batch is None else a.batch
    limit = th['chars'] if a.chars is None else a.chars
    if batch <= 0 or a.skip < 0 or limit <= 0:
        print('✗ --batch / --chars 要比 0 大，--skip 不能是负数')
        return 2
    try:
        got = [parse_range(x) for x in a.ranges]
    except ValueError as e:
        print(f'✗ {e}')
        return 2
    ranges = [r for r in got if r[0] in SEL_KINDS]        # `rows=` 只管显示，不参与选择
    rwin = next(((r[1], r[2]) for r in got if r[0] == 'rows'), None)
    text = Path(a.ledger).read_text(encoding='utf-8-sig')
    try:
        led = json.loads(text)
    except ValueError as e:
        print(f'✗ 账本不是合法 JSON（{e}）')
        return 2
    if not isinstance(led, dict) or not isinstance(led.get('elements'), list):
        print('✗ 这不是账本：顶层要有 `elements[]`（`probe → parse → ledger` 的产物）')
        return 2
    mid = {x.strip() for x in (a.material or '').split(',') if x.strip()}
    rows, total = select(led['elements'], mid, a.grep, ranges, a.skip, batch)
    meta = {'ledger': a.ledger,
            'sha': hashlib.sha256(text.encode('utf-8')).hexdigest()[:12],
            'skip': a.skip, 'batch': batch,
            'what': ' · '.join(x for x in (
                f'材料 {"、".join(sorted(mid))}' if mid else '',
                f'含「{a.grep}」' if a.grep else '',
                '范围 ' + '、'.join(a.ranges) if a.ranges else '') if x) or '全部证据'}
    cap_state, cap_detail = capability.compare(capability.read_json(led))
    if a.json:
        print(json.dumps({'total': total, 'skip': a.skip, 'given': len(rows),
                          'next_skip': a.skip + len(rows) if a.skip + len(rows) < total else None,
                          'what': meta['what'], 'ledger_sha256': meta['sha'],
                          # **机器可读的那份提醒**（2026-09-19）：JSON 里多一个键，
                          # 而不是往 stdout 插一行——插一行会让吃这份 JSON 的子代理当场解析失败。
                          'capability': {'state': cap_state, 'detail': cap_detail},
                          'rows': [{'id': el.get('id'), 'material': m, 'ordinal': n,
                                    'kind': el.get('kind'), 'location': loc_text(el),
                                    'excerpt': excerpt(el, limit, rwin)} for m, n, el in rows]},
                         ensure_ascii=False, indent=2))
        return 0
    for line in capability.warn(capability.read_json(led), f'账本 `{a.ledger}`'):
        print(line)                       # 人读那份：**打在最前面**，别让人读到一半才发现它按的是旧判据
    print(render(rows, total, meta, limit, rwin), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
