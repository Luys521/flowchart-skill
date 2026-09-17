# -*- coding: utf-8 -*-
"""validate.py — 质量门禁：八项几何检查 + 报告 + 命令行。

三层结构，改动时按层定位：检查层 `check_xxx(L, rects)` 纯函数（**不打印、不退出**）、
编排层 `check(L)`（按依赖顺序串起八项；引用/列号/类型坏了直接返回）、
呈现层 `report(L, errs, notes)`（stdout 与退出码）。

几何谓词**只在 geometry.py 实现一次**，router 的主动避让与这里的事后复检共用——两套实现迟早给出不同答案。
第 3、4、8 项已被主动保证，这里是事后复检。八项明细与用法见 references/visual-spec.md。
"""
import argparse
import json
import math
import sys
from pathlib import Path

from engine import load
from geometry import RECT_SHAPES, point_seg_dist, rects_overlap, seg_overlap, seg_rect_hit
from semantics import Finding, findings_receipt

PORTS = ('top', 'bottom', 'left', 'right')
THROUGH_SHRINK = 2   # 「边穿无关节点」判定的矩形内缩量：贴边不算穿
OWN_SHRINK = 6       # 「横穿自身节点」判定的矩形内缩量：端口向外出线不算横穿
CHECK_NAMES = ('引用完整', '节点不重叠', '边不穿节点', '边不横穿自身端点',
               '边不重叠', '标签压线不压节点', '画布内', '网格对齐')
OK_LINE = ('✓ 全部通过：零节点重叠 / 零边穿节点 / 零边横穿自身端点 / 零边重叠（正交交叉已允许）/ '
           '标签全部压线不压节点 / 引用完整 / 画布内 / 网格对齐')


# ---------------------------------------------------------------- 检查层
def check_refs(L):
    """1. 引用完整：端点存在、端口合法、列号与类型在字典范围内。

    必须排在几何之前——列号越界 / 类型未知会让 rect() 直接抛异常，轮不到中文报错出场。
    """
    errs = []
    ids = {n['id'] for n in L.dsl['nodes']}
    for i, e in enumerate(L.edges, 1):
        if e['from'] not in ids:
            errs.append(Finding(f'边{i}: from 引用不存在的节点 {e["from"]}',
                                subject=f'edge{i}', fix='核对边引用的节点 id；节点改名/删除后边的引用要跟上'))
        if e['to'] not in ids:
            errs.append(Finding(f'边{i}: to 引用不存在的节点 {e["to"]}',
                                subject=f'edge{i}', fix='核对边引用的节点 id；节点改名/删除后边的引用要跟上'))
        ex, en = L.ports(e)
        if ex not in PORTS:
            errs.append(Finding(f'边{i}: 非法 exit {ex}', subject=f'edge{i}',
                                fix='端口名只有 top / bottom / left / right'))
        if en not in PORTS:
            errs.append(Finding(f'边{i}: 非法 entry {en}', subject=f'edge{i}',
                                fix='端口名只有 top / bottom / left / right'))
    for n in L.dsl['nodes']:
        if not (0 <= n['col'] < len(L.col_x)):
            errs.append(Finding(f'节点 {n["id"]}: 列号越界 col={n["col"]}，'
                                f'layout.col_x 只有 {len(L.col_x)} 列（新增列时要把 col_x 一起补上）',
                                subject=n['id'],
                                fix='layout.col_x 补一列（新列中心 = 上一列中心 + col_pitch），或把 col 改回已有列'))
        if n['type'] not in L.sizes:
            errs.append(Finding(f'节点 {n["id"]}: 未知类型 {n["type"]}（字典 shapes 里没有）',
                                subject=n['id'], fix='类型改回字典 shapes 里有的名字'))
    return errs


def check_overlap(L, rects):
    """2. 节点互不重叠"""
    errs = []
    nodes = L.dsl['nodes']
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if rects_overlap(rects[nodes[i]['id']], rects[nodes[j]['id']]):
                errs.append(Finding(f'节点重叠: {nodes[i]["id"]} × {nodes[j]["id"]}',
                                    subject=f'{nodes[i]["id"]},{nodes[j]["id"]}',
                                    fix='调整 row/col 分层，或加大 gapx（泳道布局调 row）'))
    return errs


def check_edge_through_nodes(L, rects):
    """3. 边不穿过无关节点（矩形内缩 2px：贴边不算穿）"""
    errs = []
    for i, e in enumerate(L.edges, 1):
        pts = L.path(e)
        for k in range(len(pts) - 1):
            for nid, r in rects.items():
                if nid in (e['from'], e['to']):
                    continue
                if seg_rect_hit(pts[k], pts[k + 1], r, grow=-THROUGH_SHRINK):
                    errs.append(Finding(f'边{i}({e["from"]}→{e["to"]}) 穿过节点 {nid}',
                                        subject=f'{e["from"]}→{e["to"]}',
                                        fix='删掉手写的 gutter/channel 让 router 重排（泳道为 sdye/dye）'))
    return errs


def _on_border(p, rect, shape=None, tol=0.6):
    """点是否落在该形状的**可视边界**上。

    矩形类查四条边；菱形/椭圆是**内接**于外接矩形的，只有边中点那一点与矩形重合——
    锚点一旦沿边偏移（`sdye`/`dye`），线就离开真实形状悬在空中（实测 12→13 悬空 16px、
    13→10 悬空 27px）。所以这里必须按形状判，只比外接矩形等于没查。
    """
    x, y, w, h = rect
    if not (x - tol <= p[0] <= x + w + tol and y - tol <= p[1] <= y + h + tol):
        return False
    hw, hh = w / 2, h / 2
    dx, dy = abs(p[0] - (x + hw)), abs(p[1] - (y + hh))
    if shape in ('rhombus', 'ellipse') and hw and hh:
        # 沿 中心→p 的射线，形状边界落在 t=1；点到边界的距离 = r·(1 − 1/t)
        if shape == 'rhombus':
            t = dx / hw + dy / hh
        else:
            t = math.hypot(dx / hw, dy / hh)
        if t <= 0:
            return False
        r = math.hypot(dx, dy)
        return abs(r * (1 - 1 / t)) <= tol
    return (abs(p[0] - x) <= tol or abs(p[0] - (x + w)) <= tol
            or abs(p[1] - y) <= tol or abs(p[1] - (y + h)) <= tol)


def _seg_in_shape(pts, rect, shape, margin):
    """折线是否穿进该形状的**内部**（按形状判，`margin` 向内收）。

    必须按形状判：非矩形节点的锚点经投影后落在**外接矩形内部**（菱形斜边上），
    若仍拿内缩矩形去判，正常的出线也会被误报成"横穿自身节点"。
    轴向线段到中心的最近点 = 该段上最"深入"形状的点，取它算 t 即可判内外。
    """
    x, y, w, h = rect
    cx, cy, hw, hh = x + w / 2, y + h / 2, w / 2, h / 2
    if not (hw and hh):
        return False
    for k in range(len(pts) - 1):
        p1, p2 = pts[k], pts[k + 1]
        if abs(p1[1] - p2[1]) <= 0.6:                       # 水平段
            qx = min(max(cx, min(p1[0], p2[0])), max(p1[0], p2[0]))
            qy = p1[1]
        elif abs(p1[0] - p2[0]) <= 0.6:                     # 竖直段
            qx = p1[0]
            qy = min(max(cy, min(p1[1], p2[1])), max(p1[1], p2[1]))
        else:
            qx, qy = p1
        dx, dy = abs(qx - cx), abs(qy - cy)
        t = (dx / hw + dy / hh) if shape == 'rhombus' else math.hypot(dx / hw, dy / hh)
        if t < 1 - margin / min(hw, hh):
            return True
    return False


def check_edge_own_nodes(L, rects):
    """4. 边的**端点必须落在源/目标节点的边框上**，且不横穿该节点内部（内缩 6px）。

    端点查"线有没有真的接上节点"——且按**真实形状**判：菱形/椭圆内接于外接矩形，
    只查外接矩形的边会放行"线悬在菱形斜边外 16~27px"这类缺陷（实测 12→13）。
    "横穿"同样按形状判（非矩形节点的锚点投影后本就在外接矩形内部，按矩形判会误报）。
    布线层由 `anchor()` 保证端点位置，但此前**没有门禁复核**：sdye/dye 算错、端口写错、
    尺寸变化都会让线悬空而其余七项照样全绿。`grow` 为负是**内缩**，这样"端口向外出线"不算横穿。
    """
    errs = []
    shapes = L.cfg.get('shapes') or {}
    for i, e in enumerate(L.edges, 1):
        pts = L.path(e)
        if len(pts) < 2:
            # 首尾端点要有"首"有"尾"才谈得上接没接上：geometry_from_html 碰到畸形的 `d`
            # （非 M/L 指令、或坐标缺失）只解析得出 0~1 个点，下面的 pts[0]/pts[-1] 会直接抛
            # IndexError，门禁以 traceback 收场，真正的问题"这条边根本没画出来"反而看不见。
            # 同为产物反解的 geometry_table 早有 `if pts else None` 的守卫，这里补上同一口径。
            errs.append(Finding(f'边{i}({e["from"]}→{e["to"]}) 的折线缺失/不完整'
                                f'（产物里只解析出 {len(pts)} 个折点）：边没画出来或 d 属性损坏',
                                subject=f'{e["from"]}→{e["to"]}',
                                fix='重新渲染产物；重渲染后仍如此，检查渲染器输出的 path d 属性是否只有一段'))
            continue
        for nid, p in ((e['from'], pts[0]), (e['to'], pts[-1])):
            shp = shapes.get(L.nodes[nid]['type'], {}).get('shape')
            if not _on_border(p, rects[nid], shp):
                errs.append(Finding(f'边{i}({e["from"]}→{e["to"]}) 的端点 ({p[0]:g}, {p[1]:g}) 不在 {nid} 的边框上'
                                    f'——线没接上节点',
                                    subject=f'{e["from"]}→{e["to"]}',
                                    fix='删掉手写的 exit/entry（含 sdye/dye）让 router 重定端口'))
        for nid in (e['from'], e['to']):
            shp = shapes.get(L.nodes[nid]['type'], {}).get('shape')
            if shp in ('rhombus', 'ellipse'):
                hit = _seg_in_shape(pts, rects[nid], shp, OWN_SHRINK)
            else:
                hit = any(seg_rect_hit(pts[k], pts[k + 1], rects[nid], grow=-OWN_SHRINK)
                          for k in range(len(pts) - 1))
            if hit:
                errs.append(Finding(f'边{i}({e["from"]}→{e["to"]}) 横穿自身节点 {nid}：'
                                    f'端口方向与走向矛盾（箭头会被节点遮盖）',
                                    subject=f'{e["from"]}→{e["to"]}',
                                    fix='端口朝向与走向矛盾：删掉手写 gutter/channel（泳道 sdye/dye）后重跑'))
    return errs


def _segment_paths(L):
    """每条边的折线 → 线段列表（相邻折点成段），供两两比对。"""
    return [[(p[k], p[k + 1]) for k in range(len(p) - 1)] for p in (L.path(e) for e in L.edges)]


def _edge_overlap_errors(L, paths):
    """两两共线重叠的边（共享端点的分叉/合流豁免）→ 错误列表。"""
    errs = []
    for i in range(len(L.edges)):
        for j in range(i + 1, len(L.edges)):
            a, b = L.edges[i], L.edges[j]
            if {a['from'], a['to']} & {b['from'], b['to']}:
                continue
            hit = next(((s1, s2) for s1 in paths[i] for s2 in paths[j] if seg_overlap(s1, s2)), None)
            if hit:
                (x1, y1), (x2, y2) = hit[0]
                errs.append(Finding(f'边{i + 1}({a["from"]}→{a["to"]}) 与 边{j + 1}({b["from"]}→{b["to"]}) '
                                    f'重叠于 ({round(x1)},{round(y1)})-({round(x2)},{round(y2)})：'
                                    f'两条线叠成一条，无法分辨',
                                    subject=f'{a["from"]}→{a["to"]}',
                                    fix='换一条通道：调整 gapx/channel，或加大 gutter_step'))
    return errs


def _edge_uturn_errors(L, paths):
    """出边把入边末段原路画回来的「掉头折返」→ 错误列表（DECISIONS.md D-15）。"""
    errs = []
    # 「掉头折返」：出边首段把入边末段**原路画回来**（DECISIONS.md D-15）。
    # 上面的豁免只对"分叉/合流"成立——两条边**同向**汇到一点才叫汇成一点；
    # 方向相反就是折返：线会压过节点边沿上的箭头，看起来像线穿过了框。
    for i in range(len(L.edges)):
        for j in range(len(L.edges)):
            if i == j or L.edges[i]['to'] != L.edges[j]['from']:
                continue
            pa, pb = paths[i], paths[j]          # 都是**线段**列表（不是点列表）
            if not pa or not pb:
                continue
            (s1, s2), (t1, t2) = pa[-1], pb[0]   # 入边最后一段 × 出边第一段
            if not seg_overlap((s1, s2), (t1, t2)):
                continue
            if (s2[0] - s1[0]) * (t2[0] - t1[0]) + (s2[1] - s1[1]) * (t2[1] - t1[1]) >= 0:
                continue                       # 同向 → 是分叉/合流，豁免成立
            errs.append(Finding(f'边{i + 1}({L.edges[i]["from"]}→{L.edges[i]["to"]}) 与 '
                                f'边{j + 1}({L.edges[j]["from"]}→{L.edges[j]["to"]}) '
                                f'在节点 {L.edges[j]["from"]} 的边沿掉头折返（共线反向）：'
                                f'出边把入边原路画回来，看起来像线穿过了框',
                                subject=f'{L.edges[j]["from"]}→{L.edges[j]["to"]}',
                                fix='出边换侧：给该节点出边错峰（sdye），或调整出边端口方向'))
    return errs


def check_edge_overlap(L, rects):
    """5. 边不重叠（允许正交交叉、允许共享端点的出/入段）。

    三条"禁止 / 允许"的边界最容易改错——图省事改成"端点集合有交集就跳过"，这项就废了。判据见 visual-spec 第 5 项。
    """
    paths = _segment_paths(L)
    return _edge_overlap_errors(L, paths) + _edge_uturn_errors(L, paths)


def _label_box_errors(L, rects):
    """逐边标签盒：中心压线 / 不压节点 / 不越界 → (错误列表, 标签盒清单)。"""
    errs = []
    boxes = []
    for i, e in enumerate(L.edges, 1):
        if not e.get('label'):
            continue
        bx, by, bw, bh = L.label_box(e)
        pts = L.path(e)
        c = (bx + bw / 2, by + bh / 2)
        if not any(point_seg_dist(c, pts[k], pts[k + 1]) < 6 for k in range(len(pts) - 1)):
            errs.append(Finding(f'边{i} 标签"{e["label"]}" 未压线', subject=f'edge{i}',
                                fix='先查标签是否过长（>4 字精简），再调 gapx'))
        for nid, r in rects.items():
            if rects_overlap((bx, by, bw, bh), r):
                errs.append(Finding(f'边{i} 标签"{e["label"]}" 压到节点 {nid}', subject=f'edge{i}',
                                    fix='调整路由高度（gapx/channel）或缩短标签'))
        if bx < 0 or bx + bw > L.width or by < 0 or by + bh > L.height():
            errs.append(Finding(f'边{i} 标签"{e["label"]}" 越界', subject=f'edge{i}',
                                fix='缩短标签或调整路由'))
        boxes.append((i, e['label'], (bx, by, bw, bh)))
    return errs, boxes


def _label_pair_errors(boxes):
    """两个标签盒互相重叠 → 错误列表。"""
    errs = []
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            i1, l1, x1 = boxes[a]
            i2, l2, x2 = boxes[b]
            if rects_overlap(x1, x2):
                errs.append(Finding(f'边{i1} 标签"{l1}" 与 边{i2} 标签"{l2}" 互相重叠：两个字叠在一起，看不清',
                                    subject=f'edge{i1}', fix='错开两边的路由高度，或缩短其中一个标签'))
    return errs


def check_labels(L, rects):
    """6. 标签：中心压线（距所属折线 < 6px）、不压节点、不越界、不压别的标签。

    **"压到别的边"有意不做**——为什么不做见 visual-spec 第 6 项，改成检查它必然误报。
    """
    errs, boxes = _label_box_errors(L, rects)
    return errs + _label_pair_errors(boxes)


def check_grid(L, rects):
    """8. 网格对齐：矩形类节点四边守粗格，非矩形格位与折点/通道/标签盒守细格"""
    gcfg = L.cfg.get('grid') or {}
    GL, GN = int(gcfg.get('lattice', 10)), int(gcfg.get('node', 20))
    shapes = L.cfg.get('shapes') or {}
    bad = []

    def chk(v, u, what):
        if abs(v - round(v / u) * u) > 0.01:
            bad.append(f'{what}={round(v, 2)} 非 {u} 的倍数')

    chk(L.width, GN, '画布宽')
    chk(L.height(), GL, '画布高')
    for n in L.dsl['nodes']:
        r = rects[n['id']]
        u = GN if shapes.get(n['type'], {}).get('shape') in RECT_SHAPES else GL
        for tag, v in (('left', r[0]), ('top', r[1]), ('right', r[0] + r[2]), ('bottom', r[1] + r[3])):
            chk(v, u, f'节点{n["id"]}.{tag}')
    for i, e in enumerate(L.edges, 1):
        for p in L.path(e):
            chk(p[0], GL, f'边{i}({e["from"]}→{e["to"]}).x')
            chk(p[1], GL, f'边{i}({e["from"]}→{e["to"]}).y')
        if e.get('label'):
            bx, by, bw, bh = L.label_box(e)
            chk(bx, GL, f'边{i}标签盒.left')
            chk(by, GL, f'边{i}标签盒.top')
            chk(bx + bw, GL, f'边{i}标签盒.right')
            chk(by + bh, GL, f'边{i}标签盒.bottom')
    return [f'网格对齐：{len(bad)} 处离格 —— ' + '；'.join(bad[:4]) + (' …' if len(bad) > 4 else '')] \
        if bad else []


def check_canvas(L, rects):
    """7. 画布内"""
    errs = []
    for nid, r in rects.items():
        if r[0] < 0 or r[1] < 0 or r[0] + r[2] > L.width or r[1] + r[3] > L.height():
            errs.append(Finding(f'节点 {nid} 越界', subject=nid,
                                fix='调整 row/col，或加大画布（width 随通道自动扩）'))
    for i, e in enumerate(L.edges, 1):
        for p in L.path(e):
            if p[0] < 0 or p[0] > L.width or p[1] < 0 or p[1] > L.height():
                errs.append(Finding(f'边{i} 路径越界 ({p[0]},{p[1]})', subject=f'{e["from"]}→{e["to"]}',
                                    fix='删掉手写通道让 router 重排，或加大画布'))
    return errs


GEOMETRY_CHECKS = (check_overlap, check_edge_through_nodes, check_edge_own_nodes,
                   check_edge_overlap, check_labels, check_canvas, check_grid)


# ---------------------------------------------------------------- 编排层
def _run_geometry_checks(L):
    """按依赖顺序跑七项几何检查（引用已验通过）→ 错误列表。"""
    rects = {n['id']: L.rect(n['id']) for n in L.dsl['nodes']}
    errs = []
    for fn in GEOMETRY_CHECKS:
        errs += fn(L, rects)
    return errs


def check(L):
    """八项检查 → (errors, notes)。纯函数：不打印、不退出，便于被其他脚本复用。"""
    errs = check_refs(L)
    if errs:
        return errs, []                    # 结构已坏，几何算不出来，直接返回
    return _run_geometry_checks(L), list(L.grid.notes)


# ---------------------------------------------------------------- 产物复核层
ARTIFACT_CHECKS = (check_overlap, check_edge_through_nodes, check_edge_own_nodes,
                   check_edge_overlap, check_canvas, check_grid)
# 产物侧判据的**规范清单**：前六项与模型侧同名同义（判据也只有一份实现），后三项是产物侧独有——
# "每段不短于一格粗格"两种布局都查，"里程碑带"与"底色铺满"只对**泳道底稿**查；
# 判"该不该有"的是 `_artifact_lane_expected`：拿得到底稿以底稿为准，拿不到才按产物自称。
# 它与文档成对：`references/visual-spec.md` §4.1 逐条写清"查什么 / 不查什么 / 不过就阻断"，
# `dev/verify/contract.py` 逐名核两处文档都提到——改了代码没改文档，当场红。
ARTIFACT_RULES = ('节点不重叠', '边不穿节点', '端点接在真实形状的边框上', '边不重叠', '画布内', '网格对齐',
                  '每一段不短于一格粗格', '不得落进左侧里程碑带', '底色必须盖住所有节点')
_SHAPE_TYPE = {'rhombus': '__rhombus', 'ellipse': '__ellipse'}


class _ArtifactL:
    """把"从产物读回的真实几何"包装成八项检查认识的样子。

    为什么要包装而不是另写一套：几何谓词与判据只能有一份实现，否则"布线时避开了"与
    "事后复检报出来"会给出不同答案（见文件头）。与真模型只差三处：形状**从产物读**
    （不是按类型查字典）、折线**从产物读**（不是重跑 router）、没有标签盒——
    所以第 6 项（标签）在产物侧不做。
    """

    def __init__(self, geom, lattice, node_grid):
        self.cfg = {'grid': {'lattice': lattice, 'node': node_grid},
                    'shapes': {'__rect': {'shape': 'rounded'},
                               '__rhombus': {'shape': 'rhombus'},
                               '__ellipse': {'shape': 'ellipse'}}}
        self._rect, nodes, dsl_nodes = {}, {}, []
        for nid, v in geom['nodes'].items():
            self._rect[nid] = v['rect']
            typ = _SHAPE_TYPE.get(v['shape'], '__rect')
            nodes[nid] = {'type': typ}
            dsl_nodes.append({'id': nid, 'type': typ})
        self.nodes, self.dsl = nodes, {'nodes': dsl_nodes}
        self.edges = geom['edges']
        self.width, self._h = geom['canvas']

    def rect(self, nid):
        return self._rect[nid]

    def path(self, e):
        return e['pts']

    def height(self):
        return self._h


def _artifact_lane_expected(geom, expect_lanes):
    """这份产物该不该有泳道底图：**调用方知道就照它判**，不知道（None）才按产物自称判。

    为什么必须有这个参数（2026-09-15 实测）：「流程布局的产物」与「泳道源但底图没画」的产物
    在几何表上**完全同形**——两者都是 `band=0 / lanes=None`（`examples/workflow` 是流程布局，
    实测三份产物全是 0/None）。只看产物的话，"泳道源被渲染成流程样"这个洞永远抓不到，
    而那正是这两条判据此前"输入缺失就自我跳过"的根因。
    知道底稿的那一层（`build` 手里有 yaml）把 `L.lanes() is not None` 传下来，洞才堵上；
    拿不到底稿的入口（`validate.py --artifact`）只能退化为"自称"——**这是明说的弱化，不是静默**。
    """
    if expect_lanes is not None:
        return expect_lanes
    return bool(geom.get('band')) or geom.get('lanes') is not None


def _artifact_band_errors(geom):
    """泳道左侧里程碑带：**必须存在**（没带＝底图没画），且折点不得落进标注区。"""
    # 泳道底图最左边那条里程碑带是标注区，线压上去就是"底图与线撞车"——带宽从**产物**读
    # （底色带一律从 x=0 起画），不靠配置反推，这样渲染器少画/多画一条带也躲不过（D-39）。
    band = geom.get('band') or 0
    if not band:
        return ['产物里没有里程碑带宽（band）：泳道底图的左侧阶段带没画']
    errs = []
    for i, e in enumerate(geom['edges'], 1):
        bad = [p for p in e['pts'] if p[0] < band - 0.6]
        if bad:
            errs.append(f'边{i}({e["from"]}→{e["to"]}) 的折点 x={bad[0][0]:g} 落在左侧里程碑带内'
                        f'（带宽 {band:g}）——底图和线撞车')
    return errs


def _artifact_short_segment_errors(geom, node_grid):
    """每段至少一格粗格：更短就是"微残段"，转角挤在箭头上（D-40）。"""
    # 每段至少一格粗格：更短就是"微残段"——转角挤在箭头上（箭头本身约 9px），看着像没画完（D-40）。
    errs = []
    for i, e in enumerate(geom['edges'], 1):
        for p, q in zip(e['pts'], e['pts'][1:]):
            if abs(q[0] - p[0]) < node_grid - 0.6 and abs(q[1] - p[1]) < node_grid - 0.6:
                errs.append(f'边{i}({e["from"]}→{e["to"]}) 有一段只有 '
                            f'{max(abs(q[0] - p[0]), abs(q[1] - p[1])):g}px'
                            f'（短于一格粗格 {node_grid}px）：转角挤在箭头上')
                break
    return errs


def _artifact_lane_errors(geom):
    """泳道底色**必须存在**，且必须盖住所有节点：没盖住就是"底图没铺满"（D-41）。"""
    # 泳道底色必须**盖住所有节点**（与具体产物无关的判据）：底色比节点列平移一个走廊宽、末列
    # 没铺到画布右沿这类"底图没铺满"，一量就露（D-41）。
    lb = geom.get('lanes')
    if not lb:
        return ['产物里没有泳道底色盒（lanes）：泳道底图没画']
    errs = []
    for nid, v in sorted(geom['nodes'].items()):
        x, y, w, h = v['rect']
        if x < lb[0] - 0.6 or y < lb[1] - 0.6 or x + w > lb[2] + 0.6 or y + h > lb[3] + 0.6:
            errs.append(f'节点 {nid} 在泳道底色之外（底色 x {lb[0]:g}..{lb[2]:g}、'
                        f'y {lb[1]:g}..{lb[3]:g}）：底图没铺满')
            break
    return errs


def check_artifact(geom, lattice=10, node_grid=20, expect_lanes=None):
    """对**产物里真实写下的坐标**跑一遍几何门禁 → 错误列表（空 = 逐项通过）。

    与 `check(L)` 互补的一双眼睛：`check(L)` 读 `flow.yaml` 并**现算**折线，与渲染器共用同一个
    router——router 若把线接歪，两边一起错、一起"通过"。这里只认产物里那一串数字：接没接上
    节点、有没有穿框、有没有离格，一律以它为准（见 DECISIONS.md D-32）。

    `expect_lanes` 是"这份产物该不该有泳道底图"，语义见 `_artifact_lane_expected`：
    `True`/`False` = 调用方拍板（`build` 从 yaml 传），`None` = 按产物自称判。
    两个方向都会报错：该有而没有（底图没画）／不该有却画了（渲染器把布局判错了）。
    """
    if not geom.get('nodes'):
        return ['产物里解析不出任何节点：文件损坏，或渲染器没按约定输出几何']
    L = _ArtifactL(geom, lattice, node_grid)
    rects = {nid: v['rect'] for nid, v in geom['nodes'].items()}
    errs = []
    for fn in ARTIFACT_CHECKS:
        errs += fn(L, rects)
    if _artifact_lane_expected(geom, expect_lanes):
        errs += _artifact_band_errors(geom)
        errs += _artifact_lane_errors(geom)
    elif geom.get('lanes') is not None or geom.get('band'):
        errs.append('底稿是流程布局（不该有泳道底图），产物里却画了里程碑带/底色盒：'
                    '渲染器把布局判错了')
    errs += _artifact_short_segment_errors(geom, node_grid)
    return errs


def _side_ports(x, y, w, h):
    """可接端点：四条边的中点。菱形/椭圆的上下左右顶点与矩形边中点重合，故共用一套。"""
    return {'left': (x, y + h / 2), 'right': (x + w, y + h / 2),
            'top': (x + w / 2, y), 'bottom': (x + w / 2, y + h)}


def geometry_table(geom, source=''):
    """几何表：节点（中心 / 尺寸 / 形状 / 可接端点）+ 边（起点 / 终点 / 端口比例 / 折线）。

    用户要的那份"数据列表"——同一份数据既是自检的输入，也可以 `--dump` 出来给人核对。
    边的起点/终点不是另算的：它们就是**产物里写下的端口比例**（`exitX/exitY`、`entryX/entryY`）
    按节点矩形反算出来的，所以 `exit`/`entry` 一并列出——排查"线为什么接歪"时先看这两个数。
    """
    def r(v):
        return round(v, 2)

    nodes = {}
    for nid, v in sorted(geom['nodes'].items()):
        x, y, w, h = v['rect']
        nodes[nid] = {'shape': v['shape'], 'rect': [r(x), r(y), r(w), r(h)],
                      'center': [r(x + w / 2), r(y + h / 2)], 'size': [r(w), r(h)],
                      'ports': {s: [r(p[0]), r(p[1])] for s, p in _side_ports(x, y, w, h).items()}}
    edges = []
    for i, e in enumerate(geom['edges'], 1):
        pts = e['pts']
        edges.append({'i': i, 'from': e['from'], 'to': e['to'],
                      'start': [r(pts[0][0]), r(pts[0][1])] if pts else None,
                      'end': [r(pts[-1][0]), r(pts[-1][1])] if pts else None,
                      'exit': [r(v) for v in e['exit']] if e.get('exit') else None,
                      'entry': [r(v) for v in e['entry']] if e.get('entry') else None,
                      'points': [[r(px), r(py)] for px, py in pts]})
    lanes = geom.get('lanes')
    return {'source': source, 'canvas': [round(v, 2) for v in geom['canvas']],
            'band': r(geom.get('band') or 0), 'lanes': [r(v) for v in lanes] if lanes else None,
            'nodes': nodes, 'edges': edges}


def _write_geometry_dump(geom, dump, name):
    """--dump：把几何表写成 JSON；写不出去返回 1，成功返回 None。"""
    # 目标目录不存在/不可写是**外部输入**的问题，不能让它以 traceback 收场（与顶层 CLI 的约定一致）
    try:
        Path(dump).write_text(json.dumps(geometry_table(geom, name), ensure_ascii=False, indent=1) + '\n',
                              encoding='utf-8')
    except OSError as e:
        print(f'✗ 几何表写不出去 {dump}：{e}')
        return 1
    print(f'✓ 几何表: {dump}')
    return None


def artifact_main(path, dump=None):
    """读产物 → 几何表 → 复核。`--artifact` 的入口。"""
    from manifest import artifact_geometry
    p = Path(path)
    if not p.exists():
        print(f'✗ 找不到 {p}')
        return 1
    geom = artifact_geometry(p)
    if dump and _write_geometry_dump(geom, dump, p.name):
        return 1
    errs = check_artifact(geom)
    print(f'产物: {p.name}  节点: {len(geom["nodes"])}  边: {len(geom["edges"])}  '
          f'画布: {geom["canvas"][0]:g}x{geom["canvas"][1]:g}')
    if errs:
        print(f'✗ 几何自检未过（{len(errs)} 项）：')
        for e in errs[:20]:
            print('  -', e)
        return 1
    print('✓ 真实坐标复核通过：端点接框 / 不穿节点 / 不重叠 / 网格对齐 / 画布内')
    return 0


# ---------------------------------------------------------------- 呈现层
def report(L, errs, notes=()):
    labeled = sum(1 for r in range(L.maxrow)
                  if any(e.get('kind') == 'spine' and e.get('label')
                         and abs(L.nodes[e['to']]['row'] - L.nodes[e['from']]['row']) == 1
                         and min(L.nodes[e['from']]['row'], L.nodes[e['to']]['row']) == r
                         for e in L.edges))
    print(f'节点: {len(L.dsl["nodes"])}  边: {len(L.edges)}  带标签边: '
          f'{sum(1 for e in L.edges if e.get("label"))}  满间距行间: {labeled}  画布: {L.width}x{round(L.height())}')
    if errs:
        print(f'✗ 未通过 ({len(errs)} 项):')
        for e in errs[:20]:
            print('  -', e)
        return 1
    if notes:
        print('· 网格吸附: ' + '；'.join(notes))
    print(OK_LINE)
    return 0


def structured(errs):
    """报错列表 → 结构化回执（D-55）：subject/fix 供 AI 修复循环直接消费。"""
    return findings_receipt(errs)


def _showcase_blocks(notes):
    """showcase 档门禁：网格吸附提示非零即阻断（D-55）；应阻断时返回 True。"""
    if not notes:
        return False
    print(f'✗ showcase 档要求零网格吸附提示（现有 {len(notes)} 条）——yaml 里有离格值，'
          f'应把 row/col/col_x 改回格上再交付（D-55）')
    return True


def main(path, quality='standard'):
    """供 build.py / sync.py 调用：加载 → 检查 → 打印 → 退出码。"""
    L = load(path)
    errs, notes = check(L)
    if quality == 'showcase' and not errs and _showcase_blocks(notes):
        return 1
    return report(L, errs, notes)


def _cli_parser():
    """cli 的 argparse 定义（模型侧门禁 / 产物几何自检）。"""
    ap = argparse.ArgumentParser(description='flow.yaml 质量门禁（八项几何检查）/ 产物几何自检')
    ap.add_argument('path', help='flow.yaml 路径；加 --artifact 时改为产物（.drawio/.html）路径')
    ap.add_argument('--artifact', action='store_true',
                    help='把参数当渲染产物，按其中**真实坐标**复核（不重跑 router）')
    ap.add_argument('--dump', metavar='out.json', help='把反解出的几何表写成 JSON（配合 --artifact）')
    ap.add_argument('--json', action='store_true',
                    help='以 JSON 透出结构化结果（message/subject/fix，见 D-55）')
    ap.add_argument('--quality', choices=['standard', 'showcase'], default='standard',
                    help='showcase：零网格吸附提示才放行（D-55）')
    return ap


def _cli_json(p):
    """--json：结构化结果（message/subject/fix，见 D-55）→ 退出码。"""
    L = load(str(p))
    errs, notes = check(L)
    print(json.dumps({'errors': structured(errs), 'notes': list(notes)},
                     ensure_ascii=False, indent=1))
    return 1 if errs else 0


def cli(argv=None):
    """命令行入口。**必须显式给路径**——缺参数时绝不能退回校验某个样例并报"全部通过"，
    那等于引用错了目标却报成功，在自动化里就是假通过。"""
    a = _cli_parser().parse_args(argv)
    if a.artifact:
        return artifact_main(a.path, a.dump)
    p = Path(a.path)
    if not p.exists():
        print(f'✗ 找不到 {p}')
        return 1
    if a.json:
        return _cli_json(p)
    return main(str(p), quality=a.quality)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(cli())
