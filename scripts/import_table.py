# -*- coding: utf-8 -*-
r"""import_table.py — 把**外部节点表**吃成契约流程表（`PIPELINE-SPEC` §4 的**可选**落表入口）。

**它不是必经路径**（§0.1：**流程节点的采集与判断归 AI 自由发挥**）。它只服务一种情形：
AI 手上**已经有**一张"准流程表"（别人给的 / 自己上一轮写的），而列数、列名、分支写法不合契约。
没有这张表就照常落表——脚本从不"从材料里生成节点"（那是理解，不是转换）。

**为什么值得有**（2026-09-18 实测）：真材料集上那张 43 行节点表原先是我**手写**转成 12 列的
（`<br>` 换 `｜`、长标签收进描述、缺列补 `—`、编号与引用逐个核）——"手写"意味着列数、编号、
双向引用全靠人保证。

本脚本只做**三件机械事**（判断仍归 AI）：
1. **认列**：按**列名同义词**映射到契约的十二列（不认列序）；认不出的列**列出来**（不静默丢）；
2. **规格化写法**：`<br>` / 真换行 → `｜`（规范里唯一的分隔符）· 类型同义词 → 四种 · 缺列留 `—` ·
   `下个节点` 的 `回 X ...` 归一成 `→回 X`；
3. **补两处声明**：`frontmatter`（id / level / description）与「主体配色」小节（按出现顺序分配 hex）。

**语义列（输入 / 依据 / 输出）填不出来就留 `—`**：那是 AI 的活（依据要指到 element id）。
转完照常跑 `python scripts/table_to_dsl.py --check <产物>`——**契约校验才是门**，本脚本不是。

用法：
    python scripts/import_table.py 外部表.md -o output/<流程名>/flowtable.md [--subject 默认主体]
    python scripts/import_table.py 外部表.md -o ... --id gujia-ea-epc --title "珈伟 × 怡云智 EPC 合作流程"

退出码：0 = 转出来了（可能带软提示）；1 = 有阻拦项（没认到表 / 编号重复）；2 = 输入读不了。
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from flowtable import COLUMNS                     # 十二列规范**只有一份**（公共层），不在这里再抄

# 列名同义词：**目标列 → 认得的写法**（长短无所谓，按"包含"匹配，所以 `序号` 能认 `序 号`）
SYNONYMS = {
    '项目运作阶段': ('项目运作阶段', '阶段', '环节', '模块', '篇章'),
    '节点编号': ('节点编号', '编号', '序号', '步骤号', '节点号'),
    '节点名称': ('节点名称', '名称', '节点', '步骤', '事项', '做什么'),
    '节点类型': ('节点类型', '类型', '形状', '种类'),
    '输入': ('输入', '输入物', '前置'),
    '依据': ('依据', '出处', '条款', '根据'),
    '输出': ('输出', '产出', '成果', '交付物', '交付'),
    '执行主体': ('执行主体', '主体', '责任方', '部门', '归属'),
    '执行者': ('执行者', '执行人', '岗位', '角色', '执行岗位'),
    '行动所需时间': ('行动所需时间', '行动时间', '时限', '时间要求', '行动时间要求', '时间'),
    '下个节点': ('下个节点', '下一节点', '下一步', '流向', '后续', '出边'),
    '节点描述': ('节点描述', '描述', '说明', '备注', '节点说明'),
}
# 「节点类型」只有四种（`references/flowtable-spec.md` 的类型登记表）：外部写法一律归到这四种
TYPES = {'开始': '开始', '起点': '开始', '入口': '开始', 'start': '开始', '起': '开始',
         '结束': '结束', '终点': '结束', '出口': '结束', 'end': '结束', '止': '结束',
         '判断': '判断', '决策': '判断', '分支': '判断', 'condition': '判断', '判定': '判断',
         '任务': '任务', '处理': '任务', '步骤': '任务', '活动': '任务', 'task': '任务',
         '子流程': '任务', '既定处理': '任务', '人工': '任务', '自动': '任务'}
# 主体配色：只声明"用到的"，其余由渲染器按未占用色档补（见 `references/flowtable-spec.md`）
PALETTE = ('#dae8fc', '#d5e8d4', '#ffe6cc', '#fff2cc', '#e1d5e7', '#f8cecc', '#d5e8f0', '#e6f2d9')
NO = '—'
ID_RE = re.compile(r'^\s*`?([0-9]+[a-z]?)`?\s*$')


def _cells(line):
    """一行 markdown 表格 → 单元格列表。"""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def header_of(text):
    """外部表 → `(表头, 数据行, 报错)`。认**第一张"像节点表"的表**（至少认出编号与名称两列）。"""
    header, rows = None, []
    for line in text.splitlines():
        if not line.startswith('|'):
            if header and rows:
                break                              # 第一张表看完就停
            header = None
            continue
        cells = _cells(line)
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if header is None:
            got = map_columns(cells)[0]
            if '节点编号' in got.values() and '节点名称' in got.values():
                header = cells
            continue
        if len(cells) == len(header):
            rows.append(cells)
    if not header:
        return None, [], ('没认到节点表：要有一张表，表头里能认出「节点编号」与「节点名称」'
                          '（同义词见 SYNONYMS，比如 序号/编号 + 名称/步骤/事项）')
    return header, rows, ''


def map_columns(cells):
    """表头 → `({下标: 契约列}, 认不出的列名)`。**按"最长的同义词"取胜**，不是"先命中先得"。

    为什么必须取最长（实测踩到）：`节点类型` / `下个节点` / `节点描述` 都**包含**「节点」，
    而「节点」是 `节点名称` 的同义词 ⇒ 先命中先得会把这三列全判成节点名称，再因为"目标已占"被丢掉，
    结果整张表只剩编号与名称两列。改成长者优先：`节点类型`(4) 胜过 `节点`(2)。
    """
    got, ignored = {}, []
    for i, name in enumerate(cells):
        cands = sorted(((len(w), c) for c, words in SYNONYMS.items() for w in words if w in name),
                       reverse=True)
        pick = next((c for _n, c in cands if c not in got.values()), None)
        if pick:
            got[i] = pick
        elif cands:
            ignored.append(f'{name}（与「{cands[0][1]}」重了）')
        else:
            ignored.append(name)
    return got, ignored


def norm_next(cell):
    """`下个节点` 归一：`<br>` / 真换行 → `｜`（规范里唯一的分隔符），`回 X ...` → `→回 X ...`。"""
    parts = [p.strip() for p in re.split(r'<br\s*/?>|[\n｜]', str(cell or '')) if p.strip()]
    out = []
    for p in parts:
        if p in ('—', '-', '无', ''):
            continue
        if '→' not in p:
            p = ('→' if not p.startswith('回') else '→') + p
        out.append(re.sub(r'\s+', ' ', p))
    return ' ｜ '.join(out) if out else NO


def norm_type(cell, used):
    """类型同义词 → 四种之一；认不出的记一笔（H7 会再拦一次）。"""
    raw = str(cell or '').strip()
    hit = TYPES.get(raw) or TYPES.get(raw.lower())
    if not hit:
        used.append(raw or '（空）')
        return '任务'
    return hit


def rows_of(rows, cols):
    """数据行 → `[(编号, {契约列: 值})]`（缺列写 `—`；`下个节点` / `节点类型` 过规格化）。"""
    bad_types, out = [], []
    for cells in rows:
        row = {}
        for t in COLUMNS:
            i = next((k for k, v in cols.items() if v == t), None)
            row[t] = (cells[i] if i is not None and i < len(cells) else NO)
        if not row['节点编号'] or row['节点编号'] in (NO, '—'):
            continue
        m = ID_RE.match(row['节点编号'])
        row['节点编号'] = m.group(1) if m else row['节点编号'].strip('`')
        row['节点类型'] = norm_type(row['节点类型'], bad_types)
        row['下个节点'] = norm_next(row['下个节点'])
        row['输入'] = row['输入'] or NO
        row['依据'] = row['依据'] or NO
        row['输出'] = row['输出'] or NO
        out.append((row['节点编号'], row))
    return out, bad_types


def render(artifact_id, title, rows, subject):
    """转好的行 → 契约流程表全文（frontmatter + 主体配色 + 十二列表）。"""
    subjects = [s for s in dict.fromkeys(r['执行主体'] for _i, r in rows) if s not in (NO, '')]
    if subject and subject not in subjects:
        subjects.insert(0, subject)
    lines = ['---', f'id: {artifact_id}', 'level: L0', f'description: {title}', '---', '',
             f'# {title}', '', '## 主体配色', '', '| 执行主体 | 颜色 |', '| --- | --- |']
    for i, s in enumerate(subjects):
        lines.append(f'| {s} | {PALETTE[i % len(PALETTE)]} |')
    lines += ['', '## 流程表', '',
              '| ' + ' | '.join(COLUMNS) + ' |',
              '|' + '---|' * len(COLUMNS)]
    for _i, r in rows:
        lines.append('| ' + ' | '.join(str(r[c]).replace('|', '｜') or NO for c in COLUMNS) + ' |')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='外部节点表 → 契约流程表（只做机械转换，语义留给 AI）')
    ap.add_argument('source', help='外部节点表（.md）')
    ap.add_argument('-o', '--out', required=True, help='写到哪里（如 output/<流程名>/flowtable.md）')
    ap.add_argument('--id', dest='aid', help='frontmatter 的 id（默认取产物目录名）')
    ap.add_argument('--title', help='标题（默认取外部表的一级标题）')
    ap.add_argument('--subject', help='外部表没有「执行主体」列时的默认主体（AI 的判断，写在这里）')
    a = ap.parse_args(argv)

    try:
        text = Path(a.source).read_text(encoding='utf-8-sig')
    except OSError as e:
        print(f'⚠ 读不了: {e}', file=sys.stderr)
        return 2
    header, raw, err = header_of(text)
    if err:
        print(f'✗ {err}', file=sys.stderr)
        return 1
    cols, ignored = map_columns(header)
    rows, bad_types = rows_of(raw, cols)
    if not rows:
        print('✗ 表里没有数据行', file=sys.stderr)
        return 1
    dup = [k for k, v in Counter(i for i, _r in rows).items() if v > 1]
    if dup:
        print(f'✗ 节点编号重复（H2 会拦）：{", ".join(dup)}', file=sys.stderr)
        return 1
    out = Path(a.out)
    title = a.title or next((ln.lstrip('# ').strip() for ln in text.splitlines()
                             if ln.startswith('# ')), out.parent.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(a.aid or out.parent.name, title, rows, a.subject), encoding='utf-8',
                   newline='\n')
    print(f'→ 已写出 {out}：{len(rows)} 个节点'
          + (f'（默认主体 `{a.subject}`）' if a.subject else ''))
    print('  · 认到的列：' + ' / '.join(f'{header[i]}→{t}' for i, t in sorted(cols.items())))
    if ignored:
        print(f'  · **没认到的列（原样丢掉，请核对是否漏了信息）**：{" / ".join(ignored)}')
    for c in COLUMNS:
        if c not in cols.values():
            print(f'  · 缺列 `{c}` ⇒ 留 `{NO}`' + ('（AI 要填：依据要指到 element id）'
                                                  if c in ('依据', '输入', '输出') else ''))
    if bad_types:
        print(f'  ⚠ 认不出的节点类型 {sorted(set(bad_types))} ⇒ 一律兜底成「任务」（H7 会再拦一次）')
    print(f'  · 下一步：`python scripts/table_to_dsl.py --check {out}`（契约校验才是门）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（写在这里免得下个会话重新提）：
# - **不做语义判断**：输入 / 依据 / 输出 一律留 `—`（依据要指到 element id，那是 AI 按 §2.5 填的）；
#   外部表的"备注"列并进「节点描述」——规范里 `★` / `⚠` / `⊞` 都住在描述列。
# - **不判 ⊞ 子流程**：外部表若用"子流程"表类型，只当归一成「任务」+ 一笔提醒；挂哪张子表是 AI 的判断。
# - **不改外部表**：它是材料（只读），本脚本只写产物（与 `parse_legacy` 的转换副本同一条纪律）。
