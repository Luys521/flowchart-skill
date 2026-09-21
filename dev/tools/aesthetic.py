# -*- coding: utf-8 -*-
"""aesthetic.py — 三条审美律的仪器：主轴偏心 / 绕行率 / 通道半径（`visual-spec` §0.1，D-91）。

**它答的问题**：图不是"能不能看"，而是"读起来顺不顺"。三条律都能算成一个数，于是审美不再靠嘴说：

  ① 主轴偏心 = |主轴 x − 墨迹外包盒中心 x| / 墨迹宽            0 = 主轴正落在墨迹中轴（两臂均衡）
  ② 绕行率   = (折线实长 − 两端锚点曼哈顿距离) / 曼哈顿距离      0 = 一步都没多走
  ③ 通道半径 = 通道 x 到**最近列沿**的距离 / 列距（col_pitch）        ≈0 = 贴着某一列走，≥1 = 绕出一整列
     （**粗读数**：不含通道的边走自身端点，天然记 0，会把均值压低；裁决只看 ①②）

**典型命令**：`python dev/tools/aesthetic.py output/self-boot dev/baseline/workflow`
**退出码**：0 = 打印完（**本工具不裁决**，阈值见 `visual-spec` §0.1 的表）。
**它已在验收里**（门⑨，2026-09-17 起）：判的是"读数**不许变差**"（偏心 ≤0.15 · 通道半径 ≤0.5 ·
绕行均值 ≤45% / 最坏 ≤60%）。**那三个阈值与 `visual-spec` §0.1 的表逐值一致**——2026-09-19（D-132）
对齐过一次：§0.1 原先写着"绕行均值 ≤35%"，而门按 45% 执行，**一条不执行的阈值就是一句空话**。
"""
import sys
from pathlib import Path

# 路径只许走 dev/_paths.py（布局假设只表述一次，见 D-66；contract 有断言防漂回）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from engine import load  # noqa: E402

#: 三条审美律的**阈值（唯一出处）**：门⑨ 与这里逐值一致，`visual-spec` §0.1 的表也逐值对上——
#: 三处同值由**面① 一条断言**守着（2026-09-19，D-132）。原先门⑨ 把 0.15/0.5/45/60 写死在自己的
#: 源码里、规范另写一套（"绕行均值 ≤35%"），于是"两处同值"只是一句承诺，而它们**当时并不一致**。
LIMITS = {'主轴偏心': 0.15, '通道半径': 0.5, '绕行均值': 45, '绕行最坏': 60}


def _seglen(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def measure(yml):
    """一张表 → {主轴偏心, 平均绕行率, 平均通道半径, 画布宽, 节点数}；读不动返回 None。"""
    try:
        L = load(str(yml))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    L.head_band(False)
    rects = [L.rect(n["id"]) for n in L.dsl["nodes"]]
    if not rects:
        return None
    x0 = min(r[0] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    # 主轴 = **首行那个节点所在的列**（与 `flowtable_layout.balance_arms` 同一个判据）。
    # 早先写死 `col_x[0]`：D-92 把主轴挪到中列以后，那个读数量的成了左臂到墨迹中心的距离。
    first = min(L.dsl["nodes"], key=lambda n: n.get("row", 0))
    spine = L.col_x[first["col"]] if getattr(L, "col_x", None) else None
    ncol = len(set(n["col"] for n in L.dsl["nodes"]))
    off = abs(spine - (x0 + x1) / 2) / (x1 - x0) if spine is not None and x1 > x0 else None
    det = []
    for e in L.dsl["edges"]:
        p = L.path(e)
        real = sum(_seglen(p[i], p[i + 1]) for i in range(len(p) - 1))
        man = _seglen(p[0], p[-1])
        if man > 0:
            det.append((real - man) / man)
    # 通道半径：通道 x 落在**它自己那一侧**、离最近列沿多远，用列距（col_pitch）归一。
    # 第一版按"到最右沿的距离 / 右侧可用宽"算——左族回路被它算成 3.5（其实是贴着主列走的），
    # 读数指着错的方向；仪器算错方向比没有仪器更坏。
    pitch = 0.0
    if len(getattr(L, "col_x", ())) > 1:
        pitch = abs(L.col_x[1] - L.col_x[0])
    edges_x = [r[0] for r in rects] + [r[0] + r[2] for r in rects]
    rad = []
    for e in L.dsl["edges"]:
        if e["kind"] not in ("loop", "jumpR"):
            continue
        xs = [x for x, _ in L.path(e)]
        far = max(xs) if e["kind"] == "jumpR" else min(xs)
        near = min(edges_x, key=lambda v: abs(v - far))
        rad.append(abs(far - near) / pitch if pitch else 0.0)
    return {"off": off, "ncol": ncol, "det": sum(det) / len(det) if det else 0.0,
            "rad": sum(rad) / len(rad) if rad else 0.0,
            "w": round(L.width), "nodes": len(rects)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roots = [Path(p) for p in sys.argv[1:]] or [Path("output/self-boot")]
    tot = []
    for root in roots:
        files = sorted(root.rglob("*-flow.yaml")) if root.is_dir() else [root]
        for yml in files:
            m = measure(yml)
            if m and m["off"] is not None:
                tot.append(m)
                arm = f'{m["off"]:.2f}' if m["ncol"] >= 3 else '— (单臂)'
                print(f'{yml.name:<28} 节点{m["nodes"]:>3}  主轴偏心{arm:>8}  '
                      f'平均绕行{m["det"] * 100:5.0f}%  通道半径{m["rad"]:.2f}  画布宽{m["w"]}')
    if not tot:
        print("✗ 没读到任何 flow.yaml（给目录或文件路径）")
        return 2
    n = len(tot)
    # 偏心只对**可配平**的表求均值：列数 <3 时没有两侧可分（"臂"退化），拿它当失败是误伤
    arm = [m for m in tot if m["ncol"] >= 3]
    off = sum(m["off"] for m in arm) / len(arm) if arm else 0.0
    det = sum(m["det"] for m in tot) / n
    rad = sum(m["rad"] for m in tot) / n
    print(f"\n—— {n} 张表（可配平 {len(arm)} 张）：平均主轴偏心 {off:.2f} · 平均绕行 {det * 100:.0f}% · "
          f"平均通道半径 {rad:.2f} · 阈值 偏心<={LIMITS['主轴偏心']} · 半径<={LIMITS['通道半径']} · "
          f"绕行<={LIMITS['绕行均值']}% / 最坏<={LIMITS['绕行最坏']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
