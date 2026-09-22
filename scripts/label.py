# -*- coding: utf-8 -*-
"""label.py — 边标签层：沿折线弧长选位置，徽章居中压线且不压节点。

优先弧长中点；压到节点就向两侧滑动取最近的不压节点的比例；全压则回退中点（由 validate 报出）。
网格：徽章盒宽高向上吸 2×细格；落点只吸所在线段的"自由轴"，被约束的那一轴保持线位不动。

**标签一律横排**；一行放不下时**折两排**（G85/D-153）：判据是"一行的宽度超不超过**通道档距**"——
横排徽章骑在竖线上，比档距还宽就会压到相邻通道的线（作者原话"阻挡线条"）。折排把宽度减半，
而不是把字转 90°：竖排试过，作者 2026-09-22 改口径为横排 + 折排。
"""
from geometry import RectCache, ceil_to, lane_step, snap
from semantics import text_width


class Labeler(RectCache):
    def __init__(self, router, cfg, grid=None):
        self.router = router
        self.M = router.M
        self.cfg = cfg
        self.grid = grid if grid is not None else router.grid
        self._rows = {}            # id(边) → 徽章的文字行（`label_box` 选位时定下来，渲染器照它画）

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

    # ---------- 徽章尺寸 ----------
    def _padding(self):
        return self.cfg.get('label_badge', {})['padding']

    def _text_w(self, text):
        b = self.cfg.get('label_badge', {})
        return text_width(text, b.get('full_width', 12), b.get('half_width', 7))

    def _badge_w(self, text):
        """一行文字时的徽章宽（向上吸 2×细格）。"""
        return ceil_to(self._text_w(text) + self._padding(), 2 * self.grid.lattice)

    def _badge_h(self, rows=1):
        b = self.cfg.get('label_badge', {})
        return ceil_to(b.get('height', 20), 2 * self.grid.lattice) * rows

    def _pitch(self):
        """竖线左右能给标签让出的横向预算 = **本图实际的通道档距**。

        为什么是它：平行通道之间的实际间距就是这个数。横排徽章比它还宽就会压到相邻通道的线，
        那正是"阻挡线条"的判据；比它窄就谁也压不着。取值口径与路由器**同一处**：字典 + 本图
        `layout` 覆盖——档距本身是按**这张图最宽的标签**派生出来的
        （`table_to_dsl._derive_channel_step`），所以标签与通道永远算的是同一个数。
        """
        lay = dict(self.cfg.get('layout') or {})
        lay.update(self.M.dsl.get('layout') or {})
        return lane_step(lay, self.grid.lattice)

    def _rows_for(self, text, seg):
        """这条边的标签排成哪几行：默认一行；**竖段上**且一行宽度超档距 ⇒ 折两排。

        只折两排（作者口径）。折法按字宽累计到一半处断开——不引入第二套排版规则。
        横段不折：徽章顺着线躺，横向预算管不着它。
        """
        if self._badge_w(text) <= self._pitch():
            return [text]
        a, b = seg
        if abs(a[0] - b[0]) > 0.5 or len(text) < 2:
            return [text]
        half, acc, cut = self._text_w(text) / 2, 0.0, 1
        for i, ch in enumerate(text, 1):
            acc += self._text_w(ch)
            if acc >= half:
                cut = i
                break
        cut = min(max(cut, 1), len(text) - 1)          # 两行都非空
        return [text[:cut], text[cut:]]

    def _size(self, rows):
        """徽章盒的 (宽, 高)：宽取最长那一行，高 = 行数 × 行高。"""
        return ceil_to(max(self._text_w(t) for t in rows) + self._padding(),
                       2 * self.grid.lattice), self._badge_h(len(rows))

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

        排几行**在这个循环里一起定**：每个候选位置知道自己落在哪一段上，折排只看那一段
        （见 `_rows_for`）——折完再算盒、再判"压不压节点"，判据用的就是最终那个盒。
        """
        pts = self.router.path(e)
        rects = self._node_rects()
        for t in self._candidate_ts():
            rows = self._rows_for(e['label'], self._seg_at(pts, t))
            w, h = self._size(rows)
            bx, by = self._box_at(pts, t, w, h)   # 命中判定用吸附后的盒，避免吸附后再压节点
            if not self._hits(bx, by, w, h, rects):
                self._rows[id(e)] = rows
                return bx, by, w, h
        rows = self._rows_for(e['label'], self._seg_at(pts, 0.5))
        w, h = self._size(rows)
        bx, by = self._box_at(pts, 0.5, w, h)
        self._rows[id(e)] = rows
        return bx, by, w, h

    def _seg_at(self, pts, t):
        """弧长比例 t 落在哪一段上 → `(a, b)` 两个端点。"""
        _x, _y, i = self._point_at(pts, t)
        return pts[i], pts[min(i + 1, len(pts) - 1)]

    def invalidate(self):
        """缓存全清：整流平（`head_band`）之后，**行数**和矩形一样会失效。

        为什么要在这里明说（G92）：`_rows` 以 `id(边)` 为键，而基类的 `invalidate()` 只清 `_rects`
        ——"先 `label_box`、再 `head_band`、再 `label_rows`"这条顺序会拿到**平移前**定下的行数，
        且不报错（当前三个渲染器都是"先 box 后 rows"，所以是潜伏）。缓存有几个就清几个，
        别指望调用点的顺序永远不变。
        """
        super().invalidate()
        self._rows.clear()

    def label_rows(self, e):
        """这条边的徽章分几行、每行是什么（渲染器照它画）。没算过就先算一次盒。

        **无标签边自己挡**：调用点现在都有 `e.get('label')` 守卫，但方法不该依赖调用点自证——
        没标签就返回空表，渲染器一行 `<text>` 都不画。
        """
        if not e.get('label'):
            return []
        if id(e) not in self._rows:
            self.label_box(e)
        return self._rows.get(id(e)) or [e['label']]
