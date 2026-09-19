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
from pathlib import Path

from flowtable import COLUMNS                     # 十二列规范**只有一份**（公共层），不在这里再抄

# 列名同义词：**目标列 → 认得的写法**（长短无所谓，按"包含"匹配，所以 `序号` 能认 `序 号`）
# 2026-09-18 用五种真实表形态撞过之后扩容：**英文字段名**（`Step` / `Node Name` / `Owner`）与
# 中文常见叫法（`负责人` / `期限` / `主责` / `环节`…）原先一律"认不出"，整张表就废了。
SYNONYMS = {
    '项目运作阶段': ('项目运作阶段', '阶段', '环节', '模块', '篇章', 'phase', 'stage'),
    '节点编号': ('节点编号', '编号', '序号', '步骤号', '节点号', 'no.', 'no', 'step', 'id'),
    '节点名称': ('节点名称', '名称', '节点', '步骤', '事项', '做什么', '环节', 'name', 'node'),
    '节点类型': ('节点类型', '类型', '形状', '种类', '网关', 'type'),
    '输入': ('输入', '输入物', '前置', '前置条件', 'input'),
    '依据': ('依据', '出处', '条款', '根据', 'basis', 'reference'),
    '输出': ('输出', '产出', '成果', '交付物', '交付', 'output', 'deliverable'),
    '执行主体': ('执行主体', '主体', '责任方', '部门', '归属', '主责', '主办', '牵头部门',
                 '责任部门', 'department', 'owner dept'),
    '执行者': ('执行者', '执行人', '岗位', '角色', '执行岗位', '负责人', '责任人', '承办人',
               '办理人', '经办人', 'owner', 'role'),
    '行动所需时间': ('行动所需时间', '行动时间', '时限', '时间要求', '行动时间要求', '时间',
                     '期限', '办理时限', '工期', 'time', 'duration', 'sla'),
    '下个节点': ('下个节点', '下一节点', '下一步', '流向', '后续', '出边', '流转', '后续步骤',
                 'next', 'next node', 'flow'),
    '节点描述': ('节点描述', '描述', '说明', '备注', '节点说明', 'note', 'remark', 'comment', 'desc'),
}
# **关键列优先**：同长度的同义词打架时（真样本实测：`环节` 既像"阶段"又像"一步"），
# 先把票投给"少了它这张表就不成立"的列；被抢走的那一列如果因此落空，第二轮再把词让回来。
KEY_ORDER = ('节点编号', '节点名称', '下个节点', '节点类型', '执行主体', '执行者',
             '行动所需时间', '输入', '依据', '输出', '节点描述', '项目运作阶段')
# 「节点类型」只有四种（`references/flowtable-spec.md` 的类型登记表）：外部写法一律归到这四种
TYPES = {'开始': '开始', '起点': '开始', '入口': '开始', 'start': '开始', '起': '开始',
         '结束': '结束', '终点': '结束', '出口': '结束', 'end': '结束', '止': '结束',
         '判断': '判断', '决策': '判断', '分支': '判断', 'condition': '判断', '判定': '判断',
         '网关': '判断', '审批': '判断', '审核': '判断', 'gate': '判断', 'decision': '判断',
         '任务': '任务', '处理': '任务', '步骤': '任务', '活动': '任务', 'task': '任务',
         '办理': '任务', '子流程': '任务', '既定处理': '任务', '人工': '任务', '自动': '任务'}
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
    """表头 → `({下标: 契约列}, 认不出的列名)`。**按"最长的同义词"取胜，平局按关键列**。

    两条都实测踩过：
    - **长者优先**：`节点类型` / `下个节点` / `节点描述` 都**包含**「节点」，而「节点」是 `节点名称`
      的同义词 ⇒ 先命中先得会把这三列全判成节点名称、再因为"目标已占"被丢掉，整张表只剩编号与名称。
    - **关键列优先**（2026-09-18 五种真实表形态实测）：`环节` 在两列的同义词表里都有，长度也一样，
      先到先得会把它判给「项目运作阶段」，于是**"节点名称"整列落空、表直接不成立**
      （报错还只说"没认到节点表"）。关键列（编号 / 名称 / 下个节点…）少了表就不成立 ⇒ 平局先给它。
    """
    got, ignored = {}, []
    for i, name in enumerate(cells):
        low = str(name).lower()
        cands = sorted(((len(w), -KEY_ORDER.index(c) if c in KEY_ORDER else -99, c)
                        for c, words in SYNONYMS.items() for w in words if w in low),
                       reverse=True)
        pick = next((c for _n, _k, c in cands if c not in got.values()), None)
        if pick:
            got[i] = pick
        elif cands:
            ignored.append(f'{name}（与「{cands[0][2]}」重了）')
        else:
            ignored.append(name)
    # 第二轮：关键列落空 ⇒ 去"被抢走的列"里把词让回来（`环节` 那种情况就靠这一步）
    for want in KEY_ORDER:
        if want in got.values() or want not in ('节点名称', '节点编号', '下个节点'):
            continue
        for i, name in enumerate(cells):
            if i in got:
                continue
            if any(w in str(name).lower() for w in SYNONYMS[want]):
                got[i] = want
                ignored[:] = [x for x in ignored if not x.startswith(str(name))]
                return got, ignored
    return got, ignored


ARROW = re.compile(r'-{1,2}>|→|⇒|➔|➜')
# 分支之间的分隔符：**真实表用什么都得认**（实测：`；` `;` `/` `、` `,` 全在用，原先只认 `<br>` 与 `｜`）
SPLIT_NEXT = re.compile(r'<br\s*/?>|[\n｜|]|；|;|/|、|,')
NUM_ID = re.compile(r'^[（(]?\s*0*(\d{1,3})\s*[.、．)）]?$')
PLAIN_ID = re.compile(r'^\s*`?([0-9]+[a-z]?)`?\s*$')
# 「下个节点」里**目标那一段**的编号写法：`2` / `2.` / `（3）` / `回 2` ——与节点编号**同一套归一**，
# 否则转出来的表**自己引用自己都指不上**（实测：编号归一了、引用还留着 `→2`，H3 当场报"引用不存在"）。


def norm_id(cell, bad):
    """外部编号 → 契约写法。**只做"同一身份的写法归一"**（`1.` / `（1）` / `1、` → `01`）。

    **不改身份**：字母编号（`A` / `B`）或混合编号原样留下并记一笔——契约的 H2 只认
    "数字开头、至多带一个字母"，把它们硬改成 `01` 会**凭空换掉节点身份**（引用全断），
    那是 AI 的判断（也是 §0.1 那条边界：脚本不替 AI 决定节点）。
    """
    raw = str(cell or '').strip().strip('`').strip()
    m = NUM_ID.match(raw)
    if m:
        return f'{int(m.group(1)):02d}'
    if PLAIN_ID.match(raw):
        return PLAIN_ID.match(raw).group(1)
    bad.append(raw or '（空）')
    return raw


def merge_same_id(rows, conflicts):
    """**同一编号出现多行**：只有"其余列一致、仅仅是分支不同"才合并（真实表最常见的"一行一分支"）。

    **不合并真重复**（2026-09-18 夹具当场抓到）：同号两行如果**名称/类型/主体**这些列不一致，
    它们多半是两个不同节点撞了编号（或重复录入）——那种要照旧报"编号重复"，让 AI 去定身份。
    合并规则（机械、不走语义）：`下个节点` 逐行**并起来**（于是两条分支合成 `A ｜ B`）；
    其余列取第一个非空值。冲突一律记进 `conflicts`（调用方据此退 1）。
    """
    out, index = [], {}
    for i, row in rows:
        if i not in index:
            index[i] = row
            out.append((i, row))
            continue
        first = index[i]
        clash = [c for c in COLUMNS if c != '下个节点'
                 and str(row.get(c) or '').strip() not in ('', NO)
                 and str(first.get(c) or '').strip() not in ('', NO)
                 and str(row.get(c)).strip() != str(first.get(c)).strip()]
        if clash:
            conflicts.append(f'{i}: 同一编号的行「{"、".join(clash)}」不一致'
                             f'（{str(first.get(clash[0])).strip()} vs {str(row.get(clash[0])).strip()}）'
                             f'——这不是"一行一分支"，是两个身份撞了编号')
            continue
        for col in COLUMNS:                           # 其余列取第一个非空（不覆盖已有值）
            v = str(row.get(col) or '').strip()
            if v not in ('', NO) and str(first.get(col) or '').strip() in ('', NO):
                first[col] = v
        v = str(row.get('下个节点') or '').strip()
        old = str(first.get('下个节点') or '').strip()
        if v in ('', NO):
            continue
        if old in ('', NO):
            first['下个节点'] = v
        elif v not in old:
            first['下个节点'] = old + ' ｜ ' + v
        else:
            conflicts.append(f'{i}: 重复行（连「下个节点」都一样：{v}）——删掉一行或改编号')
    return out


def _fix_target(p):
    r"""一条分支里的**目标编号**归一（`→2` / `→2.` / `→（3）` / `→回 3` 都成 `→02` / `→回 03`）；
    标签（`超限`）与空白**原样不动**——这里只换编号那一段。

    两种写法分开处理，比一条正则稳（实测：想用一条正则同时管"整段"与"夹在 `回` 后面"，
    结果 `\s*` 把 `回 03` 的空格吃掉了 ⇒ 输出 `回03`，**那就是改了材料的写法**）。
    """
    head, sep, tail = p.rpartition('→')
    if not sep or not tail.strip():
        return p
    t = tail.strip()
    whole = re.fullmatch(r'[（(]?\s*0*(\d{1,3})\s*[.、．)）]?', t)
    if whole:
        return f'{head}{sep}{int(whole.group(1)):02d}'
    return head + sep + re.sub(r'(回\s*)[（(]?\s*0*(\d{1,3})\s*[.、．)）]?(?=\s|$)',
                               lambda m: f'{m.group(1)}{int(m.group(2)):02d}', t)


def norm_next(cell):
    """`下个节点` 归一：各种箭头 → `→`、各种分隔符 → `｜`（规范里唯一的分隔符）、`回 X` → `→回 X`、
    **目标编号与节点编号同一套归一**（`2.` → `02`）。"""
    parts = [p.strip() for p in SPLIT_NEXT.split(str(cell or '')) if p.strip()]
    out = []
    for p in parts:
        if p in ('—', '-', '无', ''):
            continue
        p = ARROW.sub('→', p).strip()
        p = re.sub(r'^[→\s]+', '', p).strip()
        if not p:
            continue
        if '→' not in p:
            p = '→' + p
        out.append(_fix_target(re.sub(r'\s+', ' ', p)))
    return ' ｜ '.join(out) if out else NO


def norm_type(cell, used, missing_col):
    """类型同义词 → 四种之一。**区分两件事**：这一列**根本没有**（要 AI 判定）与**值认不出**。"""
    raw = str(cell or '').strip()
    hit = TYPES.get(raw) or TYPES.get(raw.lower())
    if not hit:
        (missing_col if raw in ('', NO) else used).append(raw or '（空）')
        return '任务'
    return hit


def rows_of(rows, cols):
    """数据行 → `[(编号, {契约列: 值})]`（缺列写 `—`；编号 / `下个节点` / 类型过规格化）。

    **同编号多行在这里合并**（真实表最常见的"一行一分支"写法）；不像"一行一分支"的记进 `conflicts`。
    """
    bad_types, bad_ids, conflicts, out = [], [], [], []
    has_type = '节点类型' in cols.values()
    for cells in rows:
        row = {}
        for t in COLUMNS:
            i = next((k for k, v in cols.items() if v == t), None)
            row[t] = (cells[i] if i is not None and i < len(cells) else NO)
        if not row['节点编号'] or row['节点编号'] in (NO, '—'):
            continue
        row['节点编号'] = norm_id(row['节点编号'], bad_ids)
        row['节点类型'] = norm_type(row['节点类型'], bad_types, missing_col=bad_types if not has_type else [])
        row['下个节点'] = norm_next(row['下个节点'])
        row['输入'] = row['输入'] or NO
        row['依据'] = row['依据'] or NO
        row['输出'] = row['输出'] or NO
        out.append((row['节点编号'], row))
    merged = merge_same_id(out, conflicts)
    if not has_type:                                  # 列都没有 ⇒ 这不是"值认不出"，是该让 AI 判类型
        bad_types.clear()
    return merged, bad_types, bad_ids, conflicts


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
    rows, bad_types, bad_ids, conflicts = rows_of(raw, cols)
    if not rows:
        print('✗ 表里没有数据行', file=sys.stderr)
        return 1
    if conflicts:                                     # 同编号多行里"不像一行一分支"的那些
        print(f'✗ 编号重复（H2 会拦）：{len(conflicts)} 处', file=sys.stderr)
        for c in conflicts[:5]:
            print(f'   · {c}', file=sys.stderr)
        print('  → 若确实是"一个节点分了几个分支"，请让同编号的几行**其余列保持一致**；'
              '否则请给它们各自的编号（身份由 AI 定，脚本不改）', file=sys.stderr)
        return 1
    if bad_ids:
        print(f'✗ 编号不合契约（H2 只认"数字开头、至多带一个字母"，如 01 / 02a）：'
              f'{sorted(set(bad_ids))[:6]}', file=sys.stderr)
        print('  → 本脚本**不改节点身份**：请在外部表里给它们定编号（或让 AI 直接落表）', file=sys.stderr)
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
    if '节点类型' not in cols.values():
        print('  ⚠ 外部表**没有类型列** ⇒ 全部兜底成「任务」：**类型是判断**（哪一步是判断 / 起止），'
              '请按出边与语义定，别让它停在「任务」')
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
