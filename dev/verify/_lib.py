# -*- coding: utf-8 -*-
"""_lib.py — 验证层的共用薄层：路径、跑脚本、断言收集、报告。

只放"四个面都要用"的东西；具体用例各自成文件、互不依赖（高内聚），
公共依赖只有这一层（低耦合）。路径**不在本文件推**——统一从 `dev/_paths.py` 取，
**在任何 cwd 下都能跑**（见 DECISIONS D-66：布局假设只许表述一次）。

解释器用 `sys.executable`：脚本依赖 PyYAML，请用能 import yaml 的那个（本机是系统 Python 3.14）。
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

# `_paths` 住在 dev/（本文件的上一级）：解释器默认只把本文件所在目录挂上 sys.path，
# 所以这一行必须先于 `from _paths import …`。**这是全仓唯一允许写"上一级目录"的地方**——
# 其余模块一律"从 _paths 取"（dev/verify/contract.py 有断言守着，防布局假设再散开）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# `EXAMPLES` **本文件不用，但要对各面再导出**（`from _lib import EXAMPLES` 是那几个面的用法：
# 路径解析只许走 `dev/_paths.py` 一处，面文件不再各自 `sys.path` 折腾）——所以它不是未用 import。
from _paths import BASELINE, EXAMPLES, REPO, SCRIPTS  # noqa: E402,F401

#: 兼容既有引用：各面里的 `SKILL`（文档里的路径都相对仓库根）语义 = 仓库根。
SKILL = REPO
#: 基线目录：`examples/` 的**同构镜像**，机器生成的产物住这里（见 D-66）。
BASE = BASELINE
PY = sys.executable

# 让各验证面能直接 `import validate` / `from engine import load` 复用产品代码，
# 而不是再抄一遍检查逻辑——验证要验的就是那份实现。
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# 命名规则的唯一出处：验证层与产品代码必须算出同一个产物名，否则"断言找错地方"式的假红
from artifact import artifact_stem  # noqa: E402


def run(*args, cwd=None, env=None):
    """跑一个脚本（`run('validate.py', path)`）→ (退出码, 合并后的输出)。

    带 180s 超时：脚本若死循环/卡死，无超时会让整个 verify 无限挂起、且零输出可查。
    超时按失败处理（rc=9，附上已收到的输出），其余用例照常跑完。
    """
    cmd = [PY, str(SCRIPTS / args[0]), *[str(a) for a in args[1:]]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           cwd=str(cwd or SKILL), env=env, timeout=180)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or '') if isinstance(e.stdout, str) else ''
        return 9, out + f'\n✗ 脚本超时（>180s）: {args[0]}'
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def md5(path, n=8):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()[:n]


def prod(d, ext, table='flowtable.md'):
    """目录 + 流程表名 → 该表的产物路径（见 D-51）：`<流程名>-flow.<ext>`。

    验证层不许再写死 `flow.html`。产物名带流程名之后，写死的断言会在"表名不是
    flowtable / 目录名不是样例名"的场景里全部假红——红得还没道理（产物是对的，
    是断言找错了地方）。命名规则只有一份（`artifact.artifact_stem`），
    这里复用它而不是抄一遍。
    """
    return Path(d) / f"{artifact_stem(Path(d) / table)}-flow.{ext}"


def relp(path, start):
    """产物相对某目录的 posix 路径（下钻链接 / 面包屑都是相对路径）。"""
    return Path(os.path.relpath(str(path), str(start))).as_posix()


# ---------------------------------------------------------------- 合成表格
# 用例自带合成表，**不借 examples/**：约定与理由见 dev/verify/README.md「怎么加一条用例」。
# 表头规范 v2（D-57）后元信息只住在 frontmatter——纯表格夹具不需要任何表头。
HEAD = ('# 验证用流程表\n\n## 流程表\n\n'
        '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 |'
        ' 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n')


def row(stage, i, name, typ, subj, who, t, nxt, desc='', inp='—', bas='—', out='—'):
    """拼一行流程表（列序固定为 ICOM 序，见 flowtable-spec §2 的字段登记表）。

    夹具里 输入/依据/输出 默认为 `—`＝本表不涉及——这样既有 12 列，又不给每行添一条软提示。
    """
    return (f'| {stage} | {i} | {name} | {typ} | {inp} | {bas} | {out} |'
            f' {subj} | {who} | {t} | {nxt} | {desc} |\n')


class Case:
    """一个验证面的结果集合：逐条 ok/✗，最后给一行汇总。"""

    def __init__(self, title):
        self.title = title
        self.items = []

    def check(self, ok, label, detail=''):
        self.items.append((bool(ok), label, detail))
        print(f'  {"✓" if ok else "✗"} {label}' + (f'   {detail}' if detail else ''))
        return ok

    def section(self, name):
        print(f'\n-- {name} --')

    @property
    def failed(self):
        return [i for i in self.items if not i[0]]

    def summary(self):
        n, bad = len(self.items), len(self.failed)
        print(f'\n【{self.title}】{n - bad}/{n} 通过' + ('' if not bad else '  ← 有未通过项'))
        return not bad
