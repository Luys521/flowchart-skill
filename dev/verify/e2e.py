# -*- coding: utf-8 -*-
"""e2e.py — 面④：端到端往返。一条完整的活能不能走完，且每个交接点都对。

链路：init → 填表 → 结构校验 → build（渲染+门禁）→ 截图 → 注入语义改动
      → sync 预览（差异必须精确）→ --apply（覆盖+重渲染）→ 再 build（幂等）
产物与流程表都落在传入的临时目录里，不碰 skill 本体。
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import Case, md5, prod, run  # noqa: E402

FLOWTABLE = '''---
id: e2e
level: L0
description: 端到端验证流程
---

# 端到端验证流程

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 受理 | 01 | 收到申请 | 开始 | 申请材料 | — | — | 甲方 | 受理员 | — | →02 | 接收并登记申请材料★ |
| 受理 | 02 | 资料是否齐全？ | 判断 | 申请材料 | 齐全清单 | 齐全 / 不齐全 | 甲方 | 受理员 | — | 齐全→03 ｜ 不齐全→回 01 补件 | 齐全才受理，否则退回补件★ |
| 核验 | 03 | 现场核验 | 任务 | 受理单 | 核验规程 | 核验记录 | 乙方 | 工程师 | 3个工作日 | →04 | 现场核查并出具记录 |
| 核验 | 04 | 核验是否通过？ | 判断 | 核验记录 | 通过标准 | 通过 / 不通过 | 乙方 | 工程师 | — | 通过→05 ｜ 不通过→回 03 复验 | 通过则归档，否则复验★ |
| 归档 | 05 | 归档 | 结束 | 核验记录 | — | 档案 | 双方 | 双方共责 | — | — | 资料归档，流程结束 |

## 表后核对要点

- 回写闭环（WRITEBACK-TAIL 哨兵）：sync --apply 只改表格行，本节必须原样保留。
'''


def run_face(tmp):
    c = Case('面④ 端到端往返')
    e2e = tmp / 'e2e'
    shutil.rmtree(e2e, ignore_errors=True)

    c.section('init 建目录')
    rc, out = run('init.py', 'e2e', '-d', tmp)
    c.check(rc == 0, 'init 退出码 0', (out.strip().splitlines() or [''])[0])
    c.check((e2e / 'flowtable.md').exists() and (e2e / 'checklist.md').exists(), '模板已就位')
    rc, out = run('init.py', 'e2e', '-d', tmp)
    c.check(rc == 1, '重复 init 被拦（不覆盖已有文件）')

    c.section('填表 → 结构校验 → 渲染')
    ft = e2e / 'flowtable.md'
    ft.write_text(FLOWTABLE, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', ft)
    hit = next((l for l in out.splitlines() if 'H1起止' in l), '')
    c.check(rc == 0, '结构校验通过', hit[:52] if rc == 0 else out[-120:])
    rc, out = run('build.py', ft)
    # 六件套都按 `<流程名>-flow.*` 命名（D-51）：目录名 e2e → e2e-flow.html
    # `svg` 是 W7b 起新增的可编辑中间态产物（见 ARCHITECTURE.md 9.9）。
    c.check(rc == 0 and all(prod(e2e, f).exists() for f in
                            ('yaml', 'manifest.json', 'html', 'drawio', 'svg')), 'build 产出六件套')
    c.check('全部通过' in out and '网格对齐' in out, '八项质量门禁通过')
    # 层级索引（D-56）：单表流程也要派生出索引（1 张表，L0），派生物随 build 刷新
    idx = e2e / 'e2e-index.md'
    c.check(rc == 0 and idx.exists() and '层级树' in idx.read_text(encoding='utf-8'),
            '层级索引已派生（含层级树与构建顺序）')
    rc, out = run('shot.py', prod(e2e, 'html'))
    c.check(rc == 0 and prod(e2e, 'html').with_suffix('.shot.png').exists(), '截图自检可用')

    c.section('注入一处真实改动 → sync 预览')
    before = ft.read_bytes()
    d = prod(e2e, 'drawio')
    s = d.read_text(encoding='utf-8').replace('&gt;归档&lt;', '&gt;资料归档&lt;').replace('value="不齐全"', 'value="否"')
    d.write_text(s, encoding='utf-8')
    rc, out = run('sync.py', d, ft)
    lines = [l for l in out.splitlines() if l.startswith(('    -|', '    +|'))]
    pairs = sum(1 for l in lines if l.startswith('    -|'))
    c.check(rc == 0, 'sync 退出码 0')
    # 只数行数是脆弱 oracle：格式微调会让这条红，而"恰好 2 处**别的**差异"会让它假绿。
    # 所以再钉一次内容——+| 必须带着新名字、-| 必须带着旧标签。
    _minus = '\n'.join(l for l in lines if l.startswith('    -|'))
    _plus = '\n'.join(l for l in lines if l.startswith('    +|'))
    c.check(pairs == 2, '差异精确到 2 处改动（改名 + 改标签）', f'{pairs} 对')
    c.check('资料归档' in _plus and '不齐全' in _minus,
            '这两处的**内容**也对得上（+| 带新名、-| 带旧标签），不是恰好 2 处别的差异',
            f'+: {_plus[:60]}')
    c.check((e2e / 'flowtable.sync.md').exists()
            and prod(e2e, 'yaml').with_suffix('.sync.yaml').exists(), '预览产物已生成')
    c.check(ft.read_bytes() == before, '预览阶段不覆盖原表')

    c.section('--apply 覆盖并重渲染')
    rc, out = run('sync.py', d, ft, '--apply')
    after = ft.read_text(encoding='utf-8')
    c.check(rc == 0 and '资料归档' in after and '否→回 01 补件' in after, '原表已覆盖（含保留的注解）')
    c.check('## 表后核对要点' in after and 'WRITEBACK-TAIL' in after,
            '--apply 后表格之后的内容仍保留（表后小节未被丢弃）')
    c.check(out.count('生成:') >= 2, 'apply 后自动重渲染')

    c.section('幂等复查')
    arts = [prod(e2e, f) for f in ('yaml', 'manifest.json', 'html', 'drawio')]
    before_h = [md5(p) for p in arts]
    rc, out = run('build.py', ft)
    # rc 必须并入：build 崩溃时产物不会更新，md5 恒等会让"幂等"假通过
    c.check(rc == 0 and before_h == [md5(p) for p in arts], '再 build 产物不变',
            '' if rc == 0 else f'build rc={rc}：{out.strip()[-120:]}')
    return c


if __name__ == '__main__':
    from _lib import SKILL
    sys.exit(0 if run_face(SKILL / '.verify_tmp').summary() else 1)
