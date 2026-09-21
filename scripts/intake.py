# -*- coding: utf-8 -*-
r"""intake.py — L1 清点（PIPELINE-SPEC §3）：`evidence.json` → `intake.md`（材料卡片）+ 卡片校验器。

**分工**（与 `recon.py` 同一条线：**脚本只执行，不承载判断**）：
- **机器填**：材料（`M##` + 文件名）· 档位（**从账本抄，不重判**）· 读不动（抄 `materials[].reason`）·
  **`重复` 关系**（§3 判重只看 `sha256`，这是纯事实，不是判断）；
- **AI 填**：主题（标 `⚠`）· 含流程（`是`/`否` 必须标 `⚠` 并给理由）· 互补 / 替代 / 无关 · 依据。
骨架里 AI 那几格写 `—`：**"没填"与"填了"必须能分辨**，否则一张空卡片也能过校验。

两张表各司其职：`build` 出的骨架给 AI 填；`check` 只认**收口后**的卡片——它查两件事（§8 登记的那两条），
外加取值封闭与"推断必须留痕"：
1. **卡片与账本一致**：材料一一对应、档位逐字相等、读不动逐字等于 `materials[].reason`（空写 `—`）；
2. **版本关系双向一致**（§3）：`A 互补(B) ⇔ B 互补(A)`、`A 替代(B) ⇔ B 被替代(A)`，
   `A 重复(B)` 必须 `sha256` 相同且 `B` 的编号更小（"只保留 `M##` 小者，另一条标副本"）。

**不查 element id 存不存在**：那是 **H10.1** 的活（§6 明说"任何产物里出现的每个 element id 都必须在账本里存在"），
在这里再写一份 id 提取就是两份真值。本脚本只查"有证据的材料必须填依据"。

用法：
    python scripts/intake.py build evidence.json -o intake.md
    python scripts/intake.py check intake.md --ledger evidence.json

退出码：0 = 过（check）/ 写出（build）；1 = 卡片有问题（**只报，不改**）；2 = 输入读不了。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cells
import flowtable_check
import artifact

COLUMNS = ('材料', '档位', '主题', '含流程', '版本关系', '读不动', '依据')
# 「AI 要填的格子」的登记：`cells.py fill` 按**列名**回写（AI 不再手改表格，见 `cells.py` 的文件头）
TODO_TABLES = (cells.table('材料卡片', '材料', {
    '主题': {'列': '主题'},
    '含流程': {'列': '含流程'},
    '版本关系': {'列': '版本关系'},
    '依据': {'列': '依据'}},
    {'含流程': ['是', '否', '不确定'],
     '版本关系': ['独立', '不确定', '重复(M##)', '互补(M##)', '替代(M##)', '被替代(M##)', '无关(M##)']}),)
RELATIONS = ('独立', '不确定', '重复', '互补', '替代', '被替代', '无关')
REL_RE = re.compile(r'^(独立|不确定|(?:重复|互补|替代|被替代|无关)\((M\d+)\))')
REL_TAIL_OK = (' ', '（', '(', '⚠', '·')                  # 取值后面只许跟这些（理由 / 留痕 / 备注）
FLOW_RE = re.compile(r'^(不确定|是|否)')
REVERSE = {'互补': '互补', '替代': '被替代', '被替代': '替代'}   # 双向一致的配对（重复另有一条判据）
FLOW_VALUES = ('是', '否', '不确定')
NO_FLOW = '—'
ID_RE = re.compile(r'`(M\d+)`')
KIND_CN = {'heading': '标题', 'paragraph': '段落', 'list_item': '列表', 'table': '表格',
           'sheet': '工作表', 'code': '代码', 'caption': '题注', 'figure': '图', 'cell': '单元格'}
DIGEST_PER_MATERIAL = 6          # 摘要里一份材料最多给几条线索（够 AI 填卡片，又不至于把文件撑爆）
QUOTE_LIMIT = 60


def escape(text):
    """单元格转义：ASCII 竖线 → 全角 `｜`（竖线是表格列分隔符，不换就**切错列**——与 `selfboot_gen` 同一处置）。"""
    return str(text).replace('|', '｜')


def duplicate_pairs(materials):
    """材料层 → `({M##: 被重复的 M##}, [(原件, 副本), …])`。**判重只看 `sha256`**（§3，不看文件名与路径）。"""
    by_sha = {}
    for m in materials:
        sha = m.get('sha256') or ''
        if sha:
            by_sha.setdefault(sha, []).append(m.get('id'))
    pairs, copy_of = [], {}
    for _sha, ids in sorted(by_sha.items()):
        ids = sorted(x for x in ids if x)
        for extra in ids[1:]:                        # 只保留 `M##` 小者，其余标「副本」
            copy_of[extra] = ids[0]
            pairs.append((ids[0], extra))
    return copy_of, pairs


def _line_of(e):
    """一条证据 → 摘要里的一行（表格给行列数，其余给原文节选：压成单行 + 截断）。

    这两行**内联**、不单独立一个助手：自举生成器的绕行读数对**小表**很敏感——每多一个只被调一次的小
    函数就多一条长跳边（门⑨ 当场红，见表尾「已知边界」）。
    """
    if e.get('kind') in ('table', 'sheet'):
        body = f'{e.get("text") or "（表）"}（{len(e.get("rows") or [])} 行）'
    else:
        flat = ' '.join(str(e.get('text') or '').split())
        body = flat if len(flat) <= QUOTE_LIMIT else flat[:QUOTE_LIMIT - 1] + '…'
    return f'  - {KIND_CN.get(e.get("kind"), e.get("kind"))} `{e.get("id")}`：{escape(body)}'


def _digest_lines(mid, elements):
    """一份材料的线索：证据条数 / 种类分布 / 头几处可引用的原文（填「主题 / 依据」时从这里挑）。

    **不写成嵌套函数**（第一版把"取一行"写成闭包 `take`）：自举生成器按 owner 分组排表，
    嵌套函数自成一组、被排到**全表最后**，于是它与 `_digest_lines`、`escape`、`_capped` 之间
    凭空多出三条长跳边——门⑨ 当场报绕行 **67% > 60%**（阈值不许变差）。提到模块级就没了。
    """
    mine = [e for e in elements if e.get('material_id') == mid]
    if not mine:
        return ['- 无证据']
    kinds = {}
    for e in mine:
        kinds[e.get('kind', '?')] = kinds.get(e.get('kind', '?'), 0) + 1
    dist = ' · '.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
    picks, used = [], set()
    for want in ('heading', 'paragraph', 'list_item', 'table', 'sheet', 'code'):
        for e in mine:                               # 每种结构各挑第一条（读表的人先看结构长什么样）
            if e.get('kind') == want and e.get('id') not in used:
                used.add(e.get('id'))
                picks.append(_line_of(e))
                break
    for e in mine:                                   # 结构种类不够时，用剩下的正文补齐
        if len(picks) >= DIGEST_PER_MATERIAL:
            break
        if e.get('id') not in used:
            used.add(e.get('id'))
            picks.append(_line_of(e))
    return [f'- 证据 {len(mine)} 条（{dist}）'] + picks[:DIGEST_PER_MATERIAL]


def build_card(ledger):
    """账本 → `intake.md` 全文。机器可算的格子已填，语义格子留 `—`（check 会把未填当错）。"""
    materials, elements = ledger['materials'], ledger['elements']
    copy_of, pairs = duplicate_pairs(materials)
    kept = {a for a, _b in pairs}                    # 判重里被保留的那一份：它**就是**独立的（机器事实）
    lines = ['# 清点（L1）— 材料卡片', '',
             '> 由 `scripts/intake.py` 从 `evidence.json` 生成：**机器可算的格子已填**（材料 / 档位 / '
             '读不动 / `重复` 关系），语义格子留 `—` 待 AI 按 `PIPELINE-SPEC` §3 填（主题标 `⚠`；'
             '`是`/`否` 要给理由并标 `⚠`）。', '',
             '> **清点不改账本**：发现材料缺失、读不动、可疑，只写卡片与澄清申请（§3 纪律 1）；'
             '澄清答复是**新材料**，回 §1 重走探测 → 解析 → 落账。', '']
    if pairs:
        facts = '、'.join(f'`{a}` 与 `{b}` 内容逐字节相同 → `{b}` 记 `重复({a})`' for a, b in pairs)
        lines += [f'> **判重（只看 `sha256`）**：{facts}；不许因此多出一条流程（§3）。', '']
    lines += ['## 材料卡片', '',
              '| ' + ' | '.join(COLUMNS) + ' |',
              '| ' + ' | '.join(['---'] * len(COLUMNS)) + ' |']
    for m in materials:
        mid = m.get('id', '?')
        rel = (f'重复({copy_of[mid]})' if mid in copy_of
               else ('独立' if mid in kept else NO_FLOW))   # 其余的互补 / 替代 / 无关是 AI 的判断，留 `—`
        cells = [f'`{mid}` {escape(Path(str(m.get("path", ""))).name)}', escape(m.get('tier', '')),
                 NO_FLOW, NO_FLOW, rel,
                 escape(m.get('reason') or NO_FLOW) if m.get('status') != 'ok' else NO_FLOW,
                 NO_FLOW]
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '## 材料摘要（机器给的线索：填「主题 / 含流程 / 依据」时从这里挑）', '']
    for m in materials:
        mid = m.get('id', '?')
        name = escape(Path(str(m.get('path', ''))).name)
        how = (f'`{m.get("tier")}` · 谁产的 `{m.get("extractor")}`' if m.get('status') == 'ok'
               else f'`{m.get("tier")}` · `{m.get("status")}`')
        facts = [how, f'{m.get("bytes", 0)} 字节', f'`sha256` {str(m.get("sha256"))[:12]}',
                 f'mtime {m.get("mtime")}']
        lines += [f'### `{mid}` {name}', f'- {" · ".join(str(x) for x in facts)}']
        lines += _digest_lines(mid, elements)
        lines.append('')
    return '\n'.join(lines).rstrip('\n') + '\n'


def parse_cards(text):
    """`intake.md` → `(表头, {M##: {列: 值}}, 报错)`。表头必须逐字对得上（列规范 §3）。"""
    header, rows = None, {}
    for line in text.splitlines():
        if not line.startswith('|'):
            if header is not None and rows:
                break                                # 卡片表看完就停（后面是摘要段）
            header = None if not rows else header
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if header is None:
            header = cells
            continue
        if all(set(c) <= set('-: ') for c in cells):
            continue                                 # `|---|---|` 分隔行
        if len(cells) != len(header):
            return header, rows, f'有一行的列数 {len(cells)} 与表头 {len(header)} 不一致：{line[:60]}'
        mid = ID_RE.search(cells[0])
        if not mid:
            return header, rows, f'「材料」列里找不到 `M##`：{cells[0][:40]}'
        rows[mid.group(1)] = dict(zip(header, cells))
    if header is None or not rows:
        return header, rows, '没有解析到材料卡片表（表头行 + 至少一行数据）'
    if tuple(header) != COLUMNS:
        return header, rows, f'表头不是 §3 的七列：{" | ".join(header)}'
    return header, rows, ''


def check_cards(ledger, rows):
    """卡片 vs 账本 → 错误清单（空 = 过）。**只报不改**（§3 纪律 1：清点不改账本）。"""
    errs, mats = [], {m.get('id'): m for m in ledger['materials']}
    have_evidence = {e.get('material_id') for e in ledger['elements']}
    elem_ids = {e.get('id') for e in ledger['elements'] if e.get('id')}
    for mid in sorted(set(mats) - set(rows)):
        errs.append(f'{mid}: 账本里有这份材料，卡片里没有（材料必须一一对应）')
    for mid in sorted(set(rows) - set(mats)):
        errs.append(f'{mid}: 卡片里有，账本里没有（`M##` 一律从账本抄，不许自己编号）')
    for mid in sorted(set(rows) & set(mats)):
        cell, m = rows[mid], mats[mid]
        if cell['档位'] != m.get('tier'):
            errs.append(f'{mid}: 档位 {cell["档位"]!r} ≠ 账本 {m.get("tier")!r}（档位只许抄，不许重判）')
        want = escape(m.get('reason') or NO_FLOW) if m.get('status') != 'ok' else NO_FLOW
        if cell['读不动'] != want:
            errs.append(f'{mid}: 读不动 {cell["读不动"]!r} ≠ 账本 {want!r}（必须逐字一致）')
        errs += _check_relation(mid, cell, rows, mats)
        hit = FLOW_RE.match(cell['含流程'].strip())     # 含流程：三值封闭；`是`/`否` 必须标 `⚠`（AI 判的要留痕）
        if not hit:
            errs.append(f'{mid}: 含流程 {cell["含流程"]!r} 不在三值（{" / ".join(FLOW_VALUES)}）内')
        elif hit.group(1) in ('是', '否') and '⚠' not in cell['含流程']:
            errs.append(f'{mid}: 含流程=「{hit.group(1)}」是 AI 的判断，必须标 `⚠` 并给理由')
        if cell['主题'] in (NO_FLOW, ''):
            errs.append(f'{mid}: 主题没填（一句话 + `⚠`）')
        elif '⚠' not in cell['主题']:
            errs.append(f'{mid}: 主题是语义推断，必须标 `⚠`')
        if mid in have_evidence and cell['依据'] in (NO_FLOW, ''):
            errs.append(f'{mid}: 有证据却没填「依据」（填 element id；H10 会核它存不存在）')
        elif cell['依据'] not in (NO_FLOW, ''):
            # **H10.1 引用完整**（§6）：卡片里的 element id 必须真在账本里。
            # 这条以前只写了半句承诺（"H10 会核它存不存在"）而没人核——现在核了。
            miss = [i for i in flowtable_check.citations(cell['依据']) if i not in elem_ids]
            if miss:
                errs.append(f'{mid}: 「依据」引用了账本里不存在的 element id：{"、".join(miss[:6])}'
                            f'—— 改成真存在的 id，或降级成 `⚠` 推断')
    return errs


def _check_relation(mid, cell, rows, mats):
    """版本关系：取值封闭 + **双向一致**（§3 的硬要求，单向声明按错处理）。"""
    value = cell['版本关系'].strip()
    hit = REL_RE.match(value)
    if not hit:
        return [f'{mid}: 版本关系 {value!r} 不在封闭取值内'
                f'（{" / ".join(RELATIONS)}，引用型写成 `重复(M##)` 这样）']
    tail = value[len(hit.group(1)):]
    if tail and not tail.startswith(REL_TAIL_OK):
        return [f'{mid}: 版本关系 {value!r} 的取值后面跟了认不出的内容 {tail!r}（理由请写在括号里）']
    other = hit.group(2)
    if not other:
        return []
    if other not in rows:
        return [f'{mid}: 版本关系指向 {other}，卡片里没有这份材料']
    if other == mid:
        return [f'{mid}: 版本关系指向自己']
    kind = hit.group(1).split('(')[0]
    if kind == '重复':                                # 判重只看 sha256，且副本编号必须更大
        errs = []
        if mats[mid].get('sha256') != mats[other].get('sha256'):
            errs.append(f'{mid}: 记了 `重复({other})`，但两份的 sha256 不同（判重只看 sha256）')
        if other > mid:
            errs.append(f'{mid}: 记了 `重复({other})`，但副本必须是编号更大的那份'
                        f'（应记在 {other} 上：`重复({mid})`）')
        back = rows[other]['版本关系'].strip()
        if back != '独立':
            errs.append(f'{mid}: 记了「副本」，但被复制的那份 {other} 记的是 {back!r}'
                        f'（保留的那份应当 `独立`——§3：只保留 `M##` 小者）')
        return errs
    want = REVERSE.get(kind)
    if want is None:
        # `无关(M##)` 是合法取值（§3 取值表与 `TODO_TABLES` 域都列了它），而 `REVERSE` 只装
        # 互补 / 替代 / 被替代 三对——原先直接下标，撞上 `无关` 当场 KeyError 崩栈退 1（G39）。
        # §3 的双向一致只要求互补与替代配对；`无关` 不要求对偶。
        return []
    back = rows[other]['版本关系'].strip()
    if back != f'{want}({mid})':
        return [f'{mid} 记 `{kind}({other})`，但 {other} 记的是 {back!r}'
                f'（双向一致要求 `{want}({mid})`）']
    return []


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='L1 清点：证据账本 → 材料卡片（intake.md）+ 卡片校验器')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='出骨架（机器可算的格子已填）')
    b.add_argument('ledger', help='evidence.json')
    b.add_argument('-o', '--out', help='写到哪里（默认：与账本同目录的 intake.md）')
    b.add_argument('--todo', help='把「待填清单」写到这里（建议写成 <产物名>.todo.json，cells.py fill 默认就找它）')
    c = sub.add_parser('check', help='校验收口后的卡片（退 1 = 有问题）')
    c.add_argument('card', help='intake.md')
    c.add_argument('--ledger', required=True, help='evidence.json（对照用）')
    a = ap.parse_args(argv)
    if a.cmd == 'build':                      # 默认落盘跟着输入走（D-119，见 `artifact.beside`）
        a.out = a.out or str(artifact.beside(a.ledger, 'intake.md'))

    try:
        # 读账本（容忍 BOM）：只此一处用，**不单独立一个助手**——自举绕行读数对小表敏感（见表尾）
        ledger = json.loads(Path(a.ledger).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as e:
        print(f'⚠ 账本读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(ledger, dict):
        # 审计实测：喂一份 JSON **数组**（比如把材料层当账本）曾在这里裸抛
        # `AttributeError: 'list' object has no attribute 'get'`——"不抛裸异常"这条对所有脚本都成立，
        # 输入形态不对要**说人话**并退 2（仪器故障），不是崩栈。
        print(f'⚠ 账本结构不对（要一个对象，含 materials[] 与 elements[]）：实际是 {type(ledger).__name__}',
              file=sys.stderr)
        return 2
    if not isinstance(ledger.get('materials'), list) or not isinstance(ledger.get('elements'), list):
        print('⚠ 账本结构不对（要 materials[] 与 elements[]）', file=sys.stderr)
        return 2

    if a.cmd == 'build':
        text = build_card(ledger)
        Path(a.out).write_bytes(text.encode('utf-8'))   # UTF-8 / LF（build_card 用 \n 拼）
        n_dup = len(duplicate_pairs(ledger['materials'])[1])
        print(f'→ 已写出 {a.out}：材料 {len(ledger["materials"])} 张卡片'
              f' · 判重事实 {n_dup} 对 · 待 AI 填的格子标 `{NO_FLOW}`')
        if getattr(a, 'todo', None):
            cells.dump(cells.todo_from_doc(a.out, TODO_TABLES), a.todo)   # 见 cells.py 的文件头
            print(f'  · 待填清单已写出 {a.todo}：AI 填完它再跑 '
                  f'`python scripts/cells.py fill {Path(a.out).name} <答案>.json`')
        return 0

    try:
        cards_text = Path(a.card).read_text(encoding='utf-8')
    except OSError as e:
        print(f'⚠ 卡片读不了: {e}', file=sys.stderr)
        return 2
    header, rows, err = parse_cards(cards_text)
    if err:
        print(f'⚠ 卡片解析不了（仪器故障，不是卡片内容的问题）: {err}', file=sys.stderr)
        return 2
    errs = check_cards(ledger, rows)
    if errs:
        print(f'✗ 卡片校验未过（{len(errs)} 条；**只报不改**，改卡片或回 §1 重走，别就地改账本）:')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1
    print(f'✓ 卡片校验通过：{len(rows)} 张 · 档位/读不动逐字等于账本 · 版本关系双向一致 · '
          f'推断都留了痕 · 有证据的都填了依据')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（写在这里免得下个会话重新提）：
# - **不判语义**：主题 / 含流程 / 互补·替代·无关 / 依据都是 AI 的活（§3 纪律 4：拆解是 AI 的职责）。
#   脚本只保证"你填的东西与前两个层级不矛盾"。
# - **查 element id 存不存在**：那是 H10.1（§6）的活，这里**复用** `flowtable_check` 的同一份判据
#   （**不另写一份 id 提取**——两份真值必漂）。同一条判据的两个调用点：本模块与 `table_to_dsl --check`。
# - **`被替代(M##)` 与 `不确定` 补进取值表**：§3 的列契约原先只列了五种，但同节的判据表要求
#   `A 替代(B) ⇔ B 被替代(A)`，且"判不出 → 不确定 → 进澄清申请"——两处不自洽，取值表按判据表补全。
# - **这个小模块的"函数个数"受审美门约束**：自举绕行率是**逐边平均**，小表里每多一个只被调一次的
#   助手就多一条跨 3~4 行的长跳边（实测：14 个节点时 67% > 60% 当场红；把"取一行/读 JSON/查含流程"
#   三处内联、嵌套函数提成模块级后 11 个节点、34%）。所以这里的"少一个函数"是**读数**要求，
#   不是风格偏好——真要把它们拆回来，得先让生成器把长跳拆到两列（`coding-spec` G12）。
