# -*- coding: utf-8 -*-
"""render_html.py — 流程图 DSL → 独立 HTML（评审查看版）。

几何全部服务端算好，输出纯静态 SVG；悬浮节点显示语义信息。与 drawio 版的差异见 visual-spec §1。
用法：python render_html.py flow.yaml [-o out.html]

**单文件多视图（D-52）**：主图有后代子图时，把它们**内嵌进同一个 html** 作为"视图"，
点节点下钻 = 切视图，不跳页。没有后代子图时输出与单视图时代**逐字节相同**。
退出码：0 = 写出 .html（含内嵌子视图）；1 = 输入读不了 / 结构校验不过 / 渲染失败。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from engine import load
from geometry import arc_px, with_hops
import hops
from semantics import arrow_markers, pending_style, subflow_target, SUB_INSET
from artifact import artifact_name, artifact_stem
from manifest import MAIN_VIEW

# 可下钻节点的记号：**框内一道内衬线**，同形状向内缩 `SUB_INSET` 这么多像素（见 D-78）。
# 规格另有两条同样要紧：描边 1px、同色 55% 透明——节点高 60 而文字两到三行时，
# 内圈离文字只剩几像素，只有退成"里衬"才不跟文字抢。
# 那个数**不在这里**：三份渲染器共用同一个（`semantics.SUB_INSET`，D-115）。

# 主干边上的**流光**：沿连线跑动的一小段高亮（纯装饰，不承载语义）。
#   - 只叠在**主干（实线）**边上：分支/回路是虚线，再叠流动会满屏乱闪，也会挤掉"虚线=负向"这条语义。
#   - 叠层与底边同 `d`、不改几何 ⇒ 不进碰撞检测、不被 `manifest.py` 当成边反查
#     （它靠 `<path class="edge"` 与 `data-from/to` 认边，所以叠层两者都不能带）。
#   - **画在底边之前（下层）且比底边宽**：底边仍完整压在最上，
#     光晕从线两侧透出来。第一版把它画在上层且取白色 —— 白底上等于把灰线擦断，
#     截图当场看到"线被切成一截一截"，故改为下层 + 半透明冷色。
#   - 取冷色而不是新色相堆叠：主体配色是**很淡的**蓝/绿/橙（#dae8fc/#d5e8d4/#ffe6cc），
#     半透明的饱和蓝在亮度上拉得开，不像第四个主体色。
EDGE_FLOW_DASH = (12, 18)      # 亮段 / 间隔，动画周期 = 亮段 + 间隔
EDGE_FLOW_MS = 1600            # 一道光跑完一条边的时长；悬停期间**循环**，鼠标离开即停
EDGE_FLOW_COLOR = '#4a86c8'    # 晕：冷色光晕（比灰底边饱和 ⇒ 在白底上才**看得见**）
EDGE_FLOW_STAGGER = 120        # 相邻流程步之间的错峰（ms）—— 光"顺着流程走"全靠它
# 流光 = **两层同一道光**（见 D-79）：晕负责"周围渐变"、芯负责"中间很亮"。
# 为什么不用白：白只在**深色**底上发光（svg-flow 的默认轨道 #1a1a2e、ECharts 的深色地图），
# 而我们的底是白画布与浅色填充——白在那儿只能"把线擦亮"，读作擦除而不是发光。
EDGE_FLOW_WIDTH = 9.0          # 晕宽：比底边(2)宽得多，模糊后才从两侧透出来
EDGE_FLOW_CORE = '#2f6fb4'     # 芯：同色系**加深**一档（"亮"靠的是比底色更饱和，不是更白）
EDGE_FLOW_CORE_WIDTH = 3.0
EDGE_FLOW_BLUR = 2.5           # 晕的高斯模糊半径（全文档共用一条 filter）

# 子视图用"子表流程表相对主 DSL 目录的 posix 路径"当 key——
# 天然唯一，两张不同的表不会撞；同一张表被多个节点引用时也只会内嵌一份。
MAX_VIEWS = 64          # 内嵌视图上限：环是语法上可能出现的，不值得为它赌一次死循环。
# **它的用途是"防环"，不是"控体积"**（这是 D-52 的原意，2026-09-18 说清）：
# 自举树的子表数 = 模块数 + 1，模块数在长（现 41 张），所以这个护栏要留余量——
# 原先的 40 一加模块就撞上限，于是 `build.py` 打一条"内嵌视图超过上限"的告警，
# 而门⑤ 要求收口态零告警 ⇒ **每加一个模块就要动一次护栏**，那是把"防环"用成了"预算"。
# 撞上限仍会**显式报出**（`build.py` 的 ⚠ 行），不会静默截断。

# 箭头标记与流光的模糊：**箭头本身**（尺寸 + 按极性上色）的唯一出处是 `semantics.arrow_markers`
# （见 D-89）；这里只管把它装进**整篇文档共用的一只 `<defs>`**（见 D-90）。
# `soft-glow` 是流光的**晕**层那一条模糊（见 D-79）：只 html 有（svg 产物不带流光）。
def _defs_block(cfg):
    """整篇文档共用的资源：箭头 marker + 流光模糊。**必须放在所有视图之外**（见 D-90）。

    为什么不在每张图的 `<svg>` 里各写一份：`url(#ar-main)` 按 id 解析，浏览器只认文档里
    **第一份**——而单文件里第一份属于主视图；切到子视图后主视图 `display:none`，那份定义
    就不渲染，于是**子视图一条箭头都没有**（实测：主图正常、7 张子图全无箭头，用户报的
    "子流程没有箭头"就是它）。滤镜 `soft-glow` 同理，坏了会让流光的**晕**层整个不画。
    放在视图之外一只 0×0 的 `<svg>` 里：既不在任何 `display:none` 子树下，也不占版面。
    **位置必须在所有视图之后**：它里面的 marker 各自带 `viewBox="0 0 10 10"`，而
    `manifest._html_canvas` / `shot.py` 都是取文档里**第一个** `viewBox` / 第一个 `<svg>` 当画布
    ——放到前面会让产物的几何自检把画布读成 10×10、全线"越界"（实测：build 当场退非 0）。
    """
    return (f'<svg class="vdefs" width="0" height="0" aria-hidden="true" '
            f'style="position:absolute;width:0;height:0;overflow:hidden">'
            f'<defs>{arrow_markers(cfg)}'
            f'<filter id="soft-glow" x="-80%" y="-80%" width="260%" height="260%">'
            f'<feGaussianBlur stdDeviation="{EDGE_FLOW_BLUR}"/></filter></defs></svg>')

MULTI_CSS = """
/* 单文件多视图（见 D-52）：子图内嵌为视图，点下钻切视图而不是跳页。 */
.view { display:none; }
.view.cur { display:block; }
.crumbs a { color:#555555; text-decoration:none; padding:2px 8px; border-radius:4px; }
.crumbs a:hover { color:#185FA5; background:#f5f9ff; }
.crumbs .sep { color:#aaaaaa; }
.crumbs .here { color:#9673a6; font-weight:bold; padding:2px 8px; }
"""

# 多视图的脚本。`@MAIN@` 由 Python 替换成 MAIN_VIEW——JS 与 Python 必须指向同一个标识，
# 写死两份迟早对不上，替换一份就不必记着改两处。
MULTI_JS = """
/* 单文件多视图（见 D-52）：子图**内嵌在本文件里**，下钻 = 切视图，不再跳页。
   发给客户的就是这一个文件，整个层级都在里面，不依赖子目录里的任何 html。 */
var _views = [].slice.call(document.querySelectorAll('.view'));
var byKey = {};
_views.forEach(function(v){ byKey[v.dataset.view] = v; });
var _h1 = headmod ? headmod.querySelector('h1') : null;
var _crumbs = document.getElementById('crumbs');
var _baseCrumb = _crumbs ? _crumbs.innerHTML : '';
var _trail = ['@MAIN@'];
function _esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function _ensureCrumbs(){
  if (_crumbs) return _crumbs;
  /* 顶层主图没有"回程路"，HTML 里不必先摆一个空条——等真下钻了再建，
     建的时候补上 has-crumbs，让标题模块让位（两个都是 fixed，重叠就谁也看不见）。 */
  _crumbs = document.createElement('div');
  _crumbs.id = 'crumbs'; _crumbs.className = 'crumbs';
  document.body.insertBefore(_crumbs, document.body.firstChild);
  if (headmod) headmod.classList.add('has-crumbs');
  _crumbs.addEventListener('click', function(ev){
    var el = ev.target;
    while (el && el !== _crumbs) {
      var g = el.getAttribute && el.getAttribute('data-go');
      if (g) { go(g); return; }
      el = el.parentNode;
    }                                /* 服务端给的"返回父图"链接没有 data-go：走浏览器默认行为 */
  });
  return _crumbs;
}
var _trail = ['@MAIN@'];
function vhash(k){ return '#' + encodeURIComponent(k === '@MAIN@' ? 'main' : k); }
function keyOfHash(){
  var h = location.hash.replace(/^#/, '');
  if (!h || h === 'main') return '@MAIN@';
  try { h = decodeURIComponent(h); } catch (e) {}
  return byKey[h] ? h : '@MAIN@';
}
function _crumbsHtml(){
  var out = _baseCrumb, n = _trail.length;
  if (!out && n <= 1) { if (_crumbs) _crumbs.style.display = 'none'; return; }
  var el = _ensureCrumbs();
  el.style.display = '';
  _trail.forEach(function(k, i){
    var v = byKey[k]; if (!v) return;
    var nm = _esc(v.dataset.title || k);
    if (i > 0 || out) out += '<span class="sep"> \\u203a </span>';
    out += (i === n - 1) ? '<span class="here">' + nm + '</span>'
                         : '<a href="javascript:void 0" data-go="' + _esc(k) + '">' + nm + '</a>';
  });
  el.innerHTML = out;
}
function showView(key, setHash){
  var v = byKey[key]; if (!v) return;
  saveScroll();                      /* 先存"离开的这一层"——此时 SCROLL_KEY 还是它的 */
  _views.forEach(function(x){ x.classList.toggle('cur', x === v); });
  if (_h1) _h1.innerText = v.dataset.title || '';
  /* 每层各记各的视窗位置：单文件里 location.pathname 不再区分层级，键必须带上视图 key */
  SCROLL_KEY = 'fc-scroll:' + location.pathname + '#' + key;
  _crumbsHtml();
  fitHead();                         /* 换了视图，标题可能换行变高，body 顶部留白要重算 */
  restoreScroll();
  if (setHash && location.hash !== vhash(key)) location.hash = vhash(key);
}
function go(key){
  if (!byKey[key]) return;
  var i = _trail.indexOf(key);
  if (i >= 0) _trail = _trail.slice(0, i + 1); else _trail.push(key);
  showView(key, true);
}
window.addEventListener('hashchange', function(){
  var k = keyOfHash();
  if (k === _trail[_trail.length - 1]) return;
  _trail = (k === '@MAIN@') ? ['@MAIN@'] : ['@MAIN@', k];
  showView(k, false);
});
_crumbsHtml();
(function(){ var k = keyOfHash(); if (k !== '@MAIN@') { _trail = ['@MAIN@', k]; showView(k, false); } })();
""".replace('@MAIN@', MAIN_VIEW)

# 单击下钻：单视图跳页，多视图切视图（`go` 由 MULTI_JS 定义，在这个 <script> 里是同一个作用域）。
# 自引用要先掐掉：节点的 ⊞ 指向的表就是主表自己时，`collect_views` 把它的 key 记成 MAIN_VIEW，
# 而单视图里 `data-sub` 同时承担着"这个节点可下钻"的画环判据——照旧拼 URL 就是跳到 __main__ 这个
# 不存在的页面（并且没有任何别的子图时 multi 为 False，走不到切视图那条路）。点了没反应 >> 跳 404。
CLICK_SINGLE = (f"    if (d.sub === '{MAIN_VIEW}') return;   // 自引用：跳无可跳，不响应\n"
                "    if (ev.ctrlKey || ev.metaKey) window.open(d.sub, '_blank');\n"
                "    else window.location.href = d.sub;")
CLICK_MULTI = ("    if (ev.ctrlKey || ev.metaKey) "
               "window.open(location.href.split('#')[0] + '#' + encodeURIComponent(d.sub), '_blank');\n"
               "    else go(d.sub);")


def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def fmt(v):
    return f'{v:.1f}'.rstrip('0').rstrip('.')


def _display_desc(desc):
    """悬浮框里显示的「节点描述」：剥掉行首的标记语法本身（`⚠…` / `⊞ 路径；…`）。

    两个标记都各有专门的展示位，描述里再原样打一遍就是重复：
    `⚠` → 悬浮框首行的固定说明句；`⊞` → 框内内衬线 + 悬浮框标题行右侧的「（点击查看流程详情）」。

    而且 `⊞` 后面跟的是**文件路径**（`parts/结构校验/flowtable.md`）——那是给机器读的管道，
    不是给人看的语义。把它原样摊在悬浮框里，用户读到的是一串目录名。
    """
    d = re.sub(r'^\s*⚠\s*', '', desc)                    # 与既有行为一致，不动
    # `⊞ + 路径`，**分隔符（`；`/`;`）可有可无**（G71）：规范里的示例带分号，但没强制；
    # 写成 `⊞ parts/x.md ⚠ 推断` 时原先剥不掉，用户会在悬浮框里看到一串目录名。
    d = re.sub(r'^\s*⊞\s*[^\s；;]*\s*(?:[；;]\s*)?', '', d)
    return d


def _sub_ring(shp, w, h, stroke):
    """可下钻节点的**内衬线**（见 D-78）：同形状、向内缩 `SUB_INSET` 的一圈细线。

    为什么记号必须**在框内**：一旦出框，它同时和端口、相邻墨迹、包围盒/网格三样打交道——
    向外叠影那版就是这个病：向下的出线从卡片里钻出来（端口在边中点，卡片却压在下面），
    而且外扩 10px 的包围盒 170×70 是**离格**的。框内的一圈谁都不碰。

    **只有这一层**：记号全靠它自己"看得见"（截图、打印、关掉动画都在）。悬停时曾经另跑一段光
    沿它转一圈（见 D-80），撤掉了——点亮可点击这件事改由悬浮框标题行右侧的灰字承担。
    """
    i = SUB_INSET
    if shp['shape'] == 'rhombus':
        pts = (f'{fmt(0)},{fmt(-(h / 2 - i))} {fmt(w / 2 - i)},{fmt(0)} '
               f'{fmt(0)},{fmt(h / 2 - i)} {fmt(-(w / 2 - i))},{fmt(0)}')
        return (f'<polygon class="sub-ring" points="{pts}" fill="none" stroke="{stroke}"'
                f' stroke-width="1" opacity="0.55"/>')
    rx = (h / 2 - i) if shp['shape'] == 'stadium' else arc_px(shp, w - 2 * i, h - 2 * i)
    return (f'<rect class="sub-ring" x="{fmt(-(w / 2 - i))}" y="{fmt(-(h / 2 - i))}"'
            f' width="{fmt(w - 2 * i)}" height="{fmt(h - 2 * i)}" rx="{fmt(rx)}"'
            f' fill="none" stroke="{stroke}" stroke-width="1" opacity="0.55"/>')


def svg_node(L, n, subs=None, prefix=''):
    nid = n['id']
    x, y, w, h = L.rect(nid)
    cx, cy = x + w / 2, y + h / 2
    s = L.subjects.get(n['subject']) or L.subjects['默认']
    t = L.cfg['text']
    shp = L.cfg['shapes'][n['type']]
    # ⚠ 推断留痕是描边上唯一的一层：颜色 + 虚线，取值见 dictionary `pending:`（见 flowtable-spec §2）
    stroke, dash = s['stroke'], ''
    ps = pending_style(L.cfg, n.get('desc'))
    if ps:
        stroke = ps['stroke'] or stroke
        dash = f' stroke-dasharray="{ps["dash"]}"' if ps['dash'] else ''
    # 背面卡跟着节点走：同形状、同色（含 ⚠ 换过的描边色），但**不带虚线**——⚠ 是节点的事，不是卡的。
    mark = _sub_ring(shp, w, h, stroke)
    if shp['shape'] == 'rhombus':
        # 组已 translate(cx,cy)，多边形须用以(0,0)为中心的局部坐标，否则坐标被二次叠加错位
        shape = (f'<polygon class="shape" points="{fmt(0)},{fmt(-h/2)} {fmt(w/2)},{fmt(0)} '
                 f'{fmt(0)},{fmt(h/2)} {fmt(-w/2)},{fmt(0)}" fill="{s["fill"]}" stroke="{stroke}"{dash}/>')
    elif shp['shape'] == 'stadium':
        # 胶囊（开始/结束）：圆角半径取半高 = 左右半圆。**几何仍按矩形**——端口落在外接矩形边界上，
        # 与 drawio 的矩形周长一致（D-74）。
        r = h / 2
        shape = (f'<rect class="shape" x="{fmt(-w/2)}" y="{fmt(-h/2)}" width="{fmt(w)}" height="{fmt(h)}" '
                 f'rx="{fmt(r)}" fill="{s["fill"]}" stroke="{stroke}"{dash}/>')
    else:
        shape = (f'<rect class="shape" x="{fmt(-w/2)}" y="{fmt(-h/2)}" width="{fmt(w)}" height="{fmt(h)}" '
                 f'rx="{fmt(arc_px(shp, w, h))}" fill="{s["fill"]}" stroke="{stroke}"{dash}/>')
    lines = L.node_lines(nid)
    step = 16
    base = -(len(lines) - 1) * step / 2 + 4
    txt = ''
    for i, (kind, text) in enumerate(lines):
        cls = {'name': 't1', 'executor': 'tm', 'time': 'tt2'}[kind]
        txt += f'<text class="{cls}" y="{fmt(base + i * step)}">{esc(text)}</text>'
    # 子流程标记（见 D-78）：**框内一道内衬线**（同形状内缩 2px / 1px / 55%）——
    # 它落在节点包围盒内，于是端口、连线、相邻墨迹、包围盒与网格全都不受影响。
    # "这里能点"由**悬浮框**说明（标题行右侧灰字 `（点击查看流程详情）`，见 D-80）：
    # 可点击是"读到这里顺手做的事"，由悬浮框在用户已经伸手去点的时候说，最准；
    # 画在图上的记号只承担"里面有子流程"这一条，静态可见、不借运动。
    #
    # 为什么不是"往外叠一张卡"：出框就同时和上面那三样打交道——向下的出线会从卡片里钻出来
    # （端口在边中点、卡片却压在下面），外扩的包围盒还会离格。三种形状上逐个试过，只有内衬线全身而退。
    #
    # `mark` 与 `data-sub` 都以**同一个已解析的目标**为准（D-52 之后是"视图 key"，早先是子图产物路径）。
    # 早期版本把 `data-sub` 直接写成 `subflow_ref()` 的原文（`.md`），而 JS 跳转读的是 TIPS 里
    # 的 `.html`——同一个事实两处写法，改一处必漏一处。现在唯一真值就是 subs。
    sub = (subs or {}).get(n['id'])
    mark_card, sub_attr = '', ''
    if sub:
        mark_card = mark            # 画在本体**之后**：它无填充，落在框内，只多一道线
        sub_attr = f' data-sub="{esc(sub)}"'
    # 子视图的节点 id 加 `key::` 前缀：单文件里 N 张图共用一份 TIPS，
    # 而各表的编号天然重复（每张表都有 01），不加前缀后画的会把先画的整条覆盖掉。
    # `data-nid` 另存**不加前缀**的编号：悬停配对要和边的 `data-from/to` 同口径（见 D-90）。
    return (f'<g class="ndg" data-id="{esc(prefix + nid)}" data-nid="{esc(nid)}"{sub_attr} '
            f'transform="translate({fmt(cx)},{fmt(cy)})">{shape}{mark_card}{txt}</g>')


def _node_row(L, nid):
    """节点所在行 —— 用作流光的错峰序号（光顺着流程一段段亮过去）。

    用行号而不是边的数组下标：行号本身就是流程次序，且不依赖边被渲染的先后。
    """
    for n in L.dsl['nodes']:
        if n['id'] == nid:
            return int(n.get('row', 0))
    return 0


def svg_edge(L, e):
    pol = L.polarity(e)
    ed = L.cfg['edges'][pol]
    # 交叉打跳（D-149）：方案由 `hops.plan` 出（每张图缓存一次），拼串留在这里（N3）。
    # 半圆两端落在原线段上 ⇒ `manifest.py` 只认 `M`/`L` 的反解得到的仍是共线折线。
    hp, hr = hops.plan(L)
    pts = with_hops(L.path(e), hp.get(id(e), []), hr)
    parts = [f'M {fmt(pts[0][0])} {fmt(pts[0][1])}']
    for px, py, arc in pts[1:]:
        parts.append(f'A {fmt(hr)} {fmt(hr)} 0 0 1 {fmt(px)} {fmt(py)}' if arc
                     else f'L {fmt(px)} {fmt(py)}')
    d = ' '.join(parts)
    dash = ' stroke-dasharray="5 4"' if ed['dashed'] else ''
    # 箭头按**极性**取（`semantics.arrow_markers` 给每条极性一枚同色的 marker）。
    # 早先按"实线/虚线"取 `ar-solid`/`ar-dash`：那两支的色值是写死的，与字典的边色重复陈述，
    # 且"虚线"与"负向"本是两件事（见 D-89）。
    # data-from / data-to 不是给浏览器看的，是给 `manifest.py` 反查用的：
    # 只有 path 的 d 属性时，产物侧无法知道这条线连的是谁，"渲染丢了哪条边"就查不出来。
    base = (f'<path class="edge" data-from="{esc(e["from"])}" data-to="{esc(e["to"])}"'
            f' d="{d}" stroke="{ed["color"]}"{dash} marker-end="url(#ar-{pol})"/>')
    # 流光：只在**主干（实线）**边上，**两层同一道光**（晕 + 芯，见 D-79）。
    # **必须画在底边之前**（SVG 后者压前者）：底边完整压在最上，晕从两侧透出来；
    # 画在上层就成了"用颜色盖住线"，白底上等于把线擦断。
    # 样式（色/宽/dash/动画/透明）全在 CSS 里，Python 只给几何 `d`、`--step` 与那条共用的模糊。
    # 不带 data-from/to、class 不叫 edge：产物审核靠这两个认边，叠层不能被算成第二条边。
    if ed['dashed']:
        flow = ''
    else:
        # --step 给 CSS 的 animation-delay 用（错峰），见 _node_row 的说明。
        # 芯**紧跟**在晕之后：CSS 用相邻兄弟选择器让两层的动画同进同退（`.is-run + .edge-flow-core`）。
        step = _node_row(L, e['from'])
        flow = (f'<path class="edge-flow" style="--step:{step}" d="{d}" filter="url(#soft-glow)"/>'
                f'<path class="edge-flow-core" style="--step:{step}" d="{d}"/>')
    return flow + base + svg_label(L, e, ed)


def svg_label(L, e, ed):
    if not e.get('label'):
        return ''
    x, y, w, h = L.label_box(e)
    c = ed['color']
    # class="elab" 只是"这是边标签"的语义钩子（几何自检与产物审核都不认它，认的是 `path.edge`）。
    return (f'<g class="elab"><rect class="lab-r" x="{fmt(x)}" y="{fmt(y)}" '
            f'width="{fmt(w)}" height="{fmt(h)}" rx="4" stroke="{c}"/>'
            f'<text class="lab" x="{fmt(x + w / 2)}" y="{fmt(y + h / 2 + 4)}" fill="{c}">{esc(e["label"])}</text></g>')


def svg_lanes(ln):
    """泳道背景：顶部部门带 + 左侧阶段带 + 部门列底色（画在边与节点之前，规则见 swimlane-spec §6）。

    **算的部分只有一处**：`swimlane.lane_bands`（D-124）——末列铺到右沿、阶段带合并、文字基线
    偏移这些会漂的算术都在那儿；**拼串留在这里**（元素约定归各自渲染器，见 N3）。
    原先本函数与 `render_svg._emit_lanes` 各存一份逐字相同的实现（38 行里 21 行一字不差）。
    """
    b = ln['bands']
    out = ['<g class="lanes">']
    if b['corridor']:            # 左走廊补底色，否则里程碑带与首列之间是一条白缝（D-39）
        x, y, w, h = b['corridor']
        out.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" '
                   f'height="{fmt(h)}" fill="#f5f4f1"/>')
    for c in b['cols']:
        out.append(f'<rect x="{fmt(c["x"])}" y="{fmt(b["y0"])}" width="{fmt(c["w"])}" '
                   f'height="{fmt(b["bot"] - b["y0"])}" fill="{c["fill"]}" opacity="0.4"/>')
        out.append(f'<rect x="{fmt(c["x"])}" y="{fmt(b["top"])}" width="{fmt(c["w"])}" '
                   f'height="{fmt(b["head"])}" fill="{c["fill"]}" stroke="{c["stroke"]}"/>')
        out.append(f'<text x="{fmt(c["x"] + c["w"] / 2)}" y="{fmt(b["top"] + b["head"] / 2 + 5)}" '
                   f'text-anchor="middle" font-size="13" fill="{c["stroke"]}">{esc(c["name"])}</text>')
    for s in b['stages']:
        out.append(f'<rect x="0" y="{fmt(s["y"])}" width="{fmt(b["sw"])}" height="{fmt(s["h"])}" '
                   f'fill="#f5f4f1" stroke="#cccccc"/>')
        out.append(f'<text x="{fmt(b["sw"] / 2)}" y="{fmt(s["y"] + s["h"] / 2 + 5)}" '
                   f'text-anchor="middle" font-size="13" fill="#444441">{esc(s["name"])}</text>')
    out.append('</g>')
    return ''.join(out)


def html_head(L, subjects, cls=''):
    """标题模块：标题 + 图例色块合成一个 `position: fixed` 的条（滚动不离视窗）。

    它在画布之外，所以画布不必预留标题带。subjects 只用 `meta.subjects` 声明的那份——不能用 `L.subjects`。
    `cls` 是附加类（下钻子图带 `has-crumbs` 时标题模块要下移，见 D-47）。

    **只放"这是什么图 + 颜色是谁"**：形状/线型/橙色字一眼就能看出，写进来是噪声；
    "悬浮看路由与描述"这类**用法说明**也一并撤掉了——它常驻在标题栏里，说的却是要动手才知道的事，
    而 drawio 版（没有悬浮语义）根本没这句话可对（见 visual-spec §1「图例」）。
    """
    sw = ''.join(
        f'<span class="lg"><span class="sw" style="background:{esc(s["fill"])};'
        f'border-color:{esc(s["stroke"])}"></span>{esc(k)}执行</span>'
        for k, s in (subjects or {}).items()) or '<span class="lg">（未配置执行主体）</span>'
    return (f'<div class="headmod{cls}" id="headmod">\n'
            f'  <h1>{esc(L.dsl["meta"]["title"])}</h1>\n'
            f'  <div class="legend">{sw}</div>\n'
            f'</div>')


def collect_views(dsl_path):
    """主 DSL → 内嵌视图计划（BFS，按**表**去重，防环）。见 D-52。

    返回 `{'views': [(key, 子图 yaml 路径)…], 'keys': {子表绝对路径: key},
           'pending': [缺 DSL 的子表…], 'absent': [⊞ 指向但不存在的表…],
           'truncated': [(key, 子图 yaml 路径)…], 'unreadable': [key…],
           'max_views': 上限值}`。

    `views` 不含主图，顺序 = BFS 序（直属子表在前，孙表在后）。`pending` 由 build 先补上 DSL
    再重跑本函数即可内嵌；`absent` 是 `⊞` 写错字，渲染时静默降级（该节点没有内衬线、不可点）。

    `truncated` 是**撞上 `MAX_VIEWS` 而没进 `views`** 的那些表，**连同它们下面还没展开的子孙**
    （子孙也在这份里，否则"到底少了几张"数不准）。它与 `absent` 语义不同、必须分开报：
    `absent` 是"表不存在"，这里是"表在、DSL 也备好了，只是配额不够"——混进 `absent` 会让
    调用方以为 `⊞` 路径写错了。`max_views` 带出实际生效的上限值，免得调用方把 40 写进文案。

    `unreadable` 是第四种、也是唯一会让**子孙整支消失**的情形：表在、yaml 也在（所以它照样
    进了 `views`，渲染器届时 `continue` 跳过它），但 `load` 读不动——于是**它自己的子孙永远
    发现不了**：不在 `views`/`pending`/`absent`/`truncated` 任何一份里，无从枚举。这里只如实
    报出"读不动的那几张"，把"子孙未知、需人工确认"这件事交给调用方说出口。
    四者语义两两不同：`pending`=待补 DSL、`absent`=表不存在、`truncated`=配额不够、
    `unreadable`=表在但 DSL 读不动。

    `keys` 只收**能 load 得动**的表（口径：`keys ⊆ 能 load 的`）。读不动的表仍留在 `views` 里
    ——那是给调用方逐张报"这张读不动"用的——但**不进 `keys`**：`keys` 是"主图的这个节点能不能
    指到一个真视图"的判据，收进来就等于给用户一枚点了没反应的下钻入口（`_assemble_view_blocks`
    里 load 失败那张会 `continue`，产物里根本没有它的视图块）。

    为什么按**表**去重而不是按节点：同一张子表被三个节点引用，嵌三份就是三倍体积，
    而且下钻进去是三张一模一样的图。用户要的是"那张图"，不是"那个入口"。

    防环要在三处做：`seen` 挡住"同一份 yaml 被展开两次"（A→B→A 这种环），`keys` 挡住
    "同一张表被两个节点引用"，`trunc_seen` / `unread_seen` 挡住"同一张在菱形引用下被数两次"。
    漏掉 `seen` 会重复展开，漏掉 `keys` 会死循环，漏掉后两者则张数偏大。
    """
    base = Path(dsl_path).resolve().parent
    root = Path(dsl_path).resolve()
    views, pending, absent, keys = [], [], [], {}
    truncated, trunc_seen = [], set()
    unreadable, unread_seen = [], set()
    # `bad`：**已经判定"进不了视图"的表**（读不动 / 缺席 / 还没备好 DSL）。见 G47：
    # 原先去重只靠 `keys`，而读不动那一刻要 `keys.pop`（不给出点下去没反应的下钻入口），
    # 于是第二张父表再引用同一张表时会把它**第二次 append 进 views**；absent / pending
    # 两条路更是完全没有去重，同一张表被几个节点引用就被数几遍——"内嵌 N 张"于是虚高。
    bad = set()
    # 队列里带上"这张 yaml 是从哪张流程表来的"：读不动时要靠它报出是哪一张。
    seen, queue = {root}, [(root, None)]
    # 上限只在**收视图那一处**判（`len(views) >= MAX_VIEWS`），不再兼作 while 的退出条件。
    # 判在追加点而不是轮首是必须的：一张表里写多个 ⊞ 时，只在轮首判会让同一轮连续 append 冲过
    # 上限（总数取决于那张表有几个 ⊞，MAX_VIEWS 就成了守不住的软上限）。
    # 收满后**不再停下**：被截掉的那些表以前既不在 views、也不在 pending/absent，调用方无从知道
    # 少了几张——"不内嵌"于是成了这条路上**唯一不报警**的失效，连同被截表的子孙整支没被发现。
    # 现在收满后继续走完这棵树、只数不再收，把每一张没进去的表记进 `truncated`，由 build 报出来。
    # ≤ MAX_VIEWS 时下面的截断分支一次都不会进，行为与从前逐字节相同。
    while queue:
        yp, src_md = queue.pop(0)
        try:
            L = load(str(yp))
        except (OSError, ValueError, KeyError, TypeError):
            # 读不动/结构坏：不在这里炸。但它自己的子孙**再也发现不了**（读不动就读不动，
            # 枚举不出来），必须把这张表记下来——否则它那一支会整支不出现也不报告。
            # 注意它仍可能已经在 `views` 里（入列只看 yaml 在不在），build 会另对它报一次
            # "DSL 读不动，渲染时跳过"；两份记录视角不同，是有意的。
            if src_md is not None and src_md not in unread_seen:
                unread_seen.add(src_md)
                bad.add(src_md)
                unreadable.append(Path(os.path.relpath(str(src_md), str(base))).as_posix())
            # 读不动 = 渲染时没有它的视图本体 → **退回认领**，把 `keys` 收敛成"只收能 load 的"。
            # `keys` 是主图节点画不画内衬线（`data-sub`）的判据：留着它，用户就得到一枚点了没
            # 反应的下钻入口。认领要留到**这一刻**才退是有原因的——`md in keys` 同时是"同一张表
            # 被两个节点引用"的去重守卫，退早了，同一张读不动的表会被 append 进 `views` 两次。
            if src_md is not None:
                keys.pop(src_md, None)
            continue
        for n in L.dsl.get('nodes') or []:
            rel = subflow_target(n.get('desc'))          # 子表**流程表**的路径
            if not rel:
                continue
            md = (yp.parent / rel).resolve()
            if md in keys or md in bad:                   # 已经有视图 / 已判定进不了视图
                continue
            if not md.exists():
                bad.add(md)                               # 同一张缺席的表被多张父表引用只报一次
                absent.append(md)
                continue
            yml = (md.parent / artifact_name(artifact_stem(md), 'yaml')).resolve()
            if yml == root:                               # 子表又指回主表 → 回主视图，不重复嵌一份
                keys[md] = MAIN_VIEW
                continue
            if not yml.exists():
                bad.add(md)                               # 同 `absent`：计数不重复
                pending.append(md)
                continue
            key = Path(os.path.relpath(str(md), str(base))).as_posix()
            if len(views) >= MAX_VIEWS:
                # 配额已满：这张表（连同它下面还没展开的子孙）不会进 HTML，但必须被数到。
                # **不写 keys**——写了就会给出"有视图 key 却没有视图本体"的假条，
                # 那等于给用户一个点下去没反应的下钻入口。
                if md not in trunc_seen:
                    trunc_seen.add(md)
                    truncated.append((key, str(yml)))
                    if yml not in seen:                  # 继续往下走，把它们也数进来
                        seen.add(yml)
                        queue.append((yml, md))
                continue
            keys[md] = key
            views.append((key, str(yml)))
            if yml not in seen:
                seen.add(yml)
                queue.append((yml, md))
    return {'views': views, 'keys': keys, 'pending': pending, 'absent': absent,
            'truncated': truncated, 'unreadable': unreadable, 'max_views': MAX_VIEWS}


def _union_subjects(entries):
    """跨层配色并集：[(来源, 配色表)…] → (并集表, [冲突…])。见 D-52 / D-49。

    图例是**一份**（单文件里标题模块只有一个），所以它得覆盖主图与所有内嵌子图用到的主体，
    否则下钻进去会看见图上有颜色、图例里查不到。

    同一个主体跨层两色 = **硬错误**：颜色在这个体系里是主体的身份（D-49），
    单文件让所有层共用一张图例，两色会并排出现在同一条图例里，藏不住也不该藏。
    """
    out, origin, errs = {}, {}, []
    for src, sub in entries:
        for k, v in (sub or {}).items():
            if k in out:
                # fill 与 stroke 都要比：D-49 说的"同色"是整个配色（填充 + 描边），只比 fill 时
                # 描边不同的同名主体会静默以先者为准——单文件只有一条共用图例，
                # 图上边框会与图例里的色块对不上，而这正是"认不出这是哪个主体"的那种错。
                if out[k]['fill'] != v['fill'] or out[k]['stroke'] != v['stroke']:
                    errs.append(f'执行主体「{k}」跨层配色不一致：《{origin[k]}》与《{src}》'
                                f'颜色不同——同一主体必须同色，改其中一张表的「执行主体配色」')
            else:
                out[k], origin[k] = v, src
    return out, errs


def _view_svg(L, base, key, keys):
    """一张图 → (svg 字符串, tips 字典, 画布高)。

    `base` 是这张图 DSL 所在目录（`⊞` 的路径相对它解析），`key` 是它在单文件里的视图标识。
    """
    H = round(L.height())
    pre = '' if key == MAIN_VIEW else key + '::'
    # 子表解析基准 = DSL 所在目录。build.py 总是把 flow.yaml 写在流程表旁边，
    # 所以 `⊞ parts/渲染.md` 相对 DSL 目录解析，正好等于"相对流程表所在目录"。
    # 必须在画节点**之前**算好——节点上那道内衬线与悬浮框里的提示都要用它（见 D-78）。
    subs = {}                       # nid -> 目标**视图 key**（仅当那张表真的内嵌了才收录）
    for n in L.dsl['nodes']:
        rel = subflow_target(n.get('desc'))
        if rel is None:
            continue
        # **内嵌不了就不画环**：宁可少一个可点，也不能给用户一个点下去没反应的入口。
        # 静默降级为普通节点——主图渲染不该依赖子图是否已 build 过。
        k = keys.get((base / rel).resolve())
        if k:
            subs[n['id']] = k
    svg = [f'<svg viewBox="0 0 {L.width} {H}" xmlns="http://www.w3.org/2000/svg">']
    _lanes = L.lanes()
    if _lanes:
        svg.append(svg_lanes(_lanes))
    # 先画边，后画节点（节点在上层）
    for e in L.edges:
        svg.append(svg_edge(L, e))
    for n in L.dsl['nodes']:
        svg.append(svg_node(L, n, subs, pre))
    svg.append('</svg>')
    tips = {}
    up = {}
    for e in L.dsl['edges']:
        up.setdefault(e['to'], []).append(e['from'])
    for n in L.dsl['nodes']:
        # 描述的 `⚠` 前缀是给人看的标记，悬浮框里换成固定说明句，不重复显示（否则两个 ⚠ 叠在一起）
        tips[pre + n['id']] = {
            'title': f"{n['id']} {n['name']}",
            'subject': n['subject'], 'executor': n['executor'],
            'input': n.get('input'), 'basis': n.get('basis'), 'output': n.get('output'),
            'up': '、'.join(up.get(n['id'], [])) or None,
            'time': n.get('time'), 'route': L.route_text(n['id']),
            'desc': _display_desc(n.get('desc') or ''),
            'pend': (pending_style(L.cfg, n.get('desc')) or {}).get('note'),
            'sub': subs.get(n['id']),
        }
    return '\n'.join(svg), tips, H


def render(dsl_path, out_path, ctx=None):
    """DSL → 独立 HTML。按阶段装配：上下文 → 视图块 → 页头/正文 → 整页 → 落盘。

    `ctx` 是统一契约里**渲染器私有选项的唯一入口**（ARCHITECTURE.md 第九节 W2/W3）：
    不传（`None`）时与最初的 `render(dsl_path, out_path)` 完全等价。
    本模块只认 `parent` 一个键（下钻子图的面包屑，见 D-47）。
    注意：函数体内的局部量叫 `rctx`（渲染上下文），与入参 `ctx` 不是一回事——
    同名会互相遮蔽，后来人往下加代码时极易抓错那个。
    """
    parent = (ctx or {}).get('parent')
    rctx = _load_render_context(dsl_path)
    blocks, subjects, cerr = _assemble_view_blocks(rctx)
    if cerr:
        print('✗ 跨层配色不一致，已阻断渲染（同一执行主体必须同色，见 D-49）：')
        for e in cerr:
            print('   -', e)
        return 1
    multi = bool(rctx['views'])
    tips_json = _serialize_tips(rctx['tips'])
    crumbs_html, crumbs_cls = _build_crumbs(multi, parent)
    head_html = html_head(rctx['L'], subjects, crumbs_cls)
    body = _build_page_body(multi, blocks, rctx['main_svg'])
    html = _build_html_document(rctx['L'], rctx['H'], rctx['t'], tips_json,
                                crumbs_html, head_html, body, multi)
    # 回执里的张数取**真的落到产物里的视图数**（`blocks` 去掉主视图），不取 `views` 的长度：
    # 读不动的表在 `views` 里（那是给 build 逐张告警用的），但它的视图块根本没拼进去——
    # 按 `views` 数就会报"内嵌 N 张"，而产物里一张都没有。
    return _write_html_output(out_path, html, rctx['L'], rctx['H'], len(blocks) - 1, multi)


def _load_render_context(dsl_path):
    """加载主 DSL、收集内嵌视图计划并渲染主视图，返回渲染上下文 dict。"""
    plan = collect_views(dsl_path)
    views, keys = plan['views'], plan['keys']

    L = load(dsl_path)
    L.head_band(False)      # 标题模块在画布外（见 html_head），画布不再预留标题带
    base = Path(dsl_path).resolve().parent
    H = round(L.height())
    t = L.cfg['text']
    title = L.dsl['meta']['title']
    subjects = dict((L.dsl.get('meta') or {}).get('subjects') or {})
    main_svg, tips, _ = _view_svg(L, base, MAIN_VIEW, keys)
    return {'L': L, 'H': H, 't': t, 'title': title, 'subjects': subjects,
            'views': views, 'keys': keys, 'main_svg': main_svg, 'tips': tips}


def _assemble_view_blocks(ctx):
    """装配主视图与各内嵌子视图的 (key, 标题, svg, 宽, 高) 块，并归并跨层图例。

    返回 (blocks, subjects, cerr)；cerr 非空表示跨层配色不一致（调用方负责报错并中止）。
    """
    views, keys, L = ctx['views'], ctx['keys'], ctx['L']
    subjects, tips = ctx['subjects'], ctx['tips']
    blocks = [(MAIN_VIEW, ctx['title'], ctx['main_svg'], L.width, ctx['H'])]
    if views:
        # 内嵌后代子图（D-52）：每张图各自 load 一遍几何，拼成同文件里的一个"视图"。
        # 图例取**跨层并集**——单文件里标题模块只有一个，图例漏了哪一层，那一层就有色无解。
        all_sub = [(MAIN_VIEW, subjects)]
        for key, yml in views:
            try:
                SL = load(yml)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            SL.head_band(False)
            s2, t2, h2 = _view_svg(SL, Path(yml).resolve().parent, key, keys)
            tips.update(t2)                     # 子视图的 id 带 key:: 前缀，不会覆盖主视图
            blocks.append((key, (SL.dsl.get('meta') or {}).get('title') or key, s2, SL.width, h2))
            all_sub.append((key, (SL.dsl.get('meta') or {}).get('subjects') or {}))
        subjects, cerr = _union_subjects(all_sub)
        return blocks, subjects, cerr
    return blocks, subjects, []


def _serialize_tips(tips):
    """把悬浮提示表序列化成可安全内联进 <script> 的 JS JSON 字面量。"""
    # JSON 里必须转义 `<`：不转义的话，节点描述里出现 `</script` 会让 HTML 解析器提前闭合
    # 这个 <script> 块，整页 JS 报废（悬浮框全失效）。\u2028/\u2029 同理，它们是合法的行分隔符，
    # 直接出现在 JS 字符串字面量里会断句。转写成 \uXXXX 转义后，JSON 解析结果一字不变。
    tips_json = (json.dumps(tips, ensure_ascii=False)
                 .replace('<', '\\u003c').replace('>', '\\u003e')
                 .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))
    return tips_json


def _build_crumbs(multi, parent):
    """生成面包屑 HTML 与标题模块附加类；顶层主图无回程路时两者皆空。"""
    # 面包屑（见 D-47 / D-52）：本表是别人的下钻子图时，在左上角挂一条回程路。
    # 没有回程路的下钻比不做还糟——用户点进来就困在子图里，只能按浏览器后退。
    # `parent` 由 build.py 从父表反查得到（(相对链接, 父节点名)），顶层主图为 None。
    # 多视图时这里只是**容器**：下钻栈由 JS 按点击轨迹往里追加（见 MULTI_JS）。
    crumbs_html, crumbs_cls = '', ''
    if multi:
        # 顶层主图没有"回程路"，先不摆空条——下钻栈由 JS 在第一次下钻时建（见 `_ensureCrumbs`）。
        back = (f'<a href="{esc(parent[0])}">← 返回主图（{esc(parent[1])}）</a>'
                if parent else '')
        crumbs_cls = ' has-crumbs' if parent else ''
        crumbs_html = (f'<div class="crumbs" id="crumbs">{back}</div>\n') if parent else ''
        return crumbs_html, crumbs_cls
    if parent:
        href, pname = parent
        crumbs_cls = ' has-crumbs'
        crumbs_html = (f'<a class="crumbs" href="{esc(href)}">← 返回主图'
                       f'（{esc(pname)}）</a>\n')
    return crumbs_html, crumbs_cls


def _build_page_body(multi, blocks, main_svg):
    """生成 body 内的视图容器：多视图每个视图一块 `.chart-container`，单视图只有主图。"""
    # 单视图 → 与多视图之前逐字节相同；多视图 → 每个视图一个 `.chart-container`，只显示当前的。
    if multi:
        return ''.join(
            f'<div class="view{" cur" if i == 0 else ""}" data-view="{esc(k)}" '
            f'data-title="{esc(tt)}">\n'
            f'<div class="chart-container" style="width:{round(w)}px;height:{round(h)}px">\n'
            f'{sv}\n</div>\n</div>\n' for i, (k, tt, sv, w, h) in enumerate(blocks))
    return f'<div class="chart-container">\n{main_svg}\n</div>\n'


def _build_html_document(L, H, t, tips_json, crumbs_html, head_html, body, multi):
    """把标题/视图/提示数据套进整页 HTML 模板，并注入多视图 CSS/JS 与点击行为。"""
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{esc(L.dsl['meta']['title'])}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:"Microsoft YaHei","Segoe UI",sans-serif; background:#f0f2f5; padding:20px; }}
.chart-container {{ position:relative; margin:0 auto; width:{L.width}px; height:{H}px;
                   background:white; border:1px solid #ddd; box-shadow:0 2px 8px rgba(0,0,0,0.1); overflow:auto; }}
.node-tooltip {{ position:fixed; background:#fffef5; border:1px solid #d6b656; border-radius:6px;
                padding:10px 14px; box-shadow:0 4px 16px rgba(0,0,0,0.18); z-index:2000;
                max-width:320px; font-size:12px; line-height:1.6; pointer-events:none; display:none; }}
.node-tooltip .tt-title {{ font-weight:bold; color:#9673a6; margin-bottom:6px;
                          border-bottom:1px solid #f0e6d2; padding-bottom:4px; }}
/* "这里能点"就写在**节点名右侧**（见 D-80）：悬浮框是"用户已经伸手去点"的那一刻，
   在此处说一句最省事，也最不会跟节点内那几行语义文字抢地方。灰字、比名称小一号。 */
.node-tooltip .tt-sub {{ font-weight:normal; font-size:11px; color:#999999; margin-left:8px; }}
.node-tooltip .tt-content {{ color:#444; white-space:pre-line; }}
svg {{ display:block; }}
.t1 {{ font-size:{t['name']['size']}px; font-weight:bold; fill:{t['name']['color']}; text-anchor:middle; }}
.tm {{ font-size:{t['executor']['size']}px; fill:{t['executor']['color']}; text-anchor:middle; }}
.tt2 {{ font-size:{t['time']['size']}px; font-weight:bold; fill:{t['time']['color']}; text-anchor:middle; }}
.lab {{ font-size:{t['label']['size']}px; font-weight:bold; text-anchor:middle; }}
.lab-r {{ fill:#ffffff; stroke-width:1; }}
.shape {{ stroke-width:2; }}
/* 可下钻节点的记号是**框内一道内衬线**（同形状内缩 2px / 1px / 55%，见 D-78）：
   它在包围盒内，所以端口、连线、相邻墨迹、包围盒与网格一样都不碰。静态可见是它的本分。
   **它没有动画**：曾经悬停时另跑一段光沿它转一圈，与"连线上已经在跑的那道流光"重复了一遍
   （见 D-80），撤掉了——"这里能点"改由悬浮框标题行右侧的灰字说。 */
.ndg {{ cursor:default; }}
.ndg[data-sub] {{ cursor:pointer; }}
.ndg:hover .shape {{ stroke-width:3; }}
/* 子图/主图之间的面包屑：走进去要能走出来，否则下钻比不做还糟。*/
.crumbs {{ position:fixed; top:0; left:0; z-index:1600; padding:6px 14px;
          font-size:12px; color:#555555; text-decoration:none;
          background:#ffffff; border-right:1px solid #e1d5e7; border-bottom:1px solid #e1d5e7;
          border-bottom-right-radius:6px; }}
.crumbs:hover {{ color:#185FA5; background:#f5f9ff; }}
/* 标题模块与面包屑都是 fixed，左上一角会重叠——有面包屑时把标题模块整体下移一格。*/
.headmod.has-crumbs {{ padding-top:34px; }}
.edge {{ stroke-width:2; fill:none; }}
/* 主干边上的**流光** = **两层同一道光**（见 D-79）：晕（宽 + 模糊 + 暗）+ 芯（窄 + 实 + 加深）。
   **一律不用白色**：白只在深色底上发光（svg-flow 的默认轨道 #1a1a2e、ECharts 的深色地图），
   我们的底是白画布与浅色填充——白在那儿只能"把线擦亮"，读作擦除而不是发光。
   两层共用同一套 dash 与时长 ⇒ 芯和晕一起走。`.is-run` 只挂在晕上、芯用**相邻兄弟**选择器跟随：
   JS 那套"实线边 ↔ 流光元素"的一一配对因此不用改（层数变了，配对仍是 1:1）。
   纯装饰、不承载语义 ⇒ 「减少动态效果」时直接不画；底边仍在，信息一点不丢。 */
.edge-flow {{ fill:none; stroke:{EDGE_FLOW_COLOR}; stroke-width:{EDGE_FLOW_WIDTH};
              stroke-opacity:0.4;
              stroke-linecap:round; stroke-dasharray:{EDGE_FLOW_DASH[0]} {EDGE_FLOW_DASH[1]};
              stroke-dashoffset:{EDGE_FLOW_DASH[0] + EDGE_FLOW_DASH[1]};
              opacity:0; pointer-events:none; }}
.edge-flow-core {{ fill:none; stroke:{EDGE_FLOW_CORE}; stroke-width:{EDGE_FLOW_CORE_WIDTH};
                   stroke-linecap:round; stroke-dasharray:{EDGE_FLOW_DASH[0]} {EDGE_FLOW_DASH[1]};
                   stroke-dashoffset:{EDGE_FLOW_DASH[0] + EDGE_FLOW_DASH[1]};
                   opacity:0; pointer-events:none; }}
/* **悬停期间循环**：只在悬停相关节点时给叠层挂 .is-run，鼠标离开就摘掉（JS）。
   为什么不是跑一趟：一触发就跑完即停，光一闪而过，反而像"页面抖了一下"——
   循环才读得出"光顺着流程一条条走下去"这件事。为什么**不是常驻**：常驻会把"实线/虚线"
   这条作者语义磨掉，也看不出这束光是在回答"我现在看着谁"（第一版就是常驻无限循环）。
   为什么不给相关边加粗：同一个意思说两遍——边上的光已经在回答"哪儿相关"，实线/虚线的
   线宽口径也就不必为悬停再开一个例外（见 D-80）。 */
.edge-flow.is-run, .edge-flow.is-run + .edge-flow-core {{
                     animation:edge-flow-trace {EDGE_FLOW_MS}ms linear infinite;
                     animation-delay:calc(var(--step, 0) * {EDGE_FLOW_STAGGER}ms); }}
@keyframes edge-flow-trace {{
  0%   {{ stroke-dashoffset:{EDGE_FLOW_DASH[0] + EDGE_FLOW_DASH[1]}; opacity:0; }}
  12%  {{ opacity:1; }}
  88%  {{ opacity:1; }}
  100% {{ stroke-dashoffset:0; opacity:0; }}
}}
/* 悬停：**只加不减**。悬停节点自己的描边加粗由 `.ndg:hover .shape` 给（静态记号，
   「减少动态效果」下也成立），相关主干边在悬停期间循环跑流光。
   **不压暗任何东西**：压暗（曾经 0.13）会连 ⚠ 的橙/红描边、主体配色、执行者小字一起抹掉，
   那是**删信息**；而"哪些是相关的"已经有加法记号，不需要再来一遍减法（见 D-76）。 */
@media (prefers-reduced-motion: reduce) {{
  .edge-flow {{ display:none; }}
}}
/* 标题模块：与正文模块（画布）分离的一块，固定在视窗顶部；滚动时不离视窗。
   底部内边距由脚本按实际高度回填，长图滚到哪都看得到"这是什么图 / 颜色是谁"。*/
.headmod {{ position:fixed; top:0; left:0; right:0; z-index:1500; background:#ffffff;
           border-bottom:1px solid #e1d5e7; box-shadow:0 1px 4px rgba(0,0,0,0.08);
           padding:10px 20px 12px; }}
.headmod h1 {{ font-size:16px; font-weight:bold; color:#333333; text-align:center; margin:0 0 8px; }}
.headmod .legend {{ display:flex; flex-wrap:wrap; justify-content:center; align-items:center;
                    gap:6px 18px; font-size:11px; color:#555555; }}
.headmod .lg {{ display:inline-flex; align-items:center; gap:6px; }}
.headmod .sw {{ display:inline-block; width:34px; height:14px; border:1.5px solid; border-radius:3px; }}
{{multi_css}}</style>
</head>
<body>
{crumbs_html}{head_html}
{body}<div class="node-tooltip" id="nodeTooltip">
  <div class="tt-title"><span id="ttTitle"></span><span class="tt-sub" id="ttSub"></span></div>
  <div class="tt-content" id="ttContent"></div>
</div>
{_defs_block(L.cfg)}
<script>
var TIPS = {tips_json};
var tooltip = document.getElementById('nodeTooltip');
var ttTitle = document.getElementById('ttTitle');
var ttSub = document.getElementById('ttSub');
var ttContent = document.getElementById('ttContent');
var headmod = document.getElementById('headmod');
var HEAD_BOTTOM = 0;
function fitHead() {{
  var h = headmod.offsetHeight;
  document.body.style.paddingTop = (h + 20) + 'px';   // 正文让出标题模块的位置，避免被盖住
  HEAD_BOTTOM = h + 12;
}}
fitHead();
window.addEventListener('resize', fitHead);
// 视窗位置记忆（见 D-48）：下钻进子图再返回，视窗要回到**离开时的位置**。
// 大图看到一半点进去、回来被扔回左上角，等于把人正在盯的上下文抹掉——
// 这比不做下钻还累：功能是"按需展开"，不是"每次重新找路"。
// 存 sessionStorage（同一标签页有效，关掉即忘），键带上本页路径，主图与每张子图各记各的。
// 初始键必须**带主视图后缀**：`showView()` 切走时会把键换成带视图 key 的（见 D-52），
// 主视图的位置从此写进 `#__main__` 那个键。这里若不带后缀，页面刷新后初始键与它不同名，
// 主视图就读回不到自己最后停的地方——"返回时视窗停在你离开时的位置"对主图失效。
// 两个滚动层都记：`body` 是实际的滚动层（画布多高容器就多高，撑着整页滚），
// `.chart-container` 现在不滚，但容器高度一旦改成视窗高就会变成滚动层——两个都存，不必回头改。
var SCROLL_KEY = 'fc-scroll:' + location.pathname + '#{MAIN_VIEW}';
var _cc = document.querySelector('.chart-container');
function _snap() {{
  return {{ x: window.scrollX || document.documentElement.scrollLeft || 0,
           y: window.scrollY || document.documentElement.scrollTop || 0,
           cl: _cc ? _cc.scrollLeft : 0, ct: _cc ? _cc.scrollTop : 0 }};
}}
function saveScroll() {{
  try {{ sessionStorage.setItem(SCROLL_KEY, JSON.stringify(_snap())); }} catch (e) {{}}
}}
function restoreScroll() {{
  var raw = null;
  try {{ raw = sessionStorage.getItem(SCROLL_KEY); }} catch (e) {{}}
  if (!raw) return;
  var p; try {{ p = JSON.parse(raw); }} catch (e) {{ return; }}
  if (_cc) {{ _cc.scrollLeft = p.cl || 0; _cc.scrollTop = p.ct || 0; }}
  window.scrollTo(p.x || 0, p.y || 0);
}}
// 必须在 fitHead() 之后：它要按标题模块实测高度回填 body.paddingTop，
// 布局没定就滚，滚到的位置是错的。字体加载完还会再抖一次，故 load 时补一次。
restoreScroll();
window.addEventListener('load', restoreScroll);
var _st = null;
function _onScroll() {{
  clearTimeout(_st); _st = setTimeout(saveScroll, 200);   // 节流，滚动中别狂写
}}
window.addEventListener('scroll', _onScroll);
// `scroll` 事件**不冒泡**，所以容器内部滚动不会冒到 window 上——必须单独挂一个。
// 现在容器不滚（多高就多高），挂了也不写脏数据；哪天容器改成视窗高，这条就是现成的。
if (_cc) _cc.addEventListener('scroll', _onScroll);
window.addEventListener('beforeunload', saveScroll);      // 点进子图/走面包屑都会触发
function positionTip(g) {{
  var r = g.getBoundingClientRect();
  var left = r.right + 12, top = r.top;
  if (left + tooltip.offsetWidth > window.innerWidth) left = r.left - tooltip.offsetWidth - 12;
  if (top + tooltip.offsetHeight > window.innerHeight) top = window.innerHeight - tooltip.offsetHeight - 10;
  if (top < HEAD_BOTTOM) top = HEAD_BOTTOM;
  tooltip.style.left = left + 'px';
  tooltip.style.top = top + 'px';
}}
document.querySelectorAll('.ndg').forEach(function(g) {{
  g.addEventListener('mouseenter', function() {{
    var d = TIPS[g.dataset.id];
    if (!d) return;
    ttTitle.innerText = d.title;
    // "这里能点"只在**真的内嵌了子图**的节点上说（`d.sub` 就是那个判据，见 D-80）：
    // 描述里声明了子表、但那张表拿不到 DSL 的节点不画内衬线、不给入口，也就不该说这句话。
    ttSub.innerText = d.sub ? '（点击查看流程详情）' : '';
    var parts = [];
    if (d.pend) parts.push('⚠ ' + d.pend);
    parts.push('执行主体：' + d.subject, '执行者：' + d.executor);
    if (d.input) parts.push('输入：' + d.input);
    if (d.basis) parts.push('依据：' + d.basis);
    if (d.output) parts.push('输出：' + d.output);
    if (d.time) parts.push('行动所需时间：' + d.time);
    parts.push('下个节点：' + (d.route.indexOf('\\n') >= 0 ? '\\n' + d.route : d.route));
    parts.push('节点描述：' + d.desc);
    if (d.sub) parts.push('Ctrl/⌘+点击：在新窗口打开（保留主图上下文便于对照）');
    ttContent.innerText = parts.join('\\n');
    tooltip.style.display = 'block';
    positionTip(g);
  }});
  g.addEventListener('mousemove', function() {{ positionTip(g); }});
  g.addEventListener('mouseleave', function() {{ tooltip.style.display = 'none'; }});
  // 子流程下钻（见 D-47）：单击跳转、Ctrl/⌘+点击新标签页（保留主图上下文便于对照）。
  // 没有 data-sub 的节点不绑行为——不弹窗、不报错，就是"点了没反应"。
  g.addEventListener('click', function(ev) {{
    var d = TIPS[g.dataset.id];
    if (!d || !d.sub) return;
{{click_body}}
  }});
}});
/* 悬停：**只加不减**。悬停节点 → 与它相连的主干边在**悬停期间循环**跑流光，鼠标离开即停。
   相关边**不加粗**（见 D-80）：边上那道流光已经在回答"哪儿相关"，加粗是同一个意思说第二遍。
   **不压暗任何东西**（见 D-76）：压暗会把别的节点上的 ⚠ 描边、主体配色、执行者小字一起抹掉——
   那是删信息；而"哪些是相关的"已经有加法记号，不必再来一遍减法。 */
(function () {{
  // **对每个 svg 分别接线**：单文件里可能内嵌多个子视图（D-52 下钻，主图 + 若干子图各一个 <svg>），
  // 抓某一个 id 只会给主图接线、子图点了没反应；而且这些 <svg> 本来就没有 id 属性，
  // getElementById 会返回 null，整个函数静默退出（第一版就是这么"看起来没反应"的）。
  function wire(svg) {{
  var edges = [].slice.call(svg.querySelectorAll('path.edge'));
  var flows = [].slice.call(svg.querySelectorAll('path.edge-flow'));
  // 流光只给实线（主干）边生成，所以按出现顺序与实线边一一配对，不能按下标硬取。
  var flowOf = [], fi = 0;
  edges.forEach(function (e) {{
    flowOf.push(e.getAttribute('stroke-dasharray') ? null : (flows[fi++] || null));
  }});
  function clear() {{
    flows.forEach(function (f) {{ f.classList.remove('is-run'); }});
  }}
  function focus(id) {{
    if (!id) return;
    clear();
    edges.forEach(function (e, i) {{
      var a = e.getAttribute('data-from'), b = e.getAttribute('data-to');
      if (a !== id && b !== id) return;
      var f = flowOf[i];
      if (f) f.classList.add('is-run');     // 循环由 CSS 的 infinite 承担，这里只开关
    }});
  }}
  [].forEach.call(svg.querySelectorAll('g.ndg'), function (g) {{
    /* 悬停配对用 **`data-nid`（DSL 的原始节点编号）**，与边的 `data-from/to` 同口径（见 D-90）：
       `data-id` 是 TIPS 的键、子视图里带 `视图key::` 前缀（防跨表重号），拿它去比 `data-from`
       永远不相等——子视图于是"悬停什么也不亮"（用户报的"流光效果没有"）。
       主视图没有前缀、两者取值相同，所以这个 bug 只在子视图里显形。 */
    g.addEventListener('mouseenter', function () {{ focus(g.getAttribute('data-nid')); }});
    g.addEventListener('mouseleave', clear);
  }});
  }}
  [].forEach.call(document.querySelectorAll('svg'), wire);
}})();
{{multi_js}}</script>
</body>
</html>
'''.replace('{multi_css}', MULTI_CSS if multi else '').replace(
        '{multi_js}', MULTI_JS if multi else '').replace(
        '{click_body}', CLICK_MULTI if multi else CLICK_SINGLE)


def _write_html_output(out_path, html, L, H, n_views, multi):
    """落盘 HTML 并打印一行摘要，返回退出码 0。

    `n_views` 是**真的拼进产物**的子视图张数（主视图不算），不是 `collect_views` 那份 intent 清单
    的长度——两者只在这两种情况下不等：读不动的表（视图块拼不出来）与被截断的表（压根没收）。
    """
    Path(out_path).write_text(html, encoding='utf-8', newline='\n')
    extra = f'  内嵌子图: {n_views}' if multi else ''
    print(f'生成: {out_path}  节点: {len(L.dsl["nodes"])}  边: {len(L.edges)}  画布: {L.width}x{H}{extra}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='DSL → HTML')
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    args = ap.parse_args()
    if not Path(args.input).exists():
        print(f'✗ 找不到输入文件: {args.input}')
        return 1
    out = args.output or str(Path(args.input).with_suffix('.html'))
    return render(args.input, out)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
