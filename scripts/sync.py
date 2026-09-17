# -*- coding: utf-8 -*-
"""sync.py — 一键同步：drawio → 差异对比 → 回写《流程表》→ 生成 DSL → 质量门禁。

把同步闭环的读回 + 回写 + 转码 + 校验合成一条命令，并把外部图的二维布局作为布局提示带入 DSL，
避免并排分支被拉成单列。默认只预览（产 flowtable.sync.md + <流程名>-flow.sync.yaml），`--apply` 才覆盖原表。

退出码：0 全通过；1 结构校验或质量门禁未过（流程表已写出，修正后重跑）。
"""
import argparse
import sys
import tempfile
from pathlib import Path

import yaml as _yaml

from xml_reader import read, brief, diff
from writeback import write, compare_bytes, branch_conflicts, format_conflicts
from artifact import artifact_stem
from flowtable_layout import auto_layout
from table_to_dsl import main as t2d_main
from validate import main as validate_main


def build_hint(data: dict) -> dict:
    """把读回结果的 row/col/col_x 打包成 table_to_dsl 的布局提示"""
    nodes = data['nodes']
    row = {n['id']: n['row'] for n in nodes}
    col = {n['id']: n['col'] for n in nodes}
    edges_src = []
    for e in data['edges']:
        # 只比行号会漏掉"同一行里往左走"的回边：并排分支之间那条返工线就是这样画的，
        # 行号相等却被当成正向边，几何便不会给它留左侧回程通道。行号相同再看列号。
        rf, rt = row.get(e['from'], 0), row.get(e['to'], 0)
        is_loop = rt < rf or (rt == rf and col.get(e['to'], 0) < col.get(e['from'], 0))
        edges_src.append({'from': e['from'], 'to': e['to'],
                          'label': e.get('label', ''), 'is_loop': is_loop})
    dsl_edges = auto_layout(nodes, edges_src)
    dashed = {(e['from'], e['to']) for e in data['edges'] if e.get('dashed')}
    for d in dsl_edges:
        if (d['from'], d['to']) in dashed:
            d['polarity'] = 'negative'
    # 通道（gutter/channel/gapx）一律不落盘：它是 router 依节点与端口现场规划的派生量，
    # 落盘只会把过期几何钉死（换布局后水平段会横穿节点、箭头被盖住）。
    return {'layout': {'col_x': data['grid']['col_x']},
            'nodes': [{'id': n['id'], 'row': n['row'], 'col': n['col']} for n in nodes],
            'edges': dsl_edges}


def _parse_args(argv):
    """解析 sync 的命令行参数。"""
    ap = argparse.ArgumentParser(description='drawio → 流程表 → DSL → 质量门禁，一键同步')
    ap.add_argument('drawio_path')
    ap.add_argument('orig_ft', help='原 flowtable.md')
    ap.add_argument('-o', '--out', help='输出的更新流程表路径')
    ap.add_argument('--yaml', dest='yaml_out', help='输出的 flow.yaml 路径')
    ap.add_argument('--no-diff', action='store_true', help='跳过差异对比')
    ap.add_argument('--brief', action='store_true', help='额外打印拓扑摘要')
    ap.add_argument('--apply', action='store_true',
                    help='直接覆盖 flowtable.md/flow.yaml 并重渲染两份产物')
    ap.add_argument('--force', action='store_true',
                    help='分支走向与流程表冲突时仍强行 --apply（默认拦截，需人工裁决哪边对）')
    return ap.parse_args(argv)


def _resolve_paths(a):
    """校验 drawio 与原流程表路径，返回 (drawio, 原表, 输出表)；缺文件返回 None。"""
    src = Path(a.drawio_path)
    if not src.exists():
        print(f'✗ 找不到 drawio 文件: {src}')
        return None
    orig = Path(a.orig_ft)
    if not orig.exists():
        print(f'✗ 找不到原流程表: {orig}')
        return None
    out_ft = Path(a.out) if a.out else orig.parent / (orig.stem + '.sync.md')
    return src, orig, out_ft


def _read_back(src, orig, brief_flag, no_diff):
    """读回 drawio（BOM 兼容）并按需打印摘要与差异；解析失败返回 None。"""
    # utf-8-sig：带 BOM 的 drawio 按裸 utf-8 读，首字符 \ufeff 会让 ET.fromstring 直接抛解析错
    try:
        data = read(src.read_text(encoding='utf-8-sig'))
    except ValueError as e:
        print(f'✗ {e}')
        return None
    print(f'读回: {src.name}  来源格式: {data["source"]}  '
          f'节点: {len(data["nodes"])}  边: {len(data["edges"])}')
    if brief_flag:
        print(brief(data))
    if not no_diff:
        print('--- 与流程表的差异 ---')
        print(diff(data, orig))
    return data


def _write_back(src, orig, out_ft):
    """回写《流程表》到预览文件并做逐字节复核；回写失败返回 1。"""
    print('--- 回写流程表 ---')
    try:
        ok = write(str(src), str(orig), str(out_ft))
    except ValueError as e:
        print(f'✗ {e}')
        return 1
    if not ok:
        # 回写自检（H1–H8）没过：这份预览**不能**当成品——`--apply` 是把它原样复制过去的，
        # 放行等于绕过结构校验往《流程表》里落一份不合格的表（D-84）。
        print('✗ 回写结果没通过结构校验（见上面那条 ✗）——本次不覆盖《流程表》')
        print(f'   预览已写出供核对：{out_ft}')
        return 1
    # 上一句"无差异"是集合比较，看不见分支顺序、尾注、「回」、换行符——补文件级真相。
    same, lines = compare_bytes(orig, out_ft)
    if same:
        print('✓ 回写结果与原文逐字节一致（本次未改动流程表）')
    else:
        print(f'ℹ 流程表有 {len(lines)} 行差异：')
        for line in lines[:24]:
            print('   ', line)
        if len(lines) > 24:
            print(f'    …（共 {len(lines)} 行，其余见 {out_ft.name}）')
    return 0


def _gen_dsl(data, orig, out_ft, yaml_opt):
    """写布局提示临时 yaml 并转出 DSL（泳道布局另报文案）；返回 (DSL 路径, 退出码)。

    预览用的 yaml 也带流程名（D-51）：它得与 `build.py` 会读的那一份**同名不同后缀**，
    否则"预览看着对、--apply 之后几何没了"——apply 是把这份复制过去的。
    """
    hint = build_hint(data)
    yaml_out = Path(yaml_opt) if yaml_opt else out_ft.parent / f'{artifact_stem(orig)}-flow.sync.yaml'
    with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        _yaml.safe_dump(hint, f, allow_unicode=True, sort_keys=False)
        hint_path = f.name
    # 泳道布局的行列按「阶段 × 主体」语义重排，table_to_dsl 会忽略 --layout 提示——文案分开说，别让人找错地方
    from flowtable import parse_table
    _t, wb_meta, _r = parse_table(out_ft.read_text(encoding='utf-8-sig'))
    if '泳道' in (wb_meta.get('输出布局') or ''):
        print('--- 生成 DSL（泳道布局按阶段×主体重排，不借用原图几何）---')
    else:
        print('--- 生成 DSL（带入原图二维布局）---')
    rc = t2d_main(['--write', '--layout', hint_path, str(out_ft), '-o', str(yaml_out)])
    Path(hint_path).unlink(missing_ok=True)
    if rc != 0:
        print('✗ DSL 生成未通过结构校验，请修正流程表后重跑')
        return yaml_out, 1
    return yaml_out, 0


def _quality_gate(yaml_out):
    """跑质量门禁；未过则报错并返回 1。"""
    print('--- 质量门禁 ---')
    rc = validate_main(str(yaml_out))
    if rc != 0:
        print('✗ 质量门禁未过：只可调 flow.yaml 的几何字段后重跑——流程布局 row/col/gutter/gapx/channel，'
              '泳道布局 row/col/sdye/dye；或回写流程表后重跑本命令')
        return 1
    return 0


def _source_guard(orig):
    """《流程表》自上次渲染后是否被直改过 → `(state, 说明)`。

    有它才能回答"为什么不能拿图回灌"：`writeback.build_rows` 是**按图里的节点集合重建表格行**的，
    表里手工加的节点会被删掉、手工改过的名字会被图里的旧值覆盖回去。表动过时，回灌是破坏性的。
    没有基线（首版契约没记指纹）时判不出，这时不拦——旧行为保持不变。
    """
    from manifest import manifest_path_for, source_stale
    yaml_path = orig.parent / f'{artifact_stem(orig)}-flow.yaml'
    return source_stale(orig, manifest_path_for(yaml_path))


def _apply(orig, out_ft, yaml_out, data, force, stale=None):
    """--apply：两道覆盖门禁通过后覆盖原表/DSL 并重渲染，返回退出码。

    门禁一（本函数开头）：**《流程表》自上次渲染后被直改过**——表与图已经不是同一版，
    回灌会把手工改动抹掉。这是数据损失，默认拦住。
    门禁二（D-45）：分支走向冲突——「下个节点」列必然由图重建，所以"改了表还没重跑 build"
    的正确改动会在这里被静默吃掉（D-01 描述的那类错）。覆盖前必须让人先裁决：表对还是图对。
    """
    import shutil
    from flowtable import parse_table
    from build import main as build_main
    if stale and stale[0] == 'changed' and not force:
        print('--- 覆盖被拦截 ---')
        print(f'✗ 《流程表》自上次渲染后改过（{stale[1]}），表与图已不是同一版。')
        print('   回灌是按图重建表格行的：表里手工加的节点会被删掉，手工改过的名字会被覆盖回去。')
        print('   先对齐再走：')
        print('     · 表是对的 → 重跑 build 让图跟上（build.py "<流程表>"），再走 --apply')
        print('     · 一定要以图为准 → 加 --force（表里的手工改动会丢）')
        return 1
    conflicts = branch_conflicts(data, parse_table(orig.read_text(encoding='utf-8-sig'))[2])
    if conflicts and not force:
        print('--- 覆盖被拦截 ---')
        print(format_conflicts(conflicts))
        print(f'✗ 上述 {len(conflicts)} 处分支走向「流程表与图不一致」，--apply 会把流程表改成图里的旧走向。')
        print('   先判断哪边对：')
        print(f'     · 图是对的 → 用 --force 把图里的走向落进表：{Path(__file__).name} … --apply --force')
        print('     · 表是对的 → 重跑 build 让图跟上（build.py "<流程表>"），再走 --apply')
        return 1
    if stale and stale[0] == 'changed':
        print(f'⚠ --force：表自上次渲染后改过（{stale[1]}），表里的手工改动可能已丢')
    # **覆盖前留底**（D-87）：`--apply` 是"先覆盖《流程表》再重渲染"，而重渲染会失败（几何自检、
    # 产物审核任意一环）。失败时表已经换成图里那版，用户的手工改动再也回不来——build 那边
    # "不留半成品"的纪律在这里一直是缺的。底本只留内存，不落 `.bak`：用户不需要多一个"要不要删"的
    # 文件，这里只需要一次失败回滚。
    yaml_target = orig.parent / f'{artifact_stem(orig)}-flow.yaml'
    prev = {p: p.read_bytes() for p in (orig, yaml_target) if p.exists()}
    shutil.copyfile(out_ft, orig)
    shutil.copyfile(yaml_out, yaml_target)
    if conflicts:
        print('⚠ --force：已按图覆盖，下列冲突项以图为准：')
        print(format_conflicts(conflicts))
    print('--- 已覆盖原流程表并重渲染 ---')
    rc = build_main([str(orig)])
    if rc != 0:
        for p in (orig, yaml_target):
            if p in prev:
                p.write_bytes(prev[p])
            elif p.exists():
                p.unlink()
        print('✗ 覆盖后重渲染失败 → 《流程表》与 yaml 已还原成本次覆盖前的样子（手工改动没丢）'
              '；先修掉上面那条错误，再走一次 --apply')
    return rc


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _parse_args(argv)

    paths = _resolve_paths(a)
    if paths is None:
        return 1
    src, orig, out_ft = paths

    stale = _source_guard(orig)
    if stale[0] == 'changed':
        print(f'⚠ 《流程表》自上次渲染后改过：{stale[1]}')
        print('  本次只做预览。--apply 会被拦下——回灌是按图重建表格行的，'
              '会删掉表里手工加的节点、覆盖手工改过的名字。')
        print('  要走通：先把表与图对齐（重跑 build 让图跟上，或在表里改），再回来。')

    data = _read_back(src, orig, a.brief, a.no_diff)
    if data is None:
        return 1

    if _write_back(src, orig, out_ft) != 0:
        return 1

    yaml_out, rc = _gen_dsl(data, orig, out_ft, a.yaml_out)
    if rc != 0:
        return 1
    if _quality_gate(yaml_out) != 0:
        return 1
    print(f'✓ 同步完成：{out_ft} → {yaml_out}')

    if a.apply:
        return _apply(orig, out_ft, yaml_out, data, a.force, stale)

    print(f'  复核差异后覆盖：python flowchart-skill/scripts/sync.py "{src}" "{orig}" --apply')
    print(f'  或先预览渲染：python flowchart-skill/scripts/render_html.py "{yaml_out}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
