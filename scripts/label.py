# -*- coding: utf-8 -*-
"""label.py — 边标签层：沿折线弧长选位置，徽章居中压线且不压节点。

优先弧长中点；压到节点就向两侧滑动取最近的不压节点的比例；全压则回退中点（由 validate 报出）。
网格：徽章盒宽高向上吸 2×细格；落点只吸所在线段的"自由轴"，被约束的那一轴保持线位不动。

**徽章跟线走**（G85/D-153）：落在**竖段**上时文字转 90°、盒子宽高互换——这样长跳的标签是"竖着写在
竖线上"，而不是横着压一条竖线（`visual-spec` §1）。只在**该段容得下转过来的徽章**时才转：
否则盒子会探出拐角、压到相邻节点，而"不压节点"是硬判据。
"""
from geometry import RectCache, ceil_to, snap
from semantics import text_width


class Labeler(RectCache):
    def __init__(self, router, cfg, grid=None):
        self.router = router
        self.M = router.M
        self.cfg = cfg
        self.grid = grid if grid is not None else router.grid
        self._orient = {}          # id(边) → 是不是竖排（`label_box` 选位时定下来，渲染器照它画）

    # ---------- 节点矩形（懒加载，缓存本体在 geometry.RectCache） ----------
    def _node_rects(self):
        """徽章命中判定只要矩形列表（不带节点 id）。"""
        return [r for _nid, r in self._all_rects()]

    # ---------- 弧长参数化 ----------
    @staticmethod
    def _point_at(pts, t):
        """按弧长比例 t∈[0,1] 取折线上的点，并返回所在线段下标。"""
        segs = [((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
                for i in range(len(pts) - 1)]
        total = sum(segs)
        if total == 0:
            return pts[0][0], pts[0][1], 0
        rem = total * t
        for i, l in enumerate(segs):
            if rem <= l:
                k = rem / l if l else 0
                return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k,
                        pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k, i)
            rem -= l
        return pts[-1][0], pts[-1][1], len(segs) - 1

    def _badge_w(self, e):
        b = self.cfg.get('label_badge', {})
        return ceil_to(text_width(e['label'], b.get('full_width', 12), b.get('half_width', 7))
                       + b['padding'], 2 * self.grid.lattice)

    def _badge_h(self):
        b = self.cfg.get('label_badge', {})
        return ceil_to(b.get('height', 20), 2 * self.grid.lattice)

    def _size(self, e, vert):
        """徽章盒的 (宽, 高)：竖排时宽高互换（文字转了 90°，沿线的"长"变成盒子的高）。"""
        w, h = self._badge_w(e), self._badge_h()
        return (h, w) if vert else (w, h)

    def _vert_at(self, pts, t, e):
        """弧长比例 t 处的徽章要不要竖排：所在段是**竖段**，且段长容得下转过来的徽章。

        为什么要求段长 ≥ 转过来的高（= 原徽章宽）：竖排盒子的中心在中点上，盒子沿 y 探出
        `宽/2 + padding`。段不够长时盒子会越过拐角压到相邻节点，而"不压节点"是硬判据
        （`check_labels`）——所以宁可横排，横排是这套几何一直以来的行为。
        """
        x, y, i = self._point_at(pts, t)
        a, b = pts[i], pts[min(i + 1, len(pts) - 1)]
        if abs(a[0] - b[0]) > 0.5:                 # 横段（自由轴是 x）→ 横排
            return False
        if abs(a[1] - b[1]) <= 0.5:                # 退化零长段
            return False
        return abs(b[1] - a[1]) >= self._badge_w(e)

    def _box_at(self, pts, t, w, h):
        """取弧长比例 t 处的徽章盒（左上角 x,y,w,h），并沿自由轴吸到细格。"""
        GL = self.grid.lattice
        x, y, i = self._point_at(pts, t)
        a, b = pts[i], pts[min(i + 1, len(pts) - 1)]
        if abs(a[1] - b[1]) <= 0.5:            # 水平段：x 自由，y 必须压线
            x = snap(x, GL)
        elif abs(a[0] - b[0]) <= 0.5:          # 垂直段：y 自由，x 必须压线
            y = snap(y, GL)
        else:                                  # 斜段（罕见）：两轴都吸
            x, y = snap(x, GL), snap(y, GL)
        return x - w / 2, y - h / 2

    @staticmethod
    def _hits(bx, by, bw, bh, rects, m=2):
        for (rx, ry, rw, rh) in rects:
            if bx < rx + rw + m and bx + bw > rx - m and by < ry + rh + m and by + bh > ry - m:
                return True
        return False

    @staticmethod
    def _candidate_ts(n=12):
        """候选弧长比例：中点优先，之后向两侧交替扩散。"""
        cand = [0.5]
        for i in range(1, n):
            cand.append(0.5 + i / (2 * n))
            cand.append(0.5 - i / (2 * n))
        return cand

    def label_box(self, e):
        """徽章盒（左上角 x,y,w,h）：沿折线取第一个不压节点的候选比例，全压则回退中点。

        竖排/横排**在这个循环里一起定**：每个候选位置知道自己落在哪一段上，取向跟着那段走
        （见 `_vert_at`）——取向定完再算盒、再判"压不压节点"，判据用的就是最终那个盒。
        """
        pts = self.router.path(e)
        rects = self._node_rects()
        for t in self._candidate_ts():
            vert = self._vert_at(pts, t, e)
            w, h = self._size(e, vert)
            bx, by = self._box_at(pts, t, w, h)   # 命中判定用吸附后的盒，避免吸附后再压节点
            if not self._hits(bx, by, w, h, rects):
                self._orient[id(e)] = vert
                return bx, by, w, h
        vert = self._vert_at(pts, 0.5, e)
        w, h = self._size(e, vert)
        bx, by = self._box_at(pts, 0.5, w, h)
        self._orient[id(e)] = vert
        return bx, by, w, h

    def label_vertical(self, e):
        """这条边的徽章是不是跟竖线竖排（渲染器照它决定转不转文字）。没算过就先算一次盒。"""
        if id(e) not in self._orient:
            self.label_box(e)
        return bool(self._orient.get(id(e)))
