# -*- coding: utf-8 -*-
"""build.py — 一键渲染：流程表 → 碰撞检测 → flow.html + flow.drawio。

管线：结构校验 → 转 DSL（可复用已手调几何）→ 碰撞检测 → HTML → drawio → **产物审核**（见 D-11）。

用法：build.py "output/<名称>/flowtable.md" [--no-layout] [--quality showcase]
（--no-layout 丢弃已有几何重排；--quality showcase 把软提示/吸附提示升级为阻断，见 D-55）。
已有 flow.yaml 时默认复用其几何以保护手工微调。退出码 0 = 全通过并产出。
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

from artifact import artifact_stem
from engine import load as load_dsl
from flowtable import find_parent_table
from table_to_dsl import (main as t2d_main)
from semantics import is_pending, pending_kind
from manifest import (check as audit, summary, manifest_path_for,
                      artifact_geometry, read_html, read_drawio, read_svg,
                      geometry_from_html, geometry_from_drawio, geometry_from_svg)
from validate import main as validate_main, check as check_geometry, check_artifact
# `render_html` 是**必需**的：主干靠它产出可用的评审图 ⇒ 硬 import，缺了就该当场炸。
from render_html import render as render_html, collect_views
# 可选渲染器：模块不在就**降级**——注册表里没有它，主干照出 html，只是少一个产物。
# 这是"把其它模块暂时关掉也不影响出图"的落点（W7a）。判定与告知见 `build_registry`。
try:
    from render_drawio import render as render_drawio, discover_pages
except ImportError:
    render_drawio = discover_pages = None
try:
    from render_svg import render as render_svg
except ImportError:
    render_svg = None


def _ids(yaml_path):
    """读 flow.yaml 里的节点 id 集合；读不动（文件坏/不存在/缺 id 键）返回空集。

    这是"新增节点提醒"的辅助视角，不值得为它阻断渲染——所以口径放最宽。"""
    try:
        d = yaml.safe_load(Path(yaml_path).read_text(encoding='utf-8-sig'))
        return {n['id'] for n in (d or {}).get('nodes', [])}
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return set()


def _rollback(prev, *paths):
    """审核未过 → 把刚写下的产物还原成审核前的样子（原本不存在的就删掉）。

    产物是**先渲染、后审核**的：审不过必须还原，否则盘上躺着半成品交付物——第四步第 6 环那句
    "审核不过会 exit 1"就成了半句话（退出码对了，文件却已经换成了没审过的那一版）。
    """
    for p in paths:
        if p in prev:
            p.write_bytes(prev[p])
        elif p.exists():
            p.unlink()


def _rollback_manifest(prev_bytes, yaml_path):
    """渲染契约跟产物**同进同退**：失败时还原成上一版（原本不存在的就删掉）。见 D-81。

    契约里的 `source_sha256` 是 `sync` 判"《流程表》有没有被直改过"的唯一依据，而它由
    `table_to_dsl` 在**渲染之前**写下一轮的指纹。后面任一环失败时产物被还原成上一版、契约却
    已经指向新表 ⇒ `sync --fresh` 从此回答"表未变"，stale 门禁**永久失效**（实测走得通）。
    还原成上一版后状态是自洽且**看得见**的：产物旧、契约旧、yaml 新 ⇒ 任何消费者都会报不一致。
    """
    mf = manifest_path_for(yaml_path)
    if prev_bytes is None:
        mf.unlink(missing_ok=True)
    else:
        mf.write_bytes(prev_bytes)


def _prepare_child(md):
    """给一张后代子表补上 DSL（结构校验 → 转 DSL）。见 D-52。

    主 html 要**内嵌**子图，就得先有子图的 `flow.yaml`——它平时是用户单独 build 那张子表时
    产出的。等用户自己去 build 一遍才内嵌，等于没做：所以主 build 顺手把它备齐。
    只补 DSL 不补 html/drawio：html 已经不再单独产出了，drawio 仍是谁 build 谁有（多页承载层级）。

    **这里只补 DSL，不查几何**：几何门禁由 `_prepare_views` 对**所有最终会内嵌的子表**统一跑。
    放在这里会漏掉"yaml 早已存在"的子表（它不经过本函数）——那正是门禁被绕过的那条路。

    失败**只警告不阻断**：主图本身是好的，不该被孙表里一个坏坐标拖着不产出——
    那张子表就不会被内嵌（不可下钻），与"产物不存在就降级"同一口径。
    """
    from pathlib import Path as _P
    yml = _P(md).parent / f'{artifact_stem(_P(md))}-flow.yaml'
    if t2d_main(['--check', str(md)]) != 0:
        print(f'  ⚠ 子表未内嵌（结构校验未过）：{md}')
        return False
    args = ['--write', str(md), '-o', str(yml)]
    if yml.exists():
        args = ['--write', '--layout', str(yml), str(md), '-o', str(yml)]
    if t2d_main(args) != 0:
        print(f'  ⚠ 子表未内嵌（转 DSL 失败）：{md}')
        return False
    return True


def _gate_child_view(key, yml):
    """对一张**会内嵌的子表**跑几何门禁；只警告不阻断（见 D-52）。

    与 `_prepare_child` 分开是刻意的：`_prepare_child` 只服务"yaml 还不存在"的子表，
    而 **yaml 已存在**的子表（外部工具预生成、或上一次 build 留下的）根本不经过它——
    实测过：同一批子表在一次改动前后「碰撞检测未过」从 22 行掉到 0 行，不是它们合格了，
    是这条路径整条不查了。门禁**只能按"会不会内嵌"跑，不能按"yaml 在不在"分岔**。

    "未过"与"未内嵌"是两件事，措辞必须分开：yaml 已在盘上 → 它会被内嵌，只是几何不过；
    只有补不出 DSL 才是"未内嵌"（那由 `_prepare_child` / `absent` 报）。
    """
    try:
        L = load_dsl(str(yml))
    except (OSError, ValueError, KeyError, TypeError) as e:
        # 读不动 = 渲染时 `_assemble_view_blocks` 会 `continue` 跳过它 → 实际没内嵌。仍只警告。
        print(f'  ⚠ 子表未内嵌（DSL 读不动，渲染时跳过）：{key} — {e}')
        return
    errs, _ = check_geometry(L)
    if errs:
        print(f'  ⚠ 子表已内嵌但几何未过（{len(errs)} 项）：{key}')
        print(f'     - {errs[0]}')


def _find_parent(ft):
    """这张流程表是不是别人的下钻子图？是则返回 (父图相对链接, 父节点名)，不是返回 None。

    扫描本身在 `table_to_dsl.find_parent_table`（配色继承也用同一份）——**只扫一次、只认一种父子关系**
    是刻意的：面包屑的"回程路"与配色的"继承链"必须是同一棵树，否则会出现"能走回去但颜色不继承"
    这种半吊子状态，排查时两头都对不上。
    """
    r = find_parent_table(ft)
    if not r:
        return None
    parent_ft, node_name = r
    # 回程链接指向**父图的产物**（同一套命名规则算出来的名字），不是父图流程表。
    href = os.path.relpath(parent_ft.parent / f'{artifact_stem(parent_ft)}-flow.html',
                           ft.parent).replace('\\', '/')
    return href, node_name


def _parse_args(argv):
    """解析 build 的命令行参数。"""
    ap = argparse.ArgumentParser(description='流程表 → HTML + drawio 一键渲染')
    ap.add_argument('flowtable', help='flowtable.md 路径')
    ap.add_argument('--no-layout', action='store_true',
                    help='忽略已有 flow.yaml 的几何，按表序重排。'
                         '⚠ 会丢弃"哪些节点并排"这类只存在于 flow.yaml 的信息（见 DECISIONS.md D-18），'
                         '重排后必须人工复核列归属')
    ap.add_argument('--no-pages', action='store_true',
                    help='drawio 只渲染主图、不把子流程铺成附加页（见 D-47）。'
                         '默认：有 `⊞` 子表就自动多页；没有则与单页时代逐字节相同')
    ap.add_argument('--quality', choices=['standard', 'showcase'], default='standard',
                    help='showcase：软提示/吸附提示也阻断，零提示才产出；默认 standard（见 D-55）')
    return ap.parse_args(argv)


def _check_structure(ft, quality):
    """跑结构校验；未过则报错并返回 1。"""
    print('--- 结构校验 ---')
    rc = t2d_main(['--check', str(ft), '--quality', quality])
    if rc != 0:
        print('✗ 结构校验未过：已阻断渲染，不产出任何交付物。修正 flowtable.md 后重跑。')
        return 1
    return 0


def _gen_dsl(ft, yaml_path, quality, no_layout):
    """生成 DSL（可复用已有 flow.yaml 几何）；复用时提示新增节点，失败返回 1。"""
    print('--- 生成 DSL ---')
    args = ['--write', str(ft), '-o', str(yaml_path), '--quality', quality]
    old_ids = None
    if not no_layout and yaml_path.exists():
        # 读旧 yaml 的节点 id，跑完后再 diff——新加的节点在 --layout 模式下会被拍到 col=0，
        # 经常不是用户想要的列；与其静默产出列归属不直观的图，不如明说。
        old_ids = _ids(yaml_path)
        args = ['--write', '--layout', str(yaml_path), str(ft), '-o', str(yaml_path)]
        print('（复用已有 flow.yaml 的几何）')
    rc = t2d_main(args)
    if rc != 0:
        return 1
    if old_ids is not None:
        added = _ids(yaml_path) - old_ids
        if added:
            print(f'  ⚠ 新增 {len(added)} 个节点（{"、".join(sorted(added))}）：'
                  f'复用旧几何会把它们一律放到 col=0')
            print(f'    若要让新节点各归其列，用 --no-layout 重排')
    return 0


def _validate_geometry(yaml_path, quality):
    """跑碰撞检测；未过则报错并返回 1。"""
    print('--- 碰撞检测 ---')
    rc = validate_main(str(yaml_path), quality=quality)
    if rc != 0:
        print('✗ 碰撞检测未过：只可调 flow.yaml 的几何字段后重跑——流程布局 row/col/gutter/gapx/channel，'
              '泳道布局 row/col/sdye/dye（泳道不读 gutter/gapx/channel，尺寸参数在字典 lane: 段）。禁止改语义。')
        return 1
    return 0


def _prepare_views(yaml_path):
    """备齐后代子表的 DSL（BFS 至多 5 轮），报告内嵌/缺失并返回视图计划。

    单文件（D-52）：先把后代子图的 DSL 备齐，主 html 才能把它们内嵌成视图。
    一轮备不齐就再来一轮——孙表只有等子表的 DSL 生成后才"看得见"（BFS 靠 DSL 往下走）。

    备齐后**对所有会内嵌的子表跑一遍几何门禁**（`_gate_child_view`）。这一步不能并进
    `_prepare_child`：那里只服务"yaml 还不存在"的子表，yaml 已存在的子表会整条跳过门禁
    （见 `_gate_child_view` 的注释）。门禁**只警告不阻断**，主图照常产出。

    撞上 `MAX_VIEWS` 而被截断的子表（`plan['truncated']`）也**只警告不阻断**：它们确实没进
    HTML，但主图本身是好的——与"子表失败只警告"同一契约，只是不允许它不声不响。

    DSL 读不动的表（`plan['unreadable']`）同样只警告不阻断。这一类要报的**不是它自己**
    （那条由 `_gate_child_view` 报），而是"它的子孙枚举不出来、既未内嵌也未校验"——
    否则那一支会整支不出现也不报告。
    """
    plan = collect_views(str(yaml_path))
    for _ in range(5):
        if not plan['pending']:
            break
        for md in list(plan['pending']):
            _prepare_child(md)
        plan = collect_views(str(yaml_path))
    else:
        # 轮数耗尽仍有没备齐的：其余两条降级路径（子表不存在 / 备 DSL 失败）都有提示，
        # 唯独"嵌套太深"会一声不响地少内嵌几张——用户看到的是节点没有叠影卡、点不动。
        if plan['pending']:
            print(f'  ⚠ 子图嵌套超过 5 层，更深的 {len(plan["pending"])} 张未内嵌：'
                  f'{"、".join(Path(m).name for m in plan["pending"][:3])}' +
                  ('…' if len(plan['pending']) > 3 else ''))
    # 几何门禁按"会不会内嵌"跑，不按"yaml 在不在"分岔：`views` 就是**这一版真的会被内嵌**的
    # 全部子表（含 yaml 早已存在的那些），逐一过门禁，未过如实报出。
    for key, yml in plan['views']:
        _gate_child_view(key, yml)
    # 上限截断也必须报：被截掉的表**确实没进 HTML**（所以"未内嵌"是真话），但它们既不是
    # "DSL 补不齐"也不是"表不存在"——不报的话，少掉的那几张就是这条路上唯一不声不响的失效。
    # 上限值取自 `collect_views` 回传的 `max_views`，不在这句话里写死数字。
    if plan['truncated']:
        shown = '、'.join(k for k, _ in plan['truncated'][:3])
        print(f'  ⚠ 内嵌视图超过上限（MAX_VIEWS={plan["max_views"]}）：'
              f'{len(plan["truncated"])} 张子表未内嵌、未做几何校验（被截表的子孙也计入）：'
              f'{shown}' + ('…' if len(plan['truncated']) > 3 else ''))
    # 读不动的表：它自己那条由 `_gate_child_view` 报（它仍在 views 里），这里要报的是**报不了
    # 的那部分**——读不动就读不动，它的子孙枚举不出来，于是那一支会整支不出现也不报告。
    # 把"子孙未知、需人工确认"本身说出口，别让用户以为"没报警就是没少图"。
    if plan['unreadable']:
        shown = '、'.join(plan['unreadable'][:3])
        print(f'  ⚠ 有 {len(plan["unreadable"])} 张子表 DSL 读不动：'
              f'它们的子孙既未内嵌也未校验（无法枚举，需人工确认）：'
              f'{shown}' + ('…' if len(plan['unreadable']) > 3 else ''))
    # 张数取"真会内嵌的"：读不动的表在 `views` 里只为逐张告警用，它的视图块根本没拼出来，
    # 按 `views` 数就会报"内嵌 N 张"而产物里其实一张都没有——回执不能说谎。
    embedded = len(plan['views']) - len(plan['unreadable'])
    if embedded:
        print(f'  · 单文件：内嵌 {embedded} 张子图作为视图（下钻切视图，不跳页）')
    for md in plan['absent']:
        print(f'  ⚠ 子表不存在，未内嵌：{md}（节点里的 ⊞ 写错了路径）')
    return plan


def _render_products(yaml_path, products, ft, no_pages):
    """按**注册表**渲染全部产物；任一失败即还原旧产物并返回 None。

    渲染前把旧产物读进内存：这些产物常被**手工微调**（尤其 drawio 的几何），
    而 build 的契约就是"覆盖"。不留存的话，一次重跑就把手工成果永久抹掉（DECISIONS.md D-20）。
    同一份内存还兼作**回滚底本**：产物是先渲染、后审核的，审不过要还原（见 _rollback）。

    **遍历 `products` 而不是写死 html/drawio**（W5）：字典顺序即注册表顺序，
    与改动前"先 html 后 drawio"一致 ⇒ 行为逐字节不变。
    """
    prev = {p: p.read_bytes() for p in products.values() if p.exists()}
    for kind, path in products.items():
        ctx = _render_ctx(kind, yaml_path, ft, no_pages)
        try:
            rc = _renderer(kind)(str(yaml_path), str(path), ctx=ctx)
        except ValueError as e:
            # 节点 id 撞上 drawio 结构 id（0/1/title/lane-*）是**表里能改**的东西：
            # 甩 traceback 等于让人去读渲染器源码（engine.load 那里踩过同一条：要一句人话）
            print(f'✗ {e}')
            _rollback(prev, *products.values())
            return None
        except Exception as e:                      # noqa: BLE001 —— 见下
            # 渲染期**任何**异常都要走同一条还原路：只兜 ValueError 时，别的异常（KeyError、
            # TypeError、渲染器自身的 bug）会直接从 build 里逃出去，而**前面几份产物已经落盘**——
            # "审不过就还原"只对已经写下的那几份成立，剩下的成了半批交付物（D-84）。
            # 这里仍然打印人话并还原，而不是吞掉：异常类型与前 200 字带出去，便于归因。
            print(f'✗ 渲染 {kind} 时抛了 {type(e).__name__}：{str(e)[:200]}')
            _rollback(prev, *products.values())
            return None
        if rc != 0:
            _rollback(prev, *products.values())
            return None
    return prev


def _audit_contract(yaml_path, products, prev):
    """拿自检产出的契约反查**注册表里的每一份产物**；不过则还原产物并返回 1。

    前两道门禁都不看产物，这一环补「源 → 产物」的缺口。契约跟着 yaml 走（`manifest_path_for`），
    不拼约定名——产物名带流程名之后（D-51），`flow.manifest.json` 这个写死的名字只对
    "表名恰好是 flowtable"的目录成立。

    每份产物用**它自己声明的反解器**（注册表的 `ids`）读回节点/边集合，再与契约比（W6）。
    """
    print('--- 产物审核（契约 vs 产物）---')
    mf_path = manifest_path_for(yaml_path)
    if not mf_path.exists():
        print(f'✗ 找不到渲染契约 {mf_path}：它应由 table_to_dsl --write 产出，缺失说明上游被跳过')
        _rollback(prev, *products.values())
        return 1
    mf = json.loads(mf_path.read_text(encoding='utf-8'))
    specs = {kind: {'path': p, 'ids': _bind(RENDERERS[kind]['ids']),
                    'label': RENDERERS[kind]['label']}
             for kind, p in products.items()}
    errs = audit(mf, products=specs, yaml_path=yaml_path)
    print(f'契约: {summary(mf)}')
    if errs:
        print(f'✗ 产物审核未通过（{len(errs)} 项）：')
        for e in errs:
            print('   -', e)
        _rollback(prev, *products.values())
        return 1
    print(f'✓ {len(products)} 份产物与契约逐项一致（节点 id 集合 + 边集合）')
    return 0


def _lane_source(yaml_path):
    """底稿是不是泳道布局。

    这是**唯一**能把"流程布局的产物"与"泳道源但底图没画的产物"区分开的信号——两者在几何表上
    完全同形（band=0 / lanes=None）。所以只有这一层（手里有 yaml）能给出「该不该有底图」的
    期望，`validate.check_artifact` 拿它关门（见那里的 `_artifact_lane_expected`）。
    """
    return load_dsl(str(yaml_path)).lanes() is not None


def _audit_geometry(products, prev, expect_lanes=None):
    """反解**注册表里每一份产物**的真实坐标再跑几何门禁；不过则还原产物并返回 1。

    契约反查只比"有哪些节点/哪些边"；这一关反过来读产物里**真实写下的坐标**再跑一遍几何门禁。
    前两道门禁都用 router 现算折线，router 把线接歪时会跟着一起错——只有这一关是另立视角。

    每份产物用它自己声明的**几何反解器**（注册表的 `geom`）读成几何表（W6）。
    `expect_lanes` 由**知道底稿的调用方**传下来（`main` 用 `_lane_source`）——产物的坐标是产物
    自己写的，无法自证"我该不该有泳道底图"（见 `validate._artifact_lane_expected`）。
    """
    print('--- 产物几何自检（反解各产物的真实坐标）---')
    for kind, p in products.items():
        reader = _bind(RENDERERS[kind]['geom'])
        errs = check_artifact(artifact_geometry(p, reader=reader), expect_lanes=expect_lanes)
        if errs:
            print(f'✗ {p.name} 几何自检未过（{len(errs)} 项）：')
            for e in errs[:20]:
                print('   -', e)
            _rollback(prev, *products.values())
            return 1
    print('✓ 各产物的真实坐标复核通过（端点接框 / 不穿节点 / 不重叠 / 网格对齐 / 画布内 / '
          '每段不短于一格粗格；泳道另查里程碑带与底色）')
    return 0


def _write_layer_index(ft, out_dir, stem):
    """从各表 ⊞ 声明派生层级索引，写 <stem>-index.md 并报告表数与层级。

    层级索引（D-56）：每次 build 刷新（派生物，勿手改）。
    """
    from layer_index import build_layer_index, format_index_md
    idx = build_layer_index(ft)
    idx_path = out_dir / f'{stem}-index.md'
    idx_path.write_text(format_index_md(idx), encoding='utf-8', newline='\n')
    for n in idx['notes']:
        print(f'  ⚠ 层级索引: {n}')
    depth_max = max((max(t['depths']) for t in idx['tables'].values()), default=0)
    print(f'  · 层级索引: {idx_path.name}（{len(idx["tables"])} 张表，L0..L{depth_max}）'
          + ('；构建顺序见索引' if len(idx['tables']) > 1 else ''))


def _product_note(kind, embedded):
    """每类产物在交付清单里那句"它是干嘛的"（与 `_render_ctx` 同理：每类一处，集中放）。"""
    if kind == 'html':
        return ('   （评审语义：单文件'
                + (f'，已内嵌 {embedded} 张子图，发给客户就发这一个）' if embedded else '）'))
    if kind == 'drawio':
        return ' （微调几何：每层各一份，靠多页承载层级）'
    if kind == 'svg':
        return ' （朴素可编辑中间态：浏览器/Inkscape 直接开，不依赖专用软件）'
    return ''


def _report_receipt(products, ft, prev, plan):
    """留存被覆盖旧版为 .bak，并打印交付清单与 sha256 回执。

    审过才算这次的产物要交付——这时候留旧版为 .bak 才有意义（审不过的那一版已经还原掉了）。
    """
    for p, data in prev.items():
        if p.read_bytes() != data:
            bak = p.with_name('.' + p.name + '.bak')
            bak.write_bytes(data)
            print(f'  ℹ 旧版 {p.name} 已留存为 {bak.name}（本次渲染改变了它；'
                  f'若那是你手工调过的，用 sync.py 回写《流程表》而不是重跑 build）')

    print(f'✓ 交付 {len(products)} 份产物：')
    # 同 `_prepare_views`：张数取"真会内嵌的"，读不动的表不计（它的视图块没拼出来）。
    embedded = len(plan['views']) - len(plan['unreadable'])
    for kind, p in products.items():
        print(f'  {p}{_product_note(kind, embedded)}')
    # 交付回执（D-55，借鉴 wrench-ai 的 delivery）：转发者可拿摘要核对拿到的是审过的这一版。
    for p in products.values():
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f'  ✓ 回执 {p.name}: sha256:{digest} ({p.stat().st_size} 字节)')
    # 回写入口只认 drawio（`sync.py` 读的就是它的 xml）⇒ 这里点明 kind，不是漏改成通用。
    # drawio 是可选的：它不在（降级中）就别提回写——否则等于给了一条走不通的路。
    if 'drawio' in products:
        print('  几何改动后：python flowchart-skill/scripts/sync.py '
              f'"{products["drawio"]}" "{ft}"')


def _report_pending(yaml_path):
    """汇总图上 AI 推断处（虚线标出），提醒用户重点核对。

    与 _ids 同理：这是提醒，不是门禁，读不动就跳过。
    """
    try:
        dsl = yaml.safe_load(yaml_path.read_text(encoding='utf-8-sig')) or {}
        nodes = dsl.get('nodes', [])
        pend = [n['id'] for n in nodes if is_pending(n.get('desc'))]
        must = [n['id'] for n in nodes if pending_kind(n.get('desc')) == 'verdict']
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        pend, must = [], []
    if pend:
        shown = '、'.join(pend[:12]) + ('…' if len(pend) > 12 else '')
        tail = f'，其中必须业务方拍板 {len(must)} 处' if must else ''
        print(f'⚠ 图中有 {len(pend)} 处为 AI 推断（原文未载明）{tail}：{shown}')
        print('  已用两档虚线描边标出（红 = 必须拍板，橙 = 有依据的推断），悬浮可见说明；'
              '请重点核对，不对就说「XX 应该是 YY」')


# ---- 四阶段骨架与渲染器注册表（ARCHITECTURE.md 第九节 W1）------------------
# 「阶段」是**数据流**的视图，与模块的**依赖分层**是两个正交维度（第八节）：
# 层答"谁许 import 谁"，阶段答"谁生产谁消费"。这里把四阶段在代码里落成可被引用的
# 常量，成员是本文件里**已有的**阶段函数——`main` 本来就是按这个顺序调的。
#
# **本波只声明，不驱动执行**：`main` 仍按原样顺序调用，产物应当逐字节不变
# （这条正是 `dev/verify/run.py` 面③的两条断言在守：build 幂等 + 验证过程未改 examples/）。
STAGES = (
    ('流程表制作', '人写的 flowtable.md', '校验过的 flowtable.md + flow.yaml',
     (_check_structure, _gen_dsl)),
    ('几何求解', 'flow.yaml（语义 + 几何）', '同一份 yaml 落定几何',
     (_validate_geometry,)),
    ('视觉呈现', 'yaml + dictionary.yaml', 'html / drawio 两份产物的内容',
     (_prepare_views, _render_products)),
    ('成果审核与落盘', '渲染结果', '落盘的产物 + 审核回执',
     (_audit_contract, _audit_geometry, _write_layer_index, _report_receipt,
      _report_pending)),
)

# 渲染器注册表：**加一个渲染器 = 加一个文件 + 在这里加一行**。
# 放**编排层**而不放契约层——放契约层就得让契约层 import 阶段实现，
# 而分层门禁规定"契约层不许依赖上层"，会直接违规。
#
# **这里存的是「名字」，不是函数对象——别改回去**（这一条是被门禁逼出来的）：
# `dev/verify/gates.py` 用"把 `build.render_html` 这个**模块级名字**换成假渲染器、
# 再断言假渲染器真被调到"来证明"渲染器写出空壳产物时 build 会退 1"。
# 若注册表在导入时就把函数对象固化下来，替换就落空 ⇒ 那条用例变成**永远绿的假绿**，
# 而它的守卫断言（"monkeypatch 真的被 build 调到"）会先红。所以每次调用现查。
_RENDERER_SPECS = (
    {'kind': 'html', 'fn': 'render_html', 'ext': '.html', 'ids': 'read_html',
     'geom': 'geometry_from_html', 'label': 'flow.html', 'required': True},
    {'kind': 'drawio', 'fn': 'render_drawio', 'ext': '.drawio', 'ids': 'read_drawio',
     'geom': 'geometry_from_drawio', 'label': 'flow.drawio', 'required': False},
    {'kind': 'svg', 'fn': 'render_svg', 'ext': '.svg', 'ids': 'read_svg',
     'geom': 'geometry_from_svg', 'label': 'flow.svg', 'required': False},
)


def build_registry():
    """按**可用性**装注册表，返回 `(RENDERERS, 缺的可选件, 缺的必需件)`。

    "把其它模块暂时关掉也不影响出图"（W7a）就落在这里：可选渲染器的模块不在，
    注册表里就没有它 ⇒ 主干照出 html，只在交付清单里说明少了一份。两条纪律：

    · **必需件缺失 = 硬失败**（`main` 里报错退出）——静默少一个产物会让人以为图出全了，
      而这正是本项目最忌的**假绿**；
    · **可选件缺失要明说**，不静默 —— `MISSING_RENDERERS` 会打进交付清单。
    """
    reg, missing, absent = {}, [], []
    for spec in _RENDERER_SPECS:
        if globals().get(spec['fn']) is None:
            (absent if spec['required'] else missing).append(spec['kind'])
            continue
        reg[spec['kind']] = {k: v for k, v in spec.items()
                             if k not in ('kind', 'required')}
    return reg, tuple(missing), tuple(absent)


RENDERERS, MISSING_RENDERERS, ABSENT_REQUIRED = build_registry()


def _bind(name):
    """按名字现查 `globals()` 取函数——渲染器与两个**反解器**都走这里。

    现查而不是导入时固化，理由见上面 RENDERERS 的注释（否则 `gates` 的 monkeypatch 落空）。

    为什么每类渲染器要声明**两个**反解器：产物要用两种视角被复核——
      `ids`  : 反解出「有哪些节点/哪些边」，供**契约反查**（`manifest.check`）；
      `geom` : 反解出「真实坐标与折线」，供**几何门禁**（`artifact_geometry`）。
    **反解器是插件契约的另一半**：只注册渲染器、不注册反解器，那个产物就没人复核。
    """
    return globals()[name]


def _renderer(kind):
    """按注册表取渲染器实例。**调用时现查 `globals()`**（理由见上面 RENDERERS 的注释）。"""
    return _bind(RENDERERS[kind]['fn'])


def _product_paths(out_dir, stem):
    """产物路径由注册表派生（W5）：`<流程名>-flow<ext>`。

    这样"加一个渲染器"不必再去 `main` 里补一行路径拼装——路径是注册表的函数。
    """
    return {kind: out_dir / f'{stem}-flow{meta["ext"]}'
            for kind, meta in RENDERERS.items()}


def _render_ctx(kind, yaml_path, ft, no_pages):
    """每类渲染器自己的私有选项（经 `ctx` 传，见 ARCHITECTURE.md 第九节）。

    渲染循环是通用的，但**上下文天然是每类不同的**（html 要面包屑父表、drawio 要分页），
    所以这里按 kind 分派——新增一类渲染器，要么不用 ctx（什么都不用加），
    要么在这里加一条分支。**这是"注册一行"之外唯一可能需要动的地方**，刻意集中在一处。
    """
    if kind == 'html':
        return {'parent': _find_parent(ft)}
    if kind == 'drawio':
        return {'pages': None if no_pages else (discover_pages(str(yaml_path)) or None)}
    return {}


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _parse_args(argv)

    # 降级纪律（W7a，见 build_registry）：**必需件缺失硬失败**，可选件缺失明说。
    if ABSENT_REQUIRED:
        print(f'✗ 缺少必需渲染器：{"、".join(ABSENT_REQUIRED)}'
              f'（主干靠它出图，不能少；只有可选件缺失才降级）')
        return 1
    if MISSING_RENDERERS:
        print(f'· 跳过不可用的可选渲染器：{"、".join(MISSING_RENDERERS)}'
              f'（对应模块不在）—— 主干照出图，交付清单里会少这几份')

    ft = Path(a.flowtable)
    if not ft.exists():
        print(f'✗ 找不到流程表: {ft}')
        return 1
    out_dir = ft.parent
    # 产物名**带流程名**（见 D-51）：`<流程名>-flow.{yaml,html,drawio}`。
    # 流程名取目录名（表名是约定名 `flowtable` 时）或表名——`flowtable.md` 不承载语义，
    # 流程的身份在目录上。产物一律叫 `flow.html` 的话，发出去是一堆没有名字的文件。
    stem = artifact_stem(ft)
    yaml_path = out_dir / f'{stem}-flow.yaml'
    if ft.name != 'flowtable.md':
        print(f'· 流程表文件名是 {ft.name}（约定名是 flowtable.md）：产物名按表名取 '
              f'→ {stem}-flow.yaml / {stem}-flow.html / {stem}-flow.drawio')

    if _check_structure(ft, a.quality) != 0:
        return 1
    # 契约的上一版必须在 `_gen_dsl` **之前**读下来：它由 table_to_dsl 连同 yaml 一起刷新，
    # 而失败分支要把它跟产物一起还原（见 _rollback_manifest）。
    mf_path = manifest_path_for(yaml_path)
    prev_mf = mf_path.read_bytes() if mf_path.exists() else None
    if _gen_dsl(ft, yaml_path, a.quality, a.no_layout) != 0:
        _rollback_manifest(prev_mf, yaml_path)
        return 1
    if _validate_geometry(yaml_path, a.quality) != 0:
        _rollback_manifest(prev_mf, yaml_path)
        return 1

    print('--- 渲染交付物 ---')
    # 产物路径由**注册表派生**（W5）：加一类渲染器不必再在这里补一行拼装。
    products = _product_paths(out_dir, stem)
    plan = _prepare_views(yaml_path)
    prev = _render_products(yaml_path, products, ft, a.no_pages)
    if prev is None:
        _rollback_manifest(prev_mf, yaml_path)
        return 1
    if _audit_contract(yaml_path, products, prev) != 0:
        _rollback_manifest(prev_mf, yaml_path)
        return 1
    if _audit_geometry(products, prev, expect_lanes=_lane_source(yaml_path)) != 0:
        _rollback_manifest(prev_mf, yaml_path)
        return 1
    _write_layer_index(ft, out_dir, stem)
    _report_receipt(products, ft, prev, plan)
    _report_pending(yaml_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
