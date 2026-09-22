# -*- coding: utf-8 -*-
"""table_to_dsl.py — 《flowtable.md》 → 内部 DSL(flow.yaml) + 结构校验门禁。

`--check` 只校验不产出；`--write` 产 DSL；`--write --layout HINT.yaml` 复用已润色图的几何（供 build 调用）。
检查分三层跑：① 节点 → ② 类型 → ③ 关系；H1–H8 明细见 references/flowtable-spec.md 第 3 节。
退出码：硬错误 → 1（阻断渲染）；仅软提示 → 0（`--quality showcase` 时软提示也阻断，见 D-55）。

本文件保留为**装配器与公开命令**：解析归 flowtable、校验归 flowtable_check、配色归 flowtable_colors、
布局归 flowtable_layout；这里只把五者按 `--check` / `--write` 的流程串起来，并写 DSL。
"""
import sys
import argparse
import json
from pathlib import Path

from artifact import artifact_name, artifact_stem
from geometry import snap, ceil_to, DEFAULT_COL_X, DEFAULT_GRID
from flowtable import Errors, COLOR_KEY, parse_table
from flowtable_check import run_checks, check_header, check_evidence
from flowtable_colors import resolve_colors, subject_map
from flowtable_layout import (parse_lane_order, auto_layout,
                              reuse_hint, merge_parallel_branches)
from semantics import findings_receipt, text_width
import thresholds
from flowtable import BLANK
import deps

try:
    import yaml
except ImportError:
    yaml = None


def build_dsl_nodes(nodes, hint_nodes=None):
    """流程表节点 → DSL 节点。row/col 优先取布局提示（手调值），语义字段一律来自流程表。"""
    hl = hint_nodes or {}
    dsl_nodes = []
    for n in nodes:
        hp_ = hl.get(n['id'])
        dn = {'id': n['id'], 'name': n['name'], 'lines': [n['name']], 'type': n['type'],
              'subject': n['subject'], 'executor': n['executor'],
              'row': (hp_['row'] if hp_ else n['row']), 'col': (hp_['col'] if hp_ else n['col']),
              'stage': n.get('stage') or '', 'route': n['route'], 'desc': n['desc']}
        if n['time'] and n['time'] not in ('—', '-', '无'):
            dn['time'] = n['time']
        for _k in ('input', 'basis', 'output'):
            _v = (n.get(_k) or '').strip()
            if _v and _v not in BLANK:
                dn[_k] = _v
        dsl_nodes.append(dn)
    return dsl_nodes


def _parse_args(argv):
    """解析 table_to_dsl 的命令行参数。"""
    ap = argparse.ArgumentParser(description='《flowtable.md》→ DSL 转换 + 结构校验门禁')
    ap.add_argument('ft_path', help='flowtable.md 路径')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true', help='仅跑结构校验，不产出')
    g.add_argument('--write', action='store_true', help='校验通过后转为内部 DSL')
    g.add_argument('--fresh', action='store_true',
                   help='只答"表自上次渲染后有没有被直改过"，不校验、不产出（rc 1 = 改过或无从判断）')
    ap.add_argument('--layout', help='复用已润色 DSL 的布局提示（.yaml）')
    ap.add_argument('-o', '--out', help='输出 flow.yaml 路径（约定名 flowtable.md → 同目录 flow.yaml）')
    ap.add_argument('--quality', choices=['standard', 'showcase'], default='standard',
                    help='showcase：零软提示才放行（软提示也阻断）；默认 standard 与从前一致（D-55）')
    ap.add_argument('--json', action='store_true',
                    help='以 JSON 透出结构化校验结果（message/subject/fix，见 D-55）')
    return ap.parse_args(argv)


def _load_flowtable(p):
    """校验流程表存在与 PyYAML 可用，解析出 (标题, 元信息, 行)；任一缺失返回 None。"""
    if not p.exists():
        print(f'✗ 找不到流程表文件: {p}')
        return None
    if yaml is None:
        print(f'✗ 缺少依赖 PyYAML：{deps.hint("yaml")}')
        return None
    # utf-8-sig：带 BOM 的流程表按裸 utf-8 读会让标题行带上 \ufeff、元信息匹配失效
    title, tbl_meta, rows = parse_table(p.read_text(encoding='utf-8-sig'))
    if not rows:
        print('✗ 未在文件中找到流程表表格（应为 "| 阶段 | 编号 | … |" 的 markdown 表格）')
        return None
    return title, tbl_meta, rows


def _run_checks(p, tbl_meta, rows):
    """跑 H1–H9 结构校验与配色解析，返回 (模式, 列序, 配色, 节点, 边, 错误集, 槽位备注)。"""
    errs = Errors()
    # H9 表头规范先于一切：键笔误丢的语义与 H1–H8 同级，且要和 H1–H8 一起列出（D-56）
    check_header(tbl_meta, p, errs)
    # H10 证据完整性（§6）：**有账本时才启用**——它核的是"依据指的东西真的在账本里"，
    # 没有账本（口头需求 / 示例表 / 自举树）就跳过，不许误伤（§8.1 的误伤回归也是这条）
    check_evidence(p.read_text(encoding='utf-8-sig'), p, errs)
    mode = 'swimlane' if '泳道' in (tbl_meta.get('输出布局') or '') else 'flow'
    lane_order = parse_lane_order(tbl_meta.get('泳道列序')) if mode == 'swimlane' else []
    # 配色在结构校验**之前**解析：它是硬错误（声明写错要拦下），且错误要跟 H1~H8 一起列出，
    # 而不是等到渲染阶段才炸——那时用户已经看了一半输出，会以为表没问题。
    colors, color_errs = resolve_colors(p, tbl_meta.get(COLOR_KEY))
    for e in color_errs:
        errs.err(e)
    slot_notes = []
    nodes, edges, errs = run_checks(rows, mode, errs, lane_order, slot_notes)
    return mode, lane_order, colors, nodes, edges, errs, slot_notes


def _report_checks(title, nodes, edges, errs, slot_notes, as_json):
    """打印校验结果（--json 走结构化，否则走人类可读文本）。"""
    hard = errs.hard
    checked = bool(getattr(errs, 'evidence_checked', False))
    led = getattr(errs, 'evidence_ledger', '') or ''
    skip = getattr(errs, 'evidence_skip', '') or ''
    if as_json:
        print(json.dumps({'hard': findings_receipt(errs.hard),
                          'soft': findings_receipt(errs.soft),
                          'nodes': len(nodes), 'edges': len(edges),
                          # **机器那份也要说清 H10 跑没跑**（D-108）：`--json` 的消费者
                          # （门②、等价夹具、子代理）以前只能从文本里猜这一层。
                          'evidence': {'checked': checked, 'ledger': led, 'skip': skip}},
                         ensure_ascii=False, indent=1))
    else:
        print(f'《{title}》  节点:{len(nodes)}  边(解析):{len(edges)}')
        if hard:
            print(f'✗ 结构校验未通过（{len(hard)} 项硬错误）→ 已阻断渲染：')
            for m in hard:
                print('   -', m)
        else:
            print('✓ 结构校验通过（①节点 ②类型 ③关系）：'
                  'H1起止 · H2编号 · H3引用 · H4分支 · H5结束 · H6死循环 · H7语义 · H8连通 · H9表头'
                  + (f' · H10引用完整（账本 {led}）' if checked and led else ''))
        if not checked:
            # **跳过的理由要说准**（D-108）：一路向上找遍了没有账本 ≠ "本表附近没有账本"。
            print(f'ℹ H10 引用完整这一层跳过：{skip or "本表附近没有证据账本"}'
                  '（纯口头需求 / 示例表 / 自举树都属这类）')
        if errs.soft:
            print('⚠ 软提示（不阻断，请 AI 处理并打 ⚠ 留痕）：')
            for m in errs.soft:
                print('   -', m)
        if slot_notes:
            print('· 槽位求解：' + '；'.join(slot_notes))


def _enforce_showcase(hard, errs, quality):
    """showcase 档要求零软提示；有软提示则阻断并返回 1。"""
    if not hard and quality == 'showcase' and errs.soft:
        print(f'✗ showcase 档要求零软提示（现有 {len(errs.soft)} 条）→ 已阻断（D-55）。'
              f'逐条处理完，或改用 standard 档重跑')
        return 1
    return 0


def _load_hint(layout_path, mode):
    """读布局提示 yaml（泳道布局不借提示）；文件不存在时告警并返回 None。"""
    hint = None
    if layout_path and mode != 'swimlane':      # 泳道布局与流程布局几何不同，不借用提示
        hp = Path(layout_path)
        if not hp.exists():
            print(f'⚠ 布局提示不存在，回退到基线自动布局: {hp}')
        else:
            hint = yaml.safe_load(hp.read_text(encoding='utf-8-sig'))
    return hint


def _assemble_dsl(nodes, edges, mode, lane_order, colors, title, hint):
    """按布局提示或泳道/流程分派组装 DSL，返回 dsl 字典。"""
    if hint:
        # 列中心吸入粗格：提示可能来自手改过的 yaml 或旧版本产物，离格值一旦落盘
        # 就会与渲染结果（geometry 会吸附）不一致，sync 比对时冒假 diff。
        # **显式空表**（`col_x: []`）与"没写这个键"是两回事：前者是"按字典 col_pitch 展开"
        # （多列产物的写法），当成缺省单列会让 col=1 的节点直接报"列号越界"。
        raw_cx = (hint.get('layout') or {}).get('col_x')
        if raw_cx:
            col_x = [snap(x, DEFAULT_GRID['node']) for x in raw_cx]
        else:
            col_x = [] if raw_cx is not None else [DEFAULT_COL_X]
        # **旧几何的形状坏了要说人话**（G49）：`hint['nodes']` 缺键原先直接 KeyError 裸栈——
        # 而提示来自"用户手改过 / 旧版本的 yaml"，那是**外部输入**。抛 ValueError（人话），
        # 由 `_write_dsl` 接住退 2——与 `engine.load` 把 KeyError 兜成中文同一手法。
        try:
            hnodes = {n['id']: n for n in hint['nodes']}
        except (KeyError, TypeError) as e:
            raise ValueError(
                f'旧几何（提示）形状不对（{type(e).__name__}: {str(e)[:80]}）——'
                f'它可能被手改过或是旧版本的产物；用 `--no-layout` 丢弃旧几何重排，'
                f'或删掉那份 yaml 再跑') from e
        dsl_nodes = build_dsl_nodes(nodes, hnodes)
        # 先用（提示的）行列推出 kind，再让提示只覆盖几何
        base_edges = auto_layout(dsl_nodes, edges)
        dsl_edges = reuse_hint(base_edges, hint)
    else:
        if mode == 'swimlane':
            col_x = []                                # 泳道列中心由部门列宽推出
        else:
            merge_parallel_branches(nodes, edges)     # 并行分支并排（D-37）
            # 单列时写死首列中心（与既有产物逐字节一致）；多列时留空，由 geometry 按字典
            # `layout.col_pitch` 展开——那份数值的家在字典（D-29），不在本脚本里再抄一遍。
            col_x = [DEFAULT_COL_X] if max(n['col'] for n in nodes) == 0 else []
        dsl_edges = auto_layout(nodes, edges)
        dsl_nodes = build_dsl_nodes(nodes)

    meta = {'title': title, 'subjects': subject_map(nodes, lane_order, colors), 'layout': mode}
    if lane_order:
        # 声明列序 = 采纳槽位模式：渲染层据此把左侧阶段带按「连续同阶段」合并（见 swimlane.SwimGrid）
        meta['lane_order'] = lane_order
    return {'meta': meta,
            'layout': {'col_x': col_x},
            'nodes': dsl_nodes, 'edges': dsl_edges}


def _emit_dsl(dsl, p, out_path):
    """落盘 DSL 并打印下一步提示，返回 DSL 路径。

    默认输出也按 D-51 带流程名：`<流程名>-flow.yaml`（与 build.py 的三件套同源）。
    早先这里对约定名写死 `flow.yaml`，于是"直接跑 table_to_dsl 不带 -o"与
    "跑 build.py" 产出两个不同名字的 yaml——手工跑一次就把 build 的几何提示换了个文件。
    """
    out = Path(out_path) if out_path else p.with_name(artifact_name(artifact_stem(p), 'yaml'))
    out.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding='utf-8', newline='\n')
    print(f'✓ 已生成内部 DSL: {out}  → 下一步：python validate.py "{out}"')
    return out


def _emit_manifest(dsl, out, p):
    """与 DSL 同刻产出渲染契约（供下游渲染后反查产物，见 DECISIONS.md D-11）。

    同时记下**《流程表》自己的指纹**：契约里其余字段都是产物的口径，只有这一条能回答
    "这张表还是不是渲染时那一版"（见 `manifest.source_stale`）。
    """
    from manifest import (build as _mf_build, manifest_path_for as _mf_path,
                         summary as _mf_summary, dsl_fingerprint as _mf_sha,
                         source_fingerprint as _mf_src_sha)
    mf = _mf_build(dsl, source=p.name, dsl_sha=_mf_sha(out), ft_sha=_mf_src_sha(p))
    mf_path = _mf_path(out)
    mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1) + '\n',
                       encoding='utf-8', newline='\n')
    print(f'✓ 渲染契约: {mf_path}  {_mf_summary(mf)}')


def _run_fresh(p):
    """`--fresh`：只答一句"这张表自上次渲染后有没有被直改过"，不校验、不产出。

    为什么要单开一支：产物、DSL、契约可以**互相一致，却同时落后于事实源**——手工改了表而没重跑
    build 时，「契约已过期」那条判据不响（yaml 一个字没动），八项门禁也照样全绿。这里补那个缺口。
    退出码：0 = 与渲染时一致；1 = 改过，或**无从判断**（没有基线，按保守路线处理）。
    """
    from artifact import artifact_stem
    from manifest import manifest_path_for, source_stale, source_fingerprint
    yaml_path = p.with_name(artifact_name(artifact_stem(p), 'yaml'))
    state, detail = source_stale(p, manifest_path_for(yaml_path))
    if state == 'same':
        print(f'✓ 表自上次渲染后未变（指纹 {detail}）')
        return 0
    if state == 'nobase':
        print(f'· 无从判断：{detail}——按"可能被改过"处理，回第一段重走校验与出图最稳')
        return 1
    print(f'✗ 表自上次渲染后改过：{detail}')
    print(f'   这是绕过流水线的直改（当前指纹 {source_fingerprint(p)}）：'
          f'回第一段把口径确认好，再重跑校验与出图。'
          f'**不要拿图去回灌它**——回灌是按图重建表格行的，手工加的节点会被删掉')
    return 1


#: `label_badge` / `layout` 两段里本脚本要用的字段的**内置默认**。
#: `thresholds.load(section, defaults)` 的口径就是"默认 + 字典覆盖"，而面① 会断言这两份默认与
#: `dictionary.yaml` 同值——所以这里只列本函数真读的字段，不抄整段。
_BADGE_DEFAULTS = {'full_width': 12, 'half_width': 7, 'padding': 16}
_LAYOUT_DEFAULTS = {'right_channel_step': 40, 'right_channel_step_max': 80}


def _derive_channel_step(dsl, mode):
    """按**这张图最宽的标签**定通道档距，写进 `layout`（派生量，与 `width` / `origin_x` 同一路数）。

    为什么要派生（G87/D-155）：档距有两条约束，而"一个数管所有表"两头都不合适——
      · 40：自举树（最长标签 2 字、徽章 40px）紧凑，可 workflow 那张表最长的标签 4 字（徽章 64px）
        就得**折两排**，于是同一张图里折的与不折的混在一起（作者 2026-09-22 看到的"处理不一致"）；
      · 80：全都不折，但把自举树的绕行抬到门槛外（门⑨ 实测均值 49% / 最坏 83%）。
    所以档距按图算：最宽徽章吸到粗格，夹在 `[right_channel_step, right_channel_step_max]` 之间。
    上限之外还有更长的标签才折排（G85）——折排从此是**兜底**，不是常态。
    """
    if mode == 'swimlane':
        return
    b = thresholds.load('label_badge', _BADGE_DEFAULTS)
    lay_cfg = thresholds.load('layout', _LAYOUT_DEFAULTS)
    GN = DEFAULT_GRID['node']
    step = int(lay_cfg.get('right_channel_step', 40))
    cap = int(lay_cfg.get('right_channel_step_max', 80))
    pad, full, half = b['padding'], b.get('full_width', 12), b.get('half_width', 7)
    widest = max([text_width(e.get('label') or '', full, half) + pad
                  for e in (dsl.get('edges') or [])] or [0])
    dsl['layout']['right_channel_step'] = min(max(ceil_to(widest, GN), step), cap)


def _center_canvas(dsl, mode):
    """流程布局：把画布**贴合内容**、并让内容横向居中（泳道布局不动——它的宽度本来就由列宽算出）。

    做法是"**量一次再平移**"：先把当前 DSL 落成临时 yaml、载入引擎（引擎会跑路由，量到的是**含通道与
    标签**的真 ink），再按粗格定两个派生量写进 `layout`：

    · `origin_x` —— 画布左留白。`Grid` 把它加在**每一列**上、`Router` 把它加在左侧回路通道的基准上；
      **不写进 `col_x`**：`col_x` 留空是有含义的（"按字典 col_pitch 展开"，见 `_assemble_dsl`），
      把展开结果写死等于把字典里的列距抄进本脚本——那正是 D-29 禁掉的。
    · `width` —— 画布宽。引擎取 `max(配置宽, 内容右沿 + 边距)`：写小了它会自己撑开，写大了才有空当。
      下限取标题/图例块宽：那块居中画在 `width/2`（drawio 版画在画布内），画布比它窄就会被裁。

    为什么平移是安全的：x 锚点全是 col_x 的函数（右通道 = max(col_x) + 偏移、左族上限 = 最左节点边 − 边距），
    平移是刚体运动 ⇒ 第二次跑量到的 ink 已经居中、Δ = 0，**幂等**，不会越跑越偏。
    """
    if mode == 'swimlane':
        return
    _derive_channel_step(dsl, mode)      # 必须在落临时 yaml **之前**：它会影响通道位置，也就影响居中量
    import tempfile
    from engine import load as _load
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / 'flow.yaml'
        tmp.write_text(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False), encoding='utf-8', newline='\n')
        L = _load(str(tmp))
        xs = []
        for n in dsl['nodes']:
            x, _y, w, _h = L.rect(n['id'])
            xs += [x, x + w]
        for e in L.edges:
            xs += [px for px, _py in L.path(e)]
            if e.get('label'):
                lx, _ly, lw, _lh = L.label_box(e)
                xs += [lx, lx + lw]
    if not xs:
        return
    cfg = L.cfg.get('layout') or {}
    GN = L.grid.node_grid
    margin = cfg.get('channel_margin', 40)
    x0, x1 = min(xs), max(xs)
    lay = dsl['layout']
    lay['width'] = ceil_to(max(x1 - x0 + 2 * margin, L.legend_width() + 2 * margin), GN)
    lay['origin_x'] = snap(lay['width'] / 2 - (x0 + x1) / 2, GN)


def _write_dsl(p, nodes, edges, mode, lane_order, colors, title, layout_path, out_path):
    """--write 路径：读布局提示 → 组装 DSL → 量一次并居中画布 → 落盘 DSL 与渲染契约；返回退出码。

    **旧几何形状不对**（G49）：`_assemble_dsl` 抛 `ValueError`（提示是外部输入），这里接住
    打人话并退 2——原先它一路 KeyError 裸栈出去，读的人以为脚本坏了。
    """
    hint = _load_hint(layout_path, mode)
    try:
        dsl = _assemble_dsl(nodes, edges, mode, lane_order, colors, title, hint)
    except ValueError as e:
        print(f'✗ {e}')
        return 2
    _center_canvas(dsl, mode)
    out = _emit_dsl(dsl, p, out_path)
    _emit_manifest(dsl, out, p)
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _parse_args(argv)

    p = Path(a.ft_path)
    if a.fresh:
        return _run_fresh(p)
    loaded = _load_flowtable(p)
    if loaded is None:
        return 1
    title, tbl_meta, rows = loaded

    mode, lane_order, colors, nodes, edges, errs, slot_notes = _run_checks(
        p, tbl_meta, rows)
    hard = errs.hard
    _report_checks(title, nodes, edges, errs, slot_notes, a.json)

    if _enforce_showcase(hard, errs, a.quality) != 0:
        return 1
    if a.check:
        return 1 if hard else 0
    if hard:
        print('✗ 因结构校验未过，不产出 DSL。请先修正流程表。')
        return 1

    return _write_dsl(p, nodes, edges, mode, lane_order, colors, title, a.layout, a.out)


if __name__ == '__main__':
    sys.exit(main())
