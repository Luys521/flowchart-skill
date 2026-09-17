# -*- coding: utf-8 -*-
"""swimlane.py — 泳道布局：行 = 项目运作阶段，列 = 执行主体（规则见 references/swimlane-spec.md）。

与 `geometry.Grid` 接口一致，`Engine` 按 `dsl.meta.layout` 二选一，所以下游都不必知道当前是哪种。
"""
from geometry import Grid, RECT_SHAPES, ceil_to, snap

CANVAS_BOTTOM_MARGIN = 40  # 泳道画布高度在最后一行之下保留的余量


def _align_half(v, unit):
    """向上取到「≡ unit/2 (mod unit·2)」的最小值（unit=20 → 20/60/100…）。

    为什么行高与格内间距都得是这个余数：节点四边要守粗格（20）⇒ 栈顶落 20 格 ⇒
    栈中线必落在 `20k+10` 上。而行中线 = rowy + row_h/2，要它也是 `20k+10`，
    就得 row_h ≡ 20 (mod 40)；要让**任意节点数**的摞都居中并落格，每个格子的
    stack_h 也必须 ≡ 20 (mod 40)。单节点格 stack_h = h 已是 20 mod 40，
    多节点格靠 gap ≡ 20 (mod 40) 维持——两者缺一，行内各列的中线就会差 10px。
    """
    return ceil_to(v - unit, 2 * unit) + unit


class SwimGrid:
    def __init__(self, model, route_left=0):
        """建泳道栅格：读配置 → 吸附尺寸 → 定行列预算 → 算列宽与坐标 → 铺行名/泳道名。"""
        self.M = model
        self._read_configs(model, route_left)
        self._fit_sizes(model)
        self._collect_cells(model)
        self._solve_col_widths(model)
        self._solve_row_heights()
        self._solve_col_positions()
        self._build_rows()
        self._assign_lane_names(model)

    # ---------------------------------------------------------------- 内部
    def _read_configs(self, model, route_left):
        """读网格刻度与泳道参数（`grid` 段 + 顶层 `lane:` 段），定下与尺寸无关的配置字段。"""
        dsl = model.dsl
        c = model.cfg.get('layout') or {}
        gcfg = model.cfg.get('grid') or {}
        self.lattice = int(gcfg.get('lattice', 10))
        self.node_grid = int(gcfg.get('node', 20))
        GL, GN = self.lattice, self.node_grid
        self.notes = []

        # 泳道参数的家在字典顶层 `lane:` 段（与 visual-spec 参数表的 `lane.*` 命名一致），
        # 不是 `layout.lane`——旧读取路径读不到字典，所有泳道参数一直走代码默认值。
        lane = model.cfg.get('lane') or c.get('lane') or {}
        # 左侧里程碑带之外的路由走廊。宽度由**引擎探布量出来**（D-39），这里只接值；
        # 字典 `lane.route_left` 是手调下限。量少只是留白不够、长跳退回列缝（交叉变多），
        # **压带不可能**——左族一律从带右沿起算。
        self.route_left = snap(max(int(lane.get('route_left', 0)), int(route_left or 0)), GL)
        self._band_cfg = c['legend_band']
        self.legend_h = snap(self._band_cfg, GL)
        self.head_h = snap(lane.get('head', 60), GN)        # 顶部「职能部门」带
        self.stage_w = snap(lane.get('stage', 120), GN)     # 左侧「里程碑阶段」带
        self.pad = snap(lane.get('pad', 60), GN)            # 每列左右各留这么多
        self.vpad = snap(lane.get('vpad', 40), GL)          # 每行上下各留这么多
        # 间距必须是 `20 + 40k`：见下方 _align_half 的说明，否则同格多节点与单节点
        # 摞出来的高度不同余，行内各列的中线就对不到一起（DECISIONS.md D-16）。
        raw_gap = snap(lane.get('gap', 60), GN)
        self.gap = _align_half(raw_gap, GN)
        if self.gap != raw_gap:
            self.notes.append(f'泳道间距 gap {raw_gap:g} → {self.gap:g}（半格对齐）')

        # 槽位模式（见 swimlane-spec §3.1）：流程表声明了「泳道列序」→ 行不再是阶段号，而是**槽位号**，
        # 层高严格等距 pitch。一个阶段因此可能横跨多行，左侧色带由渲染层按连续同阶段合并。
        # 没声明列序就退回原来的「阶段行」行为，老表一字不变。
        self.slot_mode = bool((model.meta or {}).get('lane_order'))
        self.pitch = snap(lane.get('pitch', 120), GN)

    def _fit_sizes(self, model):
        """把每个形状的宽高向上吸附到细格，并记录改动提示。"""
        GN = self.node_grid
        # 泳道不共用行中线，所以没有 h ≡ 20 (mod 40) 那条额外要求（见 swimlane-spec §3）。
        self.sizes = {}
        for t, (w, h) in model.sizes.items():
            nw, nh = ceil_to(w, GN), ceil_to(h, GN)
            self.sizes[t] = (nw, nh)
            if (nw, nh) != (round(w), round(h)):
                self.notes.append(f'形状 {t} {w:g}×{h:g} → {nw}×{nh}')

    def _collect_cells(self, model):
        """按 (行,列) 归集节点 id，并定出行数、列数与最大行号。"""
        self.cells = {}
        for n in model.nodes.values():
            self.cells.setdefault((n['row'], n['col']), []).append(n['id'])
        self.nrows = max((r for r, _ in self.cells), default=0) + 1
        # 列数取「节点占到的列」与「声明的泳道数」的较大者：只按节点算的话，**尾部空泳道**
        # （如列序里最后一个部门本流程不参与）会整列消失；中间的空列因为后面还有节点占着更大的
        # col 号，反而一直存在——同一件事只在一头出问题，最容易被漏掉。
        self.ncols = max(max((cc for _, cc in self.cells), default=0) + 1,
                         len((model.meta or {}).get('lane_order') or []))
        self.maxrow = self.nrows - 1

    def _solve_col_widths(self, model):
        """每列宽取该列最宽节点 + 左右各 pad，向上吸细格。"""
        GN = self.node_grid
        self.col_w = []
        for col in range(self.ncols):
            w = 0
            for row in range(self.nrows):
                for i in self.cells.get((row, col), []):
                    w = max(w, self.sizes[model.nodes[i]['type']][0])
            self.col_w.append(ceil_to(w + 2 * self.pad, GN) if w else ceil_to(2 * self.pad, GN))

    def _solve_row_heights(self):
        """每行高：槽位模式等距 pitch，阶段行模式按该行最厚摞 + 上下 vpad 取半格余数。"""
        GN = self.node_grid
        self.row_h = []
        if self.slot_mode:
            self.row_h = [self.pitch] * self.nrows      # 等距层高：层间净空恒为 pitch - 节点高
        else:
            for row in range(self.nrows):
                hh = 0
                for col in range(self.ncols):
                    ids = self.cells.get((row, col), [])
                    if ids:
                        hh = max(hh, self._stack_h(ids))
                self.row_h.append(_align_half(hh + 2 * self.vpad, GN) if hh
                                  else _align_half(2 * self.vpad, GN))

    def _solve_col_positions(self):
        """从阶段带右侧起逐列推列中心 x，画布宽取整列宽之和与下限 400 的较大者。"""
        GN = self.node_grid
        x = self.stage_w + self.route_left
        self.col_x = []
        for col in range(self.ncols):
            self.col_x.append(snap(x + self.col_w[col] / 2, GN))
            x += self.col_w[col]
        self.width = max(ceil_to(x, GN), 400)

    def _assign_lane_names(self, model):
        """按显式列序先铺一遍空泳道名，再由节点覆盖成行阶段名与列主体名。"""
        self.stages = [None] * self.nrows
        self.departments = [None] * self.ncols
        # 显式列序里的**空泳道**（如白板上全空的「财务部」）没有节点去认领它，
        # 但它在图上是要画的（表头 + 列底），所以先按列序铺一遍，再由节点覆盖成同一名字。
        for i, name in enumerate(((model.meta or {}).get('lane_order') or [])[:self.ncols]):
            self.departments[i] = name
        for n in model.nodes.values():
            self.stages[n['row']] = n.get('stage') or '未分组'
            self.departments[n['col']] = n.get('subject') or '未分组'

    def _stack_h(self, ids):
        return sum(self.sizes[self.M.nodes[i]['type']][1] for i in ids) + self.gap * (len(ids) - 1)

    def _snap_unit(self, ids):
        """该格摞顶对哪一级刻度负责：含矩形类节点 → 粗格（四边守粗格）；全是非矩形 → 细格。

        菱形/椭圆只需守细格（visual-spec §0）。一律吸粗格会把它们整摞推下 10px：行中线恒为
        `20k+10`，而 h=80 的菱形 `摞高/2 = 40 ≡ 0 (mod 20)` ⇒ 摞顶必落在 `20k+10`，永远吸不上
        粗格——这些格子就比同一行的矩形格低 10px，中线错开（DECISIONS.md D-33）。
        """
        shapes = self.M.cfg.get('shapes') or {}
        for i in ids:
            if shapes.get(self.M.nodes[i]['type'], {}).get('shape') in RECT_SHAPES:
                return self.node_grid
        return self.lattice

    def _build_rows(self):
        """按标题带 + 表头带 + 逐行高重算各行顶边 y（切换标题带后调用），并预算各格的**摞顶**。

        摞顶在这里一次算完（而不是在 `rect()` 里现算）：`rect()` 是取值路径，每调一次都重算
        就会把同一条提示重复记一遍（实测同一格记了 35 次）。
        """
        if self.slot_mode:
            # 槽位模式：层中线等距。
            # 行的**中线**必须落在 `20k+10` 上——矩形类节点四边守粗格，中线 = 行顶 + pitch/2，
            # pitch=120 时 pitch/2 ≡ 0 (mod 20)，于是行顶本身要 ≡ 10 (mod 20)，与阶段行
            # （行高 ≡ 20 mod 40，靠 pitch/2 ≡ 10 抵消）的余数**不同**，不能照抄 snap(y, 20)。
            # 而且标题带是可开关的（HTML 版不预留）——开关会把余数翻转，所以基准按当前
            # legend_h 现算，不写死。
            base = self.legend_h + self.head_h
            want = (10 - self.pitch // 2) % self.node_grid   # 行顶顶边 y 的余数
            y0 = base + ((want - base) % self.node_grid)
            self.rowy = [snap(y0 + rr * self.pitch, self.lattice) for rr in range(self.nrows)]
            self._bottom = self.rowy[-1] + self.pitch
        else:
            y = self.legend_h + self.head_h
            self.rowy = []
            for rr in range(self.nrows):
                self.rowy.append(snap(y, self.node_grid))
                y += self.row_h[rr]
            self._bottom = y

        self._stack_y = {}
        for (r, cc), ids in self.cells.items():
            mid = self.rowy[r] + self.row_h[r] / 2
            top = mid - self._stack_h(ids) / 2
            snapped = snap(top, self._snap_unit(ids))
            if snapped != top:
                self.notes.append(f'行{r} 列{cc} 摞顶 {top:g} → {snapped:g}（该格形状高度不是 20 mod 40）')
            self._stack_y[(r, cc)] = snapped

    def set_head_band(self, on=True):
        """开关画布顶部的标题带（同 `geometry.Grid.set_head_band`）。"""
        self.legend_h = snap(self._band_cfg, self.lattice) if on else 0
        self._build_rows()

    # ---------------------------------------------------------------- 与 Grid 一致的接口
    def Y(self, r):
        return self.rowy[r]

    def MID(self, r):
        """阶段行的参考 y（行垂直中心）。泳道下一行有多个节点，此值只作兜底。"""
        return self.rowy[r] + self.row_h[r] / 2

    def height(self):
        return ceil_to(self._bottom + CANVAS_BOTTOM_MARGIN, self.lattice)

    def legend_rect(self):
        return (0, 0, self.width, self.legend_h)

    def rect(self, nid):
        n = self.M.nodes[nid]
        w, h = self.sizes[n['type']]
        ids = self.cells[(n['row'], n['col'])]
        y = self._stack_y[(n['row'], n['col'])]
        for i in ids:
            if i == nid:
                break
            y += self.sizes[self.M.nodes[i]['type']][1] + self.gap
        return (self.col_x[n['col']] - w / 2, y, w, h)

    # 端口锚点与流程版 `Grid.anchor` 逐行相同（`off` 沿端口边切向错位，见 DECISIONS.md D-15/D-17）——
    # 两种布局对锚点的语义一致，直接复用 geometry 的实现，不再抄一份（抄两份迟早改散）。
    # `port_frac` 同理：它由 anchor() 反算（非矩形节点投影后比例会变，必须同源）。
    anchor = Grid.anchor
    port_frac = Grid.port_frac

    # ---------------------------------------------------------------- 泳道背景（渲染器用）
    def lanes(self):
        """泳道背景信息。流程模式的 `Grid` **没有**这个方法——渲染器据此判断该画哪种背景。

        `stage_spans` 是**连续同阶段的行区间** `[(阶段, 起行, 止行), …]`。阶段行模式下每行一个
        阶段，区间长度恒为 1；槽位模式下同一个阶段横跨多行，必须合并成一条色带再画——
        否则左侧会叠出一串同名小色块（见 swimlane-spec §3.1 末段）。
        """
        spans = []
        for rr, st in enumerate(self.stages):
            if spans and spans[-1][0] == st:
                spans[-1][2] = rr
            else:
                spans.append([st, rr, rr])
        return {'stages': self.stages, 'departments': self.departments,
                'stage_spans': [tuple(s) for s in spans], 'slot_mode': self.slot_mode,
                'stage_w': self.stage_w, 'head_h': self.head_h, 'route_left': self.route_left,
                'col_x': self.col_x, 'col_w': self.col_w,
                'rowy': self.rowy, 'row_h': self.row_h,
                'legend_h': self.legend_h, 'width': self.width,
                'subjects': self.M.subjects}
