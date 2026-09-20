# -*- coding: utf-8 -*-
r"""deps.py — 可选依赖的**读入与提示，只有这一处**（D-122）。

"缺依赖"这条信息在本仓有**六个地方**各写了一遍（`parse_ooxml` / `parse_pdf` / `recon` 各带一份
`_import_dep` + `DEP_PKG`，`render_pages` 自己一份 `_import_pdfplumber`，`manifest` /
`table_to_dsl` 各一句 PyYAML 提示），而且**写法已经漂了**：`recon` / `parse_pdf` 写
"`pip install -r requirements.txt`"、`parse_ooxml` / `render_pages` 写
"`python -m pip install -r …`"、`manifest` / `table_to_dsl` 干脆只写 "pip install pyyaml"。
同一句话说六遍必漂（`dev/tools/cohesion.py` 一跑就现形：`_import_dep` 三份、结构相似 0.91–1.0）。

**为什么值得单独一个模块**：§1.4 对适配器有一条硬要求——"**缺依赖要报可执行的错**"。
可执行的意思是：用户照着那句话敲一遍就能装上。那么**那句话本身**就该只有一个出处，
并且顺手把"**import 名 ≠ pip 包名**"这张最容易忘的映射也放在这儿
（`docx` ↔ `python-docx`、`PIL` ↔ `Pillow`、`yaml` ↔ `pyyaml`——忘了这张表，
提示就会让人去 `pip install docx`，装上一个同名的空壳包，然后更迷惑）。
"""
import importlib

#: **import 名 → pip 包名**（同名的就不必列，`hint` 会退回 import 名本身）
PKG = {'docx': 'python-docx', 'PIL': 'Pillow', 'yaml': 'pyyaml',
       'openpyxl': 'openpyxl', 'pdfplumber': 'pdfplumber'}

#: 装全套的提示（requirements.txt 里就是这几个可选依赖）
ALL_HINT = 'python -m pip install -r requirements.txt'


def hint(name):
    """`'docx'` → "装 `python -m pip install python-docx`（或 `python -m pip install -r requirements.txt`）"。

    **用 `python -m pip` 而不是裸 `pip`**：裸 `pip` 在某些环境里指向另一个解释器，
    照着敲会装到别处去——那种"装了却还说缺"的故障最难查。
    """
    pkg = PKG.get(name, name)
    return f'装 `python -m pip install {pkg}`（或 `{ALL_HINT}`）'


def import_dep(name):
    """import 一个**可选**依赖 → `(模块, 报错文案)`；缺了给**可执行**的提示（§1.4 的硬要求）。

    调用方一律这样用：`mod, err = deps.import_dep('docx')`，`err` 非空就把它当"读不动"的理由
    （`status=unreadable` + 这句 reason），**不是**当成仪器故障——缺依赖是环境事实，不是命令坏了。
    """
    try:
        return importlib.import_module(name), ''
    except ImportError:
        pkg = PKG.get(name, name)
        return None, f'缺依赖 {pkg}：{hint(name)}'
