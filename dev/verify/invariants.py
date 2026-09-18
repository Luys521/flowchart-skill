# -*- coding: utf-8 -*-
"""invariants.py — 面③：不变式。不靠"这次对了"，靠"永远对"。

  1 网格贴合：直接复用 validate.check()，不另写一套审计（验证要验的就是那份实现）
  2 确定性：换 PYTHONHASHSEED 多次渲染，产物必须逐字节相同（否则说明有集合迭代顺序依赖）
  3 幂等：同一流程表 build 两次，产物不变
  4 只读事实源：跑完整面测试不许往 `examples/` 写一个字节，且那里**不许有产物**（D-66）
  5 自愈：手塞离格几何 → 吸附 + 提示，且仍通过
  6 图例带：带内不得出现节点/折点（origin_y 已按带高下推，这是结构保证）
  7 门面一致：`Engine.sizes` 必须直接指向 `grid.sizes`（否则两层各拿一份尺寸，改了不同步）

（清单与 `run_face` 的 `c.section` 一一对应；增删小节时这里要跟着改。）
"""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import BASE, EXAMPLES, HEAD, Case, md5, prod, row, run  # noqa: E402

import validate                                      # noqa: E402  （_lib 已把 scripts/ 挂上 sys.path）
from engine import load                              # noqa: E402

# 样例**动态发现**：examples/ 下有哪些就跑哪些，增删样例不必改测试
SAMPLES = tuple(sorted(q.parent.name for q in EXAMPLES.glob('*/flowtable.md')))


def _art(sample, ext):
    """样例的**产物**路径——产物住在 `dev/baseline/`（examples/ 只留事实源，见 D-66）。

    `examples/<样例>` 与 `dev/baseline/<样例>` 是**同构镜像**：目录名相同 ⇒ 产物名相同
    （产物名由目录名决定，D-51），所以换根即可，映射算法一行不用改。

    注意**产物就在样例目录里**、不再多套一层：`dev/baseline/workflow/workflow-flow.yaml`
    （`prod(根, 'yaml')` 自己会用目录名当 stem；多套一层样例名会指到不存在的路径）。
    """
    return prod(BASE / sample, ext)


def run_face(tmp):
    c = Case('面③ 不变式')
    tmp.mkdir(parents=True, exist_ok=True)
    c.check(bool(SAMPLES), 'examples/ 下至少有一个样例（否则下面的不变式无从施加）', str(SAMPLES))
    if not SAMPLES:
        return c
    first = SAMPLES[0]

    c.section('网格贴合（复用 validate.check）')
    for n in SAMPLES:
        L = load(str(_art(n, 'yaml')))
        errs, notes = validate.check(L)
        grid = [e for e in errs if e.startswith('网格对齐')]
        c.check(not grid, f'{n} 全部坐标落格', grid[0][:70] if grid else f'吸附提示 {len(notes)} 条')

    c.section('确定性：换哈希种子，产物必须字节相同')
    yp = _art(first, 'yaml')
    digests, rcs = set(), []
    for seed in ('0', '1', '12345'):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        h, d = tmp / f'h{seed}.html', tmp / f'd{seed}.drawio'
        rc_h, _ = run('render_html.py', yp, '-o', h, env=env)
        rc_d, _ = run('render_drawio.py', yp, '-o', d, env=env)
        rcs.append((rc_h, rc_d))
        # 渲染崩溃时产物文件不存在，直接 md5 会把整面炸掉；rc 并入断言，
        # 防止"三次全崩、都没写出文件"被算成"三个种子下一致"
        if rc_h == 0 and rc_d == 0:
            digests.add((md5(h), md5(d)))
    c.check(rcs == [(0, 0)] * 3 and len(digests) == 1, '三个种子下产物一致',
            f'渲染 rc={rcs}；{sorted(digests)}')

    c.section('幂等：build 两次产物不变')
    # **必须在副本里跑**：build.py 会重渲染 flow.yaml/flow.html/flow.drawio。
    # 直接在样例上跑有两重罪——① 用户在 drawio 里的手工微调被静默覆盖；
    # ② 幂等断言本身会因此失败（拿"手改产物"当基准），把真问题混成假警报（DECISIONS.md D-20）。
    # 进循环前记下事实源指纹，循环后逐字节复核（见本节末尾的"examples/ 是只读的事实源"）。
    src_digests = {p.relative_to(EXAMPLES).as_posix(): md5(p)
                   for p in sorted(EXAMPLES.rglob('*')) if p.is_file()}
    for n in SAMPLES:
        # **目录名必须与样例同名**：产物名由目录名决定（D-51），换个目录名 build 就会产出
        # 另一个名字的文件——`idem-<名>/` 这种前缀会让"产物不变"根本无从比对（旧名字的文件
        # 永远不会被重写，md5 恒等 → 假绿）。tmp 本身已按样例名隔离，不会互相污染。
        work = tmp / n
        shutil.rmtree(work, ignore_errors=True)
        # **工作树 = examples 的整棵树（事实源）+ 基线产物盖上去**（D-66 后的形态）。
        # 两半都不能少，各自的坑都踩过：
        #   ① 缺 `parts/*/flowtable.md` ⇒ 主表读不到子表，**不内嵌子图视图**（静默降级，D-52），
        #      柱状产品必然与基线不同——"幂等"被假红（实测：html 少 8 段 style、3 个 data-sub 消失）。
        #   ② 缺基线的 `*.yaml` ⇒ build 只能从零重排，丢掉只存在于 yaml 的手调几何（D-18）。
        # 只 `copytree(EXAMPLES)` 会踩②，只 `copytree(BASE)` 会踩①。先铺①、再叠②。
        shutil.copytree(EXAMPLES / n, work)
        shutil.copytree(BASE / n, work, dirs_exist_ok=True)
        # 产物集合要跟**注册表**走：漏掉一类，那一类的"幂等"与"未改 examples"就没人守
        # （W7b 加 svg 时正是这个缺口——原先只列 yaml/html/drawio）。
        arts = [prod(work, f) for f in ('yaml', 'html', 'drawio', 'svg')]
        before = [md5(p) for p in arts]
        rc, out = run('build.py', work / 'flowtable.md')
        # rc 并入：build 崩溃时产物不会更新，md5 恒等会让"幂等"假通过
        c.check(rc == 0 and before == [md5(p) for p in arts], f'{n} build 幂等',
                '' if rc == 0 else f'build rc={rc}：{out.strip()[-100:]}')
        # 比基线而不是"自比"：自比只能证明 build 两次一样，证明不了**这一版代码**
        # 画出来的还是当初审过的那份产物（跨版本漂移就是这么溜过去的）。
        c.check([md5(p) for p in arts] == [md5(_art(n, p.suffix.lstrip('.'))) for p in arts],
                f'{n} 重建产物与基线逐字节相同')

    c.section('examples/ 是只读的事实源')
    # D-66 之后 examples/ **只有** flowtable.md（产物在 dev/baseline/），所以这条能直接
    # 逐字节证明"跑完整面测试没往事实源里写过一个字节"——比原先"拿样例目录自比"更干脆。
    after = {p.relative_to(EXAMPLES).as_posix(): md5(p)
             for p in sorted(EXAMPLES.rglob('*')) if p.is_file()}
    c.check(after == src_digests, '验证过程未改 examples/',
            '；'.join(sorted(set(after) ^ set(src_digests)))[:80])
    # 上面那条只答"跑测试期间变没变"，答不了"examples/ 里本来就躺着生成文件"——实测过一次：
    # 就地试跑一遍 build，事实源目录里留下 20 个生成物（与基线同名的那两份已经分叉），
    # 而所有面全绿。判据只认**已知的产物形态**（扩展名 + `-index.md`），不规定"只许有 md"：
    # 事实源将来可能是 png / 外部 drawio，那是输入不是产物。
    PROD = ('.html', '.drawio', '.svg', '.yaml', '.json')
    junk = [p.relative_to(EXAMPLES).as_posix() for p in sorted(EXAMPLES.rglob('*'))
            if p.is_file() and (p.suffix in PROD or p.name.endswith('-index.md'))]
    c.check(not junk, 'examples/ 下只有事实源（机器产物住 dev/baseline/，见 D-66）',
            '多余 ' + '；'.join(junk[:4]))

    c.section('自愈：离格值被吸附且不阻断')
    # 先合成一张单列流程表拿到底稿：`col_x` 得有**显式**的列中心才谈得上"离格"
    # （多列产物的 `col_x` 是空表，由字典 col_pitch 展开，没有可手改的数）。
    fix = tmp / 'heal-src.md'
    fix.write_text(HEAD + ''.join([row('受理', '01', '收到', '开始', '甲方', '甲', '—', '→02'),
                                   row('归档', '02', '归档', '结束', '甲方', '甲', '—', '—')]),
                   encoding='utf-8')
    y = tmp / 'heal.yaml'
    rc0, out0 = run('table_to_dsl.py', '--write', fix, '-o', y)
    if not c.check(rc0 == 0, '合成底稿可转 DSL', out0.strip()[-80:]):
        return c
    # EOL 不可知：yaml 落盘换行随平台（write_text 按 os.linesep 翻译），LF 检出下硬编码
    # \r\n 会替换 0 次——这正是 README 修复表里"声称已修"的那条，曾只改了 gates 漏了这里
    import re as _re
    y.write_bytes(_re.sub(rb'  - 400(\r?\n)', rb'  - 442\g<1>', y.read_bytes(), count=1))
    rc, out = run('validate.py', y)
    L = load(str(y))
    c.check(L.col_x[0] % 20 == 0, '离格 col_x 已吸附到格上', f'col_x[0]={L.col_x[0]}')
    c.check(rc == 0 and '网格吸附' in out, '给出吸附提示但不阻断')

    c.section('图例带：带内无节点、无折点')
    L = load(str(_art(first, 'yaml')))
    _, _, _, lh = L.legend_rect()
    intrude = [n['id'] for n in L.dsl['nodes'] if L.rect(n['id'])[1] < lh]
    edge_in = [f"{e['from']}→{e['to']}" for e in L.edges if any(p[1] < lh for p in L.path(e))]
    c.check(not intrude, '带内无节点', str(intrude))
    c.check(not edge_in, '带内无折点', str(edge_in[:3]))

    c.section('门面一致：Engine.sizes 必须直接指向 grid.sizes')
    # 渲染器按 L.sizes 画框、rect() 按 grid.sizes 定位；两者不是同一个对象就会错位。
    # 用 `is` 而不是 `==`：字典里写非格上尺寸时 fit_size 会改写 grid.sizes，
    # 而 model.sizes 留原值——两者内容可能恰好相等，但一旦被吸附过就分叉。
    bad = []
    for q in EXAMPLES.glob('*/flowtable.md'):
        p = _art(q.parent.name, 'yaml')
        L = load(str(p))
        if L.sizes is not L.grid.sizes:
            bad.append(p.parent.name)
    c.check(not bad, '每个样例的 sizes 都是 grid.sizes 本体', '；'.join(bad))

    c.section('自举树基线：改错了也要红（D-67）')
    # 上面的样例是从 `examples/*/flowtable.md` **发现**的，而 examples/ 下只有 workflow 一个
    # （D-66）⇒ 自举那棵树（D-67：连表带产物一起进库，88 个文件）**没有任何比对仪器**：
    # 它改错了、或者重钉顺序错了（先镜像 self-boot 再重钉 workflow，表会被删掉），都不会红，
    # 而"两份基线重钉"这句说法让人以为它被守着。
    #
    # **必须重跑整条链、不是只 build**：那批模块 yaml 是 `selfboot_gen.py` 带布局提示展开出来的
    # （`row` 来自生成器的拓扑序，不是表序）——只把表铺进临时目录再 build，会得到另一套 row，
    # 于是"重建"与基线全不可比（本检查的第一版就是这么假红的：54 个文件里全是 row/kind 差异）。
    # 所以：生成器重造表 → build 出图 → 与基线**整树逐字节**比。目录名必须是 `self-boot`（D-51）。
    sb = BASE / 'self-boot'
    c.check(len(list(sb.rglob('flowtable.md'))) == 28, '自举树基线含 28 张表（1 根表 + 27 模块表）',
            f'{len(list(sb.rglob("flowtable.md")))} 张')
    work = tmp / 'self-boot'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rc, out = run(os.path.join('..', 'dev', 'tools', 'selfboot_gen.py'), '--out', work, '--quiet')
    if c.check(rc == 0, '自举树可按生成器重造（fn-graph.json → 28 张表）',
               '' if rc == 0 else out.strip()[-100:]):
        rc2, out2 = run('build.py', work / 'flowtable.md')
        if c.check(rc2 == 0, '重造的自举表可出图（28 张一次跑通）',
                   '' if rc2 == 0 else out2.strip()[-100:]):
            old = {p.relative_to(sb).as_posix(): md5(p) for p in sb.rglob('*') if p.is_file()}
            new = {p.relative_to(work).as_posix(): md5(p) for p in work.rglob('*') if p.is_file()}
            diff = sorted(k for k in old if k in new and old[k] != new[k])
            gone, extra = sorted(set(old) - set(new)), sorted(set(new) - set(old))
            c.check(not (diff or gone or extra),
                    '自举树重造结果与基线逐字节相同（表 / yaml / manifest / 三份产物）',
                    f'不同 {len(diff)} · 少 {len(gone)} · 多 {len(extra)}：'
                    + '、'.join((diff + gone + extra)[:3]))
    return c


if __name__ == '__main__':
    from _lib import SKILL
    sys.exit(0 if run_face(SKILL / '.verify_tmp').summary() else 1)
