# -*- coding: utf-8 -*-
r"""repin.py — 重钉基线：把"改了 `scripts/` 之后那一串手工步骤"收成一条命令。

**为什么要有它**（2026-09-19，D-117）：自举树与样例的产物进库当**逐字节安全网**（面③ / 门⑥），
所以改了 `scripts/` 就要重造一遍再把基线换掉。这件事原先靠人记 **六步**：
`fn_graph → selfboot_gen → build → robocopy → 重建 workflow 基线 → accept`——
实测漏过、顺序也错过（先 build 后改样例 ⇒ 基线比产物旧，面③ 当场红）。**靠人记的顺序迟早会漏**，
所以把它做成一条命令，`accept.py` 的收尾再来裁决。

**它做什么**（五步，全都能重放；**顺序照 G2**：先 workflow 再镜像自举树）：

  ① `fn_graph.py`  —— 依赖图快照（图旧了 `coverage` 的分母就是旧代码，必然假绿）
  ② `selfboot_gen.py` —— 流程表树（根表 + 每个模块一张）
  ③ `build.py output/self-boot/flowtable.md` —— 三份产物
  ④ **workflow 基线重建**：`examples/workflow` 铺底 → build → 删掉那棵里的 `flowtable.md` 与 `*.bak`
     （基线里只放产物，事实源住 `examples/`，见 D-66）。**删的动作只在这棵树里做**——
     G2 那条"顺序反了会删掉整棵自举树的表"的隐患，在这里被"作用域"消掉了。
  ⑤ 自举树 → 基线（只拷变化的；`--prune` 才删多出来的）

**为什么现在做这件事（N1 原先写着"不做"）**：N1 的理由是"顺序错的**后果**已被面③ 兜住"——
那句话仍然成立，可它兜的是**后果**，不是**过程**：这一版会话里那套六步手工仪式跑了八次，
漏过一次（基线比产物旧、面③ 当场红）。**用户明确要"重钉半自动"**，而实现里删的动作按树作用域
收窄之后，N1 担心的那个隐患不再存在（细节与推翻理由见 D-117）。

**它不做什么**：不 commit、不打 tag、不跑验收。理由：那三件事要人过目（"这一版产物我认了"是判断），
而且 `git tag -f api-base HEAD` 这条**只在有意改动可观测行为时**才该做——自动化它等于把
"等价门"变成橡皮图章。跑完它会打印下一步。

用法：

    python dev/tools/repin.py --dry-run   # 造出来但**不动基线**：只报"哪些文件会变"
    python dev/tools/repin.py             # 真重钉
    python dev/tools/repin.py --prune     # 连"基线里多出来、新树里没有"的文件也删掉

退出码：0 = 干完了；2 = 某一步起不来 / 退非 0（**不假装成功**：哪一步坏了就说哪一步）。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # dev/tools/ → 仓库根（与 dev/_paths.py 同一口径）
PY = sys.executable
SKIP = ('.bak',)                                    # 点开头的备份不进基线（门⑥ 的整树口径也不含它们）
#: 基线认的产物后缀（见 `_is_baseline_artifact`；名字来自 D-51 的 `<流程名>-flow.<ext>`）。
PRODUCT_NAMES = ('-flow.yaml', '-flow.manifest.json', '-flow.html', '-flow.drawio', '-flow.svg')


def _md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def _snapshot(d):
    return {p.relative_to(d).as_posix(): _md5(p) for p in sorted(d.rglob('*')) if p.is_file()}


def _run(script, *args):
    """跑一步 → `(rc, 尾巴)`。**带 `PYTHONDONTWRITEBYTECODE`**：不在仓库里留 `__pycache__`。

    **每一步算不算"跑成"由调用方给**（见 `main` 的 `steps`）：`fn_graph.py` 的合约是
    "**1 = 跑完了但有需人工复核的缺口/歧义**（超过 `REVIEW_*` 阈值）"——那不是失败（图已经写出来了）。
    实测踩过：把 1 一律当失败 ⇒ 只要图上待复核项超标，整个重钉就拒绝干活。
    """
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    r = subprocess.run([PY, str(ROOT / script), *[str(a) for a in args]],
                       capture_output=True, text=True, encoding='utf-8', env=env, cwd=str(ROOT))
    out = ((r.stdout or '') + (r.stderr or '')).strip().splitlines()
    return r.returncode, (out[-1] if out else '')


def _is_baseline_artifact(rel):
    """这条路名该不该进基线：**只放"这张表的产物"**（表本身 / `-index.md` / `-flow.<ext>`，命名见 D-51）。

    为什么要有这一条（G80）：`_sync` 原先镜像 `src` 里的**一切**（只跳 `.bak`），而 `output/self-boot/`
    是**工作目录**——人手跑一次 `shot.py` 就会在里面留下一张 `-flow.shot.png`，于是它被**钉进基线**。
    而面③ 的重造（`selfboot_gen` + `build`）永远造不出截图 ⇒ 那条不变式**从此恒红**，
    报的还是"少 1 …shot.png"：读起来像基线缺东西，其实是基线**多了**东西——一句话里两个方向都反了。
    """
    n = rel.rsplit('/', 1)[-1]
    return n.endswith('.md') or n.endswith(PRODUCT_NAMES)


def _sync(src, dst, prune):
    """`src` 里的产物 → `dst`（只拷变化的；`prune` 时删掉多出来的）→ 变更行清单。"""
    before = _snapshot(dst) if dst.is_dir() else {}
    now = _snapshot(src)
    changed, skipped = [], []
    for rel, digest in sorted(now.items()):
        if rel.endswith(SKIP):
            continue
        if not _is_baseline_artifact(rel):
            skipped.append(rel)               # 报出来，不默默丢（见 `_is_baseline_artifact`）
            continue
        s, d = src / rel, dst / rel
        if before.get(rel) == digest:
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        changed.append(('改' if rel in before else '新') + f' {rel}')
    changed += [f'（不是产物，未镜像：{rel}）' for rel in skipped]
    extra = sorted(set(before) - set(now)) if prune else []
    for rel in extra:
        (dst / rel).unlink()
        changed.append(f'删 {rel}')
    if not prune:
        changed += [f'（多出，未删：{rel}）' for rel in sorted(set(before) - set(now))]
    return changed


def _rebuild_workflow(baseline, dry):
    """workflow 基线**重建**：`examples/workflow` 铺底 → build → 只留产物（D-66 的布局）。

    → `(rc, 尾巴, 变更清单, 产物数)`。`--dry-run` 时造在 `.repin_tmp/` 里、**不动基线**，
    但变更清单照样算——"这次重钉会动哪些文件"正是人要看的那个数。
    """
    src = ROOT / 'examples' / 'workflow'
    before = _snapshot(baseline) if baseline.is_dir() else {}
    if dry:
        tmp = ROOT / '.repin_tmp' / 'workflow'
        shutil.rmtree(ROOT / '.repin_tmp', ignore_errors=True)
        shutil.copytree(src, tmp)
        work = tmp
    else:
        shutil.rmtree(baseline, ignore_errors=True)
        shutil.copytree(src, baseline)
        work = baseline
    rc, tail = _run('scripts/build.py', work / 'flowtable.md')
    if rc != 0:
        return rc, tail, [], 0
    for junk in list(work.rglob('flowtable.md')) + list(work.rglob('*.bak')):
        junk.unlink()
    now = _snapshot(work)
    changed = [('改' if k in before else '新') + f' {k}' for k, v in sorted(now.items())
               if before.get(k) != v]
    changed += [f'（多出，未删：{k}）' for k in sorted(set(before) - set(now))]
    if dry:
        shutil.rmtree(ROOT / '.repin_tmp', ignore_errors=True)
    return 0, tail, changed, len(now)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='重钉基线：生成器 → build → 基线（不 commit / 不 tag）')
    ap.add_argument('--dry-run', action='store_true', help='造出来但**不动基线**，只报会变哪些文件')
    ap.add_argument('--prune', action='store_true', help='连"基线里多出来"的文件也删掉')
    a = ap.parse_args(argv)

    # 每一步「算跑成」的退出码：**只有 `fn_graph` 多一个 1**（＝跑完了但有需人工复核的缺口）。
    steps = [('① 依赖图快照', 'dev/tools/fn_graph.py', (), (0, 1)),
             ('② 流程表树', 'dev/tools/selfboot_gen.py', (), (0,)),
             ('③ 出图', 'scripts/build.py', ('output/self-boot/flowtable.md',), (0,))]
    for label, script, args, ok in steps:
        rc, tail = _run(script, *args)
        print(f'{label}: rc={rc}  {tail[:110]}')
        if rc not in ok:
            print(f'✗ {label} 没跑成——**基线一个字都没动**，先修这一步', file=sys.stderr)
            return 2

    sb = ROOT / 'output' / 'self-boot'
    print('④ 样例基线重建' + ('（--dry-run：造在临时目录里）' if a.dry_run else ''))
    rc, tail, wdiff, n_prod = _rebuild_workflow(ROOT / 'dev' / 'baseline' / 'workflow', a.dry_run)
    if rc != 0:
        print(f'✗ workflow 基线没重建成功：{tail}', file=sys.stderr)
        return 2
    for ln in wdiff[:10]:
        print('   ' + ln)
    if len(wdiff) > 10:
        print(f'   …共 {len(wdiff)} 项')
    if not wdiff:
        print(f'   （{n_prod} 个产物，与基线逐字节相同）')

    print('⑤ 自举树 → 基线' + ('（--dry-run：不动基线）' if a.dry_run else ''))
    if a.dry_run:
        base = ROOT / 'dev' / 'baseline' / 'self-boot'
        before, now = _snapshot(base), _snapshot(sb)
        diff = [('改' if k in before else '新') + f' {k}' for k, v in sorted(now.items())
                if not k.endswith(SKIP) and before.get(k) != v]
        diff += [f'（多出，未删：{k}）' for k in sorted(set(before) - set(now))]
    else:
        diff = _sync(sb, ROOT / 'dev' / 'baseline' / 'self-boot', a.prune)
    for ln in diff[:20]:
        print('   ' + ln)
    if len(diff) > 20:
        print(f'   …共 {len(diff)} 项')

    print(f'\n→ 重钉完成：样例 {len(wdiff)} 项（{n_prod} 个产物）· 自举树 {len(diff)} 项')
    print('  下一步（**要人过目，所以不替你跑**）：')
    print('    python dev/verify/run.py            # 四面')
    print('    python dev/tools/accept.py          # 十二道门')
    print('    git add -A && git commit …          # 提交这一版基线')
    print('    git tag -f api-base HEAD            # **只在有意改了可观测行为时**')
    return 0


if __name__ == '__main__':
    sys.exit(main())
