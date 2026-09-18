# -*- coding: utf-8 -*-
r"""plan.py — L2 计划（PIPELINE-SPEC §4）：`intake.md` → `plan.md`（流程清单 + 澄清申请 + 排除清单）。

**回答的问题**：做几张图 · 谁是谁的子 · 谁依赖谁 · 谁能并行。**它不回答"这一张怎么做"**——
那是流程表的事（§0：计划 ⇒ 表 ⇒ 图，三段不许互相代替）。

**分工**（与 `intake.py` / `recon.py` 同一条线：**脚本只执行，不承载判断**）：
- **机器填**：候选流程的**种子**（清点里「含流程 = 是」的材料各出一个）·
  **强合并**（§4.2 步骤 2：`重复` / `互补` / `替代` / `被替代` 是 §3 判据表里的**纯事实**，必并）·
  `F##` 编号（按"材料集里最小的 `M##`"排，可复现）· 排除清单（抄「含流程 = 否」的材料 + 理由）·
  澄清申请的**种子**（哪几份材料的版本关系是 `不确定` 就得问，**问什么是 AI 的事**）·
  以及"含 `不确定` 材料 ⇒ 状态必须 `待澄清`"这条蕴含；
- **AI 填**：流程名（§4.2 步骤 4 命名）· 角色（`主` / `子`）· `挂在`（子流程挂在父表哪个节点）·
  与其它流程（甲 / 乙 / 丙 三对关系）· 并行组 · 澄清申请的「问题 / 推荐答案」。

**为什么 `build` 拒绝覆盖已有的 `plan.md`**：它同时是**AI 判断的落点**（名字、关系、澄清问题都写在里面），
重出一次草稿等于把那些判断抹掉。确要重出就显式 `--force`（旧的会被覆盖）。

**表列规范只有一份**（这里）：`FLOW_COLUMNS` / `ASK_COLUMNS` / `EXCL_COLUMNS`。
`PIPELINE-SPEC` §4.1 里那三张样例表的表头是它们的**抄本**，门⑪ 的 ㊶ 会逐字核。

**`check` 能拦什么**（§4.4 的三条可机器核是前三条，其余是它们的必要前提）：
0. **表头写了主体与目的**（§4.0 前置澄清）——**没填就没澄清，直接退 1**。这一条排在最前面不是形式：
   拆解算法的每一步都以"主体是谁"为前提；真材料集上现形过（合作框架是「怡云智 × 珈伟」的，
   模板与标准却是「怡亚通」的，主体不定就开始拆，四条流程里两条要推倒）；
1. **材料集里的每个 `M##` 都在 `intake.md` 里**（§4.4 ①）——计划不许凭空造材料；
2. **流程数 = 成果根下的 `<流程名>/` 目录数**（§4.4 ②，要 `--root`；**不给就跳过并打印**，
   不静默）——计划说做几张，就得真做出几张；
3. 角色 / 状态 / 并行组取值封闭；`子` 必须写 `挂在` 且父流程在本表里；`主` 的 `挂在` 必须是 `—`；
4. **排除清单两支**（§4.1 ③）：`含流程 = 否` 的**必须齐全**（漏一个就报）；**含流程 = 是 的材料
   只能靠"`范围外…`"的理由进来**（说清它为什么不在本次主体 / 目的范围内）——两条路都行，
   静默塞进来不行；
5. **`不确定` 的材料 ⇒ 它所在流程的状态必须是 `待澄清`**（§3 判据表："判不出 → 进澄清申请，不许猜"）；
   **`待澄清` 的流程 ⇒ 澄清申请里必须有一条指向它**（否则"待澄清"是个凭空的状态）。
   ——这两条合起来就是 §5.4 收敛口径里那个**"澄清申请"**：以前它没有仪器（`plan.md` 未实现），
   现在"还有没有要问的事"可以直接核；
6. `共享(M##)` 必须**真的被另一条流程共享**（那个 `M##` 出现在别人的材料集里），
   `接力(F##)` 指向的流程必须存在，**同一个并行组里不许有 `接力` 关系**（依赖关系与"可并行"互斥）。

**它不读 `evidence.json`**：§4 的输入写着"`intake.md` + `evidence.json`"，但计划要用到的材料事实
（含流程 / 版本关系）在这一版里**全都已经在清点卡片上**（卡片本身是账本的标注层）。真要核 element id
存不存在，那是 **H10.1** 的活（§6）——在这里再抄一份账本读取就是第三份真值。
所以本脚本的输入是**一份 `intake.md`**（缺 `含流程` / `版本关系` 两列就退 2，并指向 `intake.py check`）。

用法：
    python scripts/plan.py build intake.md -o plan.md
    python scripts/plan.py check plan.md --intake intake.md [--root 成果根]

退出码：0 = 过（check）/ 写出（build）；1 = 计划有问题（**只报，不改**）；2 = 输入读不了。

**函数的排列顺序是"读数"要求，不是风格偏好**：自举表的绕行率按**调用边**量，边两端隔得越远、
竖直跨度越重叠，读数越差（`coding-spec` G12）。所以这里按"**被调者紧挨调用者**"排（叶子在前、
枢纽在后），并且**只被调一次的小助手一律内联**（`escape` / `_mat_cell` / `_names` 三处，实测把这张表
从 62% 压下来）；`_mid_of` / `_fid_of` 合成一个 `_id_of(text, 前缀)` 也是同一笔账。
要把它们拆回去，得先让生成器把长跳拆到两列——那是布局/生成器的活。
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

FLOW_COLUMNS = ('流程', '角色', '挂在', '材料集', '与其它流程', '并行组', '状态')
ASK_COLUMNS = ('编号', '问题', '推荐答案', '指向')
EXCL_COLUMNS = ('材料', '理由')

ROLES = ('主', '子')
STATES = ('可落表', '待澄清')
NO = '—'
BLANK = ('—', '-', '－', '无', '')
# 必并的关系（§4.2 步骤 2 = §3 判据表里的纯事实：内容相同的副本 / 同一标的的两份 / 新的覆盖旧的）
MERGE_KINDS = ('重复', '互补', '替代', '被替代')
# Windows 上不能出现在目录名里的字符（流程名 = 目录名，§4.1）
BAD_NAME = ('/', '\\', ':', '*', '?', '"', '<', '>', '|')

# **取值宽容一点**：`M##` / `F##` 在产物里写不写反引号都认（§4.1 的样例里就有两种写法——
# 材料集写 `` `M02`、`M07` ``，而 `共享(M08)` / 接力(`F01`) 是不加反引号的）。
# 这条不是"放松校验"：认的是**同一个东西的两种写法**，而不是两种东西。
MID_ANY = re.compile(r'`?(M\d{2,})`?')
FID_ANY = re.compile(r'`?(F\d{2,})`?')
REL_RE = re.compile(r'^(独立|不确定|(重复|互补|替代|被替代|无关)\((M\d+)\))')
MOUNT_RE = re.compile(r'^`?(F\d{2,})`?#(\d+)$')
FLOW_YES = re.compile(r'^是')
FLOW_NO = re.compile(r'^否')
GROUP_RE = re.compile(r'^`?G\d+`?$')
# 流程名列：`` `F01` 名称 ``；名字留空写成 `—`（check 会把"没填"当错）
FLOW_CELL = re.compile(r'^`(F\d{2,})`\s*(.*)$')
# **§4.0 前置澄清**：主体是谁、要图来干什么——必须在**拆解之前**问清楚，答复落进表头这一行。
# 为什么它是硬要求而不是礼貌：§4.2 的每一步（种子 / 合并 / 命名 / 定关系）都以"主体"为前提——
# 材料跨两个主体时（真实材料集实测：合作框架是「怡云智 × 珈伟」的，模板与标准却是「怡亚通」的），
# 主体不定，种子该出几条、命名该按谁的体系、哪些材料算"配套制度"全是悬的。
# 而目的决定**交付粒度**（汇报全貌 vs SOP 落地）。
SCOPE_RE = re.compile(r'^> \*\*本任务\*\*：主体 = (?P<who>.+?) · 目的 = (?P<why>.+?)\s*$', re.M)
SCOPE_BLANK = '> **本任务**：主体 = — · 目的 = —'
# 排除清单的**第二支**（§4.1 ③）：含流程=否 的材料当然不进流程；**含流程、但不在本次主体/目的范围内**
# 的材料也要有地方放——否则只能把它塞进流程清单（凭空多一条图）或删掉（静默消失）。
# 机器可核的形式：这类行的理由必须以它开头。
OUT_OF_SCOPE = '范围外'


def rel_of(cell):
    """版本关系单元格 → `(kind, 对方 M##)`；取值以 `不确定` / `独立` 开头时对方为空。

    **取前缀、不取逐字**（与 `drift.rule_d4` 同一条教训）：§3 允许在取值后面写理由 / 留痕
    （`互补(M04) ⚠ 附件`），逐字比较会把合规的卡片判成"取值不认"。
    """
    hit = REL_RE.match(str(cell or '').strip())
    if not hit:
        return '', ''
    return (hit.group(2) or hit.group(1) or '').split('(')[0], hit.group(3) or ''


def reason_of(cell):
    """`含流程` 单元格 → 那一句理由（`否 ⚠ 通篇参数，无步骤` → `通篇参数，无步骤`）。

    **转义内联在这里**（原先是一个 `escape` 助手，只被本函数调用一次）：自举表的绕行读数对
    "只被调一次的小助手"很敏感——多一个这样的函数就多一条长跳边（`intake.py` 同一条教训）。
    """
    tail = str(cell or '').strip()
    for mark in ('⚠', '：', ':'):
        if mark in tail:
            tail = tail.split(mark, 1)[1]
            break
    else:
        tail = re.sub(r'^(不确定|是|否)\s*', '', tail)
    return tail.strip(' ⚠（）()').replace('|', '｜').replace('\n', ' ').strip()


def groups_of(cards):
    """§4.2 步骤 2 的**强合并**：把必并的关系连成组，返回按"最小 `M##`"排序的材料号组列表。

    并查集写成**两趟扫描**而不是嵌套函数（`intake.py` 的教训：嵌套函数在自举表里自成一组、
    被排到全表最后，凭空多出长跳边 ⇒ 门⑨ 的绕行读数当场变差）。
    """
    groups = [[m] for m in sorted(cards)]
    for mid in sorted(cards):
        kind, other = rel_of(cards[mid].get('版本关系', ''))
        if kind not in MERGE_KINDS or not other:
            continue
        mine = next((g for g in groups if mid in g), None)
        theirs = next((g for g in groups if other in g), None)
        if mine is None or theirs is None or mine is theirs:
            continue
        mine.extend(theirs)
        groups.remove(theirs)
    return sorted([sorted(g) for g in groups], key=lambda g: g[0])


def build_plan(cards):
    """清点卡片 → `plan.md` 全文。机器可算的格子已填，语义格子留 `—`（`check` 会把未填当错）。"""
    groups = groups_of(cards)
    flow_ids = [g for g in groups if FLOW_YES.match(str(cards[g[0]]['含流程']).strip())]
    excl = [m for m in sorted(cards) if FLOW_NO.match(str(cards[m]['含流程']).strip())]
    # 要问的事有两种来源（**都是"不确定"**，§3 判据表：判不出 → 进澄清申请，不许猜）：
    # ① 版本关系 `不确定`（哪一份生效）；② `含流程 = 不确定`（读不动 / 判不出它有没有步骤）——
    # 后者更要紧：它既不是流程、也不在排除清单里，没有这一问就会**静默消失**（真实材料集上现形）。
    sure = {m for m in cards if str(cards[m]['含流程']).strip().startswith('不确定')}
    unsure = sorted(sure | {m for m in cards if rel_of(cards[m].get('版本关系', ''))[0] == '不确定'})
    lines = ['# 计划（L2）— 做几张图、谁是谁的子', '',
             '> 由 `scripts/plan.py` 从 `intake.md` 生成：**机器可算的格子已填**（种子 / 强合并 / `F##` 编号 / '
             '排除清单 / 澄清申请的种子），语义格子留 `—` 待 AI 按 `PIPELINE-SPEC` §4 填'
             '（流程名 · 角色 · `挂在` · 与其它流程 · 并行组 · 澄清问题与推荐答案）。',
             SCOPE_BLANK,
             '> ↑ **这两格要先问用户**（§4.0 前置澄清）：`主体` = 这几张图覆盖谁；`目的` = 给谁看、'
             '用来干什么（它决定交付粒度）。**没填这两格，`check` 直接退 1**——拆解算法的每一步都以'
             '"主体是谁"为前提，主体不定就开始拆，拆出来的东西迟早要推倒（真材料集上现形过一次）。',
             '> **强合并只并"纯事实"**：§4.2 步骤 2 的 `重复` / `互补` / `替代` / `被替代` 来自清点卡片'
             '（§3 判据表），不是判断；弱合并（共享 ≥2 个起止点 / 交付物）留给 AI，宁可多出一条流程。',
             '> `check` 会核 §4.4 的三条：① 计划里的 `M##` 都在 `intake.md` 里；'
             '② 流程数 = 成果根下的 `<流程名>/` 目录数（**要 `--root`**；不给就跳过并打印）；'
             '③ 排除清单与清点双向一致 · `待澄清` 与「含流程 = 不确定」都必须有账 · '
             '`共享(M##)` 得真被别的流程共享 · 同组内不许有 `接力`。',
             '> `plan.md` 是"做几张"的事实源，流程表是"一张怎么做"的事实源（§0），两者不许互相代替。', '']
    if unsure:
        lines += [f'> **有问题要问**：{len(unsure)} 份材料的结论是"不确定"（'
                  + '、'.join(f'`{m}`' for m in unsure)
                  + '）——按 §3 判据表"判不出 → 进澄清申请，不许猜"。'
                  '其中「含流程 = 不确定」的那几份**既不是流程、也不在排除清单里**，'
                  '不写进澄清申请就会静默消失；它们所在的流程状态必须是 `待澄清`。', '']
    lines += ['## ① 流程清单', '',
              '| ' + ' | '.join(FLOW_COLUMNS) + ' |',
              '|' + '---|' * len(FLOW_COLUMNS)]
    for i, g in enumerate(flow_ids, 1):
        state = '待澄清' if any(m in unsure for m in g) else NO       # 蕴含是机器事实，见 check 规则 5
        mats = '、'.join(f'`{m}`' for m in g)                        # 只在这里用一次 ⇒ 内联（见文件头）
        lines.append(f'| `F{i:02d}` {NO} | {NO} | {NO} | {mats} | {NO} | {NO} | {state} |')
    lines += ['', '## ② 澄清申请', '',
              '| ' + ' | '.join(ASK_COLUMNS) + ' |',
              '|' + '---|' * len(ASK_COLUMNS)]
    for i, m in enumerate(unsure, 1):
        lines.append(f'| `Q{i:02d}` | {NO} | {NO} | `{m}` |')
    lines += ['', '## ③ 排除清单（两支：`含流程 = 否` · 有流程但按 §4.0 在本次范围外——后者理由以'
                  '「`范围外`」开头）', '',
              '| ' + ' | '.join(EXCL_COLUMNS) + ' |',
              '|' + '---|' * len(EXCL_COLUMNS)]
    for m in excl:
        lines.append(f'| `{m}` | {reason_of(cards[m]["含流程"])} |')
    return '\n'.join(lines).rstrip('\n') + '\n'


def read_cards(text):
    """`intake.md` → `({M##: {'含流程': …, '版本关系': …}}, 报错)`。

    **按列名取值，不认列序**：本脚本只消费两列，把 §3 的七列再抄一遍就是第二份列规范（必漂）。
    找不到这两列就退 2 并指向 `intake.py check`——那是"仪器故障"，不是计划写错了。
    """
    header, cards = None, {}
    for line in text.splitlines():
        if not line.startswith('|'):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if header is None:
            header = cells
            continue
        if len(cells) != len(header) or '含流程' not in header or '版本关系' not in header:
            continue
        row = dict(zip(header, cells))
        hit = MID_ANY.search(row.get('材料', ''))
        if hit:
            cards[hit.group(1)] = {'含流程': row['含流程'], '版本关系': row['版本关系']}
    if not cards:
        return {}, ('读不出清点卡片：`intake.md` 里要有一张含 `含流程` / `版本关系` 两列的表'
                    '（先跑 `python scripts/intake.py check intake.md --ledger evidence.json`）')
    return cards, ''


def parse_doc(text):
    """`plan.md` → `(流程行, 申请行, 排除行, 报错)`。三张表各按**自己的表头**认（列规范在代码里只有一份）。

    认表头而不是认位置：三张表的列数都不同（7 / 4 / 2），按顺序硬认会在"漏了中间一张"时静默错位——
    那正是本仓反复吃过的那类错（伴生表少一列被当成"没给"）。
    """
    want = {FLOW_COLUMNS: '流程清单', ASK_COLUMNS: '澄清申请', EXCL_COLUMNS: '排除清单'}
    got = {c: [] for c in want}
    seen, header = set(), None
    for line in text.splitlines():
        if not line.startswith('|'):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if tuple(cells) in want:
            header = tuple(cells)
            seen.add(header)
            continue
        if header is None:
            continue
        if len(cells) != len(header):
            return [], [], [], f'有一行列数 {len(cells)} ≠ 表头 {len(header)}：{line[:50]}'
        got[header].append(dict(zip(header, cells)))
    miss = [v for k, v in want.items() if k not in seen]
    if miss:
        return [], [], [], ('没解析到这张表（表头逐字要对得上 §4.1）：' + '、'.join(miss))
    return got[FLOW_COLUMNS], got[ASK_COLUMNS], got[EXCL_COLUMNS], ''


def _id_of(text, prefix):
    """单元格里的第一个 `M##` / `F##`（`prefix` 取 `'M'` / `'F'`；写不写反引号都认）。

    **两个前缀合成一个函数**：它们各自只做一行事，分成两个函数就多一个节点、多两条长跳边
    （自举表的绕行读数按边量，见文件头）。
    """
    hit = re.search(r'`?(' + prefix + r'\d{2,})`?', str(text or ''))
    return hit.group(1) if hit else ''


def _check_links(row, fid, names, rows):
    """`与其它流程` / `并行组` 两列（§4.3 的甲 / 乙 / 丙：取值的形态与后果都可机器核）。"""
    errs, cell = [], str(row.get('与其它流程', '')).strip()
    group = str(row.get('并行组', '')).strip()
    same_group = {_id_of(r.get('流程', ''), 'F') for r in rows
                  if str(r.get('并行组', '')).strip() == group}
    for item in [x.strip() for x in re.split(r'[、,，;；]', cell) if x.strip() not in BLANK]:
        if item.startswith('接力'):
            peer = _id_of(item, 'F')
            if not peer or peer not in names:
                errs.append(f'{fid}: {item} 指向的流程不在计划里')
            elif peer in same_group and group not in BLANK:
                errs.append(f'{fid}: 与 {peer} 记了「接力」（有依赖）却又同属并行组 {group}'
                            f'——依赖与"可并行"互斥')
        elif item.startswith('共享'):
            shared = _id_of(item, 'M')
            if not shared:
                errs.append(f'{fid}: {item} 要写成 `共享(M##)`（共享的是**同一份材料 / 依据 / 产出物**）')
            elif not any(shared in set(MID_ANY.findall(r.get('材料集', ''))) for r in rows if r is not row):
                errs.append(f'{fid}: 记了 {item}，但 `{shared}` 没出现在别的流程的材料集里'
                            f'（"共享"得真的有另一条流程共享它）')
        else:
            errs.append(f'{fid}: 与其它流程里的 {item!r} 不是 `接力(F##)` / `共享(M##)`（§4.1 的取值）')
    if group not in BLANK and not GROUP_RE.match(group):
        errs.append(f'{fid}: 并行组 {group!r} 要写成 `G##` 或 `{NO}`')
    return errs


def _check_asks(rows, asks, cards, names):
    """澄清申请 ↔ 流程状态：**待澄清的必须有账**（这就是 §5.4 收敛口径里那个"澄清申请"）。"""
    errs = []
    ids = {str(a.get('编号', '')).strip() for a in asks}
    for a in asks:
        qid = str(a.get('编号', '')).strip()
        if not re.match(r'^`?Q\d+`?$', qid):
            errs.append(f'澄清申请有一行的编号 {qid!r} 不是 `Q##`')
        if str(a.get('问题', '')).strip() in BLANK:
            errs.append(f'{qid}: 没写问题（问什么必须写清——它是给业务方看的）')
        if str(a.get('推荐答案', '')).strip() in BLANK:
            errs.append(f'{qid}: 没写推荐答案（§4.1 ②：每问都要附一个推荐答案，业务方只需点头或改）')
        hit = str(a.get('指向', ''))
        for m in MID_ANY.findall(hit):
            if m not in cards:
                errs.append(f'{qid}: 指向的 `{m}` 在 `intake.md` 里没有')
        for f in FID_ANY.findall(hit):
            if f not in names:
                errs.append(f'{qid}: 指向的 {f} 不在计划里')
        if not _id_of(hit, 'M') and not _id_of(hit, 'F'):
            errs.append(f'{qid}: 「指向」是空的（要写这个问句属于哪份材料 / 哪条流程）')
    if len(ids) != len(asks):
        errs.append(f'澄清申请的编号有重复（{len(asks)} 行只有 {len(ids)} 个编号）')
    asked, states = set(), {}
    for a in asks:
        hit = str(a.get('指向', ''))
        asked |= set(MID_ANY.findall(hit)) | set(FID_ANY.findall(hit))
    for r in rows:
        fid, mats = _id_of(r.get('流程', ''), 'F') or '?', set(MID_ANY.findall(r.get('材料集', '')))
        states[fid] = (r.get('状态', ''), mats)
        if r.get('状态', '').strip() == '待澄清' and fid not in asked and not (mats & asked):
            errs.append(f'{fid}: 状态是 `待澄清`，但澄清申请里没有一条指向它（那这个状态是凭空来的）')
    # 「含流程 = 不确定」的材料**必须有人问**：它既不是流程、也不在排除清单里，
    # 不写进澄清申请就会**静默消失**（这一条是真材料集上现形的：5 份 legacy / 扫描件读不动，
    # 计划里它们一个都不出现，而谁也没注意到少了 5 份）。
    for m in sorted(m for m in cards if str(cards[m]['含流程']).strip().startswith('不确定')):
        if m not in asked:
            errs.append(f'`{m}` 在清点里是「含流程 = 不确定」（读不动 / 判不出有没有步骤），'
                        f'澄清申请里却没有它——它既不是流程、也不在排除清单里，会静默消失')
    return errs


def _check_dirs(names, root):
    """§4.4 ②：流程数 = 成果根下的 `<流程名>/` 目录数（名字逐个对，多的少的都报）。"""
    try:
        dirs = {p.name for p in Path(root).iterdir() if p.is_dir()}
    except OSError as e:
        return [f'成果根读不了：{e}']
    want = {n for n in names.values() if n not in BLANK}
    miss, extra = sorted(want - dirs), sorted(dirs - want)
    errs = []
    if miss:
        errs.append(f'计划里有 {len(miss)} 条流程还没有目录（§4.4 ②：计划说做几张就得真做出几张）：'
                    + '、'.join(miss))
    if extra:
        errs.append(f'成果根下有 {len(extra)} 个目录不在计划里（计划是"做几张"的事实源）：' + '、'.join(extra))
    return errs


def _scope_of(text):
    """`plan.md` 表头那一行 → `(主体, 目的)`；没有那一行就返回两个空串（`check` 会当错）。"""
    hit = SCOPE_RE.search(str(text or ''))
    return (hit.group('who').strip(), hit.group('why').strip()) if hit else ('', '')


def check_plan(cards, rows, asks, excl, root=None, scope=('', '')):
    """计划 vs 清点（+ 成果根）→ 错误清单（空 = 过）。**只报不改**。"""
    errs, names = [], {}
    who, why = scope
    if not who and not why:
        errs.append('计划表头没有「本任务：主体 = … · 目的 = …」这一行——§4.0 前置澄清：**先问清主体与目的，'
                    '再拆解**（拆解的每一步都以"主体是谁"为前提）')
    elif who in BLANK or why in BLANK:
        errs.append(f'计划的「本任务」没填完（主体 = {who or "空"} · 目的 = {why or "空"}）——'
                    f'没澄清就不该开工（§4.0）')
    for r in rows:                                    # `_names` 内联：只被本函数用一次（见文件头）
        hit = FLOW_CELL.match(str(r.get('流程', '')).strip())
        if hit:
            names[hit.group(1)] = hit.group(2).strip()
    no_flow = {m for m in cards if FLOW_NO.match(str(cards[m]['含流程']).strip())}
    unsure = {m for m in cards if rel_of(cards[m].get('版本关系', ''))[0] == '不确定'}
    if len(names) != len(rows):
        errs.append(f'有 {len(rows) - len(names)} 行的「流程」列不是 `` `F##` 名称 `` 这种写法，或编号重复'
                    f'（必填，`F##` 唯一）')
    for fid, name in sorted(names.items()):
        if name in BLANK:
            errs.append(f'{fid}: 流程名没填（§4.2 步骤 4；它同时是**目录名**，不给名字就没法落表）')
        elif any(c in name for c in BAD_NAME):
            errs.append(f'{fid}: 流程名 {name!r} 里有不能做目录名的字符（{"/".join(BAD_NAME)}）')
    for r in rows:
        fid = _id_of(r.get('流程', ''), 'F') or '?'
        role, mount = r.get('角色', ''), str(r.get('挂在', ''))
        mats = set(MID_ANY.findall(r.get('材料集', '')))
        if role not in ROLES:
            errs.append(f'{fid}: 角色 {role!r} 不在 {" / ".join(ROLES)} 内（必填；"子"= 被父流程的一个节点展开）')
        elif role == '子':
            hit = MOUNT_RE.match(mount.strip())
            if not hit:
                errs.append(f'{fid}: 子流程必须写 `挂在`，形如 `F01`#07（挂的是父表里的**节点编号**）')
            elif hit.group(1) not in names:
                errs.append(f'{fid}: 挂在 {hit.group(1)}，但计划里没有这条流程')
            elif hit.group(1) == fid:
                errs.append(f'{fid}: 挂在它自己')
        elif mount.strip() not in BLANK:
            errs.append(f'{fid}: 主流程的 `挂在` 必须是 `{NO}`（只有子流程才挂在父表的节点上）')
        if not mats:
            errs.append(f'{fid}: 材料集是空的（流程没有材料就没有依据，§4.4 ①）')
        for m in sorted(mats - set(cards)):
            errs.append(f'{fid}: 材料集里的 `{m}` 在 `intake.md` 里没有（§4.4 ①：计划不许凭空造材料）')
        state = r.get('状态', '')
        if state not in STATES:
            errs.append(f'{fid}: 状态 {state!r} 不在 {" / ".join(STATES)} 内（必填）')
        elif mats & unsure and state != '待澄清':
            bad = '、'.join(f'`{m}`' for m in sorted(mats & unsure))
            errs.append(f'{fid}: 材料集里的 {bad} 版本关系是 `不确定`，状态却是 {state!r}'
                        f'（§3：判不出 → 进澄清申请，不许猜）')
        errs += _check_links(r, fid, names, rows)
    for r in excl:
        m = _id_of(r.get('材料', ''), 'M')
        why_ = str(r.get('理由', '')).strip()
        if not m:
            errs.append(f'排除清单有一行没有 `M##`：{str(r.get("材料", ""))[:30]}')
            continue
        if m not in cards:
            errs.append(f'排除清单里的 `{m}` 在 `intake.md` 里没有')
        elif m not in no_flow and not why_.startswith(OUT_OF_SCOPE):
            errs.append(f'排除清单 `{m}`：它在清点里是「含流程 = 是」，不是"没流程"。含流程的材料'
                        f'要么进流程清单，要么把理由写成「{OUT_OF_SCOPE}…」说清它为什么不在本次'
                        f'主体 / 目的范围内（两条路都行，静默塞进来不行）')
        if why_ in BLANK:
            errs.append(f'排除清单 `{m}`：没写理由（"为什么它不参与"要能复核）')
    for m in sorted(no_flow - {_id_of(r.get('材料', ''), 'M') for r in excl}):
        errs.append(f'`{m}` 在清点里是「含流程 = 否」，排除清单里却没有它（§4.1 ③：这份清单是从清点抄的）')
    errs += _check_asks(rows, asks, cards, names)
    if root:
        errs += _check_dirs(names, root)
    return errs


def cmd_build(a):
    """出草稿：机器列已填，AI 那几列留空（`—`）。拒绝覆盖已有计划（它是 AI 判断的落点）。"""
    out = Path(a.out)
    if out.exists() and not a.force:
        print(f'✗ {out} 已存在——它同时是**AI 判断的落点**（流程名 · 关系 · 澄清问题都写在里面）。')
        print('  → 确要重出草稿就显式加 `--force`（旧的会被覆盖）。')
        return 2
    try:
        text = Path(a.intake).read_text(encoding='utf-8')
    except OSError as e:
        print(f'⚠ 清点卡片读不了: {e}', file=sys.stderr)
        return 2
    cards, err = read_cards(text)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2
    text = build_plan(cards)
    out.write_bytes(text.encode('utf-8'))
    lines = text.splitlines()
    n_flow = sum(1 for ln in lines if ln.startswith('| `F'))
    n_excl = sum(1 for ln in lines if ln.startswith('| `M'))
    n_ask = sum(1 for ln in lines if ln.startswith('| `Q'))
    print(f'→ 已写出 {out}：候选流程 {n_flow} 条 · 澄清申请 {n_ask} 条 · 排除 {n_excl} 条'
          f'（材料 {len(cards)} 份）· 待 AI 填的格子标 `{NO}`')
    return 0


def cmd_check(a):
    """校验收口后的计划（退 1 = 有问题）。`--root` 给了才核 §4.4 ②，**没给就打印跳过**。"""
    try:
        text = Path(a.plan).read_text(encoding='utf-8')
        cards_text = Path(a.intake).read_text(encoding='utf-8')
    except OSError as e:
        print(f'⚠ 读不了: {e}', file=sys.stderr)
        return 2
    cards, err = read_cards(cards_text)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2
    rows, asks, excl, err = parse_doc(text)
    if err:
        print(f'⚠ 计划解析不了（仪器故障，不是计划内容的问题）: {err}', file=sys.stderr)
        return 2
    print(f'> 输入：`{a.plan}`（sha256 {hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]}）'
          f' · 清点 `{a.intake}` · 流程 {len(rows)} / 澄清 {len(asks)} / 排除 {len(excl)}')
    if not a.root:
        print('> **跳过了 §4.4 ②**（流程数 = `<流程名>/` 目录数）：没给 `--root`。')
    errs = check_plan(cards, rows, asks, excl, a.root, _scope_of(text))
    waiting = sum(1 for r in rows if str(r.get('状态', '')).strip() == '待澄清')
    if errs:
        print(f'✗ 计划校验未过（{len(errs)} 条；**只报不改**。改计划 → 再落流程表，§4.4）：')
        for x in errs[:20]:
            print(f'  - {x}')
        return 1
    print(f'✓ 计划校验通过：{len(rows)} 条流程 · 材料集都能在清点里核到'
          + (' · 流程目录一一对上' if a.root else '')
          + f' · 排除清单两支都对（"含流程 = 否"抄全 · 范围外的写明了）'
            f' · `待澄清` 都有账（当前 {waiting} 条）')
    if waiting:                    # **过程状态，不是错误**：要不要接着问是 AI 的判断（§5.4 收敛口径）
        print(f'  · 收敛还差这一步：§5.4 要求 `待澄清` = 0（现在 {waiting} 条）'
              f'——把澄清申请问完并把状态改成 `可落表`，再落流程表。')
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='L2 计划：清点卡片 → plan.md（流程清单 + 澄清申请 + 排除清单）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='出草稿（机器可算的格子已填）')
    b.add_argument('intake', help='intake.md')
    b.add_argument('-o', '--out', default='plan.md', help='写到哪里（默认 plan.md，落成果根）')
    b.add_argument('--force', action='store_true', help='覆盖已有的 plan.md（它会抹掉 AI 填过的判断）')
    c = sub.add_parser('check', help='校验收口后的计划（退 1 = 有问题）')
    c.add_argument('plan', help='plan.md')
    c.add_argument('--intake', required=True, help='intake.md（对照用）')
    c.add_argument('--root', help='成果根：给了就核 §4.4 ②（流程数 = `<流程名>/` 目录数）')
    a = ap.parse_args(argv)

    if a.cmd == 'build':
        return cmd_build(a)
    return cmd_check(a)


if __name__ == '__main__':
    sys.exit(main())

# 已知边界（写在这里免得下个会话重新提）：
# - **不做弱合并**（§4.2 步骤 3：共享起点 / 终点 / 交付物 ≥2 个 → 并）：那要读**节点级**语义，
#   而计划层手里只有卡片（材料级）。判错了会把两张图的材料互相污染，正是 §4.2 保守原则要防的。
# - **不判甲 / 乙 / 丙**（§4.3）：`挂在` 里的节点编号要落表后才存在（H9 双向核），
#   这里只核"父流程在本表里"这一层；真正的节点级校验等 H10 / H9 那一档（§6）。
# - **不读 `evidence.json`**：理由见文件头（避免第三份真值）；要核 element id 走 H10.1。
# - **`共享(M##)` 只核"有别人也带这份材料"**：共享的是不是**同一个 element**（§4.3 丙的原话）
#   在计划层看不见——那要节点级依据列，留给 H10。
