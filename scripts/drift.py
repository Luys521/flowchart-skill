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

**分工**：脚本填机器可判的（判据 / 档 / 位置 / 事实，以及缺口的材料与现状）；
`处置` / `依据`（漂移）与 `要哪一片` / `状态` / `说明`（缺口）**留给 AI**。

**为什么必须配 `check`**：`build` 每次重出的草稿都是"未处置"，光看它永远不知道收没收敛。
`check` 拿**当前表重跑一遍判据**，于是两件机器判得死的事就成立了：
① 文件里标 `已修` 的，判据**必须不再命中**（说谎会被抓住）；② 判据现在命中的，**文件里必须都有**
（文件过期会被抓住）。收敛口径见 §5.4：**硬漂移 0 且缺口清单空**。

**为什么 `build` 拒绝覆盖已有的产物**：`drift.md` 同时是**漂移账**（发现 → 处置 → 依据），
AI 填过的格子被"重跑一次 build"静默抹掉，就是丢账。要重来就显式 `--force`（§2.4 不许静默降级同一条）。

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
BLANK = ('—', '-', '－', '无', '')

# 引用 id：element id（`M03#p012`）与裸材料号（`M03`）都在射程内（§2.2）。
ID_RE = re.compile(r'M\d{2,}(?:#[0-9A-Za-z_]+)?')
MID_RE = re.compile(r'M\d{2,}')


def _read_text(path):
    """读文本（容忍 BOM）。"""
    return Path(path).read_text(encoding='utf-8-sig')


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(_read_text(path))


def _writer(path, text):
    """落盘（UTF-8、LF、末尾留一个换行——与 §2.4 的其他产物同一套）。"""
    Path(path).write_text(text, encoding='utf-8', newline='\n')


def _sha(text):
    """输入指纹前 12 位：产物表头要打印它，事后才复核得了"这份结论是对着哪一版表算的"。"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def _esc(s):
    """单元格里的 `|` 会撕表 → 换全角（与 `intake.py` 同一口径）。"""
    return str(s if s is not None else '').replace('|', '｜').replace('\n', ' ').strip()


def _blank(s):
    """空值判据（`—` / 空 / `无` 都算没填）。"""
    return str(s or '').strip() in BLANK


def _refs(text):
    """单元格 → 引用到的 id 集合（element id 与裸 `M##` 都在内）。"""
    return set(ID_RE.findall(str(text or '')))


def _mat_of(ids):
    """id 集合 → 材料号集合。"""
    return {i.split('#')[0] for i in ids}


def _cited(nodes):
    """全表引用到的 id 集合：依据列 + 节点描述（描述里也会写"见 M05"这类引用）。"""
    got = set()
    for nd in nodes:
        got |= _refs(nd.get('basis')) | _refs(nd.get('desc'))
    return got


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


# ----------------------------------------------------------------读入（表 / 账本 / 两张伴生表）
def load_flowtable(path):
    """流程表 → `(nodes, edges, errs)`。用的是**结构校验的唯一入口**（`run_checks`），不另写一份解析。"""
    _, _, rows = parse_table(_read_text(path))
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
    header, out, err = None, {}, ''
    for line in _read_text(path).splitlines():
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


def _col(row, prefix):
    """按**列名前缀**取值（`状态（AI 填）` / `走哪条路` 这类名字前缀足够稳，后缀由对方决定）。"""
    for k, v in (row or {}).items():
        if str(k).startswith(prefix):
            return v
    return ''


# ----------------------------------------------------------------判据（每条一个函数，口径在 §5.2）
def _f(rule, pos, fact):
    """一条读数 → 行（判据号 / 位置 / 事实）。**档与文案渲染时从 `RULES` 取**，不在这里抄。"""
    return {'rule': rule, 'pos': pos, 'fact': fact}


def rule_d1(nodes, els):
    """D1 等级拔高：依据指向 `certainty=inferred`（`extractor=vlm`）或带 `degraded` 的证据，

    而该节点的描述**没有** `⚠` 留痕——把"我看到的 / 被截断的"当成"文件里逐字写着的"（§1.3 / §2.3）。
    """
    out = []
    for nd in nodes:
        why = []
        for i in sorted(_refs(nd.get('basis'))):
            e = els.get(i)
            if not e:
                continue
            if e.get('extractor') == 'vlm' or e.get('certainty') == 'inferred':
                why.append(f'`{i}` 是视觉推断（`certainty=inferred`）')
            elif e.get('degraded'):
                why.append(f'`{i}` 带降级留痕（{_esc(e.get("degraded"))[:40]}）')
        if why and pending_kind(nd.get('desc')) is None:
            out.append(_f('D1', f'节点 {nd["id"]}', '；'.join(why[:3])))
    return out


def rule_d2(nodes, recon):
    """D2 假设被推翻仍在用：假设账里 `状态 = 已推翻` 的材料，表里还有节点依据它。"""
    out = []
    for mid in sorted(mid for mid, r in recon.items() if _col(r, '状态') == '已推翻'):
        hits = sorted(nd['id'] for nd in nodes if mid in _mat_of(_refs(nd.get('basis'))))
        if hits:
            out.append(_f('D2', f'节点 {"、".join(hits)}',
                          f'假设账里 `{mid}` 记「已推翻」，而 {len(hits)} 个节点的「依据」仍指向它'))
    return out


def rule_d3(nodes, mats):
    """D3 建立在读不动的材料上：依据里的材料在账本里 `status=unreadable`——断言的来源不存在。"""
    out = []
    bad = {mid for mid, m in mats.items() if m.get('status') == 'unreadable'}
    for nd in nodes:
        hit = sorted(_mat_of(_refs(nd.get('basis'))) & bad)
        if hit:
            out.append(_f('D3', f'节点 {nd["id"]}',
                          '依据里的 ' + '、'.join(f'`{x}`' for x in hit) + ' 在账本里 `status=unreadable`'))
    return out


def rule_d4(nodes, intake):
    """D4 含流程的材料零引用 → **缺口**：这份材料的信息没进表（漏读，或读了没落表）。"""
    cited = _mat_of(_cited(nodes))
    out = []
    for mid in sorted(intake):
        if _col(intake[mid], '含流程') == '是' and mid not in cited:
            out.append(('D4', mid, '表里没有任何节点引用它的证据'))
    return out


def rule_d5(els, cited, th):
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
            out.append(('D5', mid, f'账本里 {n} 条元素，表里只引用 {used} 条（{used / n:.0%}）'))
    return out


def collect(nodes, _edges, els, mats, recon, intake, th):
    """跑全部**启用**的判据 → `(漂移行, 缺口行)`。缺哪个输入就整条跳过（§5.2 启用条件）。

    缺口行是 `(判据号, 材料号, 事实)`：**同一份材料可以被两条判据各报一次**（如"含流程零引用"
    与"读了没用上"），所以它按 `(判据, 材料)` 去重，**不按材料去重**——后者会把一条发现静默吃掉。

    `_edges` 只是与 `load_flowtable` 的返回形状对齐（曾经有一条判据要看边，实测被砍，见 §5.2）。
    """
    drift, gaps = [], []
    if els:
        drift += rule_d1(nodes, els)
        drift += rule_d3(nodes, mats)
        gaps += rule_d5(els, _cited(nodes), th)
    if els and recon:
        drift += rule_d2(nodes, recon)
    if els and intake:
        gaps += rule_d4(nodes, intake)
    drift.sort(key=lambda r: (r['rule'], r['pos']))
    return drift, sorted(set(gaps))


# ----------------------------------------------------------------渲染与校验
def _enabled(els, recon, intake):
    """本次**跳过**了哪几条判据（打印出来：**"跳过"与"跑了没命中"必须能分辨**）。"""
    off = []
    if not els:
        off += list(RULES)
    else:
        off += ([] if recon else ['D2']) + ([] if intake else ['D4'])
    return '、'.join(off) if off else '（无，五条全启用）'


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
        lab = RULES[r['rule']][0]
        lines.append(f'| `X{i:02d}` | {r["rule"]} {lab} | {_esc(r["pos"])} | '
                     f'{_esc(r["fact"])} | 待验 |  |')
    lines += ['', f'## ② 缺口清单（{len(gaps)} 条）', '',
              '| ' + ' | '.join(GAP_COLUMNS) + ' |',
              '|' + '---|' * len(GAP_COLUMNS)]
    for i, (rule, mid, note) in enumerate(gaps, 1):
        path = _col(meta['recon'].get(mid, {}), '走哪条路') or '—'
        lines.append(f'| `Q{i:02d}` | {rule} {RULES[rule][0]}：{_esc(note)} | `{mid}` |  | '
                     f'{_esc(path)} | 待取证 |  |')
    return '\n'.join(lines) + '\n'


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


def check_drift_rows(drift, live):
    """漂移账 → 错误清单。**该表与"现在的读数"双向对账**：

    ① 每条处置合法（`已解释` 必写依据）；② 标 `已修` 的**必须真的不再命中**（说谎会被抓住）；
    ③ 现在命中的**必须都在账内**（文件过期会被抓住）。
    """
    errs = []
    file_keys = {(((r.get('判据') or '').split() or [''])[0], r.get('位置')) for r in drift}
    live_keys = {(r['rule'], r['pos']) for r in live}
    for r in drift:
        rule = (r.get('判据') or '').split()[0]
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
        elif d == '已修' and (rule, r.get('位置')) in live_keys:
            errs.append(f'{r.get("漂移")}: 标了「已修」，但判据 {rule} 在 {r.get("位置")} 仍然命中')
    for rule, pos in sorted(live_keys - file_keys):
        errs.append(f'{rule} 在 {pos} 命中，但 `drift.md` 里没有这一条（文件过期？重跑 build --force）')
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


# ----------------------------------------------------------------子命令
def inputs_of(a):
    """一次运行的三份输入 → `(元素表, 材料表, 假设账, 清点, 报错)`。

    没给的输入都是空（对应判据整条跳过）；**给了但读坏了**要报出来，不许当成"没给"。
    """
    els, mats = ({}, {})
    if a.ledger:
        els, mats = index_ledger(_read_json(a.ledger))
    recon, e1 = read_side_table(getattr(a, 'recon', None))
    intake, e2 = read_side_table(getattr(a, 'intake', None))
    return els, mats, recon, intake, '；'.join(x for x in (e1, e2) if x)


def cmd_build(a):
    """出草稿：机器列已填，AI 那几列留空（`待验` / `待取证`）。"""
    out = Path(a.out)
    if out.exists() and not a.force:
        print(f'✗ {out} 已存在——它同时是**漂移账**（AI 填过的处置写在里面）。')
        print('  → 处置完先跑 `check`；确要重出草稿就显式加 `--force`（旧的会被覆盖）。')
        return 2
    draft = _read_text(a.flowtable)
    nodes, edges, errs = load_flowtable(a.flowtable)
    if errs.hard:
        print(f'✗ 流程表结构不过（{len(errs.hard)} 条硬错）——在坏表上判漂移是噪音，先修结构：')
        for e in errs.hard[:5]:
            print(f'   · {e}')
        return 2
    els, mats, recon, intake, bad = inputs_of(a)
    if bad:
        print(f'✗ 伴生表读坏了：{bad}')
        print('  → 「读坏了」与「没给」是两回事：当成没给会让对应判据**静默不跑**，那种绿比红危险。')
        return 2
    th = load_thresholds(a.dict)
    drift, gaps = collect(nodes, edges, els, mats, recon, intake, th)
    meta = {'table': a.flowtable, 'sha': _sha(draft), 'recon': recon,
            'coverage_min_elements': th['coverage_min_elements'],
            'coverage_min_ratio': th['coverage_min_ratio'],
            'off': _enabled(els, recon, intake),
            'inputs': ' · '.join(x for x in (
                f'账本 `{a.ledger}`' if a.ledger else '',
                f'假设账 `{a.recon}`' if a.recon else '',
                f'清点 `{a.intake}`' if a.intake else '') if x) or '（只有流程表）'}
    _writer(out, render(drift, gaps, meta))
    print(f'✓ 漂移 {len(drift)} 条 · 缺口 {len(gaps)} 条 → {out}')
    print(f'  · 跳过：{meta["off"]} · 输入：{meta["inputs"]}')
    print(f'  · 下一步：AI 填「处置 / 依据」与「要哪一片 / 状态 / 说明」，再跑')
    print(f'    python scripts/drift.py check {out} --flowtable {a.flowtable}'
          + (f' --ledger {a.ledger}' if a.ledger else '')
          + (f' --recon {a.recon}' if a.recon else '')
          + (f' --intake {a.intake}' if a.intake else ''))
    return 0


def cmd_check(a):
    """查收敛：**拿当前表重跑判据**，与文件里的处置对账（§5.4）。"""
    if not a.flowtable:
        print('✗ check 必须给 --flowtable：不重跑判据就没法知道「已修」是不是真修了')
        return 2
    drift, gaps, err = parse_doc(_read_text(a.card))
    if err:
        print(f'✗ {a.card}: {err}')
        return 2
    nodes, edges, errs = load_flowtable(a.flowtable)
    if errs.hard:
        print(f'✗ 流程表结构不过（{len(errs.hard)} 条硬错）——先修结构：')
        for e in errs.hard[:5]:
            print(f'   · {e}')
        return 2
    els, mats, recon, intake, bad = inputs_of(a)
    if bad:
        print(f'✗ 伴生表读坏了：{bad}')
        return 2
    live, live_gaps = collect(nodes, edges, els, mats, recon, intake, load_thresholds(a.dict))
    bad = check_drift_rows(drift, live) + check_gap_rows(gaps, live_gaps)
    if bad:
        print(f'✗ 没收敛：{len(bad)} 条')
        for e in bad[:20]:
            print(f'   · {e}')
        return 1
    explained = sum(1 for r in drift if r.get('处置（AI 填）') == '已解释')
    print(f'✓ 收敛：文件里 {len(drift)} 条漂移全部处置完（其中 {explained} 条判「已解释」）· '
          f'缺口 {len(gaps)} 条全部有结论；现在的判据读数没有漏在账外的')
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='循环的发动机：漂移 → 缺口（PIPELINE-SPEC §5）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='出草稿（机器列已填，AI 列留空）')
    b.add_argument('flowtable', help='流程表路径，如 output/<流程名>/flowtable.md')
    b.add_argument('--ledger', help='证据账本 evidence.json（不给就跳过 D1/D2/D3/D4/D6）')
    b.add_argument('--recon', help='假设账 recon.md（不给就跳过 D2，缺口也填不了「走哪条路」）')
    b.add_argument('--intake', help='清点 intake.md（不给就跳过 D4）')
    b.add_argument('--dict', help='dictionary.yaml（默认取 scripts/ 下那份）')
    b.add_argument('-o', '--out', default='drift.md', help='写到哪里（默认 drift.md，落成果根）')
    b.add_argument('--force', action='store_true', help='覆盖已存在的产物（默认拒绝：那是漂移账）')
    b.set_defaults(func=cmd_build)
    c = sub.add_parser('check', help='查收敛（拿当前表重跑判据，与文件里的处置对账）')
    c.add_argument('card', help='drift.md')
    c.add_argument('--flowtable', required=True, help='当前流程表（判据要重跑一遍）')
    c.add_argument('--ledger', help='证据账本 evidence.json')
    c.add_argument('--recon', help='假设账 recon.md')
    c.add_argument('--intake', help='清点 intake.md')
    c.add_argument('--dict', help='dictionary.yaml（默认取 scripts/ 下那份）')
    c.set_defaults(func=cmd_check)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
