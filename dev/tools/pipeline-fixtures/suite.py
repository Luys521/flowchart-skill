# -*- coding: utf-8 -*-
"""pipeline-fixtures/suite.py — 材料链两台仪器的合成夹具与路径测试（**门⑪ 每轮验收都跑**）。

覆盖两件东西：
- `scripts/drift.py`（PIPELINE-SPEC §5）：判据 D1—D5 + `check` 的**账目对账**（说谎 / 过期 / 无理由都要抓住）；
- `scripts/query.py`（§5.3）：**点名取子集**——材料 / 范围 / 关键词 / 分批 + 游标，只查不抽。

另有三条"接缝"路径（夹具不能只测"判据对不对"，还要测"规范与仪器对不对得上"）：
`scripts/intake.py`（§3 清点，㊴ / ㊵）· `scripts/recon.py check` 的正例（㉝）· `.wps` / `.dps` 这类
**只认内容不认后缀**的改名件（㉔b）· 以及**规范里的列模板必须逐字等于仪器列规范**（㊶）。

为什么要有它：这些仪器的判据都有"**读得对不对**"与"**边界守不守得住**"两半，后者用真实材料造不出来
（要故意标错、要故意越界），只能合成。实测抓到过三件真问题，全在夹具里现形：
`check` 原先**只查了"已修是否真修"、没查"现在的命中是否漏在账外"**；伴生表**一行少一列被静默当成"没给"**
（D2 静默不跑而表头还写"跳过了 D2"）；`--range rows=` 只顾着裁显示、差点把命中筛成 0。

夹具（`--out` 下现生成，不写进仓库）：
    7 份材料（含一份 `status=unreadable`、一份 30 条元素全没引用的合订本）
    × 一张 5 节点的表 × 假设账（有一条 `状态=已推翻`）× 清点（两条「含流程 = 是」却零引用）
    ——清点那份**不手抄**：由 `intake.py build` 出骨架再填 AI 四列（手抄过一版，16 条错，
    而"D4 语法互斥"那条阻断就是被它藏住的）。

期望读数（`--out` 下的 `drift.md`）：
    漂移 3 条：D1 节点 02（依据带**抽取质量**降级）· D2 节点 03（`M05` 已推翻仍在用）· D3 节点 03（`M02` 读不动）
    缺口 3 条：D4 `M04`（零引用）· D4 `M06`（零引用）· D5 `M06`（30 条元素只引 0 条）
    反例：节点 04 引 `M07#p001`（vlm）但描述以 `⚠` 开头 → **不报 D1**；
          `M07` 引 3/25 = 12% ≥ 10% → **不报 D5**；
          节点 03 还引了 `M01#p002`（只有**浏览摘录**截断）→ **不报 D1**（摘录短了 ≠ 证据弱了）

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
sys.path.insert(0, str(REPO / 'scripts'))
# 夹具也走**正式接口**填 AI 列（`cells.fill` 按列名落笔，不再手改单元格）：见 `scripts/cells.py`。
import cells                                                    # noqa: E402
import drift as DRIFT_MOD                                       # noqa: E402
import intake as INTAKE_MOD                                     # noqa: E402
import recon as RECON_MOD                                       # noqa: E402
LEDGER = REPO / 'scripts' / 'ledger.py'
DRIFT = REPO / 'scripts' / 'drift.py'
QUERY = REPO / 'scripts' / 'query.py'
PROBE_CMD = REPO / 'scripts' / 'probe.py'
RECON_CMD = REPO / 'scripts' / 'recon.py'          # 名字带 _CMD：本文件的 `RECON` 是**夹具表格文本**
OOXML_CMD = REPO / 'scripts' / 'parse_ooxml.py'
IMPORT_CMD = REPO / 'scripts' / 'import_table.py'
PARSE_CMD = REPO / 'scripts' / 'parse.py'
INTAKE_CMD = REPO / 'scripts' / 'intake.py'
PLAN_CMD = REPO / 'scripts' / 'plan.py'
SPEC = REPO / 'dev' / 'PIPELINE-SPEC.md'

# 合成 pptx 的标题（第 2 张含「审批」——后面的取子集断言就找它）
DECK_TITLES = ('第 1 章 项目概况', '第 2 章 审批与分工', '第 3 章 结算与付款')
# 幻灯片**之外**的文字（图表 / SmartArt / 备注）：读者不读，但必须报出来（不许静默漏掉）
DECK_OUTSIDE = ('CHARTONLY词', 'SMARTARTONLY词', 'NOTESONLY词')
DECK_SLIDES = len(DECK_TITLES) + 1        # 3 张有字 + 1 张纯图片

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
| 阶段 | 03 | 核验 | 任务 | 受理回执 | `M02`、`M05`、`M01#p002` | 核验结论 | 甲方 | 甲 | 1 天 | →04 | |
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

INTAKE_COLUMNS = ('材料', '档位', '主题', '含流程', '版本关系', '读不动', '依据')
# 清点卡片的 **AI 四列**（§3：主题 / 含流程 / 版本关系 / 依据）。机器那三列由 `intake.py build` 填，
# 这里只给语义列——**手抄整张卡片踩过坑**：手抄的那版 16 条错（主题没标 ⚠、读不动与账本不逐字、
# 互补关系单向），而"D4 语法互斥"那条阻断正是被它藏住的（夹具自己不合规 ⇒ 测不出判据是死的）。
INTAKE_AI = {
    'M01': ('⚠ 项目背景', '否 ⚠ 通篇背景说明，无过程步骤', '独立', '`M01#p001`'),
    'M02': ('⚠ 主体资质', '是 ⚠ 含资质审查步骤（待视觉）', '独立', '—'),
    'M03': ('⚠ 参数表', '否 ⚠ 通篇参数，无步骤', '独立', '`M03#p001`'),
    'M04': ('⚠ 采购流程', '是 ⚠ 有审批步骤', '互补(M05)', '—'),
    'M05': ('⚠ 补充约定', '是 ⚠ 补充的也是审批步骤', '互补(M04)', '`M05#p001`'),
    'M06': ('⚠ 全套流程', '是 ⚠ 合订本含审批环节', '独立', '`M06#p001`'),
    'M07': ('⚠ 流程图白板', '是 ⚠ 白板上画的就是流程', '不确定', '`M07#p001`'),
}


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
    # `M01#p001` 挂**抽取质量**降级（D1 该命中）；`M01#p002` 只挂**浏览摘录**截断（D1 **不许**命中——
    # 那是 §2.3 的写盘契约，摘录短了不等于证据弱了；2026-09-18 真材料集上实测：不分这两类时，
    # 一份每个节点都规矩引条款的表被报成 23 条"等级拔高"）。
    elements = [_elem('M01#p001', degraded='抽取质量有保留：单字行 62%（140/225）'),
                _elem('M01#p002', degraded='quote 截断到 200 字'),
                _elem('M03#p001', sheet='短名单'),
                _elem('M05#p001'),
                _elem('M07#p001', 'vlm', 'inferred'), _elem('M07#p002'), _elem('M07#p003')]
    # M06 的 30 条**带上页码**：`query.py --range pages=` 才有正例可测（原先夹具里 `page` 全是 `None`，
    # 于是门⑪ 对 `pages=` / `sheet=` 这两支坐标只有反例、没有正例——删掉那两支代码也照样全绿）。
    elements += [_elem(f'M06#p{i:03d}', page=i) for i in range(1, 31)]   # 30 条，一条都没被引用
    elements += [_elem(f'M07#p{i:03d}') for i in range(4, 26)]     # M07：共 25 条，被引 3 条 = 12%
    (root / 'materials.json').write_text(json.dumps(materials, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8', newline='\n')
    (root / 'elements.json').write_text(json.dumps(elements, ensure_ascii=False, indent=2) + '\n',
                                        encoding='utf-8', newline='\n')
    (root / 'flowtable.md').write_text(FLOWTABLE, encoding='utf-8', newline='\n')
    (root / 'recon.md').write_text(RECON, encoding='utf-8', newline='\n')
    # `intake.md` **不在这里写**：它由 `intake.py build` 从账本出骨架（见 `intakeize`），
    # 手抄一份就是第二份真值，而且必然过不了 `check`（§3：档位 / 读不动只许抄）。
    return root / 'flowtable.md'


def _elem(eid, extractor='py:text', certainty='direct', degraded=None, page=None, sheet=None):
    """一条合成证据（键取 §2.1 的 element 模型，字段够判据用）。

    `page` / `sheet` 是 `location` 里的坐标（`query.py --range pages= / sheet=` 要按它取值）。
    """
    e = {'id': eid, 'material_id': eid.split('#')[0], 'kind': 'paragraph', 'text': f'（夹具正文 {eid}）',
         'location': {'path': '材料/夹具.bin', 'page': page, 'sheet': sheet, 'cell': None,
                      'bbox': None, 'quote': f'（夹具摘录 {eid}）'},
         'extractor': extractor, 'certainty': certainty}
    if degraded:
        e['degraded'] = degraded
    return e


def run(cmd):
    """跑一条命令 → `(退出码, 输出)`（UTF-8 解码，两个流合起来看）。cwd 固定在仓库根。"""
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', cwd=str(REPO))
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def repo_root_clean():
    """**跑完不许往仓库根写字节**——这条是踩过才加的：夹具里有一次漏给 `--elements/--notes`，
    于是 `parse.py` 的默认产物名把 `<仓库根>/elements.json`、`notes.json` 写了出来，
    而下一次 `git add -A` 顺手把它们（连同用户材料正文）提交进库了。
    `.gitignore` 能挡住它**进库**，但挡不住"没人发现"——所以在这里当场判。
    """
    return [p.name for p in (REPO / 'elements.json', REPO / 'notes.json',
                             REPO / 'materials.json', REPO / 'evidence.json') if p.exists()]


def ledgerize(root):
    """用**产品的写入器**造账本（不手写 JSON：那会绕开 §2.1 的键封闭校验）。"""
    rc, out = run([sys.executable, str(LEDGER), '--materials', str(root / 'materials.json'),
                   '--elements', str(root / 'elements.json'), '--task', 'driftfix',
                   '-o', str(root / 'evidence.json')])
    return rc == 0, out


def intakeize(root):
    """清点卡片：`intake.py build` 出骨架（**用产品的写入器**）→ 填 AI 四列（`INTAKE_AI`）。

    为什么要走这条路而不是手写一份 `intake.md`：手写的那版**自己就过不了** `intake.py check`
    （16 条错：主题没标 `⚠`、`读不动` 没与账本逐字一致、`互补` 单向），于是夹具测的东西与规范说的东西
    之间隔了一层——审计里"D4 在合规 intake 上永不命中"这条阻断，正是被这一层藏住的
    （判据按逐字 `=='是'` 写，而规范要求同格写理由并标 `⚠`，两套语法互斥；夹具恰好两边都不合规，
    于是它永远绿）。改成"骨架 + 填 AI 列"之后，夹具这份卡片**同时**满足 §3 与 §5.2，两边的语法冲突
    当场现形。
    """
    rc, out = run([sys.executable, str(INTAKE_CMD), 'build', str(root / 'evidence.json'),
                   '-o', str(root / 'intake.md'), '--todo', str(root / 'intake.todo.json')])
    p = root / 'intake.md'
    if rc != 0 or not p.exists():
        return False, out                               # 骨架都没出来就别往下填（与 `ledgerize` 同一约定）
    # 填 AI 四列**走正式接口**（`cells.py`）：夹具与产品侧同一条路，列序/转义都不由人手保证。
    new, errs = cells.fill(p.read_text(encoding='utf-8'),
                           {k: {'主题': v[0], '含流程': v[1], '版本关系': v[2], '依据': v[3]}
                            for k, v in INTAKE_AI.items()}, INTAKE_MOD.TODO_TABLES)
    if errs:
        return False, f'cells.fill 落了空：{errs}'
    p.write_text(new, encoding='utf-8', newline='\n')
    return True, out


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


def answers_of(text, drift_act='已解释', gap_act='已放弃', basis='已核：措辞不同但同一件事',
               where='第 3 页', note='与流程无关'):
    """把"AI 该填的那几格"写成**答案 JSON**——正式接口是 `scripts/cells.py`（见它的文件头）。

    夹具也走这条路，理由与产品侧同一条：**按列名写、由脚本落笔**，列序/转义出不了错。
    （原先这里按列序号 `c[4], c[5] = …` 改单元格——那正是 2026-09-18 在真材料上踩到的坑。）
    """
    ans = {}
    for line in text.splitlines():
        if re.match(r'^\| `X\d+` \|', line):
            ans[line.split('`')[1]] = {'处置': drift_act, '依据': basis}
        elif re.match(r'^\| `Q\d+` \|', line):
            ans[line.split('`')[1]] = {'要哪一片': where, '状态': gap_act, '说明': note}
    return ans


def fill(text, drift_act='已解释', gap_act='已放弃', basis='已核：措辞不同但同一件事',
         where='第 3 页', note='与流程无关', only=None):
    """填上 AI 那几列（默认填成可收敛的一版）——**经 `cells.fill` 按列名落笔**。

    `only` 给了就只填那一行（用来测"某一行处置不同"这类路径）。
    """
    ans = answers_of(text, drift_act, gap_act, basis, where, note)
    if only:
        ans = {k: v for k, v in ans.items() if k == only}
    new, errs = cells.fill(text, ans, DRIFT_MOD.TODO_TABLES)
    if errs:                                   # 夹具自身故障：接口没把答案落进去
        raise AssertionError(f'cells.fill 落了空：{errs}')
    return new


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
    # ⑨ 改完表重出一份账 → 收敛（**账与表必须对得上**：账里记着它是对着哪张表算的，
    #    拿 A 表的账去 check B 表要报错——那正是"改动后账没跟上"的一种）。
    #    "标已修却不真修"由 ④ 反向钉住；这里证的是"改完表 → 重出账 → 收敛"这条路通。
    rc, out = run([sys.executable, str(DRIFT), 'build', str(root / 'fixed.md'),
                   '--ledger', str(root / 'evidence.json'), '--recon', str(root / 'recon.md'),
                   '--intake', str(root / 'intake.md'), '-o', str(root / 'd-fixed.md'), '--force'])
    draft_fixed = (root / 'd-fixed.md').read_text(encoding='utf-8')
    rc, out = check(root, fill(draft_fixed), flowtable=root / 'fixed.md')
    cases.append(('⑨ 改完表重出账 → 收敛（拿旧账 check 新表要报"对不上"）', rc == 0, rc, out))
    rc, out = run([sys.executable, str(DRIFT), 'check', str(root / 'd-fixed.md'),
                   '--flowtable', str(root / 'flowtable.md'), '--ledger', str(root / 'evidence.json'),
                   '--recon', str(root / 'recon.md'), '--intake', str(root / 'intake.md')])
    cases.append(('⑨b 拿 A 表的账 check B 表 → 退 1（账与表对不上）',
                  rc == 1 and '另一张表' in out, rc, out))

    # ㉟ D4 在**合规** intake.md 上必须仍然命中（审计实测的阻断：drift 要逐字 `=='是'`，而 §3 要求
    #    同格补理由并标 ⚠ ⇒ 两套语法互斥，D4 永远是死的、而且死得没声音）。这里用**夹具自带那份**：
    #    它由 `intake.py build` 出骨架 + AI 四列（`intakeize`），㊴ 另证它过 `intake.py check`——
    #    也就是说"合规"与"判据活着"这两件事在同一份产物上同时成立。
    rc, out = run([sys.executable, str(DRIFT), 'build', str(root / 'flowtable.md'),
                   '--ledger', str(root / 'evidence.json'), '--recon', str(root / 'recon.md'),
                   '--intake', str(root / 'intake.md'), '-o', str(root / 'd-ok.md'), '--force'])
    d_ok = (root / 'd-ok.md').read_text(encoding='utf-8') if (root / 'd-ok.md').exists() else ''
    cards = (root / 'intake.md').read_text(encoding='utf-8')
    cases.append(('㉟ D4 在合规 intake（含流程=`是 ⚠ 理由`）上仍命中（语法取前缀，不取逐字）',
                  rc == 0 and '是 ⚠' in cards and 'D4 含流程的材料零引用' in d_ok, rc, d_ok[:200]))

    # ㊱ `check` 少了账里记着的输入 ⇒ 退 1（审计实测的阻断：五条判据全关也照样打印"没有漏在账外"）
    rc, out = run([sys.executable, str(DRIFT), 'check', str(root / 'd-ok.md'),
                   '--flowtable', str(root / 'flowtable.md')])
    cases.append(('㊱ check 少了账里记着的 --ledger → 退 1（不许当橡皮图章）',
                  rc == 1 and '静默少跑' in out, rc, out[-200:]))

    # ㊲ 事实变了 ⇒ 该命中在账外（键含「事实」）：把节点依据换成视觉推断的证据——正是 D1 要防的那件事
    swapped = (root / 'flowtable.md').read_text(encoding='utf-8').replace('`M01#p001`', '`M07#p001`')
    (root / 'swapped.md').write_text(swapped, encoding='utf-8', newline='\n')
    rc, out = run([sys.executable, str(DRIFT), 'build', str(root / 'swapped.md'),
                   '--ledger', str(root / 'evidence.json'), '--recon', str(root / 'recon.md'),
                   '--intake', str(root / 'intake.md'), '-o', str(root / 'd-swap.md'), '--force'])
    d_swap = (root / 'd-swap.md').read_text(encoding='utf-8') if (root / 'd-swap.md').exists() else ''
    stale = fill(d_swap).replace('节点 02 | `M01#p001`', '节点 02 | `M07#p001`')   # 事实被手改回旧值
    rc, out = run([sys.executable, str(DRIFT), 'check', str(root / 'd-swap.md'),
                   '--flowtable', str(root / 'swapped.md'), '--ledger', str(root / 'evidence.json'),
                   '--recon', str(root / 'recon.md'), '--intake', str(root / 'intake.md')])
    cases.append(('㊲ 表里换了成因 ⇒ 旧账不再覆盖（键含「事实」）', 'D1' in d_swap, rc, d_swap[:200]))
    return cases


def intake_paths(root):
    """清点链 3 条路径（§8 里那三行原先都写着"未进验收路径"，这笔账在这里结清）。

    **正例是必须的**：只测反例时，"`check` 永远退 1"也能全绿——㉝ 原先就是这样（`rc_ok` 算出来只打印、
    不作判据，于是"合规的 recon.md 到底过不过"没人管）。
    """
    cards = (root / 'intake.md').read_text(encoding='utf-8')
    led = str(root / 'evidence.json')
    cases = []
    rc, out = run([sys.executable, str(INTAKE_CMD), 'check', str(root / 'intake.md'), '--ledger', led])
    cases.append(('㊴ intake 正例：`build` 骨架 + AI 四列 ⇒ 过 `check`（材料一一对应 / 档位与读不动逐字 / '
                  '双向一致 / 推断留痕）', rc == 0 and '✓' in out, rc, out[-200:]))
    tampered = (
        ('改档位', cards.replace('| T1 | ⚠ 项目背景 |', '| T2 | ⚠ 项目背景 |'), '档位'),
        ('断双向一致', cards.replace('| 是 ⚠ 有审批步骤 | 互补(M05) |', '| 是 ⚠ 有审批步骤 | 独立 |'),
         '双向一致'),
        ('少一行', '\n'.join(x for x in cards.splitlines() if not x.startswith('| `M07`')) + '\n',
         '卡片里没有'),
    )
    bad = []
    for name, text, want in tampered:
        f = root / 'i-tamper.md'
        f.write_text(text, encoding='utf-8', newline='\n')
        rc2, out2 = run([sys.executable, str(INTAKE_CMD), 'check', str(f), '--ledger', led])
        if not (rc2 == 1 and want in out2):
            bad.append(f'{name}(rc={rc2})')
    cases.append(('㊵ intake 反例：改档位 / 断双向一致 / 少一行 ⇒ 各退 1 且说清哪一条',
                  not bad, 1, '；'.join(bad)))
    return cases


def spec_paths():
    """规范 ↔ 仪器（㊶）：**本文里的列模板必须逐字等于仪器列规范**。

    为什么值得一条路径：列规范漂了**不会报错**，只会在别人照着规范写产物时被 `check` 退 2
    （本轮实测漂了两处：§5.3 的缺口表只有 6 列而 `GAP_COLUMNS` 是 7 列；§1.5 的示例表只有 6 列
    而 `CARD_COLUMNS` 是 12 列）。规范自称"唯一出处"，那它自己的模板就得能被机器核。
    """
    sys.path.insert(0, str(REPO / 'scripts'))
    import drift
    import intake
    import plan
    import recon
    spec = SPEC.read_text(encoding='utf-8')
    want = (('drift.DRIFT_COLUMNS', drift.DRIFT_COLUMNS), ('drift.GAP_COLUMNS', drift.GAP_COLUMNS),
            ('drift.READOUT_COLUMNS', drift.READOUT_COLUMNS),
            ('intake.COLUMNS', intake.COLUMNS), ('recon.CARD_COLUMNS', recon.CARD_COLUMNS),
            ('plan.FLOW_COLUMNS', plan.FLOW_COLUMNS), ('plan.ASK_COLUMNS', plan.ASK_COLUMNS),
            ('plan.EXCL_COLUMNS', plan.EXCL_COLUMNS))
    missing = [name for name, cols in want if '| ' + ' | '.join(cols) + ' |' not in spec]
    return [('㊶ 规范 ↔ 仪器：§1.5 / §3 / §4.1 / §5.3 / §5.4 / §5.6 的表头逐字等于仪器列规范',
             not missing, 0, ('PIPELINE-SPEC 里找不到：' + '、'.join(missing)) if missing else '')]


def plan_paths(root):
    """L2 计划链 3 条路径：机器列（种子 / 强合并 / 排除清单）· 收口后过 `check` · 反例十一连。

    这是 `PIPELINE-SPEC` §4 的仪器：§4.4 的两条可机器核（材料集都在清点里 · 流程数 = 目录数）
    外加"`待澄清` 必须有账"——**那条正是 §5.4 收敛口径里的"澄清申请"**，以前它没有仪器。
    """
    cards = (root / 'intake.md').read_text(encoding='utf-8')
    plan_file = root / 'plan.md'
    cases = []
    rc, out = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake.md'),
                   '-o', str(plan_file)])
    draft = plan_file.read_text(encoding='utf-8') if plan_file.exists() else ''
    # 机器列：F## 按"材料集里最小 M##"排 · 互补的两份**并成一条** · 排除清单 = 「含流程 = 否」·
    # 澄清申请种子 = 版本关系 `不确定` 的那份
    f_rows = [l for l in draft.splitlines() if l.startswith('| `F')]
    ok = (rc == 0 and len(f_rows) == 4 and '`M04`、`M05`' in f_rows[1] and '`M02`' in f_rows[0]
          and draft.count('\n| `M') == 2 and '| `M01` |' in draft and '无过程步骤' in draft
          and '| `Q01` | — | — | `M07` |' in draft)
    cases.append(('㊸ plan：机器列（种子 / 强合并 / `F##` 排序 / 排除清单 / 澄清种子）', ok, rc,
                  (out[-200:] + draft[:300]) if not ok else ''))
    # 收口：填表头那两格（§4.0 主体 / 目的，**先问用户**）+ AI 那几列
    draft = draft.replace('> **本任务**：主体 = — · 目的 = — · 材料根 = —',
                          '> **本任务**：主体 = 夹具的两个甲方 · 目的 = 漂移判据的夹具（不是真图） · 材料根 = 临时夹具目录')
    ai = {'F01': ('资质审查', '主', '—', '—', '`G1`', ''), 'F02': ('采购申请', '主', '—', '—', '`G1`', ''),
          'F03': ('结算付款', '子', '`F02`#03', '接力(`F01`)', '`G2`', ''),
          'F04': ('白板流程', '主', '—', '—', '`G2`', '')}
    lines = []
    for line in draft.splitlines():
        if line.startswith('| `F'):
            c = [x.strip() for x in line.strip().strip('|').split('|')]
            fid = c[0].split('`')[1]
            name, role, mount, rel, grp, _ = ai[fid]
            c[0], c[1], c[2], c[4], c[5] = f'`{fid}` {name}', role, mount, rel, grp
            # 列序见 `plan.FLOW_COLUMNS`（**8 列**：2026-09-19 起多了「合并/拆分理由」，状态退到 `c[7]`）
            c[7] = '待澄清' if name == '白板流程' else ('可落表' if c[7] == '—' else c[7])
            line = '| ' + ' | '.join(c) + ' |'
        elif line.startswith('| `Q01`'):
            line = '| `Q01` | 白板与合订本哪份算数？ | 取合订本 | `M07` |'
        lines.append(line)
    filled = '\n'.join(lines) + '\n'
    (root / 'plan-ok.md').write_text(filled, encoding='utf-8', newline='\n')
    rc, out = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                   '--intake', str(root / 'intake.md')])
    cases.append(('㊹ plan 正例：收口后过 `check`（§4.4 ① · 排除清单双向 · `待澄清` 有账）',
                  rc == 0 and '✓' in out, rc, out[-200:]))
    # 反例十一连：每条只错一处，都必须被抓住（rc 1 = 计划有问题 / 2 = 表头坏了，仪器故障）
    ex_rows = [l for l in filled.splitlines() if l.startswith('| `M')]
    negs = (('材料集造材料', filled.replace('`M04`、`M05`', '`M04`、`M99`'), 1),
            ('不确定没标待澄清', filled.replace('| 待澄清 |', '| 可落表 |'), 1),
            ('排除清单少一条',
             '\n'.join(x for x in filled.splitlines() if not x.startswith('| `M03`')) + '\n', 1),
            ('共享是空话', filled.replace('接力(`F01`)', '共享(M03)'), 1),
            ('接力与同组并存', filled.replace('接力(`F01`)', '接力(`F04`)'), 1),
            ('并行组写歪', filled.replace('| `G1` |', '| 第一组 |'), 1),
            ('接力指向不存在', filled.replace('接力(`F01`)', '接力(`F09`)'), 1),
            ('挂在指向不存在', filled.replace('`F02`#03', '`F09`#03'), 1),
            # §4.0：**主体 / 目的没填就没澄清，不许开工**
            ('表头没澄清', filled.replace('主体 = 夹具的两个甲方 · 目的 = 漂移判据的夹具（不是真图） · 材料根 = 临时夹具目录',
                                          '主体 = — · 目的 = — · 材料根 = —'), 1),
            # §4.1③ 第二支：含流程的材料不许静默塞进排除清单（要么进流程，要么写明「范围外…」）
            ('含流程的塞进排除清单',
             filled.replace(ex_rows[-1], ex_rows[-1] + '\n| `M02` | 看着不像流程 |'), 1),
            ('表头坏', filled.replace('| 流程 | 角色 |', '| 流程 | 角色X |'), 2))
    bad = []
    for name, text, want in negs:
        (root / 'plan-bad.md').write_text(text, encoding='utf-8', newline='\n')
        rc2, out2 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-bad.md'),
                         '--intake', str(root / 'intake.md')])
        if rc2 != want:
            bad.append(f'{name}(rc={rc2}≠{want})')
    cases.append(('㊺ plan 反例十一连：造材料 / 不确定不标 / 排除漏项 / 共享空话 / 接力撞并行组 / '
                  '组名歪 / 接力悬空 / 挂在悬空 / **表头没澄清** / **含流程的塞进排除清单** / 表头坏',
                  not bad, 1, '；'.join(bad)))
    # §4.4 ②：流程数 = `<流程名>/` 目录数（少一个要报，补齐后要过）
    #    2026-09-18 校准：**只对「可落表」的流程要求目录**——`白板流程` 的状态是 `待澄清`
    #    （材料 `不确定`），而 §5.4 的收敛口径要 `待澄清` = 0，也就是说它**还不该落表**；
    #    一边要它零条、一边要它的目录，是两句互相打架的话（真根上跑出来的）。
    dirs = root / 'plan-dirs'
    for n in ('资质审查', '采购申请'):
        (dirs / n).mkdir(parents=True, exist_ok=True)
    rc1, out1 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(dirs)])
    (dirs / '结算付款').mkdir(exist_ok=True)
    rc2, out2 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(dirs)])
    cases.append(('㊻ §4.4 ②：3 条「可落表」的流程只做出 2 个目录 ⇒ 退 1 并点名缺哪条；补齐 ⇒ 退 0 · '
                  '**`待澄清` 的流程不要求目录**（它还落不了表）',
                  rc1 == 1 and '结算付款' in out1 and rc2 == 0, rc1, (out1[-200:] + out2[-160:])))

    # ㊼ 清点里「含流程 = 不确定」的材料**必须有人问**（真材料集上现形的那条：5 份读不动的材料
    #    既不是流程、也不在排除清单里，计划里一份都没出现，而谁也没注意到少了 5 份）。
    #    断言两半：`build` 要**给它种一条澄清申请**（机器列），`check` 要**抓住没账的那种计划**。
    (root / 'intake-unsure.md').write_text(
        cards.replace('是 ⚠ 含资质审查步骤（待视觉）', '不确定 ⚠ 缺 OCR，判不出有没有步骤'),
        encoding='utf-8', newline='\n')
    rc1, out1 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                     '--intake', str(root / 'intake-unsure.md')])
    rc2, out2 = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake-unsure.md'),
                     '-o', str(root / 'plan-u.md')])
    d_u = (root / 'plan-u.md').read_text(encoding='utf-8') if (root / 'plan-u.md').exists() else ''
    seeded = [l for l in d_u.splitlines() if l.startswith('| `Q') and '`M02`' in l]
    # 反向那一半：**给它补一条指向 M02 的澄清申请之后，这条错必须消失**
    # （少了这半，规则写成"只要有不确定材料就报"也能过——真材料集上就这么错过一次）。
    q_rows = [l for l in filled.splitlines() if l.startswith('| `Q')]
    with_q = filled.replace(q_rows[-1], q_rows[-1] + '\n| `Q05` | 这两份哪份算数？ | 取 M02 | `M02` |')
    (root / 'plan-q.md').write_text(with_q, encoding='utf-8', newline='\n')
    rc3, out3 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-q.md'),
                     '--intake', str(root / 'intake-unsure.md')])
    cases.append(('㊼ 「含流程 = 不确定」的材料：`build` 给它种澄清申请 · `check` 抓住"没账"的计划 · '
                  '补上账之后必须过', rc1 == 1 and '会静默消失' in out1 and rc2 == 0 and bool(seeded)
                  and rc3 == 0, rc1,
                  (out1[-160:] + str(seeded) + out3[-160:]) if not (rc3 == 0 and seeded) else ''))

    # ㊽ `--scope` + `--split`：**AI 的拆解落成结构化产物**（行集合由它定，落笔由脚本做）。
    # 为什么值得一条路径：在那之前，"合并 / 移出范围 / 加一条澄清"只能靠 AI 手改 markdown 表格
    # （行集合一改，列数、编号、双向引用全靠人保证）；真材料集上就是这么踩的。
    scope = {'主体': '夹具的两个甲方', '目的': '夹具：验证拆解接口', '材料根': '临时夹具目录'}
    # 夹具里「含流程 = 是」的是 M02/M04/M05/M06/M07（M07 的**版本关系**是 `不确定` ⇒ 它所在流程
    # 状态必须是 `待澄清`，且澄清申请要有账——两条都由 `check` 核）。
    split = {'流程': [{'材料集': ['M02', 'M04', 'M05', 'M06', 'M07'], '名': '夹具流程', '角色': '主',
                     '挂在': '—', '与其它流程': '—', '并行组': '`G1`',
                     # 五份并成一条：**这不是机器种子里的任何一组** ⇒ 理由必须写（§4.1 ①）
                     '合并/拆分理由': '五份讲的是同一条链（夹具）', '状态': '待澄清'}],
             '范围外': [],
             # `注记` = **AI 判断的落点**（§0.1 / §4.1 ②：这类判断不许写成澄清申请的问句）
             '注记': ['白板那条子流程本次不拆：材料只够画主干'],
             '澄清': [{'问题': '白板与合订本哪份算数？', '推荐答案': '取合订本', '指向': '`M07`'}]}
    (root / 'scope.json').write_text(json.dumps(scope, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8', newline='\n')
    (root / 'split.json').write_text(json.dumps(split, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8', newline='\n')
    rc1, out1 = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake.md'),
                     '-o', str(root / 'plan-split.md'), '--scope', str(root / 'scope.json'),
                     '--split', str(root / 'split.json')])
    d_sp = (root / 'plan-split.md').read_text(encoding='utf-8') if (root / 'plan-split.md').exists() else ''
    rc2, out2 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-split.md'),
                     '--intake', str(root / 'intake.md')])
    ok_split = (rc1 == 0 and '| `F01` 夹具流程 | 主 | — | `M02`、`M04`、`M05`、`M06`、`M07` | — | `G1` '
                '| 五份讲的是同一条链（夹具） | 待澄清 |' in d_sp and '主体 = 夹具的两个甲方' in d_sp
                and '⚠ **AI 判断**：白板那条子流程本次不拆' in d_sp and rc2 == 0)
    bad_split = dict(split)
    bad_split['流程'] = [dict(split['流程'][0], 材料集=['M02', 'M04'])]     # M05 / M06 / M07 没了下落
    (root / 'split-bad.json').write_text(json.dumps(bad_split, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8', newline='\n')
    before = ((root / 'plan-split.md').read_bytes() if (root / 'plan-split.md').exists() else b'')
    rc3, out3 = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake.md'),
                     '-o', str(root / 'plan-split.md'), '--force', '--scope', str(root / 'scope.json'),
                     '--split', str(root / 'split-bad.json')])
    frow = next((ln for ln in d_sp.splitlines() if ln.startswith('| `F')), '（没有流程行）')
    cases.append(('㊽ plan `--scope` / `--split`：拆解落成 JSON（行集合由它定、落笔由脚本做）· '
                  '**漏一份「含流程 = 是」的材料 ⇒ 退 2 且不写盘**',
                  ok_split and rc3 == 2 and '静默消失' in out3
                  and (root / 'plan-split.md').read_bytes() == before,
                  rc1, (out1[-200:] + frow + out2[-260:] + out3[-200:]) if not ok_split else ''))
    # 56 plan 的三处口径（2026-09-18 端到端跑真根时现形的三条，都已修）：
    #    ① 成果根里的**辅助目录**（`render_pages.py` 的 `shots/`）不算"流程目录"——它没有流程表；
    #    ② `待澄清` 的流程**不要求**目录（§5.4 要它零条 = 它还不该落表，两句不能互相打架）；
    #    ③ 表头三格**按字段名取值**：真样本用 `；` 分隔、夹着散文；缺哪一格就点哪一格的名。
    (root / 'shots').mkdir(exist_ok=True)
    (root / 'shots' / 'M13-p001.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16)
    rc1, out1 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-split.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(root)])
    txt = (root / 'plan-split.md').read_text(encoding='utf-8')
    prose = ('> **本任务**：主体 = 甲（…）× 乙（…）的 **合作链**；材料包里属「丙」体系的模板按 §4.0 '
             '移出本次范围 · 目的 = **合作全貌** + **SOP 落地**；先出全貌，再挑一条细化 · 材料根 = `D:\\材料包`')
    (root / 'plan-prose.md').write_text(re.sub(r'^> \*\*本任务\*\*：.*$', prose, txt, count=1, flags=re.M),
                                        encoding='utf-8', newline='\n')
    rc2, out2 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-prose.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(root)])
    (root / 'plan-noroot.md').write_text(
        re.sub(r'^> \*\*本任务\*\*：.*$', prose.replace(' · 材料根 = `D:\\材料包`', ''), txt, count=1, flags=re.M),
        encoding='utf-8', newline='\n')
    rc3, out3 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-noroot.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(root)])
    ok56 = (rc1 == 0 and 'shots' not in out1 and '还没有目录' not in out1
            and rc2 == 0 and '主体 = 甲' in (root / 'plan-prose.md').read_text(encoding='utf-8')
            and rc3 == 1 and '缺 材料根' in out3)
    cases.append(('56 plan 的三处口径：辅助目录（`shots/`）不算流程目录 · `待澄清` 的流程不要求目录 · '
                  '表头三格按**字段名**取值（`；` + 散文照样认）且缺哪格点哪格',
                  ok56, rc1, (out1[-200:] + out2[-200:] + out3[-260:]) if not ok56 else ''))
    # 63 「合并/拆分理由」（D-111）：并 / 拆是 **AI 的判断** ⇒ 材料集不是机器种子那一组的，必须写一句。
    #    **两个入口都要有牙**：`build --split` 那个是"当初那个决定"，`check` 那个是"手改之后还作不作数"——
    #    只装在一个入口上，另一条路就漏（本仓踩过同一形状）。
    nope = {'流程': [{k: v for k, v in split['流程'][0].items() if k != '合并/拆分理由'}],
            '范围外': [], '澄清': split['澄清'], '注记': split['注记']}
    (root / 'split-noreason.json').write_text(json.dumps(nope, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8', newline='\n')
    rc_nr, out_nr = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake.md'),
                         '-o', str(root / 'plan-nr.md'), '--scope', str(root / 'scope.json'),
                         '--split', str(root / 'split-noreason.json')])
    (root / 'plan-erased.md').write_text(
        txt.replace('| 五份讲的是同一条链（夹具） |', '| — |'), encoding='utf-8', newline='\n')
    rc_er, out_er = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-erased.md'),
                         '--intake', str(root / 'intake.md')])
    # 机器那一组（单份 / 强合并）**不要求**理由：正例就是夹具 ㊹ 那份（它的四行全是机器种子）
    ok63 = (rc_nr == 2 and '合并/拆分理由' in out_nr and not (root / 'plan-nr.md').exists()
            and rc_er == 1 and '合并/拆分理由' in out_er)
    cases.append(('63 「合并/拆分理由」：AI 并/拆出来的流程（材料集不是机器那一组）必须写一句——'
                  '`--split` 时退 2 不写盘 · 手改 plan.md 抹掉它 `check` 退 1；机器那一组不要求',
                  ok63, (rc_nr, rc_er), (out_nr[-200:] + out_er[-240:]) if not ok63 else ''))
    # 57 外部表的**五种真实形态**（2026-09-18 用它们撞过 `import_table`，四处修 + 两处判定"不该硬转"）：
    #    ① 英文表头 + 英文类型值 ② 一行一分支（同编号多行）③ 中文点号编号 + 裸编号引用
    #    ④ 字母编号 ⇒ **不改节点身份、报清楚**（H3：有些形态不该由它硬转）
    imp_d = root / 'imports5'
    imp_d.mkdir(exist_ok=True)
    shapes = {
        'en.md': ('| Step | Node Name | Type | Owner | Next |\n| --- | --- | --- | --- | --- |\n'
                  '| 1 | 提交申请 | Start | 申请人 | 2 |\n| 2 | 资料齐全? | Decision | 窗口 | 齐全->3<br>不齐->4 |\n'
                  '| 3 | 科室审核 | Task | 科长 | 5 |\n| 4 | 补正材料 | Task | 申请人 | 2 |\n'
                  '| 5 | 归档 | End | 档案室 | — |\n'),
        'rows.md': ('| 序号 | 节点名称 | 节点类型 | 下个节点 |\n| --- | --- | --- | --- |\n'
                    '| 01 | 提交 | 开始 | →02 |\n| 02 | 超限? | 判断 | 超限→回 03 |\n'
                    '| 02 | 超限? | 判断 | 未超→04 |\n| 03 | 招标 | 任务 | →04 |\n'
                    '| 04 | 归档 | 结束 | — |\n'),
        'dot.md': ('| 序号 | 处理步骤 | 下一步 |\n| --- | --- | --- |\n'
                   '| 1. | 受理 | 2. |\n| 2. | 判定 | 3. / 4. |\n| 3. | 排查 | 5. |\n'
                   '| 4. | 协商 | 5. |\n| 5. | 关闭 | — |\n'),
        'letter.md': ('| 编号 | 环节 | 流转 |\n| --- | --- | --- |\n| A | 收草案 | →B |\n| B | 法务评审 | →C |\n'),
    }
    for name, text in shapes.items():
        (imp_d / name).write_text('# 外部表\n\n' + text, encoding='utf-8', newline='\n')
    got = {}
    for name in shapes:
        rc_i, out_i = run([sys.executable, str(IMPORT_CMD), str(imp_d / name),
                           '-o', str(imp_d / ('out-' + name))])
        body_i = (imp_d / ('out-' + name)).read_text(encoding='utf-8') if (imp_d / ('out-' + name)).exists() else ''
        rc_c, _out_c = (run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check',
                             str(imp_d / ('out-' + name))]) if body_i else (1, ''))
        got[name] = (rc_i, out_i, body_i, rc_c)
    ok57 = (got['en.md'][0] == 0 and got['en.md'][3] == 0                 # 英文表头 → 直接过契约校验
            and '齐全→03 ｜ 不齐→04' in got['en.md'][2]
            and got['rows.md'][0] == 0 and got['rows.md'][3] == 0         # 一行一分支 ⇒ 合并
            and '超限→回 03 ｜ 未超→04' in got['rows.md'][2]
            and got['dot.md'][0] == 0                                     # `1.` → `01`、`3. / 4.` → `→03 ｜ →04`
            and '| 01 | 受理' in got['dot.md'][2] and '→03 ｜ →04' in got['dot.md'][2]
            and got['letter.md'][0] == 1 and '不改节点身份' in got['letter.md'][1])
    cases.append(('57 外部表五种真实形态：英文表头 / 一行一分支（合并） / 中文点号编号+裸编号引用 ⇒ 都能过契约校验；'
                  '**字母编号 ⇒ 退 1 并说清"不改节点身份"**（不硬转）',
                  ok57, got['en.md'][0],
                  '；'.join(f'{k}: import={v[0]} check={v[3]}' for k, v in got.items()) if not ok57 else ''))
    return cases


def query_run(root, *args):
    """跑一条 `query.py`（账本固定用夹具那份）。"""
    return run([sys.executable, str(QUERY), str(root / 'evidence.json'), *args])


def query_paths(root):
    """点名取子集的 8 条路径：分批 + 游标 · 续批 · 行区间 · 关键词 · 只裁显示 · 语法错 · 喂错形态 ·
    **页码 / 子表名两个坐标的正例**（⑩—⑯ + ㊷）。"""
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
    cases.append(('⑭ 只给 rows= 不许把命中筛成 0（它只管显示）', rc == 0 and '命中 59 条' in out, rc, out))
    rc, out = query_run(root, '--range', 'pages=9-1')
    cases.append(('⑮ 范围语法错 → 退 2 + 人话', rc == 2 and '上界小于下界' in out, rc, out))
    rc, out = run([sys.executable, str(QUERY), str(root / 'intake.md')])
    cases.append(('⑯ 喂错形态（不是账本）→ 退 2 + 人话', rc == 2 and '合法 JSON' in out, rc, out))

    # ㊷ 坐标**正例**：`pages=` 按 `location.page` 取（闭区间）· `sheet=` 按子表名逐字取。
    #    原先夹具里 `page` / `sheet` 全是 `None`，于是这两支**整段删掉也全绿**——门⑪ 对它们没有牙。
    rc, out = query_run(root, '--material', 'M06', '--range', 'pages=2-3', '--batch', '5')
    rc2, out2 = query_run(root, '--range', 'sheet=短名单', '--batch', '5')
    ok = (rc == 0 and '命中 2 条' in out and 'M06#p002' in out and 'M06#p003' in out
          and 'M06#p001' not in out
          and rc2 == 0 and '命中 1 条' in out2 and 'M03#p001' in out2)
    cases.append(('㊷ 坐标正例：`pages=` 按页码取（闭区间、越界不含）· `sheet=` 按子表名取', ok, rc,
                  (out[-160:] + out2[-160:]) if not ok else ''))

    # ㊸ 「没给」与「给了 0」是两回事。2026-09-19 修掉的一处静默默认：`batch = a.batch or th['batch']`
    #    会把 `--batch 0` 悄悄换成默认 20，于是紧跟其后的 `if batch <= 0` **永远轮不到**——
    #    点名取子集自己的规则是"语法错不猜"（§5.3），而它当时正在猜。
    rc1, out1 = query_run(root, '--batch', '0')
    rc2, out2 = query_run(root, '--chars', '0')
    cases.append(('58 `--batch 0` / `--chars 0` 不许被当成"没给"（静默取默认）⇒ 退 2、说人话',
                  rc1 == 2 and rc2 == 2 and '要比 0 大' in out1 and '要比 0 大' in out2,
                  (rc1, rc2), (out1 if rc1 != 2 else out2)[-200:]))
    return cases


def capability_paths(root):
    """能力指纹的三条路径（㊽—㊿，§1.2）：新账本有章 · 章与现算一致 · 篡改 / 缺章 ⇒ `check` 退 2 ·
    **消费端只喊不拦**且不破坏 `--json`。

    夹具**自己算的那个数不许手写**：期望值来自 `capability.py --json`（产品接口），
    手抄一个 sha 进夹具就等于抄一份会漂的真值。
    """
    cases = []
    cap = REPO / 'scripts' / 'capability.py'
    rc_now, out_now = run([sys.executable, str(cap), '--json'])
    try:
        want = json.loads(out_now.strip().splitlines()[-1])
    except (ValueError, IndexError):
        want = {}
    led = json.loads((root / 'evidence.json').read_text(encoding='utf-8'))
    got = led.get('capability') or {}
    # 两份**副本**（原账本后面几条路径还要用）：一份章对不上，一份干脆没章
    tam = root / 'evidence.tampered.json'
    tam.write_text(json.dumps(dict(led, capability={'code': 'deadbeef0000',
                                                    'rules': got.get('rules') or '000000000000'}),
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    no = root / 'evidence.nostamp.json'
    no.write_text(json.dumps({k: v for k, v in led.items() if k != 'capability'},
                             ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    rc_ok, out_ok = run([sys.executable, str(cap), 'check', str(root / 'evidence.json')])
    rc_bad, out_bad = run([sys.executable, str(cap), 'check', str(tam), str(no)])
    ok = (rc_now == 0 and set(got) == {'code', 'rules'} and got == want
          and rc_ok == 0 and '与当下同版' in out_ok
          and rc_bad == 2 and '机制变了' in out_bad and '没盖章' in out_bad)
    cases.append(('59 账本盖了能力指纹且与现算一致（`code` / `rules` 两个分开）· 篡改 ⇒ 退 2 · '
                  '**缺章也算对不上**（"不知道是哪版产的"不能用）',
                  ok, (rc_now, rc_ok, rc_bad), (out_bad or out_ok)[-240:] if not ok else ''))

    # 消费端：**只喊不拦**——退 0（拦着读等于不让人取证），但话要说在最前面；
    # `--json` 时**不许往 stdout 插行**（吃这份 JSON 的子代理会当场解析失败），状态进字段。
    rc_q1, out_q1 = run([sys.executable, str(QUERY), str(tam), '--batch', '1'])
    rc_q2, out_q2 = run([sys.executable, str(QUERY), str(tam), '--batch', '1', '--json'])
    try:
        payload = json.loads(out_q2)
    except ValueError:
        payload = {}
    who = payload.get('capability') or {}
    ok = (rc_q1 == 0 and '能力指纹' in out_q1 and out_q1.index('能力指纹') < out_q1.index('取子集')
          and rc_q2 == 0 and who.get('state') == 'drift' and payload.get('rows'))
    cases.append(('60 消费端只喊不拦：旧账本照样读得出来（退 0），提醒打在最前面；`--json` 里进 '
                  '`capability` 字段（插一行会毁掉那份 JSON）',
                  ok, (rc_q1, rc_q2), (out_q1[:200] + out_q2[-200:]) if not ok else ''))

    # 计划那一侧同理：`plan.md` 的表头带一行机制指纹，`plan.py check` 核它。
    # **另起一份文件名**（`plan-cap.md`）：`plan_paths` 已经写过 `plan.md` 并靠它做断言，
    # 这里覆盖它会把那条路径的现场搅掉（夹具之间的隐式耦合正是最难查的一类红）。
    cap_plan = root / 'plan-cap.md'
    rc_plan, out_plan = run([sys.executable, str(PLAN_CMD), 'build', str(root / 'intake.md'),
                             '-o', str(cap_plan)])
    plan_text = cap_plan.read_text(encoding='utf-8') if cap_plan.exists() else ''
    rc_pc, out_pc = run([sys.executable, str(PLAN_CMD), 'check', str(cap_plan),
                         '--intake', str(root / 'intake.md')])
    stamped = [ln for ln in plan_text.splitlines() if ln.startswith('> 机制指纹：')]
    cases.append(('61 计划的表头带机制指纹（写与读同一句）· `plan.py check` 认得它、不因此告警',
                  rc_plan == 0 and len(stamped) == 1 and want.get('code', 'x') in stamped[0]
                  and rc_pc in (0, 1) and '能力指纹' not in out_pc,
                  (rc_plan, rc_pc), (out_plan + out_pc)[-240:] if not stamped else ''))
    return cases


def make_deck(path):
    """造一份**最小可读的 .pptx**：确切部件 `ppt/presentation.xml` + 每张一行标题一行正文，
    **最后再放一张纯图片页**（没有任何 `<a:t>`）。

    为什么要有那张图片页：真稿实测（`西门子 S7-1200 …V3.0.pptx`，19 张）里有 3 张是纯图片——
    原先被抽成 `text: ""` 的空 element：既占着账本，又让"19 张都进来了"这句话变成假的。
    **空元素不是证据**，这条现在钉在这里。
    """
    p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/presentation.xml', f'<p:presentation xmlns:p="{p}"/>')
        for i, title in enumerate(DECK_TITLES, 1):
            # 标题段落里**故意放一个制表位**（`<a:tabLst>` / `<a:tab pos=…>`，真稿常见）：
            # 它是 `<a:t` 前缀家族的标签，正则写松了就会被当开标签、把原始 XML 吃进正文。
            z.writestr(f'ppt/slides/slide{i}.xml',
                       f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>'
                       f'<a:p><a:pPr><a:tabLst><a:tab pos="914400" algn="l"/></a:tabLst></a:pPr>'
                       f'<a:r><a:t>{title}</a:t></a:r></a:p>'
                       f'<a:p><a:r><a:t>正文 {i}：审批流程第 {i} 步</a:t></a:r></a:p>'
                       f'</p:spTree></p:cSld></p:sld>')
        n = len(DECK_TITLES) + 1
        z.writestr(f'ppt/slides/slide{n}.xml',
                   f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree>'
                   f'<p:pic><p:nvPicPr><p:cNvPr id="9" name="整页截图"/></p:nvPicPr></p:pic>'
                   f'</p:spTree></p:cSld></p:sld>')
        # **幻灯片之外装着文字的部件**（图表 / SmartArt / 备注页）：本读者不读它们，
        # 但必须**报出来**——静默漏掉是 §2.4 明令不许的（真稿复验时发现的缺口）。
        for part, word in (('ppt/charts/chart1.xml', DECK_OUTSIDE[0]),
                           ('ppt/diagrams/data1.xml', DECK_OUTSIDE[1]),
                           ('ppt/notesSlides/notesSlide1.xml', DECK_OUTSIDE[2])):
            z.writestr(part, f'<x xmlns:a="{a}"><a:p><a:r><a:t>{word}</a:t></a:r></a:p></x>')


def _broken_zip(path, bad_name):
    """打开一个 zip，但让**指定那一条**读的时候抛 `RuntimeError`（模拟加密条目 / 未知压缩法）。

    为什么要造这个桩：原实现要么让别的异常穿透出去（**整份材料被判读不动**、其余页文字一起丢），
    要么把 CRC 坏的页静默吞掉（**无声少一页**，摘要还写成"这份稿子本来就没文字"）。
    真实改法（改中央目录的加密位 / file_size）要动二进制，桩能测到同一条机制且更清楚。
    """
    class _Broken(zipfile.ZipFile):
        def read(self, name, *a, **k):
            if name == bad_name:
                raise RuntimeError('File is encrypted')
            return super().read(name, *a, **k)
    return _Broken(path)


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
    cases.append(('⑱ recon：出 pptx 摘要（张数 + 每张标题 + **点明纯图片页**）',
                  rc == 0 and f'幻灯片 {DECK_SLIDES} 张' in rec and DECK_TITLES[1] in rec
                  and '纯图片' in rec, rc, out + rec[:300]))
    rc, out = run([sys.executable, str(OOXML_CMD), '--materials', str(d / 'materials.json'),
                   '-o', str(d / 'elements.json'), '--max-slides', '9'])
    els = []
    if (d / 'elements.json').exists():
        try:
            els = json.loads((d / 'elements.json').read_text(encoding='utf-8'))
        except ValueError:
            els = []
    ok = (rc == 0 and len(els) == len(DECK_TITLES)          # 纯图片那张**不许**变成空元素
          and els[0].get('location', {}).get('page') == 1
          and DECK_TITLES[1] in els[1].get('text', '')
          and not any(not (e.get('text') or '').strip() for e in els)
          and not any('<a:' in str(e.get('text') or '') for e in els)   # **原始 XML 不许进正文**
          and '没有文字层' in (els[0].get('degraded') or '')
          and '本读者不读' in (els[0].get('degraded') or '')     # 图表/SmartArt/备注：报出来
          and not any(w in str(e.get('text') or '') for e in els for w in DECK_OUTSIDE))
    cases.append(('⑲ pptx 读者：按张出元素 + 页码坐标 + **纯图片页丢掉并记账** + '
                  '**原始 XML 不进正文** + **幻灯片外文字报出来**', ok, rc, out + str(els)[:300]))

    # ⑲b 单张读不动：**不许掀翻整份，也不许静默少一页**（拿桩把 zip 的一条读坏）
    sys.path.insert(0, str(REPO / 'scripts'))
    import pptx_text                                     # noqa: E402  （夹具内部用，测的是这条机制）
    with _broken_zip(d / '大演示稿.pptx', 'ppt/slides/slide2.xml') as z:
        got, failed = pptx_text._slides_from(z, 0)
    ok = (len(got) == DECK_SLIDES - 1 and len(failed) == 1 and failed[0][2] == 'RuntimeError')
    cases.append(('⑲b 单张读不动：不掀翻整份 + 逐页记账（原先是"穿透"或"静默消失"二选一）',
                  ok, 0, f'got={len(got)} failed={failed}'))
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


def _pdf_pages(page_texts):
    """**pdfplumber 读得动**的最小多页 PDF（带真 xref 表），每页一段 ASCII 正文。

    与 `_pdf_bytes` 分工：那个故意不带 xref（考"读不动的材料只影响它自己"），
    这个要能被真抽出来——**尺子二（文本层薄）只能在这种"抽得出来、但抽得太少"的材料上考**。
    """
    def esc(s):
        return s.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')

    n = len(page_texts)
    font_no = 3 + 2 * n
    objs = [b'<</Type/Catalog/Pages 2 0 R>>',
            ('<</Type/Pages/Kids[' + ' '.join(f'{3 + 2 * i} 0 R' for i in range(n))
             + f']/Count {n}>>').encode()]
    for i, txt in enumerate(page_texts):
        body = b'BT /F1 12 Tf 40 800 Td (' + esc(txt).encode('ascii', 'replace') + b') Tj ET'
        objs.append((f'<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]'
                     f'/Resources<</Font<</F1 {font_no} 0 R>>>>/Contents {4 + 2 * i} 0 R>>').encode())
        objs.append(b'<</Length ' + str(len(body)).encode() + b'>>stream\n' + body + b'\nendstream')
    objs.append(b'<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>')
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + o + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objs) + 1}\n'.encode() + b'0000000000 65535 f \n'
    for off in offsets:
        out += f'{off:010d} 00000 n \n'.encode()
    out += (f'trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n').encode()
    return bytes(out)


def _ole_bytes(stream):
    """假 OLE 字节，**带上真族标记**：`<流名>` 按 UTF-16LE 写进去（真 OLE 的目录就是这么存的）。

    为什么要造：真样本实测 `…告知函.wps`（WPS 产出）其实是 **Word 97-2003 族**（OLE 里有
    `WordDocument` 流），缺转换器时提示必须**指名族与另存目标**——泛泛说"另存为 OOXML"等于没说。
    `.wps` / `.dps` 这两个后缀在 `parse_legacy.OLE_EXT` 的**兜底表里根本没有**，所以它们只能靠
    "流名对上了"被认出来：这正是"按内容判、不按后缀判"（§1.2）最干净的一份样本。
    """
    return (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 64
            + stream.encode('utf-16-le') + b'\x00' * 64)


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
    | `p.doc` `r.wps` `s.dps` `t.xls` | 假 OLE：**三族各一份**，且 `.wps` / `.dps` 在兜底后缀表里没有 ⇒ 只能靠流名认（本机无转换器 ⇒ 记读不动 + 逐族指名另存目标） |
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
    # 假 OLE，三族各一份（**它们的后缀在 OLE_EXT 兜底表里都没有**，只能靠流名认出来）：
    # Word 族（`.doc` / WPS 的 `.wps`）· Excel 族（`.xls`）· PowerPoint 族（WPS 的 `.dps`）。
    (d / 'p.doc').write_bytes(_ole_bytes('WordDocument'))
    _unsized_xlsx(d / 'q.xlsx')                                           # 无 <dimension> 的流式表
    (d / 'r.wps').write_bytes(_ole_bytes('WordDocument'))                 # WPS 后缀，真样本就是这一族
    (d / 's.dps').write_bytes(_ole_bytes('PowerPoint Document'))
    (d / 't.xls').write_bytes(_ole_bytes('Workbook'))
    # `u.md`：**真 markdown 表格**——它的"结构缩样"会原样回显头几行，而那里全是 `|`。
    # 不转义就把侦查表那一行的列数撑破（`check` 报"仪器故障"），而真正的原因在材料正文里
    # （真实材料集实测：一份 `.md` 的缩样让整张侦查表读不了，2026-09-18）。
    (d / 'u.md').write_text('| 项目 | 值 |\n| --- | --- |\n| 直流容量 | 1MW |\n', encoding='utf-8')
    return d


def _fill_recon_card(text):
    """把侦查表的**四个 AI 列**填成合法值——经 `cells.fill` 按**列名**落笔（正式接口）。

    为什么不用字符串替换：审计里踩过一次——替换式填空"看着对"，但口径一歪就少一格，
    于是测的其实是"列数不对"而不是想测的那条判据。列序见 `recon.CARD_COLUMNS`（12 列）。
    """
    ans = {}
    for line in text.splitlines():
        if line.startswith('| `M'):
            ans[line.split('`')[1]] = {'假设角色': '⚠ 假设一句话', '依据': '依据 x',
                                       '验证方式': '读大纲', '状态': '待验'}
    new, errs = cells.fill(text, ans, RECON_MOD.TODO_TABLES)
    if errs:
        raise AssertionError(f'cells.fill 落了空：{errs}')
    return new


def import_paths(root):
    """外部节点表 → 契约流程表（P2）：**只做机械转换，语义留给 AI**。

    为什么值得一条路径：真材料集上那张 38 行（实为 43 行）的节点表是我**手写**转成 12 列的——
    列数、编号、`｜` 分支全靠人保证。这条路径钉住三件机械事：认列（同义词，**长者优先**）、
    规格化写法（`<br>` → `｜` · 类型同义词 → 四种 · 缺列留 `—`）、补 frontmatter 与主体配色；
    并与**手写版逐节点对账**（差异只允许出现在"AI 该做的那三件"上）。
    """
    d = root / 'imp'
    d.mkdir(exist_ok=True)
    src = d / '外部节点表.md'
    src.write_text(
        '# 外部节点表（夹具）\n\n'
        '| 环节 | 步骤号 | 事项 | 类型 | 责任方 | 岗位 | 时限 | 下一步 | 备注 |\n'
        '|---|---|---|---|---|---|---|---|---|\n'
        '| 受理 | 1 | 收件 | 起点 | 甲方 | 前台 | 1天 | 2 | 拿材料 → 出回执 |\n'
        '| 受理 | 2 | 分派？ | 决策 | 甲方 | 主管 | — | 是→3<br>否→4 | 按轻重缓急分派 |\n'
        '| 受理 | 3 | 快速通道 | 处理 | 乙方 | 专员 | 2天 | 5 | |\n'
        '| 受理 | 4 | 常规通道 | 处理 | 乙方 | 专员 | 5天 | 5 | |\n'
        '| 受理 | 5 | 归档 | 终点 | 甲方 | 档案 | — | — | |\n', encoding='utf-8')
    cases = []
    out_file = d / 'flowtable.md'
    rc, out = run([sys.executable, str(IMPORT_CMD), str(src), '-o', str(out_file),
                   '--id', 'importfix', '--title', '外部表导入夹具'])
    got = out_file.read_text(encoding='utf-8') if out_file.exists() else ''
    hdr = [ln for ln in got.splitlines() if ln.startswith('| 项目运作阶段')]
    n_cols = len(hdr[0].strip().strip('|').split('|')) if hdr else 0
    ok = (rc == 0 and n_cols == 12 and '| 开始 |' in got and '| 结束 |' in got
          and '是→03 ｜ 否→04' in got and '| 01 |' in got and '<br>' not in got and '拿材料 → 出回执' in got
          and '| 甲方 | #dae8fc |' in got and 'id: importfix' in got)
    cases.append(('㊾ import：外部表（同义词列 / `<br>` 分支 / 起点终点 / 备注列 / 缺 3 列）→ '
                  '12 列契约（类型归一 · `<br>`→`｜` · 备注进描述 · 缺列留 `—`）', ok, rc,
                  (out[-200:] + got[:200]) if not ok else ''))
    rc2, out2 = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check',
                     str(out_file)])
    cases.append(('㊿ import 的产物**过 H1—H9**（契约校验才是门；软提示允许）',
                  rc2 == 0 and '结构校验通过' in out2, rc2, out2[-200:]))
    # 反例：编号重复 / 表头认不出来 —— 都必须当场退 1（不是产出个坏表让别人去猜）
    dup = d / 'dup.md'
    dup.write_text('| 编号 | 名称 | 下一步 |\n|---|---|---|\n| 1 | 甲 | 2 |\n| 1 | 乙 | — |\n',
                   encoding='utf-8')
    rc3, out3 = run([sys.executable, str(IMPORT_CMD), str(dup), '-o', str(d / 'x.md')])
    blind = d / 'blind.md'
    blind.write_text('| 甲 | 乙 |\n|---|---|\n| 1 | 2 |\n', encoding='utf-8')
    rc4, out4 = run([sys.executable, str(IMPORT_CMD), str(blind), '-o', str(d / 'y.md')])
    cases.append(('㊿b import 反例：编号重复 ⇒ 退 1 · 表头认不出来 ⇒ 退 1（都不产出坏表）',
                  rc3 == 1 and '重复' in out3 and rc4 == 1 and '没认到节点表' in out4, rc3,
                  out3[-160:] + out4[-160:]))
    # 62 **表头不在第一行**（D-110）：顶上一行是分组标题。多行表头那类外部表里，"哪一行是列名"
    #    是**人的知识**——让脚本去猜就是赌（分组标题行里恰好有「序号 / 名称」时，它会被当成表头，
    #    真正的列名那行反而变成数据行）。所以给一只手：`--header-row N`（1 起，分隔行不计），
    #    并说清两种写歪：越界、那一行里认不出关键列。
    hdr_src = d / '外部表-两行表头.md'
    hdr_src.write_text(
        '# 两行表头夹具\n\n'
        # 第 1 行是**分组标题**，却恰好含「序号 / 名称」——认列式启发会被它骗：把它当表头，
        # 真列名那行（第 2 行）反而成了数据行。
        '| 序号 | 名称 | 名称 | 类型 | 责任方 | 岗位 | 时限 | 下一步 | 备注 |\n'
        '| 阶段 | 步骤号 | 事项 | 类型 | 责任方 | 岗位 | 时限 | 下一步 | 备注 |\n'
        '|---|---|---|---|---|---|---|---|---|\n'
        '| 受理 | 1 | 收件 | 起点 | 甲方 | 前台 | 1天 | 2 | 拿材料 → 出回执 |\n'
        '| 受理 | 2 | 归档 | 终点 | 甲方 | 档案 | — | — | |\n', encoding='utf-8')
    hdr_out = d / 'flowtable-hdr.md'
    rc5, out5 = run([sys.executable, str(IMPORT_CMD), str(hdr_src), '-o', str(hdr_out),
                     '--header-row', '2', '--id', 'hdr'])
    got5 = hdr_out.read_text(encoding='utf-8') if hdr_out.exists() else ''
    rc6, out6 = run([sys.executable, str(IMPORT_CMD), str(hdr_src), '-o', str(d / 'h9.md'),
                     '--header-row', '9'])
    # 「那一行里认不出关键列」要另起一张表：上面那张的第 1 行含「序号 / 名称」⇒ 它会**过**认列这一关，
    # 然后在编号重复那一关被拦（那是另一条路径，也合理，但不是这条要考的）
    grp_src = d / '外部表-分组行.md'
    grp_src.write_text(
        '# 分组行夹具\n\n'
        '| 受理环节 | 受理环节 | 审批 |\n'
        '| 阶段 | 步骤号 | 事项 | 类型 | 责任方 | 岗位 | 时限 | 下一步 | 备注 |\n'
        '|---|---|---|---|---|---|---|---|---|\n'
        '| 受理 | 1 | 收件 | 起点 | 甲方 | 前台 | 1天 | 2 | |\n', encoding='utf-8')
    rc7, out7 = run([sys.executable, str(IMPORT_CMD), str(grp_src), '-o', str(d / 'h1.md'),
                     '--header-row', '1'])
    ok = (rc5 == 0 and '| 01 |' in got5 and '| 02 |' in got5 and '收件' in got5
          and '事项→节点名称' in out5 and '步骤号→节点编号' in out5      # 认的是第 2 行那套列名
          and '序号' not in got5 and '步骤号' not in got5                # 分组行的文字不许进产物
          and rc6 == 1 and '越界' in out6
          and rc7 == 1 and '认不出' in out7)
    cases.append(('62 import `--header-row N`：表头不在第一行时**明说**，不靠认列去猜；'
                  '越界 / 那一行认不出关键列都当场说清',
                  ok, (rc5, rc6, rc7), (out5[-200:] + out6[-120:] + out7[-160:]) if not ok else ''))
    return cases


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
    ok = (len(mats) == 21 and all(m.get('tier') and m.get('kind') for m in mats)
          and by.get('i.xlsx.et', {}).get('kind') == 'xlsx'        # 改名件按内容判
          and by.get('j.pdf.png', {}).get('kind') == 'pdf-text'
          and by.get('k.docx', {}).get('kind') == 'unknown'        # 半容器不许冒充 docx
          and by.get('o.txt', {}).get('tier') == 'T4')             # 空文件记 T4，不猜
    cases.append(('⑳ probe：21 份都有档位 + kind；改名件/半容器/空文件都按内容判', ok, rc,
                  out[-300:] if not ok else ''))
    if not mats:
        return cases
    (d / 'materials.json').write_text(json.dumps(mats, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8', newline='\n')
    t1 = {m.get('kind') for m in mats if m.get('tier') == 'T1'}
    cases.append(('㉑ probe 不变式：判 T1 的 kind 全都有 reader 认领',
                  t1 <= {'docx', 'xlsx', 'pptx', 'text'}, rc, f'T1 的 kind = {sorted(t1)}'))
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--elements', str(d / 'e-tree.json'), '--notes', str(d / 'n-tree.json'),
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
    ok = (rc == 0 and len(rows) == 21 and not blank
          and '摘要不可得' in rec                       # legacy：说清极限
          and '尺寸不可知' in rec                        # 无 <dimension> 的流式表：记在行里而不是崩
          and '超护栏' not in rec)                      # 正常阈值下不该有护栏记账
    # **产物要能被自己的 `check` 读回来**（2026-09-18 补，真材料集上现形）：`.md` / `.csv` 的
    # "结构缩样"会原样回显材料的头几行，而那里可能有 `|`（markdown 表格）——不转义就把这一行的
    # 列数撑破，`check` 报"仪器故障"，而真正的原因在材料正文里。此前 ㉓ 只 grep 文本，抓不到。
    (d / 'c-tree.md').write_text(_fill_recon_card(rec), encoding='utf-8', newline='\n')
    rc_chk, out_chk = run([sys.executable, str(RECON_CMD), 'check', str(d / 'c-tree.md'),
                           '--materials', str(d / 'materials.json')])
    cases.append(('㉓ recon：21 行 · 每行的「规模/读不动」都有交代 · **产物能被自己的 `check` 读回来**'
                  '（含一份正文带 `|` 的 markdown）',
                  ok and rc_chk == 0, rc,
                  (out[-200:] + f'｜空白行={blank}' + out_chk[-200:]) if not (ok and rc_chk == 0) else ''))
    small = d / 'small.yaml'
    small.write_text('recon:\n  easy_max_bytes: 1024\n  max_open_bytes: 512\n'
                     '  outline_max: 50\n  outline_show: 3\n', encoding='utf-8')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                   '--dict', str(small), '-o', str(d / 'recon-small.md')])
    rec2 = (d / 'recon-small.md').read_text(encoding='utf-8') if (d / 'recon-small.md').exists() else ''
    cases.append(('㉔ 超护栏：`max_open_bytes` 调到 512 后记在行里（不打开结构、不崩）',
                  rc == 0 and '超护栏' in rec2, rc, out[-300:] if rc != 0 else ''))

    # ㉔b 缺转换器时的提示要**指名族与另存目标**（真样本 .wps 是 Word 族：该说 .docx，不该泛泛说 OOXML）。
    #     三族各一份：`.wps` / `.dps` 两个后缀在 `OLE_EXT` 兜底表里**没有**，认出来就证明"按内容判"。
    fams = (('p.doc', 'Word 97-2003', '.docx'), ('r.wps', 'Word 97-2003', '.docx'),
            ('s.dps', 'PowerPoint 97-2003', '.pptx'), ('t.xls', 'Excel 97-2003', '.xlsx'))
    bad = []
    for name, fam, save_as in fams:
        mid = by.get(name, {}).get('id', '')
        led_f = d / 'led-ole.json'
        rc2, out2 = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                         '--only', mid, '--elements', str(d / 'e-ole.json'),
                         '--notes', str(d / 'n-ole.json'), '--ledger', str(led_f)])
        try:
            reason = next((m.get('reason') or '' for m in
                           json.loads(led_f.read_text(encoding='utf-8'))['materials'] if m['id'] == mid), '')
        except (OSError, ValueError, KeyError, StopIteration):
            reason = ''
        if not (rc2 == 0 and fam in reason and save_as in reason):
            bad.append(f'{name}/{mid}→{reason[:80] or out2[-80:]}')
    cases.append(('㉔b legacy 提示逐族指名族与另存目标（Word→.docx · PowerPoint→.pptx · Excel→.xlsx，'
                  '`.wps`/`.dps` 只能靠流名认）', not bad, 0, '；'.join(bad)))

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
    hard = {m['id'] for m in mats if m.get('status') != 'ok'}      # 材料层自己就判读不动的
    others = {k: (v.get('status'), v.get('reason') or '') for k, v in ms.items()
              if k not in ('M06', 'M07')}
    ok = (rc == 0
          and {e['material_id'] for e in els} == {'M06'}                 # 只有 f.txt 含「审批」
          and ms.get('M07', {}).get('status') == 'skipped'               # 被滤空的那份：记「未取」
          and '未取' in (ms.get('M07', {}).get('reason') or '')
          # **读不动是材料的属性**：`--only` 不许把它改写成「未取」（审计实测的阻断，这里钉住）
          and all(others.get(i, ('', ''))[0] == 'unreadable' for i in hard)
          and all(s == 'skipped' for i, (s, _r) in others.items() if i not in hard)
          and all('本轮收窄' in (e.get('degraded') or '') for e in els))
    cases.append(('㉕ 抽取时收窄（--only + --grep）：只留该留的 · 其余记「本轮未取」· '
                  '**读不动的仍记读不动**', ok, rc,
                  (out[-200:] + str({k: v[0] for k, v in others.items()})) if not ok else ''))

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

    # ㉘ 「图多大都不该挡住摘要」：**媒体很大、文字很小**的稿子 —— 护栏必须按"要读的部件"算。
    # 真是这么发现的：一份 42 MB 的稿子（媒体 42 MB、slides 几百 KB）被判"超护栏"⇒ **摘要直接没有**，
    # 而摘要恰恰是这种大材料最需要的（§1.5 手段 1）。
    fat = root / 'fat'
    fat.mkdir(exist_ok=True)
    make_deck(fat / '带大图.pptx')
    with zipfile.ZipFile(fat / '带大图.pptx', 'a') as z:
        z.writestr('ppt/media/image1.png', b'\x00' * 20000)          # 20 KB 的"图"
    rc, out = run([sys.executable, str(PROBE_CMD), str(fat), '--json'])
    (fat / 'materials.json').write_text(out[out.index('['):] if '[' in out else '[]',
                                        encoding='utf-8', newline='\n')
    (d / 'guard4k.yaml').write_text('recon:\n  max_open_bytes: 4096\n', encoding='utf-8')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(fat / 'materials.json'),
                   '--dict', str(d / 'guard4k.yaml'), '-o', str(fat / 'r1.md')])
    r1 = (fat / 'r1.md').read_text(encoding='utf-8') if (fat / 'r1.md').exists() else ''
    (d / 'guard512.yaml').write_text('recon:\n  max_open_bytes: 512\n', encoding='utf-8')
    rc2, out2 = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(fat / 'materials.json'),
                     '--dict', str(d / 'guard512.yaml'), '-o', str(fat / 'r2.md')])
    r2 = (fat / 'r2.md').read_text(encoding='utf-8') if (fat / 'r2.md').exists() else ''
    ok = (rc == 0 and '幻灯片' in r1 and '超护栏' not in r1        # 20 KB 媒体 + 4 KB 护栏 ⇒ 摘要照出
          and rc2 == 0 and '超护栏' in r2)                        # 护栏收到 512 ⇒ 照样记在行里
    cases.append(('㉘ 图大不挡摘要：护栏按*要读的部件*算（20KB 媒体 + 4KB 护栏 → 有摘要；'
                  '收到 512 → 才记超护栏）', ok, rc, (r1[-200:] + r2[-200:]) if not ok else ''))
    # ㉙ 范围写歪 / 点名不存在的材料 ⇒ 退 2 说人话（原先：静默按全量走 / 静默退 0 且写一张空账本）
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--only', 'M02', '--lines', '5-2',
                   '--elements', str(d / 'x.json'), '--notes', str(d / 'xn.json')])
    rc2, out2 = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                     '--only', 'M99', '--elements', str(d / 'x.json'), '--notes', str(d / 'xn.json')])
    ok = (rc == 2 and '上界小于下界' in out and rc2 == 2 and '一个都不在材料层里' in out2)
    cases.append(('㉙ 写歪的范围 / 点名不存在的材料 ⇒ 退 2 + 人话', ok, rc,
                  (out[-150:] + out2[-150:]) if not ok else ''))

    # ㉚ 收窄把材料读空 ⇒ 记 `skipped`「本轮收窄未取」，**不是** `unreadable`「空文档 / 只有图片」、
    #    也不是假报「探测说谎」退 1（审计实测：`--slides 999-1000`、`--sheet 不存在`、`--pages 越界`
    #    都会把**参数错**记成**材料缺陷**，下一轮 AI 会照它把好材料判死）。
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                   '--only', 'M03', '--slides', '99-100',
                   '--elements', str(d / 'e-narrow.json'), '--notes', str(d / 'n-narrow.json'),
                   '--ledger', str(d / 'led-narrow.json'), '--task', 'narrow-empty'])
    led2 = {}
    if (d / 'led-narrow.json').exists():
        try:
            led2 = json.loads((d / 'led-narrow.json').read_text(encoding='utf-8'))
        except ValueError:
            led2 = {}
    m3 = next((m for m in led2.get('materials', []) if m['id'] == 'M03'), {})
    ok = (rc == 0 and m3.get('status') == 'skipped' and '收窄' in (m3.get('reason') or '')
          and '探测说谎' not in out)
    cases.append(('㉚ 收窄读空 ⇒ skipped「本轮收窄未取」（不是 unreadable「空文档」、也不是假探谎）',
                  ok, rc, (out[-200:] + str(m3)[:150]) if not ok else ''))

    # ㉛ 阈值文件**形状不对**（YAML 里给列表，常见笔误）⇒ 退回默认、照出表；阈值 ≤0 同理（不许让摘要说假话）
    (d / 'bad-shape.yaml').write_text('recon: [1,2]\n', encoding='utf-8')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                   '--dict', str(d / 'bad-shape.yaml'), '-o', str(d / 'r-shape.md')])
    (d / 'bad-range.yaml').write_text('recon:\n  outline_max: -1\n', encoding='utf-8')
    rc2, out2 = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'materials.json'),
                     '--dict', str(d / 'bad-range.yaml'), '-o', str(d / 'r-range.md')])
    r_range = (d / 'r-range.md').read_text(encoding='utf-8') if (d / 'r-range.md').exists() else ''
    ok = (rc == 0 and (d / 'r-shape.md').exists() and rc2 == 0 and '幻灯片' in r_range)
    cases.append(('㉛ 阈值形状不对/≤0 ⇒ 退回默认照出表（原先裸栈退 1 零产物 / 摘要谎称「空稿」）',
                  ok, rc, (out[-160:] + r_range[:160]) if not ok else ''))

    # ㉜ 材料层**形状坏** ⇒ 退 2 说人话（原先裸栈退 1、零产物：`["x"]` / `bytes:"很 大"` / `path:null`）
    (d / 'bad-mats.json').write_text('["x"]\n', encoding='utf-8')
    rc, out = run([sys.executable, str(RECON_CMD), 'build', '--materials', str(d / 'bad-mats.json'),
                   '-o', str(d / 'r-bad.md')])
    cases.append(('㉜ 材料层形状坏 ⇒ 退 2 + 人话', rc == 2 and '形状不对' in out, rc, out[-160:]))

    # ㉝ `check` 的**脚本列**不许被改（原先只比档位+四个 AI 列：把「只取摘要」改成「全量解析」照样过），
    #    重复行也不许（原先后写覆盖先写，人读第一行、校验最后一行）。
    #    **正例一起判**：原先 `rc_ok` 算出来只打印、不作判据——"check 永远退 1"也能全绿。
    draft = (d / 'r-range.md').read_text(encoding='utf-8')
    filled = _fill_recon_card(draft)
    (d / 'c-ok.md').write_text(filled, encoding='utf-8', newline='\n')
    rc_ok, out_ok = run([sys.executable, str(RECON_CMD), 'check', str(d / 'c-ok.md'),
                         '--materials', str(d / 'materials.json')])
    (d / 'c-tampered.md').write_text(filled.replace('全量解析', '不参与'), encoding='utf-8', newline='\n')
    rc_bad, out_bad = run([sys.executable, str(RECON_CMD), 'check', str(d / 'c-tampered.md'),
                           '--materials', str(d / 'materials.json')])
    rows = [l for l in filled.splitlines() if l.startswith('| `M')]
    (d / 'c-dup.md').write_text(filled + rows[0] + '\n', encoding='utf-8', newline='\n')
    rc_dup, out_dup = run([sys.executable, str(RECON_CMD), 'check', str(d / 'c-dup.md'),
                           '--materials', str(d / 'materials.json')])
    ok = (rc_ok == 0 and rc_bad == 1 and '解析深度' in out_bad and rc_dup == 2 and '两行' in out_dup)
    cases.append(('㉝ check：合规的过（退 0）· 改脚本列（只取摘要→全量解析）⇒ 退 1 · 重复行 ⇒ 退 2',
                  ok, rc_bad, (out_ok[-160:] + out_bad[-160:] + out_dup[-120:]) if not ok else ''))

    # ㉞ probe：**头部是文本、尾部是二进制**的 `.txt` 不许判 T1（原先只看前 4 KB ⇒ 判可直读，
    #    而 parse_text 要解整份、谁都读不动）
    tail_d = root / 'tail'
    tail_d.mkdir(exist_ok=True)
    (tail_d / 'bad-tail.txt').write_bytes(b'A' * 5000 + b'\xff\xfe\xff')
    (tail_d / 'big-cn.txt').write_text('中文内容测试。' * 2000, encoding='utf-8')   # >4KB 的中文，不许回归
    rc, out = run([sys.executable, str(PROBE_CMD), str(tail_d), '--json'])
    tm = {}
    if '[' in out:
        try:
            tm = {pathlib.Path(m['path']).name: m for m in json.loads(out[out.index('['):])}
        except ValueError:
            tm = {}
    ok = (tm.get('bad-tail.txt', {}).get('tier') == 'T4'
          and tm.get('big-cn.txt', {}).get('tier') == 'T1')
    cases.append(('㉞ probe：头文本尾二进制的 .txt 判 T4 · 大中文 txt 仍 T1（尾部检查不许反向误判）',
                  ok, rc, str({k: v.get('tier') for k, v in tm.items()})))

    # ㊳ 纯文本**不猜编码**（§1.4）：GBK 材料记读不动 + 可执行提示；显式 `--encoding gbk` 读出来并把
    #    `status` 改回 `ok`；**同一批里的 UTF-8 材料不受影响**（实测修掉"一份 GBK 把整批拖成读不动"）。
    led_mats = {}
    if (d / 'evidence.json').exists():
        try:
            led_mats = {pathlib.Path(m.get('path', '')).name: m for m in
                        json.loads((d / 'evidence.json').read_text(encoding='utf-8'))['materials']}
        except (ValueError, KeyError):
            led_mats = {}
    n_before = led_mats.get('n.txt', {})
    nid = by.get('n.txt', {}).get('id', '')
    rc2, out2 = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                     '--only', nid, '--encoding', 'gbk',
                     '--elements', str(d / 'e-gbk.json'), '--notes', str(d / 'n-gbk.json'),
                     '--ledger', str(d / 'led-gbk.json')])
    n_after, n_els = {}, []
    try:
        got = json.loads((d / 'led-gbk.json').read_text(encoding='utf-8'))
        n_after = next((m for m in got['materials'] if m['id'] == nid), {})
        n_els = got['elements']
    except (OSError, ValueError, KeyError, StopIteration):
        pass
    ok = (n_before.get('status') == 'unreadable' and '--encoding' in (n_before.get('reason') or '')
          and led_mats.get('f.txt', {}).get('status') == 'ok'          # UTF-8 的那份没被带坏
          and rc2 == 0 and n_after.get('status') == 'ok' and len(n_els) > 0)
    cases.append(('㊳ 纯文本不猜编码：GBK 记读不动 + 可执行提示 · `--encoding gbk` 读出来并改回 `ok` · '
                  'UTF-8 材料不受影响', ok, rc2,
                  (str(n_before)[:160] + str(n_after)[:120]) if not ok else ''))

    # 51 legacy 的**自包含降级读法**（§1.6）：没有转换器时，真 OLE 里按 UTF-16LE 捞文本 run 就能读；
    #    但"捞得出来"不等于"都是正文"——纯二进制、以及**错位读出来的怪字**都必须挡在门外（记读不动）。
    #    这一条考的是**通用能力**：任何 OLE 材料（含 `.wps` / `.dps` 这类 WPS 后缀）都走它，与具体项目无关。
    ole_d = root / 'oletext'
    ole_d.mkdir(exist_ok=True)
    body = '本合同项下，甲方每5MW或每半年向乙方支付一次工程款，付款比例另行约定。' * 12
    (ole_d / 'a.doc').write_bytes(_ole_bytes('WordDocument') + body.encode('utf-16-le'))
    (ole_d / 'b.doc').write_bytes(_ole_bytes('WordDocument')
                                  + bytes([(i * 7 + 3) % 256 for i in range(6000)]))
    # `00 3a` 反复：按 UTF-16LE 读成一串"低字节恒为 0"的合法汉字（实测在真材料里抓到过这种噪声）
    (ole_d / 'c.doc').write_bytes(_ole_bytes('WordDocument') + b'\x00\x3a' * 300)
    # `d.doc`：**正文两边夹着"另外两种语言"**（D-109）——内嵌 XML 与 Word 域代码。它们长度够、
    # 字符也"像字"，前四道判据全过，所以过去会混进账本（下游「依据」一引就是一段标签）。
    # 用 `\x00\x00` 分隔（UTF-16LE 的 U+0000 不是文本单元 ⇒ run 在此断开，与真 .doc 里一样）。
    noise_markup = ('<w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom>'
                    '<o:DocumentProperties><o:Author>张三</o:Author></o:DocumentProperties>'
                    '</w:WordDocument>')
    (ole_d / 'd.doc').write_bytes(
        _ole_bytes('WordDocument')
        + noise_markup.encode('utf-16-le') + b'\x00\x00'
        + 'PAGE \\* MERGEFORMAT'.encode('utf-16-le') + b'\x00\x00'
        + ('本合同项下，甲方每5MW或每半年向乙方支付一次工程款，付款比例另行约定。' * 6).encode('utf-16-le'))
    rc_p, out_p = run([sys.executable, str(PROBE_CMD), str(ole_d), '--json'])
    (ole_d / 'materials.json').write_text(out_p[out_p.index('['):], encoding='utf-8')
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(ole_d / 'materials.json'),
                   '-o', str(ole_d / 'els.json'), '--notes', str(ole_d / 'notes.json'),
                   '--ledger', str(ole_d / 'led.json')])
    ole_mats, ole_els = {}, []
    try:
        got = json.loads((ole_d / 'led.json').read_text(encoding='utf-8'))
        ole_mats = {pathlib.Path(m.get('path', '')).name: m for m in got['materials']}
        ole_els = got['elements']
    except (OSError, ValueError, KeyError):
        pass
    m_a, m_b, m_c = (ole_mats.get('a.doc', {}), ole_mats.get('b.doc', {}), ole_mats.get('c.doc', {}))
    m_d = ole_mats.get('d.doc', {})
    a_els = [e for e in ole_els if e.get('material_id') == m_a.get('id')]
    d_els = [e for e in ole_els if e.get('material_id') == m_d.get('id')]
    d_text = '\n'.join(e.get('text') or '' for e in d_els)
    d_deg = '\n'.join(e.get('degraded') or '' for e in d_els)
    ok = (rc_p == 0 and rc == 0
          and m_a.get('status') == 'ok' and m_a.get('extractor') == 'py:oletext'
          and a_els and all(e.get('extractor') == 'py:oletext'
                            and 'py:oletext' in (e.get('degraded') or '') for e in a_els)
          and any('5MW' in (e.get('text') or '') for e in a_els)
          and m_b.get('status') == 'unreadable' and '另存为' in (m_b.get('reason') or '')
          and m_c.get('status') == 'unreadable'
          # D-109：正文留下 · **另外两种语言**不进账本 · 而且**账上说了是判据丢的**
          and m_d.get('status') == 'ok' and any('5MW' in (e.get('text') or '') for e in d_els)
          and '<w:' not in d_text and 'MERGEFORMAT' not in d_text and 'o:Author' not in d_text
          and '内嵌 XML' in d_deg and '域代码' in d_deg)
    cases.append(('51 legacy 降级读法（§1.6）：真 OLE 捞 UTF-16LE 正文（extractor=py:oletext + 逐条挂 degraded）· '
                  '纯二进制与"错位读出的怪字"都不许当正文 · '
                  '**内嵌 XML / 域代码这两种"别的语言"丢掉并记账**（D-109）',
                  ok, rc, (str({k: (v.get('status'), v.get('extractor')) for k, v in ole_mats.items()})
                           + f' a.doc 元素 {len(a_els)} · d.doc 元素 {len(d_els)}'
                           + (f' · d 的 degraded: {d_deg[:150]}' if not ok else '')) if not ok else ''))

    # 52 两份**通用**材料的边界（同样与具体项目无关）：
    #    ① markdown 表格**按行成块**——`依据` 要指得到"第几项"（盲读实测：一整张表并成一个块，只能写人话）；
    #    ② `noisy` 判决要把**丢之前 / 丢之后**两次读数并排打（同一份材料 62% vs 37%，不说清就像读数说谎）。
    tb_d = root / 'textblocks'
    tb_d.mkdir(exist_ok=True)
    rows = '\n'.join(f'| 阶段{i} | {i:02d} 第{i}项动作 | 任务 | →{i + 1:02d} |' for i in range(1, 9))
    (tb_d / 'table.md').write_text('# 一张表\n\n| 阶段 | 节点 | 类型 | 下个节点 |\n| --- | --- | --- | --- |\n'
                                   + rows + '\n', encoding='utf-8')
    # 40 行里 18 行是单字行（占 45%：≥ noisy 的 25%、< garbled 的 75%）⇒ 判 noisy；
    # 那 18 行**自成一块**（空行隔开）⇒ 元素级判据把它整条丢掉，丢完读数与丢前不同
    noisy_lines = ['验'] * 18 + [''] + [f'第 {i} 条正文内容，这一行是一句完整的话。' for i in range(1, 23)]
    (tb_d / 'noisy.txt').write_text('\n'.join(noisy_lines) + '\n', encoding='utf-8')
    rc_tp, out_tp = run([sys.executable, str(PROBE_CMD), str(tb_d), '--json'])
    (tb_d / 'materials.json').write_text(out_tp[out_tp.index('['):], encoding='utf-8')
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(tb_d / 'materials.json'),
                   '-o', str(tb_d / 'els.json'), '--notes', str(tb_d / 'notes.json'),
                   '--ledger', str(tb_d / 'led.json')])
    tb_mats, tb_els = {}, []
    try:
        got = json.loads((tb_d / 'led.json').read_text(encoding='utf-8'))
        tb_mats = {pathlib.Path(m.get('path', '')).name: m['id'] for m in got['materials']}
        tb_els = got['elements']
    except (OSError, ValueError, KeyError):
        pass
    t_els = [e for e in tb_els if e.get('material_id') == tb_mats.get('table.md')]
    row3 = [e for e in t_els if '第3项动作' in (e.get('text') or '')]
    n_els = [e for e in tb_els if e.get('material_id') == tb_mats.get('noisy.txt')]
    ok = (rc_tp == 0 and rc == 0
          and row3 and '第4项动作' not in row3[0]['text']          # 一行一格：第 3 项自己就是一条证据
          and '丢完读数' in out and 'noisy' in out
          and n_els and all('抽取质量有保留' in (e.get('degraded') or '') for e in n_els)
          and not any(set((e.get('text') or '').strip()) == {'验'} for e in n_els))
    cases.append(('52 文本层两条边界：markdown 表格**按行成块**（一行一条证据）· `noisy` 判决并排打'
                  '「丢前 / 丢完」两次读数、纯碎片那条不进账本',
                  ok, rc, (f'table 元素 {len(t_els)} · row3 {len(row3)} · noisy 元素 {len(n_els)}') if not ok else ''))

    # 53 **尺子二：文本层薄**（§1.6）——两种 PDF 的**每页元素数一样（都 1 条）**，只差每页字数：
    #    这份对照就是判据本身（"两个量一起看"）：光看元素数会把"一页一整篇"也判成薄。
    pt_d = root / 'thinpdf'
    pt_d.mkdir(exist_ok=True)
    (pt_d / 'thin.pdf').write_bytes(_pdf_pages([f'Page {i}' for i in range(1, 6)]))
    (pt_d / 'dense.pdf').write_bytes(_pdf_pages(['word ' * 120 for _ in range(5)]))
    rc_tp, out_tp = run([sys.executable, str(PROBE_CMD), str(pt_d), '--json'])
    (pt_d / 'materials.json').write_text(out_tp[out_tp.index('['):], encoding='utf-8')
    rc, out = run([sys.executable, str(PARSE_CMD), '--materials', str(pt_d / 'materials.json'),
                   '-o', str(pt_d / 'els.json'), '--notes', str(pt_d / 'notes.json'),
                   '--ledger', str(pt_d / 'led.json')])
    pt_mats, pt_els = {}, []
    try:
        got = json.loads((pt_d / 'led.json').read_text(encoding='utf-8'))
        pt_mats = {pathlib.Path(m.get('path', '')).name: m for m in got['materials']}
        pt_els = got['elements']
    except (OSError, ValueError, KeyError):
        pass
    thin_els = [e for e in pt_els if e.get('material_id') == pt_mats.get('thin.pdf', {}).get('id')]
    dense_els = [e for e in pt_els if e.get('material_id') == pt_mats.get('dense.pdf', {}).get('id')]
    ok = (rc_tp == 0 and rc == 0
          and pt_mats.get('thin.pdf', {}).get('tier') == 'T2' and len(thin_els) == 5
          and thin_els and all('文字层薄' in (e.get('degraded') or '') for e in thin_els)
          and len(dense_els) == 5
          and not any('文字层薄' in (e.get('degraded') or '') for e in dense_els))
    cases.append(('53 尺子二（文本层薄）：每页元素数相同、只差每页字数 ⇒ 薄的那份逐条挂降级 + 建议转图片，'
                  '密的**不许**被误判（两个量一起看）',
                  ok, rc, (f"thin {len(thin_els)} / dense {len(dense_els)} · {out[-200:]}") if not ok else ''))

    # 54 **H10.1 引用完整**（§6）：四条路径一次钉住——有账本且引用都对 ⇒ 退 0 且**打印这一层跑了**；
    #    引了不存在的 id ⇒ 退 1 且点名；没有账本 ⇒ **整层跳过、不报错**（不许误伤旧表）；账本坏且引了 id ⇒ 退 1。
    #    这条判据是**通用**的：与具体项目无关，任何"成果根 + 账本"的任务都受它保护。
    h10_d = root / 'h10'
    h10_d.mkdir(exist_ok=True)
    led = {'schema': 2, 'task': 'h10', 'materials': [
        {'id': 'M01', 'path': '材料/甲.md', 'sha256': 'a' * 64, 'bytes': 10,
         'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'text', 'probe': '夹具', 'status': 'ok'}],
        'elements': [{'id': 'M01#p001', 'material_id': 'M01', 'kind': 'paragraph', 'text': '一句',
                      'location': {'path': '材料/甲.md', 'quote': '一句'},
                      'extractor': 'py:text', 'certainty': 'direct'}]}
    (h10_d / 'evidence.json').write_text(json.dumps(led, ensure_ascii=False), encoding='utf-8')
    head = ('---\nid: h10\nlevel: L0\n---\n\n# H10 夹具\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 '
            '| 行动所需时间 | 下个节点 | 节点描述 |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n')
    ok_row = '| 起 | 01 | 收料 | 开始 | — | `M01#p001` | 材料 | 甲 | 甲 | — | →02 | — |\n'
    end_row = '| 起 | 02 | 归档 | 结束 | 材料 | `M01#p001` | — | 甲 | 甲 | — | — | — |\n'
    (h10_d / 'flowtable.md').write_text(head + ok_row + end_row, encoding='utf-8')
    rc_h10, out_h10 = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(h10_d / 'flowtable.md')])
    (h10_d / 'bad.md').write_text(head + ok_row.replace('M01#p001', 'M01#p999') + end_row, encoding='utf-8')
    rc_bad, out_bad = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(h10_d / 'bad.md')])
    # "没有账本"这一支**必须放在整棵夹具树之外**：H10 是**向上**找账本的，而夹具树自己有一份账本
    # （实测踩到两次：放在 h10/no-ledger 里、放在 root 下，那一支都照样跑起了 H10 —— 夹具自己骗了自己）。
    # 所以借一个**独立临时目录**（跑完自动删）。
    with tempfile.TemporaryDirectory(prefix='h10-noledger-') as td:
        p = pathlib.Path(td) / 'flowtable.md'
        p.write_text(head + ok_row + end_row, encoding='utf-8')
        rc_none, out_none = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(p)])
    (h10_d / 'broken').mkdir(exist_ok=True)
    (h10_d / 'broken' / 'evidence.json').write_text('{ 这不是 JSON', encoding='utf-8')
    (h10_d / 'broken' / 'flowtable.md').write_text(head + ok_row + end_row, encoding='utf-8')
    rc_brok, out_brok = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(h10_d / 'broken' / 'flowtable.md')])
    # 54b **深层子表**（D-108）：账本在成果根，表在 `a/parts/b/parts/c/`（**比原来的 4 层上限还深一层**）。
    #     旧实现够不着，于是把它报成"本表附近没有账本"——**同一个词说两件事**。两条路径：
    #     引用对 ⇒ 退 0 且打印用了哪本账（相对写法能看出它在上面几层）；引用错 ⇒ 退 1 点名（证明它真跑了）。
    deep = h10_d / 'a' / 'parts' / 'b' / 'parts' / 'c'
    deep.mkdir(parents=True, exist_ok=True)
    (deep / 'flowtable.md').write_text(head + ok_row + end_row, encoding='utf-8')
    rc_deep, out_deep = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(deep / 'flowtable.md')])
    (deep / 'bad.md').write_text(head + ok_row.replace('M01#p001', 'M01#p999') + end_row, encoding='utf-8')
    rc_deepbad, out_deepbad = run([sys.executable, str(REPO / 'scripts' / 'table_to_dsl.py'), '--check', str(deep / 'bad.md')])
    ok = (rc_h10 == 0 and 'H10引用完整' in out_h10 and '账本 evidence.json' in out_h10
          and rc_bad == 1 and 'M01#p999' in out_bad
          and rc_none == 0 and 'H10引用完整' not in out_none and '跳过' in out_none
          and '盘根' in out_none                       # 跳过的理由要说准：找到哪儿为止
          and rc_brok == 1 and '账本读不动' in out_brok
          and rc_deep == 0 and 'H10引用完整' in out_deep
          and '../../../../../evidence.json' in out_deep
          and rc_deepbad == 1 and 'M01#p999' in out_deepbad)
    cases.append(('54 H10.1 引用完整（§6）：有账本且引用都对 ⇒ 退 0 并打印用的是哪本账 · 引错 ⇒ 退 1 点名 · '
                  '**没有账本 ⇒ 整层跳过不报错**（理由说准"找到盘根"）· 账本坏且引了 id ⇒ 退 1 · '
                  '**子表的子表（5 层）也够得着**（旧实现 4 层上限够不着，还把它说成"没有账本"）',
                  ok, rc_h10, (f'ok={rc_h10}/{out_h10[-80:]} bad={rc_bad}/{out_bad[-90:]} '
                               f'none={rc_none}/{out_none[-70:]} brok={rc_brok}/{out_brok[-70:]} '
                               f'deep={rc_deep}/{out_deep[-80:]} deepbad={rc_deepbad}') if not ok else ''))

    # 55 **依据分布**（§5.6，读数不是判据）：受控的表序把"连续段"算准——01,02 只引 M01（一条 2 长的段）、
    #    03 只引 M02（单节点段**不报**）、04,05 引 M01（新起一段）。同时验它**不进** check 的收敛口径。
    dep_d = root / 'depreadout'
    dep_d.mkdir(exist_ok=True)
    (dep_d / 'evidence.json').write_text(json.dumps(
        {'schema': 2, 'task': 'dep', 'materials': [
            {'id': m, 'path': f'材料/{m}.md', 'sha256': c * 64, 'bytes': 10,
             'mtime': '2026-09-01T10:00:00', 'tier': 'T1', 'kind': 'text', 'probe': '夹具', 'status': 'ok'}
            for m, c in (('M01', 'a'), ('M02', 'b'))],
         'elements': [{'id': f'{m}#p001', 'material_id': m, 'kind': 'paragraph', 'text': '一句',
                       'location': {'path': f'材料/{m}.md', 'quote': '一句'},
                       'extractor': 'py:text', 'certainty': 'direct'} for m in ('M01', 'M02')]},
        ensure_ascii=False), encoding='utf-8')
    dep_head = ('---\nid: dep\nlevel: L0\n---\n\n# 依据分布夹具\n\n## 流程表\n\n'
                '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 '
                '| 行动所需时间 | 下个节点 | 节点描述 |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n')
    dep = [('01', '开始', 'M01#p001', '→02'), ('02', '甲步', 'M01#p001', '→03'),
           ('03', '乙步', 'M02#p001', '→04'), ('04', '丙步', 'M01#p001', '→05'),
           ('05', '收尾', '`M01#p001`、`M02#p001`', '—')]
    typ = {'01': '开始', '05': '结束'}                 # 01 必须是「开始」，否则整表不可达（第一版漏了这行）
    body = ''.join(f'| 段 | {i} | {n} | {typ.get(i, "任务")} | — | `{b}` | — | 甲 | 甲 '
                   f'| — | {nx} | — |\n' for i, n, b, nx in dep)
    (dep_d / 'flowtable.md').write_text(dep_head + body, encoding='utf-8')
    rc_dep, out_dep = run([sys.executable, str(DRIFT), 'build', str(dep_d / 'flowtable.md'),
                           '--ledger', str(dep_d / 'evidence.json'), '--out', str(dep_d / 'drift.md')])
    readout = ''
    if (dep_d / 'drift.md').is_file():
        text_d = (dep_d / 'drift.md').read_text(encoding='utf-8')
        readout = text_d[text_d.index('## ③'):] if '## ③' in text_d else ''
    # 节点 01/02/04/05 引 M01、03/05 引 M02 ⇒ M01 4 个（80%）、M02 2 个（40%）；
    # 只引一份材料的相邻节点里：01,02 连成一段（2），04 单独一个（单节点段**不报**），03 同理
    ok = (rc_dep == 0 and '| 材料 | 撑着的节点 | 占比 | 材料状态 | 连续段 |' in readout
          and '01–02（2）' in readout and '03–' not in readout
          and '| `M01` | 4 | 80% |' in readout and '| `M02` | 2 | 40% |' in readout
          and '依据分布' in out_dep)
    cases.append(('55 依据分布（§5.6）：节点级占比 + **连续段**（只引一份材料的相邻节点）算得准 · '
                  '单节点段不报 · 它是读数（不进 `check` 的收敛口径）',
                  ok, rc_dep, (readout[:400] or out_dep[-300:]) if not ok else ''))
    return cases


def vlm_paths(root):
    """T3 → 视觉取证的**整条通道**（§1.3 / §1.5 手段 2；D-112）：账本说"待视觉" → 渲图/取原图 →
    AI 填骨架 → `check` 写补注 → **两路合并**重出账本。

    为什么值得一条路径：这条通道在 §8 里一直写着"**未进验收路径**"（渲染 PDF 要 pdfplumber +
    pypdfium2 同时在场，夹具只测到"不参与"那一侧）。**图片材料不用渲染**（`probe` 已记 T3 + 图片魔数，
    直接用原文件）⇒ 这条通道**可以完全自包含地测**，那半句"未进验收"就没有理由了。
    """
    cases = []
    d = root / 'vlm'
    d.mkdir(exist_ok=True)
    _minimal_png(d / '扫描件.png')
    (d / '正文.md').write_text('# 办法\n\n甲方向乙方提交材料。\n', encoding='utf-8')
    rc_p, out_p = run([sys.executable, str(PROBE_CMD), str(d), '--json'])
    (d / 'materials.json').write_text(out_p[out_p.index('['):], encoding='utf-8')
    rc1, out1 = run([sys.executable, str(PARSE_CMD), '--materials', str(d / 'materials.json'),
                     '-o', str(d / 'elements.json'), '--notes', str(d / 'notes.json'),
                     '--ledger', str(d / 'evidence.json'), '--task', 'vlm'])
    led = {}
    try:
        led = json.loads((d / 'evidence.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    img = next((m for m in led.get('materials', []) if m.get('kind') == 'image'), {})
    rc2, out2 = run([sys.executable, str(REPO / 'scripts' / 'render_pages.py'), 'build',
                     '--materials', str(d / 'materials.json'), '--out-dir', str(d / 'shots'),
                     '--elements', str(d / 'vision.todo.json')])
    todo = []
    try:
        todo = json.loads((d / 'vision.todo.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    # 反例①：**空骨架不许过**（"没填"必须当错，否则空骨架也能混进账本）
    rc3, out3 = run([sys.executable, str(REPO / 'scripts' / 'render_pages.py'), 'check',
                     str(d / 'vision.todo.json'), '--notes', str(d / 'none.notes.json')])
    # **先把这个判断存下来**：下面几行会把 `todo` **就地填满**（模拟 AI），
    # 而 `ok = (...)` 是在填完之后才算的——直接把它写在那个表达式里就永远为假（我第一版就是这么错的）。
    skeleton_ok = bool(todo) and all(e.get('text') == '' and re.match(r'^M\d+#v\d+$', e.get('id') or '')
                                     for e in todo)
    for e in todo:                                   # 装 AI：读图后填 text、收紧 bbox
        e['text'] = f'（模拟读图）{e["id"]} 上读到的一句话'
        e['location']['bbox'] = [0.1, 0.2, 0.5, 0.1]
    (d / 'vision.json').write_text(json.dumps(todo, ensure_ascii=False, indent=2) + '\n',
                                   encoding='utf-8', newline='\n')
    rc4, out4 = run([sys.executable, str(REPO / 'scripts' / 'render_pages.py'), 'check',
                     str(d / 'vision.json'), '--notes', str(d / 'vision.notes.json')])
    rc5, out5 = run([sys.executable, str(LEDGER), '--materials', str(d / 'materials.json'),
                     '--elements', str(d / 'elements.json'), '--elements', str(d / 'vision.json'),
                     '--notes', str(d / 'notes.json'), '--notes', str(d / 'vision.notes.json'),
                     '--task', 'vlm', '-o', str(d / 'evidence2.json')])
    led2 = {}
    try:
        led2 = json.loads((d / 'evidence2.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    img2 = next((m for m in led2.get('materials', []) if m.get('kind') == 'image'), {})
    vels = [e for e in led2.get('elements', []) if e.get('extractor') == 'vlm']
    ok = (rc_p == 0 and rc1 == 0 and rc2 == 0 and rc5 == 0 and skeleton_ok
          # ① 文本链把 T3 记成"待视觉取证"并**指了路**（原先它是 ok / 零证据 / 没有 reason）
          and img.get('status') == 'skipped' and '视觉取证' in (img.get('reason') or '')
          and 'render_pages' in (img.get('reason') or '')
          # ② 空骨架当场退 1 且**不写补注**
          and rc3 == 1 and 'text' in out3 and not (d / 'none.notes.json').exists()
          # ③ 填好之后：补注 unreadable→? 这一侧 + 合并后 `ok`/`vlm`/[inferred]，且**覆盖被打印**
          and rc4 == 0 and vels and all(e.get('certainty') == 'inferred' for e in vels)
          and img2.get('status') == 'ok' and img2.get('extractor') == 'vlm'
          and 'skipped → ok' in out5)
    cases.append(('64 T3 → 视觉取证整条通道（§1.3 / §1.5 手段 2）：文本链把 T3 记「待视觉取证」并指路 · '
                  '**空骨架退 1 不写补注** · 填好后两路合并 ⇒ `ok`/`vlm`/`inferred`、覆盖被打印',
                  ok, (rc1, rc2, rc3, rc4, rc5),
                  (out1[-160:] + out3[-160:] + out5[-260:] + str(img)[:160]) if not ok else ''))
    # 反例②：`extractor=vlm` 却自称 `certainty=direct` ⇒ 账本**当场不落盘**（§1.3：视觉是推断）
    if todo:
        bad = json.loads(json.dumps(todo))
        bad[0]['certainty'] = 'direct'
        (d / 'vision-bad.json').write_text(json.dumps(bad, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8', newline='\n')
        rc6, out6 = run([sys.executable, str(LEDGER), '--materials', str(d / 'materials.json'),
                         '--elements', str(d / 'vision-bad.json'), '--task', 'vlm',
                         '-o', str(d / 'evidence-bad.json')])
        cases.append(('64b `vlm` 不许自称 `direct`：账本校验退 1 且**不落盘**（§1.3 的机器拦）',
                      rc6 == 1 and 'inferred' in out6 and not (d / 'evidence-bad.json').exists(),
                      rc6, out6[-200:]))
    return cases


def main(argv=None):
    """造夹具 → 比 `drift` 读数 → 跑漂移 13 + 清点 3 + 取子集 10 + 能力指纹 3 + pptx 4 + 材料树若干 + 规范 1 条路径

    （"若干"是刻意的：材料树那批路径按**审计抓到的问题**一条条长出来，写死一个数就会天天改这一行。）
    """
    sys.stdout.reconfigure(encoding='utf-8')
    root = pathlib.Path(argv[0]) if argv else pathlib.Path(tempfile.mkdtemp(prefix='pipeline-fix-'))
    root.mkdir(parents=True, exist_ok=True)
    print(f'夹具目录：{root}')
    make_fixture(root)
    ok, out = ledgerize(root)
    if not ok:
        print(f'✗ 账本没写出来：{out.strip()[-300:]}')
        return 2
    ok, out = intakeize(root)                       # 清点骨架由**产品的写入器**出（见 intakeize）
    if not ok:
        print(f'✗ 清点骨架没写出来：{out.strip()[-300:]}')
        return 2
    rc, out, draft = build(root)
    head = '✓ 漂移 3 条 · 缺口 3 条' in out
    print(f'{"PASS" if rc == 0 and head else "FAIL"}  ⓪ 读数：{out.splitlines()[0] if out else "（无输出）"}')
    bad = 0 if (rc == 0 and head) else 1
    # ⓪b D1 **只认"证据被削弱"的降级**：`M01#p001`（抽取质量）该报，`M01#p002`（只有浏览摘录截断）
    # 不该报——2026-09-18 真材料集上实测：不分类时，一份每个节点都规矩引条款的表被报成 23 条"等级拔高"。
    d1_ok = 'M01#p001' in (root / 'drift.md').read_text(encoding='utf-8') \
        and 'M01#p002' not in (root / 'drift.md').read_text(encoding='utf-8')
    print(f'{"PASS" if d1_ok else "FAIL"}  ⓪b D1 不把"浏览摘录截断"当等级拔高（`M01#p002` 不许出现）')
    bad += 0 if d1_ok else 1
    for name, good, rc, out in (paths(root, draft) + intake_paths(root) + plan_paths(root)
                                + query_paths(root) + capability_paths(root) + vlm_paths(root)
                                + pptx_paths(root) + materials_paths(root) + import_paths(root)
                                + spec_paths()):
        print(f'{"PASS" if good else "FAIL"}  {name}  （rc={rc}）')
        if not good:
            print('      ' + out.strip().replace('\n', '\n      ')[:500])
            bad += 1
    dirty = repo_root_clean()
    print(f'{"PASS" if not dirty else "FAIL"}  ㉗ 跑完没往仓库根写字节'
          + (f'（多出：{"、".join(dirty)}）' if dirty else ''))
    bad += 1 if dirty else 0
    print(f'—— {"全部符合预期" if not bad else f"{bad} 条不符合预期"}（夹具：{root}）')
    if argv:
        return 0 if not bad else 1
    shutil.rmtree(root, ignore_errors=True)          # 临时目录自己收（`--out` 给了就留着）
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
