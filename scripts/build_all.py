# -*- coding: utf-8 -*-
r"""build_all.py — **并行出图**（PIPELINE-SPEC §7 的 L4 最小形态，D-126）：一个成果根下所有流程一起 build。

**它解决什么**：一个任务出一个成果根，根下 `每个流程一个目录`（§0）。流程一多，"一条一条点
`build.py`"就成了纯等待——而这些流程之间**没有任何共享状态**：各自一棵产物树、各自的目录、
产物名由目录名定（`artifact.artifact_stem`）。所以它们是**天然可并行**的。

**为什么现在才做（§7 的 YAGNI 是怎么被满足的）**：§7 写着"这一版不实现并行调度……先把**任务单元**
切干净（每流程一棵产物树、零共享状态），调度器等真遇到'一目录几十条流程'再上"。那三件事现在齐了：
① 任务单元切干净（本节的前提）；② **默认落盘跟着输入走**（D-119）——两个流程不再抢同一个默认名；
③ 并行安全有仪器：门⑪ 夹具 **65**（两任务同 cwd 同时跑材料链）与面③「两棵树同时 build」。
**本文只做"把 K 次 build 并发起来"这一件**，不做跨任务的作业调度（那是另一件事，§7 仍然不做）。

**三条边界**（都在代码里）：
- **默认串行**（`--jobs 1`）：不加参数时行为与"自己循环跑 K 次 build"等价，且**逐字节相同**；
- **每个流程一个进程**：走 `build.py` 的公开命令行（模块层不许横向 import，编排靠产物/命令）；
- **按名字排序输出**，不按完成先后——同输入同输出，别让"谁先跑完"混进产物与读数。

用法：

    python scripts/build_all.py <成果根>                 # 串行（等于逐条点 build）
    python scripts/build_all.py <成果根> --jobs 4        # 并行 4 个流程
    python scripts/build_all.py <成果根> --only 甲,乙     # 只要这几条

退出码：0 = 全部成功；1 = **有流程没过**（点名是哪几条）；2 = 仪器故障（成果根读不了 / 一条流程都没有）。
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BUILD = SCRIPTS / 'build.py'


def find_flows(root):
    """成果根 → `[(流程名, 流程表路径), …]`（**按名字排序**，确定性）。

    只认 `<根>/<名>/flowtable.md` 与 `<根>/flowtable.md`：**不递归**——`parts/<子表>/`
    是父表的视图，由父表那次 build 一起渲染（D-52）；把它们也当独立流程会重复渲染、
    还会在"流程数 = 目录数"那条校验上引入幽灵条目。
    """
    got = []
    if (root / 'flowtable.md').is_file():
        got.append((root.name, root / 'flowtable.md'))
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / 'flowtable.md').is_file():
            got.append((d.name, d / 'flowtable.md'))
    return got


def run_one(name, ft, verbose):
    """跑一条流程 → `(名字, rc, 输出)`。**走公开命令行**（子进程），与手动点 build 一模一样。"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    r = subprocess.run([sys.executable, str(BUILD), str(ft)],
                       capture_output=True, text=True, encoding='utf-8', cwd=str(ft.parent),
                       env=env)
    return name, r.returncode, (r.stdout or '') + (r.stderr or '')


def _heads(out):
    """一条流程的读数：最后一个 `✓/→` 行 + 第一条 `✗` 行（不必把整份输出倒出来）。"""
    lines = [ln.strip() for ln in (out or '').splitlines() if ln.strip()]
    bad = next((ln for ln in lines if ln.startswith('✗')), '')
    tail = next((ln for ln in reversed(lines) if ln.startswith(('✓', '→', '·'))), '')
    return bad, tail


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='并行出图：成果根下所有流程一起 build（PIPELINE-SPEC §7）')
    ap.add_argument('root', help='成果根（下面每个 <名>/flowtable.md 是一条流程）')
    ap.add_argument('--jobs', type=int, default=1, help='并发几个流程（默认 1 = 串行，与逐条点 build 等价）')
    ap.add_argument('--only', default='', help='只要这几条流程（逗号分隔的目录名）')
    ap.add_argument('--verbose', action='store_true', help='把每条流程的完整输出也打出来')
    a = ap.parse_args(argv)

    if a.jobs < 1:
        print('✗ --jobs 要比 0 大（1 = 串行）')
        return 2
    root = Path(a.root)
    if not root.is_dir():
        print(f'✗ 成果根读不了（不是目录）: {root}')
        return 2
    flows = find_flows(root)
    want = {x.strip() for x in a.only.split(',') if x.strip()}
    if want:
        missing = sorted(want - {n for n, _f in flows})
        if missing:
            print(f'✗ --only 点名的流程没找到：{"、".join(missing)}'
                  f'（根下现有 {"、".join(n for n, _f in flows) or "空"}）')
            return 2
        flows = [(n, f) for n, f in flows if n in want]
    if not flows:
        print(f'✗ 成果根下一条流程都没有（要 <根>/<名>/flowtable.md）: {root}')
        return 2

    print(f'成果根 {root}：{len(flows)} 条流程 · 并发 {a.jobs}'
          + ('（串行）' if a.jobs == 1 else ''))
    if a.jobs == 1:
        results = [run_one(n, f, a.verbose) for n, f in flows]
    else:
        with ThreadPoolExecutor(max_workers=min(a.jobs, len(flows))) as pool:
            results = list(pool.map(lambda nf: run_one(nf[0], nf[1], a.verbose), flows))
    # **按流程名排序打印**（不是完成先后）：同输入同输出，读数里别混进调度次序。
    failed = []
    for name, rc, out in sorted(results, key=lambda x: x[0]):
        bad, tail = _heads(out)
        flag = '✓' if rc == 0 else '✗'
        print(f'  {flag} {name}: rc={rc}' + (f'  {bad}' if bad else (f'  {tail}' if tail else '')))
        if rc != 0:
            failed.append((name, rc))
        if a.verbose:
            for ln in out.splitlines():
                print(f'      {ln}')

    print('─' * 56)
    if failed:
        print(f'✗ {len(failed)}/{len(flows)} 条流程没过：'
              + '、'.join(f'{n}(rc={rc})' for n, rc in failed))
        return 1
    print(f'✓ {len(flows)} 条流程全部出图成功'
          + (f'（并发 {a.jobs}）' if a.jobs > 1 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
