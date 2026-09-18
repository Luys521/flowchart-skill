# -*- coding: utf-8 -*-
"""pipeline-fixtures/suite.py — 材料链两台仪器的合成夹具与路径测试（**门⑪ 每轮验收都跑**）。

覆盖两件东西：
- `scripts/drift.py`（PIPELINE-SPEC §5）：判据 D1—D5 + `check` 的**账目对账**（说谎 / 过期 / 无理由都要抓住）；
- `scripts/query.py`（§5.3）：**点名取子集**——材料 / 范围 / 关键词 / 分批 + 游标，只查不抽。

为什么要有它：这两台仪器的判据都有"**读得对不对**"与"**边界守不守得住**"两半，后者用真实材料造不出来
（要故意标错、要故意越界），只能合成。实测抓到过三件真问题，全在夹具里现形：
`check` 原先**只查了"已修是否真修"、没查"现在的命中是否漏在账外"**；伴生表**一行少一列被静默当成"没给"**
（D2 静默不跑而表头还写"跳过了 D2"）；`--range rows=` 只顾着裁显示、差点把命中筛成 0。

夹具（`--out` 下现生成，不写进仓库）：
    7 份材料（含一份 `status=unreadable`、一份 30 条元素全没引用的合订本）
    × 一张 5 节点的表 × 假设账（有一条 `状态=已推翻`）× 清点（两条「含流程 = 是」却零引用）

期望读数（`--out` 下的 `drift.md`）：
    漂移 3 条：D1 节点 02（依据带 `degraded`）· D2 节点 03（`M05` 已推翻仍在用）· D3 节点 03（`M02` 读不动）
    缺口 3 条：D4 `M04`（零引用）· D4 `M06`（零引用）· D5 `M06`（30 条元素只引 0 条）
    反例：节点 04 引 `M07#p001`（vlm）但描述以 `⚠` 开头 → **不报 D1**；
          `M07` 引 3/25 = 12% ≥ 10% → **不报 D5**

用法：`python dev/tools/pipeline-fixtures/suite.py`（退 0 = 全部符合预期）
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[3]        # dev/tools/pipeline-fixtures/ → 仓库根
LEDGER = REPO / 'scripts' / 'ledger.py'
DRIFT = REPO / 'scripts' / 'drift.py'
QUERY = REPO / 'scripts' / 'query.py'
PROBE_CMD = REPO / 'scripts' / 'probe.py'
RECON_CMD = REPO / 'scripts' / 'recon.py'          # 名字带 _CMD：本文件的 `RECON` 是**夹具表格文本**
OOXML_CMD = REPO / 'scripts' / 'parse_ooxml.py'
PARSE_CMD = REPO / 'scripts' / 'parse.py'

# 合成 pptx 的标题（第 2 张含「审批」——后面的取子集断言就找它）
DECK_TITLES = ('第 1 章 项目概况', '第 2 章 审批与分工', '第 3 章 结算与付款')

FLOWTABLE = """---
id: driftfix
level: L0
description: drift.py 判据夹具（每条判据正反各一例）
---

# drift 判据夹具

## 流程表

| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 阶段 | 01 | 收到材料 | 开始 | 材料 | — | — | 甲方 | 甲 | — | →02 | |
| 阶段 | 02 | 受理 | 任务 | 材料 | `M01#p001` | 受理回执 | 甲方 | 甲 | 1 天 | →03 | |
| 阶段 | 03 | 核验 | 任务 | 受理回执 | `M02`、`M05` | 核验结论 | 甲方 | 甲 | 1 天 | →04 | |
| 阶段 | 04 | 视觉复核 | 任务 | 核验结论 | `M07#p001`、`M07#p002`、`M07#p003` | 复核结论 | 甲方 | 甲 | 1 天 | →05 | ⚠ 依据是看图的读数（`vlm`） |
| 阶段 | 05 | 交付 | 结束 | 复核结论 | — | — | 甲方 | 甲 | — | — | |
"""

RECON = """| 材料 | 档位 | 难度 | 规模（依据数字） | 解析深度 | 走哪条路 | 读不动 | 假设角色（AI 填 `⚠`） | 依据（AI 填） | 验证方式（AI 填） | 状态（AI 填） |
|---|---|---|---|---|---|---|---|---|---|---|
| `M02` 乙-扫描.pdf | T3 | 最难 | 页 4 | 只取摘要 | 转图片 → 视觉（render_pages） | 缺 OCR | ⚠ 扫描件（内容待认） | 渲染后看图 | 逐页读图 | 待验 |
| `M05` 戊-补充.docx | T1 | 易 | 非空段 8 | 全量解析 | 直读（py:docx） | — | ⚠ 补充协议（推定） | 读正文 | 看签署日期 | 已推翻 |
| `M06` 己-合订本.pdf | T2 | 难 | 页 120 | 只取摘要 | PDF 文本抽取（py:pdfplumber） | — | ⚠ 含流程（待验） | 抽样读 | 抽前 10 页 | 待验 |
| `M07` 庚-白板.png | T3 | 最难 | 图 1 | 全量解析 | 转图片 → 视觉（原文件即图片） | — | ⚠ 白板（已识图） | 看图 | 核 bbox | 已验证 |
"""

INTAKE = """| 材料 | 档位 | 主题 | 含流程 | 版本关系 | 读不动 | 依据 |
|---|---|---|---|---|---|---|
| `M01` 甲-说明.md | T1 | 项目背景 | 否 | 独立 | — | `M01#p001` |
| `M02` 乙-扫描.pdf | T3 | 主体资质 | 是 | 独立 | 缺 OCR | — |
| `M03` 丙-表格.xlsx | T1 | 参数表 | 否 | 独立 | — | `M03#p001` |
| `M04` 丁-流程.docx | T1 | 采购流程 | 是 | 独立 | — | `M04#p001` |
| `M05` 戊-补充.docx | T1 | 补充约定 | 是 | 互补(M04) | — | `M05#p001` |
| `M06` 己-合订本.pdf | T2 | 全套流程 | 是 | 独立 | — | `M06#p001` |
| `M07` 庚-白板.png | T3 | 流程图白板 | 是 | 独立 | — | `M07#p001` |
"""


def make_fixture(root):
    """把夹具写进 `root`（**不进仓库**：`--out` 目录由 tempfile 建）。返回表的路径。"""
    materials = [
        {'id': 'M01', 'path': '材料/甲-说明.md', 'sha256': 'a' * 64, 'bytes': 1024,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'text', 'probe': '夹具', 'status': 'ok'},
        {'id': 'M02', 'path': '材料/乙-扫描.pdf', 'sha256': 'b' * 64, 'bytes': 2048,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T3', 'kind': 'pdf-scan', 'probe': '夹具',
         'status': 'unreadable', 'reason': '缺 OCR / 未走视觉：先跑 render_pages.py'},
        {'id': 'M03', 'path': '材料/丙-表格.xlsx', 'sha256': 'c' * 64, 'bytes': 3072,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'xlsx', 'probe': '夹具', 'status': 'ok'},
        {'id': 'M04', 'path': '材料/丁-流程.docx', 'sha256': 'd' * 64, 'bytes': 4096,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'docx', 'probe': '夹具', 'status': 'ok'},
        {'id': 'M05', 'path': '材料/戊-补充.docx', 'sha256': 'e' * 64, 'bytes': 5120,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'docx', 'probe': '夹具', 'status': 'ok'},
        {'id': 'M06', 'path': '材料/己-合订本.pdf', 'sha256': 'f' * 64, 'bytes': 6144,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T2', 'kind': 'pdf-text', 'probe': '夹具', 'status': 'ok'},
        {'id': 'M07', 'path': '材料/庚-白板.png', 'sha256': '0' * 64, 'bytes': 7168,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T3', 'kind': 'image', 'probe': '夹具', 'status': 'ok'},
    ]
    elements = [_elem('M01#p001', degraded='quote 截断到 200 字'), _elem('M03#p001'), _elem('M05#p001'),
                _elem('M07#p001', 'vlm', 'inferred'), _elem('M07#p002'), _elem('M07#p003')]
    elements += [_elem(f'M06#p{i:03d}') for i in range(1, 31)]     # M06：30 条，一条都没被引用
    elements += [_elem(f'M07#p{i:03d}') for i in range(4, 26)]     # M07：共 25 条，被引 3 条 = 12%
    (root / 'materials.json').write_text(json.dumps(materials, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8', newline='\n')
    (root / 'elements.json').write_text(json.dumps(elements, ensure_ascii=False, indent=2) + '\n',
                                        encoding='utf-8', newline='\n')
    (root / 'flowtable.md').write_text(FLOWTABLE, encoding='utf-8', newline='\n')
    (root / 'recon.md').write_text(RECON, encoding='utf-8', newline='\n')
    (root / 'intake.md').write_text(INTAKE, encoding='utf-8', newline='\n')
    return root / 'flowtable.md'


def _elem(eid, extractor='py:text', certainty='direct', degraded=None):
    """一条合成证据（键取 §2.1 的 element 模型，字段够判据用）。"""
    e = {'id': eid, 'material_id': eid.split('#')[0], 'kind': 'paragraph', 'text': f'（夹具正文 {eid}）',
         'location': {'path': '材料/夹具.bin', 'page': None, 'sheet': None, 'cell': None,
                      'bbox': None, 'quote': f'（夹具摘录 {eid}）'},
         'extractor': extractor, 'certainty': certainty}
    if degraded:
        e['degraded'] = degraded
    return e


def run(cmd):
    """跑一条命令 → `(退出码, 输出)`（UTF-8 解码，两个流合起来看）。"""
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', cwd=str(REPO))
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def ledgerize(root):
    """用**产品的写入器**造账本（不手写 JSON：那会绕开 §2.1 的键封闭校验）。"""
    rc, out = run([sys.executable, str(LEDGER), '--materials', str(root / 'materials.json'),
                   '--elements', str(root / 'elements.json'), '--task', 'driftfix',
                   '-o', str(root / 'evidence.json')])
    return rc == 0, out


def build(root, force=True):
    """出草稿 → `(退出码, 输出, 草稿文本)`。"""
    cmd = [sys.executable, str(DRIFT), 'build', str(root / 'flowtable.md'),
           '--ledger', str(root / 'evidence.json'), '--recon', str(root / 'recon.md'),
           '--intake', str(root / 'intake.md'), '-o', str(root / 'drift.md')]
    if force:
        cmd.append('--force')
    rc, out = run(cmd)
    f = root / 'drift.md'
    return rc, out, (f.read_text(encoding='utf-8') if f.exists() else '')


def check(root, text, flowtable=None):
    """把 `text` 当账本喂给 `check` → `(退出码, 输出)`。"""
    (root / 't.md').write_text(text, encoding='utf-8', newline='\n')
    cmd = [sys.executable, str(DRIFT), 'check', str(root / 't.md'),
           '--flowtable', str(flowtable or (root / 'flowtable.md')),
           '--ledger', str(root / 'evidence.json'), '--recon', str(root / 'recon.md'),
           '--intake', str(root / 'intake.md')]
    return run(cmd)


def fill(text, drift_act='已解释', gap_act='已放弃', basis='已核：措辞不同但同一件事',
         where='第 3 页', note='与流程无关'):
    """填上 AI 那几列（默认填成可收敛的一版）。列序 = `drift.py` 的 `*_COLUMNS`。"""
    out = []
    for line in text.splitlines():
        if re.match(r'^\| `X\d+` \|', line):
            c = [x.strip() for x in line.strip().strip('|').split('|')]
            c[4], c[5] = drift_act, basis
            line = '| ' + ' | '.join(c) + ' |'
        elif re.match(r'^\| `Q\d+` \|', line):
            c = [x.strip() for x in line.strip().strip('|').split('|')]
            c[3], c[5], c[6] = where, gap_act, note
            line = '| ' + ' | '.join(c) + ' |'
        out.append(line)
    return '\n'.join(out) + '\n'


def set_disposition(text, tag, act, basis):
    """改某一行的处置/依据（按单元格重建，免得手工拼串多一格——本轮就栽过一次）。"""
    out = []
    for line in text.splitlines():
        if line.startswith(f'| `{tag}`'):
            c = [x.strip() for x in line.strip().strip('|').split('|')]
            c[4], c[5] = act, basis
            line = '| ' + ' | '.join(c) + ' |'
        out.append(line)
    return '\n'.join(out) + '\n'


def paths(root, draft):
    """9 条路径：判据读数 1 条 + `check` 的过/不过 8 条。返回 `[(名字, 是否符合预期, 退出码, 输出)]`。"""
    cases = []
    rc, out, _ = build(root, force=False)                              # 覆盖保护
    cases.append(('① build 拒绝覆盖已有账（那是漂移账）', rc == 2 and '已存在' in out, rc, out))
    fixed = root / 'flowtable.md'
    txt = fixed.read_text(encoding='utf-8').replace('| 1 天 | →03 | |', '| 1 天 | →03 | ⚠ 依据截断过 |')
    (root / 'fixed.md').write_text(txt, encoding='utf-8', newline='\n')
    rc, out = check(root, draft)
    cases.append(('② 草稿（未处置）→ 不许过', rc == 1 and out.count('没收敛') >= 6, rc, out))
    rc, out = check(root, fill(draft))
    cases.append(('③ 全部已解释 / 已放弃 → 收敛', rc == 0, rc, out))
    rc, out = check(root, fill(draft, drift_act='已修'))
    cases.append(('④ 标「已修」但判据仍命中 → 不许过', rc == 1 and '仍然命中' in out, rc, out))
    rc, out = check(root, fill(draft, basis='—'))
    cases.append(('⑤ 「已解释」没写依据 → 不许过', rc == 1 and '必须写依据' in out, rc, out))
    rc, out = check(root, fill(draft, gap_act='已取证', where='—'))
    cases.append(('⑥ 「已取证」没写要哪一片 → 不许过', rc == 1 and '必须写「要哪一片」' in out, rc, out))
    rc, out = check(root, fill(draft, gap_act='已放弃', note='—'))
    cases.append(('⑦ 「已放弃」没写说明 → 不许过', rc == 1 and '必须写说明' in out, rc, out))
    stale = '\n'.join(l for l in fill(draft).splitlines() if not l.startswith('| `X02`')) + '\n'
    rc, out = check(root, stale)
    cases.append(('⑧ 漏了一条现在的命中 → 不许过', rc == 1 and '没有这一条' in out, rc, out))
    t = set_disposition(fill(draft), 'X01', '已修', '已给 02 补 ⚠')
    t = set_disposition(t, 'X02', '已解释', '同一份补充件的两种叫法')
    t = set_disposition(t, 'X03', '已解释', 'M02 另有直读副本，已在表内注明')
    rc, out = check(root, t, flowtable=root / 'fixed.md')
    cases.append(('⑨ 真修掉的那条判「已修」→ 收敛', rc == 0, rc, out))
    return cases


def query_run(root, *args):
    """跑一条 `query.py`（账本固定用夹具那份）。"""
    return run([sys.executable, str(QUERY), str(root / 'evidence.json'), *args])


def query_paths(root):
    """点名取子集的 7 条路径：分批 + 游标 · 续批 · 行区间 · 关键词 · 只裁显示 · 语法错 · 喂错形态。"""
    cases = []
    rc, out = query_run(root, '--material', 'M06', '--batch', '3')
    cases.append(('⑩ 点名 + 分批：命中 30 给 3，带游标', rc == 0 and '命中 30 条' in out
                  and '`--skip 3`' in out, rc, out))
    rc, out = query_run(root, '--material', 'M06', '--batch', '3', '--skip', '3')
    cases.append(('⑪ 按游标续批：给第 4–6 条', rc == 0 and 'M06#p004' in out and 'M06#p006' in out
                  and 'M06#p001' not in out, rc, out))
    rc, out = query_run(root, '--material', 'M06', '--range', 'lines=2-3', '--batch', '5')
    cases.append(('⑫ 行区间（材料内第 N 条，1 起）', rc == 0 and 'M06#p002' in out and 'M06#p003' in out
                  and 'M06#p001' not in out, rc, out))
    rc, out = query_run(root, '--grep', 'M07#p005', '--batch', '5')
    cases.append(('⑬ 关键词：只回含它的那条', rc == 0 and '命中 1 条' in out and 'M07#p005' in out,
                  rc, out))
    rc, out = query_run(root, '--range', 'rows=1-2', '--batch', '3')
    cases.append(('⑭ 只给 rows= 不许把命中筛成 0（它只管显示）', rc == 0 and '命中 58 条' in out, rc, out))
    rc, out = query_run(root, '--range', 'pages=9-1')
    cases.append(('⑮ 范围语法错 → 退 2 + 人话', rc == 2 and '上界小于下界' in out, rc, out))
    rc, out = run([sys.executable, str(QUERY), str(root / 'intake.md')])
    cases.append(('⑯ 喂错形态（不是账本）→ 退 2 + 人话', rc == 2 and '合法 JSON' in out, rc, out))
    return cases


def make_deck(path):
    """造一份**最小可读的 .pptx**：确切部件 `ppt/presentation.xml` + 每张一行标题一行正文。

    为什么夹具造得出来：`.pptx` 就是 zip + `ppt/slides/slideN.xml` 的 `<a:t>` 运行——
    所以"pptx 能不能读"这件事**不需要真的 PowerPoint**，也不需要 `python-pptx`（本仓已不依赖它）。
    """
    p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}"/>')
        for i, title in enumerate(DECK_TITLES, 1):
            z.writestr(f'ppt/slides/slide{i}.xml',
                       f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>'
                       f'<a:p><a:r><a:t>{title}</a:t></a:r></a:p>'
                       f'<a:p><a:r><a:t>正文 {i}：审批流程第 {i} 步</a:t></a:r></a:p>'
                       f'</p:spTree></p:cSld></p:sld>')


def pptx_paths(root):
    """pptx 全链 3 条路径：**认得出来**（T1 + kind）· **有摘要**（张数 + 每张标题）· **撬得开**（按张 + 页码 + 超限留痕）。

    这三条正是用户故事里那一步（"大体量的 pptx，先看摘要找线索，再指名撬开那几页"）的最小可验版本。
    """
    d = root / 'deck'
    d.mkdir(exist_ok=True)
    make_deck(d / '大演示稿.pptx')
    cases = []
    rc, out = run([sys.executable, str(PROBE_CMD), str(d), '--json'])
    mats = []
    if rc == 0 and '[' in out:
        try:
            mats = json.loads(out[out.index('['):])
        except ValueError:
            mats = []
    ok = bool(mats) and mats[0].get('tier') == 'T1' and mats[0].get('kind') == 'pptx'
    cases.append(('⑰ probe：pptx 判 T1 + kind=pptx（有 reader 才敢判可直读）', ok, rc, out))
    if not mats:
        cases.append(('⑱ recon：出 pptx 摘要', False, rc, '（probe 没产出材料层，跳过）'))
        cases.append(('⑲ pptx 读者：按张出元素', False, rc, '（同上）'))
        return cases
    (d / 'materials.json').write_text(json.dumps(mats, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8', newline='\n')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                   '-o', str(d / 'recon.md')])
    rec = (d / 'recon.md').read_text(encoding='utf-8') if (d / 'recon.md').exists() else ''
    cases.append(('⑱ recon：出 pptx 摘要（张数 + 每张标题）',
                  rc == 0 and '幻灯片 3 张' in rec and DECK_TITLES[1] in rec, rc, out + rec[:300]))
    rc, out = run([sys.executable, str(OOXML_CMD), '--materials', str(d / 'materials.json'),
                   '-o', str(d / 'elements.json'), '--max-slides', '2'])
    els = []
    if (d / 'elements.json').exists():
        try:
            els = json.loads((d / 'elements.json').read_text(encoding='utf-8'))
        except ValueError:
            els = []
    ok = (rc == 0 and len(els) == 2 and els[0].get('location', {}).get('page') == 1
          and DECK_TITLES[1] in els[1].get('text', '') and els[0].get('degraded'))
    cases.append(('⑲ pptx 读者：按张出元素 + 页码坐标 + 超限留痕', ok, rc, out + str(els[:2])[:300]))
    return cases


def _minimal_docx(path):
    """一份**真**的最小 docx（`python-docx` 自己造的，所以它必然合法）。"""
    import docx
    d = docx.Document()
    d.add_heading('验收流程', level=1)
    d.add_paragraph('第一步：受理；第二步：核验；第三步：交付。')
    d.save(str(path))


def _minimal_xlsx(path):
    """一份**真**的最小 xlsx（`openpyxl` 自己造的）。"""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '短名单'
    ws.append(['序号', '供应商'])
    ws.append([1, '甲公司'])
    wb.save(str(path))


def _unsized_xlsx(path):
    """**没有 `<dimension>` 的工作表**（`openpyxl` 的 write-only 模式就这么导出）。

    审计 R2 的原案：第三方导出 / write-only 常没这个标签，`openpyxl` 会抛 `Worksheet is unsized`，
    原先 `recon` 直接裸栈退 1、整批零产出。现在它必须只影响自己那一行（记"尺寸不可知"）。
    """
    import openpyxl
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet('流式表')
    ws.append(['序号', '金额'])
    ws.append([1, 100])
    wb.save(str(path))


def _minimal_png(path):
    """一张**真**的 4×4 PNG（Pillow 造的）。"""
    from PIL import Image
    Image.new('RGB', (4, 4), (200, 30, 30)).save(str(path))


def _pdf_bytes(with_font):
    """最小 PDF 字节。**只要有 `/Font` 就够 `probe` 判"有文本层"**——本夹具只考探测，不考抽取。

    所以不写 xref 表（`pdfplumber` 会拒收它）——那正好**顺带考另一件事**：一份读不动的材料
    必须只影响它自己，整链照常退 0（§1.4 硬要求 2）。
    """
    font = '/Resources<</Font<</F1 5 0 R>>>>' if with_font else '/Resources<<>>'
    body = b'BT /F1 12 Tf 10 50 Td (hello) Tj ET' if with_font else b'q 1 0 0 1 0 0 cm /Im0 Do Q'
    return (b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
            b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
            b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]' + font.encode() +
            b'/Contents 4 0 R>>endobj\n'
            b'4 0 obj<</Length ' + str(len(body)).encode() + b'>>stream\n' + body +
            b'\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n')


def _zip_with(path, parts):
    """按 `{部件名: 字节}` 写一个 zip —— 用来造"半容器 / 坏部件"这类**只有内容能分辨**的材料。"""
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in parts.items():
            z.writestr(name, data)


def build_material_tree(root):
    """造一棵**合成材料树**：审计抓到的那批"整批硬失败"全在这里复现。

    台账（每行 = 一份材料 + 它要考的那件事）：

    | 文件 | 考什么 |
    |---|---|
    | `a.docx` `b.xlsx` `c.pptx` `f.txt` `g.csv` | 五种**有 reader** 的正常材料（含 CSV） |
    | `h.png` | 图片魔数（T3） |
    | `d-text.pdf` `e-scan.pdf` | 有 / 无 `/Font` → `pdf-text` / `pdf-scan`（探测的分档依据） |
    | `i.xlsx.et` | **改名件**：真 xlsx 叫 `.et`（WPS 后缀）——必须按内容判、按内容读（审计 F6） |
    | `j.pdf.png` | **改名件**：PDF 字节叫 `.png`——不许被扩展名带偏成图片（审计 F3） |
    | `k.docx` | **半容器**：有 `word/` 却没有 `word/document.xml`（审计 R3） |
    | `l.docx` `m.xlsx` | **部件是垃圾**：容器像、正文坏（原先让 `recon` 裸栈退 1） |
    | `n.txt` | GBK 纯文本：**不猜编码**，要记读不动 + 可执行提示 |
    | `o.txt` | 空文件（0 字节） |
    | `p.doc` | 假 OLE 魔数：legacy 那条路（本机无转换器 ⇒ 记读不动 + 提示） |
    | `q.xlsx` | **无 `<dimension>` 的流式表**（审计 R2：原先 `recon` 在这里裸栈退 1） |

    返回材料目录。**全部现造在临时目录里**，不进仓库。
    """
    d = root / '材料树'
    d.mkdir(parents=True, exist_ok=True)
    _minimal_docx(d / 'a.docx')
    _minimal_xlsx(d / 'b.xlsx')
    make_deck(d / 'c.pptx')
    (d / 'd-text.pdf').write_bytes(_pdf_bytes(True))
    (d / 'e-scan.pdf').write_bytes(_pdf_bytes(False))
    (d / 'f.txt').write_text('第一行：材料清单\n第二行：审批流程\n', encoding='utf-8')
    (d / 'g.csv').write_text('序号,名称\n1,甲\n2,乙\n', encoding='utf-8')
    _minimal_png(d / 'h.png')
    shutil.copy(d / 'b.xlsx', d / 'i.xlsx.et')                 # 改名件（WPS 后缀）
    shutil.copy(d / 'd-text.pdf', d / 'j.pdf.png')             # 改名件（PDF 叫 .png）
    _zip_with(d / 'k.docx', {'word/styles.xml': '<w:styles/>'})            # 半容器
    _zip_with(d / 'l.docx', {'word/document.xml': '这不是 XML <<<'})        # 部件是垃圾
    _zip_with(d / 'm.xlsx', {'xl/workbook.xml': 'not xml at all'})         # 部件是垃圾
    (d / 'n.txt').write_bytes('第一行：中文\n第二行：中文\n'.encode('gbk'))  # GBK
    (d / 'o.txt').write_bytes(b'')                                        # 空文件
    (d / 'p.doc').write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 64)   # 假 OLE
    _unsized_xlsx(d / 'q.xlsx')                                           # 无 <dimension> 的流式表
    return d


def materials_paths(root):
    """材料树 5 条路径：**探测不撒谎 · 整批不崩 · 缩样尽力而为 · 护栏记在行里**。

    这是 `coding-spec` G13 要的仪器：审计实测过"三类整批硬失败 + 五类 `recon` 崩溃**全都逃过十道门**"——
    不是门坏了，是这批判据根本没进门。这笔账在这里结清。
    """
    d = build_material_tree(root)
    cases = []
    rc, out = run([sys.executable, str(PROBE_CMD), str(d), '--json'])
    mats = []
    if rc == 0 and '[' in out:
        try:
            mats = json.loads(out[out.index('['):])
        except ValueError:
            mats = []
    by = {pathlib.Path(m['path']).name: m for m in mats}
    ok = (len(mats) == 17 and all(m.get('tier') and m.get('kind') for m in mats)
          and by.get('i.xlsx.et', {}).get('kind') == 'xlsx'        # 改名件按内容判
          and by.get('j.pdf.png', {}).get('kind') == 'pdf-text'
          and by.get('k.docx', {}).get('kind') == 'unknown'        # 半容器不许冒充 docx
          and by.get('o.txt', {}).get('tier') == 'T4')             # 空文件记 T4，不猜
    cases.append(('⑳ probe：17 份都有档位 + kind；改名件/半容器/空文件都按内容判', ok, rc,
                  out[-300:] if not ok else ''))
    if not mats:
        return cases
    (d / 'materials.json').write_text(json.dumps(mats, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8', newline='\n')
    t1 = {m.get('kind') for m in mats if m.get('tier') == 'T1'}
    cases.append(('㉑ probe 不变式：判 T1 的 kind 全都有 reader 认领',
                  t1 <= {'docx', 'xlsx', 'pptx', 'text'}, rc, f'T1 的 kind = {sorted(t1)}'))
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--ledger', str(d / 'evidence.json'), '--task', 'mat-tree'])
    els = []
    if (d / 'evidence.json').exists():
        try:
            els = json.loads((d / 'evidence.json').read_text(encoding='utf-8')).get('elements') or []
        except ValueError:
            els = []
    bad = [m for m in json.loads((d / 'evidence.json').read_text(encoding='utf-8')).get('materials', [])
           if m.get('status') != 'ok'] if els else []
    cases.append(('㉒ parse 整链：坏材料逐份记账、整批不崩（退 0 且证据没归零）',
                  rc == 0 and len(els) > 0 and len(bad) >= 3
                  and all(m.get('reason') for m in bad), rc, out[-400:] + str(bad)[:200]))
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                   '-o', str(d / 'recon.md')])
    rec = (d / 'recon.md').read_text(encoding='utf-8') if (d / 'recon.md').exists() else ''
    rows = [l for l in rec.splitlines() if l.startswith('| `M')]
    cells = [[c.strip() for c in l.strip().strip('|').split('|')] for l in rows]
    # 「每种 kind 都有交代」的可机器核形式：**每行的「规模」或「读不动」至少有一格非空**——
    # 空白格子 = 这一份材料没被交代（那正是审计里"摘要静默为空"的样子）。
    blank = [c[0] for c in cells if not c[4].strip('— ') and not c[7].strip('— ')]
    ok = (rc == 0 and len(rows) == 17 and not blank
          and '摘要不可得' in rec                       # legacy：说清极限
          and '尺寸不可知' in rec                        # 无 <dimension> 的流式表：记在行里而不是崩
          and '超护栏' not in rec)                      # 正常阈值下不该有护栏记账
    cases.append(('㉓ recon：17 行 · 每行的「规模/读不动」都有交代（坏部件/半容器/流式表/GBK/空文件）',
                  ok, rc, (out[-200:] + f'｜空白行={blank}') if not ok else ''))
    small = d / 'small.yaml'
    small.write_text('recon:\n  easy_max_bytes: 1024\n  max_open_bytes: 512\n'
                     '  outline_max: 50\n  outline_show: 3\n', encoding='utf-8')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                   '--dict', str(small), '-o', str(d / 'recon-small.md')])
    rec2 = (d / 'recon-small.md').read_text(encoding='utf-8') if (d / 'recon-small.md').exists() else ''
    cases.append(('㉔ 超护栏：`max_open_bytes` 调到 512 后记在行里（不打开结构、不崩）',
                  rc == 0 and '超护栏' in rec2, rc, out[-300:] if rc != 0 else ''))

    # ㉕ 抽取时收窄（§5.3 的执行面）：**只要两份 + 只留含关键词的片段**，其余记「本轮未取」
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--only', 'M06,M07', '--grep', '审批',
                   '--elements', str(d / 'e-only.json'), '--notes', str(d / 'n-only.json'),
                   '--ledger', str(d / 'led-only.json'), '--task', 'narrow'])
    led = {}
    if (d / 'led-only.json').exists():
        try:
            led = json.loads((d / 'led-only.json').read_text(encoding='utf-8'))
        except ValueError:
            led = {}
    ms = {m['id']: m for m in led.get('materials', [])}
    els = led.get('elements', [])
    ok = (rc == 0
          and {e['material_id'] for e in els} == {'M06'}                 # 只有 f.txt 含「审批」
          and ms.get('M07', {}).get('status') == 'skipped'               # 被滤空的那份：记「未取」
          and '未取' in (ms.get('M07', {}).get('reason') or '')
          and all(m.get('status') == 'skipped' for k, m in ms.items() if k not in ('M06', 'M07'))
          and all('本轮收窄' in (e.get('degraded') or '') for e in els))
    cases.append(('㉕ 抽取时收窄（--only + --grep）：只留该留的，其余记「本轮未取」而不是读不动',
                  ok, rc, (out[-300:] + str({k: v.get('status') for k, v in ms.items()})) if not ok else ''))

    # ㉖ 范围收窄下沉到适配器：xlsx 只要一张子表 + 只要第 2 行（逐条记 degraded）
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--only', 'M02', '--sheet', '短名单', '--rows', '2-2',
                   '--elements', str(d / 'e-row.json'), '--notes', str(d / 'n-row.json')])
    row_els = []
    if (d / 'e-row.json').exists():
        try:
            row_els = json.loads((d / 'e-row.json').read_text(encoding='utf-8'))
        except ValueError:
            row_els = []
    ok = (rc == 0 and len(row_els) == 1 and row_els[0].get('rows') == [['1', '甲公司']]
          and '--rows 只要第 2–2 行' in (row_els[0].get('degraded') or ''))
    cases.append(('㉖ 范围收窄（--sheet + --rows）：只回那一张表的第 2 行，且带降级留痕',
                  ok, rc, (out[-200:] + str(row_els)[:200]) if not ok else ''))
    return cases


def main(argv=None):
    """造夹具 → 比 `drift` 读数 → 跑漂移 9 + 取子集 7 + pptx 3 + 材料树 5 条路径 → 打印结论并给退出码。"""
    sys.stdout.reconfigure(encoding='utf-8')
    root = pathlib.Path(argv[0]) if argv else pathlib.Path(tempfile.mkdtemp(prefix='pipeline-fix-'))
    root.mkdir(parents=True, exist_ok=True)
    print(f'夹具目录：{root}')
    make_fixture(root)
    ok, out = ledgerize(root)
    if not ok:
        print(f'✗ 账本没写出来：{out.strip()[-300:]}')
        return 2
    rc, out, draft = build(root)
    head = '✓ 漂移 3 条 · 缺口 3 条' in out
    print(f'{"PASS" if rc == 0 and head else "FAIL"}  ⓪ 读数：{out.splitlines()[0] if out else "（无输出）"}')
    bad = 0 if (rc == 0 and head) else 1
    for name, good, rc, out in (paths(root, draft) + query_paths(root) + pptx_paths(root)
                                + materials_paths(root)):
        print(f'{"PASS" if good else "FAIL"}  {name}  （rc={rc}）')
        if not good:
            print('      ' + out.strip().replace('\n', '\n      ')[:500])
            bad += 1
    print(f'—— {"全部符合预期" if not bad else f"{bad} 条不符合预期"}（夹具：{root}）')
    if argv:
        return 0 if not bad else 1
    shutil.rmtree(root, ignore_errors=True)          # 临时目录自己收（`--out` 给了就留着）
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
