# -*- coding: utf-8 -*-
"""lane_router.py — 泳道布线：在源/目标锚点之间选一条**不穿节点**的正交折线。

泳道的 `col` 是**部门**而不是分支列，所以 router 那套"通道族 / 列间通道"不适用——
部门之间不是"空隙"而是泳道本身。流转大多发生在相邻格，挑一条不碰节点的折线即可；
长距离跨节点的边走画布外缘通道。接口与 `Router` 一致（path/ports/polarity）。

布线分两步（见 DECISIONS.md D-30）：
  1 按跨度降序贪心出初始解（长边最受约束，先占道）
  2 **坐标下降**：每次只重选一条边、其余固定，仅接受代价严格下降的改动
"""
from geometry import (RectCache, ceil_to, ortho_cross, seg_overlap, seg_rect_hit,
                      snap, stagger_source_anchors)

HIT_MARGIN = 4        # 折线与节点的最小避让间隙（px）
MIN_LEG = 2           # 每段的最短长度（× 细格 = 20px = 一个粗格）：比这更短，转角就挤在箭头上
Z_DETOUR_TRIES = 5     # Z 形中段从中点向两侧交替偏移的最大档数（每档 1×细格）
SIDE_CHANNEL_TRIES = 4  # 贴列沿通道的候选档数（每档 2×细格）
FAR_CHANNEL_TRIES = 6   # 画布外缘通道的候选档数（每档 gutter_step）
PREROUTE_SWEEPS = 6     # 坐标下降的扫描轮数上限（一整轮无人改动即停）

# 代价权重：把四条判据编码成一个可比较的标量，**次序即优先级**。
#   共线重叠（门禁第 5 项，违规） ≫ 形状非法（D-17/D-27，贴边滑行） ≫ 交叉（允许但越少越好） ≫ 折点数
# 用标量而非元组，是为了让"改动前后比大小"满足单调性——坐标下降据此保证终止、不震荡。
W_OVERLAP, W_BADEND, W_CROSS = 10 ** 9, 10 ** 6, 10 ** 3

# 对向端口组合：出与入分处节点两侧（下→上 / 上→下 / 左→右 / 右→左）。
OPPOSITE_PORTS = {('bottom', 'top'), ('top', 'bottom'), ('left', 'right'), ('right', 'left')}

# 端口法线（朝外）：端点段必须沿法线进出，否则那段贴着节点边沿滑行、箭头横着顶进端口。
NORMAL = {'bottom': (0, 1), 'top': (0, -1), 'left': (-1, 0), 'right': (1, 0)}


class LaneRouter(RectCache):
    def __init__(self, model, grid, explore=False):
        self.M = model
        self.grid = grid
        self.explore = explore        # 探布：左族暂从画布左缘起算，用来量"left 走廊"要多宽（D-39）
        self._paths_done = False      # 预路由是否已跑
        self._choice = {}             # {边id: 候选 dict} —— 当前解
        self._orig_ports = {}         # {边id: (exit, entry)} —— 候选生成的输入（布线前/冻结）
        self._router_set = []         # 被布线器改过端口的边（重跑前要还原）
        self._router_ids = set()      # 上者对应的 id 集合（两趟提交时不重复登记）
        self._dye_set = {}            # {边id: 原 dye} —— 被对齐改写过的 dye（重跑前要还原）
        self._spread_orig = {}        # {边id: 原 (exit,entry)} —— 被"挪到空闲侧"改过端口的边
        self._edge_pts = {}           # {边id: 折点} —— path() 的对外缓存
        # 错峰锚点会把矩形缓存提前填上（stagger → ports → _row_blocked → _hits 一路读矩形，
        # 那一刻标题带还开着）——head_band(False) 之后必须靠 invalidate() 清掉它（D-19）。
        self._stagger_set = stagger_source_anchors(self.M, self.grid, self.ports)

    def invalidate(self):
        """丢矩形缓存（父类）+ 折线解——切标题带会把整图 y 平移（D-19），
        定案的折线同样按旧坐标算的，不清就会与新矩形错位。"""
        super().invalidate()
        self._edge_pts = {}
        self._choice = {}
        self._paths_done = False

    # ---------------------------------------------------------------- 几何小工具
    @classmethod
    def _dir_ok(cls, d, port, leaving):
        """该段方向是否沿端口法线：出边朝外（点积>0）、入边朝内（点积<0）。"""
        nx, ny = NORMAL[port]
        dot = d[0] * nx + d[1] * ny
        return dot > 0 if leaving else dot < 0

    def _bad_ends(self, pts, ex, en):
        """端点段不沿端口法线的条数（0/1/2）。

        形状合法性是**比交叉数更强的可读性规则**：不沿法线的那段贴着节点边框滑行、
        箭头横着顶进端口（D-17/D-27 专门修过）。不把它排在交叉数之前，"折点少"的坏形状
        会赢过"折点多"的正确形状——实测 pv-swimlane 的 15→16 就这样从 Z 退化成贴边 L。
        """
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
                if abs(pts[i][0] - pts[i + 1][0]) > 0.5 or abs(pts[i][1] - pts[i + 1][1]) > 0.5]
        if not segs:
            return 0
        bad = 0
        (a, b) = segs[0]
        if not self._dir_ok((b[0] - a[0], b[1] - a[1]), ex, True):
            bad += 1
        (a, b) = segs[-1]
        if not self._dir_ok((b[0] - a[0], b[1] - a[1]), en, False):
            bad += 1
        return bad

    def _legs_ok(self, pts):
        """每一段都不短于一个粗格（`MIN_LEG × 细格` = 20px）。

        短于此的段是"微残段"：转角挤在箭头上、看着像没画完（实测 `06→10` 的 C 形两端各 10px）。
        代价函数原先只看重叠/形状/交叉/折点数，**腿长不在其中**，于是最内缩的那条候选天然胜出。
        """
        m = MIN_LEG * self.grid.lattice
        return all(abs(q[1] - p[1]) >= m or abs(q[0] - p[0]) >= m for p, q in zip(pts, pts[1:]))

    def _hits(self, pts, ignore):
        """折线是否碰到无关节点（外扩 HIT_MARGIN 留间隙）。"""
        for k in range(len(pts) - 1):
            for nid, r in self._all_rects():
                if nid in ignore:
                    continue
                if seg_rect_hit(pts[k], pts[k + 1], r, grow=HIT_MARGIN):
                    return True
        return False

    # ---------------------------------------------------------------- 代价
    def _count_conflicts(self, pts, others):
        """数候选折线与其余各折线的共线重叠数、正交交叉数 → (重叠, 交叉)。"""
        ov = 0
        cr = 0
        for o in others:
            for i in range(len(pts) - 1):
                for j in range(len(o) - 1):
                    if seg_overlap((pts[i], pts[i + 1]), (o[j], o[j + 1])):
                        ov += 1
                    elif ortho_cross(pts[i], pts[i + 1], o[j], o[j + 1]):
                        cr += 1
        return ov, cr

    def _cost(self, cand, key, others):
        """候选的代价（越小越好）。`others` 是其余边**当前**的折线列表。

        四条判据按权重合成标量：共线重叠 ≫ 形状非法 ≫ 交叉数 ≫ 折点数。
        标量而非元组：坐标下降要求"改动前后可比大小"才能保证单调下降、不震荡。
        """
        pts = cand['pts']
        ex, en = cand.get('ports') or self._orig_ports[key]
        ov, cr = self._count_conflicts(pts, others)
        return (ov * W_OVERLAP + self._bad_ends(pts, ex, en) * W_BADEND
                + cr * W_CROSS + len(pts))

    # ---------------------------------------------------------------- 候选
    def _span(self, e):
        """边的"跨度"（行差 + 列差）。长边最受约束，先路由。"""
        na, nb = self.M.nodes[e['from']], self.M.nodes[e['to']]
        return abs(na['row'] - nb['row']) + abs(na['col'] - nb['col'])

    def _chan_pts(self, e, a, b, pex, pen, x):
        """给定左右族通道 x 与端口，拼出那条 Z 形折线。"""
        g = self.grid
        sx, sy = g.anchor(a, pex, e.get('sdye', 0))
        tx, ty = g.anchor(b, pen, e.get('dye', 0))
        return [(sx, sy), (x, sy), (x, ty), (tx, ty)]

    def _far_cands(self, e, a, b):
        """画布**最外侧**的远通道候选（所有节点左沿之外 / 右沿之外），分层排布。

        长距离跨节点的边（同列长跳、回环）走这里：空间宽、不挤列缝、交叉也少——
        用户手改版把 01b→20（跨 14 槽）、36→01（跨 30 槽）都甩到画布边缘，正是这个道理。
        纯几何生成（不看别的边选了什么），代价函数负责挑——这样坐标下降才能重算候选。

        **左族从左侧里程碑带的右沿起算**：泳道底图最左边那条带是阶段/里程碑标注，线压上去
        就是"底图和线撞车"（实测 4 条回环穿带而过）。带内一律不算可走空间。
        """
        g = self.grid
        lay = self.M.cfg.get('layout', {})
        margin = snap(lay.get('channel_margin', 40), g.lattice)
        step = snap(lay.get('gutter_step', 40), g.lattice)
        rects = [g.rect(nid) for nid in self.M.nodes]
        left_base = 0 if self.explore else snap(getattr(g, 'stage_w', 0), g.lattice)
        left_limit = min(r[0] for r in rects) - HIT_MARGIN
        right_limit = max(r[0] + r[2] for r in rects) + HIT_MARGIN
        out = []
        for k in range(FAR_CHANNEL_TRIES):
            xl = left_base + margin + step * k
            if xl >= left_limit:
                break
            out.append({'pts': self._chan_pts(e, a, b, 'left', 'left', xl),
                        'ports': ('left', 'left'), 'channel': xl})
        for k in range(FAR_CHANNEL_TRIES):
            xr = g.width - margin - step * k
            if xr <= right_limit:
                break
            out.append({'pts': self._chan_pts(e, a, b, 'right', 'right', xr),
                        'ports': ('right', 'right'), 'channel': xr})
        return out

    def _side_cands(self, e, a, b):
        """贴列**侧沿**的通道候选（左右两侧都出，D-30）。

        源目标同列、中间隔着同列节点时，走列中心线必穿中间节点。用户手改版的处理是
        **贴列沿走**（06→10 贴左沿、25→26 贴右沿外 40），而不是绕到列外再折回的大回环。

        内缩量按**一个粗格**算（不是"HIT_MARGIN + 细格"）：贴太近时出线腿只剩 10px，
        转角挤在箭头上（实测 06→10 的 C 形两端各 10px）。
        """
        g = self.grid
        ra, rb = g.rect(a), g.rect(b)
        left_edge = min(ra[0], rb[0])
        right_edge = max(ra[0] + ra[2], rb[0] + rb[2])
        inset = HIT_MARGIN + MIN_LEG * g.lattice
        step = 2 * g.lattice
        out = []
        for k in range(SIDE_CHANNEL_TRIES):
            xl = snap(left_edge - inset, g.lattice) - step * k
            xr = ceil_to(right_edge + inset, g.lattice) + step * k
            if xl >= HIT_MARGIN:
                out.append({'pts': self._chan_pts(e, a, b, 'left', 'left', xl),
                            'ports': ('left', 'left'), 'channel': xl})
            if xr <= g.width - HIT_MARGIN - g.lattice:
                out.append({'pts': self._chan_pts(e, a, b, 'right', 'right', xr),
                            'ports': ('right', 'right'), 'channel': xr})
        return out

    def _diag_l_cands(self, e, a, b):
        """回环也吃"顺路的对角 L"：目标在上 → 从顶顶点出去；在左 → 从右侧顶点接进。

        只给通道族时，回环一律绕画布外缘或贴列沿——哪怕源目标斜对角、一个折点就到（实测 13→10：
        从 13 顶顶点直上 200px 再左转 480px 接 10 的右顶点即可，却被算成绕右外缘 580px 的大回环）。
        两条 L 都生成（竖出横入 / 横出竖入）：穿节点由 `_hits` 过滤，好不好由代价择优。
        """
        g = self.grid
        ca, cb = g.rect(a), g.rect(b)
        acx, acy = ca[0] + ca[2] / 2, ca[1] + ca[3] / 2
        bcx, bcy = cb[0] + cb[2] / 2, cb[1] + cb[3] / 2
        # 出口取"源自身上朝目标的那一侧"，入口取"目标身上朝源的那一侧"——两侧的判据刚好相反：
        # 目标在上 ⇒ 源出顶顶点，而入口落在目标的**底**顶点。
        up = bcy < acy
        left = bcx < acx
        exit_v, entry_v = ('top' if up else 'bottom'), ('bottom' if up else 'top')
        exit_h, entry_h = ('left' if left else 'right'), ('right' if left else 'left')
        out = []
        for ex, en in ((exit_v, entry_h), (exit_h, entry_v)):
            sx, sy = g.anchor(a, ex, e.get('sdye', 0))
            tx, ty = g.anchor(b, en, e.get('dye', 0))
            pts = [(sx, sy), (sx, ty), (tx, ty)] if ex in ('top', 'bottom') \
                else [(sx, sy), (tx, sy), (tx, ty)]
            out.append({'pts': pts, 'ports': (ex, en)})
        return out

    def _direct_cands(self, e, a, b, ex, en, sx, sy, tx, ty, add):
        """非回环边的直连候选：直线、对向端口的 Z 形、两条 L 形、行内空带绕行、同列贴沿/外缘。

        前四类经调用方的 `add` 闭包按序收集（顺序即择优优先级）；同列的贴沿/外缘候选
        以返回值给出，由调用方追加在末尾。

        对向端口且两轴都有偏移时，两条 L 形**各有一端贴边**：to_v 的末段水平滑进 top 口、
        水平段贴着目标上边框；to_h 的首段同理贴源边框——"首末段都沿端口法线"这条约束
        （D-17/D-27）在此时只有 Z 形满足。
        """
        g = self.grid
        if abs(sx - tx) < 0.5 or abs(sy - ty) < 0.5:
            add([(sx, sy), (tx, ty)])
        if ((ex, en) in OPPOSITE_PORTS
                and abs(sx - tx) >= 0.5 and abs(sy - ty) >= 0.5):
            for pts in self._z_cands(sx, sy, tx, ty, g.lattice, ex in ('top', 'bottom')):
                add(pts)
        to_h = [(sx, sy), (tx, sy), (tx, ty)]
        to_v = [(sx, sy), (sx, ty), (tx, ty)]
        for pts in ([to_h, to_v] if ex in ('left', 'right') else [to_v, to_h]):
            add(pts)
        ra = self.M.nodes[a]['row']
        # row_h 是**泳道栅格**才有的（每阶段的泳道带高度不同）；误配到流程版 Grid 上，
        # 这里会抛一个指向行号的 AttributeError，而真正的错因是"grid 与 router 组合错了"。
        row_h = getattr(g, 'row_h', None)
        if row_h is None:
            raise AttributeError(f'LaneRouter 需要泳道栅格（有 row_h），当前是 '
                                 f'{type(g).__name__}：grid 与 router 的布局组合不匹配')
        lys = [g.rowy[ra] + g.lattice, g.rowy[ra] + row_h[ra] - g.lattice]
        lys.sort(key=lambda v: (abs(v - sy), -v))
        for ly in lys:
            add([(sx, sy), (sx, ly), (tx, ly), (tx, ty)])
        if self.M.nodes[a]['col'] == self.M.nodes[b]['col']:
            # 同列（可能跨过同列中间节点）：近处贴列沿，远处走画布外缘——交给代价择优。
            return self._side_cands(e, a, b) + self._far_cands(e, a, b)
        return []

    def _prune_cands(self, out, a, b):
        """硬约束筛选：先取"不穿无关节点且每段不短于一个粗格"的；没有再退一步只保证不穿节点。

        不能为了腿长逼出穿节点的线，那更糟（validate 会报出来，好过悄悄压节点）。
        """
        clean = [c for c in out if not self._hits(c['pts'], (a, b)) and self._legs_ok(c['pts'])]
        if clean:
            return clean
        safe = [c for c in out if not self._hits(c['pts'], (a, b))]
        return safe or out

    def _cands(self, e):
        """这条边的**全部**候选（纯几何，不依赖别的边选了哪条）。

        纯函数是关键：坐标下降要对同一条边反复重算候选，候选集一旦随"别的边的选择"变化，
        "只改一条"的前提就不成立了。
        """
        g = self.grid
        a, b = e['from'], e['to']
        ex, en = self._orig_ports[id(e)]
        sx, sy = g.anchor(a, ex, e.get('sdye', 0))
        tx, ty = g.anchor(b, en, e.get('dye', 0))

        out = []

        def add(pts, ports=None):
            out.append({'pts': pts, 'ports': ports})

        if e.get('kind') == 'loop':
            # 回环：画布外缘通道 + 贴列沿通道（左侧被节点堵死时走右侧）+ 顺路的对角 L
            out += self._far_cands(e, a, b)
            out += self._side_cands(e, a, b)
            out += self._diag_l_cands(e, a, b)
        else:
            out += self._direct_cands(e, a, b, ex, en, sx, sy, tx, ty, add)
        return self._prune_cands(out, a, b)

    def _z_cands(self, sx, sy, tx, ty, lattice, vertical):
        """对向端口的 Z 形候选：两端沿端口法线进出，中段在两锚点之间折一次。

        中段坐标取两锚点的中点（吸细格）；撞节点就在开区间内交替向两侧偏移再试
        （与 loop 绕行同思路，步距 1×细格）。开区间保证首末两段方向仍沿端口法线
        ——mid 越过任一锚点，首段或末段就会反向、贴着节点边沿折回来。
        """
        offs = [0] + [s * k for k in range(1, Z_DETOUR_TRIES) for s in (1, -1)]
        if vertical:                       # 竖进竖出：中段水平，my 落在 (sy, ty) 开区间
            lo, hi = sorted((sy, ty))
            base = snap((sy + ty) / 2, lattice)
            return [[(sx, sy), (sx, my), (tx, my), (tx, ty)]
                    for my in (base + lattice * d for d in offs) if lo < my < hi]
        lo, hi = sorted((sx, tx))           # 水平端口：中段竖直，mx 落在 (sx, tx) 开区间
        base = snap((sx + tx) / 2, lattice)
        return [[(sx, sy), (mx, sy), (mx, ty), (tx, ty)]
                for mx in (base + lattice * d for d in offs) if lo < mx < hi]

    # ---------------------------------------------------------------- 端口
    def _row_blocked(self, a, b, ex, en):
        """同行的 a→b 是否**两条 L 形都走不通**（要绕空带）——那才值得换端口。

        判据必须是实际布线的折线，不是两端锚点的连线：锚点分处节点左右两侧时，
        连线是斜的，会"穿过"根本没挡路的节点，把干净的直线也误判成被挡。
        """
        sx, sy = self.grid.anchor(a, ex)
        tx, ty = self.grid.anchor(b, en)
        to_h = [(sx, sy), (tx, sy), (tx, ty)]
        to_v = [(sx, sy), (sx, ty), (tx, ty)]
        return self._hits(to_h, (a, b)) and self._hits(to_v, (a, b))

    def ports(self, e):
        """端口按源与目标的相对位置选，**不能写死 bottom→top**——原因与后果见 swimlane-spec §4。"""
        if e.get('exit') and e.get('entry'):
            return e['exit'], e['entry']
        if e.get('kind') == 'loop':
            return 'left', 'left'
        a, b = e['from'], e['to']
        na, nb = self.M.nodes[a], self.M.nodes[b]
        row_from, row_to = na['row'], nb['row']
        col_from, col_to = na['col'], nb['col']
        if row_from == row_to and col_from == col_to:  # 同格：按格内先后（下→上 或 上→下）
            ids = self.grid.cells[(row_from, col_from)]
            return ('bottom', 'top') if ids.index(a) < ids.index(b) else ('top', 'bottom')
        if row_from == row_to:                         # 同行不同列
            ex, en = ('right', 'left') if col_from < col_to else ('left', 'right')
            if self._row_blocked(a, b, ex, en):
                # 中间隔着别的节点时，从左右端口出去必然撞上它；此时绕本行下方空带走
                # bottom→bottom 最短（见 DECISIONS.md D-17），也让开"贴着被挡节点边沿"的走法。
                return 'bottom', 'bottom'
            return ex, en
        return ('bottom', 'top') if row_from < row_to else ('top', 'bottom')

    def polarity(self, e):
        return e.get('polarity') or ('negative' if e.get('kind') == 'loop' else 'main')

    def _spread_contended_ports(self):
        """非矩形节点的同一侧挤了多条出边时，把多余的挪到**空着的垂直侧**去。

        菱形/椭圆的端点一旦沿同侧错峰就落到斜边上（肉眼就是"接到了它的边"，D-31），而它的左右侧
        往往空着。挪过去后锚点落在顶点上，同侧的挤占也自然消解；被挪那条原来的错峰量随即成了孤儿，
        由 `_drop_orphan_offsets()` 在第二趟清掉。
        """
        shapes = self.M.cfg.get('shapes') or {}
        used = {}
        for e in self.M.edges:
            ex, en = self.ports(e)
            used.setdefault(e['from'], set()).add(ex)
            used.setdefault(e['to'], set()).add(en)
        groups = {}
        for e in self.M.edges:
            groups.setdefault((e['from'], self.ports(e)[0]), []).append(e)
        for (nid, side), group in groups.items():
            if len(group) < 2:
                continue
            if shapes.get(self.M.nodes[nid]['type'], {}).get('shape') not in ('rhombus', 'ellipse'):
                continue
            free = [s for s in (('left', 'right') if side in ('top', 'bottom') else ('top', 'bottom'))
                    if s not in used.get(nid, set())]
            # 跨度最短的留在原侧——它多半是"下一行的那一步"，本该直着走；需要绕行的长边才挪走。
            # 反过来的话，短边被推到侧面绕一圈，长边反而直着穿中间节点（实测 06→07 被挪到左侧后，
            # 与同样走左侧的 06→10 又挤到一起，偏移照样落在斜边上）。
            for oe in sorted(group, key=self._span)[1:]:
                if not free:
                    break
                _ex, en = self.ports(oe)
                alt = free.pop(0)
                self._spread_orig[id(oe)] = (oe.get('exit'), oe.get('entry'))
                oe['exit'], oe['entry'] = alt, en
                used.setdefault(nid, set()).add(alt)

    def _drop_orphan_offsets(self):
        """清掉"成了孤儿"的错峰量，返回是否有改动。

        错峰在构造时按**布线前**的端口决定，可布线器随后可能把"竞争者"挪到别的端口（实测 06→10
        改从左顶点出线）——这条偏移就没人跟它挤了，却还把锚点从菱形顶点推到斜边上。所以端口定案后
        复查一次：某端口只剩它一条边 ⇒ 偏移没有存在理由。只清本布线器自己设过的那批（D-31），
        用户手填的 `sdye` 不动。
        """
        shapes = self.M.cfg.get('shapes') or {}
        used = {}
        for e in self.M.edges:
            px, py = self._choice[id(e)].get('ports') or self._orig_ports[id(e)]
            for nid, side in ((e['from'], px), (e['to'], py)):
                used[(nid, side)] = used.get((nid, side), 0) + 1
        dropped = False
        for e in self.M.edges:
            if id(e) not in self._stagger_set or not e.get('sdye'):
                continue
            px = (self._choice[id(e)].get('ports') or self._orig_ports[id(e)])[0]
            shp = shapes.get(self.M.nodes[e['from']]['type'], {}).get('shape')
            if shp in ('rhombus', 'ellipse') and used.get((e['from'], px), 0) <= 1:
                e['sdye'] = 0
                dropped = True
        return dropped

    # ---------------------------------------------------------------- 求解
    def _others(self, key):
        """其余边当前选择的折线（坐标下降里"固定不动"的那部分）。"""
        return [c['pts'] for k, c in self._choice.items() if k != key]

    def _pick(self, e):
        """在候选里挑代价最低的（其余边固定为当前选择）。"""
        key = id(e)
        cands = self._cands(e)
        others = self._others(key)
        best = min(cands, key=lambda c: self._cost(c, key, others))
        return best

    def _align_anchors(self):
        """微折点消除：两锚点在端口**切向**只差 ≤1 细格时，把目标锚点对齐到源锚点。

        不消除的话会造出一条 10px 的残段（如 01a→02 的 `[(680,340),(680,330)]`）——是噪声不是路由。
        两个要点：
          1. 写成 **`dye`**，而不是在候选里直接改写坐标：渲染器画端口读的是 `dye`，
             只改候选坐标会让"drawio 画的起点"与"折线首点"不一致。
          2. 写**偏移量**而不是直接改 y：`anchor()` 会据偏移把非矩形节点（菱形/椭圆）的点
             投影回真实边界，绕过它就会留在矩形边上、离开斜边（D-31 实测悬空 16px）。
        """
        g = self.grid
        for e in self.M.edges:
            ex, en = self._orig_ports[id(e)]
            horiz = ex in ('left', 'right') and en in ('left', 'right')
            vert = ex in ('top', 'bottom') and en in ('top', 'bottom')
            if not (horiz or vert):
                continue
            dye = e.get('dye', 0) or 0
            sx, sy = g.anchor(e['from'], ex, e.get('sdye', 0))
            tx, ty = g.anchor(e['to'], en, dye)
            d = (sy - ty) if horiz else (sx - tx)
            if abs(d) <= g.lattice and abs(d) > 0.01:
                e['dye'] = dye + d
                self._dye_set[id(e)] = dye

    def _greedy_seed(self, order):
        """贪心初始解（1）：按跨度降序逐边取当前最优候选，长边最受约束、先占道。"""
        self._choice = {}
        for e in order:
            self._choice[id(e)] = self._pick(e)

    def _descend(self, order):
        """坐标下降（2）：每次只重选一条边、其余固定，仅接受代价严格下降的改动，不降即停。"""
        for _ in range(PREROUTE_SWEEPS):
            changed = 0
            for e in order:
                key = id(e)
                new = self._pick(e)
                if self._cost(new, key, self._others(key)) \
                        < self._cost(self._choice[key], key, self._others(key)):
                    self._choice[key] = new
                    changed += 1
            if not changed:
                break

    def _solve(self):
        """贪心初始解 + **坐标下降**，解写进 `self._choice`（输入是 `self._orig_ports`）。"""
        order = sorted(self.M.edges, key=self._span, reverse=True)
        self._greedy_seed(order)
        self._descend(order)
        return order

    def _commit(self, order):
        """定案：写回端口与折线缓存。"""
        for e in order:
            c = self._choice[id(e)]
            if c.get('ports'):
                e['exit'], e['entry'] = c['ports']
                if id(e) not in self._router_ids:
                    self._router_ids.add(id(e))
                    self._router_set.append(e)
            self._edge_pts[id(e)] = c['pts']

    def release(self):
        """把写进边对象的几何改写（端口 / `dye` / 被挪到空闲侧的端口 / **本趟自动设下的 `sdye`**）还回去。

        引擎重建布局（探布之后定案重排，D-39）时要**干净重解**：不还原的话，新一趟会把探布
        写下的 `exit`/`entry` 当成"布线前的端口"照单全收，等于在旧解上打补丁而不是重算。

        `sdye`（D-82）要**清掉、不是还原成原值**：`stagger_source_anchors` 对手填值一律让路，
        所以上一趟的自动偏移在这趟眼里就是"手填值"——还原成原值等于把上一趟的残留原样留在原地
        （实测：探布趟写下的 20 / −20 会一路活到定案趟）。而**手填值本来就不进 `_stagger_set`**
        （那条函数只往空槽位写），所以"清掉这个集合里的"既清得干净、又不碰用户填的。

        注意这段**只挂在 `release()` 上、不并进 `_reset()`**：`_pre_route()` 里也调 `_reset()`，
        而那时的 `_stagger_set` 正是本趟刚设下、还要用的偏移——并进去会把本趟的错峰当场清掉。
        """
        for e in self.M.edges:
            if id(e) in self._stagger_set:
                e.pop('sdye', None)
        self._reset()

    def _reset(self):
        """还原上一轮留下的端口改写与 dye 对齐（invalidate 后重解的前提）。"""
        for e in self._router_set:
            e.pop('exit', None)
            e.pop('entry', None)
        self._router_set, self._router_ids = [], set()
        for k, v in self._dye_set.items():
            for e in self.M.edges:
                if id(e) == k:
                    if v is None:
                        e.pop('dye', None)
                    else:
                        e['dye'] = v
        self._dye_set = {}
        for k, (x, y) in self._spread_orig.items():
            for e in self.M.edges:
                if id(e) == k:
                    for key, v in (('exit', x), ('entry', y)):
                        if v is None:
                            e.pop(key, None)
                        else:
                            e[key] = v
        self._spread_orig = {}

    def _resolve_orphan_offsets(self):
        """端口定案后复查孤立偏移：有漂移就冻结端口、只让偏移归零，再干净重解一趟（D-31）。"""
        if not self._drop_orphan_offsets():
            return
        self._orig_ports = {id(e): ((e['exit'], e['entry']) if e.get('exit') else self.ports(e))
                            for e in self.M.edges}
        self._commit(self._solve())

    def _pre_route(self):
        """两步求解（D-30）：贪心初始解 + **坐标下降**；再清一遍"孤立偏移"重解（D-31）。

        path() 原本"谁先问谁先算"（表序），致命的是**信息不足**：路由长边时短边尚未定案，
        "交叉最少"对每条候选都算出 0，退化成按候选顺序挑（实测 01b→20 因此落到列缝 450，
        而它该走的 80 交叉为 0、450 有 9）。故先按跨度降序贪心一次，让长边先占道。

        再反复扫描：**固定其余边，只重选一条**，且仅接受代价严格下降的改动。这一步是关键——
        早先"每轮全体重选"的做法，A 的改动会推翻 B 的判断依据，可能 A→B→A 来回震荡；
        而"一次一条 + 只接受下降"让全图代价**单调递减**，必然终止、且不会震荡。

        第二趟只在"端口出现孤儿偏移"时才跑：端口沿用第一趟的结果（冻结），只让那些偏移归零，
        因此不可能与第一趟的选择来回震荡。
        """
        if self._paths_done:
            return
        self._paths_done = True
        self._reset()
        self._spread_contended_ports()        # 同侧挤多条出边 → 挪到空闲侧（D-31）
        # 候选生成只认"布线前"的端口，中途不改边对象——否则坐标下降重算候选时输入就变了
        self._orig_ports = {id(e): self.ports(e) for e in self.M.edges}
        self._align_anchors()                 # 微折点消除（写成 dye，渲染器才看得见）
        self._commit(self._solve())
        self._resolve_orphan_offsets()

    def path(self, e):
        """折线（定案后即缓存）。path 会被渲染器与 validate 反复调用，必须稳定同一条。"""
        key = id(e)
        if key in self._edge_pts:
            return self._edge_pts[key]
        self._pre_route()
        return self._edge_pts[key]
