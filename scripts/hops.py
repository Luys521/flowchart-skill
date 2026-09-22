# -*- coding: utf-8 -*-
"""hops.py — 交叉打跳的方案层：正交交叉处该让谁跳、跳在哪（D-149）。

只做**一件事**：按图算一次打跳方案并缓存。跳点怎么插（`geometry.with_hops`）与判据
（`geometry.ortho_cross`）都在 geometry；两个 SVG 渲染器**各自把方案拼成自己的 `d`**
（拼串归各自渲染器，见 N3）。

**为什么不在这里拼串**：拼串要么接一个格式化函数（`d_path(L, e, fmt)`），要么自带第三份
数字格式化。前者把函数当参数传——`fn_graph` 的静态分析判不出目标，实测记了 **8 条**
"形参派发"缺口，`unresolved` 从 45 涨到 49，当场顶破复核阈值（`REVIEW_UNRESOLVED = 45`）；
后者是同一个规则的第三处陈述。所以这一层只出方案，不出字符串。
"""
from geometry import hop_plan, snap


def plan(L):
    """这张图的打跳方案 → `(plan, radius, style)`；**每张图算一次**，缓存在 `L` 上。

    缓存而不是加参数：调用方是渲染循环里的逐边绘制，而交叉检测要看**全图的边**。
    `radius` 在构造期 `snap` 到细格——记号的入口点由 `L` 命令带出，会被产物侧的"网格对齐"
    门禁读到（不是格上值就报离格）。`radius` 为 0 ⇒ 整件事关掉，产物与此前逐字节相同。
    `style` 是记号长什么样（`gap` 断开 / `arc` 半圆），见 `geometry.with_hops`。
    """
    if '_hop_plan' not in L.__dict__:
        h = L.cfg.get('hops') or {}
        r = snap(h.get('radius', 10) or 0, L.grid.lattice)
        L._hop_radius = r
        L._hop_style = str(h.get('style', 'gap'))
        L._hop_plan = (hop_plan([(id(e), L.path(e)) for e in L.edges], h.get('policy', 'vertical'))
                       if r > 0 else {})
    return L._hop_plan, L._hop_radius, L._hop_style
