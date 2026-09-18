# -*- coding: utf-8 -*-
r"""drift.py — 循环的发动机（PIPELINE-SPEC §5）：`流程表 × 证据账本 × 假设账` → **漂移清单 + 缺口清单**。

**它解决什么**：§1—§4 各管一层，但真实过程**不是单向流水线**——"先落一张表（带着假设与 `⚠?`）→
表自己暴露**逻辑漂移** → 漂移定位出**上下文缺口** → 按缺口定向取证（撬开文件 → 子代理只回摘要）→
修表 → 再审"。本脚本是这一步的仪器：**把"漂移"变成可执行判据，把"缺口"变成一张能派活的表**。
它**不产出结论**：判据之外的一切（该补哪一片、值不值得补、改成什么）是 AI 的活（§5.5）。

**判据 D1—D5（口径只写在 §5.2，这里只实现；五条全是硬档）**：

| 号 | 一句话 | 出什么 |
|---|---|---|
| D1 | 依据指向视觉推断 / 带降级留痕的证据，节点却没有 `⚠` 留痕（等级拔高） | 漂移 |
| D2 | 假设账里记「已推翻」，表里仍依据它 | 漂移 |
| D3 | 依据里的材料在账本里 `status=unreadable` | 漂移 |
| D4 | 清点里「含流程 = 是」的材料，表里没有任何节点引用它 | **缺口** |
| D5 | 某材料元素数够多，被表引用的比例却过低（只读了开头） | **缺口** |

D1—D3 是"**表写错了**"，D4 / D5 是"**还有东西没看**"——后者不指责表，它**派活**。
**这一版没有软档判据**：试过一条（前驱「输出」vs 后继「输入」无公共词），在 `examples/workflow` 上
14 条边报 12 条、11 条误报（回边 + "表里的边是时序不是数据流"），按"宁可漏判，不可误判"整条砍掉，
数字留在 §5.2 —— **别再把它加回来**。

**启用条件按输入可用性分档**（与 §6 的 H10 同一条纪律：**没有输入就不启用，绝不误伤合法的旧表**）：
没给 `--ledger` 就跳过 D1 / D3 / D4 / D5；没给 `--recon` 跳过 D2；没给 `--intake` 跳过 D4。

**分工**：脚本填机器可判的（判据 / 位置 / 事实，以及缺口的材料与现状）；
`处置` / `依据`（漂移）与 `要哪一片` / `状态` / `说明`（缺口）**留给 AI**。

**为什么必须配 `check`**：`build` 每次重出的草稿都是"未处置"，光看它永远不知道收没收敛。
`check` 拿**当前表重跑一遍判据**，于是两件机器判得死的事就成立了：
① 文件里标 `已修` 的，判据**必须不再命中**（说谎会被抓住）；② 判据现在命中的，**文件里必须都有**
（文件过期会被抓住）。收敛口径见 §5.4：**漂移 0 且缺口清单空**。

**为什么 `build` 拒绝覆盖已有的产物**：`drift.md` 同时是**漂移账**（发现 → 处置 → 依据），
AI 填过的格子被"重跑一次 build"静默抹掉，就是丢账。要重来就显式 `--force`（§2.4 不许静默降级同一条）。

**三处"看着多余"的写法，各有理由**（改动前先读，别顺手"优化"）：

1. **读文件一律写 `utf-8-sig`**（容忍 BOM），不设 `_read_text` 那种一层壳：四个读点各写一行，
   省掉"晚段函数都要跳回文件头"的长跳。
2. **函数顺序按调用方向排**（助手在前、用户在后、CLI 压尾）：自举表是**单列函数流**，
   一条跨 20 个节点的调用边会直接推高绕行读数（门⑨ 卡 45% / 60%，见 G12）。
   所以 `_esc` 与 `render` 排在判据**之后**——它们只被 `render` 用，早放就是自找长跳。
3. **`prepare` 只写一份**：`build` 与 `check` 需要的准备步骤完全一样（读表 → 读三份输入 → 跑判据），
   分成两处必然漂——一处改了启用条件、另一处不知道。这与 `flowtable_check.run_checks`
   "顺序只写一份，否则出现 build 拦得住、回写拦不住"是同一条理由。

用法：
    python scripts/drift.py build output/<流程名>/flowtable.md --ledger evidence.json \
        [--recon recon.md] [--intake intake.md] [-o drift.md]
    python scripts/drift.py check drift.md --flowtable output/<流程名>/flowtable.md --ledger evidence.json ...

退出码：0 = 完成（build）/ 收敛（check）；1 = `check` 发现没收敛或处置不合规；2 = 输入读不了 / 表结构不过。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from flowtable import Errors, parse_table
from flowtable_check import run_checks
import cells
from semantics import pending_kind

DICT_NAME = 'dictionary.yaml'

# 阈值 = "人给的默认"（数值只有一个家，§1.2）；`dictionary.yaml` 的 `drift:` 段按名覆盖。
DEFAULTS = {
    'coverage_min_elements': 20,   # 元素数少于此的材料不判覆盖率（样本太小不判，与 §1.5 质量门同一条纪律）
    'coverage_min_ratio': 0.1,     # 被引用比例低于它 → 出缺口（"只读了开头 / 读了没落表"）
}

# 判据登记表（§5.2）：`判据` 列的文案 + 一句话解释都从这里取——别处不许再写第二份。
RULES = {
    'D1': ('等级拔高', '依据指向视觉推断 / 带降级留痕的证据，而节点没有 ⚠ 留痕'),
    'D2': ('假设被推翻仍在用', '假设账里记「已推翻」，表里仍依据它'),
    'D3': ('建立在读不动的材料上', '依据里的材料在账本里 status=unreadable'),
    'D4': ('含流程的材料零引用', '清点里「含流程 = 是」的材料，表里没有任何节点引用它'),
    'D5': ('读了没用上', '材料元素数够多，被表引用的比例却过低'),
}

DRIFT_COLUMNS = ('漂移', '判据', '位置', '事实', '处置（AI 填）', '依据（AI 填）')
GAP_COLUMNS = ('缺口', '触发', '需要哪份材料', '要哪一片（AI 填）', '走哪条路',
               '状态（AI 填）', '说明（AI 填）')
DISPOSITIONS = ('已修', '已解释', '待验')
GAP_STATES = ('待取证', '已取证', '已放弃')
# **只算"浏览摘录"的那一类降级**（D1 要跳过它，见 `rule_d1`）：`ledger.degrade` 给每条摘录超限的
# 元素挂 `quote 截断到 N 字`——那是 §2.3 的写盘契约，正文与逐字引用都不受影响。
DISPLAY_ONLY_DEGRADED = 'quote 截断'
# 「AI 要填的格子」的登记（两张表）：cells.py fill 按**列名**回写（AI 不再手改表格）。
TODO_TABLES = (cells.table('漂移清单', '漂移', {
    '处置': {'列': '处置（AI 填）'},
    '依据': {'列': '依据（AI 填）'}}, {'处置': list(DISPOSITIONS)}),
    cells.table('缺口清单', '缺口', {
        '要哪一片': {'列': '要哪一片（AI 填）'},
        '状态': {'列': '状态（AI 填）'},
        '说明': {'列': '说明（AI 填）'}}, {'状态': list(GAP_STATES)}))
BLANK = ('—', '-', '－', '无', '')

# 引用 id：element id（`M03#p012`）与裸材料号（`M03`）都在射程内（§2.2）。
ID_RE = re.compile(r'M\d{2,}(?:#[0-9A-Za-z_]+)?')
MID_RE = re.compile(r'M\d{2,}')


# ----------------------------------------------------------------纯文本助手（紧挨判据：它们只服务判据）
def _col(row, prefix):
    """按**列名前缀**取值（`状态（AI 填）` / `走哪条路` 这类名字前缀足够稳，后缀由对方决定）。"""
    for k, v in (row or {}).items():
        if str(k).startswith(prefix):
            return v
    return ''


def _ids(text):
    """单元格 → 引用到的 id 集合（element id 与裸 `M##` 都在内）。"""
    return set(ID_RE.findall(str(text or '')))


def _mats(text):
    """单元格 → 引用到的**材料号**集合（`M03#p012` → `M03`）。"""
    return {i.split('#')[0] for i in _ids(text)}


def _cited(nodes):
    """全表引用到的 id 集合：依据列 + 节点描述（描述里也会写"见 M05"这类引用）。"""
    got = set()
    for nd in nodes:
        got |= _ids(nd.get('basis')) | _ids(nd.get('desc'))
    return got


# ----------------------------------------------------------------判据（口径在 §5.2）
def rule_d1(nodes, els):
    """D1 等级拔高：依据指向 `certainty=inferred`（`extractor=vlm`）或带 `degraded` 的证据，

    而该节点的描述**没有** `⚠` 留痕——把"我看到的 / 被截断的"当成"文件里逐字写着的"（§1.3 / §2.3）。
    （这里不转义 `|`：整条「事实」在 `render` 里统一转义一次，转两次是白做。）

    **只看"证据本身被削弱"的那几类降级**（2026-09-18 在真材料集上修）：`ledger.degrade` 给每条
    浏览摘录超限的元素都挂 `quote 截断到 N 字`，而 `degraded` 是**一个字段装三类事**——
    ① 浏览摘录上限（`quote 截断`，§2.3 的写盘契约，正文与逐字引用都不受影响）；
    ② 收窄留痕（`本轮收窄未取` / `--rows 只要…`）；③ 抽取质量降级（质量门 `noisy` / 碎片）。
    **① 不该算等级拔高**（摘录短了不等于证据弱了），②③ 才算。原先不分类，于是真表上
    **23 条漂移全是 ①**——一份每个节点都规规矩矩引条款的表被判成"通篇拔高"，
    这正是 §5.2 那条纪律（**精度太低的判据整条砍掉**）要防的：**读数说谎比不报更坏**。
    判据：`degraded` **以**「quote 截断」**开头** ⇒ 只有这一类降级（`ledger.degrade` 是**追加**写，
    所以"先有质量降级、后被截断"的那种仍以质量降级开头，照样判）。
    """
    out = []
    for nd in nodes:
        why = []
        for i in sorted(_ids(nd.get('basis'))):
            e = els.get(i)
            if not e:
                continue
            if e.get('extractor') == 'vlm' or e.get('certainty') == 'inferred':
                why.append(f'`{i}` 是视觉推断（`certainty=inferred`）')
            elif str(e.get('degraded') or '').startswith(DISPLAY_ONLY_DEGRADED):
                continue                                    # 只是浏览摘录短了（见上面那段）
            elif e.get('degraded'):
                why.append(f'`{i}` 带降级留痕（{str(e.get("degraded") or "")[:40]}）')
        if why and pending_kind(nd.get('desc')) is None:
            out.append({'rule': 'D1', 'pos': f'节点 {nd["id"]}', 'fact': '；'.join(why[:3])})
    return out


def rule_d2(nodes, recon):
    """D2 假设被推翻仍在用：假设账里 `状态 = 已推翻` 的材料，表里还有节点依据它。"""
    out = []
    for mid in sorted(mid for mid, r in recon.items() if _col(r, '状态') == '已推翻'):
        hits = sorted(nd['id'] for nd in nodes if mid in _mats(nd.get('basis')))
        if hits:
            out.append({'rule': 'D2', 'pos': f'节点 {"、".join(hits)}',
                        'fact': f'假设账里 `{mid}` 记「已推翻」，而 {len(hits)} 个节点的「依据」仍指向它'})
    return out


def rule_d3(nodes, mats):
    """D3 建立在读不动的材料上：依据里的材料在账本里 `status=unreadable`——断言的来源不存在。"""
    out = []
    bad = {mid for mid, m in mats.items() if m.get('status') == 'unreadable'}
    for nd in nodes:
        hit = sorted(_mats(nd.get('basis')) & bad)
        if hit:
            out.append({'rule': 'D3', 'pos': f'节点 {nd["id"]}',
                        'fact': '依据里的 ' + '、'.join(f'`{x}`' for x in hit)
                                + ' 在账本里 `status=unreadable`'})
    return out


def rule_d4(nodes, intake, recon):
    """D4 含流程的材料零引用 → **缺口**：这份材料的信息没进表（漏读，或读了没落表）。

    **判据取前缀，不取逐字**（审计实测的阻断）：`intake.py` 的取值是 `^(不确定|是|否)` **且**
    §3 要求同格补理由并标 `⚠`（实际写出来是 `是 ⚠ 有审批步骤`），而规范自己的样例又是
    `否（无过程步骤）`——三套写法并存。这里若要求逐字 `=='是'`，**任何合规的 intake.md 都命不中
    D4**，于是这条判据是死的、而且死得没声音（表头还写着"五条全启用"）。
    取"以 `是` 开头"就与 `intake.py` 的取值口径同源了；`不确定` 不算命中（它本来就要进澄清）。
    """
    cited = {i.split('#')[0] for i in _cited(nodes)}
    out = []
    for mid in sorted(intake):
        flow = str(_col(intake[mid], '含流程') or '').strip()
        if flow.startswith('是') and mid not in cited:
            out.append(('D4', mid, '表里没有任何节点引用它的证据'))
    return [(r, m, n, _col(recon.get(m, {}), '走哪条路') or '—') for r, m, n in out]


def rule_d5(els, cited, recon, th):
    """D5 读了没用上 → **缺口**：元素够多、被引用比例却过低（"只读了开头"）。

    阈值存在的理由（§5.2）：一份 300 条元素的合订本，表里引 5 条可能正好够——
    所以它出的是**缺口**（"还有 295 条没看，要不要看由 AI 判"），不是"表写错了"。
    """
    total = {}
    for e in els.values():
        mid = e.get('material_id')
        total[mid] = total.get(mid, 0) + 1
    out = []
    for mid in sorted(total):
        n = total[mid]
        if not mid or n < th['coverage_min_elements']:
            continue
        used = len({i for i in cited if i.startswith(mid + '#')})
        if used / n < th['coverage_min_ratio']:
            out.append(('D5', mid, f'账本里 {n} 条元素，表里只引用 {used} 条（{used / n:.0%}）',
                        _col(recon.get(mid, {}), '走哪条路') or '—'))
    return out


def collect(nodes, _edges, els, mats, recon, intake, th):
    """跑全部**启用**的判据 → `(漂移行, 缺口行)`。缺哪个输入就整条跳过（§5.2 启用条件）。

    缺口行是 `(判据号, 材料号, 事实, 走哪条路)`：**同一份材料可以被两条判据各报一次**
    （如"含流程零引用"与"读了没用上"），所以它按 `(判据, 材料)` 去重，**不按材料去重**——
    后者会把一条发现静默吃掉。`走哪条路` 从 `recon.md` 抄（不另立一份），在这里一并带上，
    免得 `render` 为了取一格又跳回文件头那批函数。

    `_edges` 只是与 `load_flowtable` 的返回形状对齐（曾经有一条判据要看边，实测被砍，见 §5.2）。
    """
    drift, gaps = [], []
    if els:
        drift += rule_d1(nodes, els)
        drift += rule_d3(nodes, mats)
        gaps += rule_d5(els, _cited(nodes), recon, th)
    if els and recon:
        drift += rule_d2(nodes, recon)
    if els and intake:
        gaps += rule_d4(nodes, intake, recon)
    drift.sort(key=lambda r: (r['rule'], r['pos']))
    return drift, sorted(set(gaps))


# ----------------------------------------------------------------读入（表 / 账本 / 两张伴生表）
def load_thresholds(path=None):
    """阈值 = 默认 + `dictionary.yaml` 的 `drift:` 段（读不到就用默认，**不报错**）。"""
    th = dict(DEFAULTS)
    p = Path(path) if path else Path(__file__).with_name(DICT_NAME)
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            got = (yaml.safe_load(fh) or {}).get('drift') or {}
    except Exception:                                # 缺依赖 / 缺文件 / 坏 YAML：一律退回默认
        return th
    for k, v in got.items():
        if k in th and isinstance(v, (int, float)) and not isinstance(v, bool):
            th[k] = v
    return th


def load_flowtable(path):
    """流程表 → `(nodes, edges, errs)`。用的是**结构校验的唯一入口**（`run_checks`），不另写一份解析。"""
    _, _, rows = parse_table(Path(path).read_text(encoding='utf-8-sig'))
    return run_checks(rows, mode='flow', errs=Errors())


def index_ledger(led):
    """账本 → `(元素 id → 元素, 材料 id → 材料)`。取不到的键不硬造（下游按"没有"处理）。"""
    els = {e['id']: e for e in (led.get('elements') or []) if isinstance(e, dict) and e.get('id')}
    mats = {m['id']: m for m in (led.get('materials') or []) if isinstance(m, dict) and m.get('id')}
    return els, mats


def read_side_table(path):
    """`recon.md` / `intake.md` → `({M##: {列: 值}}, 报错)`。**列按名字取**，不 import 生成方的列规范。

    `recon` / `intake` 与本脚本同属模块层，模块之间**不许有代码依赖**（`layering.py` 门禁），
    协作走产物——这正是那条纪律的用法：这里把它当**一张表**读，而不是把对方当库调。
    没给路径（或文件不在）→ 空字典 + 无报错：对应判据整条跳过（§5.2 的启用条件）。

    **行坏了必须报，不许静默跳过**（本轮实测的教训：夹具里一行少了一列，于是整份假设账
    被当成"没给"——D2 静默不跑，而表头还写着"跳过了 D2"。那种绿比红危险）。
    """
    if not path or not Path(path).exists():
        return {}, ''
    text = Path(path).read_text(encoding='utf-8-sig')
    header, out, err = None, {}, ''
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if header is None:
            header = cells
            continue
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if len(cells) != len(header):
            err = err or f'有一行列数 {len(cells)} ≠ 表头 {len(header)}：{line[:60]}'
            continue
        mid = MID_RE.search(cells[0])
        if mid:
            out[mid.group(0)] = dict(zip(header, cells))
    if header is None:
        return {}, f'{path}: 没解析到表头行（`| 材料 | … |`）'
    if not out and not err:
        return {}, f'{path}: 表里没有任何 `M##` 行'
    return out, err


def inputs_of(a):
    """一次运行的三份输入 → `(元素表, 材料表, 假设账, 清点, 报错)`。

    没给的输入都是空（对应判据整条跳过）；**给了但读坏了**要报出来，不许当成"没给"。
    """
    els, mats = ({}, {})
    if a.ledger:
        els, mats = index_ledger(json.loads(Path(a.ledger).read_text(encoding='utf-8-sig')))
    recon, e1 = read_side_table(getattr(a, 'recon', None))
    intake, e2 = read_side_table(getattr(a, 'intake', None))
    return els, mats, recon, intake, '；'.join(x for x in (e1, e2) if x)


def prepare(a):
    """`build` / `check` 共用的准备 → `{判据读数, 阈值, 硬错, 读坏, 跳过了哪几条}`。

    **只写一份**（与 `run_checks` 同一条理由）：两个子命令要的东西完全一样，分两处必然漂——
    一处改了启用条件、另一处不知道。表结构不硬拦、输入读坏不硬拦，只把事实带回去，
    由子命令决定怎么报（`build` 与 `check` 的报错口径不同）。
    """
    nodes, edges, errs = load_flowtable(a.flowtable)
    els, mats, recon, intake, bad = inputs_of(a)
    th = load_thresholds(a.dict)
    drift, gaps = collect(nodes, edges, els, mats, recon, intake, th)
    off = (list(RULES) if not els else ([] if recon else ['D2']) + ([] if intake else ['D4']))
    return {'drift': drift, 'gaps': gaps, 'th': th, 'hard': errs.hard, 'bad': bad, 'off': off}


# ----------------------------------------------------------------产物解析与对账
def parse_doc(text):
    """`drift.md` → `(漂移行, 缺口行, 报错)`。两张表的表头**必须逐字对得上**（列规范在代码里只有一份）。"""
    drift, gaps, header, mode, err = [], [], None, None, ''
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if all(set(c) <= set('-: ') for c in cells):
            continue
        if tuple(cells) in (DRIFT_COLUMNS, GAP_COLUMNS):
            header = tuple(cells)
            mode = 'drift' if header == DRIFT_COLUMNS else 'gap'
            continue
        if header is None:
            err = err or '第一张表的表头不是本脚本的列规范：' + ' | '.join(cells)
            continue
        if len(cells) != len(header):
            err = err or f'有一行列数 {len(cells)} ≠ 表头 {len(header)}：{line[:50]}'
            continue
        (drift if mode == 'drift' else gaps).append(dict(zip(header, cells)))
    if header is None:
        err = err or '没解析到漂移清单（表头行 + 至少一行）'
    return drift, gaps, err


def _blank(s):
    """空值判据（`—` / 空 / `无` 都算没填）——只给下面两个对账函数用，所以排在这里。"""
    return str(s or '').strip() in BLANK


def check_drift_rows(drift, live):
    """漂移账 → 错误清单。**该表与"现在的读数"双向对账**：

    ① 每条处置合法（`已解释` 必写依据）；② 标 `已修` 的**必须真的不再命中**（说谎会被抓住）；
    ③ 现在命中的**必须都在账内**（文件过期会被抓住）。

    **对账键必须含「事实」**（审计实测的绕过路径）：只用 `(判据号, 位置)` 时，
    ① 同一节点换了成因（例如依据从"带降级留痕的 `M01#p001`"换成"视觉推断的 `M07#p001`"——
    恰恰是 D1 真正要防的那件事）键**原地不动**，老账上的「已解释」继续生效；
    ② D2 的位置是聚合的节点列表，两份额外材料由同一节点引用时会渲染出**两行同键**，
    删掉一行也无人发现（集合差里一条键盖住多条命中）。
    把 `事实` 并进键之后：事实变了 ⇒ 这条命中在账外 ⇒ 报"文件过期"（该重跑 build 看新事实）。
    """
    errs = []
    file_keys = {(((r.get('判据') or '').split() or [''])[0], r.get('位置'), r.get('事实'))
                 for r in drift}
    live_keys = {(r['rule'], r['pos'], r['fact']) for r in live}
    for r in drift:
        rule = ((r.get('判据') or '').split() or [''])[0]
        if rule not in RULES:
            errs.append(f'{r.get("漂移")}: 判据 {rule!r} 不在 {"/".join(RULES)} 内')
            continue
        d = r.get('处置（AI 填）')
        if d not in DISPOSITIONS:
            errs.append(f'{r.get("漂移")}: 处置 {d!r} 不在 {"/".join(DISPOSITIONS)} 内（必填）')
        elif d == '待验':
            errs.append(f'{r.get("漂移")}: 还是「待验」——没收敛（§5.4 不许留待验）')
        elif d == '已解释' and _blank(r.get('依据（AI 填）')):
            errs.append(f'{r.get("漂移")}: 判「已解释」必须写依据（不许静默抹平）')
        elif d == '已修' and (rule, r.get('位置'), r.get('事实')) in live_keys:
            errs.append(f'{r.get("漂移")}: 标了「已修」，但判据 {rule} 在 {r.get("位置")} 仍然命中')
    for rule, pos, fact in sorted(live_keys - file_keys):
        errs.append(f'{rule} 在 {pos} 命中（{str(fact)[:40]}），但 `drift.md` 里没有这一条'
                    f'（文件过期？重跑 build --force）')
    return errs


def check_gap_rows(gaps, live):
    """缺口清单 → 错误清单（状态封闭 · `已取证` 要写清要哪一片 · `已放弃` 要写理由 · 同样双向对账）。"""
    errs = []
    file_keys = {(((r.get('触发') or '').split() or [''])[0], (r.get('需要哪份材料') or '').strip('`'))
                 for r in gaps}
    live_keys = {(r[0], r[1]) for r in live}
    for r in gaps:
        state = r.get('状态（AI 填）')
        if state not in GAP_STATES:
            errs.append(f'{r.get("缺口")}: 状态 {state!r} 不在 {"/".join(GAP_STATES)} 内（必填）')
        elif state == '待取证':
            errs.append(f'{r.get("缺口")}: 还是「待取证」——没收敛（§5.4 不许留待取证）')
        elif state == '已取证' and _blank(r.get('要哪一片（AI 填）')):
            errs.append(f'{r.get("缺口")}: 判「已取证」必须写「要哪一片」（取证要能复核）')
        elif state == '已放弃' and _blank(r.get('说明（AI 填）')):
            errs.append(f'{r.get("缺口")}: 判「已放弃」必须写说明（不许静默放弃）')
    for rule, mid in sorted(live_keys - file_keys):
        errs.append(f'{rule}: `{mid}` 现在命中，但 `drift.md` 里没有这一条（文件过期？重跑 build --force）')
    return errs


# ----------------------------------------------------------------渲染（只依赖列规范与 _esc，不依赖判据）
def _esc(s):
    """单元格里的 `|` 会撕表 → 换全角（与 `intake.py` 同一口径）。"""
    return str(s if s is not None else '').replace('|', '｜').replace('\n', ' ').strip()


def render(drift, gaps, meta):
    """漂移清单 + 缺口清单（markdown）。**表头先写输入指纹、跳过的判据与本次阈值**——

    不然"漂移 0 条"这种结论事后没法复核（它是"对着哪一版表、在什么阈值下"算出来的）。
    """
    lines = ['# 漂移与缺口（循环的发动机）', '',
             f'> 由 `scripts/drift.py` 从 `{meta["table"]}`（sha256 {meta["sha"]}）生成；'
             f'判据 D1—D5 的口径见 `PIPELINE-SPEC` §5.2。',
             f'> 输入：{meta["inputs"]}',
             f'> 本次跳过的判据：{meta["off"]}（没有对应输入就不启用，**不是"跑了没命中"**）。',
             f'> 阈值：`coverage_min_elements={meta["coverage_min_elements"]}` · '
             f'`coverage_min_ratio={meta["coverage_min_ratio"]}`（改 `dictionary.yaml` 的 `drift:` 段）。',
             '> `处置` / `依据` / `要哪一片` / `状态` / `说明` **留给 AI**；'
             '`check` 不许留 `待验` 与 `待取证`（§5.4 收敛口径）。', '',
             f'## ① 漂移清单（{len(drift)} 条）', '',
             '| ' + ' | '.join(DRIFT_COLUMNS) + ' |',
             '|' + '---|' * len(DRIFT_COLUMNS)]
    for i, r in enumerate(drift, 1):
        lines.append(f'| `X{i:02d}` | {r["rule"]} {RULES[r["rule"]][0]} | {_esc(r["pos"])} | '
                     f'{_esc(r["fact"])} | 待验 |  |')
    lines += ['', f'## ② 缺口清单（{len(gaps)} 条）', '',
              '| ' + ' | '.join(GAP_COLUMNS) + ' |',
              '|' + '---|' * len(GAP_COLUMNS)]
    for i, (rule, mid, note, path) in enumerate(gaps, 1):
        lines.append(f'| `Q{i:02d}` | {rule} {RULES[rule][0]}：{_esc(note)} | `{mid}` |  | '
                     f'{_esc(path)} | 待取证 |  |')
    return '\n'.join(lines) + '\n'


# ----------------------------------------------------------------子命令
def cmd_build(a):
    """出草稿：机器列已填，AI 那几列留空（`待验` / `待取证`）。"""
    out = Path(a.out)
    if out.exists() and not a.force:
        print(f'✗ {out} 已存在——它同时是**漂移账**（AI 填过的处置写在里面）。')
        print('  → 处置完先跑 `check`；确要重出草稿就显式加 `--force`（旧的会被覆盖）。')
        return 2
    got = prepare(a)
    if got['hard']:
        print(f'✗ 流程表结构不过（{len(got["hard"])} 条硬错）——在坏表上判漂移是噪音，先修结构：')
        for e in got['hard'][:5]:
            print(f'   · {e}')
        return 2
    if got['bad']:
        print(f'✗ 伴生表读坏了：{got["bad"]}')
        print('  → 「读坏了」与「没给」是两回事：当成没给会让对应判据**静默不跑**，那种绿比红危险。')
        return 2
    draft = Path(a.flowtable).read_text(encoding='utf-8-sig')
    th = got['th']
    meta = {'table': a.flowtable, 'sha': hashlib.sha256(draft.encode('utf-8')).hexdigest()[:12],
            'coverage_min_elements': th['coverage_min_elements'],
            'coverage_min_ratio': th['coverage_min_ratio'],
            'off': '、'.join(got['off']) if got['off'] else '（无，五条全启用）',
            'inputs': ' · '.join(x for x in (
                f'账本 `{a.ledger}`' if a.ledger else '',
                f'假设账 `{a.recon}`' if a.recon else '',
                f'清点 `{a.intake}`' if a.intake else '') if x) or '（只有流程表）'}
    out.write_text(render(got['drift'], got['gaps'], meta), encoding='utf-8', newline='\n')
    if getattr(a, 'todo', None):
        cells.dump(cells.todo_from_doc(out, TODO_TABLES), a.todo)   # 见 cells.py 的文件头
        print(f'  · 待填清单已写出 {a.todo}：AI 填完它再跑 '
              f'`python scripts/cells.py fill {out.name} <答案>.json`')
    print(f'✓ 漂移 {len(got["drift"])} 条 · 缺口 {len(got["gaps"])} 条 → {out}')
    print(f'  · 跳过：{meta["off"]} · 输入：{meta["inputs"]}')
    print('  · 下一步：AI 填「处置 / 依据」与「要哪一片 / 状态 / 说明」，再跑')
    print(f'    python scripts/drift.py check {out} --flowtable {a.flowtable}'
          + (f' --ledger {a.ledger}' if a.ledger else '')
          + (f' --recon {a.recon}' if a.recon else '')
          + (f' --intake {a.intake}' if a.intake else ''))
    return 0


def check_header(text, a, th):
    """`drift.md` 头部（`>` 行）↔ 本次调用的**输入 / 阈值 / 表** → `(错误, 提示)`。

    为什么要读它（审计实测的阻断）：`check` 原先**完全不看头部**，于是"换个输入再 check"
    照样打印"✓ 收敛…现在的判据读数没有漏在账外的"——少一个 `--ledger`（五条判据全关）
    就是一枚橡皮图章：什么都能判"已解释/已修"通过。头部里明明记着当时用的输入、阈值与表，
    读一眼就能拦住这类"对不上账的绿"。

    **表指纹不一致只给提示、不算错**：循环的正常姿势就是"改完表、再拿旧账 check 有没有真修掉"，
    拿指纹当错会把这条路堵死。真正的"文件过期"由**事实进键**那条抓（表变了 ⇒ 事实变了 ⇒
    该命中在账外 ⇒ 报错），那才是精确的判据。
    """
    errs, notes = [], []
    head = '\n'.join(l for l in text.splitlines() if l.startswith('>'))
    m = re.search(r'`([^`]+)`（sha256 ([0-9a-f]{6,})）', head)
    if not m:
        errs.append('头部没有"输入指纹"那一行（这份 drift.md 不是 `build` 出的？）')
    else:
        want = m.group(1)
        if Path(want).resolve() != Path(a.flowtable).resolve():
            errs.append(f'这份账是对着另一张表算的（账里 `{want}` ≠ 本次 `{a.flowtable}`）')
        else:
            now = hashlib.sha256(Path(a.flowtable).read_text(encoding='utf-8-sig')
                                 .encode('utf-8')).hexdigest()[:12]
            if now != m.group(2):
                notes.append(f'流程表自上次 build 起改过了（账里 {m.group(2)} → 现在 {now}）：'
                             f'这正是"改完表再对账"的正常姿势；若"已修"仍被报命中，就是没真修')
    for key, flag in (('账本', a.ledger), ('假设账', getattr(a, 'recon', None)),
                      ('清点', getattr(a, 'intake', None))):
        if flag is None:
            errs.append(f'账里记着用过「{key}」，这次 check 没给——**判据会静默少跑**，'
                        f'那种绿不算收敛（补上 `--{ {"账本": "ledger", "假设账": "recon", "清点": "intake"}[key] }`）')
    mt = re.search(r'`coverage_min_elements=(\d+)`', head)
    if mt and int(mt.group(1)) != th['coverage_min_elements']:
        errs.append(f'阈值对不上（账里 coverage_min_elements={mt.group(1)}，'
                    f'本次 {th["coverage_min_elements"]}）——阈值变了要重跑 build')
    return errs, notes


def cmd_check(a):
    """查收敛：**拿当前表重跑判据**，与文件里的处置对账（§5.4）。"""
    text = Path(a.card).read_text(encoding='utf-8-sig')
    drift, gaps, err = parse_doc(text)
    if err:
        print(f'✗ {a.card}: {err}')
        return 2
    got = prepare(a)
    if got['hard']:
        print(f'✗ 流程表结构不过（{len(got["hard"])} 条硬错）——先修结构：')
        for e in got['hard'][:5]:
            print(f'   · {e}')
        return 2
    if got['bad']:
        print(f'✗ 伴生表读坏了：{got["bad"]}')
        return 2
    head_bad, head_notes = check_header(text, a, got['th'])
    for n in head_notes:
        print(f'  · {n}')
    if head_bad:
        print(f'✗ 账与本次调用对不上（{len(head_bad)} 条）：')
        for e in head_bad[:10]:
            print(f'   · {e}')
        return 1
    rows_bad = check_drift_rows(drift, got['drift']) + check_gap_rows(gaps, got['gaps'])
    if rows_bad:
        print(f'✗ 没收敛：{len(rows_bad)} 条')
        for e in rows_bad[:20]:
            print(f'   · {e}')
        return 1
    explained = sum(1 for r in drift if r.get('处置（AI 填）') == '已解释')
    print(f'✓ 收敛：文件里 {len(drift)} 条漂移全部处置完（其中 {explained} 条判「已解释」）· '
          f'缺口 {len(gaps)} 条全部有结论；现在的判据读数没有漏在账外的')
    return 0


def main(argv=None):
    """子命令分发。**用显式 if 而不是 `set_defaults(func=…)`**：后者在静态调用图里看不见，

    `hygiene.py` 会把两个子命令函数判成"没人调"（门⑧当场红）。
    """
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='循环的发动机：漂移 → 缺口（PIPELINE-SPEC §5）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='出草稿（机器列已填，AI 列留空）')
    b.add_argument('flowtable', help='流程表路径，如 output/<流程名>/flowtable.md')
    b.add_argument('--ledger', help='证据账本 evidence.json（不给就跳过 D1/D2/D3/D4/D5）')
    b.add_argument('--recon', help='假设账 recon.md（不给就跳过 D2，缺口也填不了「走哪条路」）')
    b.add_argument('--intake', help='清点 intake.md（不给就跳过 D4）')
    b.add_argument('--dict', help='dictionary.yaml（默认取 scripts/ 下那份）')
    b.add_argument('-o', '--out', default='drift.md', help='写到哪里（默认 drift.md，落成果根）')
    b.add_argument('--force', action='store_true', help='覆盖已存在的产物（默认拒绝：那是漂移账）')
    b.add_argument('--todo', help='把「待填清单」写到这里（建议写成 <产物名>.todo.json，cells.py fill 默认就找它）')
    c = sub.add_parser('check', help='查收敛（拿当前表重跑判据，与文件里的处置对账）')
    c.add_argument('card', help='drift.md')
    c.add_argument('--flowtable', required=True, help='当前流程表（判据要重跑一遍）')
    c.add_argument('--ledger', help='证据账本 evidence.json')
    c.add_argument('--recon', help='假设账 recon.md')
    c.add_argument('--intake', help='清点 intake.md')
    c.add_argument('--dict', help='dictionary.yaml（默认取 scripts/ 下那份）')
    a = ap.parse_args(argv)
    return cmd_build(a) if a.cmd == 'build' else cmd_check(a)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
