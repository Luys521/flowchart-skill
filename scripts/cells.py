# -*- coding: utf-8 -*-
r"""cells.py — 产物里「AI 要填的那几格」的**正式接口**（公共层）。

**为什么需要它**（2026-09-18 实测的教训）：`recon` / `intake` / `plan` 三个产物都是 markdown 表格，
机器列由各模块的 `build` 填好，**AI 列原先靠 AI 手改表格**。这一条路上连着踩了三次：
- `.md` 材料的缩样把正文里的 `|` 带回侦查表 ⇒ 那一行的列数从 12 变 18（`recon.render` 已转义）；
- AI 的填格脚本只能**按列序号**硬编码（`c[8], c[9], c[10], c[11]`）——列序一改就静默填错列；
- 重出草稿后重填时，凡"值里带竖线 / 换行"的答案都会把表格撕开。
**根因是同一个**：把「AI 的判断」和「表格语法」混在一处，让 AI 去当排版工。
所以接口切成两半（本仓的纪律：**判断在 AI 侧，落笔在脚本侧**）：

    <模块>.py build ... --todo <产物>.todo.json        # 出「待填清单」：键 + 现值 + 取值域 + 要求
    python scripts/cells.py fill <产物>.md <答案>.json  # 按**列名**把答案写回产物

AI 只写一份 JSON（`{"M02": {"假设角色": "…", "依据": "…"}}`），回写由脚本做：列序、转义、格式
全部出不了错；各模块 `check` 的语义一个都没变（它照旧只认收口后的产物）。

**一份产物可以有多张表**（`plan.md` 有三张）：`表` 是一张登记表，每张写清 `键列` / `AI 列` / `取值域`；
`_scan` 靠**表头里出现哪张表的键列**认表——与各模块 `parse_doc` 认表头同一取向。

**两种写法**（`AI 列` 里声明，`{列名: 写法}`；列名可以是短名，`列` 指向产物里的真列）：
- 整格替换：`{"列": "角色"}` —— 答案就是这一格的全部内容；
- 带前缀：`{"列": "流程", "前缀": "`{}` "}` —— 用「前缀 + 答案」替换整格，`{}` 换成该行的键；
  用在"编号与名字同处一格"的地方（`plan.md` 的「流程」列就是这样）。

**校验只做三件**（其余留给各模块的 `check`）：键必须存在于产物里 · 列名必须是声明过的 AI 列 ·
值不许留空（"没填"要显式写 `—`，这样 `check` 才能把"没填"当错）。写盘口径与账本一致（UTF-8 / LF）。

用法：
    python scripts/cells.py fill recon.md answers.json            # 就地写回（留一份 .bak）
    python scripts/cells.py fill recon.md answers.json -o out.md  # 写到哪里
退出码：0 = 写回成功；1 = 答案有问题（**不写**）；2 = 输入读不了。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path


def dump(obj, path):
    """标准写盘：UTF-8 / LF / 缩进 2 / 中文不转义（与 `ledger.dump` 同一套口径）。"""
    Path(path).write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def load(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def as_spec(ai_cols):
    """`AI 列` 归一成 `{列名: {'列': …, '前缀': …}}`——允许写成一个名字列表（整格替换）。"""
    out = {}
    for name, spec in (ai_cols or {}).items():
        out[name] = dict(spec) if isinstance(spec, dict) else {'列': str(spec)}
        out[name].setdefault('列', name)
    return out


def table(name, key_col, ai_cols, domain=None):
    """登记一张表：名字 / 键列 / AI 列（短名 → 写法）/ 取值域。"""
    return {'名': name, '键列': key_col, 'AI 列': as_spec(ai_cols), '取值域': dict(domain or {})}


def _cells(line):
    """一行 markdown 表格 → 单元格列表。"""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _key_of(cell):
    """单元格里的键：取第一个词并去掉反引号（`` `M02` 甲.md `` → `M02`；`` `F01` 名称 `` → `F01`）。"""
    head = str(cell or '').strip().split(' ')[0]
    return head.strip('`') if head.startswith('`') else head


def _scan(text, tables):
    """产物 → `([(行号, 表, 键, 表头, 单元格)], 报错)`。**靠表头认表**（哪张表的键列出现在表头里）。"""
    out, errs, header, hit = [], [], None, None
    for i, line in enumerate(text.splitlines()):
        if not line.startswith('|'):
            header, hit = None, None
            continue
        cells = _cells(line)
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if header is None:
            header = cells
            hit = next((t for t in tables if t['键列'] in header), None)
            continue
        if hit is None:
            continue
        if len(cells) != len(header):
            errs.append(f'有一行列数 {len(cells)} ≠ 表头 {len(header)}：{line[:60]}')
            continue
        out.append((i, hit, _key_of(cells[header.index(hit['键列'])]), header, cells))
    return out, errs


def todo_from_doc(doc, tables, note=''):
    """读**已写出的产物** → 待填清单（键与现值都现取；模块只声明"哪些列是 AI 的"）。"""
    text = Path(doc).read_text(encoding='utf-8')
    rows, errs = _scan(text, tables)
    if errs:
        raise ValueError('; '.join(errs))
    # **骨架指纹**（D-105）：`fill` 靠它认「这份答案是对着哪一版骨架填的」。
    # 没有它时，骨架换过、答案还是旧的——**键还在的行会被旧结论覆盖**，而 fill 一声不吭（实测过）。
    todo = {'产物': str(doc), '表': tables, '骨架指纹': _fp(text),
            '要求': note or '每格都要填；判不出来就写 `—`（**留空会被 check 当错**）。'
                            '值里不要写竖线（脚本会转义，但转义后的样子不好读）。',
            '待填': [{'表': t['名'], '键': k,
                      '现值': {n: (cells[h.index(s['列'])] if s['列'] in h else '')
                               for n, s in t['AI 列'].items()}}
                     for _i, t, k, h, cells in rows]}
    return todo


def _fp(text):
    """产物的骨架指纹（前 16 位）。写进待填清单、由 `fill` 回比。"""
    import hashlib
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def fill(text, answers, tables, keys=(), expect_fp=''):
    """把答案写回产物 → `(新文本, 错误清单)`。**按列名写**，列数与列序不可能被破坏。"""
    errs = []
    if expect_fp and expect_fp != _fp(text):
        return '', ['骨架对不上：这份待填清单是**另一个版本**的产物出的（产物改过或换了一份）——'
                    '重跑 `build --todo` 拿新清单再填，别把旧结论写进新骨架']
    if not isinstance(answers, dict):
        return '', ['答案必须是一个对象：`{"键": {"列名": "值"}}`']
    rows, errs = _scan(text, tables)
    patch, seen = {}, set()
    for i, t, key, header, cells in rows:
        answer = answers.get(key)
        if answer is None:
            continue
        seen.add(key)
        if not isinstance(answer, dict):
            errs.append(f'{key}: 答案要写成 `{{"列名": "值"}}`')
            continue
        for name, val in answer.items():
            if name not in t['AI 列']:
                errs.append(f'{key}: `{name}` 不是这一层的 AI 列'
                            f'（可填：{" / ".join(t["AI 列"])}）')
                continue
            spec = t['AI 列'][name]
            if spec['列'] not in header:
                errs.append(f'{key}: 产物里没有列 `{spec["列"]}`（仪器故障）')
                continue
            if not str(val or '').strip():
                errs.append(f'{key}.{name}: 空值——**判不出来就写 `—`**（留空会被 check 当错）')
                continue
            v = str(val).replace('|', '｜').replace('\n', ' ').strip()
            pre = spec.get('前缀', '')
            cells[header.index(spec['列'])] = (pre.replace('{}', key) + v) if pre else v
        patch[i] = cells
    for key in answers:
        if key not in seen:
            errs.append(f'答案里的 `{key}` 在产物里没有；产物里的键：'
                        + (', '.join(sorted(keys)) if keys else '（清单未给）'))
    if errs:
        return '', errs
    return ('\n'.join(('| ' + ' | '.join(patch[i]) + ' |') if i in patch else ln
                      for i, ln in enumerate(text.splitlines())) + '\n'), []


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='把 AI 填的答案（JSON）按**列名**写回产物')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fill', help='写回（答案有问题就不写）')
    f.add_argument('doc', help='产物（recon.md / intake.md / plan.md）')
    f.add_argument('answers', help='AI 写的答案 JSON')
    f.add_argument('--todo', help='待填清单 JSON（不给就找同目录同名的 `<stem>.todo.json`）')
    f.add_argument('-o', '--out', help='写到哪里（不给就就地写回，并留一份 `.bak`）')
    a = ap.parse_args(argv)

    doc = Path(a.doc)
    todo_p = Path(a.todo) if a.todo else doc.with_name(doc.stem + '.todo.json')
    try:
        text = doc.read_text(encoding='utf-8')
        todo = load(todo_p)
        answers = load(a.answers)
    except (OSError, ValueError) as e:
        print(f'⚠ 读不了: {e}', file=sys.stderr)
        print(f'  （待填清单默认找 {todo_p.name}；uild --todo 与产物同名即可）', file=sys.stderr)
        return 2
    if '表' not in todo or '待填' not in todo:
        print(f'⚠ 待填清单不完整（它该由 `build --todo` 产出）: {todo_p}', file=sys.stderr)
        return 2
    new, errs = fill(text, answers, todo['表'], [r['键'] for r in todo['待填']],
                                expect_fp=todo.get('骨架指纹', ''))
    if errs:
        print(f'✗ 答案没过（{len(errs)} 条；**没有写盘**）：')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1
    out = Path(a.out) if a.out else doc
    if out == doc:
        shutil.copyfile(doc, doc.with_name(doc.name + '.bak'))
    out.write_text(new, encoding='utf-8', newline='\n')
    print(f'✓ 已写回 {out}：{len(answers)} 行 · {sum(len(v) for v in answers.values())} 格'
          + (f'（原样备份 {doc.name}.bak）' if out == doc else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（写在这里免得下个会话重新提）：
# - **不判语义**：值填得对不对是各模块 `check` 的事（取值封闭、逐字等于账本、推断留痕…），
#   这里只保证"**填得进去、填不坏表**"。
# - **不改机器列**：答案只能落在声明过的 AI 列上；要改机器列一律"回 01 重走"（§0）。
# - **不做交互编辑**：那是编辑器的事；本接口是给 AI（与夹具）用的批处理。
