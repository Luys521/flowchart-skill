# -*- coding: utf-8 -*-
"""invariants.py — 面③：不变式。不靠"这次对了"，靠"永远对"。

  1 网格贴合：直接复用 validate.check()，不另写一套审计（验证要验的就是那份实现）
  2 确定性：换 PYTHONHASHSEED 多次渲染，产物必须逐字节相同（否则说明有集合迭代顺序依赖）
  3 幂等：同一流程表 build 两次，产物不变
  4 并行：两棵树同时 build（**同一个 cwd**）⇒ 产物仍等于基线、且不往 cwd 漏文件（D-119）
  5 产物一律 LF：build 写出的产物不带 CR（换平台也得同字节；D-116）
  6 只读事实源：跑完整面测试不许往 `examples/` 写一个字节，且那里**不许有产物**（D-66）
  7 自愈：手塞离格几何 → 吸附 + 提示，且仍通过
  8 图例带：带内不得出现节点/折点（origin_y 已按带高下推，这是结构保证）
  9 门面一致：`Engine.sizes` 必须直接指向 `grid.sizes`（否则两层各拿一份尺寸，改了不同步）
 10 公共层内部无环：读数（`cohesion.py --cycles`）为 0 组，**且**仪器喂一张造出来的环能报出非零（D-127）
 11 stderr 编码：带 CLI 的模块若往 stderr 打非 ASCII 必须自己配编码；**纯库一律走 `console.warn`**
    （且它在管道下也读得出来——判据读的是**原始字节**，不是实现；D-127 / D-129）

（清单与 `run_face` 的 `c.section` 一一对应；增删小节时这里要跟着改。）
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import BASE, EXAMPLES, HEAD, PY, SCRIPTS, SKILL, Case, md5, prod, row, run  # noqa: E402

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
    crlf = []                      # 刚 build 出来的产物里带 CR 的（见本节末的「产物一律 LF」）
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
        crlf += [p.relative_to(work).as_posix() for p in arts
                 if b'\r' in p.read_bytes()]

    c.section('并行：两棵树同时 build，产物仍等于基线、且不往 cwd 漏文件（D-119）')
    # 为什么值得单独一节：`PIPELINE-SPEC` §7 把"并行的单位是流程 / 任务"写成了规矩
    # （各一棵产物树、各一个工作目录），可**没有任何仪器证明过它**——上面那条幂等只证明
    # "同一棵树两次相同"。而"能不能并行"恰恰是用户会问的那个问题（批量跑、多流程一起出图）。
    # 判据三件，都在**同一个 cwd** 下跑（cwd 是两个进程唯一共享的东西，也是最容易漏的地方）：
    #   ① 两个进程同时 build，各自 rc=0；② 各自产物与基线**逐字节**相同；
    #   ③ **cwd 里除了这两棵树什么都没有**——默认落盘若还钉在 cwd（D-119 之前就是），这里当场红。
    par = tmp / 'par'
    shutil.rmtree(par, ignore_errors=True)
    trees = []
    for tag in ('a', 'b'):
        work = par / tag / 'workflow'
        shutil.copytree(EXAMPLES / 'workflow', work)
        shutil.copytree(BASE / 'workflow', work, dirs_exist_ok=True)   # 同幂等那节：事实源 + 基线产物
        trees.append(work)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
    procs = [subprocess.Popen([PY, str(SKILL / 'scripts' / 'build.py'), str(w / 'flowtable.md')],
                              cwd=str(par), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding='utf-8')
             for w in trees]
    outs = [p.communicate(timeout=300)[0] for p in procs]
    rcs = [p.returncode for p in procs]
    same = all([md5(prod(w, f)) for f in ('yaml', 'html', 'drawio', 'svg')]
               == [md5(_art('workflow', f)) for f in ('yaml', 'html', 'drawio', 'svg')]
               for w in trees)
    leaked = sorted(p.name for p in par.iterdir() if p.name not in ('a', 'b'))
    c.check(rcs == [0, 0] and same and not leaked,
            '两个进程同时 build：rc 都是 0 · 产物逐字节等于基线 · cwd 里没漏出别的文件',
            f'rc={rcs} · 产物等于基线={same} · cwd 多出 {leaked or "无"}'
            + (f' · {outs[0].strip()[-120:]}' if rcs != [0, 0] else ''))

    c.section('产物一律 LF：换个平台也得同字节（D-115）')
    # 为什么单独一节：本仓的安全网是"逐字节不变"（`.gitattributes` 用 `* -text` 让 Git 不碰字节），
    # 但**写产物那一侧有没有钉 LF** 一直没人管——`Path.write_text()` 不传 `newline=` 时，
    # Windows 会把 `\n` 翻成 `\r\n`。实测（2026-09-19）：`*-flow.yaml` / `*.manifest.json` /
    # 三份产物在 Windows 上是 CRLF，而 `flowtable.md`（走 `write_bytes`）是 LF；
    # 所有比对都是"自己跟自己比"，所以**没有任何仪器看得见**——一旦有人在 Linux 上跑，
    # 基线整棵树都会"逐字节不同"。判据落在**刚造出来的那几份产物**上（不是基线）：
    # 这样写产物那一侧的回归当场现形，而不是等到换平台。
    c.check(not crlf, 'build 写出的产物没有 CR（跨平台同字节）',
            '；'.join(crlf[:4]))

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
    # （D-66）⇒ 自举那棵树（D-67：连表带产物一起进库，118 个文件）**没有任何比对仪器**：
    # 它改错了、或者重钉顺序错了（先镜像 self-boot 再重钉 workflow，表会被删掉），都不会红，
    # 而"两份基线重钉"这句说法让人以为它被守着。
    #
    # **必须重跑整条链、不是只 build**：那批模块 yaml 是 `selfboot_gen.py` 带布局提示展开出来的
    # （`row` 来自生成器的拓扑序，不是表序）——只把表铺进临时目录再 build，会得到另一套 row，
    # 于是"重建"与基线全不可比（本检查的第一版就是这么假红的：54 个文件里全是 row/kind 差异）。
    # 所以：生成器重造表 → build 出图 → 与基线**整树逐字节**比。目录名必须是 `self-boot`（D-51）。
    sb = BASE / 'self-boot'
    # 张数**从依赖图现取**（一个模块一张表 + 1 根表）：手写死数在加模块时必漂（G7 抓到过五处）。
    n_mod = len(json.loads((SKILL / 'dev' / 'tools' / 'fn-graph.json').read_text(encoding='utf-8'))
                .get('files') or {})
    n_tab = len(list(sb.rglob('flowtable.md')))
    c.check(n_tab == n_mod + 1, f'自举树基线含 {n_mod + 1} 张表（1 根表 + {n_mod} 模块表）', f'{n_tab} 张')
    work = tmp / 'self-boot'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rc, out = run(os.path.join('..', 'dev', 'tools', 'selfboot_gen.py'), '--out', work, '--quiet')
    if c.check(rc == 0, '自举树可按生成器重造（fn-graph.json → 全部模块表）',
               '' if rc == 0 else out.strip()[-100:]):
        rc2, out2 = run('build.py', work / 'flowtable.md')
        if c.check(rc2 == 0, '重造的自举表可出图（整树一次跑通）',
                   '' if rc2 == 0 else out2.strip()[-100:]):
            old = {p.relative_to(sb).as_posix(): md5(p) for p in sb.rglob('*') if p.is_file()}
            new = {p.relative_to(work).as_posix(): md5(p) for p in work.rglob('*') if p.is_file()}
            diff = sorted(k for k in old if k in new and old[k] != new[k])
            gone, extra = sorted(set(old) - set(new)), sorted(set(new) - set(old))
            c.check(not (diff or gone or extra),
                    '自举树重造结果与基线逐字节相同（表 / yaml / manifest / 三份产物）',
                    f'不同 {len(diff)} · 少 {len(gone)} · 多 {len(extra)}：'
                    + '、'.join((diff + gone + extra)[:3]))

    c.section('公共层内部无环（D-123 建立的属性；D-127 接成仪器）')
    # 为什么要有这一节（2026-09-19，D-127）：`REPO-MAP` / `DECISIONS` D-123 都写着"公共层无环"，
    # 而那**是一句人工结论**——`layering.py` 只打印边数与方向违规，**不查环**
    # （`selfboot_gen._find_cycle` 查的是**流程图**的环，不是模块依赖图）；D-123 那条甚至把它
    # 记成"`layering` 现算'环：无'"，**归因是错的**。也就是说：这句话当时谁也复算不了，
    # 而 D-123 正是花力气拆掉那个环的提交。**一条只被人工确认过一次的性质，等于没有性质。**
    #
    # 两条一起判，缺一条都不算数：① 现状确实无环；② **仪器报得出非零**——只判第①条的话，
    # 一个恒返回"无"的装饰器也能全绿（本套件已经栽过同类跟头：夹具自己搜到自己的账本、门只看 rc 不看内容）。
    rc, out = run(os.path.join('..', 'dev', 'tools', 'cohesion.py'), '--cycles')
    c.check(rc == 0 and '允许边上的环：0 组' in out and '环：无' in out,
            '现状：允许边上的环 0 组（公共层互引 / 编排层互引都没有闭环）',
            out.strip().splitlines()[-1].strip() if rc == 0 else out.strip()[-100:])
    # ② 把一张**造出来的**环喂给同一个函数：它必须报得出来，且认出是哪一层
    prog = ('import sys; sys.path.insert(0, "dev/tools"); import cohesion; '
            'ro = ({"a", "b"}, set(), set()); e = {"a": {"b": {"x"}}, "b": {"a": {"y"}}}; '
            'print(cohesion.cycles(edges=e, rosters=ro))')
    r = subprocess.run([PY, '-c', prog], capture_output=True, text=True, encoding='utf-8',
                       cwd=str(SKILL), timeout=60)
    got = (r.stdout or '').strip()
    c.check(r.returncode == 0 and got == "[('公共层', ['a', 'b'])]",
            '仪器有效：造一个 a↔b 的环，它报得出非零（"环：无"不是装饰）',
            got or (r.stderr or '').strip()[-100:])

    c.section('stderr 的中文读得出来（D-127）')
    # 为什么要有这一节：Windows 上**管道 / 重定向**时 stderr 默认是 GBK，而各 CLI 都只把 **stdout**
    # 配成 utf-8（30/30 配了 stdout，只有 14 个配了 stderr）。于是"只配 stdout"的模块往 stderr 打中文
    # **不会报错、只会悄悄退化**——`⚠` 不在 GBK 里 ⇒ 变成字面量 `\u26a0`，中文全成 `?`。
    # 实测（`drift.py` 的错误分支，读原始字节）：`\u26a0 ��������ˣ…`。而那句正是
    # "**仪器故障，不是内容问题**"的诊断，外加 `thresholds.load` 的"段名是不是改了"告警——
    # 两句都只在真出问题时才出现，也就是说**它们恰好在最需要被读到的时候读不出来**。
    #
    # 判据取"**CLI 模块（进程入口）必须自己定两个流的编码**"：进程的流编码是入口的职责，
    # 而且这条把"将来往 stderr 加一句中文"也一并管住。**纯库不许自己写**——它们一律走
    # `console.warn`（D-129 收的那个唯一出口），所以下面第二条从"豁免名单"升成了**硬判据**。
    nonascii = re.compile(r'[^\x00-\x7f]')

    def _stderr_nonascii(src_text):
        """AST：这个模块有没有往 stderr **写非 ASCII 文本**。行内正则认不出 f-string 与多行调用。

        **只看文本层**（`print(..., file=sys.stderr)` / `sys.stderr.write`）——`console.warn`
        走的是**字节层**（`sys.stderr.buffer.write`），那正是本仓唯一被允许的写法；
        它不是"扫描器的漏网"，下面第三条会**从产物侧**证明它真的读得出来。
        """
        hits = 0
        for node in ast.walk(ast.parse(src_text)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            to_err = any(k.arg == 'file' and isinstance(k.value, ast.Attribute)
                         and k.value.attr == 'stderr' for k in node.keywords)
            if isinstance(f, ast.Attribute) and f.attr == 'write' \
                    and isinstance(f.value, ast.Attribute) and f.value.attr == 'stderr':
                to_err = True
            if not to_err:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and nonascii.search(sub.value):
                    hits += 1
                    break
        return hits

    bad_err, lib_err = [], []
    for p in sorted(SCRIPTS.glob('*.py')):
        t = p.read_text(encoding='utf-8')
        if not _stderr_nonascii(t):
            continue
        if '__main__' in t:
            if 'sys.stderr.reconfigure' not in t:
                bad_err.append(p.stem)
        elif p.stem != 'console':          # `console` 是那个出口本身，见下
            lib_err.append(p.stem)
    c.check(not bad_err,
            '带 CLI 的模块：往 stderr 打中文的自己配了编码（不再有"只配 stdout"的）',
            '没配：' + '、'.join(bad_err) if bad_err else '')
    c.check(not lib_err,
            '纯库不自己往 stderr 写中文——一律走 `console.warn`（留痕出口只有一个）',
            '裸写：' + '、'.join(lib_err) if lib_err else '')

    # 第三条**判在产物上**：把一句留痕放进**管道**（本地编码那一档，实测 stderr=gbk），
    # 读**原始字节**、按 utf-8 解——解不回原句就是没修好。为什么不信"实现写对了"：
    # 这套判据的第一版就是只看"有没有配 `reconfigure`"，而真正要保证的是**读得出来**。
    prog = ('import sys; sys.path.insert(0, "scripts"); from console import warn; '
            'warn("\u26a0 段名是不是改了？")')
    r = subprocess.run([PY, '-c', prog], capture_output=True, cwd=str(SKILL), timeout=60)
    raw = r.stderr if isinstance(r.stderr, bytes) else (r.stderr or '').encode('utf-8', 'replace')
    got = raw.decode('utf-8', 'replace').strip()
    c.check(r.returncode == 0 and '⚠ 段名是不是改了？' in got and '\\u26a0' not in got,
            '留痕在**管道**下也读得出来（原始 stderr 按 utf-8 解得回原句，不退化）',
            got[:90] or '（stderr 是空的）')
    return c


if __name__ == '__main__':
    from _lib import SKILL
    sys.exit(0 if run_face(SKILL / '.verify_tmp').summary() else 1)
