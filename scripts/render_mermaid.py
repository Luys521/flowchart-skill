# -*- coding: utf-8 -*-
"""render_mermaid.py — DSL → 平台无关的 Mermaid `flowchart TD` 文本（.mmd）。

定位：与 html/drawio/svg 平级、从同一份 <流程名>-flow.yaml 渲染，但它是**无坐标、由下游
（飞书画板 / 任意 Mermaid 工具）自动布局**的可编辑文本，因此不做几何自检（注册表无 geom）。
主路径仍是"按我方几何 POST 画板"；Mermaid 只作通用可编辑 / 快速后备格式。
只读 yaml、只写 mmd（事实源不挪位，口径同 render_svg）。
退出码：0 = 写出 .mmd；1 = 输入读不了 / 渲染失败。
"""
import re
from pathlib import Path

from engine import load


def _mid(x):
    """DSL id → Mermaid 节点 id：清洗后统一加 n 前缀（保证字母开头、唯一、可逆）。"""
    return 'n' + re.sub(r'[^A-Za-z0-9_]', '_', str(x))


def _unmid(x):
    return x[1:] if x.startswith('n') else x


def _txt(t):
    """文本放进双引号里；转义井号与双引号（Mermaid 实体写法）。"""
    return str(t).replace('#', '#35;').replace('"', '#quot;')


def _node(n):
    mid, tx, t = _mid(n['id']), _txt(n.get('name', '')), n.get('type')
    if t in ('start', 'end'):
        return f'  {mid}(["{tx}"])'
    if t == 'decision':
        return '  ' + mid + '{"' + tx + '"}'
    return f'  {mid}["{tx}"]'


def _edge(e):
    a, b = _mid(e['from']), _mid(e['to'])
    lab = e.get('label')
    if lab:
        return f'  {a} -->|"{_txt(lab)}"| {b}'
    return f'  {a} --> {b}'


def render(dsl_path, out_path, ctx=None):
    """DSL → .mmd。成功返回 0（统一契约；ctx 本渲染器不用）。"""
    L = load(str(dsl_path))
    lines = ['flowchart TD']
    lines += [_node(n) for n in L.dsl['nodes']]
    lines += [_edge(e) for e in L.edges]
    Path(out_path).write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print(f'生成: {out_path}  节点: {len(L.dsl["nodes"])}  边: {len(L.edges)}')
    return 0


def read_mermaid(path):
    """从自产 .mmd 反解 (节点 id 列表, 边列表)；id 去掉 n 前缀还原为 DSL id。

    只解析本模块的规范输出（节点声明 + --> 边），不承诺解析任意第三方 Mermaid。
    """
    t = Path(path).read_text(encoding='utf-8')
    ids, seen = [], set()

    def add(mid):
        r = _unmid(mid)
        if r not in seen:
            seen.add(r)
            ids.append(r)

    for m in re.finditer(r'^\s*(n\w+)\s*(?:\(\[|\[|\{)', t, re.M):
        add(m.group(1))
    edges = []
    for m in re.finditer(r'(n\w+)\s*-->(?:\|[^|]*\|)?\s*(n\w+)', t):
        a, b = _unmid(m.group(1)), _unmid(m.group(2))
        add(m.group(1))
        add(m.group(2))
        edges.append((a, b))
    return ids, edges


def main():
    import argparse
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='DSL → Mermaid flowchart 文本')
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    a = ap.parse_args()
    if not Path(a.input).exists():
        print(f'✗ 找不到输入文件: {a.input}')
        return 1
    return render(a.input, a.output or str(Path(a.input).with_suffix('.mmd')))


if __name__ == '__main__':
    raise SystemExit(main())
