# -*- coding: utf-8 -*-
"""geometry.py — 布局/几何层：网格规范、画布参数、动态行距、节点矩形与锚点；只回答"画在哪"。

**所有坐标的唯一出口**：构造时统一 snap，下游一律不自行取整，这样「离格」不可能从任何代码路径漏出去。
网格规范（细格 10 / 粗格 20）见 references/visual-spec.md。
"""
import math

RECT_SHAPES = ('rounded', 'stadium')   # 矩形类：取粗格、尺寸 40/20 的倍数（见 dictionary shapes）


def arc_px(shp, w, h):
    """圆角半径（像素）：字典 `shapes.*.arc` 是 **drawio 口径的 `arcSize` 百分比**（见 D-86）。

    drawio 的 `arcSize` 是"占**短边**的百分比"（`arcSize=6` + 160×60 ⇒ 半径 3.6px），
    html/svg 里却按**像素**直接写进 `rx`（同一个 6 变成 6px）——同一形状三份产物圆角不同。
    以 drawio 为准：两处 html/svg 都走这个函数换算，drawio 那边原样写 `arcSize`（它就是标准）。

    胶囊（`stadium`）不走这里：它的圆角是**半圆**（drawio 那边写死 `arcSize=50`），
    按定义就是 `h/2`，与本函数无关。
    """
    pct = shp.get('arc')
    if not pct:
        return 0.0
    return round(min(w, h) * float(pct) / 100.0, 3)
DEFAULT_GRID = {'lattice': 10, 'node': 20}   # 与 dictionary.yaml 的 grid 段保持一致
DEFAULT_COL_X = 400        # 未声明 layout.col_x 时的首列中心 x（后续列按 layout.col_pitch 展开）
CANVAS_BOTTOM_MARGIN = 50  # 画布高度在最后一行之下保留的余量


def snap(v, unit):
    """就近吸附到 unit 的倍数（.5 一律进位，避免 Python 银行家舍入造成来回抖动）。"""
    return math.floor(v / unit + 0.5) * unit


def ceil_to(v, unit):
    """向上吸附到 unit 的倍数（宁可大不可小，避免越吸附越挤）。"""
    return math.ceil(v / unit - 1e-9) * unit


def _fit_one(v, residue, cycle):
    """吸附到「≡ residue (mod cycle)」且 ≥ v 的最小值。"""
    k = max(0, math.ceil((v - residue) / cycle - 1e-9))
    return residue + cycle * k


def fit_size(w, h, mid_res, col_res, rect_like, unit=20):
    """把形状尺寸吸附到"四边都落格"的合法值，返回 (w, h, 是否改动)；cycle 由调用方给。"""
    cycle = 2 * unit if rect_like else unit
    mw = (2 * (-col_res)) % cycle
    mh = (2 * mid_res) % cycle
    nw = _fit_one(w, mw, cycle)
    nh = _fit_one(h, mh, cycle)
    return nw, nh, (nw != round(w) or nh != round(h))


def fit_base_height(v):
    """行基线高吸附到 20 mod 40 → 中线落在 20k+10 上。"""
    return 20 + 40 * round((v - 20) / 40)


class RectCache:
    """节点矩形懒缓存：`(节点id, rect)` 列表，首次访问时填充；使用者提供 `self.grid` 与 `self.M`。

    **栅格几何变了就必须调 `invalidate()`**（DECISIONS.md D-19）：切标题带会把整图 y 整体平移，
    不清缓存的话，避让判定拿新坐标的候选去撞旧坐标的矩形，判定全数失准却不报错。
    `Router` / `LaneRouter` / `Labeler` 共用本类（三处各抄一份迟早改散）。
    """

    def _all_rects(self):
        if getattr(self, '_rects', None) is None:
            self._rects = [(nid, self.grid.rect(nid)) for nid in self.M.nodes]
        return self._rects

    def invalidate(self):
        self._rects = None


class Grid:
    def __init__(self, model):
        """建流程栅格：读网格与画布配置 → 解列中心 → 解原点与行距 → 吸附尺寸 → 定右通道 → 推行 y。"""
        self.M = model
        self._read_base_config(model)
        self._solve_columns(model)
        self._solve_origin_and_gaps(model)
        self._fit_sizes(model)
        self._solve_right_channel(model)
        self._solve_rows(model)

    def _read_base_config(self, model):
        """读网格刻度与画布宽（未声明则走字典默认），建出最基础的字段与自检提示载体。"""
        dsl = model.dsl
        lay = dsl.get('layout') or {}
        gcfg = model.cfg.get('grid') or {}
        canvas = model.cfg.get('canvas') or {}
        self.lattice = int(gcfg.get('lattice', DEFAULT_GRID['lattice']))
        self.node_grid = int(gcfg.get('node', DEFAULT_GRID['node']))
        GN = self.node_grid
        self.notes = []

        self.width = ceil_to(lay.get('width', canvas.get('width', 1180)), GN)
        # 画布左留白（`table_to_dsl` 量完内容后写进来的派生量）：**加在每一列上**，
        # 于是"内容居中"只靠平移就能实现，而 `col_x` 仍是它自己的意思（列间距的家在字典，D-29）。
        self.origin_x = snap(lay.get('origin_x', 0), GN)

    def _solve_columns(self, model):
        """定各列中心 x（声明 col_x 则照用、否则按 col_pitch 展开）并记录吸附提示。"""
        dsl = model.dsl
        lay = dsl.get('layout') or {}
        c = model.cfg.get('layout') or {}
        GN = self.node_grid
        ncols = max((n['col'] for n in model.nodes.values()), default=0) + 1
        # 未声明 col_x 时的列间距走字典 layout.col_pitch（D-29）：手写多列 yaml 不必逐列算中心
        col_pitch = snap(c.get('col_pitch', 460), GN)
        raw_col = list(lay.get('col_x')) if lay.get('col_x') else [DEFAULT_COL_X + col_pitch * i for i in range(ncols)]
        self.col_x = [snap(x, GN) + self.origin_x for x in raw_col]
        # 提示只报**吸附**造成的位移：`origin_x` 是成心的平移，报成"被吸附"会变成一条假软提示
        # （`--quality showcase` 会把软提示当阻断，那就更冤了）。
        for i, a in enumerate(raw_col):
            b = snap(a, GN)
            if abs(a - b) > 1e-6:
                self.notes.append(f'列中心 col_x[{i}] {a:g} → {b:g}')

    def _solve_origin_and_gaps(self, model):
        """定原点 y、标题带高与满/缩两档行间距（全部吸附）。"""
        dsl = model.dsl
        lay = dsl.get('layout') or {}
        c = model.cfg.get('layout') or {}
        GL, GN = self.lattice, self.node_grid
        self._raw_oy = lay.get('origin_y', c.get('origin_y', 80))
        self._band_cfg = c['legend_band']
        # 画布顶部**预留**一条说明区、首行整体下推一个带高：标题画在带内，结构上不可能与节点重叠。
        self.legend_h = snap(self._band_cfg, GL)
        self.origin_y = snap(self._raw_oy + self.legend_h, GN)
        raw_fg = lay.get('full_gap', c.get('full_gap', 140))
        raw_sg = lay.get('shrink_gap', c.get('shrink_gap', 100))
        self.full_gap = snap(raw_fg, GL)
        self.shrink_gap = snap(raw_sg, GL)

    def _fit_sizes(self, model):
        """先算中线/列心余数，再把每个形状的宽高吸附到「四边都落格」的合法值。"""
        GN = self.node_grid
        c = model.cfg.get('layout') or {}
        raw_base = c.get('row_base_height', 60)
        self.base_h = fit_base_height(raw_base)
        mid_res = int(round(self.base_h / 2)) % GN      # 中线 mod 粗格
        col_res = int(round(self.col_x[0])) % GN if self.col_x else 0

        shapes = model.cfg.get('shapes') or {}
        self.sizes = {}
        for t, (w, h) in model.sizes.items():
            rect_like = shapes.get(t, {}).get('shape') in RECT_SHAPES
            nw, nh, moved = fit_size(w, h, mid_res, col_res, rect_like, GN)
            self.sizes[t] = (nw, nh)
            if moved:
                self.notes.append(f'形状 {t} {w:g}×{h:g} → {nw}×{nh}'
                                  f'（{"矩形类守粗格" if rect_like else "非矩形守细格"}）')

    def _solve_right_channel(self, model):
        """定右通道 x：声明则照用，否则取最右列中心 + 右通道偏移。"""
        dsl = model.dsl
        lay = dsl.get('layout') or {}
        c = model.cfg.get('layout') or {}
        GL = self.lattice
        raw_rg = lay.get('right_channel',
                         max(self.col_x) + c.get('right_channel_offset', 40))
        self.RG = snap(raw_rg, GL)

    def _solve_rows(self, model):
        """推行顶边 y 与满间距行集合：相邻行主干带标签则走满间距。"""
        GN = self.node_grid
        self.maxrow = max((n['row'] for n in model.nodes.values()), default=0)
        # 动态行距：相邻行主干(spine)带标签 → 满间距
        labeled = set()
        for e in model.edges:
            if e.get('kind') == 'spine' and e.get('label'):
                a = model.nodes[e['from']]['row']
                b = model.nodes[e['to']]['row']
                if abs(b - a) == 1:
                    labeled.add(min(a, b))
        ys = [self.origin_y]
        for r in range(self.maxrow):
            ys.append(ys[r] + (self.full_gap if r in labeled else self.shrink_gap))
        self.rowy = ys
        self._labeled = labeled

    def _build_rows(self):
        """按 origin_y 与逐行间距重算各行顶边 y（切换标题带后调用）。"""
        ys = [self.origin_y]
        for r in range(self.maxrow):
            ys.append(ys[r] + (self.full_gap if r in self._labeled else self.shrink_gap))
        self.rowy = ys

    def set_head_band(self, on=True):
        """开关画布顶部的标题带（HTML 版标题在画布外故不预留，drawio 版留在画布内）。

        两种版式只差一个顶部偏移量，节点相对位置完全一致。调用后画布高会变。
        """
        self.legend_h = snap(self._band_cfg, self.lattice) if on else 0
        self.origin_y = snap(self._raw_oy + self.legend_h, self.node_grid)
        self._build_rows()

    def Y(self, r):
        return self.rowy[r]

    def MID(self, r):
        """行中线（所有节点共用一条，落在 20k+10 上——网格规范见 visual-spec §0）。"""
        return self.rowy[r] + self.base_h / 2

    def height(self):
        return ceil_to(self.MID(self.maxrow) + self.base_h / 2 + CANVAS_BOTTOM_MARGIN, self.lattice)

    def legend_rect(self):
        """图例带：画布顶部 (0, 0, width, legend_h)，legend_h=0 表示关闭。

        预留空带——origin_y 已按它下推，所以带内不可能出现节点、折点或标签。"""
        return (0, 0, self.width, self.legend_h)

    def rect(self, nid):
        n = self.M.nodes[nid]
        w, h = self.sizes[n['type']]
        return (self.col_x[n['col']] - w / 2, self.MID(n['row']) - h / 2, w, h)

    def anchor(self, nid, side, off=0):
        """端口锚点。`off` 是**沿这条边的切向**错位量（见 DECISIONS.md D-15/D-17）：
        左右边竖着挪 y、上下边横着挪 x，用来把共用同一端口的进出边岔开。
        **不是** y 方向的偏移量——上下边若按 y 挪，锚点会被挪进节点内部。

        **非矩形节点（菱形/椭圆）要把错位投影回真实边界**：它们内接于外接矩形，只有边中点
        与矩形重合，沿边挪开就离开形状、箭头悬空（D-31 实测悬空 8.9~27.5px）。投影后仍吸细格
        （菱形在 160×80 上正好落格；椭圆最多差半格，肉眼不可辨）。
        """
        x, y, w, h = self.rect(nid)
        off = snap(off, self.lattice)        # 沿边错位量也必须落在细格上
        cx, cy, hw, hh = x + w / 2, y + h / 2, w / 2, h / 2
        shp = (self.M.cfg.get('shapes') or {}).get(self.M.nodes[nid]['type'], {}).get('shape')
        nonrect = shp in ('rhombus', 'ellipse') and off
        if side in ('left', 'right'):
            px = x if side == 'left' else x + w
            py = cy + off
            if nonrect and hh:
                t = min(abs(off) / hh, 0.999)                    # 沿边走了多远（1=走到中心）
                k = (1 - t) if shp == 'rhombus' else (1 - t * t) ** 0.5
                px = (cx - hw * k) if side == 'left' else (cx + hw * k)
        else:
            px = cx + off
            py = y if side == 'top' else y + h
            if nonrect and hw:
                t = min(abs(off) / hw, 0.999)
                k = (1 - t) if shp == 'rhombus' else (1 - t * t) ** 0.5
                py = (cy - hh * k) if side == 'top' else (cy + hh * k)
        return snap(px, self.lattice), snap(py, self.lattice)

    def port_frac(self, nid, side, off=0):
        """端口的 (fractionX, fractionY)——drawio 用**外接矩形的比例**表示端口位置。

        必须由 anchor() 反算，不能按"0.5 + off/边长"另算一份：非矩形节点投影后比例变了，
        两边各算各的就会出现"我们算在斜边上、drawio 画在矩形边上"的偏差（D-31）。
        """
        x, y, w, h = self.rect(nid)
        ax, ay = self.anchor(nid, side, off)
        return (round((ax - x) / w, 4) if w else 0.5, round((ay - y) / h, 4) if h else 0.5)


def _group_outs_by_side(outs, ports):
    """把一组出边按**出边所在的侧**分组 → `{侧: [出边, …]}`。

    同一侧的多条出边共用同一锚点坐标，首段会共线叠成一条
    （实测 16 的两条出边 16→16a / 16→17 都从 bottom 口出去，首段都落在 x=820，
    于是 16→16a 的合法 Z 形候选全被"共线重叠"罚掉，只能退化成贴边的坏形状）。
    """
    by_side = {}
    for oe in outs:
        by_side.setdefault(ports(oe)[0], []).append(oe)
    return by_side


def _place_offset(grid, ports, nid, ex, oe, taken, step, touched, avoid):
    """给一条出边挑一个不被占用的错峰量写进 `sdye`，并登记到 `taken` / `touched`。

    `taken` 是本侧**已被任何边**占用的槽位（含入边锚点与先排的出边），`avoid` 只含**入边锚点**：
    两趟挑选——先要一个谁都没占的槽位；本侧同类边多到槽位用尽时（一档 2×细格 + 侧中线最多两个），
    退到「只要不压在入边锚点上」。**压在入边锚点上就是掉头折返**（硬错误，线压过箭头）；
    出边之间共用槽位是分叉，`validate` 本就豁免共线——两层代价谁高谁低是明确的。
    第二趟只在侧中线被入边占住时才做：那时第一趟失败的边锚点必然落回中线 = 入边锚点。
    """
    sx, sy = grid.anchor(nid, ex)
    tx, ty = grid.anchor(oe['to'], ports(oe)[1])
    # 符号先取"切向朝目标锚点"；两个锚点在切向上**等高/等 x** 时（同行的左右端口、
    # 同列的上下面口都是这种），改按**行进方向**定向。
    # 这不是凑数：一去一回的两条反向平行边各自独立算符号，平局时会同取一侧，
    # 两条出线段落在同一 y（或同一 x）上必然共线重叠 → 形状合法的候选全被"重叠"
    # 罚掉，只能退化成穿自身端点的坏形状（实测泳道同行 02⇄01）。按行进方向定向，
    # 一去一回自动各占走廊一侧（DECISIONS.md D-34）。
    # 上限 = 半边长 - 细格：锚点得留在节点边沿内，且离角上至少一格
    if ex in ('left', 'right'):
        s = 1 if ty > sy else (-1 if ty < sy else (1 if tx > sx else -1))
        lim = grid.rect(nid)[3] / 2 - grid.lattice
    else:
        s = 1 if tx > sx else (-1 if tx < sx else (1 if ty > sy else -1))
        lim = grid.rect(nid)[2] / 2 - grid.lattice
    # 候选含 0：本侧多条出边时，第一条尽量留在中心（对既有产物改动最小）
    for cand in [0] + [s * k * step for k in range(1, 6)]:
        if abs(cand) <= lim and round(cand, 1) not in taken:
            oe['sdye'] = cand
            taken.add(round(cand, 1))
            touched.add(id(oe))
            return
    # 第一趟空手而归：槽位被本侧同类边占满。此时若不挪，锚点落回侧中线——只有中线被入边
    # 占住才叫掉头折返，所以仅在这一条件下退让：挪到本侧任一**不压入边锚点**的槽位。
    if 0 not in avoid:
        return
    for cand in [s * k * step for k in range(1, 6)]:
        if abs(cand) <= lim and round(cand, 1) not in avoid:
            oe['sdye'] = cand
            taken.add(round(cand, 1))
            touched.add(id(oe))
            break


def _first_leg(grid, nid, ex, oe):
    """一条出边的**首段长度**：锚点 → 通道折点的那一段（没有折点则 0）。

    用于 `stagger_source_anchors` 的组内排序（见 D-89）：同侧多条出边里，**首段最长的那条
    留在侧中线**，短的让到外侧。反过来（先到先得）会让短的那条横段横穿长的竖段——实测
    `09a→09c`（首段 150）与 `09a→09d`（首段 980）在 `x=410` 上交叉一次。
    """
    ax, ay = grid.anchor(nid, ex, oe.get('sdye') or 0)
    ch = next((oe[k] for k in ('gapx', 'gutter', 'channel') if oe.get(k) is not None), None)
    if ch is None:
        return 0.0
    return abs(ch - ax) if ex in ('left', 'right') else abs(ch - ay)


def stagger_source_anchors(model, grid, ports):
    """出边与入边用同一侧时，锚点会重合 → 出边首段把入边末段**原路画回来**（DECISIONS.md D-15）。

    validate 的「边不重叠」豁免了共享端点的边（分叉/合流本就该汇成一点），
    但**掉头折返**不是分叉——线会穿过节点边沿上的箭头，看起来像线穿过了框。
    修法：给出边一个 `sdye`，沿该侧挪开 2×细格，方向朝目标锚点那一侧。
    只在该侧确有入边占了中心时才挪；用户手填 `sdye` 不覆盖。
    流程版 `Router` 与泳道版 `LaneRouter` 共用（`ports` 传各自的端口解析函数）。

    **组内按首段长度从长到短处理**（D-89）：长的那条留在中心，短的让到外侧。
    泳道版在**构造期**就调这里（通道还没定案 ⇒ `_first_leg` 一律 0），排序退化成"原序"，
    即泳道侧的既有行为一字不变。

    非矩形节点（菱形/椭圆）同样适用：`anchor()` 会把错位投影回真实边界，不产生悬空（D-31）。

    返回**被设过 `sdye` 的边 id 集合**：布线器要能事后判断"这个偏移还有没有存在理由"——
    端口最后只有它一条边时，偏移在菱形/椭圆上只会把锚点从顶点推到斜边（D-31）。
    """
    step = 2 * grid.lattice
    touched = set()
    for nid in model.nodes:
        outs = [e for e in model.edges if e['from'] == nid]
        if not outs:
            continue
        ins = [e for e in model.edges if e['to'] == nid]
        by_side = _group_outs_by_side(outs, ports)
        for ex, group in by_side.items():
            avoid = {round(ie.get('dye', 0), 1) for ie in ins if ports(ie)[1] == ex}
            taken = set(avoid)
            if len(group) < 2 and 0 not in taken:
                continue                      # 本侧只有一条出边、中心又没人占 → 不用让
            auto = []
            for oe in group:
                if oe.get('sdye') is not None:
                    taken.add(round(oe['sdye'], 1))   # 手填优先，且占用该槽位
                else:
                    auto.append(oe)
            auto.sort(key=lambda oe: -_first_leg(grid, nid, ex, oe))
            for oe in auto:
                _place_offset(grid, ports, nid, ex, oe, taken, step, touched, avoid)
    return touched


# ----------------------------------------------------------------几何谓词
# 布线（router 主动避让）与质量门禁（validate 事后复检）必须用**同一套**判定，
# 否则"避开了"与"检出来"会给出不同答案。所以谓词只在这里实现一次。

def rects_overlap(a, b):
    """两个矩形是否相交（边贴边不算）。"""
    return (a[0] < b[0] + b[2] and a[0] + a[2] > b[0]
            and a[1] < b[1] + b[3] and a[1] + a[3] > b[1])


def seg_rect_hit(p1, p2, rect, grow=0.0):
    """线段与矩形是否相交。`grow>0` 外扩（留安全间隙）、`grow<0` 内缩（判"穿进内部"）。"""
    x, y, w, h = rect
    l, t, r, b = x - grow, y - grow, x + w + grow, y + h + grow
    if l >= r or t >= b:                      # 内缩到退化 → 内部为空，不可能相交
        return False
    (x1, y1), (x2, y2) = p1, p2
    if abs(x1 - x2) < 0.5:                    # 竖段：x 落在带内 + y 区间有重叠
        lo, hi = min(y1, y2), max(y1, y2)
        return l < x1 < r and not (hi < t or lo > b)
    if abs(y1 - y2) < 0.5:                    # 横段
        lo, hi = min(x1, x2), max(x1, x2)
        return t < y1 < b and not (hi < l or lo > r)
    return (min(x1, x2) < r and max(x1, x2) > l
            and min(y1, y2) < b and max(y1, y2) > t)


def seg_overlap(s1, s2, eps=1.0):
    """两条轴对齐线段是否**共线重叠**（只认重叠，不认正交穿越）。

    正交交叉是十字、读者分得清；共线重叠完全叠成一条、无从分辨——这是可读性的分界线。
    """
    (ax, ay), (bx, by) = s1
    (cx, cy), (dx, dy) = s2
    h1, v1 = abs(ay - by) <= eps, abs(ax - bx) <= eps
    h2, v2 = abs(cy - dy) <= eps, abs(cx - dx) <= eps
    if h1 and h2 and abs(ay - cy) <= eps:
        return min(ax, bx) < max(cx, dx) - eps and min(cx, dx) < max(ax, bx) - eps
    if v1 and v2 and abs(ax - cx) <= eps:
        return min(ay, by) < max(cy, dy) - eps and min(cy, dy) < max(ay, by) - eps
    return False


def ortho_cross(p1, p2, q1, q2, eps=0.6):
    """两条轴对齐线段是否**正交交叉**（一横一竖、且交点在两者内部）。

    端点相接（T 形/汇合）与共线重叠都不算——前者是正常汇流，后者由 `seg_overlap` 单独管。
    布线时用它数"候选线与已定案线交叉几次"，作为不穿节点之外的择优依据（D-30）。
    """
    pv, qv = abs(p1[0] - p2[0]) <= eps, abs(q1[0] - q2[0]) <= eps
    ph, qh = abs(p1[1] - p2[1]) <= eps, abs(q1[1] - q2[1]) <= eps
    if pv and qh:
        vx, (ylo, yhi) = p1[0], sorted((p1[1], p2[1]))
        hy, (xlo, xhi) = q1[1], sorted((q1[0], q2[0]))
    elif ph and qv:
        vx, (ylo, yhi) = q1[0], sorted((q1[1], q2[1]))
        hy, (xlo, xhi) = p1[1], sorted((p1[0], p2[0]))
    else:
        return False
    return xlo + eps < vx < xhi - eps and ylo + eps < hy < yhi - eps


def point_seg_dist(p, a, b):
    """点到线段的最短距离。"""
    ax, ay = a
    bx, by = b
    abx, aby = bx - ax, by - ay
    if abx == 0 and aby == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * abx + (p[1] - ay) * aby) / (abx * abx + aby * aby)
    t = max(0, min(1, t))
    return math.hypot(p[0] - (ax + t * abx), p[1] - (ay + t * aby))
