# -*- coding: utf-8 -*-
"""label.py — 边标签层：沿折线弧长选位置，徽章居中压线且不压节点。

优先弧长中点；压到节点就向两侧滑动取最近的不压节点的比例；全压则回退中点（由 validate 报出）。
网格：徽章盒宽高向上吸 2×细格；落点只吸所在线段的"自由轴"，被约束的那一轴保持线位不动。
"""
from geometry import RectCache, ceil_to, snap
from semantics import text_width


class Labeler(RectCache):
    def __init__(self, router, cfg, grid=None):
        self.router = router
        self.M = router.M
        self.cfg = cfg
        self.grid = grid if grid is not None else router.grid

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
        """徽章盒（左上角 x,y,w,h）：沿折线取第一个不压节点的候选比例，全压则回退中点。"""
        pts = self.router.path(e)
        w = self._badge_w(e)
        h = self._badge_h()
        rects = self._node_rects()
        for t in self._candidate_ts():
            bx, by = self._box_at(pts, t, w, h)   # 命中判定用吸附后的盒，避免吸附后再压节点
            if not self._hits(bx, by, w, h, rects):
                return bx, by, w, h
        bx, by = self._box_at(pts, 0.5, w, h)
        return bx, by, w, h
