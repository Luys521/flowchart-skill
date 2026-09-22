# -*- coding: utf-8 -*-
"""engine.py — 门面：组合各层为 Engine；渲染器/校验用 `from engine import load` 直接拿。

两种布局由 `dsl.meta.layout` 决定：`flow`（row=流程顺序、col=分支列）用 geometry.Grid + router.Router，
`swimlane`（row=阶段、col=部门）用 swimlane.SwimGrid + lane_router.LaneRouter。
两套 grid/router **接口一致**，下游不必分支；只有渲染器要多画泳道背景，靠 `L.lanes()` 判断。
"""
from pathlib import Path

from geometry import Grid, ceil_to
from router import Router
from lane_router import LaneRouter
from swimlane import SwimGrid
from label import Labeler
from semantics import Syntax

# 数据层：加载 DSL(YAML) 与默认字典，把节点/边整理成可寻址结构，解析画布/主体配置。不负责任何几何与渲染。
DICT_PATH = Path(__file__).parent / 'dictionary.yaml'


class Model:
    def __init__(self, dsl: dict, cfg: dict | None = None):
        self.dsl = dsl
        self.meta = dsl.get('meta') or {}
        self.cfg = cfg if cfg is not None else _load_yaml(DICT_PATH)
        self.nodes = {n['id']: n for n in dsl.get('nodes', [])}
        self.edges = dsl.get('edges', [])
        # 主体配色：DSL meta.subjects 覆盖字典默认
        self.subjects = dict((self.cfg.get('subjects') or {}))
        self.subjects.update(self.meta.get('subjects') or {})
        # 形状尺寸
        self.sizes = {t: tuple(s['size']) for t, s in (self.cfg.get('shapes') or {}).items()}


class Engine:
    def __init__(self, dsl: dict, cfg: dict | None = None):
        """组装引擎：建模型与语法 → 暴露旧 Layout 属性接口 → 按布局建栅格与布线器。"""
        self.model = Model(dsl, cfg)
        self.mode = (dsl.get('meta') or {}).get('layout', 'flow')
        self.syntax = Syntax(self.model)
        self._expose_attrs()
        self._build_layout()

    def _expose_attrs(self):
        """直接暴露旧 Layout 的属性接口。"""
        self.cfg = self.model.cfg
        self.dsl = self.model.dsl
        self.nodes = self.model.nodes
        self.edges = self.model.edges
        self.subjects = self.model.subjects

    def _build_layout(self):
        """按布局建栅格与布线器：泳道走"探布 → 量走廊 → 定案"两趟，流程一趟到位。"""
        if self.mode == 'swimlane':
            self._build(0, explore=True)      # 探布：量出左侧走廊要多宽
            self._reserve_left_corridor()
        else:
            self._build(0)

    def _release_router(self):
        """把上一趟写进边对象的几何改写还回去，这一趟才是干净重解。"""
        old = getattr(self, 'router', None)
        if old is not None:
            old.release()

    def _make_grid_router(self, route_left, explore):
        """按布局造栅格与布线器（泳道专属参数只在泳道模式下用）。"""
        if self.mode == 'swimlane':
            self.grid = SwimGrid(self.model, route_left)
            self.router = LaneRouter(self.model, self.grid, explore)
        else:
            self.grid = Grid(self.model)
            self.router = Router(self.model, self.grid)

    def _expose_grid_metrics(self):
        """建标签器，并把吸附后的尺寸与列中心转发给渲染器。"""
        self.labeler = Labeler(self.router, self.model.cfg)
        # sizes 必须给**吸附后**的（grid.sizes），字典原值会让渲染器与 rect() 错位（越界/重叠）。
        self.sizes = self.grid.sizes
        self.col_x = self.grid.col_x
        self.maxrow = self.grid.maxrow
        self._width = None

    def _build(self, route_left, explore=False):
        """重建栅格与布线器。泳道要走"探布 → 量走廊 → 定案"两趟，流程一趟到位。"""
        self._release_router()
        self._make_grid_router(route_left, explore)
        self._expose_grid_metrics()

    def _corridor_users(self, band):
        """数出探布时**真落进里程碑带**的边；结构已坏（列号越界 / 类型未知）时返回 None。"""
        try:
            return [e for e in self.edges if any(x < band for x, _ in self.router.path(e))]
        except (IndexError, KeyError):
            # 结构已坏（列号越界 / 类型未知）：让 validate 去报那句准备好的中文错，别在这里炸
            return None

    def _reserve_left_corridor(self):
        """左侧走廊的宽度**量**出来，不估（DECISIONS.md D-39）。

        走廊要多宽，取决于"同时有几条长跳要列外竖向通道"——那只有布完才知道。所以探布一次：
        这一趟左族暂从画布左缘起算（旧口径），数出**真落进里程碑带**的边有几条，按这个条数把
        走廊留到带子右边，再干净重解一次定案。

        探布不会把"顺路一步就到的回路"算进来——那些边有更便宜的走法（对角 L / 贴列沿），
        探布时就选了它们，压根不进带（实测对照表 route_left 仍为 0）。
        """
        band = getattr(self.grid, 'stage_w', 0)
        if not band:
            return
        users = self._corridor_users(band)
        if not users:
            return
        step = (self.cfg.get('layout') or {}).get('gutter_step', 40)
        self._build(ceil_to(len(users) * step, self.grid.lattice))

    def _measure_edge_need(self):
        """量出所有折线 x 的最大值；结构已坏（如列号越界 / 节点类型未知）时返回 None。"""
        try:
            return max((x for e in self.edges for x, _y in self.router.path(e)), default=0.0)
        except (IndexError, KeyError):
            # 结构已坏：退回配置宽，让 validate 去报那句准备好的中文错。
            # 若把异常抛出去，报错会变成 IndexError，把诊断信息整个盖掉。
            return None

    @property
    def width(self):
        """画布宽 = max(配置宽, 最外侧通道 + 边距)，吸附粗格。

        通道需求随图而变（多汇合的决策树要更多右通道），没超配置宽的图宽度一字不变。
        """
        if self._width is None:
            need = self._measure_edge_need()
            if need is None:
                # **结构已坏也要缓存**（G71）：原先直接 `return self.grid.width` 而不写 `_width`，
                # 于是每次访问都重跑一遍全部边的测量——坏结构上反而最贵。
                self._width = self.grid.width
                return self._width
            m = (self.cfg.get('layout') or {}).get('channel_margin', 40)
            self._width = max(self.grid.width, ceil_to(need + m, self.grid.node_grid))
        return self._width

    # 方法接口（转发到各层）
    def rect(self, nid):
        return self.grid.rect(nid)

    def path(self, e):
        return self.router.path(e)

    def polarity(self, e):
        return self.router.polarity(e)

    def ports(self, e):
        return self.router.ports(e)

    def label_box(self, e):
        return self.labeler.label_box(e)

    def label_vertical(self, e):
        """边标签是否竖排（跟着竖线走）。取向是 `label_box` 选位时定的，见 `label.py`。"""
        return self.labeler.label_vertical(e)

    def node_lines(self, nid):
        return self.syntax.node_lines(nid)

    def route_text(self, nid):
        return self.syntax.route_text(nid)

    def legend_rect(self):
        return self.grid.legend_rect()

    def legend_width(self):
        """标题/图例块的**宽**（画布顶部居中那块，默认 600）。

        它也是**画布宽的下限**：块居中画在 `width/2`，画布比它窄就会被裁掉——
        `table_to_dsl` 的居中据此定画布宽，两个渲染器据此定位，值只此一份。
        """
        return (self.cfg.get('layout') or {}).get('legend_width', 600)

    def lanes(self):
        """泳道背景信息；流程布局返回 None（渲染器据此决定画不画泳道带）。"""
        fn = getattr(self.grid, 'lanes', None)
        return fn() if fn else None

    def head_band(self, on=True):
        """画布顶部是否预留标题带（HTML 版标题在画布外，故不预留）。

        切带会把整张图的 y 平移 legend_h，**所以所有"从 grid 派生出来的缓存"都得一起作废**：
        `_width` 与三个节点矩形缓存。漏掉矩形缓存是本 skill 出过的最隐蔽的一类错——
        `Router`/`LaneRouter`/`Labeler` 都曾在构造期就把旧坐标的矩形存了下来，
        切换后避让判定拿新坐标的候选去撞旧坐标的矩形，判定全数失准却不报错，
        于是 HTML 版放行了横穿节点的直线，而 drawio 版（不切带）是对的（DECISIONS.md D-19）。
        """
        self.grid.set_head_band(on)
        self.router.invalidate()
        self.labeler.invalidate()
        self._width = None

    def height(self):
        return self.grid.height()


def load(dsl_path):
    """加载 DSL(yaml) + 默认字典 → Engine。

    畸形 DSL 会在深处炸（geometry 取 rect、router 取边端点、semantics 解析 →09 这种引用），
    抛出来的 KeyError/AttributeError 堆栈指向库内部，用户既看不懂也不知道该改 flow.yaml 的哪一格。
    这里统一兜成一句中文——**不静默**：宁可一句人话，也不要二十层 traceback；
    原始异常类型名保留在文案里，排查时不至于信息丢失。
    """
    import yaml
    try:
        dsl = _load_yaml(dsl_path)
    except yaml.YAMLError as e:
        raise ValueError(f'flow.yaml 不是合法 YAML：{e}\n'
                         f'  手工改过的话先查缩进与冒号；否则重跑 table_to_dsl 重新生成') from e
    if not isinstance(dsl, dict):
        raise ValueError(f'flow.yaml 的内容不是一个键值映射（读到 {type(dsl).__name__}）：{dsl_path}\n'
                         f'  空文件或只有注释会读成 None——重跑 table_to_dsl 重新生成')
    try:
        return Engine(dsl)
    except (KeyError, IndexError, AttributeError, TypeError) as e:
        raise ValueError(f'flow.yaml 结构不完整，建不出图：{type(e).__name__}: {e}\n'
                         f'  常见原因：节点缺 row/col、边指向了不存在的节点 id、缺 layout 段。'
                         f'  先跑 validate.py "{dsl_path}" 拿逐项诊断') from e


def _load_yaml(path):
    import yaml
    # utf-8-sig：全仓读文件统一用它（带 BOM 的 yaml 按裸 utf-8 读会让首个键名带上 \ufeff，
    # PyYAML 直接抛"cannot start any token"）。不带 BOM 的文件用它读结果一样，无副作用。
    with open(path, encoding='utf-8-sig') as f:
        return yaml.safe_load(f)
