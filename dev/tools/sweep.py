# -*- coding: utf-8 -*-
r"""sweep.py — 清场：删掉**本仓库自己生成的临时物**，让工作区只剩该留的。

**为什么要有它**（2026-09-19，D-113）：`accept.py` 的临时现场**默认不自动删**——那个决定的理由正当
（清理动作不许参与判分："批量删除被安全钩子拦下"会把"十二道门全过"变成"命令报错"），
可它没有配套的收口：每跑一次验收就留下几个 `build-*` 目录（各约 5.7 MB / 140 个文件）。
实测连跑十几轮之后 `.accept_tmp/` 攒到 **134 MB / 2579 个文件**，而**没有人会想起来清**。
accept 现在**成功时自己收本次新建的**（见它的收尾注释）；本工具负责两件事：
**存量**（历史现场）与**手动清一次**。

**只认这几样**（每样都能再生，且都不是一手内容）：

  · `.accept_tmp/`——验收现场　· `.verify_tmp/`——自检现场　· `__pycache__/`——字节码缓存

**绝不碰**（代码里写死的白名单，不是"小心一点"）：`output/`（**用户的**流程产物与材料）·
`dev/baseline/`（"产物逐字节不变"的比对基准）· `examples/` / `references/` / `templates/`（一手内容）·
`.git/`。清场工具最容易出的错就是**顺手多删了一层**，所以这里连"扫全仓找大文件"都不做。

用法：
    python dev/tools/sweep.py --dry-run      # 只报：哪些、多大、合计（先看一眼再删）
    python dev/tools/sweep.py                # 真删（删不掉的逐项报出来）
    python dev/tools/sweep.py --root <目录>  # 换个仓库（默认按本文件位置推）

退出码：0 = 清完了（或本来就没东西）；2 = 有目标没删掉 / 这不像本仓库（逐项报出来，不假装成功）。
"""
import argparse
import shutil
import sys
from pathlib import Path

# 布局假设：`dev/tools/` → 上两级是仓库根（与 `dev/_paths.py` 同一条口径，见 D-66）
ROOT = Path(__file__).resolve().parents[2]

#: 现场目录（整棵删）
SCENES = ('.accept_tmp', '.verify_tmp')
#: 缓存目录（按名递归找，但**不钻进已经要删的那两棵**）
CACHES = ('__pycache__',)
#: 这几棵底下的东西一律不碰（哪怕名字撞上）——它们是比对基准或一手内容
KEEP = ('output', 'dev/baseline', 'examples', 'references', 'templates', '.git', 'archive', 'old')


def _size(p):
    """`(字节数, 文件数)`；目录递归，符号链接按链接算（不跟进去）。"""
    if p.is_file():
        return p.stat().st_size, 1
    total, n = 0, 0
    for q in p.rglob('*'):
        if q.is_file():
            total += q.stat().st_size
            n += 1
    return total, n


def _under_keep(p, root):
    """这条路在不在"绝不碰"名单里（相对仓库根比前缀）。"""
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return True                      # 仓外的东西一律不动
    return any(rel == k or rel.startswith(k + '/') for k in KEEP)


def targets(root):
    """→ `[(路径, 字节数, 文件数, 种类)]`。**先收现场，再找缓存**（免得同一棵树数两遍）。"""
    out = []
    for name in SCENES:
        p = root / name
        if p.is_dir() and not _under_keep(p, root):
            mb, n = _size(p)
            out.append((p, mb, n, '现场'))
    scenes = [t[0].resolve() for t in out]
    for name in CACHES:
        for p in sorted(root.rglob(name)):
            if not p.is_dir() or _under_keep(p, root):
                continue
            if any(s == p.resolve() or s in p.resolve().parents for s in scenes):
                continue                 # 已在要删的那棵树里，别重复列
            kb, n = _size(p)
            out.append((p, kb, n, '缓存'))
    return out


def _force(func, path, _exc):
    """`rmtree` 的兜底：**只读属性**会让它删不掉（从只读来源 / 归档拷来的文件很常见，
    实测 `.accept_tmp/blind/arm2/资料包/` 那批材料拷贝就是这么留下的）⇒ 去掉只读再试一次。
    """
    import os
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass                                 # 还是删不掉：交给调用方报出来（不许假装成功）


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='清场：删掉本仓库自己生成的临时物（现场 / 缓存）')
    ap.add_argument('--root', help='仓库根（默认按本文件位置推）')
    ap.add_argument('--dry-run', action='store_true', help='只报不删（先看一眼再删）')
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else ROOT
    if not (root / 'SKILL.md').is_file() or not (root / 'scripts').is_dir():
        print(f'⚠ 这不像本仓库（缺 SKILL.md / scripts/）：{root}', file=sys.stderr)
        return 2

    found = targets(root)
    if not found:
        print('✓ 没有要清的（现场与缓存都不在）')
        return 0
    total = sum(b for _p, b, _n, _k in found)
    files = sum(n for _p, _b, n, _k in found)
    print(f'清场范围：{root}')
    for p, b, n, kind in found:
        print(f'  [{kind}] {b / 1048576:9.2f} MB {n:6} 文件  {p.relative_to(root).as_posix()}')
    print(f'合计 {total / 1048576:.1f} MB / {files} 个文件')
    if a.dry_run:
        print('（--dry-run：什么都没删。去掉这个开关就真删）')
        return 0

    bad = []
    for p, _b, _n, _k in found:
        if p.is_dir():
            shutil.rmtree(p, onerror=_force)
        elif p.exists():
            try:
                p.unlink()
            except OSError:
                _force(p.unlink, p, None)
        if p.exists():                   # 删不掉要说出来，不许假装成功
            bad.append(p.relative_to(root).as_posix())
    if bad:
        print(f'✗ {len(bad)} 项没删掉（多半是被占用 / 权限）：{"、".join(bad)}', file=sys.stderr)
        print('  → 正在被别的进程占用的，关掉那个进程再跑一次；实在删不掉就手工删（它可随时再生）',
              file=sys.stderr)
        return 2
    print(f'✓ 已清 {len(found)} 项，腾出 {total / 1048576:.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
