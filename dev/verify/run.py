# -*- coding: utf-8 -*-
"""run.py — 验证层统一入口。

  python dev/verify/run.py              # 四个面全跑
  python dev/verify/run.py --only gates  # 只跑一个面

改动脚本、文档、字典或样例之后跑一次；任一面有未通过项就返回 1。
中间产物落在 `.verify_tmp/`：全过就删掉，有失败就保留，方便直接翻看现场。

各面分工见 README.md。解释器需能 import yaml（本机用系统 Python 3.14）。
"""
import argparse
import os
import shutil
import sys
import traceback
from pathlib import Path

# 跑套件**不留字节码缓存**：下面要 import 四个面，各面又会把 `scripts/` 挂上 sys.path 去
# import 产品模块——默认会在 `dev/verify/` 与 `scripts/` 下各写一份 `__pycache__`。
# 那是运行产物、不是仓库内容（`.gitignore` 同样认定），所以从这两行起禁掉：
# `sys` 那行管本进程，`os.environ` 那行给子进程（`build` / `validate` / `shot` 等由各面 spawn）。
# 代价只是每次 import 重新编译，这些模块都很小。
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import SKILL  # noqa: E402

import contract      # noqa: E402
import e2e           # noqa: E402
import gates         # noqa: E402
import invariants    # noqa: E402

FACES = {'contract': contract.run_face, 'gates': gates.run_face,
         'invariants': invariants.run_face, 'e2e': e2e.run_face}


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='flowchart-skill 自检（四个面）')
    ap.add_argument('--only', choices=sorted(FACES), help='只跑指定面')
    # 默认目录是固定的 `.verify_tmp/`，且开跑前会 rmtree——两个人同时跑会互相删对方的现场。
    # 并行自检（如多个会话各改一片代码）时用 `--tmp` 各占一个目录。
    ap.add_argument('--tmp', help='中间产物目录（默认 .verify_tmp/）')
    a = ap.parse_args(argv)

    tmp = Path(a.tmp).resolve() if a.tmp else (SKILL / '.verify_tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    names = [a.only] if a.only else ['contract', 'gates', 'invariants', 'e2e']
    results, face_errs = {}, {}
    for n in names:
        print(f'\n{"=" * 64}\n=== 面：{n}\n{"=" * 64}')
        try:
            results[n] = FACES[n](tmp).summary()
        except Exception:
            # 一个面抛未预期异常不能让其余面陪跑：当场打出栈、记为该面失败，继续跑
            face_errs[n] = traceback.format_exc(limit=4)
            results[n] = False
            print(f'\n  ✗ 面内未预期异常（本面按失败计）：\n{face_errs[n]}')

    print(f'\n{"=" * 64}\n汇总')
    for n in names:
        if n in face_errs:
            last = face_errs[n].strip().splitlines()
            print(f'  ✗ {n}（未预期异常：{(last[-1] if last else "")[:120]}）')
        else:
            print(f'  {"✓" if results[n] else "✗"} {n}')
    ok = all(results.values())
    if ok:
        shutil.rmtree(tmp, ignore_errors=True)
        print('\n✓ 全部通过（临时目录已清理）')
    else:
        # 现场路径要能显示仓库外的 --tmp（多 worker 并发时临时目录在仓库外）：
        # 直接 relative_to(SKILL) 会抛 ValueError，把退出码钉成 1——那不是"有面未通过"的信号。
        try:
            where = f'{tmp.relative_to(SKILL)}/'
        except ValueError:
            where = f'{tmp}\\'
        print(f'\n✗ 有面未通过；现场保留在 {where}，可逐个复查')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
