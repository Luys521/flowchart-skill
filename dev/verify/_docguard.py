# -*- coding: utf-8 -*-
r"""_docguard.py — 证明"只动文档串"没有改行为。

## 为什么需要它

`scripts/*.py` 的注释与文档串**不在任何门禁的判据里**：四面自检看流程表、产物、几何，
`accept.py` 看命令退出码。所以"把 200 行文档串压成 100 行"这种做法**跑完全套也证明不了没改行为**——
真把一行代码顺手删了，`dev/verify/run.py` 照样全绿。

本工具补这一刀：**剥掉全部文档串之后比字节**。

    剥掉 docstring 用的是 `ast` 重写（`ast.unparse`），所以它是**结构等价**而不是文本等价：
    缩进、空行、注释的差异都被抹平——正是我们要的（那些本来就允许变）。

用法：

    python dev/verify/_docguard.py --snapshot <文件…>     # 压注释**前**存一份指纹
    python dev/verify/_docguard.py --check    <文件…>     # 压注释**后**核对

退出码：**0** = 剥文档串后逐字节相同（行为面未被触碰）；**1** = 有差异（动了代码，不是纯文档改动）。
"""
import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

SNAP = Path(__file__).resolve().parent / '.docguard.json'


def strip_docstrings(path):
    """返回"剥掉全部文档串"后的规范化源码（`ast.unparse`，结构等价）。"""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def fingerprint(paths):
    return {str(Path(p).as_posix()): hashlib.sha256(
        strip_docstrings(p).encode('utf-8')).hexdigest()[:16] for p in paths}


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='证明"只动文档串"没改行为')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--snapshot', action='store_true', help='存指纹（改动前）')
    g.add_argument('--check', action='store_true', help='核对（改动后）')
    ap.add_argument('files', nargs='+')
    a = ap.parse_args(argv)

    files = [f for f in a.files if Path(f).suffix == '.py']
    if not files:
        print('✗ 没给 .py 文件')
        return 2

    cur = fingerprint(files)
    if a.snapshot:
        old = json.loads(SNAP.read_text(encoding='utf-8')) if SNAP.exists() else {}
        old.update(cur)
        SNAP.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'✓ 已存指纹 {len(files)} 个 → {SNAP.name}')
        return 0

    old = json.loads(SNAP.read_text(encoding='utf-8')) if SNAP.exists() else {}
    if not old:
        print('✗ 没有快照可比对 —— 先 --snapshot 存一份，再改文档串，最后 --check')
        return 2
    bad = [f for f, h in cur.items() if f in old and old[f] != h]
    newf = [f for f in cur if f not in old]
    for f in sorted(bad):
        print(f'  ✗ {f}  剥文档串后与快照不同 → 动了代码，不是纯文档改动')
    # **没有快照的文件也算失败**：原先只印一行"· 没有快照"就照样 ✓ 退 0——于是"改完才想起来
    # 跑 --check"会拿到一个绿色的假证明。这条断言的全部价值就是"证明没动代码"，没有比对对象时
    # 它什么都没证明（实测：只传一个从未存过快照的文件，输出 ✓、退出码 0）。
    for f in sorted(newf):
        print(f'  ✗ {f}  没有快照 → 这个文件没被证明过（先 --snapshot）')
    if bad or newf:
        return 1
    print(f'✓ {len(files)} 个文件剥掉文档串后与快照逐字节相同 —— 行为面未被触碰')
    return 0


if __name__ == '__main__':
    sys.exit(main())
