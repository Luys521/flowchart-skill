# -*- coding: utf-8 -*-
"""flowtable_colors.py — 执行主体配色：声明 + 跨层继承 + 撞色拦截（D-49/D-59），以及按序取色。

`resolve_colors` 读本表声明并沿 `flowtable` 的父表链向上继承（同一主体跨层必须同色）；
`subject_map` 给没声明的主体按出现顺序分配色板。二者都只产出 {主体: 色}，不碰渲染。

跨层继承要用到父表链，故本模块 import `flowtable`；解析与校验都不在这里。
"""
import re

from flowtable import parse_table, find_parent_table, COLOR_KEY


# 主体配色（D-59）：正文「## 主体配色」小节表声明，值为 **hex**（`#RGB` / `#RRGGBB`）。
# D-49 曾用颜色名字（`机器=橙`）理由是"名字可判等、用户免挑色"；D-59 改 hex 后判等依旧成立
# （字符串相等），跨层一致检查从"名字判等"变为"hex 判等"，反而少一层查表间接。
# 色板保留：未声明配色的主体按出现顺序自动分配（灰在最后——它是兜底色，不是给人主动配的）。
COLOR_NAMES = {
    '蓝': {'fill': '#dae8fc', 'stroke': '#6c8ebf'},
    '绿': {'fill': '#d5e8d4', 'stroke': '#82b366'},
    '橙': {'fill': '#ffe6cc', 'stroke': '#d79b00'},
    '黄': {'fill': '#fff2cc', 'stroke': '#bf9000'},
    '紫': {'fill': '#e1d5e7', 'stroke': '#9673a6'},
    '红': {'fill': '#f8cecc', 'stroke': '#b85450'},
    '灰': {'fill': '#ffffff', 'stroke': '#999999'},
}
PALETTE_ORDER = ['蓝', '绿', '橙', '黄', '紫', '红', '灰']

SUBJECT_PALETTE = [COLOR_NAMES[n] for n in PALETTE_ORDER]


def _next_free(m):
    """从色板里取**第一个还没被占用**的颜色。

    为什么不是"按第几个主体取第几档"：一旦允许部分声明，显式占掉的那一档必须从池子里拿掉，
    否则未声明的主体会与显式声明的主体撞色（声明了「机器=橙」，第 3 个出现的主体正好又分到橙）。
    跳过已占用档还有一个好处：给既有流程表补一行声明，不会把其他主体的颜色整体挤位。
    """
    for name in PALETTE_ORDER:
        c = COLOR_NAMES[name]
        if all(v['fill'] != c['fill'] for v in m.values()):
            return c
    return COLOR_NAMES['灰']


def _color_map(colors, errs):
    """「主体配色」表解析出的 {主体: hex} → ({主体: {'fill','stroke'}}, errs)（D-59 hex 方案）。

    hex 判等（字符串相等）取代 D-49 的颜色名查表——跨层一致检查同样精确，少一层间接。
    stroke 规则：hex 命中色板取色板的描边，自定义 hex 用自身（同色描边）。
    两类撞色都拦：两个主体同色（维度失去区分）、同一主体声明两种颜色（自相矛盾）。
    """
    m = {}
    for who, hexv in (colors or {}).items():
        h = str(hexv).strip().replace('\\', '')
        who = str(who).strip()
        if not re.fullmatch(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})', h):
            errs.append(f'{COLOR_KEY}：主体「{who}」的颜色「{hexv}」不是合法 hex（#RGB / #RRGGBB）')
            continue
        # **当前不可达，留作防御**（G70）：`colors` 是 dict，同名主体在解析层就被后写覆盖了
        # （`flowtable._read_layout_sections` 按 dict 键去重，并把重复键记进 `__color_dup__`，
        # 由 `flowtable_check._check_color_dup` 报 H9）。所以"同一主体两种颜色"这条在**本函数**
        # 里进不来——它真正的守门人是 H9 那条。别因为读到这一支就以为它还在执勤。
        if who in m and m[who]['fill'].lower() != h.lower():
            errs.append(f'{COLOR_KEY}：主体「{who}」被声明了两种不同的颜色')
            continue
        if any(v['fill'].lower() == h.lower() for w, v in m.items() if w != who):
            owner = next(w for w, v in m.items() if w != who and v['fill'].lower() == h.lower())
            errs.append(f'{COLOR_KEY}：主体「{owner}」与「{who}」用了同一种颜色——'
                        f'图上分不开，等于没声明')
            continue
        stroke = next((p['stroke'] for p in SUBJECT_PALETTE if p['fill'].lower() == h.lower()), h)
        m[who] = {'fill': h, 'stroke': stroke}
    return m, errs


def _inherit_colors(ft):
    """沿父表链向上找**第一个**声明了配色的祖先 → (祖先映射, 祖先 Path)（找不到返回 ({}, None)）。

    冲突检查跟"继承链上最近的显式声明"比，不是跟直接父表比——否则父表没声明、
    祖父表声明了的那一段会被漏掉（L1=橙、L2 未声明、L3=红，只比 L2 就看不出 L3 反了）。
    祖先配色里的格式错误由祖先自己的 --check 报，这里只取映射（旧口径一致）。
    """
    up_map, src_ft = {}, None
    cur, seen = ft, {ft.resolve()}
    while True:
        r = find_parent_table(cur)
        if not r:
            break
        p = r[0]
        if p.resolve() in seen:          # 环形引用兜底（语法上不该发生，但不值得赌）
            break
        seen.add(p.resolve())
        try:
            _t, pmeta, _r = parse_table(p.read_text(encoding='utf-8-sig'))
        except OSError:
            break
        t = pmeta.get(COLOR_KEY)
        if t:
            up_map = _color_map(t, [])[0]
            src_ft = p
            break
        cur = p
    return up_map, src_ft


def resolve_colors(ft, own):
    """本表声明 + 向上继承 → ({主体: {'fill','stroke'}}, [硬错误…])。见 D-49/D-59。

    继承：**本表没声明，就沿父表 → 祖父表…一路向上，用找到的第一个声明**。
    为什么必须继承：主图有四个主体、「机器」排第 3 拿到橙；子图里只有「机器」一个主体，
    按出现顺序它会拿到蓝——点橙色的节点进去看到一整页蓝色。同一个主体跨层两个颜色，
    比"颜色不好看"严重得多：颜色在这个体系里是**主体的身份**，不是装饰。

    只继承"第一个找到的"，是因为父表通常就是那个定调的表；再往上的祖父母除非中间层
    都没声明，否则不该越过父表去取。

    冲突检查在这里一并做：本表**显式**声明了，且与继承来的那份不一致 → 硬错误。
    own 是本表「主体配色」表解析出的 {主体: hex}（D-59 hex 方案，判等 = 字符串相等）。
    """
    errs = []
    own_map, errs = _color_map(own, errs)
    up_map, src_ft = _inherit_colors(ft)
    for who, v in own_map.items():
        if who in up_map and up_map[who]['fill'] != v['fill']:
            errs.append(f'执行主体配色冲突：本表「{who}」与祖先表《{src_ft.stem}》颜色不一致——'
                        f'同一执行主体跨层必须同色。改本表或改祖先表，不要两处各写一套')
    return (own_map or up_map), errs


def _declare_subjects(declared):
    """显式声明过的主体直接占座（即便本表没用到也保留，图例与主图同构）→ 新字典。"""
    m = {}
    for s in (declared or {}):
        m[s] = declared[s]
    return m


def _assign_lane_colors(m, lane_order):
    """显式泳道序里的主体按泳道序取色；空泳道同样占一档（它要画，没颜色会与其他列割裂）。"""
    for s in (lane_order or []):
        if s and s not in m:
            m[s] = _next_free(m)


def _assign_node_colors(m, nodes):
    """节点「执行主体」列里还没占座的主体按出现顺序取色；占位符（-/—/空）不算主体。"""
    for n in nodes:
        s = (n['subject'] or '').strip()
        if not s or s in ('-', '—', '无'):
            continue
        if s not in m:
            m[s] = _next_free(m)


def subject_map(nodes, lane_order=None, declared=None):
    """按出现顺序给「执行主体」分配调色板；给了显式泳道序则**按泳道序**取色。

    占位符（`-` / `—` / 空）不算主体——外部图该列全是 `-`，收进配色表会多出一档没人用的颜色、
    图例还会冒出「-执行」；这类节点回落字典的「默认」色。
    空泳道同样占一档颜色：它在图上是要画的（表头 + 列底），没颜色会与其他列割裂。

    `declared` 是流程表「执行主体配色」的显式声明（见 D-49），**优先于一切自动分配**：
    声明过的主体直接占座，**即便本表没用到它也保留**——图例因此展示的是"这个项目的主体全集"，
    子图哪怕只用到一个主体，图例也与主图同构。这正是"体系"该有的观感：
    看图例就知道一共有哪些主体、各是什么颜色，不随下钻层级变化。
    """
    m = _declare_subjects(declared)
    _assign_lane_colors(m, lane_order)
    _assign_node_colors(m, nodes)
    return m
