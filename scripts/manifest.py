# -*- coding: utf-8 -*-
"""manifest.py — 渲染契约：自检阶段产出结构事实，渲染后据此反查产物。

**为什么需要**：结构校验查《流程表》、质量门禁查 `flow.yaml`——两者都不看渲染产物（见 DECISIONS.md D-11）。
调用方：`table_to_dsl --write` 产出、`build.py` 渲染后自动跑。
退出码：0 = 契约对上；1 = **契约校验不过** / 缺 PyYAML（渲染前的那道自检）。
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from semantics import is_pending
from console import warn
import deps

try:
    import yaml
except ImportError:
    yaml = None

# 产物名只许由 `artifact_stem` / `manifest_path_for` 算（D-51）：这里不再摆一个写死的名字常量。

# 主视图的视图标识。住在这里的理由：它是**渲染契约**的一部分（审核侧要按它从产物里切出主视图
# 那一段），而契约的定义者就是本模块；生成侧 `render_html` 引用它，方向是「模块 → 公共层」。
MAIN_VIEW = '__main__'


def manifest_path_for(yaml_path):
    """契约文件与 DSL 同名同目录（flow.yaml → flow.manifest.json）。

    按名派生而不是写死——`sync` 也拿这条 --write 跑临时 DSL，写死会覆盖主契约。
    """
    p = Path(yaml_path)
    return p.with_name(p.stem + '.manifest.json')


def dsl_fingerprint(yaml_path):
    """DSL 文件指纹，用来判断"契约是否已过期"。

    没有它，手改过 flow.yaml 却没重跑 `--write` 时，产物会被冤枉成"多画了节点"。两种错因的修法不同，必须分开。
    """
    return hashlib.sha256(Path(yaml_path).read_bytes()).hexdigest()[:16]


def source_fingerprint(ft_path):
    """《流程表》指纹：答"事实源自上次渲染后动过没有"。

    与 `dsl_fingerprint` 分工不同：那个答"契约对着哪版 DSL"，这个答"表还是不是渲染时那一版"。
    只有它能发现**手工改了表、而 yaml 一个字没动**的情况——那时契约不报过期、产物与契约逐项一致、
    八项门禁全绿，盘上却是一份落后于事实源的图。
    """
    return hashlib.sha256(Path(ft_path).read_bytes()).hexdigest()[:16]


def _manifest_counts(nodes, edges):
    """契约计数：节点 / 边 / 按类型 / 带标签边 / 回路 / 待定节点。"""
    by_type = Counter(n['type'] for n in nodes)
    return {
        'nodes': len(nodes),
        'edges': len(edges),
        'by_type': dict(sorted(by_type.items())),
        'labeled_edges': sum(1 for e in edges if e.get('label')),
        # 回路在 DSL 里是 `kind: loop`（不是 is_loop）——auto_layout 之后边只保留 from/to/kind/polarity
        'loop_edges': sum(1 for e in edges if e.get('kind') == 'loop'),
        'pending_nodes': sum(1 for n in nodes if is_pending(n.get('desc'))),
    }


def build(dsl, source='', dsl_sha='', ft_sha=''):
    """DSL → 契约清单。字段都是**可逐项比对**的，不是只给个总数。"""
    nodes = dsl.get('nodes') or []
    edges = dsl.get('edges') or []
    meta = dsl.get('meta') or {}
    return {
        'title': meta.get('title', ''),
        'layout': meta.get('layout', 'flow'),
        'source': source,
        'dsl_sha256': dsl_sha,
        'source_sha256': ft_sha,
        'counts': _manifest_counts(nodes, edges),
        'node_ids': sorted(n['id'] for n in nodes),
        'edges': sorted([e['from'], e['to']] for e in edges),
    }


def _main_slice(t):
    """多视图单文件（D-52）时只取**主视图**那一段再反解。

    内嵌进来的子图同样带 `data-id` / `data-from`，不切出来的话产物审核会把子图的
    节点与边算到主图头上（报"多了 N 个节点"）——错的不是产物，是反解的口径。
    主视图永远是第一个 `<div class="view">`，所以切到下一个 `class="view"` 之前即可。
    """
    i = t.find('data-view="' + MAIN_VIEW + '"')
    if i < 0:
        return t                       # 单视图（或老产物）：整篇就是主视图
    j = t.find('<div class="view"', i)
    return t[:j] if j > 0 else t


# ----------------------------------------------------------------产物反解
def read_html(path):
    """从 flow.html 反解 (节点 id 列表, 边列表)（返回列表而非集合，否则平行边的重数被吞）。

    靠渲染器写在元素上的 `data-id` / `data-from` / `data-to`——只数元素个数不够，画错一条边也得发现。
    """
    t = _main_slice(Path(path).read_text(encoding='utf-8'))
    ids = re.findall(r'class="ndg" data-id="([^"]*)"', t)
    edges = []
    for tag in re.findall(r'<path class="edge"[^>]*>', t):
        m1 = re.search(r'data-from="([^"]*)"', tag)
        m2 = re.search(r'data-to="([^"]*)"', tag)
        if m1 and m2:
            edges.append((m1.group(1), m2.group(1)))
    return ids, edges


def _default_shapes():
    """随包字典里的 `shapes`（type → {shape, …}）——形状反查的唯一依据。

    不走 `engine.load`（那要一份 DSL）：形状是**字典级**的事实，DSL 只能覆盖 subject 与 layout，
    `Model` 从不改 `shapes`（见 engine.py 的 `Model.__init__`）。

    **读不出来要吭声**（2026-09-19 修，D-129）：原先读不动就**静默退回 `{}`**，而症状是
    **下游报一堆"形状不符"**——把"字典缺 `shapes:` 段"说成"产物画错了形状"，诊断正好指反。
    这与"降级必须留痕"直接冲突，所以每一条退化路径都留痕（走 `console.warn`：本模块是纯库，
    它不能假定调用方把 stderr 配成了 utf-8）。
    """
    p = Path(__file__).with_name('dictionary.yaml')
    try:
        doc = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    except (OSError, ValueError, AttributeError) as e:
        warn(f'⚠ 读不到随包字典 `{p.name}`（{type(e).__name__}）——`shapes` 退化为空，'
             f'下面报出的"形状不符"多半是这一条引起的')
        return {}
    shapes = doc.get('shapes') if isinstance(doc, dict) else None
    if not isinstance(shapes, dict) or not shapes:
        warn(f'⚠ 随包字典 `{p.name}` 的 `shapes:` 段缺失或为空——形状反查退化为空，'
             f'下面报出的"形状不符"多半是这一条引起的')
        return {}
    return shapes


def _compare_shapes(manifest, html_text):
    """契约里的**类型数量** ←→ 产物里真正画出来的**形状数量**（形状从产物读，见 D-32）。

    为什么单列这一轮：`by_type` / `labeled_edges` / `loop_edges` / `pending_nodes` 四个计数
    此前只有 `summary()` 在打印，**从不参与反查**——于是"判断节点画成矩形""边标签丢了"这类
    错都能全绿通过（几何自检按产物自称的形状反推类型，永远自洽）。这条补最省的那一半：
    类型→形状的映射由字典给出，产物里的形状由 `_html_nodes` 读回，两边数量必须相等。
    形状读不出/字典缺该类型时**显式报错**，不静默跳过。
    """
    by_type = (manifest.get('counts') or {}).get('by_type') or {}
    shapes = _default_shapes()
    if not shapes:
        return ['字典里没有 shapes，类型→形状无法反解（形状画错这类问题本轮不设防）']
    want = Counter()
    for t, n in by_type.items():
        shp = (shapes.get(t) or {}).get('shape')
        if not shp:
            return [f'契约里的节点类型 {t} 在字典 shapes 里没有形状——无法反解']
        want[shp] += n
    got = Counter()
    for nid, g in _html_nodes(html_text).items():
        if not g.get('shape'):
            return [f'节点 {nid} 的形状读不出来——这一轮无法反解']
        got[g['shape']] += 1
    if want != got:
        return [f'形状分布与类型不符：契约要 {dict(want)}，产物里是 {dict(got)}'
                '（类型画错、或 type→shape 的映射改了没同步）']
    return []


def read_drawio(path):
    """从 flow.drawio 反解 (节点 id 列表, 边列表)。复用 xml_reader——它已经会跳过标题/图例/泳道底色。"""
    from xml_reader import read as _read
    # 与 `geometry_from_drawio`（下面 :227）**同一读法**：带 BOM 的 drawio 按裸 utf-8 读会让
    # 首个字符变成 \ufeff，ET.fromstring 直接抛解析错——同一份文件两条口径，迟早分叉（D-84）。
    d = _read(Path(path).read_text(encoding='utf-8-sig'))
    return [n['id'] for n in d['nodes']], [(e['from'], e['to']) for e in d['edges']]


# ----------------------------------------------------------------几何表（产物真实坐标）
def _html_shape(body):
    """节点组内的形状元素 → (w, h, shape)。形状**从产物读**，不从字典反查类型再映射。"""
    m = re.search(r'<polygon class="shape" points="([^"]*)"', body)
    if m:                                   # points="0,-h/2 w/2,0 0,h/2 -w/2,0"
        v = [float(x) for x in re.findall(r'-?[\d.]+', m.group(1))]
        if len(v) >= 4:
            return abs(v[2]) * 2, abs(v[1]) * 2, 'rhombus'
    m = re.search(r'<ellipse class="shape" rx="([\d.]+)" ry="([\d.]+)"', body)
    if m:
        return float(m.group(1)) * 2, float(m.group(2)) * 2, 'ellipse'
    m = re.search(r'<rect class="shape" x="-?[\d.]+" y="-?[\d.]+" width="([\d.]+)" height="([\d.]+)"'
                  r'(?: rx="([\d.]+)")?', body)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        rx = float(m.group(3)) if m.group(3) else 0.0
        # **胶囊也是 rect**：渲染器给端点画的是 `rx = h/2`（左右半圆）。不读 `rx` 就把端点
        # 一并算成"圆角矩形"，于是"端点被画成任务框"这种错查不出来——形状反查（D-84）靠这一项。
        # 阈值取半高：`rounded` 的 rx 来自字典 arc（个位数像素），不会碰到它。
        return w, h, ('stadium' if rx >= min(w, h) / 2 - 0.5 else 'rounded')
    return None, None, None


def _html_nodes(t):
    """主视图的节点组 → {id: {rect, shape}}（属性顺序与个数都不假定）。"""
    nodes = {}
    # 属性之间**不假定顺序、不假定只有两个属性**：`data-sub`（子流程下钻，见 D-47）会插在
    # `data-id` 与 `transform` 中间。写死 `data-id="…" transform=` 的话，带子流程的节点会被
    # 这条正则整个漏掉——产物审核报"少了 N 个节点"，但图上明明画着（实测：4 节点只解析出 3 个）。
    for m in re.finditer(r'<g class="ndg"([^>]*)>(.*?)</g>', t, re.S):
        attrs, body = m.group(1), m.group(2)
        a_id = re.search(r'\bdata-id="([^"]*)"', attrs)
        a_tf = re.search(r'transform="translate\((-?[\d.]+)[ ,]+(-?[\d.]+)\)"', attrs)
        if not (a_id and a_tf):
            continue
        nid, cx, cy = a_id.group(1), float(a_tf.group(1)), float(a_tf.group(2))
        w, h, shp = _html_shape(body)
        if w is None:
            continue
        nodes[nid] = {'rect': (cx - w / 2, cy - h / 2, w, h), 'shape': shp}
    return nodes


def _html_edges(t):
    """主视图的边 path → [{from, to, pts}]。"""
    edges = []
    for m in re.finditer(r'<path class="edge" data-from="([^"]*)" data-to="([^"]*)" d="([^"]*)"', t):
        pts = [(float(x), float(y)) for x, y in re.findall(r'[ML]\s*(-?[\d.]+)[ ,]+(-?[\d.]+)', m.group(3))]
        edges.append({'from': m.group(1), 'to': m.group(2), 'pts': pts})
    return edges


def _html_canvas_bands(t, nodes):
    """画布尺寸（viewBox，缺失则按节点外包盒）+ 里程碑带宽 + 泳道底色外包盒。"""
    vm = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', t)
    if vm:
        canvas = (float(vm.group(1)), float(vm.group(2)))
    else:
        canvas = (max((v['rect'][0] + v['rect'][2] for v in nodes.values()), default=0.0),
                  max((v['rect'][1] + v['rect'][3] for v in nodes.values()), default=0.0))
    # 左侧里程碑带：泳道底色带一律从 x=0 起画（`svg_lanes` 的阶段带），取最宽的那条
    band = max((float(w) for w in re.findall(r'<rect x="0" y="[-\d.]+" width="([\d.]+)"', t)), default=0.0)
    # 泳道底色外包盒：`svg_lanes` 那一组 `<rect>`（节点框在 `<g transform>` 里、x 为负，不会混进来）
    lanes = None
    grp = re.search(r'<g class="lanes">(.*?)</g>', t, re.S)
    if grp:
        for x, y, w, h in re.findall(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"', grp.group(1)):
            x, y, w, h = float(x), float(y), float(w), float(h)
            lanes = (x, y, x + w, y + h) if lanes is None else (
                min(lanes[0], x), min(lanes[1], y), max(lanes[2], x + w), max(lanes[3], y + h))
    return canvas, band, lanes


def geometry_from_html(path):
    """从 flow.html 反解几何：节点组（`translate` 中心 + 形状局部尺寸）+ 边的 `d` 折线。

    只反解**主视图**（见 `_main_slice`）：内嵌的子图坐标是另一张画布的，混进来必然"重叠"。
    """
    t = _main_slice(Path(path).read_text(encoding='utf-8'))
    nodes = _html_nodes(t)
    edges = _html_edges(t)
    canvas, band, lanes = _html_canvas_bands(t, nodes)
    return {'nodes': nodes, 'edges': edges, 'canvas': canvas, 'band': band,
            'lanes': lanes, 'source': Path(path).name}


def read_svg(path):
    """从 `<流程名>-flow.svg` 反解 (节点 id 列表, 边列表)。

    **刻意复用 `read_html`**：`render_svg` 与 `render_html` 用同一套元素约定
    （`g.ndg[data-id]` + `path.edge[data-from/data-to]`）。共用同一批正则意味着
    "哪天有人改了两边之一"，这里会立刻**读不出来**，而不是悄悄少几个节点。
    """
    return read_html(path)


def geometry_from_svg(path):
    """从 `<流程名>-flow.svg` 反解几何。与 `geometry_from_html` 同源（元素约定相同）。"""
    return geometry_from_html(path)


def geometry_from_drawio(path):
    """从 `.drawio` 反解几何。与 `geometry_from_html` 并列——两者都是"产物 → 几何表"的**反解器**。

    反解器是**插件契约的另一半**（ARCHITECTURE.md 第九节 W6）：只注册渲染器、不注册反解器，
    那个产物就没人复核——`artifact_geometry` 是几何门禁的唯一入口，它得靠反解器才读得懂产物。
    """
    from xml_reader import geometry as _geom, read as _read
    return _geom(_read(Path(path).read_text(encoding='utf-8-sig')))


def artifact_geometry(path, reader=None):
    """产物路径 → 几何表（按扩展名分流）。几何门禁的唯一入口。

    `reader` 由编排层从渲染器注册表带下来（每类渲染器自己声明怎么被反解）；
    不传时按扩展名兜底 —— 单跑 `validate.py --artifact` 时走这条。
    """
    if reader is not None:
        return reader(path)
    p = Path(path)
    # `.svg` 与 html **共用同一套元素约定**（`render_svg` 就是照它发射的）⇒ 同一支解析器。
    # 不加这一支的后果实测过：`validate.py --artifact x.svg --dump` 会掉进下面的 drawio 兜底，
    # 被当成 drawio XML 读 ⇒ **命令行单跑 svg 的产物校验直接失败**（build 链路因为有注册表传
    # reader 才没事）。这正是第九节警告过的"第三种格式被按错误格式解析"，它真的会发生。
    if p.suffix.lower() in ('.html', '.htm', '.svg'):
        return geometry_from_html(p)
    return geometry_from_drawio(p)


_EXT_SCHEMES_SKIP = ('http://www.w3.org/', 'https://www.w3.org/')


def _external_refs(path, label):
    """产物自包含硬检查（D-55，借鉴 byai 的 HAS_EXTERNAL）：单文件交付（D-52）承诺离线可开，
    外链（图片/字体/脚本引了 http）一旦混进，断网或内网环境就破——此前只有渲染端保证，
    这是产物侧复核。XML 命名空间（w3.org）是标识不是资源引用，豁免。"""
    t = Path(path).read_text(encoding='utf-8', errors='replace')
    urls = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', t, re.I)
    urls += re.findall(r'url\(\s*["\']?(https?://[^)"\']+)', t, re.I)
    if label.endswith('.drawio'):
        urls += re.findall(r'image=(https?://[^;"\s]+)', t)
    bad = sorted({u for u in urls if not u.startswith(_EXT_SCHEMES_SKIP)})
    if not bad:
        return []
    return [f'{label} 含 {len(bad)} 处外链（自包含被破坏，离线打开会缺资源）：'
            + '；'.join(bad[:5]) + ('…' if len(bad) > 5 else '')]


# ----------------------------------------------------------------比对
def _stale_manifest_error(manifest, yaml_path):
    """契约新鲜度：给了 yaml_path 就先验指纹，过期返回错误列表（否则空列表）。"""
    if not (yaml_path and manifest.get('dsl_sha256')):
        return []
    now = dsl_fingerprint(yaml_path)
    if now != manifest['dsl_sha256']:
        return [f'契约已过期：它是对着旧版 {Path(yaml_path).name} 生成的'
                f'（契约记 {manifest["dsl_sha256"]}，当前 {now}）→ 重跑 table_to_dsl --write 再审核']
    return []


def source_stale(ft_path, manifest_path):
    """《流程表》自上次渲染后是否被直改过 → `(state, 说明)`。

    `state` 三值：`same` / `changed` / `nobase`（没有契约，或契约是旧版写的、没记表指纹）。
    **它只回答"变没变"，不回答"变了什么"**——"变了什么"要靠读回图再逐项 diff（`sync.py`）。
    这条分工是有意的：哈希便宜、能当触发器；判性质必须逐项比，哈希做不到。
    """
    ft, mf = Path(ft_path), Path(manifest_path)
    if not mf.exists():
        return 'nobase', f'没有渲染契约 {mf.name}（首轮，或它被删了）'
    try:
        rec = (json.loads(mf.read_text(encoding='utf-8')) or {}).get('source_sha256') or ''
    except (OSError, ValueError) as e:
        return 'nobase', f'渲染契约读不动（{type(e).__name__}）'
    if not rec:
        return 'nobase', '渲染契约是旧版写的，没记《流程表》指纹'
    now = source_fingerprint(ft)
    if now == rec:
        return 'same', now
    return 'changed', f'契约记 {rec}，现在是 {now}'


def _compare_ids_edges(want_ids, want_edges, label, ids, edges):
    """一份产物的节点/边集合 vs 契约 → 错误列表。"""
    errs = []
    got_ids, got_edges = set(ids), Counter(edges)
    miss_n, extra_n = want_ids - got_ids, got_ids - want_ids
    if miss_n:
        errs.append(f'{label} 少了 {len(miss_n)} 个节点：{"、".join(sorted(miss_n)[:8])}')
    if extra_n:
        errs.append(f'{label} 多了 {len(extra_n)} 个契约里没有的节点：{"、".join(sorted(extra_n)[:8])}')
    miss_e = want_edges - got_edges
    extra_e = got_edges - want_edges
    if miss_e:
        errs.append(f'{label} 少了 {sum(miss_e.values())} 条边：'
                    + '、'.join(f'{a}→{b}' for a, b in sorted(miss_e)[:8]))
    if extra_e:
        errs.append(f'{label} 多了 {sum(extra_e.values())} 条契约里没有的边：'
                    + '、'.join(f'{a}→{b}' for a, b in sorted(extra_e)[:8]))
    return errs


def check(manifest, html=None, drawio=None, yaml_path=None, products=None):
    """契约 vs 产物 → 错误列表（空 = 逐项一致）。

    给了 yaml_path 就先验契约新鲜度再比产物——两种错因的修法完全不同，必须分开报。

    `products` 是**通用入口**（W6）：`{kind: {'path': …, 'ids': <反解器>, 'label': …}}`，
    由编排层从渲染器注册表带下来，本模块不必知道有哪些 kind。`html=` / `drawio=` 两个
    关键字参数保留给老调用方（本模块自己的 CLI 子命令还在用）；两者都给时以 `products` 为准。
    """
    errs = _stale_manifest_error(manifest, yaml_path)
    if errs:
        return errs

    want_ids = set(manifest.get('node_ids') or [])
    want_edges = Counter((a, b) for a, b in (manifest.get('edges') or []))

    if products:
        for kind, spec in products.items():
            path = spec['path']
            label = spec.get('label') or f'flow.{kind}'
            errs += _compare_ids_edges(want_ids, want_edges, label, *spec['ids'](path))
            errs += _external_refs(path, label)
        if 'html' in products:                 # 形状反查只看 html：另两份的形状读法还没写（D-84）
            errs += _compare_shapes(
                manifest, _main_slice(Path(products['html']['path']).read_text(encoding='utf-8')))
        return errs

    if html:
        errs += _compare_ids_edges(want_ids, want_edges, 'flow.html', *read_html(html))
        errs += _external_refs(html, 'flow.html')
        errs += _compare_shapes(manifest, _main_slice(Path(html).read_text(encoding='utf-8')))
    if drawio:
        errs += _compare_ids_edges(want_ids, want_edges, 'flow.drawio', *read_drawio(drawio))
        errs += _external_refs(drawio, 'flow.drawio')
    return errs


def summary(manifest):
    """一行人可读的统计，供 build 打印。"""
    c = manifest['counts']
    t = c['by_type']
    parts = [f"{c['nodes']} 节点", f"{c['edges']} 边"]
    if t:
        parts.append('（' + ' / '.join(f'{k} {v}' for k, v in t.items()) + '）')
    if c.get('labeled_edges'):
        parts.append(f"带标签边 {c['labeled_edges']}")
    if c.get('loop_edges'):
        parts.append(f"回路 {c['loop_edges']}")
    if c.get('pending_nodes'):
        parts.append(f"⚠ 推断 {c['pending_nodes']}")
    return '  '.join(parts)


# ----------------------------------------------------------------CLI
def _manifest_parser():
    """manifest 的 argparse 定义（build / check 两个子命令）。"""
    ap = argparse.ArgumentParser(description='渲染契约：产出清单 / 反查产物')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='DSL → manifest.json')
    b.add_argument('yaml_path')
    b.add_argument('-o', '--out')
    k = sub.add_parser('check', help='manifest.json vs 产物')
    k.add_argument('manifest')
    k.add_argument('--html')
    k.add_argument('--drawio')
    k.add_argument('--yaml', help='flow.yaml 路径：先验契约是否过期', dest='yaml_path')
    return ap


def _run_build(a):
    """build 子命令：DSL → manifest.json。"""
    # build 分支是 manifest 唯一要解析 yaml 的入口：裸 ImportError 会把"缺依赖"报成
    # 一段 traceback，看的人只会以为脚本坏了。说清要装什么，他才能自己动手。
    if yaml is None:
        print(f'✗ 需要 PyYAML：{deps.hint("yaml")}')
        return 1
    dsl = yaml.safe_load(Path(a.yaml_path).read_text(encoding='utf-8'))
    mf = build(dsl, source=Path(a.yaml_path).name, dsl_sha=dsl_fingerprint(a.yaml_path))
    out = Path(a.out) if a.out else manifest_path_for(a.yaml_path)
    out.write_text(json.dumps(mf, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'✓ 渲染契约: {out}  {summary(mf)}')
    return 0


def _run_check(a):
    """check 子命令：manifest.json vs 产物。"""
    # **一份产物都不给 = 没在反查**（G41）：`check()` 会把所有比较都跳过、返回空错误表，
    # 而这里原先照样打印"✓ 两份产物与契约逐项一致"退 0——公开命令上的假绿。
    # "少一份交付物而没人说"是本项目最忌的形态，所以这里当场拦下并给出三种给法。
    if not (a.html or a.drawio or getattr(a, 'products', None) or a.yaml_path):
        print('✗ 没给要反查的产物：`check` 至少要知道比谁——'
              '加 `--html <产物>` / `--drawio <产物>`（或 `--yaml <flow.yaml>` 先验收契约是否过期）')
        return 2
    mf = json.loads(Path(a.manifest).read_text(encoding='utf-8'))
    errs = check(mf, html=a.html, drawio=a.drawio, yaml_path=a.yaml_path)
    print(f'契约: {summary(mf)}')
    if errs:
        print(f'✗ 产物审核未通过（{len(errs)} 项）：')
        for e in errs:
            print('   -', e)
        return 1
    # 成功语按**实查份数**说（G41/⑬）：原先硬编码"两份"，只给 html 时也是"两份"。
    n = sum(1 for x in (a.html, a.drawio) if x)
    if n:
        print(f'✓ 已反查 {n} 份产物，与契约逐项一致（节点 id 集合 + 边集合）'
              + ('（契约新鲜度也验过）' if a.yaml_path else ''))
    else:
        print('✓ 契约未过期（本次只验新鲜度，没给产物可比）')
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _manifest_parser().parse_args(argv)
    if a.cmd == 'build':
        return _run_build(a)
    return _run_check(a)


if __name__ == '__main__':
    sys.exit(main())
