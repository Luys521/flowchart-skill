# -*- coding: utf-8 -*-
"""render_drawio.py — 流程图 DSL → .drawio（保真协作版）。

显式布局所见即所得；节点输出为 `<object>`；边标签居中 + 白底压线；子流程下钻见 visual-spec §1。
用法：python render_drawio.py flow.yaml [-o out.drawio] [--pages]
退出码：0 = 写出 .drawio；1 = 输入读不了 / 渲染失败（本族只有 0 与 1）。
"""
import argparse
import re
import sys
from pathlib import Path

from engine import load
from semantics import (ARROW_END_SIZE, pending_style, subflow_target, SUB_INSET,
                       SUBFLOW_MARK, NATIVE_MARK, BG_MARK, SUB_MARK)
from artifact import artifact_rel
import hops

FONT = 'Microsoft YaHei'

# 可下钻节点的记号：**框内一道内衬线**（同形状向内缩 `SUB_INSET`，见 D-78）。
# 那个数**不在这里**：三份渲染器共用同一个（`semantics.SUB_INSET`，D-115）。


def esc(s):
    # **刻意自留一份，不抽公共层**：与 `render_html.esc` / `render_svg._esc` 同体，理由是模块层
    # 之间零横向 import（门⑦），而抽到公共层要动 html 的逐字节基线重证——只有一个消费者的抽象
    # 先不抽（同 `render_svg` 文件头那次判断，见 D-39/门⑦）。
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def attr(s):
    return esc(s).replace('\n', '&#10;')


def label_html(L, nid):
    """节点标签 HTML：名称粗体 / 执行者灰 / 行动所需时间橙"""
    t = L.cfg['text']
    parts = []
    for kind, text in L.node_lines(nid):
        style = {'name': f"font-weight:bold;",
                 'executor': f"color:{t['executor']['color']};font-size:{t['executor']['size']}px;",
                 'time': f"color:{t['time']['color']};font-size:{t['time']['size']}px;font-weight:bold;"}[kind]
        parts.append(f'<div style="{style}">{esc(text)}</div>')
    return ''.join(parts)


def shape_style(shp):
    """形状段——**三种形状的唯一出处**（节点本体与子流程叠影共用，别各写一份）。

    胶囊：arcSize=50 = 圆角半径取矮边一半 = 左右半圆。端点仍按**矩形周长**算
    （drawio 的圆角矩形本来就走矩形周长），三份产物才算得出同一个端点（D-74）。
    """
    if shp['shape'] == 'rhombus':
        return 'rhombus;'
    if shp['shape'] == 'stadium':
        return 'rounded=1;arcSize=50;'
    return f"rounded=1;arcSize={shp['arc']};"


def _stroke_of(L, nid):
    """节点的描边色与线型 —— **⚠ 两档的唯一出处**（节点本体与叠影卡共用，别各算一份）。"""
    s = L.subjects.get(L.nodes[nid]['subject']) or L.subjects['默认']
    stroke, dash = s['stroke'], ''
    # ⚠ 推断留痕：`⚠`（有依据）与 `⚠?`（必须拍板）两档视觉不同，取值见 dictionary `pending:`（见 flowtable-spec §2）
    ps = pending_style(L.cfg, L.nodes[nid].get('desc'))
    if ps:
        stroke = ps['stroke'] or stroke
        dash = f'dashed=1;dashPattern={ps["dash"]};' if ps['dash'] else 'dashed=1;'
    return stroke, dash


def node_style(L, nid):
    n = L.nodes[nid]
    s = L.subjects.get(n['subject']) or L.subjects['默认']
    shp = L.cfg['shapes'][n['type']]
    stroke, dash = _stroke_of(L, nid)
    base = (f"whiteSpace=wrap;html=1;strokeWidth=2;fontFamily={FONT};{dash}"
            f"verticalAlign=middle;fillColor={s['fill']};strokeColor={stroke};fontSize={shp['font']};")
    # 末尾那个 `NATIVE_MARK` 是给 `xml_reader` 的**身份戳**（D-85）：回读靠它判"自产 / 外部"。
    # 不能靠 `<object>` 外壳——外部图被 drawio 加过 link / Edit Data 也是 `<object>`，
    # 那样会被误判成自产（既按 cell 顺序排、又把"没有语义"的告警吃掉）。
    return shape_style(shp) + base + NATIVE_MARK + ';'


def sub_ring_style(L, nid):
    """内衬线的 style（见 D-78）：同形状、**无填充**、1px、55% 不透明，落在节点框内。

    末尾的 `flowchartSkillSub=1` 是给 `xml_reader` 的通行证：它是装饰、不是节点。
    少了它，回读会把这一圈线当成一个**真节点**读进流程表（画布上凭空多一个盒子）。
    """
    n = L.nodes[nid]
    stroke, _dash = _stroke_of(L, nid)
    return (shape_style(L.cfg['shapes'][n['type']])
            + f"fillColor=none;strokeColor={stroke};strokeWidth=1;opacity=55;{SUB_MARK};")


def sub_ring_xml(L, nid):
    """内衬线 cell：同形状、向内缩 SUB_INSET（几何与 html/svg 同一口径）。"""
    x, y, w, h = L.rect(nid)
    return (f'        <mxCell id="{esc(nid)}-sub" value="" style="{sub_ring_style(L, nid)}" '
            f'vertex="1" parent="1">\n'
            f'          <mxGeometry x="{round(x + SUB_INSET)}" y="{round(y + SUB_INSET)}" '
            f'width="{w - 2 * SUB_INSET:g}" height="{h - 2 * SUB_INSET:g}" as="geometry" />\n'
            f'        </mxCell>')


def edge_style(L, e):
    pol = L.polarity(e)
    ed = L.cfg['edges'][pol]
    ex, en = L.ports(e)
    # 端口比例**由 anchor() 反算**，不另算一份：非矩形节点（菱形/椭圆）的点会投影到内接曲线上，
    # 比例不再是"0.5 + 偏移/边长"——各算各的就会"我们画在斜边、drawio 画在矩形边"（D-31）。
    exf, eyf = L.grid.port_frac(e['from'], ex, e.get('sdye', 0))
    nxf, nyf = L.grid.port_frac(e['to'], en, e.get('dye', 0))
    # 箭头：与 html/svg 的 marker **同一枚**（见 D-89）。`blockThin` 在导出里只有 8×5.3px，
    # 而 drawio 会把线尾裁到端口前 10px 给箭头让位——箭头一小，那 10px 就成了"线没接上框"。
    # `endFill=1` 实心；`endSize` 的换算（= 边长 - 2）记在 `semantics.ARROW_END_SIZE`。
    s = ('edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;'
         f'exitX={exf};exitY={eyf};entryX={nxf};entryY={nyf};'
         f'endArrow=block;endFill=1;endSize={ARROW_END_SIZE};strokeWidth=2;'
         f'strokeColor={ed["color"]};'
         f'fontSize={L.cfg["text"]["label"]["size"]};fontStyle=1;fontFamily={FONT};'
         f'labelBackgroundColor=#ffffff;labelBorderColor={ed["color"]};')
    if ed['dashed']:
        s += 'dashed=1;'
    # 交叉打跳（D-149）：**drawio 自己就有线跳**——官方边样式表里的 `jumpStyle`
    # （`arc` / `gap` / `sharp`）与 `jumpSize`（交叉处的跳线宽度）。所以三份产物**都能画**：
    # html/svg 走我们自己的半圆（几何在 `geometry.with_hops`），drawio 走这两个键。
    # 只给"在 html/svg 里确实要跳的边"加：mxGraph 是按**每条边自己的样式**决定跳不跳的，
    # 全加会让交叉的两条线同时起跳（四向跳），与另两份产物的观感不一致。
    # ⚠ `jumpSize` 的口径（总宽还是半宽）与"两条边都带样式时谁跳"我没法在本机验证——
    # 没有 drawio 渲染器；这一处观感**要人打开 .drawio 看一眼**（写在 D-149 里）。
    hp, hr, hs = hops.plan(L)
    if hr > 0 and id(e) in hp:
        s += f'jumpStyle={hs if hs in ("arc", "gap", "sharp") else "gap"};jumpSize={int(2 * hr)};'
    return s


def node_xml(L, nid, sub_pages=None):
    """节点 → `<object>`（可下钻时**前面再压一张背面卡**，见 D-75）。`sub_pages` 是 {nid: page_id}。

    可下钻的节点额外拿到 `link="data:pageId=<id>;<标题>"`：drawio 里 **Ctrl/⌘+点击**跳转到那一页。
    这是 visual-spec §1「子 SOP | 页链接」那行一直承诺、但从未实现的东西（此前 `data:pageId` 出现 0 次）。
    **不用普通 `<a href>`**：那是外链，会把用户甩到浏览器；`data:pageId` 是 drawio 的**页内跳转**协议，
    多页共存在同一个 `.drawio` 里，离线也能用。
    """
    n = L.nodes[nid]
    x, y, w, h = L.rect(nid)
    # **《流程表》的语义列一个都不写进图**（D-73）。图上只有三样：id（身份）、label（框里的字）、
    # 形状（画出来的样子）。语义列是**只读呈现**，在 HTML/SVG 里看，不在这里存第二份。
    # 存了会怎样：属性面板里多出一排改不动的副本——drawio 改它，回写仍以流程表为准，
    # 改了等于没改，用户却以为改了。属性不是可编辑入口，是块会骗人的牌子（用户只按"图上能改的"
    # 去改图：加节点、改名字、连线、偶尔调尺寸颜色）。
    # 类型也不写属性：形状已经把类型说全了（矩形=任务 / 菱形=判断 / 胶囊=起止，铁律见 D-74）。
    props = []
    pg = (sub_pages or {}).get(nid)
    if pg:
        props.append(('link', f'data:pageId={pg};{SUBFLOW_MARK} 下钻'))
    attrs = (' ' + ' '.join(f'{k}="{attr(v)}"' for k, v in props)) if props else ''
    # 内衬线**后声明**：drawio 没有 z-order，声明顺序就是层序——后声明的那圈线才压在本体之上
    # （它无填充，所以只是多一道线，不会盖住文字）。
    tail = ('\n' + sub_ring_xml(L, nid)) if pg else ''
    return (f'        <object id="{esc(nid)}" label="{attr(label_html(L, nid))}"{attrs}>\n'
            f'          <mxCell style="{node_style(L, nid)}" vertex="1" parent="1">\n'
            f'            <mxGeometry x="{round(x)}" y="{round(y)}" width="{w}" height="{h}" as="geometry" />\n'
            f'          </mxCell>\n        </object>' + tail)


def edge_xml(L, e, eid):
    full = L.path(e)
    (x0, y0), (x1, y1) = full[0], full[-1]
    pts = []
    if not (e['kind'] in ('spine', 'horiz') and (abs(y0 - y1) < 0.5 or abs(x0 - x1) < 0.5)):
        # 直线边且首尾锚点水平/垂直对齐时无需折点（回路/跳转边不适用）；其余去除连续重复的退化折点
        for p in full[1:-1]:
            if not pts or abs(pts[-1][0] - p[0]) > 0.5 or abs(pts[-1][1] - p[1]) > 0.5:
                pts.append(p)
    arr = ''
    if pts:
        arr = ('\n            <Array as="points">\n'
               + '\n'.join(f'              <mxPoint x="{round(x)}" y="{round(y)}" />' for x, y in pts)
               + '\n            </Array>\n          ')
    # 标签折排（G85）：mxGraph 的边标签是 HTML（`html=1` 已在 style 里），换行就写 `<br>`——
    # 交给 `attr()` 转义成 `&lt;br&gt;`，XML 解析器再还原成真标签（与节点标签 `label_html` 同一路数）。
    # 只折不转：不写 `horizontal=0`（作者 2026-09-22 改口径：竖排撤掉，横排 + 折两排）。
    val = ''
    if e.get('label'):
        val = f'value="{attr("<br>".join(L.label_rows(e)))}"' + ' '
    return (f'        <mxCell id="{eid}" {val}style="{edge_style(L, e)}" edge="1" parent="1" '
            f'source="{esc(e["from"])}" target="{esc(e["to"])}">\n'
            f'          <mxGeometry relative="1" as="geometry">{arr}</mxGeometry>\n'
            f'        </mxCell>')


def lane_cells(L, ln):
    """泳道背景：顶部部门表头 + 角标 + 左侧阶段带 + 部门列底色。

    drawio 没有 z-order，**声明顺序**就是层序——这批 cell 必须排在节点之前，否则底色会盖住节点。
    """
    sw, rl = ln['stage_w'], ln.get('route_left', 0)
    x0, top, head = sw + rl, ln['legend_h'], ln['head_h']
    y0, bot = top + head, L.height()
    subs = ln['subjects'] or {}
    out = [f'        <mxCell id="lane-corner" value="职能部门 →" '
           f'style="text;html=1;align=center;verticalAlign=middle;fontSize=12;fontStyle=1;fontFamily={FONT};" '
           f'vertex="1" parent="1">\n'
           f'          <mxGeometry x="0" y="{round(top)}" width="{round(sw)}" height="{round(head)}" as="geometry" />\n'
           f'        </mxCell>']
    if rl:      # 左走廊补底色，否则里程碑带与首列之间是一条白缝（见 render_html.svg_lanes）
        out.append(f'        <mxCell id="lane-corridor" value="" '
                   f'style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f4f1;strokeColor=none;{BG_MARK};" '
                   f'vertex="1" parent="1">\n'
                   f'          <mxGeometry x="{round(sw)}" y="{round(y0)}" width="{round(rl)}" '
                   f'height="{round(bot - y0)}" as="geometry" />\n'
                   f'        </mxCell>')
    last = len(ln['departments']) - 1
    for cc, dep in enumerate(ln['departments']):
        x = x0 + sum(ln['col_w'][:cc])
        w = (ln['width'] - x) if cc == last else ln['col_w'][cc]     # 末列铺到画布右沿
        sub = subs.get(dep) or {}
        fill, stroke = sub.get('fill', '#ffffff'), sub.get('stroke', '#999999')
        out.append(f'        <mxCell id="lane-col{cc}" value="" '
                   f'style="rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};opacity=40;{BG_MARK};" '
                   f'vertex="1" parent="1">\n'
                   f'          <mxGeometry x="{round(x)}" y="{round(y0)}" width="{round(w)}" '
                   f'height="{round(bot - y0)}" as="geometry" />\n'
                   f'        </mxCell>')
        out.append(f'        <mxCell id="lane-head{cc}" value="{attr(dep or "")}" '
                   f'style="rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
                   f'fontSize=12;fontFamily={FONT};{BG_MARK};" vertex="1" parent="1">\n'
                   f'          <mxGeometry x="{round(x)}" y="{round(top)}" width="{round(w)}" height="{round(head)}" as="geometry" />\n'
                   f'        </mxCell>')
    # 阶段带按**连续同阶段的行区间**合并绘制（槽位模式下同一阶段横跨多行，见 swimlane.lanes）
    spans = ln.get('stage_spans') or [(st, rr, rr) for rr, st in enumerate(ln['stages'])]
    for k, (st, r0, r1) in enumerate(spans):
        y = y0 if r0 == 0 else ln['rowy'][r0]
        y2 = bot if r1 == len(ln['row_h']) - 1 else ln['rowy'][r1] + ln['row_h'][r1]
        out.append(f'        <mxCell id="lane-stage{k}" value="{attr(st or "")}" '
                   f'style="rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f4f1;strokeColor=#cccccc;'
                   f'fontSize=12;fontFamily={FONT};{BG_MARK};" vertex="1" parent="1">\n'
                   f'          <mxGeometry x="0" y="{round(y)}" width="{round(sw)}" height="{round(y2 - y)}" as="geometry" />\n'
                   f'        </mxCell>')
    return out


def render(dsl_path, out_path, ctx=None):
    """DSL → `.drawio`。`ctx['pages']` 是 [(page_id, page_name, dsl_path), …]，本页在最前。

    **硬约束**：不传 `pages` 时输出与单页时代**逐字节相同**——否则所有已存在的 drawio 产物
    会因"多了个没用到的特性"而全体变更（字节不变式与用户的 git diff 都被噪声淹掉）。
    新代码一律走"没有子流程就一行多余的都不输出"。

    `ctx` 是渲染器私有选项的唯一入口（ARCHITECTURE.md 第九节 W2/W3），不传即与旧签名等价。
    本模块认 `pages` / `page_id` / `page_name` 三个键。
    """
    c = ctx or {}
    pages = c.get('pages')
    page_id = c.get('page_id', 'flow-1')
    page_name = c.get('page_name', '流程图')
    xml, n_nodes, n_edges, w, h = _page_xml(dsl_path, page_id, page_name, pages)
    Path(out_path).write_text(xml, encoding='utf-8', newline='\n')
    print(f'生成: {out_path}  节点: {n_nodes}  边: {n_edges}  画布: {w}x{h}'
          + (f'  页数: {len(pages) + 1}' if pages else ''))
    # 成功**显式**返回 0：统一契约里"成功的信号是 0"（见 ARCHITECTURE.md 第九节 W5）。
    # 原先这里什么都不返回（None），而编排层是按 rc 判成败的——两个渲染器信号不一致，
    # 一旦被编排层放进同一个循环，None != 0 就会被误判成失败（实测踩到）。
    # 失败信号仍是抛 ValueError（id 撞车那条），由编排层接住。
    return 0


def _page_xml(dsl_path, page_id, page_name, pages):
    """渲染**一页**（含它自己的子页），返回 (xml 全文, 节点数, 边数, 画布宽, 画布高)。"""
    L = load(dsl_path)
    H = round(L.height())
    cells = [_build_title_cell(L)]
    _ln = L.lanes()
    lane_ids = set()
    if _ln:                       # 泳道背景先入列 → 在节点之下
        lane_xml = lane_cells(L, _ln)
        cells.extend(lane_xml)
        # 背景 cell 的 id 也占着这张图的命名空间。这里从**真正写出去的 XML** 里回取，
        # 而不是另抄一份名字——lane_cells() 再加一种背景时防撞表会自动跟上。
        lane_ids = set(re.findall(r'<mxCell id="([^"]+)"', ''.join(lane_xml)))

    # 子流程页：能被下钻的节点集合。**只有子表产物真存在**才给 link——
    # 指向一个不存在的页 id，Ctrl+点击后 drawio 会静默无反应（比不给更困惑）。
    sub_pages = _sub_pages(L, dsl_path, pages)

    # `0`/`1` 是 mxGraphModel 的根节点、`title` 是标题、`lane-*` 是泳道背景、`<id>-sub` 是子流程
    # 叠影那张背面卡——几个写死的 id 与节点共用同一个命名空间。撞名时 drawio 不报错，只按同名
    # cell 解析，连线挂到错的 cell 上。这里显式报错而不是替用户改名：节点 id 是 writeback / sync
    # 认《流程表》哪一行的唯一键，改了它，"手工摆好的几何同步回表"会静默落错行——比"这是份坏表"难查得多。
    reserved = {'0', '1', 'title'} | lane_ids | {f'{nid}-sub' for nid in sub_pages}
    clash = sorted(set(L.nodes) & reserved)
    if clash:
        raise ValueError('节点 id 与 drawio 结构 id 冲突：' + '、'.join(clash)
                         + '（请改用别的节点编号）')
    cells.extend(_collect_node_cells(L, sub_pages))
    cells.extend(_collect_edge_cells(L, reserved))

    this = _wrap_diagram(page_id, page_name, L.width + 20, H, cells)
    # 子页递归拼在**本页之后**：drawio 读多页 `<diagram>` 就是取根下的顺序，
    # 主图必须在第一个（用户打开文件默认看到它，不该先看到某个零件）。
    tail = _collect_sub_diagrams(page_id, pages)
    header = ('<mxfile host="app.diagrams.net" agent="flowchart-skill/render_drawio.py" version="24.7.17">\n')
    return header + this + tail + '</mxfile>\n', len(L.dsl['nodes']), len(L.edges), L.width + 20, H


def _build_title_cell(L):
    """装配「标题 + 图例说明」cell（合成一个，拖动时标题与图例不会互相错位）。"""
    _, ly, lw, lh = L.legend_rect()
    band = max(lh, 80)
    title = L.dsl['meta']['title']
    # 标题与图例是同一块说明，必须合成一个 cell——拆开时拖其中一个就会与另一个错位。
    sw = ''.join(
        f'<span style="background:{esc(v["fill"])};border:1px solid {esc(v["stroke"])}">&nbsp;&nbsp;&nbsp;&nbsp;</span> {esc(k)}执行　'
        for k, v in (L.dsl.get('meta') or {}).get('subjects', {}).items())
    # 标题 + 主体色块。**没有用法说明那类文案**（与 HTML 版同一条规则，见 visual-spec §1「图例」）：
    # 图例只回答"这是什么图 / 颜色是谁"，两版逐字一致。
    lines = [sw] if sw else []
    # title/主体名是用户文本：html=1 的标签会被 drawio 当 HTML 解析，attr() 只保 XML 层，
    # 文本进标签前必须先过 esc（结构与色值已是安全片段，不重复转义）
    head = (esc(title) + '<br><span style="font-size:11px;font-weight:400">'
            + '<br>'.join(lines) + '</span>')
    return (f'        <mxCell id="title" value="{attr(head)}" '
            f'style="text;html=1;align=center;verticalAlign=middle;fontSize=16;fontStyle=1;fontFamily={FONT};" '
            f'vertex="1" parent="1">\n'
            f'          <mxGeometry x="{round(L.width / 2 - L.legend_width() / 2)}" y="{ly + 8}" '
            f'width="{round(L.legend_width())}" '
            f'height="{band - 16}" as="geometry" />\n'
            f'        </mxCell>')


def _collect_node_cells(L, sub_pages):
    """按 DSL 节点顺序生成每个节点的 `<object>` cell。"""
    return [node_xml(L, n['id'], sub_pages) for n in L.dsl['nodes']]


def _collect_edge_cells(L, reserved):
    """生成每条边的 cell；边 id 与节点/结构 id 共用命名空间，撞名则加后缀避让。

    `reserved` 是本页已占用的 id（`0`/`1`/`title` 与泳道背景）。
    """
    # 边 id 与节点 id 共用命名空间：外部导入的节点 id 可能就叫 e1，撞名则加后缀
    # （xml_reader 认边靠 edge="1"+source/target，不认 id 格式，改 id 不影响回读）。
    out, used_ids = [], set(L.nodes) | reserved
    for i, e in enumerate(L.edges, 1):
        eid, k = f'e{i}', 1
        while eid in used_ids:
            k += 1
            eid = f'e{i}_{k}'
        used_ids.add(eid)
        out.append(edge_xml(L, e, eid))
    return out


def _wrap_diagram(page_id, page_name, page_w, page_h, cells):
    """把 cells 包进 `<diagram>` / `<mxGraphModel>` / `<root>` 外壳。"""
    return ('  <diagram id="' + esc(page_id) + '" name="' + attr(page_name) + '">\n'
            f'    <mxGraphModel dx="1422" dy="798" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
            f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{page_w}" pageHeight="{page_h}" math="0" shadow="0">\n'
            '      <root>\n        <mxCell id="0" />\n        <mxCell id="1" parent="0" />\n'
            + '\n'.join(cells)
            + '\n      </root>\n    </mxGraphModel>\n  </diagram>\n')


def _collect_sub_diagrams(page_id, pages):
    """递归渲染并拼接各子页的 `<diagram>` 段（本页之后，保持 pages 顺序）。"""
    tail = ''
    for pid, pname, ppath in (pages or []):
        if pid == page_id:
            continue
        sub_xml, _, _, _, _ = _page_xml(ppath, pid, pname, None)
        # 只取 `<diagram>…</diagram>` 段：外层 mxfile 只该有一层。
        a, b = sub_xml.find('  <diagram '), sub_xml.rfind('  </diagram>')
        if a >= 0 and b >= 0:
            tail += sub_xml[a:b + len('  </diagram>')] + '\n'
    return tail


def _sub_pages(L, dsl_path, pages):
    """本页里可下钻的节点 → {nid: page_id}。键是 **dsl 路径**（`discover_pages` 产出的就是它），
    不是流程表文件名——子表可能叫 `rendering.md` 而非约定名，按文件名拼拼不准（实测：一对不上，
    页能生成但 `data:pageId` 一个都不出，图上看不出任何异常）。产物不存在的不收录（静默降级）。
    """
    if not pages:
        return {}
    # 节点描述里的 `⊞ parts/渲染.md` → 该子表的 dsl 是 `parts/渲染-flow.yaml`（见 D-51）
    # （产物名是约定的，与流程表文件名无关）。
    base_dir = Path(dsl_path).resolve().parent
    by_dsl = {Path(p).resolve(): pid for pid, _, p in pages}
    out = {}
    for n in L.dsl['nodes']:
        rel = subflow_target(n.get('desc'))
        if rel is None:
            continue
        sub_dsl = (base_dir / artifact_rel(rel, 'yaml')).resolve()
        pid = by_dsl.get(sub_dsl)
        if pid:
            out[n['id']] = pid
    return out


def page_id_for(rel_path):
    """子表 dsl 的**相对路径** → 稳定的页 id（内容无关的固定规则，父子两侧算得一样）。

    取 dsl 而非流程表 `.md`：dsl 是"这一页确实存在"的判据，也是父子两侧唯一的共同键；
    按 `.md` 算的话子表改个文件名页 id 就变、历史链接全断。
    **入参必须是相对路径**：早先 `.resolve()` 后哈希，于是"同一份表换个目录 build"页 id 就变
    （实测 `sub-a35842a727c0` vs `sub-ae090f5ff01d`），**任何含子流程的样例上"build 幂等"都无法成立**。
    """
    import hashlib
    h = hashlib.sha1(str(rel_path).replace('\\', '/').encode('utf-8')).hexdigest()[:12]
    return f'sub-{h}'


def _rel_to(target, base):
    """target 相对 base 的 posix 路径；算不出（跨盘/越界）就退回绝对路径。

    用 `os.path.relpath` 而不是 `Path.relative_to`：后者表达不了 `..`，一跨出 base 就抛
    `ValueError`（这条在 `build._find_parent` 里已经踩过一次）。这里越界不该让渲染整体崩，
    退回绝对路径只是"这一份产物不再可移植"，比崩掉好。
    """
    import os
    try:
        return Path(os.path.relpath(str(target), str(base))).as_posix()
    except ValueError:
        return Path(target).as_posix()


def discover_pages(dsl_path, depth=1):
    """从本表出发，顺着 `⊞` 找出**直接子表** → [(page_id, 页名, 子表 dsl 路径), …]。

    只收**已经存在 dsl** 的子表（没 build 过就渲染不出这一页，硬塞会得到空页）。
    **只铺一跳、不递归**（`depth=1`）：一份流程表只出现在一个文件里，不存在"同一张子表被
    两个 .drawio 各存一份、改一处另一处悄悄过期"的分叉；也与 HTML 侧形状一致（每层一页、一跳一链）。
    `depth` 是可调上限而非递归开关，调大即回到"平铺多层"（想在一屏看全整条链时才用）。
    """
    root = Path(dsl_path).resolve()
    out, seen = [], {root}
    frontier = [(root, 0)]
    while frontier:
        cur, lvl = frontier.pop(0)
        if lvl >= depth:
            continue
        try:
            L = load(str(cur))
        except Exception:
            continue
        for n in L.dsl['nodes']:
            rel = subflow_target(n.get('desc'))
            if rel is None:
                continue
            sub_dsl = (cur.parent / artifact_rel(rel, 'yaml')).resolve()
            if sub_dsl in seen or not sub_dsl.exists():
                continue
            seen.add(sub_dsl)
            # 页名用子表**自己的标题**（用户在 drawio 底部的页标签上看到的应该是"渲染子流程"
            # 而不是目录名 parts）。读不出来就退回目录名——这里不该因为一个标题而整体失败。
            try:
                ptitle = load(str(sub_dsl)).dsl['meta']['title']
            except Exception:
                ptitle = sub_dsl.parent.name
            # **页 id 以 dsl 路径为键**（而不是子表 md 的名字）：dsl 是"这一页确实存在"的
            # 判据，也是 `_sub_pages` 查表用的键，更是 build 侧唯一稳定的锚。早先这里写死
            # `flowtable.md` 再用 `with_name` 救回来，等于**默认所有子表都叫 flowtable.md**——
            # 子表叫 `渲染.md` / `mid.md` 时目录虽对得上，id 的输入却已经是编出来的名字。
            #
            # id 的输入取**相对主表目录**的路径（`parts/结构校验/flow.yaml`），不是绝对路径：
            # 绝对路径会让"换个目录 build"产出不同的页 id，既破坏字节确定性，也让
            # "build 幂等"这条不变式在任何带子流程的样例上必然失败（副本目录路径本就不同）。
            rel_for_id = _rel_to(sub_dsl, root.parent)
            out.append((page_id_for(rel_for_id), ptitle, str(sub_dsl)))
            frontier.append((sub_dsl, lvl + 1))
    return out


def main():
    ap = argparse.ArgumentParser(description='DSL → .drawio')
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    ap.add_argument('--pages', action='store_true',
                    help='把子流程渲染为同一个文件里的附加页（节点 Ctrl+点击下钻）。'
                         '不开时输出与单页时代逐字节相同')
    args = ap.parse_args()
    if not Path(args.input).exists():
        print(f'✗ 找不到输入文件: {args.input}')
        return 1
    out = args.output or str(Path(args.input).with_suffix('.drawio'))
    pages = discover_pages(args.input) if args.pages else None
    render(args.input, out, ctx={'pages': pages})


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
