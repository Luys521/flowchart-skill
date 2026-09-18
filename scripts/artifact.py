# -*- coding: utf-8 -*-
"""artifact.py — 产物命名规则的**唯一出处**（见 D-51）。

本模块只回答一个问题：**流程表（或子表）的路径 → 它的产物叫什么名字**。
产物名一律是 `<流程名>-flow.{yaml,manifest.json,html,drawio,svg}`——**任何地方都不许再拼一遍名字**。
（`svg` 是 W7b 起新增的可编辑中间态产物；它同样按这条命名规则，`artifact_rel(..., ext='svg')` 即可。）
名字一旦被拼在第二处，两处就会各自漂移，而漂移的后果（链接指到不存在的文件）不会报错、只会在
用户点开时才暴露。所以这里不许内联、不许复制，只许引用。

## 为什么单独成一个模块

`artifact_stem` / `artifact_rel` 原先住在 `table_to_dsl.py`（表格解析器）里，那只是历史巧合：
路径命名与「解析 / 校验 / 布局」**没有共同的变更原因**。表格语法变了，产物名不该跟着变；
产物命名规则改了，解析器也不该跟着动。把两个变更原因不同的东西绑在一个文件里，
任何一侧的改动都会牵扯另一侧，也会让引用方为了拿一个命名函数而拖进整个解析器。

命名规则被 8 个模块共用（build / sync / layer_index / render_html / render_drawio / render_svg /
table_to_dsl / validate —— 清单以 `grep -l "from artifact import" scripts/*.py` 现跑现取，
**不在这里手抄**），它是一个**被多方依赖的稳定契约**。单独成文件，既让"唯一出处"这件事在物理上看得见，
也让每个引用方只依赖这一条规则、不依赖解析器——这正是"小接口、少依赖"的拆法。
"""
from pathlib import Path


# 「不是流程表」的 .md：会出现在成果根 / 流程目录旁、但不是表的那些文档。
# **名字只在这里写一次**：凡"扫 *.md 找表"的地方（layer_index 的孤儿表检查、
# flowtable 的父表链扫描）都必须从这里取；否则每新增一个任务级产物名，
# 就要在多处补白名单，漏一处就冒假警告（见 PIPELINE-SPEC §7.2）。
NON_TABLE_MD = frozenset({'checklist.md', 'intake.md', 'plan.md'})


def artifact_stem(table_path):
    """流程表 → 产物名前缀（见 D-51）。规则：**表名是约定名就用目录名，否则用表名**。

    为什么要看目录名：`output/<名称>/flowtable.md` 里 `flowtable.md` 是**约定名**，它不承载语义——
    流程的身份在目录名上。产物若一律叫 `flow.html`，发出去就是一堆没有名字的文件。
    表名与目录名都取不到时退回 `flow`，不产空名。
    """
    p = Path(table_path)
    name = p.parent.name if p.stem.lower() == 'flowtable' else p.stem
    return name or 'flow'


def artifact_rel(table_rel, ext='html'):
    """子表流程表的相对路径 → 子图产物的相对路径（见 D-51）。

        `parts/结构校验/flowtable.md`  →  `parts/结构校验/结构校验-flow.html`
        `parts/渲染.md`               →  `parts/渲染-flow.html`

    目录不变，文件名换成 `<流程名>-flow.<ext>`。流程名来自 `artifact_stem`——
    与 build.py 给主产物命名用的是**同一个函数**。父子两侧各算一次，规则一旦分叉，
    链接就指到一个不存在的文件而没有任何报错：这正是"把产物名写死在一处"想避免、
    却又因为写死在**两处**（文本层拼 `flow.html` + build 里写死 `flow.html`）而埋下的那类脆弱。
    """
    p = Path(table_rel)
    head = p.parent.as_posix()
    name = f'{artifact_stem(p)}-flow.{ext}'
    return f'{head}/{name}' if head not in ('', '.') else name
