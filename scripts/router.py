# -*- coding: utf-8 -*-
"""router.py — 边路由层：端口解析、正交折线路径、分支极性、回路通道自动分配。

边永不穿节点：五类折线 spine/horiz/loop/jumpR/mix；loop 走左通道、jumpR 走右通道。
自动规划的通道 x 与 dye 都吸附细格（通道落在节点夹缝，10px 刻度够用），节点盒的粗格由 geometry 保证；
折点全部由「粗格锚点 + 细格通道」推出。
"""
from geometry import RectCache, lane_step, seg_rect_hit, snap, stagger_source_anchors

NODE_CLEARANCE = 6         # 通道/折线与节点边沿的最小间隙（px）
FALLBACK_CHANNEL_TRIES = 16   # 兜底通道最多右移步数（防死循环；全失败退回旧兜底由 validate 拦截）


class Router(RectCache):
    def __init__(self, model, grid):
        self.M = model
        self.grid = grid
        self._gutter_done = False

    # ---------- 端口与极性 ----------
    def ports(self, e):
        d = self.M.cfg.get('default_ports', {}).get(e['kind'], {'exit': 'bottom', 'entry': 'top'})
        return e.get('exit') or d['exit'], e.get('entry') or d['entry']

    def polarity(self, e):
        return e.get('polarity') or ('negative' if e['kind'] == 'loop' else 'main')

    # ---------- 路径 ----------
    @staticmethod
    def _dedup(pts):
        """去掉连续重复的退化折点（L 形候选的通道值=锚点 x 时首/尾会出现）。"""
        out = []
        for p in pts:
            if not out or abs(out[-1][0] - p[0]) > 0.5 or abs(out[-1][1] - p[1]) > 0.5:
                out.append(p)
        return out

    def path(self, e):
        g = self.grid
        self._ensure_gutters()
        ex, en = self.ports(e)
        sx, sy = g.anchor(e['from'], ex, e.get('sdye', 0))
        tx, ty = g.anchor(e['to'], en, e.get('dye', 0))
        xg = self._resolve_channel_x(e)
        if xg is not None:                    # 横向专用通道（跨列通道 / 左回路道 / 右长跳道 / L 折点）
            return self._dedup([(sx, sy), (xg, sy), (xg, ty), (tx, ty)])
        k = e['kind']
        if k == 'spine':
            return self._dedup([(sx, sy), (sx, ty)])
        if k == 'horiz':
            mx = snap((sx + tx) / 2, g.lattice)   # 折点必须落细格（手填奇数 dye/sdye 时中点会落半格）
            return self._dedup([(sx, sy), (mx, sy), (mx, ty), (tx, ty)])
        if ex in ('bottom', 'top'):
            return self._dedup([(sx, sy), (sx, ty), (tx, ty)])
        return self._dedup([(sx, sy), (tx, sy), (tx, ty)])

    def _resolve_channel_x(self, e):
        """定这条边要走的横向专用通道 x（已吸细格）；没有专用通道时返回 None。"""
        g = self.grid
        xg = e.get('gapx')
        if xg is None and e['kind'] in ('loop', 'jumpR'):
            # 通道字段按端口侧决定：左族写 gutter、右族写 channel、跨列写 gapx，
            # 长跳退到左族时也必须读 gutter，否则会退回默认右道。
            xg = e.get('gutter') if e.get('gutter') is not None else e.get('channel', g.RG)
        if xg is None:
            return None
        return snap(xg, g.lattice)             # 手填通道也吸到细格

    # ---------- 回路通道 ----------
    def _hs(self, e):
        """边的竖直跨度（两水平段所在 y 的 min..max），供通道重叠判定。"""
        ex, en = self.ports(e)
        sy = self.grid.anchor(e['from'], ex, e.get('sdye', 0))[1]
        ty = self.grid.anchor(e['to'], en, e.get('dye', 0))[1]
        return min(sy, ty), max(sy, ty)

    # ---------- 通道族与分配 ----------
    def _halfw(self, col):
        ws = [self.grid.sizes[n['type']][0] for n in self.M.nodes.values() if n['col'] == col]
        return (max(ws) / 2) if ws else 0

    def _col_gap(self, c):
        """第 c 列与其右邻列之间的空隙中心 x（两列节点边沿的中点）。"""
        g = self.grid
        return (g.col_x[c] + self._halfw(c) + g.col_x[c + 1] - self._halfw(c + 1)) / 2

    def _cross_adj(self, e):
        """是否需要走相邻列之间的空隙：同行直线(horiz)除外。"""
        if e.get('kind') == 'horiz':
            return False
        col_from = self.M.nodes[e['from']]['col']
        col_to = self.M.nodes[e['to']]['col']
        return abs(col_from - col_to) == 1

    def _anchor_taken(self, e, nid, side, off, is_entry):
        """nid 的 side 端口（切向偏移 off）是否会被**其他边**占用——按显式字段或 kind 默认端口推。

        L 候选独用：两条边的入口/出口叠在同一锚点时，validate 的共享端点豁免会放行
        重叠段（豁免本意是分叉/合流汇成一点），L 形必须自己避开。"""
        for o in self.M.edges:
            if o is e or (o.get('to') if is_entry else o.get('from')) != nid:
                continue
            d = self.M.cfg.get('default_ports', {}).get(o.get('kind'), {})
            if is_entry:
                side_o, off_o = o.get('entry') or d.get('entry'), o.get('dye', 0)
            else:
                side_o, off_o = o.get('exit') or d.get('exit'), o.get('sdye', 0)
            if side_o == side and abs(off_o - off) < 0.5:
                return True
        return False

    @staticmethod
    def _alt_xs(start, step, limit):
        """以 start 为中心左右交替展开的候选 x（窄空隙里也能榨出多条通道）。"""
        xs = [start]
        for i in range(1, limit):
            xs.append(start + step * i)
            xs.append(start - step * i)
        return xs

    def _clean_l_cands(self, e, fx, tx, row_from, row_to, col_from, col_to, g):
        """前向对角的干净 L 候选（右下=右出顶入、左下=左出顶入，两侧镜像）；端口被占了就跳过。"""
        cands = []
        # ① 前向对角的干净 L：折点 x 就记在 gapx 里，**两侧都取目标列中心**——取源列中心只有右向
        #    才碰巧退化成 L，左向会变成"底出竖落再横插"。
        #    端口被别的边占了就跳过（叠锚点的重叠段过不了 validate 的共享端点豁免）。
        if row_from < row_to and col_from != col_to:
            if col_from < col_to:
                if (not self._anchor_taken(e, tx, 'top', e.get('dye', 0), True)
                        and not self._anchor_taken(e, fx, 'right', e.get('sdye', 0), False)):
                    cands.append(('right', 'top', g.col_x[col_to]))
                # 右向的次选（D-162）：目标的**顶**端口被别的边占了时，退到「底出 + 侧入」的 L。
                # 占掉它的通常就是同槽位的主干入边（`bottom`→`top` 的 spine）——实测 `13d→13f`
                # 因此落到 Z 形，而它正下方明明是空的。折点取**源列中心**（首段零长，被 `_dedup`
                # 吃掉，得 [(sx,sy),(sx,ty),(tx,ty)]）；"源正下方没有别的节点"由 `_path_rejects`
                # 的穿节点检查隐式保证，不必另写判据。别删——它兜的正是右出/顶入两路都被占的那一半。
                if (not self._anchor_taken(e, tx, 'left', e.get('dye', 0), True)
                        and not self._anchor_taken(e, fx, 'bottom', e.get('sdye', 0), False)):
                    cands.append(('bottom', 'left', g.col_x[col_from]))
            else:
                # **左向必须镜像右向**（D-161）：原先只有 (`bottom`,`right`)——源出**底边**、目标进
                # **右侧**。它与右向的 (`right`,`top`) 不是镜像，于是"A 居中分叉到左右两侧"时，
                # A 的两条出边一条走底边、一条走侧沿（实测 (bottom,right) × (right,top)）。
                if (not self._anchor_taken(e, tx, 'top', e.get('dye', 0), True)
                        and not self._anchor_taken(e, fx, 'left', e.get('sdye', 0), False)):
                    cands.append(('left', 'top', g.col_x[col_to]))
                # 旧走法降为**次选**，不是删掉：左端口被别的边占了（`_anchor_taken` 挡），或左出
                # 首段撞上同行的并行节点（`_chan_conflict` → `_seg_hits_rects` 挡）时，
                # 这条边仍有一条 L 可走，不至于退到 Z 形绕行甚至画布外缘。
                # 别按"更对称"把这段也删了——它兜的正是左出被挡的那一半。
                if (not self._anchor_taken(e, tx, 'right', e.get('dye', 0), True)
                        and not self._anchor_taken(e, fx, 'bottom', e.get('sdye', 0), False)):
                    cands.append(('bottom', 'right', g.col_x[col_from]))
        return cands

    def _cross_gap_cands(self, lay, col_from, col_to, limit, GL):
        """列间通道候选（Z 形，L 走不通时的次选，折点取两列空隙中心）。"""
        # ② 列间通道（Z 形，L 走不通时的次选）
        ports = ('right', 'left') if col_from < col_to else ('left', 'right')
        gap_mid = snap(self._col_gap(min(col_from, col_to)), GL)
        return [(ports[0], ports[1], x)
                for x in self._alt_xs(gap_mid, snap(lay.get('col_gap_step', 40), GL), limit)]

    def _col_edge(self, col):
        """第 col 列的**最外沿** → `(左沿, 右沿)`。没有节点时退回该列的配置中心。

        通道基准必须用**节点外沿**、不能用列中心：中心 + `offset` 在 offset 大（旧值 140）、
        节点半宽 80 的巧合下才刚好落在框外；offset 一小（D-91 改成 40）就会落进节点里，
        候选全被"穿节点"罚掉，通道又被推回外圈。
        """
        rs = [self.grid.rect(n['id']) for n in self.M.nodes.values() if n['col'] == col]
        if not rs:
            return self.grid.col_x[col], self.grid.col_x[col]
        return min(r[0] for r in rs), max(r[0] + r[2] for r in rs)

    def _right_family_cands(self, lay, col_from, col_to, limit, GL):
        """右族长跳候选：以本边涉及列中更靠右列的**右沿**为局部基准，只向外展开（D-91）。"""
        # ③ 右族（局部基准，只向外展开）
        step_r = lane_step(lay, GL)
        off_r = snap(lay.get('right_channel_offset', 40), GL)
        local_rg = snap(self._col_edge(max(col_from, col_to))[1] + off_r, GL)
        return [('right', 'right', local_rg + step_r * i) for i in range(limit)]

    def _mirror_left_cands(self, lay, col_from, col_to, limit, GL):
        """左族：以本边涉及列的**左沿**为局部基准向左展开（D-92「臂」的另一半）。

        与右族同一个口径（贴列 + 束距）。单列图里它算出的第一个候选**恰好等于**旧的
        `gutter_inner` 走廊 x（`280 = DEFAULT_COL_X 400 − 120 = 首列左沿外 40`）——旧值能work，
        靠的正是"主轴恒为最左列"这个前提；前提一破（分支分挂两侧），走左廊的回路就得绕过整条
        左臂：实测 `05f→05b` 绕行 385%（实走 1260px、最短 260px）。

        ⚠ **左族镜像复用右族那两个参数**（G72）：`right_channel_step` / `right_channel_offset`
        的名字里带"右"，但左族**刻意同口径**——两侧束距与贴列距离必须一致，否则同一张图左右
        不对称，而 `dictionary.yaml` 里只有这两个数。命名是历史（D-92 先做右族），不是"只对右边生效"。
        """
        step_l = lane_step(lay, GL)
        off_l = snap(lay.get('right_channel_offset', 40), GL)
        local_lg = snap(self._col_edge(min(col_from, col_to))[0] - off_l, GL)
        return [('left', 'left', local_lg - step_l * i) for i in range(limit)]

    def _candidates(self, e, lay):
        """按优先级返回候选 (exit, entry, x)：干净 L（前向对角）→ 列间通道 → 左通道（单列回路）→ 右通道（长跳）。

        **前向对角先走干净 L**（D-28 / D-161）：右下=右出顶入、左下=左出顶入，两侧镜像——
        两段都沿端口法线、只有一个折点，源出侧沿、目标从顶进；列间通道的 Z 形会把出入口挤在
        节点同一侧（如 02→03b 左口进、03b→04 左口出），两条 Z 还在同一空隙里镜像交错。
        **右通道的刻度管制**：起点 = 本边涉及列的**最右外沿** + right_channel_offset（局部基准，D-91），
        只向外展开——用全图最右列做基准，会把 c0 内部的长跳推到最右列之外
        （08→09 曾落在 1000，而本列节点右沿只有 480）；撞上更右列的节点由逐候选的节点检查拦下。
        **候选 x 一律吸附细格**：起点余数不同（余 0 / 余 10），吸附后同一图的通道才落在统一刻度上。"""
        g = self.grid
        GL = g.lattice
        limit = int(lay.get('max_channels', 8))
        margin = snap(lay.get('channel_margin', 40), GL)
        fx, tx = e['from'], e['to']
        col_from, col_to = self.M.nodes[fx]['col'], self.M.nodes[tx]['col']
        row_from, row_to = self.M.nodes[fx]['row'], self.M.nodes[tx]['row']
        left_limit = snap(min(rx for _, (rx, ry, rw, rh) in self._all_rects()) - margin, GL)
        # 左族 = **镜像就近**（贴本边涉及列的左沿，D-92）+ 旧的 `gutter_inner` 左走廊兜底。
        # `gutter_inner` 是**相对画布原点**的基准（字典默认 280 = 首列默认中心 400 再往左一格半），
        # 所以要叠 `origin_x`；它只在镜像候选全冲突时才用得上（主轴不再是最左列时它绕远）。
        near_left = self._mirror_left_cands(lay, col_from, col_to, limit, GL)
        far_left = [('left', 'left', x)
                    for x in self._alt_xs(snap(lay.get('gutter_inner', 280), GL) + g.origin_x,
                                          snap(lay.get('gutter_step', 40), GL), limit)
                    if x <= left_limit]
        left_family = near_left + far_left

        cands = []
        cands += self._clean_l_cands(e, fx, tx, row_from, row_to, col_from, col_to, g)
        if self._cross_adj(e) and row_from != row_to:
            cands += self._cross_gap_cands(lay, col_from, col_to, limit, GL)
        if e.get('kind') == 'loop':
            cands += left_family
        cands += self._right_family_cands(lay, col_from, col_to, limit, GL)
        # **试过两次"长跳束两侧交替"（D-91 与 D-92），两次都更差**（自举 42%→45%、43%→45%）：
        # 单列函数流里几十条长跳的**竖直跨度互相重叠**，谁也借不了谁的竖道，束宽是"条数 × 束距"
        # 的硬账；把档交替到两侧并不减小半径（对某一条边来说两侧等距），只是让分配次序更乱。
        # 那批表的绕行要真降，得让**跨度**本身变短（把长跳拆到两列）——那是生成器/布局的活，
        # 记在 `coding-spec` G12 里。
        # 左族兜底给**非 loop** 的 pend 边：loop 已在 ① 之后加过一遍左族，再追加一份是重复
        # （同一批候选重复不影响命中结果，但会让人误以为 loop 有第二次机会）。
        # jumpR 语义是走右通道，但右族全冲突时仍允许退到左族——否则这类边直接无解。
        # **注意**：D-91 试过让跳转边也走"两侧对称束"（在右族每档后面插一条镜像档），实测更差
        # （自举 42%→45%）——那一次镜像档与 `gutter_inner` 兜底**并存**，等于给分配器多了些
        # 并不更近的选择；D-92 改的是另一件事：把**回路**的左族基准从"画布左廊"换成"本边涉及
        # 列的左沿"（贴列），并把旧走廊降级为末位兜底。
        if e.get('kind') != 'loop':
            cands += left_family
        return [(ex, en, snap(x, GL)) for ex, en, x in cands if x >= margin]

    def _seg_hits_rects(self, p1, p2, ignore, m=NODE_CLEARANCE):
        """轴向线段是否穿过某节点矩形。矩形**外扩** m 像素：通道与节点边沿至少留 m 的间隙。"""
        for nid, r in self._all_rects():
            if nid in ignore:
                continue
            if seg_rect_hit(p1, p2, r, grow=m):
                return True
        return False

    @staticmethod
    def _hsegs(ex, sx, tx, ch, sy, ty):
        return [((min(sx, ch), sy), (max(sx, ch), sy)),
                ((min(tx, ch), ty), (max(tx, ch), ty))]

    def _seg_crosses_own(self, p1, p2, a, b, m=NODE_CLEARANCE):
        """折线是否横穿自身源/目标节点的**内部**（矩形内缩 m）。判据见 visual-spec 第 4 项。"""
        for nid in (a, b):
            if seg_rect_hit(p1, p2, self.grid.rect(nid), grow=-m):
                return True
        return False

    def _path_rejects(self, e, ch, ex, en):
        """这一档通道算出来的三段路，踩没踩**硬**规矩：(d1) 任一段穿节点或横穿自身端点；
        (d2) 任一段短于一格粗格（产物自检会报"转角挤在箭头上"）。

        为什么单列出来（G84/D-152）：两条都是**产物几何自检直接红**的，候选筛选**和**兜底都不许
        放宽。此前这段判断只写在 `_chan_conflict` 里，而 `_fallback_channel` 的"最后一招"
        （只避开已占通道）**绕过**了它——于是单列的自举树漏出 0px 短段（`18→11` 就是这么来的），
        多列的表漏出穿节点的折线。
        """
        g = self.grid
        sx, sy = g.anchor(e['from'], ex, e.get('sdye', 0))
        tx, ty = g.anchor(e['to'], en, e.get('dye', 0))
        ign = (e['from'], e['to'])
        floor = g.node_grid        # 最短段 = 一格粗格（与 `validate._artifact_short_segment_errors` 同口径）
        for p1, p2 in ((sx, sy), (ch, sy)), ((ch, sy), (ch, ty)), ((ch, ty), (tx, ty)):
            d = max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))
            if d < 0.5:
                continue                      # 完全退化的零长段（L 形候选的通道值=锚点 x 时出现）
            if d < floor:
                return True
            if self._seg_hits_rects(p1, p2, ign):
                return True
            if self._seg_crosses_own(p1, p2, e['from'], e['to']):
                return True
        return False

    def _chan_conflict(self, e, ch, ex, en, assigned):
        """通道 ch 是否可用。四类约束，缺一条就出叠线或穿节点：
        a) 同通道上无竖直跨度重叠的边  b) 本边水平段不穿更内侧已占通道的竖直段
        c) 已占边的水平段不穿本边竖直段  d) 本边任一段不穿节点、不短于一格粗格（见 `_path_rejects`）"""
        sx, sy = self.grid.anchor(e['from'], ex, e.get('sdye', 0))   # 手填 sdye 也算进锚点，否则 y 失真
        tx, ty = self.grid.anchor(e['to'], en, e.get('dye', 0))
        if self._path_rejects(e, ch, ex, en):
            return True
        lo, hi = min(sy, ty), max(sy, ty)
        myh = self._hsegs(ex, sx, tx, ch, sy, ty)
        for (o, och, oex, oen) in assigned:
            olo, ohi = self._hs(o)
            if abs(och - ch) < 1 and not (lo > ohi or hi < olo):
                return True
            for (p1, p2) in myh:                      # b) 我穿你
                if min(p1[0], p2[0]) < och < max(p1[0], p2[0]) and olo < p1[1] < ohi:
                    return True
            o_sx, o_sy = self.grid.anchor(o['from'], oex, o.get('sdye', 0))
            o_tx, o_ty = self.grid.anchor(o['to'], oen, o.get('dye', 0))
            for (p1, p2) in self._hsegs(oex, o_sx, o_tx, och, o_sy, o_ty):  # c) 你穿我
                if min(p1[0], p2[0]) < ch < max(p1[0], p2[0]) and lo < p1[1] < hi:
                    return True
        return False

    def _replay_gutter_hints(self, assigned):
        """把已落盘的通道提示（gapx/gutter/channel）用同一套冲突规则复检，过期的丢掉重规划。"""
        # 已落盘的通道提示：先按家族推出端口，再用同一套冲突规则复检。
        # 过期几何（换过列布局/端口）会让折线横穿自身端点、箭头被节点盖住 —— 直接丢弃重规划。
        for o in self.M.edges:
            if o.get('gapx') is not None:
                if o.get('exit') and o.get('entry'):
                    # 落盘的端口组合优先于按列序推（D-28）：gapx 现在也承载 L 形折点，
                    # 按列序硬推会把 (right, top) 的 L 误读成 (right, left) 的 Z。
                    hint = ((o['exit'], o['entry']), o['gapx'])
                else:
                    col_from = self.M.nodes[o['from']]['col']
                    col_to = self.M.nodes[o['to']]['col']
                    hint = ((('right', 'left') if col_from < col_to else ('left', 'right')), o['gapx'])
            elif o.get('gutter') is not None:
                hint = (('left', 'left'), o['gutter'])
            elif o.get('channel') is not None:
                hint = (('right', 'right'), o['channel'])
            else:
                continue
            (ex, en), x = hint
            x = snap(x, self.grid.lattice)        # 手填通道吸到细格
            if self._chan_conflict(o, x, ex, en, assigned):
                # 落盘提示过期（换过列布局/端口）→ 通道作废。端口要不要一起丢，
                # 取决于这条边后面还有没有重规划机会：loop/jumpR 会被 pend 收走重新推端口，
                # 留着旧端口只会干扰重规划；spine/horiz **没有**重规划出口（pend 只收这两类），
                # 丢了端口就只能回落到按 kind 的默认路径——那是手工调过的端口，留着更接近原意。
                for k in ('gapx', 'gutter', 'channel'):
                    o.pop(k, None)
                if o.get('kind') in ('loop', 'jumpR'):
                    o.pop('exit', None)
                    o.pop('entry', None)
                continue
            o['exit'], o['entry'] = ex, en
            assigned.append((o, x, ex, en))

    def _fallback_channel(self, e, lay, assigned, limit):
        """候选全冲突时的兜底：从本边局部右基准最后一档向外找不冲突通道；再失败只避已占通道。"""
        # 兜底：从本边局部右基准的最后一档再往外找一条不冲突的通道。
        # 绝不能回落到已占通道——落回去等于主动制造共线重叠
        # （这正是决策树那类多汇合图失败的成因）。
        sr = lane_step(lay, self.grid.lattice)
        off_r = snap(lay.get('right_channel_offset', 40), self.grid.lattice)
        col_f = self.M.nodes[e['from']]['col']
        col_t = self.M.nodes[e['to']]['col']
        base = snap(self._col_edge(max(col_f, col_t))[1] + off_r, self.grid.lattice)
        x = base + sr * (limit - 1)
        for _ in range(FALLBACK_CHANNEL_TRIES):
            if not self._chan_conflict(e, x, 'right', 'right', assigned):
                return ('right', 'right', x)
            x += sr
        # 全部失败：**从最内侧的通道往外扫**，取第一条"没人占、又不踩硬规矩"的（G84/D-152）。
        # 为什么起点要挪到最内侧：旧写法从 `base + sr*(limit-1)`（最后一档）起步，等于**默认挑最外**，
        # 于是梯级上留下一串空洞——自举 workflow 实测右侧通道 540/600/960/1020/1080，中间空四档，
        # 看起来毫无刻度（作者 2026-09-19 的"右侧出线刻度不守规矩"就是这个）。内→外扫则自然填满。
        # 放宽的是**冲突判定整体**：这一路只查"没人占这条道"与 `_path_rejects`（穿节点 / 短段），
        # (b)(c) 两条"水平段穿竖段"照旧不查——与旧兜底同口径（旧写法也一样不查），共线叠线由
        # validate 事后拦。往图外走总有空位，所以循环有解。
        used = {round(och) for _, och, _, _ in assigned}
        x = base
        for _ in range(FALLBACK_CHANNEL_TRIES * 8):
            if round(x) not in used and not self._path_rejects(e, x, 'right', 'right'):
                return ('right', 'right', x)
            x += sr
        # 极端情况（图外也没有空位）保持旧行为：回到最后一档往外挪，剩余冲突由 validate 报出。
        x = base + sr * (limit - 1)
        while round(x) in used:
            x += sr
        return ('right', 'right', x)

    def _route_pending_edges(self, lay, assigned):
        """给还没通道的 loop/jumpR 边按候选优先级择优分配通道，全冲突时向外兜底。"""
        limit = int(lay.get('max_channels', 8))
        pend = [e for e in self.M.edges
                if e.get('kind') in ('loop', 'jumpR')
                and e.get('gutter') is None and e.get('channel') is None and e.get('gapx') is None]
        pend.sort(key=lambda e: (self._hs(e)[1] - self._hs(e)[0], self._hs(e)[0]))
        for e in pend:
            got = None
            for (ex, en, x) in self._candidates(e, lay):
                if not self._chan_conflict(e, x, ex, en, assigned):
                    got = (ex, en, x)
                    break
            if got is None:
                got = self._fallback_channel(e, lay, assigned, limit)
            ex, en, x = got
            e['exit'], e['entry'] = ex, en
            if ex == en:                          # 左侧或右侧通道族
                e['gutter' if ex == 'left' else 'channel'] = x
            else:                                 # 列间通道
                e['gapx'] = x
            assigned.append((e, x, ex, en))

    def _ensure_gutters(self):
        """一次性通道分配：跨相邻列走列间通道、单列回路走左、长跳走右；**跨度小的先排**（占内道）。

        ⚠ 排序方向是**升序**（短边先占内道），而且这是**实测选出来的**：`_route_pending_edges`
        的 `pend.sort` 自 1ce7e46（2026-09-17）起就是升序，A/B 一比，升序远好于降序——
        自举 49 张表平均绕行 **41% vs 242%**、单张 `build` **102% vs 655%**、画布 2380 vs 3080（G75）。
        机理：同一条梯级只有"竖直跨度不重叠"的边能共用，短边彼此跨度不相交 ⇒ 能叠着坐内道；
        长边先占会把内道全锁死，逼着每一条短边各占一条外道，梯级总数反而变多、横走跟着变长。
        **别按"长边最受约束所以先占"去改成降序**——那个方向试过，烂 6 倍（D-143）。

        分配时同时避让节点与已占通道——这是「边永不穿节点」的第一道保证。"""
        if self._gutter_done:
            return
        self._gutter_done = True
        # **参数来源 = 字典 + 本图的 `layout` 覆盖**（字典文件头那句就是这个契约："默认配置，DSL 可按图覆盖"）。
        # 派生量也住这里——`right_channel_step` 是按**这张图最宽的标签**算出来的档距（table_to_dsl），
        # 不叠这一层的话路由器会按字典下界 40 布线、而标签按 80 排，徽章当场压到邻道的线上（G87/D-155）。
        lay = dict(self.M.cfg.get('layout', {}))
        lay.update(self.M.dsl.get('layout') or {})
        assigned = []
        self._replay_gutter_hints(assigned)
        self._route_pending_edges(lay, assigned)
        # 源锚点错位必须在端口定案**之后**——端口是这里才最终决定的，
        # 提前算会拿默认端口判"同侧"，判错就直接跳过（DECISIONS.md D-15）。
        # **先排源、后排目标**（D-89）：槽位是入边与出边共用的，出边占不到槽位就是掉头折返（硬错），
        # 而入边之间共用槽位只是并线（可读性缺陷）。让不能容忍的那一边先挑。
        stagger_source_anchors(self.M, self.grid, self.ports)
        # 同目标同入口的 dye 错峰射程是**所有边**（不止回路，见 D-89）——也要等端口定案。
        self._stagger_target_dyes(list(self.M.edges))

    def _assign_group_dyes(self, es, to, en, reserved=0):
        """给同一目标同一入口的一批入边在 ±avail 内错开入场 dye：近源先拿靠源一侧的槽位。

        **槽位顺序**里 `0` 必须排在靠源一侧的槽位**之后**（D-89）：判据写作 `d and (d > 0) == below`
        ——少了那个 `d and`，`d = 0` 在 `below=False` 时会落进"源侧"那一档，于是"近源先拿靠源槽位"
        整条反了过来，远源的横段穿近源的竖段（实测 `09c/09d→09e`、`05d/05e→05f` 各一处交叉）。

        `reserved` 是**同一侧还要留给几条错峰出边**的槽位数（`_side_used_slots`）。槽位是入边与出边
        **共用**的：入边把槽位占满时，同侧出边只能落回侧中线＝入边锚点 —— 那就是 `validate` 报的
        "掉头折返"（硬错，D-15/D-61）。所以两件事一起做：档数按 `len(es) + reserved` 算（够就 2×细格
        拉开，不够退 1×细格多榨两档），并把出边已占的槽位**先塞进 `taken`**。
        """
        GL = self.grid.lattice
        # 可用半幅取**该入口所在边的边长**：左右口的 dye 沿 y 挪（受高限制）、上下口沿 x 挪（受宽限制）。
        # 一律取高度会让 160×60 的节点在顶/底口只剩 ±24 可用，白白挤掉槽位。
        w, h = self.grid.sizes.get(self.M.nodes[to]['type'], (160, 60))
        avail = snap((h if en in ('left', 'right') else w) / 2 - 6, GL)
        used = self._side_used_slots(to, en)
        step = 2 * GL if 2 * int(avail // (2 * GL)) + 1 >= len(es) + len(used) else GL
        slots = []
        for k in range(0, int(avail // step) + 1):   # 以中线为对称中心向外展开
            slots.append(step * k)
            if k:
                slots.append(-step * k)
        fixed = {round(e.get('dye', 0), 1) for e in es if e.get('dye')}
        auto = [e for e in es if not e.get('dye')]
        if not auto:
            return
        # 内圈优先（D-28）：**离目标近的先拿靠源一侧的槽位**——"近"要按**末段长度**量，不能按
        # 竖直跨度：跨度相同、水平远近不同的两条边（`03→06` 在左臂外侧、`05→06` 在左臂内侧）会被
        # 跨度判成平局，回头按表序发槽位，于是**远的那条占了外侧槽位**，它的横段正好横穿近的那条
        # 竖段（实测：D-89 的夹具在「臂」上线后就是这一处交叉；跨度判据在单列图上恰好看不出差别）。
        def _rank(e):
            p = self.path(e)                      # 通道已定案：末段长度就是"谁离目标近"
            if len(p) < 2:
                return 0.0
            (x0, y0), (x1, y1) = p[-2], p[-1]
            return abs(x1 - x0) if en in ('left', 'right') else abs(y1 - y0)
        auto.sort(key=_rank)
        taken = set(fixed) | used
        for e in auto:
            sy = self.grid.anchor(e['from'], self.ports(e)[0], e.get('sdye', 0))[1]
            ty = self.grid.anchor(e['to'], en, 0)[1]
            below = sy > ty
            # 槽位从「源侧」向对侧发：源在下方 → 正槽（低 y）在前，上方反之
            order = sorted(slots, key=lambda d: (0 if (d and (d > 0) == below) else 1, abs(d)))
            d = next((v for v in order if v not in taken), None)
            if d is not None:
                e['dye'] = d
                taken.add(d)

    def _side_used_slots(self, nid, side):
        """该侧**出边**已占的锚点槽位（自动与手填都算）——入边错峰必须整片避开（见 `_assign_group_dyes`）。

        入边之间共用槽位只算"并线"（可读性缺陷，槽位不够时只能容忍）；入边与**出边**共用槽位是
        "掉头折返"（`validate` 的硬错）：出边首段把入边末段原路画回，线压过节点边沿上的箭头。
        `sdye` 还是 `None` 的出边就坐在侧中线上，所以这里把 `None` 按 0 算。
        """
        return {round(o.get('sdye') or 0, 1) for o in self.M.edges
                if o['from'] == nid and self.ports(o)[0] == side}

    def _stagger_target_dyes(self, edges):
        """同一目标**同一入口**的入边：在 ±avail 内错开入场 dye，否则尾段会重合纠缠。

        射程是**所有边**，不只是回路（D-89）：两条 `jumpR` 入边（`09c/09d→09e`）同样会在端口前
        并线，且一并能线 190px——`validate` 的共享端点豁免放行它，读者看到的却是"一条线"。
        落在端口上的合流才是合流；提前并线是缺陷（visual-spec §5 第 5 项）。

        **dye 只取细格倍数**：锚点 y = 中线 + dye 而中线在 20k+10 上，dye 落 10 格折点才落 10 格。
        优先 2×细格（20）拉开间距，槽位不够才退 1×细格（**槽位与同侧出边共用**，所以档数要连
        `_side_slots_reserved` 一起算，否则入边占满槽位会把出边逼回中线＝掉头折返）。
        """
        GL = self.grid.lattice
        grouped = {}
        for e in edges:
            grouped.setdefault((e['to'], self.ports(e)[1]), []).append(e)
        for (to, en), es in grouped.items():
            for e in es:                          # 手填 dye 也吸到细格
                if e.get('dye'):
                    e['dye'] = snap(e['dye'], GL)
            if len(es) < 2:
                continue
            self._assign_group_dyes(es, to, en)

