# -*- coding: utf-8 -*-
"""xml_reader.py — 从 .drawio 回读流程图结构（同步闭环的"读回"入口）。

两种来源都支持：本 SKILL 生成的（`<object>` + style 里带 `NATIVE_MARK`）、外部工具画的（标准
`<mxCell vertex="1">`；类型由 style 与入/出边推断）。
**"自产 / 外部"按 `NATIVE_MARK` 判，不按 `<object>` 外壳**（D-85）：外壳只说明"这个 cell 带自定义
属性"，外部图被 drawio 加过 link / Edit Data 之后也是 `<object>`；只看外壳会把它误判成自产——既不按
几何重排，又把"没有语义、须补进《流程表》"的告警吃掉。三个 drawio 标记的家在 `semantics.py`。
**图里只有三样东西**：名称（框内第一行）、形状/类型、连线；九项语义列一律不读（D-73），
所以两种来源的语义都是空的——语义只住在《流程表》，回写时按 id 取表，取不到的报缺。
几何按中心坐标聚类还原 row/col 与 col_x，使外部图的二维布局能落回产物。
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from geometry import snap
from semantics import (split_branches, BRANCH_SEP, TYPE_EN_ZH,
                       NATIVE_MARK, BG_MARK, SUB_MARK)
from flowtable import C_ID, C_NAME, C_NEXT, C_TYPE, split_row_cells

# 三个 drawio 标记（`NATIVE_MARK` / `BG_MARK` / `SUB_MARK`）的家在 `semantics.py`：
# 渲染器写字面量、回读器另定常量的话，同一个字符串就有两份，改一处必漏一处（D-85）。
TERMINAL_PENDING = '__terminal'     # 端点符（胶囊/椭圆）认不出起止，按入/出边定
TERMINAL_ARC = 40                   # arcSize ≥ 40% 即"整段圆头"（我们的胶囊；见 dictionary.shapes.stadium）
GN = 20                      # 网格粗格：外部坐标回读后吸附到 20 的倍数
FALLBACK_COL_X = 400         # 无几何信息时的默认列中心；列间步距与字典 layout.col_pitch 同口径（460，D-29）
FALLBACK_COL_STEP = 460


# ----------------------------------------------------------------文本工具
def _text(val):
    """属性文本直取。ET.fromstring 已按 XML 规范解码过一次实体（&amp; → & 等），
    这里再做一遍 replace 就是双重解码——`&amp;lt;`（内容里的字面 "&lt;"）会被错解成 `<`。"""
    return val or ''


def _strip_html(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def _label_text(val):
    """节点/边标签 → 纯文本：<br> 先换空格，再剥标签，最后压空白"""
    s = _text(val)
    s = re.sub(r'<br\s*/?>', ' / ', s, flags=re.I)
    s = _strip_html(s)
    return re.sub(r'\s+', ' ', s).strip()


def _label_first_line(val):
    """节点框内可见文字 → 第一行（= 节点名称）。

    可见文字必须优先于隐藏属性——drawio 改框内文字时只动 `label`，属性优先会让改名读不回来。
    """
    s = _text(val)
    s = re.sub(r'</div>|<br\s*/?>', '\n', s, flags=re.I)
    s = _strip_html(s)
    for line in s.splitlines():
        line = line.strip()
        if line:
            return line
    return ''


def _geom(el):
    """取元素的 mxGeometry → (x, y, w, h)；缺失返回全 0"""
    if el is None:
        return (0.0, 0.0, 0.0, 0.0)
    g = el.find('mxGeometry')
    if g is None:
        return (0.0, 0.0, 0.0, 0.0)

    def f(k, d=0.0):
        try:
            return float(g.get(k, d) or d)
        except (TypeError, ValueError):
            return d
    return (f('x'), f('y'), f('width'), f('height'))


def _style_type(style):
    """style → 类型。端点符（胶囊/椭圆）分不出起止，返回待定标记，后续按入/出边判定。

    两种端点符都认：自家产物是**胶囊**（`rounded=1;arcSize=50`），外部 drawio 图按 ANSI 惯例画
    `ellipse`——都是"端点"，不该因为画法不同就当成任务。
    """
    s = style or ''
    if 'rhombus' in s:
        return 'decision'
    m = re.search(r'arcSize=(\d+(?:\.\d+)?)', s)
    if 'ellipse' in s or (m and float(m.group(1)) >= TERMINAL_ARC):
        return TERMINAL_PENDING
    return 'task'


def _shape_of(style):
    """style → 形状名（rounded / rhombus / ellipse）。几何自检按它判"端点落在哪条边界上"——
    这必须从**产物**读，不能从字典反查类型再映射，否则又跟渲染器同源了。

    胶囊报 `rounded`：drawio 的圆角矩形走的就是**矩形周长**，报成曲线会让自检去比内接边界，
    反而与产物不符（D-74）。`ellipse` 只可能来自外部图，保留它是因为那时产物真的画的是椭圆。
    """
    s = style or ''
    if 'rhombus' in s:
        return 'rhombus'
    if 'ellipse' in s:
        return 'ellipse'
    return 'rounded'


def _frac(style, key):
    """从 style 取 `exitX=0.5` 这类端口比例；缺省或非数返回 None"""
    m = re.search(rf'{key}=(-?[\d.]+)', style or '')
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _num(el, key, default=0.0):
    try:
        return float(el.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _median(vals, default):
    vs = sorted(v for v in vals if v and v > 0)
    if not vs:
        return default
    return vs[len(vs) // 2]


# ----------------------------------------------------------------解析
def _node(nid, name, typ, style, geom, native, i):
    """节点字典。**语义列一律为空**——drawio 里不写它们（见 D-73），语义只住在《流程表》。

    回写对已有 id 取流程表、对图里新增的 id 取这里的空值并报缺，所以键位必须齐全：
    "图里没有这个字段"要表现为**空值**，不是 `KeyError`。

    `native` = style 里带 `NATIVE_MARK`（本 SKILL 的渲染器产出，见 D-85）：它决定两件事——
    按 cell 顺序还是按几何重排、以及摘要里要不要报"这张图没有语义"。
    """
    x, y, w, h = geom
    return {'id': nid, 'name': name, 'type': typ,
            # 九项语义/配置列：图里没有（D-73），留键位只为下游统一取值
            'stage': '', 'subject': '', 'executor': '', 'time': '',
            'input': '', 'basis': '', 'output': '', 'desc': '',
            'native': native, 'style': style, 'shape': _shape_of(style),
            'x': x, 'y': y, 'w': w, 'h': h, '_i': i}


def _native_nodes(root_el):
    """自家格式节点：`<object>` 包裹的 `<mxCell>`。返回 (节点列表, 已认领 id 集合)。

    只读两样：框内可见文字与形状。名称以可见文字为准——drawio 双击改名只动 `label`、不动形状，
    形状优先会让改名读不回来；而且多行重排后无法可靠区分"第二行是执行者"还是"用户把名称写成了
    两行"，所以名称只认**第一行**。

    「自产 / 外部」按 style 里的 `NATIVE_MARK` 判，**不按 `<object>` 外壳**（D-85）：外壳只说明
    "这个 cell 带自定义属性"，外部图被 drawio 加过 link / Edit Data 之后也会长成 `<object>`——
    只按外壳判就会把它当自家产物，于是既按 cell 顺序排（而不是按几何）、又把"没有语义、须补进
    《流程表》"的告警吃掉。**外壳仍一律认领**（进 native_ids）：不认领的话，外部那种
    `<object>` 里的 mxCell 不是 root 的直接子元素，`_external_nodes` 找不到它，节点会整个丢掉。
    """
    nodes, native_ids = [], set()
    for i, obj in enumerate(root_el.findall('object')):
        cell = obj.find('mxCell')
        # object 里裹的也可能是**边**（给边加过自定义属性/Edit Data 后 drawio 就这么写）——
        # 边外壳不是节点；不跳过的话 sync 会凭空多出一个假节点，而真边在 _parse_edges 里被读丢
        if cell is None or cell.get('edge') == '1':
            continue
        nid = (obj.get('id') or '').strip()
        if not nid or nid in ('0', '1'):
            continue
        style = cell.get('style') or ''
        native_ids.add(nid)
        # 属性读不到就按形状推（外部工具画的图没有这个属性，见 _style_type）
        typ = (obj.get('节点类型') or '').strip() or _style_type(style)
        nodes.append(_node(nid, _label_first_line(obj.get('label')), typ, style,
                           _geom(cell), NATIVE_MARK in style, i))
    return nodes, native_ids


def _external_nodes(root_el, native_ids):
    """外部标准格式节点：裸 `<mxCell vertex="1">`，跳过标题/图例/泳道底色等装饰元素。"""
    nodes = []
    for i, cell in enumerate(root_el.findall('mxCell')):
        if cell.get('vertex') != '1':
            continue
        nid = (cell.get('id') or '').strip()
        if not nid or nid in ('0', '1') or nid in native_ids:
            continue
        style = cell.get('style') or ''
        # swimlane 是 drawio 原生泳道容器（横向泳道带 / 竖向阶段带），也是背景不是节点；
        # 不跳过的话，外部泳道图会被整条读成假节点，还会连出到泳道的幽灵边。
        # edgeLabel 是 drawio 的**独立边标签**：外部图把「是/否」这类分支字挂在线上时，
        # 它是一个 vertex="1" 的文本框，标签归边不归节点——当成节点就会多出"任务"假节点，
        # 而且它不连任何边，会在摘要里变成一堆孤立节点。自有产物把标签写在边的 value 上
        # （render_drawio.edge_cell），不产生这种 cell，故这条不会误伤。
        if re.match(r'^(text|image|line|swimlane|edgeLabel|shape=image|shape=line)(;|=|$)', style):
            continue                      # 标题/图例/图片/边标签等装饰元素，不是流程节点
        if BG_MARK in style:
            continue                      # 泳道布局的底色带（部门列/阶段带）：是背景，不是流程节点
        if SUB_MARK in style:
            continue                      # 子流程叠影的背面卡：与节点同形状同色的装饰，不是节点
        nodes.append(_node(nid, _label_first_line(cell.get('value')), _style_type(style),
                           style, _geom(cell), False, i))
    return nodes


def _parse_nodes(root_el):
    """解析节点：先 <object>（自有格式），再 <mxCell vertex=1>（外部标准格式）"""
    nodes, native_ids = _native_nodes(root_el)
    nodes += _external_nodes(root_el, native_ids)
    return nodes


def _lanes_bbox(root_el):
    """泳道底色的外包盒（所有带 `flowchartSkillBg=1` 的单元格），没有则 None。

    用来复核"底图有没有铺满"：每个节点都必须落在底色里——底片比节点列平移一个走廊宽（或末列
    只画到 `col_w` 而不是画布右沿）这类错位，从产物上一量就露。
    """
    box = None
    for cell in root_el.findall('mxCell'):
        if cell.get('vertex') != '1' or BG_MARK not in (cell.get('style') or ''):
            continue
        x, y, w, h = _geom(cell)
        box = (x, y, x + w, y + h) if box is None else (
            min(box[0], x), min(box[1], y), max(box[2], x + w), max(box[3], y + h))
    return box


def _band_width(root_el):
    """左侧里程碑带宽度 = 所有 `x=0` 的 vertex 单元格里最宽的那个。

    泳道底图的阶段带与左上角标都从 x=0 起画，节点/图例永远不会落在 x=0（列中心至少 400），
    所以这条判据不会误伤。流程布局没有这类单元格 → 0。
    """
    band = 0.0
    for cell in root_el.findall('mxCell'):
        if cell.get('vertex') != '1':
            continue
        x, _y, w, _h = _geom(cell)
        if x == 0 and w:
            band = max(band, w)
    return band


def _parse_edges(root_el):
    edges = []
    # 边有两种挂法：直挂 <mxCell edge="1">（自家产物）与 <object> 包裹（外部图/手改图里
    # 给边加过自定义属性后的 drawio 写法）。包裹时标签在 object 的 label 上，mxCell 多半没有 value。
    sources = [(c, c.get('value')) for c in root_el.findall('mxCell')]
    for obj in root_el.findall('object'):
        cell = obj.find('mxCell')
        if cell is not None:
            sources.append((cell, obj.get('label') or cell.get('value')))
    for cell, label in sources:
        if cell.get('edge') != '1':
            continue
        s, t = cell.get('source'), cell.get('target')
        if not s or not t:
            continue
        style = (cell.get('style') or '').replace(' ', '')
        # 折点与端口比例：几何自检要拿**产物里真实写下的**坐标复核，不是重跑 router 现算一遍
        pts = []
        for pt in cell.findall('mxGeometry/Array/mxPoint'):
            pts.append((_num(pt, 'x'), _num(pt, 'y')))
        ex, ey = _frac(style, 'exitX'), _frac(style, 'exitY')
        nx, ny = _frac(style, 'entryX'), _frac(style, 'entryY')
        edges.append({'from': s, 'to': t, 'label': _label_text(label),
                      'dashed': 'dashed=1' in style, 'pts': pts,
                      'exit': (ex, ey) if None not in (ex, ey) else None,
                      'entry': (nx, ny) if None not in (nx, ny) else None})
    return edges


def _finalize_types(nodes, edges):
    """端点符节点定起止（胶囊或椭圆，见 `_style_type`）：
    无入边=开始；无出边=结束；都有时，若入边全部来自顺序更后的节点（回环，如"继续→回 01"）
    仍判为开始，否则为任务。"""
    indeg = {n['id']: 0 for n in nodes}
    outdeg = {n['id']: 0 for n in nodes}
    for e in edges:
        outdeg[e['from']] = outdeg.get(e['from'], 0) + 1
        indeg[e['to']] = indeg.get(e['to'], 0) + 1
    order = {n['id']: n.get('_i', i) for i, n in enumerate(nodes)}
    for n in nodes:
        if n['type'] != TERMINAL_PENDING:
            continue
        nid = n['id']
        if indeg.get(nid, 0) == 0:
            n['type'] = 'start'
        elif outdeg.get(nid, 0) == 0:
            n['type'] = 'end'
        else:
            inbound = [e for e in edges if e['to'] == nid]
            all_loop = inbound and all(order.get(e['from'], 0) > order.get(nid, 0) for e in inbound)
            n['type'] = 'start' if all_loop else 'task'


# ----------------------------------------------------------------网格推断
def _cluster(values, tol):
    """把一维坐标聚成层：返回 {索引: 层号}（按坐标升序）"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    assign, cur, layer = {}, None, -1
    for i in order:
        if cur is None or values[i] - cur > tol:
            layer += 1
            cur = values[i]
        assign[i] = layer
    return assign


def assign_grid(nodes):
    """按中心坐标聚类推断 row/col 与列中心 col_x（容差：行 0.6×高中位数、列 0.9×宽中位数）。

    外部图的坐标是自由值（442、710 这类），col_x 必须**吸附到粗格**再落盘，
    否则会把整张图的 x 全带偏半格。"""
    cy = [n['y'] + n['h'] / 2 for n in nodes]
    cx = [n['x'] + n['w'] / 2 for n in nodes]
    if all(v == 0 for v in cy) and all(v == 0 for v in cx):
        # 无几何信息（节点缺 mxGeometry，_geom 全 0）：退化为单列顺序排布
        for i, n in enumerate(nodes):
            n['row'], n['col'] = i, 0
        return {'col_x': [FALLBACK_COL_X], 'rows': len(nodes)}

    h_med = _median([n['h'] for n in nodes], 60)
    w_med = _median([n['w'] for n in nodes], 160)
    rmap = _cluster(cy, max(h_med * 0.6, 30))
    cmap = _cluster(cx, max(w_med * 0.9, 60))
    for i, n in enumerate(nodes):
        n['row'], n['col'] = rmap[i], cmap[i]
    ncols = max(cmap.values()) + 1
    sums = [0.0] * ncols
    cnts = [0] * ncols
    for i, n in enumerate(nodes):
        sums[cmap[i]] += cx[i]
        cnts[cmap[i]] += 1
    col_x = [snap(sums[c] / cnts[c], GN) if cnts[c]
             else FALLBACK_COL_X + FALLBACK_COL_STEP * c for c in range(ncols)]
    return {'col_x': col_x, 'rows': max(rmap.values()) + 1}


# ----------------------------------------------------------------入口
def _root_model(xml_content):
    """XML 文本 → (mxGraphModel 元素, root 元素, 页数)。解析不了抛 ValueError（带原因）。"""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f'不是合法的 drawio XML: {e}') from e
    model = root.find('.//mxGraphModel')
    # 多页 .drawio 只在首张 <diagram> 上解析：本工具自产文件主页排在最前（行为正确），
    # 但外部文件的页序不保证——不把"还有 N-1 页没读"说出来，人会把漏掉的页当成"图被读坏了"，
    # 或者拿第 1 页的差异去改整份流程表。这里只**注明**不合并：合并各页会把跨页的边拼成
    # 一张不存在的拓扑（页与页之间没有父子关系，画在同一页上的两个节点未必相连）。
    pages = len(root.findall('.//diagram')) or 1
    if model is None:
        # drawio 默认存盘是压缩格式（<diagram> 内为 base64+deflate），本工具只读未压缩 XML。
        # 静默返回空图会让下游报"缺开始/结束"这类误导性错误——把真实原因说清楚。
        if root.tag == 'mxfile' and root.find('diagram') is not None:
            raise ValueError('该 .drawio 是压缩格式（<diagram> 内为 base64+deflate），'
                             '本工具只支持未压缩 XML：在 drawio 里用「另存为 → 未压缩 .drawio」后重试')
        if root.tag != 'mxGraphModel':
            # 既不是 mxfile 也不是 mxGraphModel（拿错了文件、或是别的 XML）：往下走会解析出一张
            # **空图**，于是下游报"缺开始节点/缺结束节点"——那句错把人引到完全错误的方向。
            raise ValueError(f'这不像 drawio 的图文件：根元素是 <{root.tag}>'
                             f'（应为 <mxfile> 或 <mxGraphModel>）。请确认选的是 .drawio 文件')
        model = root
    root_el = model.find('root')
    if root_el is None:
        root_el = ET.Element('root')
    return model, root_el, pages


def _order_nodes_and_edges(nodes, edges, native):
    """外部图按几何从上到下、从左到右重排，自有图按原始顺序；并丢掉两端不存在的边。"""
    if not native:                             # 外部图：按几何从上到下、从左到右重排
        nodes.sort(key=lambda n: (n['row'], n['col'], n['y'], n['x']))
    else:
        nodes.sort(key=lambda n: n['_i'])
    ids = {n['id'] for n in nodes}
    edges = [e for e in edges if e['from'] in ids and e['to'] in ids]
    for n in nodes:
        n.pop('_i', None)
    return nodes, edges


def read(xml_content: str) -> dict:
    """解析 drawio XML → {title, nodes, edges, source, grid, pages}。解析不了抛 ValueError（带原因）。"""
    model, root_el, pages = _root_model(xml_content)
    nodes = _parse_nodes(root_el)
    edges = _parse_edges(root_el)
    _finalize_types(nodes, edges)
    native = bool(nodes) and all(n['native'] for n in nodes)
    grid = assign_grid(nodes)
    nodes, edges = _order_nodes_and_edges(nodes, edges, native)
    return {'title': '', 'nodes': nodes, 'edges': edges,
            'source': 'native' if native else 'external', 'grid': grid, 'pages': pages,
            'band': _band_width(root_el), 'lanes': _lanes_bbox(root_el),
            'page': (_num(model, 'pageWidth'), _num(model, 'pageHeight'))}


# ----------------------------------------------------------------几何回读
def _frac_pt(rect, frac):
    """端口比例 → 绝对坐标。drawio 的 exitX/exitY 是**外接矩形的比例**，缺省即边中点。"""
    x, y, w, h = rect
    fx, fy = frac if frac else (0.5, 0.5)
    return (x + fx * w, y + fy * h)


def geometry(data: dict) -> dict:
    """读回结果 → 几何表 {nodes: {id: {rect, shape}}, edges: [{from, to, pts}], canvas}。

    `pts` 是**产物里真实写下的**那条折线：起点/终点由端口比例反算，中间是 `Array as="points"` 里的折点。
    门禁据此复核，而不是重跑一遍 router——那是同一个实现，只能"同错同对"（见 DECISIONS.md D-32）。
    """
    nodes = {n['id']: {'rect': (n['x'], n['y'], n['w'], n['h']),
                       'shape': n.get('shape') or 'rounded'} for n in data['nodes']}
    edges = []
    for e in data['edges']:
        if e['from'] not in nodes or e['to'] not in nodes:
            continue
        pts = ([_frac_pt(nodes[e['from']]['rect'], e.get('exit'))]
               + [tuple(p) for p in (e.get('pts') or [])]
               + [_frac_pt(nodes[e['to']]['rect'], e.get('entry'))])
        edges.append({'from': e['from'], 'to': e['to'], 'pts': pts,
                      'exit': e.get('exit'), 'entry': e.get('entry')})
    pw, ph = data.get('page') or (0.0, 0.0)
    if pw <= 0 or ph <= 0:                     # 无页面尺寸（外部图）→ 退化成内容外包，画布检查恒过
        pw = max((v['rect'][0] + v['rect'][2] for v in nodes.values()), default=0.0)
        ph = max((v['rect'][1] + v['rect'][3] for v in nodes.values()), default=0.0)
    return {'nodes': nodes, 'edges': edges, 'canvas': (pw, ph),
            'band': data.get('band') or 0.0, 'lanes': data.get('lanes'),
            'source': data.get('source', '')}


# ----------------------------------------------------------------输出：拓扑摘要
def _brief_index(nodes, edges):
    """节点序号表 + 出边索引（摘要按文档顺序、分支按目标序号排）。"""
    order = {n['id']: i for i, n in enumerate(nodes)}
    by_from = {}
    for e in edges:
        by_from.setdefault(e['from'], []).append(e)
    return order, by_from


def _brief_node_lines(nodes, order, by_from):
    """一行一节点（判断/多分支缩进列出各分支）。"""
    out = []
    for n in nodes:
        tag = TYPE_EN_ZH.get(n['type'], n['type'])
        head = f"[{tag}] {n['id']} {n['name']}"
        es = sorted(by_from.get(n['id'], []), key=lambda e: order.get(e['to'], 999))
        if n['type'] == 'decision' or len(es) > 1:
            out.append(head)
            for k, e in enumerate(es):
                bar = '└' if k == len(es) - 1 else '├'
                back = '回 ' if order.get(e['to'], 999) < order.get(n['id'], 0) else ''
                out.append(f"    {bar} {e['label'] or '(无标签)'} → {back}{e['to']}")
        elif len(es) == 1:
            e = es[0]
            back = '回 ' if order.get(e['to'], 999) < order.get(n['id'], 0) else ''
            out.append(f"{head} → {back}{e['to']}")
        else:
            out.append(head + ('   ← 孤立节点' if n['type'] != 'end' else ''))
    return out


def brief(data: dict) -> str:
    """AI/人可读的拓扑摘要：一行一节点，判断/多分支节点缩进列出各分支。

    **只说图里有的东西**——名称、类型、连线（D-73）。语义列图里不存，所以这里既不显示、
    也不报"缺"；只有外部图整张都没有语义，才提醒按流程表补全（那是导入流程的起点）。
    """
    nodes, edges = data['nodes'], data['edges']
    order, by_from = _brief_index(nodes, edges)
    out = [f"来源格式: {data['source']}   节点: {len(nodes)}  边: {len(edges)}"]
    if (data.get('pages') or 1) > 1:
        # 多页只解析了第 1 页（见 read()）：这话必须写在摘要顶部，否则下面少掉的 N-1 页
        # 会被当成"读回失败"或"节点被删了"，排查方向整个跑偏。
        out.append(f"⚠ 该 .drawio 共 {data['pages']} 页，本次仅读第 1 页"
                   f"（其余 {data['pages'] - 1} 页未参与核对；要读别的页请先在 drawio 里把它移到第一页）")
    out += _brief_node_lines(nodes, order, by_from)
    if data['source'] == 'external':
        # 判据是 style 里的 `NATIVE_MARK`（D-85），不是"有没有 `<object>` 外壳"：外部图被 drawio
        # 加过 link / Edit Data 也会长成 `<object>`，只看外壳就会把这条告警静默吃掉。
        out.append(f"⚠ 这张图来自外部工具：{len(nodes)} 个节点都没有语义（输入 / 依据 / 输出 / 执行主体 /"
                   " 执行者 / 行动所需时间），先补进《流程表》，补不出处的以 ⚠ 标出")
    return '\n'.join(out)


# ----------------------------------------------------------------输出：差异对比
def _next_of(nid, by_from, order):
    bs = []
    for e in sorted(by_from.get(nid, []), key=lambda x: order.get(x['to'], 999)):
        pre = (e['label'] + '→') if e['label'] else '→'
        back = order.get(e['to'], 999) < order[nid]
        bs.append(pre + ('回 ' if back else '') + e['to'])
    return f' {BRANCH_SEP} '.join(bs) if bs else '—'


def _target_id(raw, known=None):
    """从「回 10 重编」「n2」这类文本里取出目标节点 id：
    先整体匹配，再按已知 id 做前缀匹配（长 id 优先），最后回退到编号正则。"""
    raw = re.sub(r'^回\s*', '', raw or '').strip()
    if known:
        if raw in known:
            return raw
        for k in sorted(known, key=len, reverse=True):
            if raw.startswith(k):
                return k
    m = re.match(r'\d+[a-zA-Z]?', raw)
    return m.group(0) if m else raw


def _parse_next_cell(s, known=None):
    out = set()
    for p in split_branches(s):
        p = p.strip()
        if not p or p in ('—', '-', '无'):
            continue
        m = re.match(r'^(.*?)(?:→|->)(.+)$', p)
        if m:
            out.add((m.group(1).strip(), _target_id(m.group(2), known)))
        else:
            out.add(('', _target_id(p, known)))
    return out


def _diff_table_rows(ft_path):
    """现有流程表 → {节点id: {name, type, next}}。

    只取**图里能说的那三样**（名称 / 类型 / 走向）：语义列图里根本没有（D-73），
    拿空值去比表里的「依据」，会把每一行都报成改动，真信号就淹在噪声里了。
    """
    from flowtable import parse_table
    lines = Path(str(ft_path)).read_text(encoding='utf-8-sig').splitlines()
    _t, _m, rows = parse_table('\n'.join(lines))
    orig = {}
    for c in rows:
        c = split_row_cells(c)
        orig[c[C_ID].strip()] = {'name': c[C_NAME], 'type': c[C_TYPE], 'next': c[C_NEXT]}
    return orig


def _diff_added_removed(orig, cur):
    """新增 / 删除节点清单；新增的节点只有名称与连线，缺的语义列在这里点名。"""
    out, added = [], []
    for nid in cur:
        if nid not in orig:
            added.append(nid)
            out.append(f"+ 新增节点 {nid}「{cur[nid]['name']}」"
                       f"({TYPE_EN_ZH.get(cur[nid]['type'], cur[nid]['type'])})")
    for nid in orig:
        if nid not in cur:
            out.append(f"- 删除节点 {nid}「{orig[nid]['name']}」（图中已不存在）")
    if added:
        out.append(f'⚠ 新增的 {len(added)} 个节点在图里只有名称与连线：输入 / 依据 / 输出 / '
                   '执行主体 / 执行者 / 行动所需时间 / 项目运作阶段 / 节点描述 都是空的，'
                   '回写后须在《流程表》里补齐')
    return out


def _diff_changed(orig, cur, by_from, order):
    """共有节点的差异清单：名称、类型、分支走向——图里只有这三样可动（D-73）。"""
    out = []
    for nid in cur:
        if nid not in orig:
            continue
        o, c = orig[nid], cur[nid]
        if (o['name'] or '').strip() != c['name']:
            out.append(f"~ {nid} 名称：「{o['name']}」→「{c['name']}」")
        if (o['type'] or '').strip() != TYPE_EN_ZH.get(c['type'], c['type']):
            out.append(f"~ {nid} 类型：{o['type']} → {TYPE_EN_ZH.get(c['type'], c['type'])}")
        on = _parse_next_cell(o['next'], set(cur))
        cn = _parse_next_cell(_next_of(nid, by_from, order), set(cur))
        if on != cn:
            # 方向标注（D-45）：只写"新增/删除出边"会把因果讲反——那句话读起来像
            # 「图里新接了一条线」，而现实往往是「流程表已改成 X、图还是过期快照」。
            # 两栏并排摆出「表 → 谁 ｜ 图 → 谁」，由人裁决，不替人预设哪边是新的。
            for lab, tgt in sorted(cn - on):
                out.append(f"= {nid} 分支「{lab or '(无标签)'}」：流程表 → (无此分支) ｜ 图 → {tgt}")
            for lab, tgt in sorted(on - cn):
                out.append(f"= {nid} 分支「{lab or '(无标签)'}」：流程表 → {tgt} ｜ 图 → (无此分支)")
    return out


def diff(data: dict, ft_path) -> str:
    """读回结果 vs 现有流程表 → 差异清单"""
    orig = _diff_table_rows(ft_path)
    order = {n['id']: i for i, n in enumerate(data['nodes'])}
    by_from = {}
    for e in data['edges']:
        by_from.setdefault(e['from'], []).append(e)
    cur = {n['id']: n for n in data['nodes']}
    out = _diff_added_removed(orig, cur) + _diff_changed(orig, cur, by_from, order)
    return '\n'.join(out) if out else '✓ 与流程表一致，无差异'


# ----------------------------------------------------------------CLI
def _print_json(data):
    """--json：输出结构化 JSON。"""
    print(json.dumps(data, ensure_ascii=False, indent=1))


def _print_grid(data):
    """--grid：输出坐标推断的 row/col。"""
    print(f"来源: {data['source']}  行: {data['grid']['rows']}  列中心 x: {data['grid']['col_x']}")
    for n in data['nodes']:
        print(f"  row {n['row']:<3} col {n['col']:<3} {n['id']}  {n['name']}")


def _cmd_diff(a, data):
    """--diff：结构差异，再补一次"回写结果 vs 原文"的文件级复核。"""
    ft = Path(a.diff)
    # 与 drawio_path 同一口径：先查存在再读。diff() 内部是裸 read_text，缺文件抛
    # FileNotFoundError，而 main 只捕 ValueError——同一类"文件找不到"，在 drawio 侧给中文
    # 提示、在流程表侧甩 traceback，口径不一会让使用者以为是自己把流程表写坏了。
    if not ft.exists():
        print(f'✗ 找不到流程表: {ft}')
        return 1
    print(diff(data, ft))
    print('--- 文件级复核 ---')
    # 上面那句是集合比较，看不见分支顺序/尾注/「回」/换行——补一次文件级比对（与 sync 同一件事）。
    try:
        import contextlib
        import io
        import tempfile
        from writeback import write as _wb, compare_bytes
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'flowtable.sync.md'
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _wb(a.drawio_path, str(ft), str(tmp))
            # **回写那一步的输出要露出来**：它含"回写结果未过结构校验"的 ✗、"分支走向冲突"的
            # 告警、以及"缺主体/执行者"的 ⚠——全被 redirect 吞掉就等于这次文件级复核只做了
            # 一半，而读者以为它做全了。只挑 ✗/⚠ 两类（✓ 与统计留在回写命令自己的输出里）。
            for line in buf.getvalue().splitlines():
                if line.lstrip().startswith(('✗', '⚠')):
                    print('   ', line.strip())
            same, lines = compare_bytes(str(ft), tmp)
        if same:
            print('✓ 逐字节一致（回写结果与原文完全相同）')
        else:
            print(f'ℹ 流程表有 {len(lines)} 行差异（集合 diff 看不见的：分支顺序/尾注/「回」/换行/BOM）：')
            for line in lines[:24]:
                print('   ', line)
            if len(lines) > 24:
                print(f'    …（共 {len(lines)} 行）')
    except (ValueError, OSError) as e:
        # 文件级复核是 diff 之后的补充视角，失败只跳过它，不拖垮整个命令（上面已给过拓扑差异）
        print(f'（文件级复核跳过：{type(e).__name__}: {e}）')
    return 0


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='从 .drawio 回读流程图结构（兼容外部 drawio）')
    ap.add_argument('drawio_path')
    ap.add_argument('--json', action='store_true', help='输出结构化 JSON')
    ap.add_argument('--grid', action='store_true', help='输出坐标推断的 row/col')
    ap.add_argument('--diff', metavar='flowtable.md', help='与现有流程表对比差异')
    a = ap.parse_args()

    src = Path(a.drawio_path)
    if not src.exists():
        print(f'✗ 找不到 drawio 文件: {src}')
        return 1
    # utf-8-sig：带 BOM 的文件按裸 utf-8 读，首字符 \ufeff 会让 ET.fromstring 直接抛解析错
    try:
        data = read(src.read_text(encoding='utf-8-sig'))
    except ValueError as e:
        print(f'✗ {e}')
        return 1
    if a.json:
        _print_json(data)
        return 0
    if a.grid:
        _print_grid(data)
        return 0
    if a.diff:
        return _cmd_diff(a, data)
    print(brief(data))
    return 0


if __name__ == '__main__':
    sys.exit(main())
