# -*- coding: utf-8 -*-
"""render_svg.py — DSL → **朴素可编辑的 `.svg`**（一条独立产物，见 ARCHITECTURE.md 9.9）。

## 它是什么、不是什么

是：与 html / drawio **平级的兄弟产物**——同样从 `<流程名>-flow.yaml` 渲染。
浏览器能直接打开，Inkscape / Illustrator 能改，不依赖任何专用软件。

**不是**：不是 html 的输入。让 html 消费 svg 会把 svg 变成"几何的事实输入"，
那就等于把事实源从 yaml 挪到 svg（与已定的 **X** 冲突）。所以这里**只读 yaml、只写 svg**。

## 为什么自己发射，而不是复用 render_html 的场景

`render_html` 里那套搭 SVG 的代码是私有的，而分层门禁规定**模块层之间不许有代码依赖**
（协作走产物）⇒ 不能 import。抽到公共层是"正确但更大"的一步：它要动 render_html，
html 的逐字节基线得重新证；而**现在只有一个消费者**，抽公共层的收益还看不见。
⇒ 先自己发射（代价是这段发射逻辑与 render_html 各存一份），等真有第二个消费者再抽。

## 元素约定必须与 render_html 完全一致

`manifest` 的反解器是**按这套约定读的**（`read_html` / `_html_shape` / `_html_edges` /
`_html_canvas_bands`），差一个属性或换一下属性顺序，产物就会"读不出来"或"少几个节点"。
本模块的 `_emit_node` / `_emit_edge` / `_emit_lanes` 是与那些正则**成对**的，改动必须两边一起看。

**内容也一样**（D-86）：节点三行文字（`t1` / `tm` / `tt2`）、`⚠` 两档虚线描边、边标签
（`<g class="elab">`）三样此前这份产物**都不画**——单独发出去读不出分支条件，也看不出哪几处
是 AI 推断。"朴素"指没有交互与动画，不是内容可以少。

## 画布口径与 html 相同（不是"朴素"到自成一套）

`head_band(False)` + `W=L.width` + `H=round(L.height())`：与 `render_html._view_svg` 一字不差。
两个后果都是要的：① 泳道底图画到 `L.height()`，画布就得有 `L.height()` 高，否则底图被 viewBox
裁掉（实测差 30px）；② svg 与 html 的节点坐标于是**完全重合**，两边的几何表可以直接对照。
`head_band(False)` 必须在 `L.lanes()` **之前**调——`legend_h` 会改写 `origin_y`/`rowy`，
顺序反了量到的是带标题带的那一套坐标（html 侧同样在 `_load_render_context` 里先切带）。
退出码：0 = 写出 .svg；1 = 输入读不了 / 渲染失败。
"""
from pathlib import Path

from artifact import artifact_rel
from engine import load
from geometry import arc_px, with_hops
import hops
from semantics import arrow_markers, pending_style, subflow_target, SUB_INSET

# 可下钻节点的记号：**框内一道内衬线**（同形状内缩 `SUB_INSET`，见 D-78）。
# 框内是关键：出了框就要和端口、相邻墨迹、包围盒/网格打交道；框内谁都不碰。
# 那个数**不在这里**：三份渲染器共用同一个（`semantics.SUB_INSET`，D-115）。


# 与 render_html 同口径的数值格式化（整数不带小数点，避免产物里出现 `400.0`）。
def _fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f'{v:g}'


def _defs(cfg):
    """本产物的 `<defs>`：只有箭头 marker（没有 html 那份流光模糊——这份产物不带动画）。

    与 `render_html._defs` 共用 `semantics.arrow_markers`（见 D-89）：两份产物必须长得一样，
    此前这里和 render_html 各写了一份同款字面量，连 marker 的 id 都各写一遍。
    """
    return f'<defs>{arrow_markers(cfg)}</defs>'


def _esc(t):
    return (str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _shape_xml(shp, w, h, shp_name, style, cls='shape', dx=0.0, dy=0.0):
    """形状画在**局部坐标**（以节点中心为 0,0）——`manifest._html_shape` 就是这么读的。

    `cls`/`dx`/`dy` 只给**子流程叠影**用（同形状再画一张、向右下平移，见 D-75）：
    类名必须换掉——反解器只认 `class="shape"`，叠影若也叫 shape 就会被当成节点本体。
    """
    if shp_name == 'rhombus':
        pts = (f'{_fmt(dx)},{_fmt(-h / 2 + dy)} {_fmt(w / 2 + dx)},{_fmt(dy)} '
               f'{_fmt(dx)},{_fmt(h / 2 + dy)} {_fmt(-w / 2 + dx)},{_fmt(dy)}')
        return f'<polygon class="{cls}" points="{pts}" {style}/>'
    if shp_name == 'stadium':
        # 胶囊（开始/结束）：圆角半径取半高 = 左右半圆；几何仍按矩形（见 D-74）
        return (f'<rect class="{cls}" x="{_fmt(-w / 2 + dx)}" y="{_fmt(-h / 2 + dy)}" width="{_fmt(w)}" '
                f'height="{_fmt(h)}" rx="{_fmt(h / 2)}" {style}/>')
    # 圆角口径以 drawio 的 `arcSize`（占短边的百分比）为准 ⇒ 这里必须换算成像素（D-86）。
    arc = arc_px(shp, w, h)
    rx = f' rx="{_fmt(arc)}"' if arc else ''
    return (f'<rect class="{cls}" x="{_fmt(-w / 2 + dx)}" y="{_fmt(-h / 2 + dy)}" '
            f'width="{_fmt(w)}" height="{_fmt(h)}"{rx} {style}/>')


def _drillable(L, dsl_path):
    """声明了 `⊞` 且**子表产物真的存在**的节点 → {节点id}。

    判据与 `render_drawio._sub_pages` 同源（子表 `<名>-flow.yaml` 在不在），产物不存在就不画叠影、
    不报错——静默降级是既定纪律（见 D-47）。**这段条件刻意各渲染器自留一份**：分层门禁不许
    模块之间横向 import（见文件头），抽公共层要动 html 的逐字节基线，而现在只有两处消费者。

    与 html 的差别只有一处、且是有意的：html 还要求那份 DSL **读得动**（`render_html.collect_views`
    在 load 失败时撤回入口），因为 html 的记号是**可点的入口**，点了没反应比不画更糟；
    svg 没有可点入口，只要"这个节点有子表"这件事为真就该画 ⇒ 按产物存在性判就够了（D-86）。
    """
    base = Path(dsl_path).resolve().parent
    out = set()
    for n in L.dsl['nodes']:
        rel = subflow_target(n.get('desc'))
        if rel is not None and (base / artifact_rel(rel, 'yaml')).exists():
            out.add(n['id'])
    return out


def _emit_node(L, n, drillable=()):
    x, y, w, h = L.rect(n['id'])
    cx, cy = x + w / 2, y + h / 2
    shp = L.cfg['shapes'].get(n['type'], {})
    col = L.cfg['subjects'].get(n.get('subject'), L.cfg['subjects']['默认'])
    # ⚠ 推断留痕（`⚠` / `⚠?` 两档）与另两份产物**同一口径**：颜色 + 虚线节奏都取自
    # dictionary `pending:`，两档必须画得不一样（D-46）。此前这份产物**一个都不画**——
    # 单独把 svg 发出去，读者看不出哪几处是 AI 推断、哪几处必须自己拍板（D-86）。
    stroke, dash = col['stroke'], ''
    ps = pending_style(L.cfg, n.get('desc'))
    if ps:
        stroke = ps['stroke'] or stroke
        dash = f' stroke-dasharray="{ps["dash"]}"' if ps['dash'] else ''
    style = f'fill="{col["fill"]}" stroke="{stroke}" stroke-width="2"{dash}'
    t = L.cfg['text']
    out = [f'<g class="ndg" data-id="{_esc(n["id"])}" transform="translate({_fmt(cx)},{_fmt(cy)})">']
    if n['id'] in drillable:
        # 子流程记号（D-78）：同形状、向内缩 2px 的一圈细线，描边色跟随本体（含 ⚠ 换过的色）。
        # **没有动画**——这份产物是静态中间态，装饰只住在 HTML 里。
        i = SUB_INSET
        out.append(_shape_xml(shp, w - 2 * i, h - 2 * i, shp.get('shape'),
                              f'fill="none" stroke="{stroke}" stroke-width="1" opacity="0.55"',
                              cls='sub-ring'))
    out.append(_shape_xml(shp, w, h, shp.get('shape'), style))
    # 三行文字与 html 同一口径（`semantics.node_lines`：判断节点只放名称，其余 名称 / 执行者 /
    # 行动所需时间）：class 名 t1 / tm / tt2 与 html 逐字一致，行距也按行数居中（step 16）。
    lines = L.node_lines(n['id'])
    classes = {'name': ('t1', t['name']), 'executor': ('tm', t['executor']),
               'time': ('tt2', t['time'])}
    step, base = 16, -(len(lines) - 1) * 16 / 2 + 4
    for k, (kind, text) in enumerate(lines):
        cls, spec = classes[kind]
        weight = ' font-weight="bold"' if spec['bold'] else ''
        out.append(f'<text class="{cls}" x="0" y="{_fmt(base + k * step)}" text-anchor="middle"'
                   f' fill="{spec["color"]}" font-size="{spec["size"]}"{weight}>'
                   f'{_esc(text)}</text>')
    out.append('</g>')
    return ''.join(out)


def _emit_edge(L, e):
    # 交叉打跳（D-149）：口径与 html 版逐字相同，各自拼串（N3）。
    hp, hr, hs = hops.plan(L)
    pts = with_hops(L.path(e), hp.get(id(e), []), hr, hs)
    parts = [f'M {_fmt(pts[0][0])} {_fmt(pts[0][1])}']
    for px, py, kind in pts[1:]:
        if kind == 'arc':
            parts.append(f'A {_fmt(hr)} {_fmt(hr)} 0 0 1 {_fmt(px)} {_fmt(py)}')
        elif kind == 'gap':
            parts.append(f'M {_fmt(px)} {_fmt(py)}')
        else:
            parts.append(f'L {_fmt(px)} {_fmt(py)}')
    d = ' '.join(parts)
    ed = L.cfg['edges'][L.polarity(e)]
    dash = ' stroke-dasharray="5 4"' if ed['dashed'] else ''
    # **属性必须连续且按此序**：`manifest._html_edges` 的正则就是
    # `<path class="edge" data-from="…" data-to="…" d="…"`。
    # `stroke-width` 必须写出来：不写就吃 SVG 的默认值 1，而节点/叠影卡是 2 ——
    # 同一张图在 html 与 drawio 里线宽都是 2，只有这份产物是 1（三份产物不一致）。
    # `marker-end` 是箭头（与 html 同一枚：同尺寸、同色，按极性取，见 D-89），没有它这份产物读不出流向。
    path = (f'<path class="edge" data-from="{_esc(e["from"])}" data-to="{_esc(e["to"])}"'
            f' d="{d}" fill="none" stroke="{ed["color"]}" stroke-width="2"{dash}'
            f' marker-end="url(#ar-{L.polarity(e)})"/>')
    return path + _emit_label(L, e, ed)


def _emit_label(L, e, ed):
    """边标签（判断节点的分支条件）——与 `render_html.svg_label` **同元素约定**：
    `<g class="elab">` 内一只 `<rect class="lab-r">` + 一只 `<text class="lab">`。

    这份产物此前**不画标签**：判断节点分出"是 / 否"两支时，svg 里两支长得一模一样——
    分支条件只写在《流程表》里，单独发出去的 svg 读不出走哪条（D-86）。
    几何复用 `L.label_box(e)`（与 html/drawio 同源），不为它另算一处位置。
    **竖排**（标签落在竖段上、`L.label_vertical(e)` 为真）时给文字加 `rotate(-90 中心)`：
    盒子不用转——它本来就是按转过来的宽高算的（见 `label.py`），转的只有文字。
    """
    if not e.get('label'):
        return ''
    x, y, w, h = L.label_box(e)
    cx, cy = x + w / 2, y + h / 2
    rot = f' transform="rotate(-90 {_fmt(cx)} {_fmt(cy)})"' if L.label_vertical(e) else ''
    c = ed['color']
    return (f'<g class="elab"><rect class="lab-r" x="{_fmt(x)}" y="{_fmt(y)}" '
            f'width="{_fmt(w)}" height="{_fmt(h)}" rx="4" fill="#ffffff" stroke="{c}"/>'
            f'<text class="lab" x="{_fmt(cx)}" y="{_fmt(cy + 4)}" text-anchor="middle"{rot}'
            f' fill="{c}" font-size="{L.cfg["text"]["label"]["size"]}" font-weight="bold">'
            f'{_esc(e["label"])}</text></g>')


def _emit_lanes(ln):
    """泳道底色：左走廊 + 部门列底色/表头 + 左侧里程碑带。

    **2026-09-19 抽到公共层**（D-124）：这份原先与 `render_html.svg_lanes` 各存一份**逐字相同**的
    实现，而这里当时的文档串写着"**现在只有一个消费者**，等真有第二个再抽"——那个前提不成立
    （两个消费者都在）。现在**算的部分**共用 `swimlane.lane_bands`（末列铺右沿 / 阶段带合并 /
    文字基线偏移），**拼串仍留在这里**：把 `_fmt` / `_esc` 当参数注入进去试过，代价是静态图
    丢掉 21 条调用边（`fn_graph` 的 guardrail 报 62 > 45），而那张图是覆盖率的分母——**图的
    忠实度比少写几行更值钱**。两条硬约束（`manifest` 按产物读）写在 `lane_bands` 的文档串里。
    """
    b = ln['bands']
    out = ['<g class="lanes">']
    if b['corridor']:            # 左走廊补底色，否则里程碑带与首列之间是一条白缝（D-39）
        x, y, w, h = b['corridor']
        out.append(f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" '
                   f'height="{_fmt(h)}" fill="#f5f4f1"/>')
    for c in b['cols']:
        out.append(f'<rect x="{_fmt(c["x"])}" y="{_fmt(b["y0"])}" width="{_fmt(c["w"])}" '
                   f'height="{_fmt(b["bot"] - b["y0"])}" fill="{c["fill"]}" opacity="0.4"/>')
        out.append(f'<rect x="{_fmt(c["x"])}" y="{_fmt(b["top"])}" width="{_fmt(c["w"])}" '
                   f'height="{_fmt(b["head"])}" fill="{c["fill"]}" stroke="{c["stroke"]}"/>')
        out.append(f'<text x="{_fmt(c["x"] + c["w"] / 2)}" y="{_fmt(b["top"] + b["head"] / 2 + 5)}" '
                   f'text-anchor="middle" font-size="13" fill="{c["stroke"]}">{_esc(c["name"])}</text>')
    for s in b['stages']:
        out.append(f'<rect x="0" y="{_fmt(s["y"])}" width="{_fmt(b["sw"])}" height="{_fmt(s["h"])}" '
                   f'fill="#f5f4f1" stroke="#cccccc"/>')
        out.append(f'<text x="{_fmt(b["sw"] / 2)}" y="{_fmt(s["y"] + s["h"] / 2 + 5)}" '
                   f'text-anchor="middle" font-size="13" fill="#444441">{_esc(s["name"])}</text>')
    out.append('</g>')
    return ''.join(out)


def render(dsl_path, out_path, ctx=None):
    """DSL → 独立 `.svg`。成功返回 0（统一契约；`ctx` 本渲染器暂不用任何键）。"""
    L = load(str(dsl_path))
    L.head_band(False)          # 独立 svg 没有画布内的图例带，与 html 同口径（见文件头）
    W = L.width
    H = round(L.height())
    # 箭头标记排在最前：它必须出现在任何 `marker-end` 之前（<defs> 放最前，永不出错）
    body = [_defs(L.cfg)]
    _lanes = L.lanes()          # 流程布局返回 None —— 据此决定画不画泳道底图
    if _lanes:
        body.append(_emit_lanes(_lanes))
    body += [_emit_edge(L, e) for e in L.edges]
    drill = _drillable(L, dsl_path)          # 只算一次：它是"产物在不在"的查询，不是逐节点的
    body += [_emit_node(L, n, drill) for n in L.dsl['nodes']]
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<svg viewBox="0 0 {_fmt(W)} {_fmt(H)}" xmlns="http://www.w3.org/2000/svg"'
           f' width="{_fmt(W)}" height="{_fmt(H)}">\n'
           f'<title>{_esc(L.dsl.get("meta", {}).get("title", ""))}</title>\n'
           + '\n'.join(body) + '\n</svg>\n')
    Path(out_path).write_text(xml, encoding='utf-8', newline='\n')
    print(f'生成: {out_path}  节点: {len(L.dsl["nodes"])}  边: {len(L.edges)}  画布: {_fmt(W)}x{_fmt(H)}')
    return 0


def main():
    import argparse
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='DSL → 朴素可编辑的 .svg')
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    a = ap.parse_args()
    if not Path(a.input).exists():
        print(f'✗ 找不到输入文件: {a.input}')
        return 1
    return render(a.input, a.output or str(Path(a.input).with_suffix('.svg')))


if __name__ == '__main__':
    raise SystemExit(main())

