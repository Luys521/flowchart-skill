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
    elements = [_elem('M01#p001', degraded='quote 截断到 200 字'), _elem('M03#p001', sheet='短名单'),
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
            ('intake.COLUMNS', intake.COLUMNS), ('recon.CARD_COLUMNS', recon.CARD_COLUMNS),
            ('plan.FLOW_COLUMNS', plan.FLOW_COLUMNS), ('plan.ASK_COLUMNS', plan.ASK_COLUMNS),
            ('plan.EXCL_COLUMNS', plan.EXCL_COLUMNS))
    missing = [name for name, cols in want if '| ' + ' | '.join(cols) + ' |' not in spec]
    return [('㊶ 规范 ↔ 仪器：§1.5 / §3 / §4.1 / §5.3 / §5.4 的表头逐字等于仪器列规范',
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
            c[6] = '待澄清' if name == '白板流程' else ('可落表' if c[6] == '—' else c[6])
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
    dirs = root / 'plan-dirs'
    for n in ('资质审查', '采购申请', '结算付款'):
        (dirs / n).mkdir(parents=True, exist_ok=True)
    rc1, out1 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(dirs)])
    (dirs / '白板流程').mkdir(exist_ok=True)
    rc2, out2 = run([sys.executable, str(PLAN_CMD), 'check', str(root / 'plan-ok.md'),
                     '--intake', str(root / 'intake.md'), '--root', str(dirs)])
    cases.append(('㊻ §4.4 ②：计划 4 条 / 目录 3 个 ⇒ 退 1（点出缺哪条）；补齐 ⇒ 退 0',
                  rc1 == 1 and '白板流程' in out1 and rc2 == 0, rc1, (out1[-160:] + out2[-160:])))

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
                     '挂在': '—', '与其它流程': '—', '并行组': '`G1`', '状态': '待澄清'}],
             '范围外': [],
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
                '| 待澄清 |' in d_sp and '主体 = 夹具的两个甲方' in d_sp and rc2 == 0)
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
    cases.append(('⑭ 只给 rows= 不许把命中筛成 0（它只管显示）', rc == 0 and '命中 58 条' in out, rc, out))
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
    return cases


def main(argv=None):
    """造夹具 → 比 `drift` 读数 → 跑漂移 13 + 清点 3 + 取子集 9 + pptx 4 + 材料树若干 + 规范 1 条路径

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
    for name, good, rc, out in (paths(root, draft) + intake_paths(root) + plan_paths(root)
                                + query_paths(root) + pptx_paths(root) + materials_paths(root)
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
