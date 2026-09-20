# -*- coding: utf-8 -*-
"""layer_index.py — 层级索引：从 ⊞ 声明派生主流程的分层注册表（D-56）。

层级关系的**权威**是各流程表节点描述里的 ⊞ 声明；本模块只做派生与校验，不做裁定：

  - 层级号 = 距主流程的最深 ⊞ 深度（同一张表可从多条路径到达 → 取最深，并记入歧义）
  - 构建顺序 = 层级降序（自底向上），替代人工背诵 SKILL 的构建约束
  - 孤儿表 = 流程目录树里存在、却不在 ⊞ 可达集内的 .md → 警告（多半是改名/移动后断链）
  - 回指祖先（子表 ⊞ 回主表/上级）是**合法**的"返回入口"，不是环——与 render_html
    的"回主视图"（D-52）同一语义，不报错

`<流程名>-index.md` 是**派生产物**：每次 build 自动刷新，手改会被覆盖——
层级关系手写必漂移（grove-generator 的悬空引用即前车之鉴），这就是索引不手写的理由。
退出码：0 = 写出索引；1 = 主流程表找不到（`<名称>/flowtable.md`）。
"""
import argparse
import os
import re
import sys
from pathlib import Path

from semantics import subflow_target
from artifact import artifact_stem, NON_TABLE_MD
from flowtable import parse_table
from flowtable import C_DESC, split_row_cells


def _rel(p, root):
    # 大小写归一（Windows 文件系统不区分大小写）：⊞ 里写 Parts/X.md、磁盘上是 parts/x.md
    # 时，不归一会在索引里当成两张表、后登记的那张还被判 missing。normcase 在 posix 上是
    # 恒等（那里大小写确实不同文件），所以这层归一不会把 Linux 上的两张真表并成一张。
    try:
        rp = p.resolve().relative_to(root).as_posix()
    except ValueError:
        rp = p.resolve().as_posix()
    return os.path.normcase(rp).replace(os.sep, '/')


def _visit_subflow(ft_path, depth, parent_rp, via, chain, root, tables):
    """深度优先走一遍 ⊞ 派生树，把每张表的层级信息登记进 tables（就地修改）。"""
    rp = _rel(ft_path, root)
    if rp in chain:
        return                  # 回指链上已有的表 = 返回入口（D-52 同语义），合法，不再向下展开
    info = tables.setdefault(rp, {'depths': set(), 'parents': {}, 'missing': False,
                                  'title': '', 'nodes': 0, 'id': '', 'level': ''})
    first_at_depth = depth not in info['depths']
    info['depths'].add(depth)
    if parent_rp is not None:
        info['parents'].setdefault(parent_rp, set()).add(via)
    if not first_at_depth:
        return                      # 同深度的子树已走过（菱形引用），再走一遍结果相同
    if not ft_path.exists():
        info['missing'] = True
        return                      # 缺失的表没有可下钻的内容（build 会另行报 absent）
    title, meta, rows = parse_table(ft_path.read_text(encoding='utf-8-sig'))
    info['title'], info['nodes'] = title, len(rows)
    # 身份区（D-59）：id 缺省取 artifact_stem（约定名 flowtable → 目录名）；level 记声明值
    info['id'] = str(meta.get('id') or '').strip() or artifact_stem(ft_path)
    info['level'] = str(meta.get('level') or '').strip()
    for cells in rows:
        ref = subflow_target(split_row_cells(cells)[C_DESC])
        if not ref:
            continue
        _visit_subflow((ft_path.parent / ref).resolve(), depth + 1, rp,
                       cells[2].strip(), chain + [rp], root, tables)


def _find_orphans(root, tables, main_ft):
    """目录树里可达集之外的 .md → 孤儿表警告（生成物与说明文档不算表）。"""
    notes = []
    generated = set(NON_TABLE_MD) | {f'{artifact_stem(main_ft)}-index.md'}
    for p in sorted(root.rglob('*.md')):
        rp = _rel(p, root)
        name = p.name
        if rp in tables or name in generated or name.startswith('README') or name.endswith('.sync.md'):
            continue
        notes.append(f'孤儿表: {rp}——没有任何父表通过 ⊞ 引用它'
                     f'（多半是改名/移动后断链，或它本该删掉）')
    return notes


def _check_identity(tables):
    """身份一致性（D-59）：id 全树唯一；level 声明与 ⊞ 推导深度一致 → 警告列表。"""
    notes = []
    ids = {}
    for rp, info in tables.items():
        if info.get('id'):
            ids.setdefault(info['id'], []).append(rp)
    for i, rps in sorted(ids.items()):
        if len(rps) > 1:
            notes.append(f'id 重复: 「{i}」被 {len(rps)} 张表使用（{"、".join(rps[:3])}）——id 应在流程树内唯一')
    for rp, info in tables.items():
        lv = info.get('level')
        m = re.match(r'L(\d+)$', lv or '')
        if m and int(m.group(1)) != max(info['depths']):
            notes.append(f'层级声明不一致: {rp} 声明 {lv}，按 ⊞ 推导为 L{max(info["depths"])}')
    return notes


def _build_order(tables):
    """层级降序（自底向上）排构建顺序，并收集"多条路径到达"的歧义警告 → (order, notes)。"""
    notes = []
    order = sorted(tables, key=lambda r: (-max(tables[r]['depths']), r))
    for rp, info in tables.items():
        if len(info['depths']) > 1:
            ds = sorted(info['depths'])
            notes.append(f'层级歧义: {rp} 可从 L{ds[0]} 与 L{ds[-1]} 两条路径到达，'
                         f'按最深的 L{ds[-1]} 定级')
    return order, notes


def build_layer_index(main_ft):
    """主流程表路径 → {'tables': {相对路径: 层级信息}, 'order': [构建顺序], 'notes': [警告]}"""
    main_ft = Path(main_ft).resolve()
    root = main_ft.parent
    tables = {}
    _visit_subflow(main_ft, 0, None, None, [], root, tables)
    notes = _find_orphans(root, tables, main_ft)
    notes += _check_identity(tables)
    order, ambiguity = _build_order(tables)
    notes += ambiguity
    return {'tables': tables, 'order': order, 'notes': notes,
            'main': _rel(main_ft, root), 'main_title': tables[_rel(main_ft, root)]['title']}


def format_index_md(index):
    """层级索引 → markdown（<流程名>-index.md 的正文）。"""
    t = index['tables']
    lines = [f"# {index['main_title'] or '流程'} · 层级索引", '',
             '> **派生产物，勿手改**：由 build 从各表节点描述的 ⊞ 声明自动生成（D-56）。',
             '> 层级 = 距主流程的最深 ⊞ 深度；构建顺序自底向上，先建最深的子表。', '',
             '## 层级树', '']
    def tree(rp, depth):
        info = t[rp]
        indent = '  ' * depth
        name = f'L{depth}' + (' 主流程' if depth == 0 else ' 子流程')
        mark = ' **（缺失）**' if info['missing'] else ''
        title = f'——《{info["title"]}》' if info['title'] else ''
        idn = f'（id: {info["id"]}）' if info.get('id') else ''
        lines.append(f'{indent}- **{name}** `{rp}`{title}{idn}{mark}'
                     f'（{info["nodes"]} 节点）')
        kids = sorted((c for c in t if depth + 1 in t[c]['depths'] and rp in t[c]['parents']),
                      key=lambda c: c)
        for c in kids:
            tree(c, depth + 1)

    tree(index['main'], 0)
    lines += ['', '## 构建顺序（自底向上）', '']
    for i, rp in enumerate(index['order'], 1):
        lines.append(f'{i}. `{rp}`（L{max(t[rp]["depths"])}）')
    if index['notes']:
        lines += ['', '## 警告', '']
        lines += [f'- {n}' for n in index['notes']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='层级索引：从 ⊞ 声明派生分层注册表（只读派生，不渲染）')
    ap.add_argument('flowtable', help='主流程表路径（如 output/<名称>/flowtable.md）')
    ap.add_argument('--write', action='store_true', help='把索引写为 <流程名>-index.md（build 自动做，无需手动）')
    a = ap.parse_args(argv)
    ft = Path(a.flowtable)
    if not ft.exists():
        print(f'✗ 找不到主流程表: {ft}')
        return 1
    idx = build_layer_index(ft)
    text = format_index_md(idx)
    print(text, end='')
    for n in idx['notes']:
        print('⚠', n)
    if a.write:
        out = ft.parent / f'{artifact_stem(ft)}-index.md'
        out.write_text(text, encoding='utf-8', newline='\n')
        print(f'✓ 已派生索引: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
