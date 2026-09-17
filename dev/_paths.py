# -*- coding: utf-8 -*-
r"""_paths.py — 全仓**唯一的路径解析点**。

## 为什么单设这一个模块（见 DECISIONS D-66）

搬迁 `dev/` 分区之前，`ROOT = Path(__file__).resolve().parent.parent` 这句在**9 个文件里各写了一遍**
（`dev/tools/` 7 处 + `dev/verify/_lib.py` + `scripts/init.py`）。它把"我在仓库根下一层"这个**布局假设**
复制了 9 份——于是"把 `dev/tools/` 挪进 `dev/`"从一步变成九步，漏一处就**静默指错根**（不报错，
只是所有产物都写到别处、所有门禁都读到空）。

现在布局只在这里表述一次。**新增模块不许再自己推 `__file__` 的父目录**——
`dev/verify/contract.py` 有一道断言守着这条（防漂回）。

## 两个根的区别（容易写错）

  `REPO` 是**仓库根**（`scripts/` `references/` `templates/` `examples/` 都在它下面）
  `DEV`  是**开发分区**（`dev/verify/` `dev/tools/` `baseline/` 与三份设计文档在它下面）

`scripts/` 属产品区、在 `REPO` 下；`dev/verify/` `dev/tools/` 属维护区、在 `DEV` 下。**别混用。**
"""
from pathlib import Path

#: 本文件所在目录 = dev/
DEV = Path(__file__).resolve().parent
#: 仓库根（DEV 的父目录）
REPO = DEV.parent

# ---- 产品区（出图时的 AI 与运行期脚本消费） ----
SCRIPTS = REPO / 'scripts'
REFERENCES = REPO / 'references'
TEMPLATES = REPO / 'templates'
EXAMPLES = REPO / 'examples'

# ---- 维护区（只有改仓库的人进） ----
TOOLS = DEV / 'tools'
VERIFY = DEV / 'verify'
#: 基线：`examples/` 的**同构镜像**，放机器生成的产物（不进 examples，见 D-66）。
#: 它必须进版本库——套件靠它守"改渲染器后产物逐字节不变"这条安全网。
BASELINE = DEV / 'baseline'
