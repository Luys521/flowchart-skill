# -*- coding: utf-8 -*-
r"""thresholds.py — 数值字典的**读取口径，只有这一处**（D-121）。

`dictionary.yaml` 的每一段都是"**内置默认 + 该段按名覆盖**"，而这段读取逻辑原先在
**六个模块各写了一遍**（`drift` / `parse_legacy` / `parse_pdf` / `recon` / `query` / `textquality`，
各 14–23 行）。各写一遍的代价有两条，本仓都真发生过：

- **漏改一处 = 静默退回兜底值**：那六份实现都是"读不到就用默认、**不报错**"（这是刻意的，
  见下），于是段落名写错、或改名漏掉一个模块时，那条路会**悄悄用兜底值接着跑**——
  上一轮改 `DICT_NAME` 的家时就踩过这个形态；
- **容错口径会漂**：六份里有两份（`recon` / `query`）多要求"正整数"，另四份只要求"是数值"；
  还有一份（`recon`）补了"段是列表也算形状不对"。**同一件事三种写法**，而差异没有任何仪器看得见
  （`dev/tools/cohesion.py` 一跑就现形：`load_thresholds` 六份、结构相似 0.72–0.93）。

**读不到为什么不报错**：字典是"**多一条可调档位**"，不是主链依赖——缺 PyYAML / 缺文件 / 坏 YAML
时退回内置默认，比让整条解析链停下来合算（与 `textquality` / `parse_legacy` 当初各自的取舍一致）。

**但"段不存在"要吭一声**：整份文件读到了、只是没有这个段，多半是**改名漏改**——
这正是"静默退回默认"最难查的那一种。所以那一支印一行到 stderr（正常情况所有段都在，
只有真出问题才看得见）。**走 `console.warn` 而不是 `print(..., file=sys.stderr)`**（D-129）：
本模块是**纯库**，而库不能保证调用方把 stderr 配成了 utf-8（实测 Windows 管道下是 gbk，
`⚠` 会退化成字面量 `\u26a0`、中文全成 `?`）——**读不出来的告警等于没有告警**，而这一句正是
"段名改了"的唯一报警器。**段存在但形状不对**（列表 / 标量）只退回默认、不吭声：
那是 `coding-spec` G-类里登记过的笔误形态，夹具专门喂过（`recon: [1,2]`）。
"""
from pathlib import Path

from console import warn
from semantics import DICT_NAME


def load(section, defaults, path=None, positive_int=False):
    """`dictionary.yaml` 的 `section:` 段 → 一份"**默认 + 覆盖**"的字典。

    `positive_int=True` 是 `recon` / `query` 那两处的口径（只收正整数）：`outline_max: -1`
    会让摘要谎称"没抽出文字"、`0` 被下游当成"不限"——**收下这种值等于让读数说假话**。
    其余各处只要求"是数值"（`int` / `float`、排除 `bool`：Python 里 `True` 是 `int` 的子类）。
    """
    th = dict(defaults)
    p = Path(path) if path else Path(__file__).with_name(DICT_NAME)
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception:                      # 缺依赖 / 缺文件 / 坏 YAML：一律退回默认（见文件头）
        return th
    got = doc.get(section) if isinstance(doc, dict) else None
    if got is None:
        warn(f'⚠ `{p.name}` 里没有 `{section}:` 段——这一段退回内置默认（段名是不是改了？）')
        return th
    if not isinstance(got, dict):          # 形状不对（`recon: [1,2]` 这种笔误）⇒ 退回默认
        return th
    for k, v in got.items():
        if k not in th or isinstance(v, bool):
            continue
        if positive_int:
            if isinstance(v, int) and v > 0:
                th[k] = v
        elif isinstance(v, (int, float)):
            th[k] = v
    return th
