# -*- coding: utf-8 -*-
"""gates.py — 面②：门禁拦截。坏输入必须被拦住，好输入不许被误拦。

run_face 只做编排：**每个主题一个子函数**（结构坏例 / 分层 / 反例 / 质量门禁 / 重叠谓词 /
CLI 失败路径 / 泳道 / 流程并行分支 / 微残段 / 底色铺满 / 回写保真 / 覆盖门禁 / HTML 健壮性 /
标签 / 几何复用提示 / AI 推断留痕 / 澄清阶段 / 产物审核 / 产物几何自检 / init / xml_reader /
渲染器注册表 / 降级 / 子流程下钻 / 主干边流光 / 产物命名 / 单文件多视图 / 配色契约 /
节点类型 / drawio 权重 / 表被直改……）。**完整清单以 `run_face` 的调用为准**，这里只报家族名：
抄一份穷举名单进 docstring，等于给自己留一处必然过期的地方（实测已漂过一次）。
**每个用例自带合成夹具**（`_wb_project` / `_fixture` 一族）：样例是给人看的格式基准，用例的规模与结构
该由用例自己钉住——借样例的话，样例一改就有一堆用例跟着红，别人还看不出该改哪边（D-42）。
子函数之间互不共享状态。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import BASE, HEAD, SKILL, Case, prod, relp, row, run  # noqa: E402
from engine import load  # noqa: E402
from geometry import ortho_cross, seg_overlap  # noqa: E402
from semantics import ARROW_END_SIZE, ARROW_LEN  # noqa: E402

#: 基准样例的**目录名**（examples/ 与 dev/baseline/ 下的同名目录，D-66）。
# 它现在只用于"产物形态"这一件事（`_base`：把基线产物当**现成产物**复核 `validate --artifact`）；
# 用例的**夹具**一律自造（`_wb_project` 一族，D-42）——原先的 `_src()` 已随那次改造删掉。
SAMPLE = 'workflow'


def _base(ext=None):
    """基准样例的**产物**路径：产物住 `dev/baseline/`（examples/ 只留事实源，见 D-66）。"""
    return prod(BASE / SAMPLE, ext) if ext else (BASE / SAMPLE)

OK = [row('受理', '01', '收到申请', '开始', '甲方', '受理员', '—', '→02', '★'),
      row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—', '齐全→03 ｜ 不齐→回 01', '★'),
      row('核验', '03', '现场核验', '任务', '乙方', '工程师', '3个工作日', '→04'),
      row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—')]

BAD = [
    ('H1 缺结束节点', 'H1', [OK[0], OK[1], row('核验', '03', '现场核验', '任务', '乙方', '工程师', '3个工作日', '→04')]),
    ('H1 缺开始节点', 'H1', [OK[1], OK[2], OK[3]]),
    ('H2 编号重复', 'H2', OK + [row('归档', '04', '重复编号', '任务', '甲方', '甲', '—', '—')]),
    ('H3 引用不存在', 'H3', [OK[0], OK[1], row('核验', '03', '现场核验', '任务', '乙方', '工程师', '3个工作日', '→99')]),
    ('H4 判断只有一个分支', 'H4', [OK[0], row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—', '齐全→03'), OK[2], OK[3]]),
    ('H5 结束节点有出边', 'H5', [OK[0], OK[1], OK[2], row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '→02')]),
    ('H6 无判断的死循环', 'H6', [row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→02'),
                            row('受理', '02', '登记', '任务', '甲方', '甲', '—', '→01')]),
    ('H7 名称为空', 'H7', [OK[0], row('受理', '02', ' ', '任务', '甲方', '甲', '—', '→03'), OK[2], OK[3]]),
    ('H7 执行主体为空', 'H7', [OK[0], row('受理', '02', '登记', '任务', ' ', '甲', '—', '→03'), OK[2], OK[3]]),
    # 分支数量够、但没写条件：图上两条线长得一样，读者无从分辨该走哪条
    ('H4 判断分支缺标签', 'H4', [OK[0], row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                      '→03 ｜ →回 01'), OK[2], OK[3]]),
    # 数字开头却带两级后缀：ID_RE 会把它静默截成 03a，可能连到错的节点却无任何提示
    ('H2 编号非法（10aa）', 'H2', [row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→03aa'),
                              row('受理', '03aa', '登记', '任务', '甲方', '甲', '—', '→04'),
                              row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—')]),
    # 中文开头的编号原先一路放行（只判"数字开头"），直到取边阶段才以"无法解析「下个节点」段"
    # 报错——错误位置指向**别的列**。字母开头仍放行（外部 drawio 导入的原样 id，G36）。
    ('H2 编号非法（中文编号）', 'H2', [row('受理', '材料', '收到申请', '开始', '甲方', '甲', '—', '→02'),
                                row('受理', '02', '登记', '任务', '甲方', '甲', '—', '→03'),
                                row('归档', '03', '归档', '结束', '双方', '双方共责', '—', '—')]),
    # H8 逻辑连通：结构写法都对、但流程走不通。这类缺陷渲染出来是一张看着完整的图，
    # 八项质量门禁也全绿（它只管线条与方框），只有 H8 能拦住。
    ('H8 孤儿节点', 'H8', OK + [row('孤儿', '07', '没人指向它', '任务', '乙方', '乙', '—', '→04')]),
    ('H8 死胡同', 'H8', [OK[0], OK[1],
                     row('核验', '03', '现场核验', '任务', '乙方', '工程师', '3个工作日', '→03a'),
                     row('核验', '03a', '走进去出不来', '任务', '乙方', '乙', '—', '—'), OK[3]]),
    ('H8 判断分支目标重复', 'H8', [OK[0], row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                       '是→03 ｜ 否→03'), OK[2], OK[3]]),
    ('H8 分支标签重复', 'H8', [OK[0], row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                     '通过→03 ｜ 通过→05'), OK[2],
                          row('核验', '05', '另一路', '任务', '乙方', '乙', '—', '→04'), OK[3]]),
    ('H8 结束不可达', 'H8', [OK[0], OK[1], OK[2],
                        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—'),
                        row('归档', '09', '另一个归档', '结束', '双方', '双方共责', '—', '—')]),
    # 分号是内容字符、不是分隔符。误用它会把两个出口并成一个，静默丢掉第二条——
    # 必须当场拦下，而不是等它悄悄产出缺边的图。
    ('H3 用分号当分隔符', 'H3', [OK[0],
                          row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                              '齐全→03；不齐→回 01'), OK[2], OK[3]]),
    # 分层重构后补齐编号的两条：以前它们不带 H 编号，报错里看不出归哪一层管。
    ('H2 缺节点编号', 'H2', [row('受理', '', '无编号行', '任务', '甲方', '甲', '—', '—'),
                          OK[0], OK[1], OK[2], OK[3]]),
    ('H7 未知节点类型', 'H7', [OK[0], row('受理', '02', '登记', '大象', '甲方', '甲', '—', '→03'),
                            OK[2], OK[3]]),
    # 「终端子流程」已删（D-74）：一张图可以有多个「结束」，旁支终点不再单设类型。
    # 留着这条是**防止它悄悄回潮**——再写这个类型必须被 H7 当未知类型拦下。
    ('H7 已删类型「终端子流程」', 'H7', [OK[0], OK[1],
                                   row('核验', '03', '签约子流程', '终端子流程', '乙方', '乙', '—', '—'),
                                   OK[3]]),
]


def _structure_bad_cases(c, tmp):
    c.section('结构校验：坏输入必须被拦，且报错指向具体节点')
    for name, code, rows in BAD:
        p = tmp / f'{name.replace(" ", "_")}.md'
        p.write_text(HEAD + ''.join(rows), encoding='utf-8')
        rc, out = run('table_to_dsl.py', '--check', p)
        c.check(rc == 1 and code in out, name, '报错含 ' + code if rc == 1 else f'rc={rc}（应当为 1）')

    # ── G37：H4 的文案只说**数量**（判据数的是全部出边，"带标签"是另一条判据）──────────
    p = tmp / 'h4_msg_one_labeled.md'
    p.write_text(HEAD + ''.join([OK[0],
                                 row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—', '齐全→03'),
                                 OK[2], OK[3]]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    bad_msg = '需 ≥2 个带标签分支' in out
    c.check(rc == 1 and 'H4' in out and not bad_msg,
            'H4 分支不足时的文案只谈**数量**（1 条带标签分支不许看到"需 ≥2 个带标签分支"）',
            out.strip().splitlines()[-1][:80] if rc else f'rc={rc}')

    # ── G35：字段登记表的「行动所需时间 = 格式 min-max 单位」原先零实现 ──────────────
    p = tmp / 'h7_time_format.md'
    p.write_text(HEAD + ''.join([OK[0],
                                 row('受理', '02', '登记', '任务', '甲方', '甲', '尽快', '→03'),
                                 OK[2], OK[3]]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and '行动所需时间' in out and 'H7(软)' in out,
            '「行动所需时间」不合格式 ⇒ **软提示**（不阻断：rc 0 + 点出那一列）',
            out.strip().splitlines()[-1][:80] if rc == 0 else f'rc={rc}（软提示不许阻断）')
    p = tmp / 'h7_time_ok.md'
    p.write_text(HEAD + ''.join([OK[0],
                                 row('受理', '02', '登记', '任务', '甲方', '甲', '3个工作日', '→03'),
                                 OK[2], OK[3]]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and '不像一个量' not in out,
            '合法时间写法（`3个工作日` / `1-2 天` / `—`）不产生格式提示',
            out.strip().splitlines()[-1][:80] if rc == 0 else f'rc={rc}')

    c.section('H6 回归：绕过判断节点的并联捷径，死循环不许漏报')    # 旧算法的漏报形态：03→04→05→06→03 这个环上全是任务节点，但 04 有一条并联出口
    # →07（判断）绕到 05/08。只要图里**存在**判断节点就放行，环本身无出口的事实被掩盖。
    # 07 的分支在这里带标签（原始场景是裸 →05｜→08）：裸分支会先吃 H4，把 H6 淹掉。
    p = tmp / 'h6_shortcut.md'
    p.write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '系统', '系统', '—', '→03'),
        row('一', '03', '初审', '任务', '专员', '专员', '—', '→04'),
        row('一', '04', '分派', '任务', '专员', '专员', '—', '→05 ｜ →07', '并联出口'),
        row('一', '05', '修正', '任务', '专员', '专员', '—', '→06'),
        row('一', '06', '归档', '任务', '专员', '专员', '—', '→回 03'),
        row('一', '07', '复核', '判断', '经理', '经理', '—', '通过→05 ｜ 否→08'),
        row('一', '08', '结束', '结束', '系统', '系统', '—', '—'),
    ]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    # 错误行带列表前缀（print('   -', m)），按内容匹配而不是行首
    h6s = [l.strip() for l in out.splitlines() if 'H6 死循环无出口' in l]
    # 回路必须是 03→04→05→06→03（四个节点都在、且不带捷径上的 07）
    hit = bool(h6s) and all('死循环无出口' in l
                            and all(n in l for n in ('03', '04', '05', '06')) and '07' not in l
                            for l in h6s)
    c.check(rc == 1 and hit, 'H6 死循环无出口被报出（回路 03→04→05→06→03）',
            h6s[0][:90] if h6s else out.strip()[:90])


def _fm(*kv_lines):
    """frontmatter 身份块（表头规范 v3，D-59）：`_fm('id: x', 'level: L0')` → '---\\n…\\n---\\n\\n'。"""
    return '---\n' + '\n'.join(kv_lines) + '\n---\n\n'


def _cfg_rows(*pairs):
    """正文「## 渲染配置」小节（D-59）：`_cfg_rows(('输出布局', '泳道'))` → 小节文本。"""
    rows = '\n'.join(f'| {k} | {v} |' for k, v in pairs)
    return f'## 渲染配置\n\n| 键 | 值 |\n|---|---|\n{rows}\n\n'


def _color_section(pairs):
    """正文「## 主体配色」小节（D-59）：pairs = [(主体, hex), …]。"""
    rows = '\n'.join(f'| {who} | {c} |' for who, c in pairs)
    return f'## 主体配色\n\n| 执行主体 | 颜色 |\n|---|---|\n{rows}\n\n'


_CN_HEX = {'蓝': '#dae8fc', '绿': '#d5e8d4', '橙': '#ffe6cc', '黄': '#fff2cc',
           '紫': '#e1d5e7', '红': '#f8cecc', '灰': '#ffffff'}


def _color_section_names(decl):
    """旧颜色名声明串（'用户=蓝 ｜ 机器=橙'）→ 「## 主体配色」小节文本（D-59 hex）。

    色名表里没有的名字**原样保留**（如「柠檬绿」）——它会以非 hex 的身份流到
    _color_map 被'不是合法 hex'拦下，坏声明用例因此仍能测到产品校验。
    没有 `=` 的段跳过（表格结构本身保证了键值成对，这种形态已不可能出现）。
    """
    if not decl:
        return ''
    rows = []
    for pair in re.split(r'[｜|]', decl):
        if '=' not in pair:
            continue
        who, cn = pair.split('=', 1)
        cn = cn.strip()
        rows.append(f'| {who.strip()} | {_CN_HEX.get(cn, cn)} |')
    return _color_section([(m.group(1), m.group(2)) for m in
                           (re.match(r'\| (.+) \| (#\w+|\S+) \|', r) for r in rows) if m])


def _check_header_rules(c, tmp):
    c.section('H9 表头规范：身份键封闭 / refs 存在 / parent·level 双向一致（D-59）')
    body = HEAD + ''.join(OK)
    # 未知键：frontmatter 键封闭——`输出layou` 这类笔误被静默忽略会整条丢失语义（H3 同类）
    p = tmp / 'h9_unknown.md'
    p.write_text(_fm('statuz: draft') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and 'H9' in out and 'statuz' in out,
            '未知元信息键被拦（报错列出合法键）', out.strip().splitlines()[-1][:70] if rc else '')

    # 派生量禁入：层级号/子表清单由 ⊞ 声明推导（layer_index），写进 frontmatter 必漂移
    p = tmp / 'h9_derived.md'
    p.write_text(_fm('层级号: 2') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and '派生量' in out, '层级号/子表清单禁入表头（派生量）')

    # refs：依赖路径必须真实存在（相对本流程表目录）
    p = tmp / 'h9_src_missing.md'
    p.write_text(_fm('refs: [不存在的PRD.md]') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and 'refs 依赖不存在' in out, 'refs 指向不存在的依赖被拦')

    # refs 的空条目（G38）：同一组规则的 parent / level / id 空值都拦了，refs 原先被 `if item`
    # 整个跳过 ⇒ `refs: ['']` 静默通过，而 spec §3「H9 空值」把四者并列。
    p = tmp / 'h9_refs_empty.md'
    p.write_text(_fm("refs: ['']") + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and 'refs 有空条目' in out, 'refs 的空条目被拦（写了键就不能是空值）')

    # frontmatter 只有开行、没有闭合 `---`（G68）：整块身份区会被当成正文、键全丢却一个字都不报
    # —— 那是"静默丢语义"，必须由 H9 报出来。
    p = tmp / 'h9_unclosed.md'
    p.write_text('---\nid: x\nlevel: L0\n' + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and 'H9' in out and '没有闭合' in out,
            'G68 frontmatter 缺闭合 `---` ⇒ H9 报出来（原先整块被静默忽略）',
            (out.strip().splitlines() or [''])[-1][:60] if out.strip() else '')

    # 条目式元信息已废弃：表头区（frontmatter 之后、表格之前）不许再出现 `- 键：值` 条目，
    # 否则两套表头机制混用，早晚漂移
    p = tmp / 'h9_bullet.md'
    p.write_text('# 标题\n\n- 输出布局：泳道\n\n' + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and '表头区不放条目' in out, '表头区条目式元信息被拦（防两套机制混用）')

    # parent 双向一致（D-58）：① 声明的文件不存在 → 拦
    p = tmp / 'h9_par_missing.md'
    p.write_text(_fm('parent: 不存在的主表.md') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and 'parent 指向的文件不存在' in out, 'parent 指向不存在的文件被拦')

    # ② 声明的文件存在，但里面没有 ⊞ 指回本表 → 拦（声明与 ⊞ 漂移当场抓出）
    (tmp / '孤主表.md').write_text(HEAD + ''.join(OK), encoding='utf-8')
    p = tmp / 'h9_par_noback.md'
    p.write_text(_fm('parent: 孤主表.md') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and '双向不一致' in out, 'parent 里没有指回本表的 ⊞ → 拦（双向不一致）')

    # ③ level 声明与 ⊞ 推导不一致 → 拦（无父表的主表派生 L0，声明 L2 必不一致）
    p = tmp / 'h9_level.md'
    p.write_text(_fm('level: L2') + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1 and '不一致' in out, 'level 声明与 ⊞ 推导不一致被拦（D-59）')

    # ④ 合法表头放行：身份键齐全 + parent/level 双向一致 + refs 存在 → rc 0
    par = tmp / '合法主表.md'
    par.write_text(HEAD + row('一', 'M1', '总入口', '开始', '甲方', '甲', '—', '→M2', '⊞ h9_ok.md；下钻') +
                   row('一', 'M2', '总收尾', '结束', '甲方', '甲', '—', '—'), encoding='utf-8')
    (tmp / '真实PRD.md').write_text('# 需求\n', encoding='utf-8')
    p = tmp / 'h9_ok.md'
    p.write_text(_fm('id: h9-ok', 'level: L1', 'parent: 合法主表.md',
                     'refs: [真实PRD.md]', 'description: 演示子流程')
                 + body, encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and 'H9表头' in out, '合法表头（身份键齐全 + parent/level 双向一致）放行',
            out.strip().splitlines()[0][:70] if rc == 0 else '')


def _check_layering(c, tmp):
    c.section('检查分层：①节点 → ②类型 → ③关系，同一个节点不重复报')
    # 分层是"运行顺序 + 归属"，不是排版：① 错了后面全免谈（编号被截断会让③连错节点、
    # 报一串指向错处的假错）；② 能判的不要拖到③，否则"结束节点居然有出边"会被
    # 淹在一堆连通性报错里。这两条性质一旦破了不会报错、只会让报错变得难读，所以要钉住。
    p = tmp / 'layers.md'
    p.write_text(HEAD + ''.join([
        row('受理', '', '无编号行', '任务', '甲方', '甲', '—', '—'),        # ① H2
        row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→02'),
        row('受理', '02', '资料齐全？', '判断', '甲方', '甲', '—', '是→03'),  # ② H4 只有 1 个分支
        row('核验', '03', '现场核验', '任务', '乙方', '乙', '—', '→99'),      # ③ H3 引用不存在
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—'),
    ]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 1, '三层各带一个坏例时被拦下')
    i2, i4, i3 = out.find('H2 行1'), out.find('H4 判断节点 02'), out.find('H3 节点 03')
    c.check(0 <= i2 < i4 < i3, '报错按 ①节点 → ②类型 → ③关系 依次出现',
            f'位置 H2@{i2} H4@{i4} H3@{i3}')

    # "死胡同"由 ② 判（只看自己有没有出边），③ 必须让位——否则同一个节点挨两条报错，
    # 节点越多的表报错越吵。这条是三层切分里唯一需要跨层让步的地方。
    p = tmp / 'nodup.md'
    p.write_text(HEAD + ''.join([
        row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→02'),
        row('受理', '02', '处理', '任务', '甲方', '甲', '—', '→03'),
        row('核验', '03', '卡住不动', '任务', '乙方', '乙', '—', '—'),      # 有入边、无出边 → 死胡同
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—'),
    ]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(out.count('死胡同节点 03') == 1, '死胡同只报一次（②判、③让位）',
            f'报了 {out.count("死胡同节点 03")} 次')

    c.section('跨层让步：一个节点只报最可操作的那一条')
    # "没有出边"有两种成因、两句话：真填了 —（死胡同）vs 目标编号不存在（H3）。
    # 不分开就会自相矛盾——提示写着「下个节点」应为 —，可用户明明填了东西。
    p = tmp / 'dangling.md'
    p.write_text(HEAD + ''.join([
        row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→02'),
        row('受理', '02', '处理', '任务', '甲方', '甲', '—', '→99'),      # 99 不存在
        row('归档', '03', '归档', '结束', '双方', '双方共责', '—', '—'),
    ]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check('H3' in out and '死胡同节点 02' not in out and '孤立节点 02' not in out,
            '目标编号写错：只报 H3，不叠一条自相矛盾的"没有出边"',
            out.strip().replace(chr(10), ' | ')[:88])

    # 真·孤立（填了 —、无人指向）要报"孤立"；真·死胡同（有入边、填了 —）要报"死胡同"。
    p = tmp / 'lonely.md'
    p.write_text(HEAD + ''.join([
        row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→02'),
        row('受理', '02', '处理', '任务', '甲方', '甲', '—', '—'),        # 有入边 → 死胡同
        row('核验', '03', '整行脱离', '任务', '乙方', '乙', '—', '—'),    # 无入无出 → 孤立
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—'),
    ]), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check('孤立节点 03' in out and '死胡同节点 02' in out and '死胡同节点 03' not in out,
            '孤立与死胡同各归其位（无入无出→孤立；有入无出→死胡同）')
    # 这条守的是"入边要求不许搬进 ② 类型层的规则表"这个已定案的设计：
    # 搬进去后，无入无出的节点会同时吃到"孤儿"和 ③ 的"孤立"——两句话说的是同一件事。
    # 不看是哪一层报的，只数这个节点被点名几次，所以以后换实现也照样守得住。
    hits03 = [l.strip() for l in out.splitlines() if 'H8' in l and '节点 03' in l]
    c.check(len(hits03) == 1, '同一个节点只被点一次名', '；'.join(h[:44] for h in hits03))
    # 结束节点的"没人指向我"专名叫「不可达」——不再叠一条泛泛的「孤儿」，两句话说的是同一件事。
    c.check('结束节点 04 不可达' in out and '孤儿节点 04' not in out,
            '结束节点没人指向：只报「不可达」，不叠「孤儿」',
            out.strip().replace(chr(10), ' | ')[:88])


def _check_false_positives(c, tmp):
    c.section('反例：好输入不许被误拦')
    p = tmp / 'soft.md'
    p.write_text(HEAD + ''.join([OK[0], row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                          '全部资料齐全无误→03 ｜ 资料不齐全需补件→回 01'), OK[2], OK[3]]),
                 encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and '软提示' in out, '长分支标签：只软提示、不阻断')
    p = tmp / 'loop.md'
    p.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0, '合法回路（含判断）放行')


def _check_quality_gates(c, tmp):
    c.section('质量门禁：该拦的拦、该修的自愈')
    # 自带一张最小合成表当基准——不借样例：examples/ 只留自举那一个，测试不该依赖它的规模。
    fix = tmp / 'gatefix.md'
    fix.write_text(HEAD + ''.join([
        row('受理', '01', '收到申请', '开始', '甲方', '甲', '—', '→01a', '★'),
        row('受理', '01a', '资料齐全？', '判断', '甲方', '甲', '—', '齐全→02 ｜ 不齐→03', '★'),
        row('核验', '02', '现场核验', '任务', '甲方', '乙', '3个工作日', '→03'),
        row('归档', '03', '归档', '结束', '甲方', '甲', '—', '—'),
    ]), encoding='utf-8')
    yfix = tmp / 'gatefix.yaml'
    rc, out = run('table_to_dsl.py', '--write', fix, '-o', yfix)
    if not c.check(rc == 0, '合成基准表可转 DSL', out.strip()[-80:]):
        return
    base = yfix.read_bytes()
    off = tmp / 'off_grid.yaml'
    off.write_bytes(re.sub(rb'  - 400(\r?\n)', rb'  - 442\g<1>', base, count=1))
    rc, out = run('validate.py', off)
    c.check(rc == 0 and '网格吸附' in out, '离格 col_x：吸附 + 提示，不阻断')

    src = yfix.read_text(encoding='utf-8')
    over = tmp / 'overlap.yaml'
    over.write_text(re.sub(r"(- id: '03'\n(?:.*\n)*?  row: )\d", r'\g<1>1', src), encoding='utf-8')
    rc, out = run('validate.py', over)
    c.check(rc == 1 and '节点重叠: ' in out, '两节点叠到同一格：报节点重叠')

    # 线必须真的接到节点上：把锚点偏移推到节点外（sdye 远超半宽）→ 第 4 项要报"线没接上节点"。
    # 这条以前没有任何检查：sdye/dye/端口算错时线悬在节点外，其余七项照样全绿。
    detach = tmp / 'detach.yaml'
    detach.write_text(src.replace("- from: '01'\n  to: 01a\n",
                                  "- from: '01'\n  to: 01a\n  sdye: 200\n", 1), encoding='utf-8')
    rc, out = run('validate.py', detach)
    c.check(rc == 1 and '线没接上节点' in out, '端点悬在节点外：报"线没接上节点"')

    # 判据必须按**真实形状**：菱形内接于外接矩形，只有边中点与矩形重合——只比外接矩形
    # 会放行"线悬在菱形斜边外 16~27px"（实测 12→13），那正是用户看到的"箭头没搭到框上"。
    from validate import _on_border
    diamond = (320, 1630, 160, 80)            # 外接矩形；顶点为左边中点 (320, 1670)
    c.check(_on_border((320, 1670), diamond, 'rhombus'), '菱形顶点：判为接住')
    c.check(not _on_border((320, 1650), diamond, 'rhombus'), '菱形沿边偏 20px：判为悬空')
    c.check(_on_border((320, 1650), diamond, 'rounded'), '矩形类同一点：判为接住')


def _check_overlap_predicate(c):
    c.section('第 5 项谓词：正交交叉放行、共线重叠拦下')
    pred_cases = [
        ('正交交叉不判重叠', ((0, 0), (100, 0)), ((50, -50), (50, 50)), False),
        ('T 形相接不判重叠', ((0, 0), (100, 0)), ((50, 0), (50, 80)), False),
        ('端点为界不判重叠', ((0, 0), (100, 0)), ((100, 0), (200, 0)), False),
        ('平行不共线不判重叠', ((0, 0), (100, 0)), ((0, 40), (100, 40)), False),
        ('水平共线重叠要判出', ((0, 0), (100, 0)), ((50, 0), (150, 0)), True),
        ('竖直共线重叠要判出', ((0, 0), (0, 100)), ((0, 50), (0, 150)), True),
    ]
    for nm, s1, s2, want in pred_cases:
        c.check(seg_overlap(s1, s2) == want, nm + (' → 重叠' if want else ' → 不重叠'))


def _check_cli_failure_paths(c, tmp):
    c.section('validate.py 的失败路径（曾经会假通过 / 抛 traceback）')
    rc, out = run('validate.py')
    c.check(rc != 0 and 'Traceback' not in out and 'required' in out, '缺参数：报错而不是去校验样例')
    rc, out = run('validate.py', 'output/不存在.yaml')
    c.check(rc == 1 and 'Traceback' not in out and '找不到' in out, '路径不存在：友好报错')
    rc, out = run('validate.py', '--help')
    c.check(rc == 0 and 'usage' in out.lower(), '--help 可用')

    # 自带一张**多列**合成表（2026-09 改）：原先借自举样表的 yaml 来复现"新增列却没补 col_x"，
    # 而自举表改版后成了单列（col_x: [400]），那条路径就没东西可替换了。
    # **用例不该依赖样例的结构**（样例换个形状就该红吗？）——这与 `_lib` 的既有约定一致。
    src = tmp / 'colover' / 'flowtable.md'
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(HEAD + ''.join([
        row('一', '01', '发起', '开始', '甲方', '甲', '—', '→02'),
        row('一', '02', '走哪条？', '判断', '甲方', '甲', '—', '走A→03 ｜ 走B→03b'),
        row('一', '03', 'A 路', '任务', '甲方', '甲', '—', '→04'),
        row('一', '03b', 'B 路', '任务', '甲方', '甲', '—', '→04'),
        row('二', '04', '收尾', '结束', '甲方', '甲', '—', '—'),
    ]), encoding='utf-8')
    full = prod(src.parent, 'yaml')
    run('table_to_dsl.py', '--write', src, '-o', full)
    raw = full.read_text(encoding='utf-8')
    drop = tmp / 'col_over.yaml'
    # 多列产物的 col_x 写成 `[]`（由字典 col_pitch 展开）——这里塞回一个只有 1 列的显式表，
    # 复现"新增列却没补 col_x"。空表当成缺省单列是另一码事，另有断言守着。
    assert '  col_x: []' in raw, '前置：合成表应产出多列（col_x 留空）'
    drop.write_text(raw.replace('  col_x: []', '  col_x:\n  - 400', 1), encoding='utf-8')
    rc, out = run('validate.py', drop)
    c.check(rc == 1 and '列号越界' in out and 'Traceback' not in out,
            'col_x 列数不够：中文报错而不是 IndexError')

    # 外部 drawio 导入的原样 id（n1 / node-3）不能被引号规则的编号校验误拦
    p = tmp / 'extid.md'
    p.write_text(HEAD + ''.join([row('受理', 'n1', '收到申请', '开始', '甲方', '甲', '—', '→n2'),
                                 row('受理', 'n2', '登记', '任务', '甲方', '甲', '—', '→n3'),
                                 row('归档', 'n3', '归档', '结束', '双方', '双方共责', '—', '—')]),
                 encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0, '外部 id（n1/n2/n3）放行', '编号格式校验只约束数字开头')

    # `｜` 是唯一的分隔符；注解里出现分号是合法的（那是内容，不是分隔符），不许被误拦
    p = tmp / 'sep.md'
    p.write_text(HEAD + ''.join([OK[0],
                                 row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                     '齐全→03 ｜ 不齐→回 01 补件；需复核'), OK[2], OK[3]]),
                 encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0, '｜ 分隔 + 注解里的分号：放行', out[-90:] if rc else '')

    # 多出口不是判断节点的特权：任务节点同样可以用 `｜` 分开走两条路——那是**并行**（全都走），
    # 标签只是路线名。并行与排斥的判据是**类型**，不是标签（D-74）。
    p = tmp / 'taskfan.md'
    p.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '分派登记', '任务', '甲方', '受理员', '—', '走A→03 ｜ 走B→05'),
        OK[2], row('核验', '05', 'B 路处理', '任务', '乙方', '乙', '—', '→04'), OK[3]]),
        encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and '边(解析):5' in out, '任务节点多出口（带路线名）：放行且解析出 2 条边', out.strip()[-90:])

    # 并行的极简形态：任务的多条出口**一个标签都不带**。必须放行——无标签正是"全都走"的写法，
    # 而判断节点缺标签照旧被 H4 拦下（那是另一种分叉）。
    p = tmp / 'taskfan2.md'
    p.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '分派登记', '任务', '甲方', '受理员', '—', '→03 ｜ →05'),
        OK[2], row('核验', '05', 'B 路处理', '任务', '乙方', '乙', '—', '→04'), OK[3]]),
        encoding='utf-8')
    rc, out = run('table_to_dsl.py', '--check', p)
    c.check(rc == 0 and '边(解析):5' in out, '任务节点多出口（无标签 = 并行）：放行且解析出 2 条边',
            out.strip()[-90:])

    # ── G49：**旧几何形状不对**（用户手改过 / 旧版本产物）要说人话，不许 KeyError 裸栈 ──────
    p = tmp / 'hint_bad.md'
    p.write_text(HEAD + ''.join(OK), encoding='utf-8')
    bad_yaml = tmp / 'hint_bad.yaml'
    bad_yaml.write_text('nodes:\n  - col: 0\n', encoding='utf-8')     # 缺 `id` 键
    rc, out = run('table_to_dsl.py', '--write', '--layout', bad_yaml, p,
                  '-o', str(tmp / 'hint_bad-flow.yaml'))
    c.check(rc == 2 and '形状不对' in out and 'Traceback' not in out,
            'G49 旧几何形状不对 ⇒ 退 2 + 人话（原先 KeyError 裸栈）',
            (out.strip().splitlines() or [''])[-1][:70] if out.strip() else '')

    # ── G55：`--browser` 指向不存在的路径 ⇒ 人话（原先 FileNotFoundError 裸栈）────────────
    html = tmp / 'shot_src.html'
    html.write_text('<!DOCTYPE html><html><body><svg viewBox="0 0 10 10"></svg></body></html>',
                    encoding='utf-8')
    rc, out = run('shot.py', html, '--browser', str(tmp / '没有这个浏览器.exe'))
    c.check(rc == 1 and '路径不存在' in out and 'Traceback' not in out,
            'G55 `--browser` 路径不存在 ⇒ 退 1 + 人话（原先 FileNotFoundError 裸栈）',
            (out.strip().splitlines() or [''])[-1][:70] if out.strip() else '')

    # ── G71：`--crop 0:0` / `1200:0` 的 `y1=0` 不许被当成"没给上界" ─────────────────────
    rc, out = run('shot.py', html, '--crop', '0:0')
    c.check(rc == 1 and '上界必须大于下界' in out,
            'G71 `--crop 0:0` ⇒ 报"上界必须大于下界"（原先 y1=0 是 falsy、静默变成全高）',
            (out.strip().splitlines() or [''])[-1][:70] if out.strip() else '')


def _check_swimlane_slots(c, tmp):
    c.section('泳道列序 → 槽位模式：行=槽位、列序显式、空泳道保留')
    # 三个性质一起验：① 列序按声明（不再由"谁先出现在表里"决定）；② 行细化为**槽位**，
    # 同阶段内向右交棒同槽、其余开新槽（K = 阶段数 + Φ）；③ 声明了但没人用的泳道仍占一列
    # ——列数只按节点算的话，**尾部**空泳道会整列消失。
    p = tmp / 'lane.md'
    p.write_text(lane_head('泳道验证', '甲部 → 乙部 → 丙部 → 丁部') + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02'),
        row('阶段一', '02', '分派', '任务', '乙部', '乙', '—', '→03 ｜ →04'),
        row('阶段一', '03', '旁支收尾', '结束', '乙部', '乙', '—', '—'),
        row('阶段一', '04', '回甲部', '任务', '甲部', '甲', '—', '→05'),
        row('阶段二', '05', '推进', '任务', '甲部', '甲', '—', '→06'),
        row('阶段二', '06', '收官', '任务', '丙部', '丙', '—', '→07'),
        row('阶段二', '07', '结束', '结束', '丙部', '丙', '—', '—'),
    ]), encoding='utf-8')
    lane_yaml = tmp / 'lane.yaml'
    rc, out = run('table_to_dsl.py', '--write', p, '-o', lane_yaml)
    c.check(rc == 0, '泳道表转 DSL 通过', out.strip()[-90:])
    import yaml as _yaml
    d = _yaml.safe_load(lane_yaml.read_text(encoding='utf-8'))
    c.check(d['meta'].get('lane_order') == ['甲部', '乙部', '丙部', '丁部'],
            '列序按声明写进 meta.lane_order', str(d['meta'].get('lane_order')))
    slot = {n['id']: n['row'] for n in d['nodes']}
    col = {n['id']: n['col'] for n in d['nodes']}
    c.check(slot['01'] == slot['02'] == 0 and slot['03'] == 1 and slot['04'] == 1,
            '同阶段向右交棒同槽、同列/回退开新槽', str(slot))
    c.check(slot['05'] == 2 and slot['06'] == 2 and slot['07'] == 3 and max(slot.values()) + 1 == 4,
            '槽位数 K = 阶段数(2) + Φ(2) = 4', f'{slot} → K={max(slot.values()) + 1}')
    c.check([col['01'], col['02'], col['06']] == [0, 1, 2], '列号按声明序（甲/乙/丙 = 0/1/2）', str(col))
    from engine import load as _load
    ln = _load(str(lane_yaml)).lanes()
    c.check(ln['departments'] == ['甲部', '乙部', '丙部', '丁部'],
            '尾部空泳道仍占一列（列数取声明的泳道数）', str(ln['departments']))
    c.check(ln['stage_spans'] == [('阶段一', 0, 1), ('阶段二', 2, 3)],
            '阶段带按连续行区间合并（一个阶段可跨多行）', str(ln['stage_spans']))
    # 层距严格等距，且每层中线落在 20k+10（矩形四边守粗格）
    ys = [ln['rowy'][r] for r in range(4)]
    c.check(all(b - a == 120 for a, b in zip(ys, ys[1:])), '层距等距 = pitch', str(ys))
    c.check(all((y + 60) % 20 == 10 for y in ys), '每层中线落在 20k+10', str([y + 60 for y in ys]))


def _check_swimlane_slot_spread(c, tmp):
    c.section('泳道槽位：向右交棒要跨过同槽节点时必须另开一槽')
    # 同槽里若已站着夹在两列之间的节点，合并会让这条边横跨它（实测 17→18 跨过 16a：
    # 图上只能贴着框绕、还与别的线交叉）→ 另开一槽（DECISIONS.md D-36）。
    head = (_cfg_rows(('输出布局', '泳道'), ('泳道列序', '甲部 → 乙部 → 丙部'))
            + '# 验证用泳道表\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n')
    p = tmp / 'laneskip.md'
    p.write_text(head + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02'),
        row('阶段一', '02', '分派', '任务', '丙部', '丙', '—', '走A→03 ｜ 走B→04'),
        row('阶段一', '03', '旁支', '任务', '乙部', '乙', '—', '→05'),
        row('阶段一', '04', '回流', '任务', '甲部', '甲', '—', '→06'),
        row('阶段一', '06', '汇合', '任务', '丙部', '丙', '—', '→05'),
        row('阶段二', '05', '收尾', '结束', '丙部', '丙', '—', '—'),
    ]), encoding='utf-8')
    y = tmp / 'laneskip.yaml'
    rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc == 0, '泳道表转 DSL 通过', out.strip()[-80:])
    import yaml as _yaml
    d = _yaml.safe_load(y.read_text(encoding='utf-8'))
    slot = {n['id']: n['row'] for n in d['nodes']}
    c.check(slot['01'] == slot['02'], '向右交棒且中间没人 → 同槽', str(slot))
    c.check(slot['06'] != slot['03'], '向右交棒要跨过同槽节点 → 另开一槽', str(slot))
    c.check(slot['06'] == slot['04'] + 1, '跨节点的那条正好推进一槽', str(slot))


def _check_swimlane_backedge(c, tmp):
    c.section('泳道同行回环：一去一回的反向平行边必须各占走廊一侧')
    # 一对反向平行边（02→01 与 01→02）的错峰符号若同取一侧，两条出线段落在同一 y 上必然共线重叠，
    # 形状合法的 Z 形全被"重叠"罚掉，只能退化成穿自身端点的坏形状（DECISIONS.md D-34）。
    head = (_cfg_rows(('输出布局', '泳道'), ('泳道列序', '甲部 → 乙部 → 丙部'))
            + '# 验证用泳道回环表\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n')
    p = tmp / 'laneback.md'
    p.write_text(head + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02'),
        row('阶段一', '02', '通过？', '判断', '乙部', '乙', '—', '通过→03 ｜ 不通过→回 01'),
        row('阶段一', '03', '处理', '任务', '丙部', '丙', '—', '→04'),
        row('阶段二', '04', '收尾', '结束', '丙部', '丙', '—', '—'),
    ]), encoding='utf-8')
    y = tmp / 'laneback.yaml'
    rc_w, out_w = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc_w == 0, '前置：泳道回环表转 DSL 通过', out_w.strip()[-80:])
    rc, out = run('validate.py', y)
    c.check(rc == 0 and 'Traceback' not in out, '八项门禁全过（不再横穿自身端点）',
            out.strip().splitlines()[-1][:80] if rc else (out.strip()[-100:] if rc != 0 else ''))
    from engine import load as _load
    L = _load(str(y))
    fwd = next(e for e in L.edges if (e['from'], e['to']) == ('01', '02'))
    back = next(e for e in L.edges if (e['from'], e['to']) == ('02', '01'))
    c.check(fwd.get('sdye', 0) * back.get('sdye', 0) < 0, '一去一回的错峰量符号相反',
            f"01→02 sdye={fwd.get('sdye')} / 02→01 sdye={back.get('sdye')}")


def _check_lane_cross_pass(c, tmp):
    c.section('泳道跨趟：本趟自动设下的 sdye 必须还回去（D-82）')
    # 引擎重建布局（探布 → 定案，D-39）时对旧布线器只做一件事：`release()`。端口、`dye`、
    # 「挪到空闲侧」三样都在 `_reset()` 里还，唯独**错峰 `sdye` 没有**——于是第二趟的
    # `stagger_source_anchors` 会把上一趟的自动偏移当成"手填值"（对手填值一律让路），
    # D-31 的孤儿复查因此护不住它（实测 600 个随机泳道图里 6 个留下这种偏移）。这里钉两件事：
    # 自动的还回去、手填的留着。
    head = (_cfg_rows(('输出布局', '泳道'), ('泳道列序', '甲部 → 乙部 → 丙部'))
            + '# 验证用泳道表\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n')
    p = tmp / 'lanecross.md'
    p.write_text(head + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02'),
        row('阶段一', '02', '通过？', '判断', '乙部', '乙', '—', '通过→03 ｜ 不通过→回 01'),
        row('阶段一', '03', '处理', '任务', '丙部', '丙', '—', '→04'),
        row('阶段二', '04', '收尾', '结束', '丙部', '丙', '—', '—'),
    ]), encoding='utf-8')
    y = tmp / 'lanecross.yaml'
    rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc == 0, '前置：泳道跨趟表转 DSL 通过', out.strip()[-80:])
    from engine import load as _load
    L = _load(str(y))
    r = L.router
    auto = list(r._stagger_set)
    if not c.check(bool(auto), '前置：这份夹具真的设下了自动错峰（否则下面的断言空转）',
                   f'_stagger_set={auto}'):
        return
    auto_ids = set(auto)
    # 手填值挑一条**不在**自动集合里的边塞进去：它必须活过 release()（D-31「手填优先」）。
    others = [e for e in L.edges if id(e) not in auto_ids]
    manual = others[0] if others else None
    if manual is not None:
        manual['sdye'] = 40
    r.release()
    leaked = [f"{e['from']}→{e['to']}" for e in L.edges
              if id(e) in auto_ids and e.get('sdye')]
    c.check(not leaked, 'release() 把本趟自动设下的 sdye 还回去了（第二趟不再把它当手填）',
            '；'.join(leaked))
    c.check(manual is None or manual.get('sdye') == 40,
            '手填的 sdye 不被 release() 抹掉',
            f"手填边 {manual['from']}→{manual['to']} 现为 {manual.get('sdye')}" if manual else '')


def _check_swimlane_slot_align(c, tmp):
    c.section('泳道摞顶刻度：纯菱形格不许被推下 10px，提示不许重复')
    # 行中线恒为 `20k+10`，而 160×80 菱形 `摞高/2 = 40 ≡ 0 (mod 20)` ⇒ 摞顶必落在 `20k+10`。
    # 一律吸粗格就会把纯菱形格推下 10px，和同一行的矩形格错开（DECISIONS.md D-33）。
    head = (_cfg_rows(('输出布局', '泳道'), ('泳道列序', '甲部 → 乙部 → 丙部'))
            + '# 验证用泳道表\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n')
    p = tmp / 'lanealign.md'
    p.write_text(head + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02'),
        row('阶段一', '02', '通过？', '判断', '乙部', '乙', '—', '通过→03 ｜ 不通过→05'),
        row('阶段一', '03', '处理', '任务', '丙部', '丙', '—', '→05'),
        row('阶段二', '05', '收尾', '结束', '丙部', '丙', '—', '—'),
    ]), encoding='utf-8')
    y = tmp / 'lanealign.yaml'
    rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc == 0, '泳道表转 DSL 通过', out.strip()[-80:])
    from engine import load as _load
    L = _load(str(y))
    r01, r02 = L.rect('01'), L.rect('02')
    mid = L.grid.rowy[0] + L.grid.row_h[0] / 2
    c.check(abs(r01[1] + r01[3] / 2 - mid) < 1e-9 and abs(r02[1] + r02[3] / 2 - mid) < 1e-9,
            '同行内矩形节点与菱形节点都居中于行中线',
            f'矩形 {r01[1] + r01[3] / 2} / 菱形 {r02[1] + r02[3] / 2} / 行中线 {mid}')
    c.check(r01[1] % 20 == 0 and r02[1] % 20 == 10,
            '矩形格吸粗格(20)、纯菱形格只吸细格(10)', f'矩形顶 {r01[1]} / 菱形顶 {r02[1]}')
    notes = list(L.grid.notes)
    c.check(len(notes) == len(set(notes)), '吸附提示无重复（取值路径无副作用）', str(notes))
    c.check(not [n for n in notes if '摞顶' in n], '纯菱形格不再产生摞顶吸附提示', str(notes))
    rc_b, out_b = run('build.py', p)
    c.check(rc_b == 0 and out_b.count('网格吸附') <= 1, 'build 的吸附提示只出现一行',
            f'出现 {out_b.count("网格吸附")} 次' if rc_b == 0 else f'build rc={rc_b}')


def _check_swimlane_left_corridor(c, tmp):
    c.section('泳道左侧里程碑带：列外走廊按需量出，线不许压带')
    # 左族远通道原先从画布左缘起算，而带子左边那块空地在布局里没被声明为"不可走"——最好走，
    # 于是长回环全压上去了（实测 4 条穿带）。现在左族从带右沿起算，走廊宽度由探布量出（D-38/D-39）。
    head = lane_head('左走廊')
    base = [row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02', ''),
            row('阶段一', '02', '继续？', '判断', '甲部', '甲', '—', '通过→03 ｜ 不通过→回 01', ''),
            row('阶段一', '03', '处理', '任务', '甲部', '甲', '—', '→04', '')]
    cases = [('有同列跨行长跳',
              base + [row('阶段一', '04', '复核', '任务', '甲部', '甲', '—',
                          '继续→05 ｜ 重做→回 02', '')],
              row('阶段二', '05', '收尾', '结束', '甲部', '甲', '—', '—', '')),
             ('没有长跳',
              base + [row('阶段一', '04', '复核', '任务', '甲部', '甲', '—', '→05', '')],
              row('阶段二', '05', '收尾', '结束', '甲部', '甲', '—', '—', ''))]
    from engine import load as _load
    width = {}
    for tag, rows, tail in cases:
        p = tmp / f'laneleft-{len(width)}.md'
        p.write_text(head + ''.join(rows + [tail]), encoding='utf-8')
        y = tmp / f'laneleft-{len(width)}.yaml'
        rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
        if not c.check(rc == 0, f'{tag}：转 DSL 通过', out.strip()[-80:]):
            continue
        L = _load(str(y))
        for e in L.edges:
            L.path(e)
        width[tag] = L.grid.route_left
        inband = [f"{e['from']}→{e['to']}" for e in L.edges
                  if any(x <= L.grid.stage_w for x, _ in L.path(e))]
        c.check(not inband, f'{tag}：没有线压在里程碑带上', str(inband))
        rc2, out2 = run('validate.py', y)
        c.check(rc2 == 0, f'{tag}：八项门禁全过', out2.strip()[-80:] if rc2 else '')
    c.check(width.get('有同列跨行长跳', 0) > 0, '有长跳 → 走廊留出来了',
            str(width))
    c.check(width.get('有同列跨行长跳', 0) > width.get('没有长跳', 0),
            '走廊宽度随图而变（是量出来的，不是常数）', str(width))


def _check_min_leg(c):
    c.section('产物几何：线段不许短于一格粗格（微残段转角挤在箭头上）')
    import validate as _v

    def geom(pts):
        return {'nodes': {'01': {'rect': (0, 0, 160, 60), 'shape': 'rounded'},
                          '02': {'rect': (0, 200, 160, 60), 'shape': 'rounded'}},
                'edges': [{'from': '01', 'to': '02', 'pts': pts}],
                'canvas': (400, 400), 'band': 0}

    short = geom([(80, 60), (80, 70), (70, 70), (70, 200), (80, 200)])   # 两端各 10px
    errs = _v.check_artifact(short)
    c.check(any('挤在箭头上' in m for m in errs), '10px 的段：报"转角挤在箭头上"',
            '；'.join(errs) or '（未报）')
    ok = geom([(80, 60), (80, 80), (60, 80), (60, 200), (80, 200)])      # 四段各 20/20/120/20
    c.check(not _v.check_artifact(ok), '20px 的段：放行', '；'.join(_v.check_artifact(ok)))
    for f in ('drawio', 'html'):
        rc, out = run('validate.py', '--artifact', str(_base(f)))
        c.check(rc == 0, f'基准样例 {f} 产物里没有微残段', out.strip()[-70:] if rc else '')


def lane_head(project, depts='甲部'):
    """depts 兼容两种写法：`'甲部'`/`'甲部, 乙部'`（YAML 流式列表）与旧箭头串 `'甲部 → 乙部'`。"""
    if '→' in depts:
        depts = ', '.join(x.strip() for x in depts.split('→'))
    return (_cfg_rows(('输出布局', '泳道'), ('泳道列序', depts.replace(', ', ' → ')))
            + f'# 验证用泳道表（{project}）\n\n## 流程表\n\n'
            '| 项目运作阶段 | 节点编号 | 节点名称 | 节点类型 | 输入 | 依据 | 输出 | 执行主体 | 执行者 | 行动所需时间 | 下个节点 | 节点描述 |\n'
            '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---\n')


def lane_fixture(tmp, name):
    """一张**自带左走廊**的泳道表（`04→回 02` 是同列跨行长跳）→ 建出产物 → 返回表路径。

    产物侧用例（底色铺满 / 微残段）要有真产物可量，又不该依赖 examples/——自举样例是流程布局，
    不带泳道底色。所以自带一张。

    建在**独立子目录**里：`build.py` 把几何提示读作同目录的 `<流程名>-flow.yaml`，
    产物也写在那里——几张贴在同一目录里互相覆盖，前一张的 yaml 还会被后一张当成几何提示。
    """
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / f'{name}.md'
    p.write_text(lane_head('泳道产物验证') + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02', ''),
        row('阶段一', '02', '继续？', '判断', '甲部', '甲', '—', '通过→03 ｜ 不通过→回 01', ''),
        row('阶段一', '03', '处理', '任务', '甲部', '甲', '—', '→04', ''),
        row('阶段一', '04', '复核', '任务', '甲部', '甲', '—', '继续→05 ｜ 重做→回 02', ''),
        row('阶段二', '05', '收尾', '结束', '甲部', '甲', '—', '—', ''),
    ]), encoding='utf-8')
    run('build.py', p)
    return p


def _check_lanes_coverage(c, tmp):
    c.section('产物几何：泳道底色必须盖住所有节点')
    import validate as _v

    def geom(lb):
        return {'nodes': {'01': {'rect': (300, 100, 160, 60), 'shape': 'rounded'}},
                'edges': [], 'canvas': (1080, 400), 'band': 120, 'lanes': lb}

    # 底色整体比节点列平移一个走廊宽时，末列节点就会探出底色（实测露出去 60px）
    bad = geom((120, 60, 400, 400))
    errs = _v.check_artifact(bad)
    c.check(any('底图没铺满' in m for m in errs), '节点探出底色：报"底图没铺满"', '；'.join(errs) or '（未报）')
    ok = geom((120, 60, 1080, 400))
    c.check(not _v.check_artifact(ok), '底色盖住节点：放行', '；'.join(_v.check_artifact(ok)))
    p = lane_fixture(tmp, 'lanefix')
    for f in ('drawio', 'html'):
        rc, out = run('validate.py', '--artifact', str(prod(p.parent, f)))
        c.check(rc == 0, f'真实泳道产物 {f}：底色铺满', out.strip()[-70:] if rc else '')
    # 泳道那两样（里程碑带宽 / 底色外包盒）也要**暴露在表里**：门禁内部用了它们，人复核时也得看得见
    import json as _json
    dump = p.parent / 'geom.json'
    rc, _ = run('validate.py', '--artifact', str(prod(p.parent, 'drawio')), '--dump', str(dump))
    g = _json.loads(dump.read_text(encoding='utf-8')) if rc == 0 else {}
    c.check(g.get('band', 0) > 0 and len(g.get('lanes') or []) == 4,
            '泳道产物：几何表里有里程碑带宽与底色盒', f'band={g.get("band")} lanes={g.get("lanes")}')


def _check_lane_expectation(c, tmp):
    """「这份产物该不该有泳道底图」只能由**知道底稿的一层**拍板（2026-09-15 补的洞）。

    背景：流程布局的产物与"泳道源但底图没画"的产物在几何表上**完全同形**（band=0 / lanes=None，
    `examples/workflow` 实测如此）。此前两条判据 `if not band: return []` 正是被这个同形逼出来的
    ——结果是"泳道源渲染成流程样"永远绿。这里两个方向都要有牙齿。
    """
    c.section('产物几何：泳道底图的期望值来自底稿（产物自称抓不到的那个洞）')
    import validate as _v

    def geom(lanes=None, band=0):
        return {'nodes': {'01': {'rect': (300, 100, 160, 60), 'shape': 'rounded'}},
                'edges': [], 'canvas': (1080, 400), 'band': band, 'lanes': lanes}

    # ① 该有却没有：这是产物自称**永远**判不出来的一格（与流程布局的产物同形）
    miss = _v.check_artifact(geom(), expect_lanes=True)
    c.check(any('没有里程碑带宽' in m for m in miss),
            '泳道源、产物没画底图：报"没有里程碑带宽"', '；'.join(miss) or '（未报）')
    half = _v.check_artifact(geom(band=120), expect_lanes=True)
    c.check(any('没有泳道底色盒' in m for m in half),
            '泳道源只画了里程碑带、没画底色盒：报"没有泳道底色盒"', '；'.join(half) or '（未报）')
    # ② 不该有却画了：反方向（渲染器把布局判错）
    extra = _v.check_artifact(geom(lanes=(120, 60, 1080, 400), band=120), expect_lanes=False)
    c.check(any('布局判错了' in m for m in extra),
            '流程源、产物却画了底图：报"布局判错了"', '；'.join(extra) or '（未报）')
    # ③ 流程源照常放行（不能因为补洞就把流程布局全判红——`examples/workflow` 就是流程布局）
    ok_flow = _v.check_artifact(geom(), expect_lanes=False)
    c.check(not ok_flow, '流程源、产物没有底图：放行', '；'.join(ok_flow))
    # ④ 拿不到底稿时按产物自称判：同形的两件事只能一起放行 —— **这是明说的弱化**，不是静默
    c.check(not _v.check_artifact(geom()),
            '拿不到底稿（expect_lanes=None）：按产物自称，同形即放行', '；'.join(_v.check_artifact(geom())))
    c.check(any('没有泳道底色盒' in m for m in _v.check_artifact(geom(band=120))),
            '拿不到底稿但产物自称泳道（有带无底色）：照样全强度查', '；'.join(_v.check_artifact(geom(band=120))))

    # ⑤ 端到端：泳道底稿 + 一个"忘了画底图"的 svg 渲染器 ⇒ build 必须退 1
    #    （替身写 html 内容进 .svg——同一套元素约定，`read_svg`/`geometry_from_svg` 照读，
    #     唯独没有泳道底色。这正是产物自称抓不到、只有 build 带期望才抓得到的那一格。）
    #
    #    替身必须挂在 `build` 的**模块命名空间**上、且**在同进程里**调 `_b.main()`：
    #    `build._renderer()` 拿注册表里的**名字**去 `globals()` 现查，而子进程改不动
    #    （第一版跑出"命中 0 次"就是这么来的——那种情况下 rc==1 是子进程照常成功，
    #     这条用例会退化成永远绿的假绿）。
    import io
    import contextlib
    import build as _b

    class _Cap(io.StringIO):
        """替身 stdout：`build.main` 开头会 `reconfigure(encoding=…)`，StringIO 没有这个方法。"""

        def reconfigure(self, **kw):
            pass

    ad = tmp / 'laneexp'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    ft = ad / 'flowtable.md'
    ft.write_text(lane_head('泳道期望') + ''.join([
        row('阶段一', '01', '发起', '开始', '甲部', '甲', '—', '→02', ''),
        row('阶段一', '02', '处理', '任务', '乙部', '乙', '—', '→03', ''),
        row('阶段二', '03', '收尾', '结束', '丙部', '丙', '—', '—', ''),
    ]), encoding='utf-8')
    rc, out = run('build.py', ft)
    if not c.check(rc == 0, '前置：泳道底稿正常构建通过', out.strip()[-90:] if rc else ''):
        return
    good = {p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'), prod(ad, 'svg'))}
    orig = _b.render_svg
    hits = []

    def fake_svg(yaml_path, out_path, ctx=None):
        # 签名必须与真渲染器同步（`ctx` 是唯一的私有选项入口）——少一个参数会让 build 抛
        # TypeError，"退出码 1"就成了崩出来的、不是审出来的（同 `_check_build_rollback`）。
        #
        # 造"漏画"的正确姿势：**先正常出图，再把泳道底色那一组摘掉**。
        # 不能拿 `render_html` 当替身——泳道源在 html 里**本来就画底色**，那样产物照样有
        # lanes，等于什么都没模拟（第一版就这么写，跑出来 build rc=0、白忙一场）。
        hits.append(1)
        rc = orig(yaml_path, out_path, ctx=ctx)
        t = Path(out_path).read_text(encoding='utf-8')
        stripped = re.sub(r'<g class="lanes">.*?</g>', '', t, flags=re.S)
        emitted.append(stripped)      # 拦下后产物会被还原，所以"交出去的是什么"要当场记下来
        Path(out_path).write_text(stripped, encoding='utf-8')
        return rc

    emitted = []
    _b.render_svg = fake_svg
    cap = _Cap()
    try:
        with contextlib.redirect_stdout(cap):
            rc2 = _b.main([str(ft)])
    finally:
        _b.render_svg = orig
    out2 = cap.getvalue()
    c.check(bool(hits), '前置：替身渲染器真的被 build 调到（导入方式一改这条先红）')
    c.check(emitted and 'lanes' not in emitted[0],
            '前置：替身交出的 .svg 里确实没有底图（摘得掉才说明那组本来在）',
            f'交出 {len(emitted)} 份，含 lanes={bool(emitted) and "lanes" in emitted[0]}')
    c.check(rc2 == 1 and '没有里程碑带宽' in out2,
            '泳道源渲染成流程样：build 拦下（不是崩掉）', (out2.strip().splitlines() or [''])[-1][:80])
    c.check({p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'), prod(ad, 'svg'))} == good,
            '拦下后三份产物都还原成上一版（不留没审过的交付物）')


def _check_build_rollback(c, tmp):
    c.section('产物审核不过：不落盘（还原上一版）')
    # 第 6 环是"先渲染、后审核"。审不过必须还原，否则盘上躺着没审过的交付物——文档里
    # "不过就 exit 1、把刚写下的产物还原"就成了半句话。真跑很难造出"渲染成功但审不过"
    # （几何由同一份数据推出），所以这里替换渲染器，让它写个空壳。
    import build as _b
    ad = tmp / 'rollback'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    ft = ad / 'flowtable.md'
    ft.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc, out = run('build.py', ft)
    if not c.check(rc == 0, '底稿先成功构建一次', out.strip()[-90:] if rc else ''):
        return
    good = {p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'))}
    # 契约的上一版字节：D-81 要求"契约跟产物同进同退"——失败后它必须原样还回去，
    # 否则 `source_sha256` 已指向新表，`sync --fresh` 从此回答"表未变"，stale 门禁永久失效。
    from manifest import manifest_path_for, source_stale
    mf = manifest_path_for(ad / 'rollback-flow.yaml')
    mf_bytes = mf.read_bytes()
    orig = _b.render_html
    # 改一处语义再重跑：表指纹变了，才谈得上"契约有没有跟着变"。
    ft.write_text(ft.read_text(encoding='utf-8').replace('收到申请', '收到申请（改）'), encoding='utf-8')

    _hits = []

    def fake_html(yaml_path, out_path, ctx=None):
        # 签名必须与真渲染器同步（`ctx` 是其**唯一**的私有选项入口，见 ARCHITECTURE.md
        # 第九节 W2/W3）——少一个参数会让 build 抛 TypeError，于是"退出码 1"是
        # **崩出来的**不是"审出来的"，这条用例就变成永远"通过"的假绿（它只查 rc==1）。
        _hits.append(1)
        Path(out_path).write_text('<!DOCTYPE html><html><body></body></html>', encoding='utf-8')

    _b.render_html = fake_html
    try:
        rc2 = _b.main([str(ft)])
    finally:
        _b.render_html = orig
    c.check(rc2 == 1, '渲染器写出空壳产物 → build 退出码 1')
    # monkeypatch 生效守卫：这里靠替换 build 的**模块级名字**生效。哪天 build 改成
    # `import render_html` + `render_html.render(...)`，替换就落空、上面那条变成永远绿的假绿。
    c.check(bool(_hits), '前置：monkeypatch 真的被 build 调到（导入方式一改这条先红）')
    c.check({p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'))} == good,
            '两份产物都还原成上一版（不留没审过的交付物）')
    c.check(not (ad / f'.{prod(ad, "html").name}.bak').exists(),
            '审不过不留 .bak（旧版本来就没变）')
    # D-81：契约与产物同进同退。产物已还原（上一条），契约也必须还原——否则"表被直改过"
    # 这件事在哈希层面被抹掉，sync 的 stale 门禁以后再也拦不住。
    c.check(mf.read_bytes() == mf_bytes,
            '渲染契约也还原成上一版（source_sha256 不许指向没渲染成功的那版表）')
    st, why = source_stale(ft, mf)
    c.check(st == 'changed', '失败之后 sync 仍能看出"表被直改过"（stale 门禁没被关掉）',
            f'state={st} · {why}')

    # ── G45：**异常不许逃出 main**（逃出去 = 产物/契约都不还原 + traceback 退 1）──────────
    # ① 契约读坏（`_audit_contract` 的 `json.loads` 原先裸着）。
    # 注意：**不能直接把盘上那份 manifest 改坏**——`_gen_dsl` 每一轮都会重写它，
    # 改坏了也读不到。所以把 `build.manifest_path_for` 指向一份自己造的坏文件，
    # 模拟"契约在渲染之后坏掉/被截断"这件事本身。
    touched = prod(ad, 'html').read_bytes()        # 渲染前那一版（本轮 build 会覆盖它）
    bad_mf = ad / 'corrupt.manifest.json'
    bad_mf.write_text('{ 这不是 JSON', encoding='utf-8')
    orig_mpf = _b.manifest_path_for
    _b.manifest_path_for = lambda _y: bad_mf
    try:
        try:
            rc_c, exc_c = _b.main([str(ft)]), ''
        except Exception as e:                    # noqa: BLE001 —— 逃出来的异常正是本条要拦的
            rc_c, exc_c = None, f'{type(e).__name__}: {str(e)[:80]}'
    finally:
        _b.manifest_path_for = orig_mpf
    c.check(rc_c == 1 and not exc_c,
            'G45 渲染契约读坏 ⇒ 退 1（不是 traceback 从 main 逃出去）',
            exc_c or f'rc={rc_c}')
    c.check(prod(ad, 'html').read_bytes() == touched,
            'G45 契约读坏时产物**还原成渲染前那一版**（不留半批交付物）')

    # ② 层级索引派生失败（`_write_layer_index` 的 `parse_table` 原先裸着）——也在 try 里了
    touched2 = prod(ad, 'html').read_bytes()
    orig_idx = _b._write_layer_index

    def boom_index(*a, **kw):
        raise RuntimeError('（夹具）层级索引派生故意失败')

    _b._write_layer_index = boom_index
    try:
        try:
            rc_i, exc_i = _b.main([str(ft)]), ''
        except Exception as e:                    # noqa: BLE001
            rc_i, exc_i = None, f'{type(e).__name__}: {str(e)[:80]}'
    finally:
        _b._write_layer_index = orig_idx
    c.check(rc_i == 1 and not exc_i, 'G45 层级索引派生抛异常 ⇒ 退 1（不是 traceback）',
            exc_i or f'rc={rc_i}')
    c.check(prod(ad, 'html').read_bytes() == touched2,
            'G45 索引失败时产物也还原（交付 6 件缺一件 = 不留半批）')

    # ── G46：复用已有 flow.yaml 那条分支**不许丢 `--quality`** ─────────────────────────
    # 症状只在"软提示"这一类上现形，而 `_check_structure` 挡在前面 ⇒ 从 CLI 看不出来；
    # 所以这里替换 `t2d_main` 把 argv 记下来，直接钉住"写 DSL 那一趟带没带 quality"。
    calls = []
    orig_t2d = _b.t2d_main

    def rec_t2d(argv, *a, **kw):
        calls.append(list(argv))
        return 0                                     # 不真跑：本用例只查 argv

    _b.t2d_main = rec_t2d
    try:
        _b.main([str(ft), '--quality', 'showcase'])   # yaml 已存在 ⇒ 走复用几何那条分支
    finally:
        _b.t2d_main = orig_t2d
    write_calls = [c_ for c_ in calls if '--write' in c_]
    c.check(write_calls and all('--quality' in c_ and 'showcase' in c_ for c_ in write_calls),
            'G46 复用旧几何时 `--quality` 仍传下去（原先整份重写 args 把它丢了）',
            f'写 DSL 那几趟：{write_calls}')


def _check_renderer_registry(c, tmp):
    c.section('渲染器注册表：换渲染器 = 改注册表一行（证明它是活的开关，不是摆设）')
    # 若注册表只是"摆着好看"、build 仍旧直接调 `render_html`，那"一切皆插件"就是空话。
    # 这里证明它是**活的路径**：只改 `RENDERERS` 一行，build 实际调到的渲染器就换了。
    #
    # 为什么还要把替身挂到模块命名空间上：`build._renderer()` 把注册表的值当**名字**去
    # `globals()` 里现查（理由见 `build.RENDERERS` 的注释——导入时固化函数对象会让
    # `_check_build_rollback` 那条 monkeypatch 用例落空）。这两步正好就是"加一个渲染器"的
    # 真实动作：**新写一个模块 + 在注册表里加一行**。
    import build as _b
    ad = tmp / 'registry'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    ft = ad / 'flowtable.md'
    ft.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc0, out0 = run('build.py', ft)
    if not c.check(rc0 == 0, '前置：底稿可 build', out0.strip()[-90:] if rc0 else ''):
        return
    good = {p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'))}

    seen = []

    def stub_renderer(dsl_path, out_path, ctx=None):
        # 契约形状：恰好 (dsl_path, out_path, ctx)；私有选项一律经 ctx 进来。
        seen.append(ctx)
        Path(out_path).write_text('<!DOCTYPE html><html><body></body></html>', encoding='utf-8')
        return 0

    orig_name = _b.RENDERERS['html']['fn']
    _b.stub_renderer = stub_renderer
    # 只换 `fn` 指向：注册表的值从 W5 起是**描述符字典**（fn/ext/ids/geom/label），
    # 整项替换成字符串会让 `_product_paths` 取 `meta['ext']` 时 TypeError
    # （W2→W3 是"改签名要同步替身"，这里是"改注册表结构要同步替身"——同一类问题）。
    _b.RENDERERS['html']['fn'] = 'stub_renderer'      # ← 唯一的一处"注册"
    try:
        rc = _b.main([str(ft)])
    finally:
        _b.RENDERERS['html']['fn'] = orig_name
        del _b.stub_renderer

    c.check(bool(seen), '只改注册表一行，build 调到的渲染器就换了（注册表是活的）',
            '替身一次都没被调到 → build 没走注册表')
    c.check(bool(seen) and isinstance(seen[0], dict) and 'parent' in seen[0],
            '渲染器私有选项按契约经 ctx 传入', f'ctx={seen[0] if seen else None}')
    c.check(rc == 1, '换上的渲染器写空壳产物 → build 仍退 1（审核不依赖具体渲染器）', f'rc={rc}')
    c.check({p.name: p.read_bytes() for p in (prod(ad, 'html'), prod(ad, 'drawio'))} == good,
            '换渲染器后审核不过 → 产物仍还原成上一版')


def _check_registry_scales(c, tmp):
    c.section('注册表能装第三类产物：照样渲染 / 照样过两道反查 / 照样进交付清单（W5+W6）')
    # "新增渲染器 = 加一个文件 + 注册一行"到底是不是真的？这里**真的加第三类**，看它会不会
    # 被照样渲染、照样过契约反查、照样过几何自检、照样进交付清单。
    # 关键在于**反解器（ids / geom）是插件契约的另一半**：没有它们，新产物要么被静默跳过、
    # 要么被按错误的格式解析（`artifact_geometry` 的老兜底是"非 html 一律当 drawio XML"）。
    import build as _b
    ad = tmp / 'registry2'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    ft = ad / 'flowtable.md'
    ft.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc0, out0 = run('build.py', ft)
    if not c.check(rc0 == 0, '前置：底稿可 build', out0.strip()[-90:] if rc0 else ''):
        return
    # 先把临时目录里的产物删掉：否则回滚会还原它们，"有没有真写出第三份"就看不出来了。
    for f in (prod(ad, 'html'), prod(ad, 'drawio')):
        if f.exists():
            f.unlink()

    # ① 注册表里每个名字都要能解析到——名字写错要**当场**报，而不是跑到一半 KeyError
    missing = sorted({nm for meta in _b.RENDERERS.values()
                      for nm in (meta['fn'], meta['ids'],
                                 *(() if 'geom' not in meta else (meta['geom'],)))
                      if nm not in vars(_b)})
    c.check(not missing, '注册表里的渲染器与反解器名字都能解析到', str(missing))

    # ③ 第三类：复用一个真渲染器产出**合法产物**，但走自己的扩展名与自己的注册项。
    #    （假内容测不出"两道反查"——它们会先把它拦下；这里要测的是"装得进、且被管住"。）
    def stub_renderer(dsl_path, out_path, ctx=None):
        return _b.render_html(dsl_path, out_path, ctx=ctx)

    # **监视两个缝**而不是比对 stdout：直接看"契约反查收到了几类产物""几何自检用了谁的反解器"。
    # 比字符串断言强的地方在于——它不依赖打印文案，改动打印不会让它变成假的绿。
    audit_seen, geom_seen = {}, []
    real_audit, real_ag = _b.audit, _b.artifact_geometry

    def spy_audit(mf, **kw):
        audit_seen.update(kw)
        return real_audit(mf, **kw)

    def spy_ag(path, reader=None):
        geom_seen.append((Path(path).name, getattr(reader, '__name__', None)))
        return real_ag(path, reader=reader)

    _b.stub_renderer = stub_renderer
    # **不抄清单**：记下"本来有哪些 kind"，断言"原本那些 + stub"都被反查到了。
    # 写成 `== ['drawio','html','stub']` 的话，每加一个渲染器都要回来改门禁——
    # 那门禁就成了"产品清单的复制品"，而不是契约（实测：加 svg 时这三条一起变红）。
    kinds_before = sorted(_b.RENDERERS)
    _b.RENDERERS['stub'] = {'fn': 'stub_renderer', 'ext': '.stub.html', 'ids': 'read_html',
                            'geom': 'geometry_from_html', 'label': 'flow.stub.html'}
    _b.audit, _b.artifact_geometry = spy_audit, spy_ag
    try:
        rc = _b.main([str(ft)])
    finally:
        _b.audit, _b.artifact_geometry = real_audit, real_ag
        del _b.RENDERERS['stub']
        del _b.stub_renderer

    third_path = prod(ad, 'stub.html')
    c.check(rc == 0, '注册第三类后 build 仍成功（三道审核都放它过）', f'rc={rc}')
    c.check(third_path.exists(), '第三类产物真的落盘了（渲染循环遍历了注册表）', third_path.name)
    c.check(sorted((audit_seen.get('products') or {})) == sorted(kinds_before + ['stub']),
            '第三类被纳入**契约反查**（不是静默跳过）',
            sorted((audit_seen.get('products') or {})))
    c.check((geom_seen and [r for n, r in geom_seen if n == third_path.name] == ['geometry_from_html']),
            '第三类用**它自己声明的反解器**跑几何自检', geom_seen)


def _check_degrade(c, tmp):
    c.section('降级：可选渲染器不在也照出 html；必需件缺失必须硬失败（W7a）')
    # "把其它模块暂时关掉也不影响出图"得变成机器守得住的东西，否则只是句话。
    # **两个方向都要验**：可选件缺 → 照出图（并且明确记下缺了什么）；
    # 必需件缺 → **硬失败**（静默少一个产物正是本项目最忌的假绿）。
    import build as _b
    ad = tmp / 'degrade'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    ft = ad / 'flowtable.md'
    ft.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc0, out0 = run('build.py', ft)
    if not c.check(rc0 == 0, '前置：底稿可 build', out0.strip()[-90:] if rc0 else ''):
        return
    hp = prod(ad, 'html')

    reg0, miss0, absent0 = _b.build_registry()
    # 断言**性质**（html 必在、drawio 必在、无缺件），不抄全集 —— 加渲染器不该改门禁。
    c.check('html' in reg0 and 'drawio' in reg0 and not miss0 and not absent0,
            '装齐时注册表含 html 与 drawio，无缺件', f'{sorted(reg0)} miss={miss0} absent={absent0}')

    real_drawio, real_html = _b.render_drawio, _b.render_html
    real_miss, real_absent = _b.MISSING_RENDERERS, _b.ABSENT_REQUIRED
    try:
        # ① 模拟"drawio 模块不在"：模块级绑定置 None，再按可用性重装注册表
        _b.render_drawio = None
        reg1, miss1, absent1 = _b.build_registry()
        c.check('html' in reg1 and 'drawio' not in reg1 and miss1 == ('drawio',) and not absent1,
                '可选件不在 → 从注册表消失，并被记进"缺的可选件"',
                f'{sorted(reg1)} miss={miss1} absent={absent1}')
        # **两份产物都要先删**：前置那次 build 已经把 drawio 生成了，
        # 留着它会让我量到"上一次的遗留物"，于是"降级时没有 drawio"这条永远是绿的假绿。
        hp.unlink()
        dp = prod(ad, 'drawio')
        if dp.exists():
            dp.unlink()
        _b.RENDERERS, _b.MISSING_RENDERERS, _b.ABSENT_REQUIRED = reg1, miss1, absent1
        rc1 = _b.main([str(ft)])
        c.check(rc1 == 0 and hp.exists(), '只有 html 渲染器时 build 仍成功并出 html（**降级成立**）',
                f'rc={rc1} html={hp.exists()}')
        c.check(not dp.exists(), '降级时确实没有 drawio 产物', f'drawio={dp.exists()}')

        # ② 反向控制：必需件缺失**必须硬失败**，不许静默少一个产物
        _b.render_html = None
        reg2, miss2, absent2 = _b.build_registry()
        c.check('html' not in reg2 and absent2 == ('html',),
                '必需件缺失被识别为 absent（不是"可选缺失"）', f'{sorted(reg2)} absent={absent2}')
        hp.unlink()
        _b.RENDERERS, _b.MISSING_RENDERERS, _b.ABSENT_REQUIRED = reg2, miss2, absent2
        rc2 = _b.main([str(ft)])
        c.check(rc2 == 1 and not hp.exists(),
                '必需件缺失 → build 硬失败且不产出 html（不许静默降级）',
                f'rc={rc2} html={hp.exists()}')
    finally:
        _b.render_drawio, _b.render_html = real_drawio, real_html
        _b.RENDERERS = reg0
        _b.MISSING_RENDERERS, _b.ABSENT_REQUIRED = real_miss, real_absent


def _check_flow_parallel_branches(c, tmp):
    c.section('流程布局：汇聚到同一点的分支自动并排占相邻列')
    # 基线是"表序 × 单列"，列从来不是算法量——谁该并排只能人调（自举表的 03/03b 曾是这样，改版后没有了）。
    # 判据保守：分支节点的后继集合完全相同且非空才合并（DECISIONS.md D-37）。
    p = tmp / 'parbranch' / 'flowtable.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEAD + ''.join([
        row('一', '01', '发起', '开始', '甲方', '甲', '—', '→02'),
        row('一', '02', '走哪条？', '判断', '甲方', '甲', '—', '走A→03 ｜ 走B→03b'),
        row('一', '03', 'A 路', '任务', '甲方', '甲', '—', '→04'),
        row('一', '03b', 'B 路', '任务', '甲方', '甲', '—', '→04'),
        row('一', '04', '汇合', '任务', '甲方', '甲', '—', '→05'),
        row('二', '05', '收尾', '结束', '甲方', '甲', '—', '—'),
    ]), encoding='utf-8')
    y = prod(p.parent, 'yaml')
    rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc == 0, '前置：转 DSL 通过', out.strip()[-80:])
    import yaml as _yaml
    d = _yaml.safe_load(y.read_text(encoding='utf-8'))
    pos = {n['id']: (n['row'], n['col']) for n in d['nodes']}
    c.check(pos['03'] == (2, 0) and pos['03b'] == (2, 1),
            '同汇聚点的两条分支并排同层、占相邻列', str(pos))
    c.check(pos['04'] == (3, 0), '合并后腾空的层被压掉（04 紧随其后一层）', str(pos))
    c.check(d['layout']['col_x'] == [], '多列时 col_x 留空，由字典 col_pitch 展开', str(d['layout']))
    rc2, out2 = run('build.py', p)
    c.check(rc2 == 0 and '全部通过' in out2, '并排后的图八项门禁全过', out2.strip()[-80:] if rc2 else '')


def _check_clean_l_mirror(c, tmp):
    c.section('流程布线：前向对角的干净 L 必须四档齐全（侧出顶入 ×2、底出侧入 ×2，D-161/D-162）')
    # 夹具：主轴 01→02→03→06，02 另分两支到左右两侧的 04/05、再汇回 06。
    # `merge_parallel_branches` 把 03/04/05 并到一行相邻列，`balance_arms`（需 ≥3 列才动手）
    # 再把主轴摆回中轴 —— 于是 02 的左右两侧各挂一条跨列下游，正是"左中右三轴"的形态。
    # 它一次覆盖四种前向对角：02→左右（源在中间、顶端口空）走**侧出顶入**；
    # 04/05→06（源在两侧、06 的顶已被主干 03→06 占掉）走**底出侧入**。
    p = tmp / 'lmirror.md'
    p.write_text(HEAD + ''.join([
        row('阶段', '01', '发起', '开始', '甲', '甲', '—', '→02'),
        row('阶段', '02', '分流？', '判断', '甲', '甲', '—', '左→03 ｜ 中→04 ｜ 右→05'),
        row('阶段', '03', '主干', '任务', '乙', '乙', '—', '→06'),
        row('阶段', '04', '左支', '任务', '乙', '乙', '—', '→06'),
        row('阶段', '05', '右支', '任务', '丙', '丙', '—', '→06'),
        row('阶段', '06', '收尾', '结束', '甲', '甲', '—', '—'),
    ]), encoding='utf-8')
    y = tmp / 'lmirror.yaml'
    rc, out = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc == 0, '前置：三条分支的分流表转 DSL 通过', out.strip()[-80:])
    L = load(str(y))
    fork = [e for e in L.edges if e['from'] == '02']
    for e in fork:
        L.path(e)          # **必须先算路径**：`exit`/`entry` 是路由过程中才写进边对象的
    mid = L.nodes['02']['col']
    lf = [e for e in fork if L.nodes[e['to']]['col'] < mid]
    rt = [e for e in fork if L.nodes[e['to']]['col'] > mid]
    # 回流的两条：06 的**顶**端口已被主干入边 03→06（spine，`bottom`→`top`）占住，
    # 它们只能各走一侧的「底出 + 侧入」L —— 这正是 D-162 补的那一档。
    lb = next((e for e in L.edges if e['to'] == '06' and L.nodes[e['from']]['col'] < mid), None)
    rb = next((e for e in L.edges if e['to'] == '06' and L.nodes[e['from']]['col'] > mid), None)
    c.check(len(lf) == 1 and len(rt) == 1,
            '夹具有效：02 的左右两侧各挂一条跨列下游（`balance_arms` 真的分了侧）',
            f"左={[e['to'] for e in lf]} 右={[e['to'] for e in rt]}")
    if len(lf) == 1 and len(rt) == 1:
        c.check(L.ports(lf[0]) == ('left', 'top'), '左向走「左出 + 顶入」，不是「底出 + 右入」',
                f"02→{lf[0]['to']} ports={L.ports(lf[0])} path={L.path(lf[0])}")
        c.check(L.ports(rt[0]) == ('right', 'top'), '右向走「右出 + 顶入」，与左向镜像',
                f"02→{rt[0]['to']} ports={L.ports(rt[0])}")
        c.check(all(len(L.path(e)) == 3 for e in (lf[0], rt[0])),
                '两条都是三点 L 形（一个折点，没退化成绕行）',
                f"{L.path(lf[0])} / {L.path(rt[0])}")
    # 反向控制：顶端口被占之后**必须各走一侧的底出 L**，而不是落到 Z 形绕行。
    # 少了这两条，`_anchor_taken` 那对守卫和 (`bottom`,`left`) 那一档删掉都不会有人发现。
    for e, want, who in ((lb, ('bottom', 'left'), '左侧回流'), (rb, ('bottom', 'right'), '右侧回流')):
        c.check(e is not None and L.ports(e) == want and len(L.path(e)) == 3,
                f'反向控制：{who}在顶端口被占后走「底出 + 侧入」的三点 L',
                (f"{e['from']}→{e['to']} ports={L.ports(e)} path={L.path(e)}"
                 if e is not None else '夹具里找不到这条回流边'))
    rc, out = run('validate.py', y)
    c.check(rc == 0, '八项门禁全过', out.strip().splitlines()[-1][:90])


def _check_stagger_slots(c, tmp):
    c.section('同侧多出边的错峰：槽位用尽也不许落回入边锚点（D-61）')
    # 错峰候选 `[0] + [s·k·2×细格]` 被 `lim = 半边长 − 细格` 裁到只剩两个槽位，而 `taken` 同时装着
    # "入边锚点"与"先排的同类出边"——本侧一旦是「1 条入边占住侧中线 + ≥2 条出边」，第 3 条起就
    # **静默空手而归**，锚点落回侧中点 = 入边锚点，出边首段把入边末段原路画回来（DECISIONS.md D-61）。
    # 夹具：枢纽节点 05 有一条跨 4 行的 jumpR 入边（01→05）与 4 条同侧 jumpR 出边。
    p = tmp / 'stagger' / 'flowtable.md'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEAD + ''.join([
        row('一', '01', '发起', '开始', '甲方', '甲', '—', '主干→02 ｜ 长跳→05'),
        row('一', '02', '步骤二', '任务', '甲方', '甲', '—', '→03'),
        row('一', '03', '步骤三', '任务', '甲方', '甲', '—', '→04'),
        row('一', '04', '步骤四', '任务', '甲方', '甲', '—', '→05'),
        row('二', '05', '汇聚枢纽', '任务', '甲方', '甲', '—', '→06 ｜ 汇A→08 ｜ 汇B→09 ｜ 汇C→10 ｜ 汇D→11'),
        row('二', '06', '步骤六', '任务', '甲方', '甲', '—', '→07'),
        row('二', '07', '步骤七', '任务', '甲方', '甲', '—', '→08'),
        row('三', '08', '步骤八', '任务', '甲方', '甲', '—', '→09'),
        row('三', '09', '步骤九', '任务', '甲方', '甲', '—', '→10'),
        row('三', '10', '步骤十', '任务', '甲方', '甲', '—', '→11'),
        row('三', '11', '收尾', '结束', '双方', '双方共责', '—', '—'),
    ]), encoding='utf-8')
    y = prod(p.parent, 'yaml')
    rc_w, out_w = run('table_to_dsl.py', '--write', p, '-o', y)
    c.check(rc_w == 0, '前置：枢纽表转 DSL 通过', out_w.strip()[-80:])
    rc, out = run('validate.py', y)
    c.check(rc == 0 and '掉头折返' not in out, '八项门禁全过（不再掉头折返）',
            out.strip().splitlines()[-1][:80] if rc == 0 else out.strip()[-160:])
    from engine import load as _load
    L = _load(str(y))
    for e in L.edges:            # 通道/错峰是**惰性**算的（`_ensure_gutters` 挂在首次 `path()` 上）：
        L.path(e)                # 不先走一遍，读到的 `sdye` 全是 None——断言会在修好的代码上也假红。
    hub = '05'
    by_side = {}
    for e in L.edges:
        if e['to'] == hub:
            by_side.setdefault(L.ports(e)[1], {'in': [], 'out': []})['in'].append(e)
        if e['from'] == hub:
            by_side.setdefault(L.ports(e)[0], {'in': [], 'out': []})['out'].append(e)
    side, g = max(by_side.items(), key=lambda kv: len(kv[1]['out']))
    c.check(len(g['in']) >= 1 and len(g['out']) >= 3,
            '夹具前提：枢纽节点同侧 ≥1 条入边 + ≥3 条出边（少了就会空转成假绿）',
            f'侧={side} 入={len(g["in"])} 出={len(g["out"])}')
    in_a = {L.grid.anchor(hub, side, e.get('dye', 0)) for e in g['in']}
    out_a = [L.grid.anchor(hub, side, e.get('sdye', 0)) for e in g['out']]
    # 判据故意写成**逐条**（而不是"该侧锚点不止一种取值"）：后者是恒真断言——坏代码下第一条出边
    # 照样拿得到错峰，取值数就已经 ≥2，抓不住回归。实测：删掉第二趟后 sdye = [20, None, None, None]，
    # 锚点取值仍有 2 种，但 4 条里 3 条压在入边锚点上。
    hit = [a for a in out_a if a in in_a]
    c.check(not hit, '该侧每一条出边都避开了入边锚点（坏代码只有第一条躲得开）',
            f'{len(out_a) - len(hit)}/{len(out_a)} 条已避开 · 入边锚点 {sorted(in_a)} · '
            f'出边锚点 {sorted(set(out_a))} · sdye {[e.get("sdye") for e in g["out"]]}')


def _wb_project(tmp, tag):
    """回写保真 / 覆盖门禁两组用例共用的**自造**夹具（D-42：用例自带合成表，不借 `examples/`）。

    为什么不再借样例：样例一改，这一族用例跟着红，而"该改哪边"看不出来——判据与规模该由用例自己钉。
    表形在这里写死：`01 开始 → 02 判断（通过→03 ｜ 不通过→回 01 修正）→ 03 任务（带时间）→ 04 结束`。
    返回 (目录, 流程表 Path, build 的 rc 与输出)；产物名一律走 `prod()`（唯一出处是 `artifact.py`）。
    """
    d = tmp / tag
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        row('一', '01', '受理', '开始', '甲方', '受理员', '—', '→02'),
        row('一', '02', '齐全？', '判断', '甲方', '受理员', '—', '通过→03 ｜ 不通过→回 01 修正'),
        row('二', '03', '核验', '任务', '乙方', '工程师', '3个工作日', '→04'),
        row('三', '04', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8',
        newline='\n')          # 夹具表也钉 LF（D-116 那条"写的那一侧"对夹具同样成立）
    rc, out = run('build.py', ft)
    return d, ft, rc, out


def _cell_of(ft, nid, col):
    """按**节点编号**取某一列（`col` 是 split('|') 后的下标）→ 改表用的小工具。

    不按"名字里含某个词"找行：那正是借样例那种写法的病根（样例改个名，用例就找不到行）。
    """
    for l in Path(ft).read_text(encoding='utf-8').splitlines():
        cs = l.split('|')
        if len(cs) > 11 and cs[2].strip() == nid:
            return cs[col]
    return ''


def _set_cell(ft, nid, col, value):
    """按节点编号改某一列（写回文件），返回是否改到了。"""
    ls = Path(ft).read_text(encoding='utf-8').splitlines()
    for i, l in enumerate(ls):
        cs = l.split('|')
        if len(cs) > 11 and cs[2].strip() == nid:
            cs[col] = value
            ls[i] = '|'.join(cs)
            Path(ft).write_text('\n'.join(ls), encoding='utf-8')
            return True
    return False


def _check_writeback_semantics(c, tmp):
    c.section('回写保真：语义列以流程表为准（不许用 drawio 旧值回灌）')
    # 场景：用户按文档指引在流程表里改了执行主体，但还没重跑 build（drawio 里仍是旧值）。
    # 此时 sync 若拿 drawio 属性回写，改动就被静默回退——流程表是唯一事实源，这不该发生。
    a1, ft1, rc0, out0 = _wb_project(tmp, 'a1')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return
    assert _set_cell(ft1, '01', 8, ' A1哨兵主体 ')      # 执行主体：列下标 7（split 偏移 +1）
    assert _set_cell(ft1, '01', 6, ' A1哨兵依据 ')      # 依据：列下标 5
    rc1, _ = run('sync.py', prod(a1, 'drawio'), ft1)
    synced = a1 / 'flowtable.sync.md'
    c.check(rc1 == 0 and synced.exists() and 'A1哨兵主体' in synced.read_text(encoding='utf-8'),
            '流程表改的语义不被 drawio 回退', '哨兵主体仍在' if rc1 == 0 else f'sync rc={rc1}')
    # D-73：图里**不写任何语义列**。属性面板里摆着改不动的副本，用户会以为改得动——
    # 这条是负向守卫：产物里再出现这些属性名，就是那块牌子又回来了（读**本夹具自己**的产物）。
    dw_txt = prod(a1, 'drawio').read_text(encoding='utf-8')
    leaked = [k for k in ('输入=', '依据=', '输出=', '执行主体=', '执行者=', '行动所需时间=',
                          '项目运作阶段=', '节点描述=', '下个节点=', '节点名称=', '节点类型=')
              if k in dw_txt]
    c.check(not leaked, 'drawio 里一个语义属性都不写（表的数据不进图）',
            ('泄漏: ' + '、'.join(leaked)) if leaked else '0 处')
    c.check(synced.exists() and 'A1哨兵依据' in synced.read_text(encoding='utf-8'),
            '依据列经 sync 往返后仍在（语义列以流程表为准）')


def _check_writeback_next_conflict(c, tmp):
    """D-45：`下个节点` 列也是语义列。它由图重建、没法静默兜底，所以必须**冲突时报警**。

    这个洞曾经真实存在：改了流程表的连线走向（正确）但没重跑 build，sync 会静默改回图里的旧走向，
    且 EXIT 0、四道护栏全过——用户完全无从察觉。本段钉住"冲突必须被说出来"。
    """
    c.section('回写保真：分支走向与图冲突时必须报警（不再静默取图）')
    a2, ft, rc0, out0 = _wb_project(tmp, 'a2')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return
    orig_next = _cell_of(ft, '02', 11)
    # 改流程表：02 的第二支「不通过→回 01 修正」改成「不通过→回 03 修正」（图未动，仍是 01）
    assert _set_cell(ft, '02', 11, ' 通过→03 ｜ 不通过→回 03 修正 ')

    rc, out = run('sync.py', prod(a2, 'drawio'), ft)
    c.check('走向冲突' in out and '02' in out and '不通过' in out,
            '预览即报出走向冲突（含节点号与分支标签）',
            next((l.strip() for l in out.splitlines() if '走向冲突' in l), '（无冲突告警）'))
    # 预览产出的 flowtable.sync.md 按设计就"照图写"（预览的对象是图）——这不是缺陷，
    # 真正的保护在 --apply 那道门（见 _check_apply_guard）。这里只钉住"预览不碰原表"。
    c.check('回 03' in _cell_of(ft, '02', 11), '预览阶段不覆盖原表（回 03 仍在）',
            _cell_of(ft, '02', 11).strip())
    # 幂等面：表与图一致时不该误报冲突
    ft2 = a2 / 'same.md'
    ft2.write_text(HEAD + ''.join([
        row('一', '01', '受理', '开始', '甲方', '受理员', '—', '→02'),
        row('一', '02', '齐全？', '判断', '甲方', '受理员', '—', '通过→03 ｜ 不通过→回 01 修正'),
        row('二', '03', '核验', '任务', '乙方', '工程师', '3个工作日', '→04'),
        row('三', '04', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8',
        newline='\n')          # 夹具表也钉 LF（D-116 那条"写的那一侧"对夹具同样成立）
    _rc2, out2 = run('sync.py', prod(a2, 'drawio'), ft2)
    c.check('走向冲突' not in out2, '表与图一致时不误报冲突',
            next((l.strip() for l in out2.splitlines() if '走向冲突' in l), '无告警 ✓'))
    assert orig_next.strip()          # 夹具自检：上面确实取到了"下个节点"列


def _drop_edge(drawio, src, tgt):
    """从 drawio 里摘掉 `source=src, target=tgt` 的那条边 → 摘掉几条（0 或 1）。

    **按 `source`/`target` 属性定位，不按 `id`**：`xml_reader.read` 报的边是
    `{'from', 'to', 'label', 'dashed', 'pts', …}`，**没有 `id` 这个键**（第一版就是照 `id` 找、
    于是恒返回 0）。用两个前瞻把属性顺序也放掉。在**原文**上抠掉那个 `mxCell` 块——
    不重新序列化整份 XML（那会把没考的东西也一起改了）。
    """
    import xml_reader
    data = xml_reader.read(drawio.read_text(encoding='utf-8-sig'))
    if not any(str(e.get('from')) == src and str(e.get('to')) == tgt
               for e in data.get('edges') or []):
        return 0
    t = drawio.read_text(encoding='utf-8-sig')
    m = re.search(r'<mxCell\b(?=[^>]*\bsource="%s")(?=[^>]*\btarget="%s")'
                  r'[^>]*(?:/>|>.*?</mxCell>)' % (re.escape(src), re.escape(tgt)), t, re.S)
    if not m:
        return 0
    drawio.write_text(t[:m.start()] + t[m.end():], encoding='utf-8', newline='\n')
    return 1


def _check_writeback_selfcheck(c, tmp):
    c.section('回写自检不过 ⇒ 不许覆盖《流程表》（D-84①；G10 补的那一支）')
    # 为什么值得一条：`sync --apply` 是**唯一会不可逆改写《流程表》**的地方，而面② 现有的守卫
    # （`_check_apply_guard`）只覆盖**走向冲突**那一支——判据是"表与图的说法不一致"。**另一支一直
    # 没人跑**：图本身就把表改成了一份**过不了 H1–H8** 的东西（这里摘掉 `02→03` 那条边 ⇒ 断链 +
    # 02 没了出口）。那种回写结果 `writeback._verify_written` 已经报了 ✗、`sync` 也写了
    # "这份预览不能当成品"——但**没有人验过它真的拦住了**。G10 记的就是这一笔。
    d, ft, rc0, out0 = _wb_project(tmp, 'g10')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return
    before = ft.read_bytes()
    dw = prod(d, 'drawio')
    n = _drop_edge(dw, '02', '03')
    c.check(n == 1, '前置：drawio 里找到并摘掉 1 条边（02→03）', f'摘掉 {n} 条')
    rc, out = run('sync.py', dw, ft, '--apply')
    # 判据打在那两行**原文**上（"自检""不能当成品"是注释里的词，运行时印的是这两句）
    c.check(rc == 1 and '未过结构校验' in out and '本次不覆盖' in out,
            '回写自检不过 ⇒ 退 1 并明说"本次不覆盖《流程表》"', out.strip()[-150:])
    c.check(ft.read_bytes() == before, '被拦下时《流程表》**一字节未动**', '')


def _check_apply_guard(c, tmp):
    """D-45：`sync.py --apply` 是唯一会不可逆改写《流程表》的地方，冲突时必须先拦下来。"""
    c.section('--apply 覆盖门禁：流程表与图走向冲突时拦截，--force 才放行')
    a3, ft, rc0, out0 = _wb_project(tmp, 'a3')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return
    assert _set_cell(ft, '02', 11, ' 通过→03 ｜ 不通过→回 03 修正 ')

    before = _cell_of(ft, '02', 11)
    rc, out = run('sync.py', prod(a3, 'drawio'), ft, '--apply')
    c.check(rc == 1 and '覆盖被拦截' in out, '--apply 冲突时被拦截（退出码 1）',
            f'rc={rc}')
    c.check(_cell_of(ft, '02', 11) == before, '被拦截时流程表一字节未动（回 03 保住）',
            f'实际 {_cell_of(ft, "02", 11)!r}')

    rc2, out2 = run('sync.py', prod(a3, 'drawio'), ft, '--apply', '--force')
    c.check('已按图覆盖' in out2 and '走向冲突' in out2,
            '--force 放行且明确告知"以图为准"', f'rc={rc2}')
    # --force 的语义就是"以图为准"：目标从表里的 03 改成图里的 01（旧注解「修正」是绑在旧目标上的
    # 自由文本，目标换了就不该跟着搬，见 writeback._tail 的注释）。
    after = _cell_of(ft, '02', 11)
    c.check('回 01' in after and '回 03' not in after,
            '--force 后表确实按图改了（回 03 → 回 01）', f'实际 {after!r}')

    # D-87：`--apply` 先覆盖《流程表》再重渲染，而重渲染**会失败**（几何/审核任意一环）。
    # 失败时表已经换成图里那版——手工改动再也回不来。这里把 `build.main` 换成必然失败的替身，
    # 验证表与 yaml 都被还原（这一步只能在进程内做：sync 的 `build_main` 是函数内 import）。
    import build as _b2
    import sync as _sy
    preview_ft = a3 / 'flowtable.sync.md'
    preview_ft.write_text(ft.read_text(encoding='utf-8').replace('核验', '核验（图里改的）', 1),
                          encoding='utf-8')
    preview_yaml = a3 / 'a3-flow.sync.yaml'
    preview_yaml.write_bytes(prod(a3, 'yaml').read_bytes())
    yaml_target = prod(a3, 'yaml')       # 产物名的唯一出处是 artifact.py（`prod` 就是它的薄包装）
    before_ft, before_yaml = ft.read_bytes(), yaml_target.read_bytes()
    orig_build, _hits2 = _b2.main, []

    def _boom(argv):                     # 替身：签名与 build.main(argv=None) 一致，直接报失败
        _hits2.append(1)
        print('✗ 替身：故意让重渲染失败')
        return 1

    _b2.main = _boom
    try:
        # `data` 不能省：`_apply` 里那道 D-45 冲突检查要读它（省了会 KeyError，那是夹具的错不是被测代码的）
        _data = _sy._read_back(prod(a3, 'drawio'), ft, True, True)
        rc3 = _sy._apply(ft, preview_ft, preview_yaml, _data, force=True)
    finally:
        _b2.main = orig_build
    c.check(bool(_hits2), '前置：替身 build 真被 --apply 调到（导入方式一改这条先红）')
    c.check(rc3 == 1, '--apply 后重渲染失败 → 退出码非 0', f'rc={rc3}')
    c.check(ft.read_bytes() == before_ft and yaml_target.read_bytes() == before_yaml,
            '失败后《流程表》与 yaml **逐字节还原**（手工改动没被覆盖掉）')


def _check_html_robustness(c, tmp):
    c.section('HTML 健壮性：描述含 </script 不许破坏页面')
    b1, ft2, _rc0, _out0 = _wb_project(tmp, 'b1')
    # 描述里同时放**粗体**与 `</script>`：前者让 `_md_html` 产出一只 `<b>`，而 `<` 必须由
    # `_serialize_tips` 转成 `\u003c` 才能安全内联进 `<script>`。只放 `</script>` 的话，
    # `_md_html` 先 `esc()` 成 `&lt;` ⇒ js 里再也不出现 `\u003c`，"序列化器那一层转义"就没人守了
    # （审查反例：删掉 `render_html` 的 `.replace('<','\\u003c')`，同段三条断言全绿）。
    assert _set_cell(ft2, '01', 12, ' **粗体** 含 </script> 的描述 ')   # 节点描述：列下标 11（split +1）
    rc_b, out_b = run('build.py', ft2)
    c.check(rc_b == 0, '含 </script> 的描述：build 成功', out_b.strip()[-90:] if rc_b else '')
    html = (prod(b1, 'html')).read_text(encoding='utf-8') if rc_b == 0 else ''
    m = re.search(r'var TIPS = (.*?);\n', html, re.S)
    js = m.group(1) if m else ''
    c.check(m is not None and '</script' not in js and '<script' not in js,
            'TIPS 块内无裸 script 标签')
    c.check('\\u003c' in js, '< 已被序列化器转义为 \\u003c')
    import json as _json
    try:
        _json.loads(js.replace('\\u003c', '<').replace('\\u003e', '>'))
        c.check(True, '转义后 JSON 仍可解析且内容还原')
    except Exception as e:
        c.check(False, '转义后 JSON 仍可解析且内容还原', str(e))


def _check_writeback_labels(c, tmp):
    c.section('回写保真：改标签不丢注解')
    t = tmp / 'tail'
    shutil.rmtree(t, ignore_errors=True)
    t.mkdir(parents=True)
    ft = t / 'flowtable.md'
    ft.write_text(HEAD + ''.join([OK[0],
                                  row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
                                      '齐全→03 ｜ 材料只读、永不修改→回 01 补件', '★'),
                                  OK[2], OK[3]]), encoding='utf-8')
    rc_w, _ = run('table_to_dsl.py', '--write', ft, '-o', prod(t, 'yaml'))
    rc_h, _ = run('render_html.py', prod(t, 'yaml'), '-o', prod(t, 'html'))
    rc_r, _ = run('render_drawio.py', prod(t, 'yaml'), '-o', prod(t, 'drawio'))
    d = prod(t, 'drawio')
    if rc_r == 0:
        # 这只标签**必然折排**（`材料只读、永不修改` 徽章 124 > 上限 80），且折点落在全角顿号上
        # （G89 那个"按相邻字符猜并法"会猜错的位置）。写进 drawio 属性的是转义形态 `材料只读、&lt;br&gt;永不修改`。
        d.write_text(d.read_text(encoding='utf-8')
                     .replace('value="材料只读、&lt;br&gt;永不修改"', 'value="否"')
                     .replace('value="材料只读、永不修改"', 'value="否"'), encoding='utf-8')
    rc_s, _ = run('sync.py', d, ft)
    c.check(rc_w == 0 and rc_h == 0 and rc_r == 0 and rc_s == 0, '前置：写 DSL → 双渲染 → sync 成功')
    out_ft = t / 'flowtable.sync.md'
    cell = next((l for l in out_ft.read_text(encoding='utf-8').splitlines() if '| 02 |' in l), '') \
        if out_ft.exists() else ''
    parts = cell.split('|')
    c.check('否→回 01 补件' in cell, '改标签后原注解仍在',
            parts[8].strip() if len(parts) > 8 else cell[:60])


def _check_writeback_pseudo_diff(c, tmp):
    """回写保真：三处伪 diff 源——`--apply` 前那道 diff 复核必须干净（D-12）。

    判据不是"回写跑通了"，而是**没动过的表必须逐字节回到原文**：diff 里每多一行噪声，
    用户就得判断一次"这行是不是我改的"，复核这道防线就漏了。
    """
    c.section('回写保真：未改动的行不许产生伪 diff')

    def _roundtrip(t, text):
        """写表 → 双渲染 → sync 预览，返回 (四个 rc, sync 输出)。"""
        ft = t / 'flowtable.md'
        ft.write_text(text, encoding='utf-8')
        rc_w, _ = run('table_to_dsl.py', '--write', ft, '-o', prod(t, 'yaml'))
        rc_h, _ = run('render_html.py', prod(t, 'yaml'), '-o', prod(t, 'html'))
        rc_r, _ = run('render_drawio.py', prod(t, 'yaml'), '-o', prod(t, 'drawio'))
        rc_s, out_s = run('sync.py', prod(t, 'drawio'), ft)
        return (rc_w, rc_h, rc_r, rc_s), out_s

    def _fresh(name):
        t = tmp / name
        shutil.rmtree(t, ignore_errors=True)
        t.mkdir(parents=True)
        return t

    # ① 注解里重复出现目标编号：tail 必须截在**箭头后**那个编号之后（rfind 会截错）
    t = _fresh('pd_tail')
    rcs, _ = _roundtrip(t, HEAD + ''.join([
        OK[0],
        row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
            '齐全→03 ｜ 不齐全→回 01 参照 01 重审', '★'),
        OK[2], OK[3]]))
    c.check(all(rc == 0 for rc in rcs), '前置：注解含重复编号的表能走完 sync', 'rc=%s' % (rcs,))
    out_ft = t / 'flowtable.sync.md'
    cell = next((l for l in out_ft.read_text(encoding='utf-8').splitlines() if '| 02 |' in l), '') \
        if out_ft.exists() else ''
    c.check('不齐全→回 01 参照 01 重审' in cell,
            '注解里的重复编号不当作目标（tail 截在箭头后那个编号之后）', cell[-36:])

    # ② 裸表（表头就在文件第 0 行、没有前言）：不许凭空多一个前导空行
    t = _fresh('pd_bare')
    _rcs, out_s = _roundtrip(t, HEAD[HEAD.index('|'):] + ''.join(OK))
    c.check('逐字节一致' in out_s, '表头在第 0 行时不产生前导空行（无前言可接则不留 gap）',
            (out_s.strip().splitlines() or [''])[-1][:60])

    # ③ 单元格留空：占位符归一（`''`/`无` ↔ `—`）不算改动
    t = _fresh('pd_blank')
    _rcs, out_s = _roundtrip(t, HEAD + ''.join([
        OK[0],
        row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '',
            '齐全→03 ｜ 不齐→回 01', '★'),
        OK[2], OK[3]]))
    c.check('逐字节一致' in out_s, '行动时间留空不被归一成「—」重写（占位符等价）',
            (out_s.strip().splitlines() or [''])[-1][:60])

    # ④ G42：表头行 / 分隔行的**原文写法**要照抄（不许按 canonical 模板重生成）
    # `import_table.py` 产出的表正是 `|---|` 无空格形态，原先每步 sync 都冒一条伪 diff。
    from flowtable import COLUMNS as _COLS
    t = _fresh('pd_frame')
    tight = HEAD.replace('| ' + ' | '.join(_COLS) + ' |', '|' + '|'.join(_COLS) + '|')
    tight = tight.replace('| ' + ' | '.join(['---'] * len(_COLS)) + ' |',
                          '|' + '|'.join(['---'] * len(_COLS)) + '|')
    assert tight != HEAD, '夹具自身失效：没换掉表头/分隔行'
    _rcs, out_s = _roundtrip(t, tight + ''.join(OK))
    c.check('逐字节一致' in out_s,
            'G42 表头行/分隔行的原文写法照抄（`|---|` 形态不再冒伪 diff）',
            (out_s.strip().splitlines() or [''])[-1][:60])

    # ⑥ G53：表后的**文档表格**不许被当成"表内散行"吃掉
    # 判据原先只有"第二列等于某个节点编号"，于是「变更记录」这类文档表格（3 列）里
    # 只要有一格恰好是节点编号，那一行就被无声丢弃，`--apply` 时写进真表。
    t = _fresh('pd_after_doc')
    doc_after = ('\n## 变更记录\n\n'
                 '| 日期 | 节点 | 改动 |\n| --- | --- | --- |\n'
                 '| 2026-09-21 | 03 | 现场核验：补了时限 |\n')
    _rcs, out_s = _roundtrip(t, HEAD + ''.join(OK) + doc_after)
    kept = (t / 'flowtable.sync.md').read_text(encoding='utf-8') \
        if (t / 'flowtable.sync.md').exists() else ''
    c.check('补了时限' in kept and '日期 | 节点 | 改动' in kept,
            'G53 表后的文档表格（第二列恰好是节点编号）**原样保留**（原先被当散行吃掉）',
            '没保住' if '补了时限' not in kept else '')

    # ⑦ G51：分支分隔符两侧**空格写法**不该被当成改动（回写统一成 `' ｜ '`）
    t = _fresh('pd_sep_space')
    _rcs, out_s = _roundtrip(t, HEAD + ''.join([
        OK[0],
        row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
            '齐全→03｜不齐→回 01', '★'),            # 无空格写法（SKILL.md 只规定分隔符是 `｜`）
        OK[2], OK[3]]))
    c.check('逐字节一致' in out_s,
            'G51 `是→03｜否→04`（分隔符无空格）不被归一成 `｜` 后重写整行',
            (out_s.strip().splitlines() or [''])[-1][:60])

    # ⑧ G52：表头前一行**只含空格**时不许把换行数算多
    t = _fresh('pd_space_blank')
    spaced = HEAD.replace('## 流程表\n\n|', '## 流程表\n \n|')
    c.check(spaced != HEAD, '前置：夹具真的造出了"只含空格的行"')
    _rcs, out_s = _roundtrip(t, spaced + ''.join(OK))
    c.check('逐字节一致' in out_s,
            'G52 表头前只含空格的行不再被数两遍（不加多余换行）',
            (out_s.strip().splitlines() or [''])[-1][:60])

    # ⑨ G54：分支顺序是**作者的排版选择**——表里对调顺序（图没动）不许被改回图序
    t = _fresh('pd_branch_order')
    _roundtrip(t, HEAD + ''.join(OK))                 # 先按原序建出图（OK[1] 是 `齐全→03 ｜ 不齐→回 01`）
    ft_bo = t / 'flowtable.md'
    ft_bo.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
            '不齐→回 01 ｜ 齐全→03', '★'),            # 同目标同标签，只对调顺序
        OK[2], OK[3]]), encoding='utf-8')
    rc_bo, out_bo = run('sync.py', prod(t, 'drawio'), ft_bo)
    synced = (t / 'flowtable.sync.md').read_text(encoding='utf-8') \
        if (t / 'flowtable.sync.md').exists() else ''
    cell = next((l for l in synced.splitlines() if l.startswith('| ') and '| 02 |' in l), '')
    c.check(rc_bo == 0 and '不齐→回 01 ｜ 齐全→03' in cell,
            'G54 分支顺序以原表为准（图没动时不许按图边序改回去）',
            cell[-46:] if cell else f'rc={rc_bo}')

    # ⑤ G43：自产图里手画一个节点后，整份**不许**被判 external（那会把没动过的行按几何重排）
    import xml_reader as _xr
    t = _fresh('pd_native')
    t_ft = t / 'flowtable.md'
    t_ft.write_text(HEAD + ''.join(OK), encoding='utf-8')
    run('table_to_dsl.py', '--write', t_ft, '-o', prod(t, 'yaml'))
    run('render_drawio.py', prod(t, 'yaml'), '-o', prod(t, 'drawio'))
    xml = prod(t, 'drawio').read_text(encoding='utf-8')
    # 手画的形状就是裸 `<mxCell>`（不带我们的 NATIVE_MARK），插在自产节点之后
    extra = ('<mxCell id="99" value="手画一个" style="rounded=1;" vertex="1" parent="1">'
             '<mxGeometry x="40" y="900" width="120" height="40" as="geometry"/></mxCell>')
    mixed = xml.replace('</root>', extra + '</root>', 1)
    assert extra in mixed, '夹具自身失效：没插进裸 mxCell'
    d = _xr.read(mixed)
    c.check(d['source'] == 'native',
            'G43 自产图插一个裸 `<mxCell>` 后仍判 native（`all()` → `any()`：'
            '否则整份降级 external、没动过的行被几何重排）',
            f"source={d['source']} · 节点 {len(d['nodes'])}")


def _check_label_overlap(c):
    c.section('质检补漏：标签互相重叠（结构合法但两个词叠在一起）')
    import validate as _v

    class _Stub:
        """只喂 check_labels 需要的三个接口，精确测"两个标签盒重叠"这个谓词。"""
        width = 1000
        edges = [{'from': '01', 'to': '02', 'label': '是'},
                 {'from': '03', 'to': '04', 'label': '否'}]
        _box = {'是': (100, 100, 40, 20), '否': (110, 108, 40, 20)}   # 两盒交叠

        def label_box(self, e):
            return self._box[e['label']]

        def path(self, e):
            return [(0, 110), (200, 110)]      # 中心都压在自己的线上

        def height(self):
            return 500

    errs = _v.check_labels(_Stub(), {})
    c.check(any('互相重叠' in m for m in errs), '两个标签盒重叠要报出来', '；'.join(errs) or '(未报)')


def _check_geometry_reuse_hint(c, tmp):
    c.section('质检补漏：复用旧几何时新增节点要给出提示')
    # 自造夹具（D-42）：先 build 出一份**自己的** yaml 当"旧几何"，再往表里插一个新节点重跑——
    # `build` 会拿旧 yaml 当布局提示复用（D-18/D-26），新节点因此必须被点名（落在 col=0）。
    b6, ft6, rc_first, out_first = _wb_project(tmp, 'b6')
    if not c.check(rc_first == 0, '前置：第一次 build 产出可复用的旧几何', out_first.strip()[-90:]):
        return
    ls = ft6.read_text(encoding='utf-8').splitlines()
    out6 = []
    for l in ls:
        cs = l.split('|')
        if len(cs) > 11 and cs[2].strip() == '03':
            # 把 03→04 拆成 03→03z→04，制造一个"表里新增、旧 yaml 里没有"的节点
            cs[11] = ' →03z '
            out6.append('|'.join(cs))
            out6.append('| 二 | 03z | 新增节点 | 任务 | — | — | — | 乙方 | 工程师 | — | →04 | ★验证用 |')
        else:
            out6.append(l)
    ft6.write_text('\n'.join(out6), encoding='utf-8')
    rc6, out6s = run('build.py', ft6)
    c.check('新增' in out6s and 'col=0' in out6s, '复用几何时提示新增节点会落 col=0',
            '（未提示）' if 'col=0' not in out6s else '')
    # 新节点按表序占行，可能正落在已有节点那一行上——那时就该由碰撞检测**拦下**（不静默产出），
    # 而不是悄悄把两个节点画叠在一起。两种结局都算正常，唯独不能静默通过。
    c.check(rc6 == 0 or '节点重叠' in out6s, '新节点挤到同一格时由碰撞检测拦下（不静默产出）',
            '' if rc6 == 0 else (out6s.strip().splitlines() or [''])[-1][:70])


def _check_ai_pending_marks(c, tmp):
    c.section('AI 推断留痕：描述以 ⚠ 开头 → 图上醒目虚线标出')
    # 用户只对最终渲染图负责，不会读 checklist；所以"哪里没底"必须画在图上。
    pd = tmp / 'pend'
    shutil.rmtree(pd, ignore_errors=True)
    pd.mkdir(parents=True)
    ftp = pd / 'flowtable.md'
    ftp.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '资料齐全？', '判断', '甲方', '受理员', '—',
            '齐全→03 ｜ 不齐→回 01', '⚠ 原文没写不齐之后怎么办，此处按常理补回环'),
        OK[2], OK[3]]), encoding='utf-8')
    rc_w, _ = run('table_to_dsl.py', '--write', ftp, '-o', prod(pd, 'yaml'))
    rc_h, _ = run('render_html.py', prod(pd, 'yaml'), '-o', prod(pd, 'html'))
    rc_r, _ = run('render_drawio.py', prod(pd, 'yaml'), '-o', prod(pd, 'drawio'))
    rc_s, _ = run('render_svg.py', prod(pd, 'yaml'), '-o', prod(pd, 'svg'))
    c.check(rc_w == 0 and rc_h == 0 and rc_r == 0 and rc_s == 0, '前置：写 DSL 与三份渲染成功')
    h = (prod(pd, 'html')).read_text(encoding='utf-8') if rc_h == 0 else ''
    dw = (prod(pd, 'drawio')).read_text(encoding='utf-8') if rc_r == 0 else ''
    sv = (prod(pd, 'svg')).read_text(encoding='utf-8') if rc_s == 0 else ''
    c.check('"pend": "此处为 AI 推断，原文未载明"' in h, 'HTML 悬浮数据带推断说明')
    c.check('stroke-dasharray="6 4"' in h and 'stroke="#d97706"' in h, 'HTML 该节点虚线醒目描边')
    c.check('strokeColor=#d97706' in dw and 'dashed=1;' in dw, 'drawio 该节点虚线醒目描边')
    # **svg 也要画**（D-86）：此前它连 `⚠` 都不画——单独把 svg 发出去，读者看不出哪几处是推断。
    c.check('stroke-dasharray="6 4"' in sv and 'stroke="#d97706"' in sv,
            'svg 该节点虚线醒目描边（三份产物同口径）')
    # 文字三行与 html 同一套 class（t1 名称 / tm 执行者 / tt2 行动所需时间）——此前 svg 把
    # "执行主体 · 执行者"并成一行 t2、且**不画时间**，同一张表在三份产物里字数都不一样。
    c.check('class="t1"' in sv and 'class="tm"' in sv and 'class="tt2"' in sv,
            'svg 的节点文字三行与 html 同名（t1 / tm / tt2）')
    c.check('>3个工作日<' in sv, 'svg 画出"行动所需时间"（此前这份产物里没有）')
    # 边标签（判断节点的分支条件）：此前 svg 不画，两支在图上长得一模一样。
    c.check(sv.count('class="elab"') == 2 and 'class="lab"' in sv
            and '>齐全<' in sv and '>不齐<' in sv,
            'svg 画出边标签（分支条件，与 html 同元素约定）',
            f'elab {sv.count("class=\"elab\"")} 个')
    pend_lit = '"pend": "'
    c.check(h.count(pend_lit) == 1, '只有打了 ⚠ 的节点被标记', f'实际 {h.count(pend_lit)} 个')
    rc_p, out_p = run('build.py', ftp)
    c.check(rc_p == 0 and '1 处为 AI 推断' in out_p, 'build 汇总提示推断处数',
            '（未提示）' if 'AI 推断' not in out_p else ('' if rc_p == 0 else f'build rc={rc_p}'))

    # 5) 两档必须**画得不一样**：`⚠`（有依据、你不必管）与 `⚠?`（必须你拍板）若同款，
    #    用户看图时分不出哪几处要自己拍板——而这正是 D-46 拆标记的动机，当时只拆了标记没拆视觉。
    td = pd / 'two-tier'
    td.mkdir(parents=True, exist_ok=True)
    ft2 = td / 'flowtable.md'
    ft2.write_text(HEAD + ''.join([
        row('一', '01', '开工', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('一', '02', '推断', '任务', '甲方', '受理员', '—', '→03', '⚠ 按惯例补的时限'),
        row('二', '03', '待拍板', '任务', '甲方', '受理员', '—', '→04', '⚠? 选 A 还是 B 后果不同'),
        row('二', '04', '收尾', '结束', '甲方', '受理员', '—', '—', '★')]), encoding='utf-8')
    rc_t, out_t = run('build.py', ft2)
    c.check(rc_t == 0, '前置：两档夹具 build 通过')
    h2 = (prod(td, 'html')).read_text(encoding='utf-8') if rc_t == 0 else ''
    d2 = (prod(td, 'drawio')).read_text(encoding='utf-8') if rc_t == 0 else ''
    sv2 = (prod(td, 'svg')).read_text(encoding='utf-8') if rc_t == 0 else ''
    c.check('stroke="#d97706"' in h2 and 'stroke-dasharray="6 4"' in h2,
            'HTML：⚠ 用橙 + 疏虚线')
    c.check('stroke="#dc2626"' in h2 and 'stroke-dasharray="2 3"' in h2,
            'HTML：⚠? 用红 + 密虚线（两档分得开）')
    c.check('stroke="#d97706"' in sv2 and 'stroke-dasharray="6 4"' in sv2
            and 'stroke="#dc2626"' in sv2 and 'stroke-dasharray="2 3"' in sv2,
            'svg：两档同样画得不一样（此前一个都不画）')
    c.check('"pend": "此处为 AI 推断，原文未载明"' in h2
            and '"pend": "此处必须业务方拍板' in h2, 'HTML：两档悬浮说明不同')
    c.check('strokeColor=#dc2626' in d2 and 'dashPattern=2 3;' in d2 and 'dashPattern=6 4;' in d2,
            'drawio：同样分两档（色 + 虚线节奏）')
    c.check('必须业务方拍板 1 处' in out_t, 'build 汇总把两档分开报',
            '（未分开）' if '必须业务方拍板 1 处' not in out_t else '')


def _check_clarify_phase(c, tmp):
    c.section('澄清阶段：⚠ 分两类、frontier 只问可问的、交付如实报未决')
    # `⚠` 原先兼表"有依据的推断"与"推不出的决策"，于是没有收敛条件、可永远随图交付。
    # 拆出 `⚠?` 后由 clarify.py 算 frontier，这里钉住四件事：分拣对、顺序对、环不静默、不阻断渲染。
    cd = tmp / 'clarify'
    shutil.rmtree(cd, ignore_errors=True)
    cd.mkdir(parents=True)

    def write(name, rows):
        # **每个夹具独占一个子目录**：同目录多张表会共用 flow.yaml / flow.html，
        # 后一张表会复用前一张的几何提示（节点数不同就落到 col=0 重叠）——这是真实行为，
        # 但会让用例互相污染，所以这里按 output/<名称>/ 的习惯各自隔开。
        sd = cd / name
        sd.mkdir(parents=True, exist_ok=True)
        p = sd / 'flowtable.md'
        p.write_text(HEAD + ''.join(rows), encoding='utf-8')
        return p

    # ① 分层：02 可问（前驱 01 不是 ⚠?）；03 因前驱 02 是 ⚠? 而暂时问不了；04 只是推断，不问
    ft = write('layer', [        OK[0],
        row('裁决', '02', '口径？', '判断', '甲方', '受理员', '—',
            '宽→03 ｜ 严→04', '⚠? 材料未指明宽口径还是严口径，两种走法费用差一倍'),
        row('裁决', '03', '宽口径办理', '任务', '乙方', '工程师', '3个工作日', '→04', '⚠? 宽口径的时限未载明'),
        row('裁决', '04', '严口径办理', '任务', '甲方', '受理员', '—', '→05', '⚠ 材料有条款，按惯例补'),
        row('归档', '05', '归档', '结束', '双方', '双方共责', '—', '—')])

    rc, out = run('clarify.py', ft, '--json')
    import json as _json
    j = _json.loads(out) if rc in (0, 1) else {}
    c.check(rc == 1, '有未决项时退出码 1（不阻断渲染，只表示还没问完）', f'rc={rc}')
    c.check(j.get('counts', {}).get('inferred') == 1 and j.get('counts', {}).get('verdict') == 2,
            '⚠ 与 ⚠? 分拣正确', f'inferred={j.get("counts", {}).get("inferred")} verdict={j.get("counts", {}).get("verdict")}')
    c.check([f['id'] for f in j.get('frontier', [])] == ['02'],
            'frontier 只含前驱已定的 ⚠?', f'实际 {[f["id"] for f in j.get("frontier", [])]}')
    c.check([w['id'] for w in j.get('waiting', [])] == ['03'],
            '上游未决的 ⚠? 归入"暂时问不了"（不静默漏掉）', f'实际 {[w["id"] for w in j.get("waiting", [])]}')
    c.check(j.get('converged') is False, '仍有待问项时不谎报已收敛')

    # ⑤ G40：表带 H3 硬错时**不许装作读过了**——原先 `build_edges` 收的硬错从不检查，
    # 边被静默丢弃、frontier 按缺边图算（实测把节点误列成"现在可问"），而它的契约是"退 2"。
    broken_ft = write('layered_broken', [
        OK[0],
        row('裁决', '02', '口径？', '判断', '甲方', '受理员', '—',
            '宽→99 ｜ 严→04', '⚠? 材料未指明口径'),
        row('裁决', '04', '严口径办理', '任务', '甲方', '受理员', '—', '→05'),
        row('归档', '05', '归档', '结束', '双方', '双方共责', '—', '—')])
    rc, out = run('clarify.py', broken_ft)
    c.check(rc == 2 and 'H3' in out and '99' in out,
            'G40 表带 H3 硬错 ⇒ clarify **退 2** 并点名那处悬空引用（不许按缺边图算 frontier）',
            f'rc={rc} · {out.strip().splitlines()[-1][:60] if out.strip() else ""}')

    # ② 环兜底：02↔03 互为未决，朴素规则会判成"谁都不可问"→ 静默卡死。必须退化并说明
    cyc = write('cycle', [
        OK[0],
        row('环', '02', '甲？', '判断', '甲方', '受理员', '—', '是→03 ｜ 否→04', '⚠? 甲未定'),
        row('环', '03', '乙？', '判断', '乙方', '工程师', '—', '是→回 02 ｜ 否→04', '⚠? 乙未定'),
        OK[3]])
    rc, out = run('clarify.py', cyc)
    c.check(rc == 1 and '02' in out, '互为前驱的环：不静默卡死，按表序取一个破环', f'rc={rc}')
    c.check('环' in out or '先定' in out, '环里的阻塞原因被说明（用户知道为什么先问它）')

    # ③ 不是环时，上游未决的要能真正解锁：只改 03 的 desc 让 02 定下来，frontier 应轮转到 03
    ft2 = write('layer2', [
        OK[0],
        row('裁决', '02', '口径？', '判断', '甲方', '受理员', '—',
            '宽→03 ｜ 严→04', '口径已按严执行（用户已裁决）'),
        row('裁决', '03', '宽口径办理', '任务', '乙方', '工程师', '3个工作日', '→04', '⚠? 宽口径的时限未载明'),
        row('裁决', '04', '严口径办理', '任务', '甲方', '受理员', '—', '→05', '★'),
        row('归档', '05', '归档', '结束', '双方', '双方共责', '—', '—')])
    rc, out2 = run('clarify.py', ft2, '--json')
    # rc 守卫：子进程异常退出时输出不是 JSON，`loads` 直接抛会掀翻整个 gates、掩盖后面的检查。
    c.check(rc in (0, 1), 'clarify --json 正常退出（异常退出会掀翻后续检查）', f'rc={rc}')
    j2 = _json.loads(out2) if rc in (0, 1) else {}
    c.check([f['id'] for f in j2.get('frontier', [])] == ['03'],
            '上游答完后：下一个 ⚠? 进入 frontier（逐轮收敛真的能推进）',
            f'实际 {[f["id"] for f in j2.get("frontier", [])]}')

    # ④ 零开销：无 ⚠ 的表不该被这套机制打扰
    # **注意**（G40 修好后照出来的）：这里原先写 `[OK[0], OK[3]]`——`OK[0]` 的「下个节点」是 `→02`，
    # 而 02 不在表里 ⇒ 这是一张**断链表**，clarify 按缺边图算 frontier 照样退 0，于是"零开销"
    # 这条断言一直站在一张坏表上（正是 G40 要拦的那种假绿）。改成**结构完整**的两节点表。
    cl = write('clean', [
        row('受理', '01', '收到申请', '开始', '甲方', '受理员', '—', '→04'),
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—')])
    rc, out = run('clarify.py', cl)
    c.check(rc == 0 and '无待决项' in out, '无任何 ⚠ 时：零开销、退出码 0、不误报')

    # ⑤ 只有 ⚠ 没有 ⚠?：报告推断但不当成待问项
    oi = write('only_inferred', [
        OK[0],
        row('受理', '02', '登记', '任务', '甲方', '受理员', '3个工作日', '→04', '⚠ 原文没写时限，按行业惯例补'),
        OK[3]])
    rc, out = run('clarify.py', oi)
    c.check(rc == 0 and '无待裁决项' in out, '只有 ⚠ 时：报推断但不当待问项（不问用户）')

    # ⑥ 回归：is_pending 语义未变——`⚠?` 节点在图上必须照样画虚线（最该被看见的一类）
    rc_b, out_b = run('build.py', oi)
    c.check(rc_b == 0 and '1 处为 AI 推断' in out_b, '⚠? 之外的 ⚠ 仍被 build 计入推断数')

    pend_q = write('pend_q', [
        OK[0],
        row('裁决', '02', '口径？', '判断', '甲方', '受理员', '—',
            '宽→03 ｜ 严→04', '⚠? 材料未指明口径'),
        row('裁决', '03', '一路', '任务', '乙方', '工程师', '3个工作日', '→05', '★'),
        row('裁决', '04', '另一路', '任务', '甲方', '受理员', '3个工作日', '→05', '★'),
        row('归档', '05', '归档', '结束', '双方', '双方共责', '—', '—')])
    rc_bq, out_bq = run('build.py', pend_q)
    h = (prod(pend_q.parent, 'html')).read_text(encoding='utf-8') if rc_bq == 0 else ''
    c.check(rc_bq == 0 and '"pend": "此处必须业务方拍板' in h,
            '⚠? 照样画虚线标出，且带自己那句悬浮说明（拆标记没把它漏掉）',
            f'rc={rc_bq}')

    # ⑦ 边界：⚠? 后没有文字不许崩
    nq = write('no_text', [
        OK[0],
        row('裁决', '02', '口径？', '判断', '甲方', '受理员', '—', '宽→03 ｜ 严→04', '⚠?'),
        row('裁决', '03', '一路', '任务', '乙方', '工程师', '3个工作日', '→05', '★'),
        row('裁决', '04', '另一路', '任务', '甲方', '受理员', '3个工作日', '→05', '★'),
        row('归档', '05', '归档', '结束', '双方', '双方共责', '—', '—')])
    rc, out = run('clarify.py', nq)
    c.check(rc == 1 and '02' in out, '⚠? 后无文字：不崩，仍算待裁决', f'rc={rc}')

    # ⑧ 流程表读不了 / 不存在：退出码 2（与"未收敛"的 1 分开，调用方能区别对待）
    rc, out = run('clarify.py', cd / '不存在的表.md')
    c.check(rc == 2 and '找不到流程表' in out, '表不存在：退出码 2、友好报错（不 traceback）', f'rc={rc}')


def _check_external_reader(c, tmp):
    c.section('外部图读回：自产 / 外部按身份戳判、名称只取第一行（D-85）')
    # ① 自家产物：style 里带 `flowchartSkillNative=1` ⇒ native，且不该出现"来自外部工具"的告警
    _od, _oft, _rc, _out = _wb_project(tmp, 'own')
    if not c.check(_rc == 0, '前置：自造夹具 build 通过（拿它当"自家产物"）', _out.strip()[-90:]):
        return
    own = tmp / 'own.drawio'
    shutil.copyfile(prod(_od, 'drawio'), own)
    rc, out = run('xml_reader.py', own)
    c.check(rc == 0 and '来源格式: native' in out, '自家产物读回：来源 native', out.strip()[:80])
    c.check('来自外部工具' not in out, '自家产物带身份戳 ⇒ 不报"须补进《流程表》"')
    # ② 抹掉身份戳（= "外部图被 drawio 加过 link/Edit Data"）：`<object>` 外壳还在，但它**不是**
    #    自家产物 ⇒ 判外部、按几何重排，且告警照报。原缺陷正是只看外壳，于是两样都丢。
    stripped = tmp / 'stripped.drawio'
    stripped.write_text(own.read_text(encoding='utf-8').replace('flowchartSkillNative=1;', ''),
                        encoding='utf-8')
    rc2, out2 = run('xml_reader.py', stripped)
    c.check(rc2 == 0 and '来源格式: external' in out2 and '来自外部工具' in out2,
            '外壳在、身份戳没了：判外部 + **告警照报**（原缺陷会静默吞掉告警）',
            (out2.strip().splitlines() or [''])[-1][:80])
    # ③ 裸 mxCell + 两行标签：名称只取**第一行**（第二行是执行者，不是名称的一部分）
    ext = tmp / 'ext.drawio'
    ext.write_text(
        '<mxfile><diagram id="p" name="外部图"><mxGraphModel pageWidth="800" pageHeight="600">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="n1" value="受理&lt;br&gt;受理员" style="rounded=1;whiteSpace=wrap;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="40" width="160" height="60" as="geometry"/></mxCell>'
        '<mxCell id="n2" value="归档" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="160" width="160" height="60" as="geometry"/></mxCell>'
        '<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="n1" target="n2">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>', encoding='utf-8')
    rc3, out3 = run('xml_reader.py', ext)
    c.check(rc3 == 0 and '受理' in out3 and '受理员' not in out3,
            '外部图两行标签：节点名只取第一行（第二行是执行者）', out3.strip()[:80])
    c.check(rc3 == 0 and '来自外部工具' in out3, '外部图照报"须补进《流程表》"')

    # ④ G71：`<mxGraphModel>` 在、`<root>` 不在 = **图内容丢了**——不许当"空图"退 0
    #    （原先造一个空 root 往下走：brief 打"节点: 0 边: 0"，`--diff` 还可能打"✓ 无差异"）
    noroot = tmp / 'noroot.drawio'
    noroot.write_text('<mxfile><diagram id="p" name="坏图">'
                      '<mxGraphModel pageWidth="800" pageHeight="600"><nothing/></mxGraphModel>'
                      '</diagram></mxfile>', encoding='utf-8')
    rc4, out4 = run('xml_reader.py', noroot)
    c.check(rc4 == 1 and '没有 <root>' in out4 and 'Traceback' not in out4,
            'G71 缺 `<root>` 的损坏图 ⇒ 退 1 + 说清"图内容丢了"（不许当空图退 0）',
            (out4.strip().splitlines() or [''])[-1][:70] if out4.strip() else '')

    # ⑤ G71：第三方图的**分组容器**（`style="group"`）是装饰，不许读成幻影节点
    grp = tmp / 'group.drawio'
    grp.write_text(
        '<mxfile><diagram id="p" name="带分组"><mxGraphModel>'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="g1" value="组A" style="group;" vertex="1" parent="1">'
        '<mxGeometry x="20" y="20" width="400" height="300" as="geometry"/></mxCell>'
        '<mxCell id="n1" value="受理" style="rounded=1;" vertex="1" parent="g1">'
        '<mxGeometry x="40" y="40" width="160" height="60" as="geometry"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>', encoding='utf-8')
    rc5, out5 = run('xml_reader.py', grp)
    c.check(rc5 == 0 and '节点: 1' in out5 and '组A' not in out5,
            'G71 分组容器（`style=group`）不算节点（否则 diff 报"+ 新增节点 g1"、回写还会写进表）',
            out5.strip()[:80])


def _check_manifest_audit(c, tmp):
    c.section('产物审核：渲染丢内容必须被反查出来')
    # 结构校验查表、质量门禁查 yaml，都不看产物。这一层专补「源 → 产物」的缺口：
    # 实测过——从 flow.html 删掉一个节点，validate.py 照样报通过。
    ad = tmp / 'audit'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    fta = ad / 'flowtable.md'
    fta.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc_a, _ = run('build.py', fta)
    mf, hp, dp = prod(ad, 'manifest.json'), prod(ad, 'html'), prod(ad, 'drawio')
    c.check(rc_a == 0 and mf.exists(), 'build 产出渲染契约 manifest')

    rc, out = run('manifest.py', 'check', mf, '--html', hp, '--drawio', dp)
    c.check(rc == 0 and '逐项一致' in out, '完好产物：审核通过')

    for label, mut, want in [
        ('删掉节点', lambda t: re.sub(r'<g class="ndg" data-id="03".*?</g>', '', t, count=1, flags=re.S),
         '少了 1 个节点：03'),
        ('把一条边画错目标', lambda t: t.replace('data-from="01" data-to="02"', 'data-from="01" data-to="03"', 1),
         '少了 1 条边：01→02'),
        # D-84：形状画错也要被反查出来。原先契约里的 by_type / 标签边 / 回路 / ⚠ 四个计数
        # 只有 summary() 在用、从不参与反查，于是"把判断节点画成矩形"能全绿通过。
        ('把判断节点画成矩形',
         lambda t: re.sub(r'<polygon class="shape"[^>]*>',
                          '<rect class="shape" x="-80" y="-30" width="160" height="60" '
                          'fill="#ffe6cc" stroke="#d79b00"/>', t, count=1),
         '形状分布与类型不符'),
    ]:
        hp.write_text(mut(hp.read_text(encoding='utf-8')), encoding='utf-8')
        rc, out = run('manifest.py', 'check', mf, '--html', hp, '--drawio', dp)
        c.check(rc == 1 and want in out, f'{label}：反查报出具体位置',
                (out.strip().splitlines() or [''])[-1][:70] if rc != 1 else '')
        # 还原失败时下一轮会在被改坏的产物上叠加 mutation，want 恰好也命中 → 假通过
        c.check(run('build.py', fta)[0] == 0, f'{label}：还原产物（build 重跑）成功')

    # 契约过期要能和"产物不一致"分开报——两种错因的修法完全不同
    y = prod(ad, 'yaml')
    y.write_bytes(y.read_bytes() + b'\n# hand-edit\n')
    rc, out = run('manifest.py', 'check', mf, '--html', hp, '--drawio', dp, '--yaml', y)
    c.check(rc == 1 and '契约已过期' in out, '手改 yaml 后：报「契约已过期」而非冤枉产物')
    run('build.py', fta)

    # G41：**一份产物都不给 = 没在反查**——原先照样打印"✓ 两份产物与契约逐项一致"退 0
    # （公开命令上的假绿）。现在退 2 并给三种给法；成功语也按**实查份数**说。
    rc, out = run('manifest.py', 'check', mf)
    c.check(rc == 2 and '没给要反查的产物' in out,
            'G41 不给任何产物 ⇒ 退 2（不许打印"两份产物逐项一致"）',
            (out.strip().splitlines() or [''])[-1][:70] if out.strip() else '')
    rc, out = run('manifest.py', 'check', mf, '--html', hp)
    c.check(rc == 0 and '已反查 1 份产物' in out,
            'G41 只给 html 时成功语说"1 份"（不再硬编码"两份"）',
            (out.strip().splitlines() or [''])[-1][:70] if rc == 0 else f'rc={rc}')


def _check_edge_merge_gate(c, tmp):
    """合流只准发生在端口上：异源入边不得在端口前并线，也不得为躲并线而交叉（D-89）。

    用户报的「线条交叉错乱」是两件事叠在一起，而且**几何自检一条都拦不住**：
    ① 两条**异源**入边在端口前并线 150~190px——`validate` 的共享端点豁免放行了它，
       可那条豁免的本意是"分叉/合流汇成一点"；并线段一长，读者看到的就是"一条线"；
    ② 出边错峰把首段推到别的边的竖段上（`stagger_source_anchors` 改的 y 横穿了人家）。

    夹具**自造**，但形状照搬触发它的拓扑（一个源扇出到同排几个侧支、侧支再各自回到下面
    同一个判断节点）——形状是这条判据的输入，名字不是。前置断言钉住"夹具真的触发了这个形状"，
    否则判据会静默变成空跑（这一族用例最常见的失效方式）。
    """
    c.section('合流只准发生在端口上：异源并线 / 错峰交叉（D-89）')
    md = tmp / 'merge'
    shutil.rmtree(md, ignore_errors=True)
    md.mkdir(parents=True)
    fta = md / 'flowtable.md'
    # 夹具要有**四条**汇聚分支：D-92 的「臂」会把分支按重量贪心分挂两侧——三条时正好一侧一条，
    # 夹具就不再触发"同侧异源并线"那类缺陷（前置当场红，判据空跑）。四条里必有两條同侧。
    fta.write_text(HEAD + ''.join([
        row('取图', '01', '出图', '开始', '脚本', 'selfboot', '1 秒', '→02 ｜ →03 ｜ →04 ｜ →05'),
        row('查看', '02', '读回现状', '任务', '脚本', 'selfboot', '1 秒', '→06'),
        row('查看', '03', '看标签', '任务', '脚本', 'selfboot', '1 秒', '→06'),
        row('查看', '04', '看走向', '任务', '脚本', 'selfboot', '1 秒', '→06'),
        row('查看', '05', '再看一处', '任务', '脚本', 'selfboot', '1 秒', '→06'),
        row('判断', '06', '有问题吗？', '判断', '脚本', 'selfboot', '1 秒',
            '是→07 ｜ 否→08', '判据：四条都过才算过'),
        row('收尾', '07', '通过', '结束', '脚本', 'selfboot', '1 秒', '—'),
        row('返工', '08', '重出图', '结束', '脚本', 'selfboot', '1 秒', '—'),
    ]), encoding='utf-8')
    rc, out = run('build.py', fta)
    c.check(rc == 0, '夹具（一源扇出 + 四条异源入边回到同一判断）build 通过',
            '' if rc == 0 else out.strip()[-100:])
    if rc != 0:
        return
    L = load(str(prod(md, 'yaml')))
    L.head_band(False)
    paths = [L.path(e) for e in L.dsl['edges']]
    ins = [e for e in L.dsl['edges'] if e['to'] == '06']
    by_side = {}
    for e in ins:
        by_side.setdefault(L.ports(e)[1], []).append(e['from'])
    same = max(by_side.values(), key=len)
    c.check(len(same) >= 2,
            '前置：06 确有 ≥2 条异源入边共用同一侧端口（判据的输入成立）',
            f'入边 {[(e["from"], L.ports(e)[1]) for e in ins]}')
    merged, crossed = [], []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            ei, ej = L.dsl['edges'][i], L.dsl['edges'][j]
            if ei['from'] == ej['from']:
                continue                      # 同源分叉共享首段是**分叉**，spec 明确允许
            for k in range(len(paths[i]) - 1):
                for m in range(len(paths[j]) - 1):
                    s1 = (paths[i][k], paths[i][k + 1])
                    s2 = (paths[j][m], paths[j][m + 1])
                    pair = (f'{ei["from"]}→{ei["to"]} × {ej["from"]}→{ej["to"]}')
                    if seg_overlap(s1, s2):
                        merged.append(pair)
                    elif ortho_cross(s1[0], s1[1], s2[0], s2[1]):
                        crossed.append(pair)
    c.check(not merged, '异源入边不在端口前并线（并线只准落在端口上）', '；'.join(merged[:3]))
    c.check(not crossed, '错峰不为躲并线而把线推到别的边上（零正交交叉）', '；'.join(crossed[:3]))


def _check_artifact_gate(c, tmp):
    c.section('产物几何自检：接歪的线必须从产物里被反查出来')
    # 模型门禁读 flow.yaml 并**现算**折线，与渲染器共用同一个 router——router 把线接歪时，
    # 两边一起错、一起"通过"。这一关只认产物里那一串数字，是另立视角（见 DECISIONS.md D-32）。
    ad = tmp / 'art'
    shutil.rmtree(ad, ignore_errors=True)
    ad.mkdir(parents=True)
    fta = ad / 'flowtable.md'
    fta.write_text(HEAD + ''.join(OK), encoding='utf-8')
    rc_b, out_b = run('build.py', fta)
    c.check(rc_b == 0 and '真实坐标复核通过' in out_b, 'build 末环内置几何自检',
            '' if rc_b == 0 else f'build rc={rc_b}：{out_b.strip()[-90:]}')

    for name in ('html', 'drawio'):
        rc, out = run('validate.py', '--artifact', prod(ad, name))
        c.check(rc == 0 and '真实坐标复核通过' in out, f'{name}: 完好产物复核通过',
                (out.strip().splitlines() or [''])[-1][:70] if rc != 0 else '')

    # G48：**坏产物不许裸崩**——原先反解器抛 ValueError 会带着 traceback 退 1，
    # 而"输入读不了"是仪器故障（退 2），读者要的是一句人话（文件坏了 / 不是本工具的产物）。
    junk = ad / 'junk.drawio'
    junk.write_text('这不是 XML，也不是任何产物', encoding='utf-8')
    rc, out = run('validate.py', '--artifact', junk)
    c.check(rc == 2 and '产物读不了' in out and 'Traceback' not in out,
            'G48 坏产物 ⇒ 退 2 + 人话（不许 traceback）',
            (out.strip().splitlines() or [''])[-1][:70] if out.strip() else '')

    # 线宽三份产物必须一致：svg 不写 `stroke-width` 就吃 SVG 默认值 1，而 html/drawio 都是 2 ——
    # 曾经只有它细一半。这是**肉眼**发现的（几何自检查的是坐标，量不到线宽），所以钉在这里。
    _w = {k: prod(ad, k).read_text(encoding='utf-8') for k in ('html', 'drawio', 'svg')}
    _se = re.findall(r'<path class="edge"[^>]*>', _w['svg'])
    c.check(bool(_se) and all('stroke-width="2"' in t for t in _se)
            and re.search(r'\.edge\s*\{[^}]*stroke-width:2', _w['html']) is not None
            and 'strokeWidth=2;' in _w['drawio'],
            '三份产物的连线线宽一致（都 2px）',
            f'svg 边 {len(_se)} 条，缺线宽的 {sum("stroke-width" not in t for t in _se)} 条')
    # 同一族还有一条更硬的：这份 svg **一个箭头都没有**（无 `<defs>`、无 `marker-end`）——方向读不出来。
    # 两条都是同一个形态：坐标全对，只有它和另外两份产物不一样，而几何自检查不出"少了什么记号"。
    c.check(bool(_se) and all('marker-end="url(#ar-' in t for t in _se)
            and '<defs>' in _w['svg'] and 'markerUnits="userSpaceOnUse"' in _w['svg'],
            'svg 的每条边都带箭头，且箭头不随线宽缩放（markerUnits=userSpaceOnUse）',
            f'svg 边 {len(_se)} 条，缺箭头的 {sum("marker-end" not in t for t in _se)} 条')

    # 箭头**三份产物同一枚**（D-89）：html 与 svg 的 marker 必须逐字节同款，drawio 的 `endSize` 必须
    # 由同一个常量推出。此前 drawio 写 `blockThin`（导出实测 8×5.3px）、marker 写 14×14——同一张图上
    # 两份产物的箭头差 2.6 倍，drawio 那份小到"看不出有箭头"；几何自检一条都查不出来（它量的是坐标）。
    _mk = {k: sorted(re.findall(r'<marker\b[^>]*>', _w[k])) for k in ('html', 'svg')}
    c.check(bool(_mk['html']) and _mk['html'] == _mk['svg'],
            'html 与 svg 的箭头 marker 逐字节同款（都出自 semantics.arrow_markers）',
            f"html {len(_mk['html'])} 枚 / svg {len(_mk['svg'])} 枚")
    c.check(all(f'markerWidth="{ARROW_LEN}"' in t and f'refX="{ARROW_LEN}"' in t for t in _mk['svg'])
            and f'endArrow=block;endFill=1;endSize={ARROW_END_SIZE};' in _w['drawio'],
            f'三份产物同一枚箭头：{ARROW_LEN}×{ARROW_LEN}px（drawio endSize={ARROW_END_SIZE}，'
            f'= 边长 - 2 的实测换算）',
            f"svg marker={_mk['svg'][:1]}；drawio 有 endArrow=block: "
            f"{'endArrow=block;' in _w['drawio']}")

    rc, out = run('validate.py', '--artifact', prod(ad, 'drawio'), '--dump', ad / 'geom.json')
    import json as _json
    g = _json.loads((ad / 'geom.json').read_text(encoding='utf-8')) if rc == 0 else {}
    first = (g.get('nodes') or {}).get('01', {})
    e0 = (g.get('edges') or [{}])[0]
    c.check(rc == 0 and set(first.get('ports') or {}) == {'left', 'right', 'top', 'bottom'}
            and first.get('center') and first.get('size') and e0.get('start') and e0.get('end')
            and e0.get('points') and 'band' in g and 'lanes' in g and 'exit' in e0 and 'entry' in e0,
            '--dump 产出几何表（中心/尺寸/形状/四端点 + 边起终点/端口比例/折线，含泳道字段）',
            str(first.get('center')) + ' ' + str(first.get('shape')))

    # ① drawio：把端口比例改歪=线离开框（10px 以上），产物侧必须报出"线没接上节点"
    #    「改歪」要**改出框外**才离开形状：沿边挪（0.5→0.9）仍落在同一条边框上，那是合法端口位置——
    #    端口判据按矩形算（矩形类含胶囊，见 D-74），所以这里把比例推过边（1.0→1.3）。
    d = prod(ad, 'drawio')
    raw = d.read_text(encoding='utf-8')
    bad = raw.replace('exitX=0.5;exitY=1.0', 'exitX=0.9;exitY=1.3', 1)
    c.check(bad != raw, '前置：drawio 里有可改的端口比例')
    d.write_text(bad, encoding='utf-8')
    rc, out = run('validate.py', '--artifact', d)
    c.check(rc == 1 and '线没接上节点' in out, '端口比例改歪：报"线没接上节点"',
            (out.strip().splitlines() or [''])[-1][:70] if rc != 1 else '')
    rc_m, _ = run('validate.py', prod(ad, 'yaml'))
    c.check(rc_m == 0, '同一处缺陷：模型门禁照样全绿（正是要补的那一关）')
    run('build.py', fta)

    # ② html：把节点组整体下移 10px——边折线没跟着动，端点就离开了框
    h = prod(ad, 'html')
    rawh = h.read_text(encoding='utf-8')
    m = re.search(r'(<g class="ndg" data-id="[^"]*"(?: data-nid="[^"]*")? transform="translate\()'
                  r'(-?[\d.]+),(-?[\d.]+)(\))', rawh)
    if c.check(bool(m), '前置：html 产物里有可挪的节点组（结构未变则正则应命中）'):
        moved = (rawh[:m.start()] + m.group(1) + m.group(2) + ',' + str(float(m.group(3)) + 10)
                 + m.group(4) + rawh[m.end():])
        h.write_text(moved, encoding='utf-8')
        rc, out = run('validate.py', '--artifact', h)
        c.check(rc == 1 and '线没接上节点' in out, 'HTML 节点被挪走：报"线没接上节点"',
                (out.strip().splitlines() or [''])[-1][:70] if rc != 1 else '')

    # ③ 产物缺节点/是空文件：要友好报错，而不是抛 traceback
    empty = tmp / 'art' / 'empty.drawio'
    empty.write_text('<mxfile><diagram><mxGraphModel><root/></mxGraphModel></diagram></mxfile>', encoding='utf-8')
    rc, out = run('validate.py', '--artifact', empty)
    c.check(rc == 1 and '解析不出任何节点' in out and 'Traceback' not in out,
            '空产物：友好报错而不是 traceback', out.strip()[-70:])

    rc, out = run('validate.py', '--artifact', prod(ad, 'drawio'), '--dump', tmp / 'art' / '没有这个目录' / 'g.json')
    c.check(rc == 1 and '写不出去' in out and 'Traceback' not in out,
            '--dump 目标目录不存在：友好报错而不是 traceback', out.strip()[-70:])


def _check_init_conflict(c, tmp):
    c.section('质检补漏：init 遇到同名文件要友好报错')
    b7 = tmp / 'b7'
    shutil.rmtree(b7, ignore_errors=True)
    b7.mkdir(parents=True)
    (b7 / 'somename').write_text('占位', encoding='utf-8')
    rc7, out7 = run('init.py', 'somename', '-d', b7)
    c.check(rc7 == 1 and '这是文件' in out7 and 'Traceback' not in out7,
            'init 同名文件：中文报错而不是 NotADirectoryError')


def _check_escape(c, tmp):
    c.section('三份产物同口径：特殊字符必须转义（`<` `&` `"`）')
    # 为什么值得一条（2026-09-19，D-125）：转义在**每个渲染器里各写一份**（`esc` / `_esc`，3 行，
    # 三份），而`coding-spec` N3 判它们"不抽公共层——共享的只有几行算术"。那个判断站得住，
    # 但**它当时是一句承诺，没有守门人**：谁都可以在一份里少转义一个字符，另两份照样出图。
    # 判据落在**产物**上（比落在一段公共代码上更贴）：同一个特殊串在三份产物里都必须转义，
    # 且**原文串一处都不许原样出现**。
    d = tmp / 'escape'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02'),
        row('一', '02', 'A<B&C"', '任务', '甲方', '受理员', '—', '标<签&"→03'),
        row('二', '03', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc, out = run('build.py', ft)
    texts = {k: prod(d, k).read_text(encoding='utf-8') for k in ('html', 'drawio', 'svg')}
    raw = [k for k, t in texts.items() if 'A<B&C"' in t or '标<签&"' in t]
    esc = [k for k, t in texts.items() if '&lt;' not in t or '&amp;' not in t]
    c.check(rc == 0 and not raw and not esc,
            '三份产物都把 < & " 转义（原文串一处都不许原样出现）',
            f'rc={rc} · 原文未转义 {raw or "无"} · 缺转义形式 {esc or "无"}'
            + ('' if rc == 0 else f' · {out.strip()[-120:]}'))


def _check_degradation_trace(c, tmp):
    c.section('降级必须留痕：字典缺段要吭声，不能让下游把病因报反（D-129）')
    # 为什么值得一条：`manifest._default_shapes()` 原先读不动就**静默退回 `{}`**，
    # 于是症状变成**下游报一堆"形状不符"**——把"字典缺 `shapes:` 段"说成"产物画错了形状"，
    # 诊断正好指反。留痕之后，读的人第一眼看到的是病因。
    #
    # 判据落在**原始 stderr 字节**上（`D-127` 的教训）：不只是"打了一行"，而是"按 utf-8 解得回来"。
    # 走子进程 + 一个驱动脚本，是因为这条退化路径只认 `manifest.__file__` 旁边的字典——要拿
    # "缺段的字典"喂它，就得把那个位置指过去（`monkeypatch` 只在进程内做得成）。
    d = tmp / 'trace'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / 'dictionary.yaml').write_text('grid:\n  lattice: 10\n', encoding='utf-8')  # 没有 shapes 段
    (d / 'driver.py').write_text(
        'import sys\n'
        'sys.path.insert(0, %r)\n'
        'import manifest\n'
        'manifest.__file__ = %r\n'
        'print(manifest._default_shapes())\n'
        % (str(SKILL / 'scripts'), str(d / 'manifest.py')), encoding='utf-8'), 
    r = subprocess.run([sys.executable, str(d / 'driver.py')], capture_output=True,
                       cwd=str(SKILL), timeout=60)
    raw = r.stderr if isinstance(r.stderr, bytes) else (r.stderr or b'').encode('utf-8', 'replace')
    err = raw.decode('utf-8', 'replace')
    c.check(r.returncode == 0 and r.stdout.strip() == b'{}',
            '缺 `shapes:` 段仍**退回默认**（降级不变成崩溃）', (r.stdout or b'').decode('utf-8', 'replace').strip())
    c.check('⚠' in err and 'shapes' in err and '\\u26a0' not in err,
            '缺段留痕读得出来（原始 stderr 按 utf-8 解得回原句，且点明是字典的问题）',
            err.strip()[:110] or '（stderr 是空的：又变成静默降级了）')


def _check_xml_diff(c, tmp):
    c.section('质检补漏：往返差异要带文件级复核（`sync` 那条路，D-123）')
    # 自造夹具（D-42）：先 build 出一对"表 + drawio"，再比它们——
    # 这样样例怎么改都与本用例无关（此前直接借 examples/ 的表与基线 drawio）。
    #
    # **2026-09-19 改指向**（D-123）：这条文件级复核原先在 `xml_reader --diff` 里，而它让公共层
    # 出现 `xml_reader ↔ writeback` 的环。复核本身是"读回 → 回写 → 逐字节比"的**下一步**，
    # 属于 `sync`（它本来就有这一步，而且写出预览文件供核对——比 `--diff` 里那个用完就丢的
    # 临时文件更有用）。**判据不变**：那句"逐字节一致"必须真被打出来——这是"文件级真相有人报"
    # 的唯一证据。同时钉住 `--diff` 不再假装做这件事：它只报结构差异并**指路 sync**。
    _d, ft, rc0, out0 = _wb_project(tmp, 'xmldiff')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return
    rc9, out9 = run('xml_reader.py', prod(_d, 'drawio'), '--diff', ft)
    c.check('文件级复核' not in out9 and 'sync.py' in out9,
            'xml_reader --diff 只报结构差异，并指路 sync', out9.strip()[-120:])
    rc10, out10 = run('sync.py', prod(_d, 'drawio'), ft)
    c.check(rc10 == 0 and '逐字节一致' in out10,
            'sync 那条路仍报逐字节复核（能力没丢，换了 owner）', out10.strip()[-140:])


def _dead_page_links(dw_text):
    """一个 .drawio 里指向**本文件不存在的页**的下钻链接 → [page_id, …]（无则 []）。

    页 id 由父子两侧**各算一次**（父：`_sub_pages` 查表；子：`discover_pages` 生成页），
    两边一旦用上不同的键，链接就指到一个不存在的页——drawio 点了没反应，**没有任何报错**。
    这正是"子表换了目录、父图没重 build"之后的症状：页能生成、链接也在、就是点不动。
    HTML 侧因为"产物不存在就不画环"天然自愈，drawio 侧没有这层兜底，所以必须显式查。
    """
    pages = set(re.findall(r'<diagram\b[^>]*\bid="([^"]*)"', dw_text))
    return [pid for pid in re.findall(r'link="data:pageId=([^;"]*)', dw_text)
            if pid not in pages]


def _check_subflow_drill(c, tmp):
    c.section('子流程下钻：⊞ 声明 → 内衬线记号 / 悬浮框提示 / 链接 / 面包屑，缺子图则静默降级')
    # 下钻把"实现层"移出主图，但**降级必须是静默的**：主图渲染不该依赖子图是否已 build 过。
    # 钉住五件事：声明解析（含越界拒绝）、产物存在才给入口、递归、面包屑、无标记时零副作用。
    #
    # **每个夹具独占一个子目录**：产物落在**流程表自己所在的目录**里，同目录多张表会互相
    # 覆盖（上一张的产物被下一张 build 掉），用例之间也会互相污染——这是真实行为，不是 bug。
    sd = tmp / 'subflow'
    shutil.rmtree(sd, ignore_errors=True)
    sd.mkdir(parents=True)

    def main_rows(desc):
        return HEAD + ''.join([
            OK[0],
            row('一', '02', '渲染产物', '任务', '甲方', 'build.py', '—', '→03', desc),
            row('二', '03', '交付', '结束', '双方', '双方共责', '—', '—')])

    SUB_ROWS = HEAD + ''.join([
        row('一', 'R1', '接单', '开始', '甲方', '受理员', '—', '→R2', '★'),
        row('二', 'R2', '完成', '结束', '双方', '双方共责', '—', '—')])

    # ① 正常路径：子表先 build（自底向上），主图才画内衬线记号
    a = sd / 'ok'
    (a / 'parts').mkdir(parents=True, exist_ok=True)
    sub = a / 'parts' / 'rendering.md'
    sub.write_text(SUB_ROWS, encoding='utf-8')
    ft = a / 'flowtable.md'
    ft.write_text(main_rows('⊞ parts/rendering.md；填完九列方可渲染'), encoding='utf-8')

    rc_sub, out_sub = run('build.py', sub)
    c.check(rc_sub == 0, '前置：子表可独立 build（它是一张完整流程表）',
            '' if rc_sub == 0 else out_sub.strip()[-90:])
    rc, out = run('build.py', ft)
    c.check(rc == 0, '主表 build 通过（含下钻那一步）', '' if rc == 0 else out.strip()[-90:])

    h = (prod(a, 'html')).read_text(encoding='utf-8')
    dw = (prod(a, 'drawio')).read_text(encoding='utf-8')
    sub_html = prod(a / 'parts', 'html', 'rendering.md')      # parts/rendering-flow.html（D-51）
    # D-52 之后下钻**不跳页**：子图内嵌在同一份 html 里，`data-sub` 是"切到哪个视图"，
    # 不再是子图产物的相对路径。链接对不对，判据也从"文件在不在"变成"那个视图在不在本页"。
    sub_view = relp(a / 'parts' / 'rendering.md', a)
    c.check(f'data-sub="{sub_view}"' in h and f'data-view="{sub_view}"' in h,
            'HTML：可下钻节点带 data-sub，指向**本文件里内嵌的那个视图**（D-52：不跳页）',
            sub_view)
    _dl = set(re.findall(r'data-sub="([^"]*)"', h)) - set(re.findall(r'data-view="([^"]*)"', h))
    c.check(not _dl, '每个下钻入口都指向本页真实存在的视图（没有点了没反应的死链）',
            '死链 %s' % (_dl or ''))
    # 记号是**框内一道内衬线**（同形状内缩 2px / 1px / 55%，见 D-78）。这条断言的重点是
    # **它不出框**：出了框就同时和端口、相邻墨迹、包围盒/网格打交道——向外叠影那版就是这样
    # （向下的出线从卡片里钻出来），而"出框"这整类病几何自检查不出来。
    c.check('class="sub-ring"' in h, 'HTML：渲染出内衬线记号')
    _ring = re.search(
        r'<g class="ndg"[^>]*data-sub="[^"]*"[^>]*>\s*'
        r'<rect class="shape" x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"[^>]*/>\s*'
        r'<rect class="sub-ring" x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"', h)
    c.check(_ring is not None, '内衬线紧跟在本体之后、且是独立元素（不是给描边加个 class）')
    if _ring:
        sx, sy, sw, sh_, rx_, ry_, rw, rh = (float(v) for v in _ring.groups())
        c.check(rx_ >= sx + 1 and ry_ >= sy + 1 and rx_ + rw <= sx + sw - 1 and ry_ + rh <= sy + sh_ - 1,
                '内衬线**完全落在节点包围盒内**（至少内缩 1px）——不碰端口/连线/网格',
                f'本体 {sx:g},{sy:g},{sw:g}×{sh_:g} 内衬 {rx_:g},{ry_:g},{rw:g}×{rh:g}')
    # 记号**只有静态那一层**（见 D-80）：曾经悬停时另跑一段光沿它转一圈，撤掉了——
    # ① 与"连线上已经在跑的那道流光"重复；② "这里能点"是可点击这件事的自然延伸，
    # 由**悬浮框**在用户已经伸手去点的时候说最准，不必在图上报时。
    c.check('sub-run' not in h and 'sub-ring-scan' not in h and 'march' not in h,
            '内衬线是**静态**的：跑光/跑马灯一点没剩（不靠动效才醒目）')
    c.check(re.search(r'\.sub-ring\s*\{', h) is None,
            '内衬线连样式都不写（规格全在元素属性上）——所以它没有任何可动的余地')
    # "这里能点"改由**悬浮框标题行右侧的灰字**说：判据就是 `d.sub`，
    # 与内衬线、下钻入口同一个真值（声明了 ⊞ 但子图没拿到的节点，三样一起不出现）。
    c.check(h.count('点击查看流程详情') == 1 and 'ttSub' in h,
            '悬浮框在节点名右侧提示「点击查看流程详情」（一处文案，不逐节点复制）')
    c.check(re.search(r'\.node-tooltip \.tt-sub\s*\{[^}]*color:#999999', h) is not None
            and 'class="tt-sub" id="ttSub"' in h,
            '提示是**灰字、挂在标题行内**（在名称右侧，不占用节点内那几行语义文字）')
    c.check(re.search(r'ttSub\.innerText = d\.sub \?', h) is not None,
            '提示只在**内嵌了子图**的节点上出现（判据与内衬线、下钻入口同一个）')
    # 箭头/滤镜的**定义只许一份、且在视图之外**（D-90）。`url(#ar-main)` 按 id 解析，浏览器只认
    # 文档里的第一份；第一份若落在某个视图里，切到别的视图时它随 `display:none` 一起不渲染——
    # 于是**子视图一条箭头都没有**（主图正常，所以这个 bug 只在有子图的产物上显形）。
    # 「定义在视图之外」还要「在视图之后」：marker 自带 `viewBox="0 0 10 10"`，
    # 放在画布前会让 `manifest._html_canvas` 把画布读成 10×10（build 的几何自检当场退非 0）。
    _vd = re.search(r'<svg class="vdefs".*?</svg>', h, re.S)
    _fv = h.find('<div class="view')
    c.check(_vd is not None and len(re.findall(r'id="ar-main"', h)) == 1 and _fv > 0
            and _vd.start() > _fv,
            '箭头/滤镜的定义只有一份，且在**所有视图之外、之后**（否则子视图没有箭头、'
            '或画布被读成 10×10）',
            f'vdefs={"有" if _vd else "无"}；ar-main 份数 {len(re.findall(chr(34) + "ar-main" + chr(34), h))}')
    # 悬停配对用 `data-nid`（DSL 原始编号）与边的 `data-from/to` 同口径（D-90）：子视图里
    # `data-id` 带 `视图key::` 前缀，拿它比 `data-from` 永远不相等 ⇒ 悬停什么也不亮。
    _pairs, _badpair = 0, []
    for _m in re.finditer(r'<div class="view[^"]*" data-view="([^"]*)"[^>]*>(.*?)(?=<div class="view|</body>)',
                          h, re.S):
        _seg, _view = _m.group(2), _m.group(1)
        _ends = set(re.findall(r'data-from="([^"]*)"', _seg)) | set(re.findall(r'data-to="([^"]*)"', _seg))
        for _nid in re.findall(r'<g class="ndg" data-id="[^"]*" data-nid="([^"]*)"', _seg):
            _pairs += 1
            if _nid not in _ends:
                _badpair.append(f'{_view}:{_nid}')
    c.check(_pairs and not _badpair,
            '悬停配对的 `data-nid` 与边的 `data-from/to` 同口径（子视图也点得亮流光）',
            f'配不上的 {_badpair[:3]}')
    # 流光的两层（晕 + 芯）都必须真的画出来：晕带 `filter`，滤镜解析不了它就不渲染，
    # 而 `.is-run` 挂在晕上——于是"悬停有反应但没有光"。这两条一起钉住"看得见的光"。
    _vflow = re.search(r'class="edge-flow"[^>]*filter="url\(#soft-glow\)"', h)
    c.check(_vflow is not None and 'id="soft-glow"' in h,
            '流光的晕层带滤镜、滤镜定义也在（解析不了就整层不画＝悬停没有光）')
    _sv = prod(a, 'svg').read_text(encoding='utf-8')
    c.check('class="sub-ring"' in _sv and 'sub-run' not in _sv and '@keyframes' not in _sv,
            'svg 也有内衬线，但**不带任何动画**（装饰只住 HTML）')
    c.check('flowchartSkillSub=1' in dw and 'opacity=55' in dw,
            'drawio 的内衬线同样带"我不是节点"标记，回读时才不会被当成真节点')
    c.check('⊞' not in h,
            'HTML 里不再出现 ⊞ 字符（描述里的声明语法已剥掉——路径是给机器读的管道）')
    c.check('restoreScroll' in h and 'SCROLL_KEY' in h,
            '返回主图时恢复视窗位置（下钻回来不会把人扔回左上角）')
    c.check("_cc.addEventListener('scroll'" in h,
            '`scroll` 事件**不冒泡**：容器内部滚动必须单独挂监听，否则那段位移记不下来')
    c.check(h.count('data-sub="') == 1, '只有声明了 ⊞ 的节点有 data-sub',
            '实际 %d 个' % h.count('data-sub="'))
    c.check(re.search(r'<g class="ndg" data-id="02"[^>]*data-sub=', h) is not None,
            '叠影画在对的那一个节点上（不是随便一个）')
    c.check('data:pageId=' in dw and dw.count('<diagram ') == 2,
            'drawio：多页（主图 + 子页），节点带 data:pageId 链接',
            '页数 %d' % dw.count('<diagram '))
    c.check(not _dead_page_links(dw),
            'drawio：下钻链接都指向**本文件里真的存在的页**（没有死链）',
            '死链 %s' % (_dead_page_links(dw) or ''))
    c.check('.ndg[data-sub]' in h and 'cursor:pointer' in h,
            '可下钻节点是 pointer 光标（不可点的节点是 default——与"看起来能不能点"一致）')

    # 面包屑：子图要能走回主图，否则"下钻进去出不来"比不做还糟
    sh = sub_html.read_text(encoding='utf-8')
    c.check('class="crumbs"' in sh and '返回主图' in sh, '子图带「← 返回主图」面包屑')
    c.check('has-crumbs' in sh, '有面包屑时标题模块下移（两个 fixed 不重叠）')
    c.check('class="crumbs"' not in h, '顶层主图**不**渲染面包屑')
    c.check(f'href="{relp(prod(a, "html"), a / "parts")}"' in sh, '回程链接指回**父图产物**',
            relp(prod(a, 'html'), a / 'parts'))

    # ② 子图 DSL 缺失 → 静默降级。
    #    D-52 之后下钻依赖的是子图**DSL**（html 不再单独产出），所以这里藏的是 yaml；
    #    而且必须直接跑 render_html.py——build.py 会把缺的 DSL 自动补上（那是要的行为），
    #    拿 build 测降级等于测了个空。
    sub_yaml = prod(a / 'parts', 'yaml', 'rendering.md')
    off = sub_yaml.with_name(sub_yaml.name + '.off')
    sub_yaml.rename(off)                 # 改名而非删除：删文件会触发批量删除保护
    rc2, out2 = run('render_html.py', str(prod(a, 'yaml')), '-o', str(prod(a, 'html')))
    h2 = (prod(a, 'html')).read_text(encoding='utf-8')
    c.check(rc2 == 0 and 'data-sub="' not in h2 and 'class="sub-stack"' not in h2,
            '子图 DSL 缺失：主图静默降级（无叠影卡、无死链、不报错）', 'rc=%d' % rc2)
    off.rename(sub_yaml)
    rc_sub2, _ = run('build.py', sub)
    c.check(rc_sub2 == 0, '前置：子图产物可再次构建')

    # ⑦ 可移植性：页 id 不能依赖**绝对路径**——换个目录 build 必须字节相同。
    # 早先 `page_id_for` 哈希的是 `.resolve()` 后的绝对路径，于是"同一份表换个目录"
    # 就换一套页 id：既破字节确定性，也让任何带子流程的样例在副本里必然"不幂等"
    # （副本目录路径本就不同）。这条把"页 id 锚在相对路径上"钉死。
    import subprocess as _sp
    twin = sd / 'twin'
    shutil.rmtree(twin, ignore_errors=True)
    shutil.copytree(a, twin)
    for tbl in (twin / 'parts' / 'rendering.md', twin / 'flowtable.md'):
        r7 = _sp.run([sys.executable, str(SKILL / 'scripts' / 'build.py'), str(tbl)],
                     capture_output=True, text=True, encoding='utf-8')
        if r7.returncode != 0:
            break
    dw_a = (prod(a, 'drawio')).read_bytes()
    dw_t = (prod(twin, 'drawio')).read_bytes()
    c.check(r7.returncode == 0 and dw_a == dw_t,
            '换个目录 build：drawio 字节相同（页 id 不依赖绝对路径）',
            '' if dw_a == dw_t else '副本产物不同')

    # ⑧ 非法路径一律拒绝（不能给用户一个点到系统目录的链接）——**并且在声明层就报出来**。
    # 原先这三条走的是"静默忽略"：越界的 ⊞ 在声明层一字不报，只有下游那句「孤儿表 x」，
    # 而它把责任指向**被引用的那张表**（写错路径的却是引用方）⇒ 人会去改错文件。
    # G77 之后 `_check_subflow_decl` 在声明层报硬错误，build 随之阻断、不产出任何可点入口。
    for k, (bad, why) in enumerate((('⊞ ../escape.md；越界', '../ 越界'),
                                    ('⊞ /etc/passwd', '绝对路径'),
                                    ('⊞ C:////win////x.md', '盘符路径'))):
        d = sd / f'bad{k}'
        d.mkdir(parents=True, exist_ok=True)
        p = d / 'flowtable.md'
        p.write_text(main_rows(bad), encoding='utf-8')
        rc3, o3 = run('table_to_dsl.py', '--check', p)
        c.check(rc3 != 0 and '越出' in o3, f'非法子表路径在**声明层**就报硬错误：{why}',
                o3.strip()[-110:])
        rc3b, _ = run('build.py', p)
        c.check(rc3b != 0 and not prod(d, 'html').exists(),
                f'非法子表路径：build 阻断、不产出任何可点入口：{why}', f'rc={rc3b}')

    # ⑨ 一格两个 ⊞：解析器只取第一个 ⇒ 第二个静默作废（G76）。也升成硬错误，
    # 理由同 ⑧：留着它，用户看到的是"这个节点点不进去"，而没有任何一句话说得出为什么。
    for k, (bad, why) in enumerate((('⊞ parts/rendering.md ⊞ parts/rendering.md；叠两个', '两个 ⊞'),
                                    ('⊞ /etc/x ⊞ parts/rendering.md', '一个合法一个越界'))):
        d = sd / f'two{k}'
        d.mkdir(parents=True, exist_ok=True)
        p = d / 'flowtable.md'
        p.write_text(main_rows(bad), encoding='utf-8')
        rc5, o5 = run('table_to_dsl.py', '--check', p)
        c.check(rc5 != 0 and '个 `⊞`' in o5, f'一格多个 ⊞ 报硬错误：{why}', o5.strip()[-110:])

    # ④ 无 ⊞ 的表：零副作用（既有产物字节不变的那条约束的用例化）
    d = sd / 'plain'
    d.mkdir(parents=True, exist_ok=True)
    p = d / 'flowtable.md'
    p.write_text(main_rows('填完九列方可渲染'), encoding='utf-8')
    rc4, _ = run('build.py', p)
    hp = (prod(d, 'html')).read_text(encoding='utf-8')
    dp = (prod(d, 'drawio')).read_text(encoding='utf-8')
    c.check(rc4 == 0 and 'data-sub="' not in hp, '无 ⊞ 的表：不产生任何 data-sub')
    c.check(dp.count('<diagram ') == 1 and 'data:pageId' not in dp,
            '无 ⊞ 的表：drawio 仍是单页、无页链接')

    # ⑤ 递归：三层真的能连起来（L1 → L2 → L3），不是"只支持一层"
    #
    # **每一层各自独占一个目录**——这不是为了整洁，而是"产物落在流程表所在目录"
    # 逼出来的硬约束。若 L2、L3 同放一个目录，两次 build 会写同一份产物
    # （目录名相同 → 产物名相同），后一次直接覆盖前一次——链看着"build 成功",
    # 实际只剩最后一层，递归根本断在里面（实测：这就是第一版夹具假红的原因）。
    # 真实用法里子表放在自己的子目录（`parts/渲染/`），所以夹具也必须照这个形状摆。
    g = sd / 'deep'
    l2d = g / 'parts' / 'l2'
    l3d = l2d / 'l3'
    l3d.mkdir(parents=True, exist_ok=True)
    (l3d / 'leaf.md').write_text(HEAD + ''.join([
        row('一', 'Z1', '开始', '开始', '甲方', '受理员', '—', '→Z2', '★'),
        row('二', 'Z2', '到底了', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    (l2d / 'mid.md').write_text(HEAD + ''.join([
        row('一', 'M1', '开始', '开始', '甲方', '受理员', '—', '→M2', '★'),
        row('一', 'M2', '再下钻', '任务', '甲方', '受理员', '—', '→M3', '⊞ l3/leaf.md；还有一层'),
        row('二', 'M3', '停', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    (g / 'flowtable.md').write_text(main_rows('⊞ parts/l2/mid.md；最深的一支'),
                                    encoding='utf-8')
    rc5a, o5a = run('build.py', l3d / 'leaf.md')
    rc5b, o5b = run('build.py', l2d / 'mid.md')
    rc5c, o5c = run('build.py', g / 'flowtable.md')
    c.check(rc5a == 0 and rc5b == 0 and rc5c == 0, '三层嵌套各自 build 通过',
            '' if rc5a == rc5b == rc5c == 0 else ((o5a + o5b + o5c).strip()[-90:]))
    # 三层各自的表名都不是约定名，产物名必须**按表名**算（mid-flow.html / leaf-flow.html）
    h1 = prod(g, 'html').read_text(encoding='utf-8')
    h2d = prod(l2d, 'html', 'mid.md').read_text(encoding='utf-8')
    h3d = prod(l3d, 'html', 'leaf.md').read_text(encoding='utf-8')
    k_l2 = relp(l2d / 'mid.md', g)
    k_l3 = relp(l3d / 'leaf.md', l2d)
    c.check(f'data-sub="{k_l2}"' in h1, 'L1 图指向 L2（入口链第一跳）', k_l2)
    c.check(f'data-sub="{k_l3}"' in h2d, 'L2 图指向 L3（递归成立，不是只支持一层）', k_l3)
    # L1 是递归内嵌的：L3 也要在**同一份文件**里（不然从主图点两层就断了）
    c.check(f'data-view="{relp(l3d / "leaf.md", g)}"' in h1,
            'L1 单文件里连孙层一起内嵌（点两层也不出文件）', relp(l3d / 'leaf.md', g))
    c.check('class="crumbs"' in h2d and 'class="crumbs"' in h3d, 'L2 与 L3 都有回程面包屑')
    c.check('class="crumbs"' not in h1, 'L1（顶层）仍无面包屑')
    # 回程每一跳都要落在**上一层的产物**上，逐层指回去才算链闭合
    c.check(f'href="{relp(prod(g, "html"), l2d)}"' in h2d, 'L2 面包屑指回 L1 产物',
            relp(prod(g, 'html'), l2d))
    c.check(f'href="{relp(prod(l2d, "html", "mid.md"), l3d)}"' in h3d, 'L3 面包屑指回 L2 产物',
            relp(prod(l2d, 'html', 'mid.md'), l3d))
    d3 = (prod(g, 'drawio')).read_text(encoding='utf-8')
    # 主 .drawio 不递归铺：只铺**直接子页**（L2）。三层全塞进一个文件会让页数与
    # 文件体积随深度线性膨胀，而 drawio 自己支持"子页里再挂子页"——这是刻意的边界。
    c.check('data:pageId=' in d3 and d3.count('<diagram ') == 2,
            '主 .drawio 只铺直接子页（1 主图 + L2），不递归膨胀',
            '页数 %d' % d3.count('<diagram '))
    # 三层各自的 drawio 都不许有死链——L2 换了目录后 L1 若没重 build，这条会红
    for who, p in (('L1', prod(g, 'drawio')),
                   ('L2', prod(l2d, 'drawio', 'mid.md')),
                   ('L3', prod(l3d, 'drawio', 'leaf.md'))):
        dead = _dead_page_links(p.read_text(encoding='utf-8'))
        c.check(not dead, f'{who} 的 drawio 无死链', '死链 %s' % (dead or ''))


def _color_proj(tmp, tag, main_decl, sub_decl, chain=()):
    """造一个"主表 + 子表（可再嵌一层）"的小工程 → (主表 Path, 子表 Path)。

    `chain` 用来造更深的链：`('l2', 'l3')` 表示主表 → l2 → l3，每层独占目录
    （产物名约定的硬约束，见 `_check_subflow_drill` ⑤ 的注释）。
    """
    d = tmp / 'colors' / tag
    shutil.rmtree(d, ignore_errors=True)
    cur = d
    (cur / 'parts').mkdir(parents=True, exist_ok=True)
    # 配色声明走正文「## 主体配色」小节（D-59 hex 方案）
    decl = _color_section_names(main_decl)
    rows = [row('一', 'A1', '开始', '开始', '用户', 'u', '—', '→A2', '★'),
            row('一', 'A2', '干活', '任务', '机器', 'm', '—', '→A3', '⊞ parts/sub.md；下钻'),
            row('二', 'A3', '结束', '结束', '双方', 'b', '—', '—')]
    if chain:                       # 子表名按链首改写，让 `⊞` 指得准
        rows[1] = row('一', 'A2', '干活', '任务', '机器', 'm', '—', '→A3',
                      f'⊞ parts/{chain[0]}/{chain[0]}.md；下钻')
    (d / 'flowtable.md').write_text(decl + '# 主\n' + HEAD + ''.join(rows), encoding='utf-8')

    sdecl = _color_section_names(sub_decl)
    srows = [row('一', 'S1', '起', '开始', '机器', 'm', '—', '→S2', '★'),
             row('二', 'S2', '止', '结束', '机器', 'm', '—', '—')]
    if chain:
        p = d / 'parts' / chain[0]
        p.mkdir(parents=True, exist_ok=True)
        (p / f'{chain[0]}.md').write_text(sdecl + '# L2\n' + HEAD + ''.join(srows), encoding='utf-8')
        return d / 'flowtable.md', p / f'{chain[0]}.md', p
    p = d / 'parts'
    (p / 'sub.md').write_text(sdecl + '# 子\n' + HEAD + ''.join(srows), encoding='utf-8')
    return d / 'flowtable.md', p / 'sub.md', p


def _subjects_of(yaml_path):
    import yaml as _y
    return (_y.safe_load(Path(yaml_path).read_text(encoding='utf-8'))['meta'].get('subjects') or {})


def _check_color_contract(c, tmp):
    c.section('执行主体配色：声明 → 跨层继承 → 冲突阻断（D-49）')
    # 颜色的**取值**不重要，**跨层一致**才重要：主图「机器」橙、子图「机器」蓝，等于
    # 同一个主体在两个层级有两个身份。所以这组用例钉的不是"哪个色好看"，而是：
    # 声明了就钉住、没声明就继承、写错了就拦下、不写就与从前逐字节相同。
    sd = tmp / 'colors'
    shutil.rmtree(sd, ignore_errors=True)

    # ① 声明 → 钉住；② 子表不声明 → 继承主表（这是"一致性"的主战场）
    m, s, p = _color_proj(tmp, 'inherit', '用户=蓝 ｜ AI=绿 ｜ 机器=橙 ｜ 双方=黄', None)
    rc, out = run('table_to_dsl.py', '--write', m)
    rcs, outs = run('table_to_dsl.py', '--write', s)
    c.check(rc == 0 and rcs == 0, '声明 + 继承：两张表都通过', (out + outs).strip()[-90:])
    ms, ss = _subjects_of(prod(p.parent, 'yaml')), _subjects_of(p / 'sub-flow.yaml')
    c.check(ms.get('机器', {}).get('fill') == '#ffe6cc',
            '声明生效：「机器=橙」钉住，不再按出现顺序漂')
    c.check(ss.get('机器', {}).get('fill') == '#ffe6cc',
            '子表**未声明**时继承主表：子图「机器」仍是橙（不是它自己排第一拿到的蓝）')
    c.check(ms.get('机器') == ss.get('机器') and ms.get('用户') == ss.get('用户'),
            '同名主体跨层**同色**——这是本组用例要保的那条不变式')
    # 图例展示主体全集：子图只用到「机器」，图例却与主图同构，看一层就知道全项目有哪些主体
    c.check(set(ss) == set(ms) and len(ss) == 4,
            '子图图例是主体全集（不随本图用到几个而变），跨层图例同构',
            '实际 %s' % sorted(ss))

    # ③ 冲突：子表显式写了另一种颜色 → 硬错误阻断，且报错说清是哪一层
    _, s2, p2 = _color_proj(tmp, 'conflict', '用户=蓝 ｜ 机器=橙', '机器=红')
    rc2, out2 = run('table_to_dsl.py', '--write', s2)
    c.check(rc2 != 0 and '执行主体配色冲突' in out2,
            '子表声明与父表不一致 → 阻断（不是静默取一边）', 'rc=%d' % rc2)
    c.check('flowtable' in out2,
            '冲突报错点名**是哪张祖先表**在跟本表打架（否则用户不知道该改哪边）')

    # ④ 只跟"继承链上最近的显式声明"比——隔着一层未声明的表也要查出来。
    #    只跟直接父表比的话，L1=橙 / L2 未声明 / L3=红 会被漏掉。
    d3 = sd / 'deep'
    (d3 / 'parts' / 'l2' / 'l3').mkdir(parents=True, exist_ok=True)
    (d3 / 'flowtable.md').write_text(
        _color_section_names('机器=橙') + '# L1\n' + HEAD +
        row('一', 'A1', '开始', '开始', '用户', 'u', '—', '→A2', '★') +
        row('一', 'A2', '干活', '任务', '机器', 'm', '—', '→A3', '⊞ parts/l2/l2.md；下钻') +
        row('二', 'A3', '结束', '结束', '双方', 'b', '—', '—'), encoding='utf-8')
    (d3 / 'parts' / 'l2' / 'l2.md').write_text(          # L2 **不声明**
        '# L2\n' + HEAD +
        row('一', 'M1', '起', '开始', '机器', 'm', '—', '→M2', '★') +
        row('一', 'M2', '再下钻', '任务', '机器', 'm', '—', '→M3', '⊞ l3/l3.md；再一层') +
        row('二', 'M3', '止', '结束', '机器', 'm', '—', '—'), encoding='utf-8')
    (d3 / 'parts' / 'l2' / 'l3' / 'l3.md').write_text(   # L3 反着来
        _color_section_names('机器=红') + '# L3\n' + HEAD +
        row('一', 'Z1', '起', '开始', '机器', 'm', '—', '→Z2', '★') +
        row('二', 'Z2', '止', '结束', '机器', 'm', '—', '—'), encoding='utf-8')
    rc3, out3 = run('table_to_dsl.py', '--write', d3 / 'parts' / 'l2' / 'l3' / 'l3.md')
    c.check(rc3 != 0 and '执行主体配色冲突' in out3,
            '隔一层也要查出来：L1 声明 / L2 未声明 / L3 反色 → 阻断',
            'rc=%d' % rc3)
    rc3b, out3b = run('table_to_dsl.py', '--write', d3 / 'parts' / 'l2' / 'l2.md')
    l2s = _subjects_of(d3 / 'parts' / 'l2' / 'l2-flow.yaml') if rc3b == 0 else {}
    c.check(rc3b == 0 and l2s.get('机器', {}).get('fill') == '#ffe6cc',
            'L2 未声明 → 继承 L1 的橙（继承链穿过"未声明的中间层"）')

    # ⑤ 坏声明一律拦下，且报错给出正确写法——写错却静默按默认值跑，
    #    用户看到的是"我声明了怎么没生效"，这类 bug 极难自查
    for tag, decl, want in (('badname', '机器=柠檬绿', '不是合法 hex'),
                            ('clash', '甲=蓝 ｜ 乙=蓝', '同一种颜色'),
                            ('dup', '机器=橙 ｜ 机器=红', '两种不同的颜色')):
        _, sx, px = _color_proj(tmp, tag, None, decl)
        rcb, outb = run('table_to_dsl.py', '--write', sx)
        c.check(rcb != 0 and want in outb, f'坏声明被拦：{tag} → 报「{want}」', 'rc=%d' % rcb)
        if tag == 'badname':
            c.check('#RRGGBB' in outb, '非 hex 的报错**给出正确格式**（否则用户只能猜）')
            # 回归（2026-09-13 复审）：resolve_colors 曾把 _color_map 就地追加的 errs 又 extend
            # 一遍（同一列表自追加），每条配色错误打印两次
            c.check(outb.count('不是合法 hex') == 1, '配色错误只报一次（不重复打印）')
        if tag == 'dup':
            # 回归（2026-09-13 复审）：内部键 __color_dup__ 曾不在 H9 白名单里，重复声明会
            # 额外挨一条指错方向的「H9 未知元信息键 __color_dup__」
            c.check('__color_dup__' not in outb,
                    '重复声明只报「两种颜色」一条，不附带指错方向的未知键报错')

    # ⑥ 零影响：不声明 → 与"按出现顺序自动分配"完全一致（既有流程表不加这行也照旧）
    _, s6, p6 = _color_proj(tmp, 'plain', None, None)
    rc6, _ = run('table_to_dsl.py', '--write', s6)
    s6s = _subjects_of(p6 / 'sub-flow.yaml')
    c.check(rc6 == 0 and s6s.get('机器', {}).get('fill') == '#dae8fc',
            '不声明 → 行为与从前一致（子图「机器」= 蓝，第 1 个出现拿到第 1 档）')

    # ⑦ 部分声明：未声明的主体**跳过已占用档**，不会与显式声明的主体撞色
    m7, s7, p7 = _color_proj(tmp, 'partial', '机器=橙', None)
    run('table_to_dsl.py', '--write', m7)
    m7s = _subjects_of(prod(p7.parent, 'yaml'))
    c.check(m7s.get('机器', {}).get('fill') == '#ffe6cc' and m7s.get('用户', {}).get('fill') == '#dae8fc',
            '部分声明：声明的钉住，其余从**未占用档**里取（不会也分到橙）',
            '%s' % {k: v['fill'] for k, v in m7s.items()})

    # ⑧ 声明写进元信息区也要能被 sync 读回——sync 会整段重写表格，元信息区若被丢弃，
    #    一次同步就把配色声明冲掉了（"改个几何，颜色全乱"）
    run('build.py', m7)                  # sync 读的是产物，先有 drawio 才有得比
    rc8, out8 = run('sync.py', str(prod(p7.parent, 'drawio')), str(m7))
    c.check(rc8 == 0 and '主体配色' in (p7.parent / 'flowtable.sync.md').read_text(encoding='utf-8'),
            'sync 回写后**保留**配色声明（配置小节不随回写丢失）', 'rc=%d' % rc8)


def _move_node(text, nid, dx, dy):
    """只挪一个节点的位置（改 `<object id=..>` 内部 mxGeometry 的 x/y），不动任何语义属性。

    这是"用户在 drawio 里拖了一下框"的最小等价改动——用来验证**几何改动只影响 html**。
    """
    def _one(m):
        if m.group(1) != nid:
            return m.group(0)
        body = m.group(2)

        def _geo(gm):
            x, y = float(gm.group(1)) + dx, float(gm.group(2)) + dy
            return (gm.group(0).replace(f'x="{gm.group(1)}"', f'x="{x:g}"')
                              .replace(f'y="{gm.group(2)}"', f'y="{y:g}"'))
        return m.group(0).replace(body, re.sub(
            r'<mxGeometry[^>]*?\bx="([-\d.]+)"\s+y="([-\d.]+)"', _geo, body, count=1))
    return re.sub(r'<object\b[^>]*?\bid="([^"]+)"[^>]*?>(.*?)</object>', _one, text, flags=re.S)


def _check_edge_flow(c, tmp):
    c.section('主干边流光：只叠主干、只进 HTML、可被「减少动态效果」关掉')
    # 流光纯装饰、不承载语义 —— 正因如此它**必须**守住三条边界，否则就是拿观感换正确性：
    #   ① 只叠主干（实线）边：分支/回路本就是虚线，再叠流动会满屏乱闪，
    #      还会把"虚线 = 负向"这条语义挤掉（一个视觉通道只承载一个语义维度）。
    #   ② 叠层不能被当成一条边：产物审核靠 `<path class="edge"` 与 data-from/to 认边，
    #      叠层带了任一个就会让"边集合"凭空多一条，审核立刻炸。
    #   ③ 只进 HTML：drawio 是另一个平级模块，不该被 HTML 的装饰污染。
    d = tmp / 'edgeflow'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    # 夹具刻意同时含：主干实线两条（01→02、02→03）+ 回路虚线一条（02→01，带判断，H6 放行）
    ft.write_text(HEAD + ''.join([
        row('一', '01', '受理', '开始', '甲方', '甲', '—', '→02'),
        row('二', '02', '要不要？', '判断', '甲方', '甲', '—', '要→03 ｜ 不要→回 01'),
        row('三', '03', '归档', '结束', '甲方', '甲', '—', '—')]), encoding='utf-8')
    rc, out = run('build.py', ft)
    if not c.check(rc == 0, '前置：夹具可 build', '' if rc == 0 else out.strip()[-90:]):
        return
    html = (d / 'edgeflow-flow.html').read_text(encoding='utf-8')
    drawio = (d / 'edgeflow-flow.drawio').read_text(encoding='utf-8')
    base = re.findall(r'<path class="edge"[^>]*>', html)
    flow = re.findall(r'<path class="edge-flow"[^>]*>', html)
    dashed = [t for t in base if 'stroke-dasharray' in t]
    solid = [t for t in base if 'stroke-dasharray' not in t]
    c.check(bool(solid) and len(flow) == len(solid), '每条主干边恰好一条流光（虚线边不叠）',
            f'底边 {len(base)}（实线 {len(solid)} / 虚线 {len(dashed)}），流光 {len(flow)}')
    c.check(not [t for t in flow if 'data-from' in t or 'data-to' in t],
            '叠层不带 data-from/to（否则会被产物审核算成第二条边）')
    # ④ 两层同一道光（见 D-79）：晕（宽 + 模糊 + 暗）+ 芯（窄 + 实 + 加深）。数量必须相等、
    #    芯紧跟晕（CSS 用相邻兄弟选择器带动它），且**两层都不许用白色**——
    #    白只在深色底上发光；我们的底是白画布与浅色填充，白在那儿只能"把线擦亮"。
    core = re.findall(r'<path class="edge-flow-core"[^>]*>', html)
    c.check(len(core) == len(flow), '每条流光都有芯层（晕 + 芯 = 两层同一道光）',
            f'晕 {len(flow)} / 芯 {len(core)}')
    c.check(re.search(r'class="edge-flow"[^>]*/><path class="edge-flow-core"', html) is not None
            and '.edge-flow.is-run + .edge-flow-core' in html,
            '芯紧跟晕、由相邻兄弟选择器带动（JS 那套一一配对因此不用改）')
    c.check(not [t for t in flow + core if 'fff' in t.lower()],
            '两层都不用白色（在白底上那只会读成"擦亮一段"）')
    c.check(re.search(r'\.edge-flow\s*\{[^}]*stroke-opacity', html) is not None
            and html.count('filter="url(#soft-glow)"') >= len(flow),
            '晕用 stroke-opacity 压暗（动画动的是 opacity，写它会连晕一起点满）+ 共用一条模糊')
    c.check('<filter id="soft-glow"' in html, '那条模糊全文档只定义一次')
    ds = {re.search(r' d="([^"]*)"', t).group(1) for t in solid if re.search(r' d="([^"]*)"', t)}
    fs = {re.search(r' d="([^"]*)"', t).group(1) for t in flow if re.search(r' d="([^"]*)"', t)}
    c.check(bool(fs) and fs <= ds, '流光几何与底边同形（不新增几何，故不参与碰撞检测）',
            f'流光里有底边没有的 d：{sorted(fs - ds)[:1]}')
    c.check('@keyframes edge-flow-trace' in html, 'CSS 里有流光动画关键帧')
    # **悬停期间循环**，但绝不是常驻（见 D-80）：常驻会把"实线/虚线"这条作者语义磨掉，
    # 也看不出这束光是在回答"我现在看着谁"；而一触发只跑一趟则一闪而过，读不出"光顺着流程走"。
    c.check(re.search(r'\.edge-flow\.is-run[^{]*\{[^}]*animation:edge-flow-trace[^}]*infinite',
                      html) is not None,
            '流光在悬停期间**循环**（不是跑一趟即停）')
    c.check('infinite' not in re.search(r'\.edge-flow\s*\{[^}]*\}', html).group(0)
            and "classList.remove('is-run')" in html and 'mouseleave' in html,
            '循环只活在悬停期间：基础样式不跑，鼠标离开即摘 .is-run')
    # 悬停反馈**只加不减**（D-76）：相关主干边循环跑流光；无关项一动不动。
    # 曾经的压暗（opacity 0.13）会连 ⚠ 的橙/红描边、主体配色、执行者小字一起抹掉——那是删信息。
    c.check('flow-focus' not in html and 'is-sel' not in html
            and re.search(r'opacity\s*:\s*0\.1', html) is None,
            '悬停不再压暗任何东西（没有 flow-focus / is-sel / 0.1x 的 opacity）')
    # 相关边**不加粗**（见 D-80）：同一个意思不说两遍——边上的光已经在回答"哪儿相关"，
    # 实线/虚线的线宽口径也就不必为悬停再开一个例外。
    c.check('is-match' not in html,
            '悬停不给相关边加粗（线宽只由"实线/虚线"这条作者语义决定）')
    c.check(re.search(r'\.ndg:hover \.shape\s*\{[^}]*stroke-width', html) is not None,
            '悬停节点**自己**的描边加粗留着：这是唯一不依赖动画的悬停反馈')
    c.check('data-ei' not in html,
            '边标签不再为悬停携带身份（标签不参与悬停，省掉一对"标签↔边"的配对）')
    # 回归闸门：聚焦必须**遍历每个 svg** 接线。单文件里内嵌多个子视图（D-52），
    # 抓某一个 id 只会给主图接线、子图点了没反应；而这些 <svg> 本来就没有 id 属性，
    # 用 getElementById 会拿到 null 后**静默退出**（第一版就是这样"悬停没反应"）。
    c.check("querySelectorAll('svg')" in html and "getElementById('flow')" not in html,
            '聚焦对每个 svg 分别接线（不是抓某一个 id —— 那些 svg 没有 id）')
    c.check(re.search(r'prefers-reduced-motion[^{]*\{[^}]*edge-flow[^}]*display:none', html) is not None,
            '「减少动态效果」时流光被关掉（底边仍在，信息一点不丢）')
    c.check('edge-flow' not in drawio, 'drawio 产物里没有流光（只影响 HTML 这一个产物）')


def _check_artifact_naming(c, tmp):
    c.section('产物命名：`<流程名>-flow.*`，流程名取目录名 / 表名（D-51）')
    # 产物是**发给别人看的**：`flow.html` 这种无名文件一多就成了"一堆 flow.html"，
    # 收件人只能靠文件夹名猜。命名规则要能被脚本算出来，所以只有一条：
    # 表名是约定名 `flowtable` → 名字在**目录**上（流程的身份本来就落在目录）；
    # 否则用表名。yaml / html / drawio / manifest 四份共用同一个前缀。
    nd = tmp / 'naming'
    shutil.rmtree(nd, ignore_errors=True)
    nd.mkdir(parents=True)

    def build_in(d, table='flowtable.md'):
        dd = nd / d
        dd.mkdir(parents=True, exist_ok=True)
        p = dd / table
        p.write_text(HEAD + ''.join(OK), encoding='utf-8')
        return p, run('build.py', p)

    # ① 约定名 → 用目录名
    p1, (rc1, o1) = build_in('报销审批')
    d1 = nd / '报销审批'
    c.check(rc1 == 0 and prod(d1, 'html').exists(), '表名是约定名 → 产物用**目录名**',
            '' if rc1 == 0 else o1.strip()[-90:])
    c.check(prod(d1, 'html').name == '报销审批-flow.html', '产物名 = 目录名 + -flow',
            prod(d1, 'html').name)
    c.check(not (d1 / 'flow.html').exists(), '不再产出无名的 flow.html（旧约定已废）')

    # ② 非约定名 → 用表名（目录只是容器时，名字在表上）
    p2, (rc2, o2) = build_in('方案A', '入职办理.md')
    d2 = nd / '方案A'
    c.check(rc2 == 0 and (d2 / '入职办理-flow.html').exists(), '表名不是约定名 → 产物用**表名**',
            '' if rc2 == 0 else o2.strip()[-90:])
    c.check('产物名按表名取' in o2, '非约定名时 build **说清楚**按什么取名（不让人猜）',
            next((l.strip() for l in o2.splitlines() if '产物名' in l), '（没提示）'))

    # ③ 五份产物共用一个前缀——契约若不带名，"哪份契约管哪张表"就靠目录猜了
    for ext in ('yaml', 'html', 'drawio', 'manifest.json', 'svg'):
        c.check(prod(d1, ext).exists() and prod(d2, ext, '入职办理.md').exists(),
                f'{ext} 也带流程名', '' if prod(d1, ext).exists() else f'缺 {prod(d1, ext).name}')

    # ④ 下钻链接必须指向**真的存在**的那份产物。
    #    早先"按后缀猜产物名"在这里翻过车（下钻入口一个都不出）——所以不比对字符串，
    #    直接把链接里的相对路径接在主图目录后面看文件在不在。
    root = nd / '主流程'
    (root / 'parts').mkdir(parents=True)
    sub = root / 'parts' / '结构校验.md'
    sub.write_text(HEAD + ''.join([row('一', 'R1', '接单', '开始', '甲方', '甲', '—', '→R2', '★'),
                                   row('二', 'R2', '完成', '结束', '双方', '双方共责', '—', '—')]),
                   encoding='utf-8')
    ft = root / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        OK[0],
        row('一', '02', '结构校验', '任务', '甲方', 'build.py', '—', '→03', '⊞ parts/结构校验.md；下钻'),
        row('二', '03', '交付', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc_s, _ = run('build.py', sub)
    rc_m, o_m = run('build.py', ft)
    h = (prod(root, 'html')).read_text(encoding='utf-8') if rc_m == 0 else ''
    links = re.findall(r'data-sub="([^"]+)"', h)
    c.check(rc_s == 0 and rc_m == 0 and len(links) == 1, '前置：子表与主表各自 build 通过',
            '' if rc_m == 0 else o_m.strip()[-90:])
    # D-52 之后下钻目标是"视图 key"（= 子表流程表的相对路径），不是产物路径。
    # 判据相应改成"这个 key 在本页真有对应视图"——比"文件在不在"更贴切：
    # 单文件里要紧的不再是磁盘上有没有那个文件，而是这一页能不能切过去。
    views = set(re.findall(r'data-view="([^"]*)"', h))
    c.check(bool(links) and set(links) <= views,
            '下钻链接指向**本页真实存在的视图**（不是按约定名拼出来的）',
            str(sorted(links)))
    # 链接里的名字 = 子表自己的名字，不是父表的、也不是约定的（html 已不再单独产出，看 yaml/drawio）
    c.check(links[:1] == ['parts/结构校验.md']
            and (root / 'parts' / '结构校验-flow.yaml').exists()
            and (root / 'parts' / '结构校验-flow.drawio').exists(),
            '子图产物按**子表自己的名字**取名（父子各叫各的）', str(links))

    # ⑤ sync --apply 写回的 yaml 必须是 build 会读的那一份。
    #    两处命名一旦分叉，症状是"手工调的布局在 apply 之后凭空消失"——极难自查。
    #    观测点选**跨列位移**（dx=460 = 一列宽）：只挪几十像素时行列表征不变，
    #    yaml 逐字节相同，这条断言会假绿——它要盯的是"几何有没有传过去"。
    before = (d2 / '入职办理-flow.yaml').read_text(encoding='utf-8')
    dw = d2 / '入职办理-flow.drawio'
    dw.write_text(_move_node(dw.read_text(encoding='utf-8'), '03', 460, 0), encoding='utf-8')
    rc5, o5 = run('sync.py', dw, p2, '--apply')
    c.check(rc5 == 0 and (d2 / '入职办理-flow.yaml').read_text(encoding='utf-8') != before,
            'sync --apply 把几何写进 **build 会读的那份 yaml**（命名分叉的回归闸门）',
            'rc=%d' % rc5)
    c.check(not (d2 / 'flow.yaml').exists() and not (d2 / 'flow.sync.yaml').exists(),
            'sync 侧不再落任何无名的 flow.yaml / flow.sync.yaml')
    c.check((d2 / '入职办理-flow.sync.yaml').exists(), '预览用的 yaml 也带流程名',
            '（缺 入职办理-flow.sync.yaml）')


def _check_single_file(c, tmp):
    c.section('单文件：子图内嵌为主 html 里的视图，下钻不跳页（D-52）')
    # 发给客户的是一个 flow.html——概念上类似 PPT：一个文件打开就能看完整个层级。
    # 于是"下钻"从"跳到子目录里另一个 html"变成"同一页里切视图"。
    # 钉住四件事：① 内嵌真的发生了；② 切视图而非跳页；③ 每层各记各的视窗位置；
    # ④ 没有子图时输出与从前逐字节相同（没用到这个功能就不该受影响）。
    sd = tmp / 'single'
    g = sd / 'main'
    p1 = g / 'parts' / 'l2'
    p2 = p1 / 'l3'
    p2.mkdir(parents=True, exist_ok=True)
    (p2 / 'leaf.md').write_text(HEAD + ''.join([
        row('一', 'Z1', '开始', '开始', '甲方', '受理员', '—', '→Z2', '★'),
        row('二', 'Z2', '到底了', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    (p1 / 'mid.md').write_text(HEAD + ''.join([
        row('一', 'M1', '开始', '开始', '甲方', '受理员', '—', '→M2', '★'),
        row('一', 'M2', '再下钻', '任务', '甲方', '受理员', '—', '→M3', '⊞ l3/leaf.md；还有一层'),
        row('二', 'M3', '停', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    ft = g / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('一', '02', '下钻', '任务', '甲方', '受理员', '—', '→03', '⊞ parts/l2/mid.md；两层深'),
        row('二', '03', '收尾', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    # 只 build **主表**：子表此前从未 build 过，它的 DSL 由主 build 自动补齐后内嵌。
    rc, out = run('build.py', ft)
    c.check(rc == 0, '只 build 主表就拿到完整层级（子表无需单独 build）',
            '' if rc == 0 else out.strip()[-90:])
    c.check('内嵌 2 张子图' in out,
            'build 说清楚内嵌了几张（不让人猜有没有嵌进去）', out.strip()[-60:])
    h = prod(g, 'html').read_text(encoding='utf-8')
    views = re.findall(r'data-view="([^"]*)"', h)
    c.check(len(views) == 3 and '__main__' in views,
            '孙层也内嵌进来（1 主视图 + 2 子视图）', str(views))
    c.check(h.count('<div class="chart-container"') == 3,
            '每个视图各有一块自己的画布（不是挤在一张里）',
            str(h.count('<div class="chart-container"')))
    c.check('class="view cur"' in h and '.view { display:none; }' in h,
            '默认只显示主视图（其余先藏起来，靠 JS 切）')
    # ② 下钻 = 切视图：`go(d.sub)`，不是 `location.href = d.sub`
    c.check('go(d.sub)' in h and 'location.href = d.sub' not in h,
            '下钻走**切视图**而不是跳页（单文件里跳页就是 404）')
    c.check('function showView(' in h and 'function go(' in h,
            '切视图与面包屑由脚本托管（每层各记各的轨迹）')
    # ③ 视窗位置按视图分层记：单文件里 location.pathname 不再区分层级
    c.check("SCROLL_KEY = 'fc-scroll:' + location.pathname + '#' + key" in h,
            '视窗位置**每层各记各的**（键带视图，不再共用一把）')
    # ④ 图例是跨层全集：子图里出现、主图没有的主体也要能查到颜色
    c.check('headmod.querySelector' in h, '切视图时标题跟着换（图例仍是主图那份全集）')
    # ⑤ 标题模块只回答"这是什么图 / 颜色是谁"：用法说明句（曾有一句「悬浮节点查看路由与描述」）
    #    常驻标题栏却说的是要动手才知道的事，而 drawio 版没有悬浮语义、那句话在那边不成立——
    #    两版图例因此逐字一致，只有一个真值（见 visual-spec §1「图例」）。
    c.check('class="hint"' not in h and '悬浮节点查看' not in h,
            'HTML：标题模块只有标题 + 主体色块行，没有任何用法说明')
    dw = prod(g, 'drawio').read_text(encoding='utf-8')
    c.check('悬浮节点查看' not in dw and 'title' in dw,
            'drawio：标题 cell 同样只有标题 + 色块行（两版图例逐字一致）')
    # ⑤ 同一张表被两个节点引用 → 只嵌一份（按表去重，不是按节点）
    d = sd / 'dup'
    (d / 'parts').mkdir(parents=True, exist_ok=True)
    (d / 'parts' / 'sub.md').write_text(HEAD + ''.join([
        row('一', 'S1', '开始', '开始', '甲方', '受理员', '—', '→S2', '★'),
        row('二', 'S2', '停', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    (d / 'flowtable.md').write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('一', '02', '第一次', '任务', '甲方', '受理员', '—', '→03', '⊞ parts/sub.md；同一个'),
        row('一', '03', '第二次', '任务', '甲方', '受理员', '—', '→04', '⊞ parts/sub.md；还是它'),
        row('二', '04', '收尾', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc2, out2 = run('build.py', d / 'flowtable.md')
    hd = prod(d, 'html').read_text(encoding='utf-8') if rc2 == 0 else ''
    c.check(rc2 == 0 and hd.count('data-view="') == 2 and hd.count('data-sub="') == 2,
            '同一张子表被两个节点引用：只内嵌**一份**，两个入口都指向它',
            '视图 %d 个 / 入口 %d 个' % (hd.count('data-view="'), hd.count('data-sub="')))
    # ⑥ 没有子图 → 单视图，输出里不出现任何多视图的痕迹
    dn = sd / 'none'
    dn.mkdir(parents=True, exist_ok=True)
    (dn / 'flowtable.md').write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('二', '02', '停', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc3, _ = run('build.py', dn / 'flowtable.md')
    hn = prod(dn, 'html').read_text(encoding='utf-8') if rc3 == 0 else ''
    c.check(rc3 == 0 and 'data-view=' not in hn and 'class="view' not in hn
            and 'function go(' not in hn,
            '没有子图时：单视图，输出里不出现任何多视图的痕迹')
    # ⑦ 自指（子表又指回自己）不能把文件撑爆：已经有这个视图了就复用，不再嵌一份。
    #    真环（子表指回主表）在语法层就被 `⊞` 的越界规则挡掉了（`../` 一律拒绝），
    #    所以能写出来的只有自指与菱形引用——两种都得靠"按表去重"兜住。
    dc = sd / 'cycle'
    (dc / 'parts').mkdir(parents=True, exist_ok=True)
    (dc / 'parts' / 'sub.md').write_text(HEAD + ''.join([
        row('一', 'S1', '开始', '开始', '甲方', '受理员', '—', '→S2', '★'),
        row('一', 'S2', '自指', '任务', '甲方', '受理员', '—', '→S3', '⊞ sub.md；指回自己'),
        row('二', 'S3', '停', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    (dc / 'flowtable.md').write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('一', '02', '下钻', '任务', '甲方', '受理员', '—', '→03', '⊞ parts/sub.md；一层'),
        row('二', '03', '收尾', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc4, out4 = run('build.py', dc / 'flowtable.md')
    hc = prod(dc, 'html').read_text(encoding='utf-8') if rc4 == 0 else ''
    c.check(rc4 == 0 and hc.count('data-view="') == 2,
            '子表指回自己：复用已有视图，不重复内嵌（防环）',
            '视图 %d 个' % hc.count('data-view="'))
    # ⑧ drawio 仍每表一份（不合并），主 drawio 只铺直接子页
    c.check(prod(dc, 'drawio').exists(), 'drawio 仍按每表一份产出（不合并进 html）')
    c.check(not (dc / 'parts' / 'sub-flow.drawio').exists(),
            '内嵌不代劳：子表的 drawio 仍要 build 那张表才有')


def _check_node_types(c, tmp):
    """D-74：类型只有四种、形状只有三个，**形状是类型的唯一载体**（图里不写类型属性）。

    钉两件事：① 四种类型各画各的形状（矩形 / 菱形 / 胶囊）；② 形状读回来还是同一个类型——
    后者是"表 → 图 → 表 互为逆运算"的实证，也是"图里不需要隐藏属性"的前提。
    """
    c.section('节点类型：四种类型 ←→ 三个形状（形状单射，图里不写类型）')
    d = tmp / 'types'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        row('一', '01', '开始', '开始', '甲方', '受理员', '—', '→02'),
        row('一', '02', '齐全？', '判断', '甲方', '受理员', '—', '是→03 ｜ 否→回 01'),
        row('二', '03', '办结', '任务', '乙方', '工程师', '—', '→04'),
        row('三', '04', '结束', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc, out = run('build.py', ft)
    c.check(rc == 0, '前置：四种类型的表 build 通过', out.strip()[-90:])
    dw = prod(d, 'drawio').read_text(encoding='utf-8')
    c.check('rounded=1;arcSize=6' in dw and 'rhombus;' in dw and 'rounded=1;arcSize=50' in dw,
            '三种形状各就各位（矩形=任务 / 菱形=判断 / 胶囊=起止）')
    arts = {k: prod(d, k).read_text(encoding='utf-8') for k in ('html', 'drawio', 'svg')}
    # 圆角口径以 drawio 为准（D-86）：`arcSize` 是**占短边的百分比**。drawio 那边原样写 6，
    # html/svg 必须按 `min(w,h)×6/100` 换算成像素——此前两边把 6 直接当像素写进 `rx`，
    # 同一形状三份产物圆角差一倍多（6px vs 3.6px），而没有任何仪器量过它。
    _arc = int(re.search(r'arc:\s*(\d+)', (SKILL / 'scripts' / 'dictionary.yaml')
                         .read_text(encoding='utf-8')).group(1))
    _bad = []
    for art in ('html', 'svg'):
        for m in re.finditer(r'<rect class="shape" x="-?[\d.]+" y="-?[\d.]+" '
                             r'width="([\d.]+)" height="([\d.]+)" rx="([\d.]+)"', arts[art]):
            w_, h_, rx_ = (float(v) for v in m.groups())
            if abs(rx_ - h_ / 2) < 0.01:
                continue                      # 胶囊（起止）：圆角是**半圆**，按定义取 h/2（D-74）
            want = round(min(w_, h_) * _arc / 100.0, 3)
            if abs(rx_ - want) > 0.01:
                _bad.append(f'{art} {w_:g}×{h_:g} rx={rx_:g} ≠ {want:g}')
    c.check(not _bad, f'html/svg 的圆角 = 短边 × arcSize% ({_arc}%)，与 drawio 同口径',
            '；'.join(_bad[:3]))
    c.check(not any('ellipse' in t for t in arts.values()),
            '三份产物里都没有椭圆（起止改画胶囊）',
            ('仍在: ' + '、'.join(k for k, t in arts.items() if 'ellipse' in t)) if
            any('ellipse' in t for t in arts.values()) else '0 处')
    rc2, out2 = run('xml_reader.py', prod(d, 'drawio'))
    tags = ' | '.join(l for l in out2.splitlines() if l.startswith('['))
    c.check(rc2 == 0 and all(t in out2 for t in ('[开始] 01', '[判断] 02', '[任务] 03', '[结束] 04')),
            '形状读回类型：四种类型一个不错（表 ⇄ 图 互为逆运算）', tags)


def _check_drawio_weight(c, tmp):
    c.section('drawio 的权重：改几何只影响 html，改走向才动流程表')
    # drawio 的定位是**流程表和 html 的配套产物**，不是第二份事实源。它的权重随用户动了什么而变：
    #   只挪节点/线条（几何） → 只回流到 flow.yaml → 只影响两份产物的布局，流程表一个字都不动；
    #   改了节点走向（拓扑） → 那是在改事实源，必须能回写流程表，且冲突时要拦下让人裁决。
    # 这组用例钉的是这条分界——两头都别越界：几何改动不许偷偷改表，走向改动不许被静默吞掉。
    d = tmp / 'weight'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    ft.write_text(HEAD + ''.join([
        row('一', '01', '收到申请', '开始', '甲方', '受理员', '—', '→02', '★'),
        row('一', '02', '资料齐全？', '判断', '甲方', '受理员', '—', '齐全→03 ｜ 不齐→回 01', '★'),
        row('二', '03', '现场核验', '任务', '乙方', '工程师', '3个工作日', '→04'),
        row('三', '04', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8',
        newline='\n')          # 夹具表也钉 LF（D-116 那条"写的那一侧"对夹具同样成立）
    orig = ft.read_text(encoding='utf-8')
    rc0, out0 = run('build.py', ft)
    c.check(rc0 == 0, '前置：主表 build 通过', out0.strip()[-90:])

    dw = prod(d, 'drawio')
    html_before = (prod(d, 'html')).read_text(encoding='utf-8')
    # 挪得**足够远**：横 200 > 列聚类阈值（0.9×宽中位数 = 144）、纵 150 > 行阈值（0.6×高中位数 = 36），
    # 于是它真的换了一列一行。**为什么不能只挪一点点**（原来挪 60×40）：像素不是终值——挪不动聚类结果时，
    # 唯一的变化是"列均值平移"，而那点平移被画布居中（`table_to_dsl._center_canvas`）归一化掉了（D-77）；
    # 这条断言要钉的是"**相对**几何改动有出口"，不是"任何像素位移都得改产物"。
    dw.write_text(_move_node(dw.read_text(encoding='utf-8'), '03', 200, 150), encoding='utf-8')

    # ① 只挪位置 → 流程表零改动（"改几何不动事实源"是这条分界的一半）
    rc1, out1 = run('sync.py', dw, ft)
    c.check(rc1 == 0 and '逐字节一致' in out1,
            '只挪节点位置：流程表**零改动**（几何不回写事实源）', 'rc=%d' % rc1)
    # ② --apply 是最凶的一步（会覆盖原表），几何改动走它之后表也必须还是原文
    rc2, _ = run('sync.py', dw, ft, '--apply')
    c.check(rc2 == 0 and ft.read_text(encoding='utf-8') == orig,
            '只挪位置 + --apply：流程表仍逐字节是原文（覆盖不越界）', 'rc=%d' % rc2)
    # ③ 几何得有出口——否则"只影响 html"就成了"改了白改"。
    #    注意不能只 `build.py`：它默认复用 flow.yaml 的几何（保护手工微调），
    #    几何要经 sync 回流到 yaml 才会进产物——这正是 drawio 参与布局的正确路径。
    c.check((prod(d, 'html')).read_text(encoding='utf-8') != html_before,
            '只挪位置（换行换列）：html 布局**确实跟着变**了（几何改动有出口，不是被吞掉）')

    # ④ 反向：在 drawio 里改**框内文字**（名称）→ 流程表跟着改。名称与走向是图这一面**真的能改**
    #    的两样（图里只有名称、形状、连线，别的都没有，D-73/D-74）。
    d2 = d / 'name'
    d2.mkdir(parents=True, exist_ok=True)
    ft2 = d2 / 'flowtable.md'
    ft2.write_text(orig, encoding='utf-8')
    run('build.py', ft2)
    dw2 = prod(d2, 'drawio')
    txt2 = dw2.read_text(encoding='utf-8')
    assert '现场核验' in txt2, '基准样例已变，请同步更新本用例'
    dw2.write_text(txt2.replace('现场核验', '现场核查'), encoding='utf-8')
    rc4, out4 = run('sync.py', dw2, ft2, '--apply')
    c.check(rc4 == 0 and '现场核查' in ft2.read_text(encoding='utf-8'),
            'drawio 里改框内文字：流程表跟着改（名称以图为准）', 'rc=%d' % rc4)


def _check_source_freshness(c, tmp):
    c.section('表被直改：指纹当场报出，--apply 拦下（保手工改动）')
    # 补的是缺的那一环：手工改表而没重跑 build 时 yaml 一个字没动 ⇒「契约已过期」不响，
    # 产物与契约逐项一致 ⇒ 八项门禁全绿，盘上却是一份落后于事实源的图。
    d, ft, rc0, out0 = _wb_project(tmp, 'fresh')
    if not c.check(rc0 == 0, '前置：自造夹具 build 通过', out0.strip()[-90:]):
        return

    # ① 没动过：表与渲染时同版
    rc1, out1 = run('table_to_dsl.py', '--fresh', ft)
    c.check(rc1 == 0 and '未变' in out1, '未动过：--fresh 报"未变"（rc 0）', f'rc={rc1}')

    # ② 手工改一处**语义**：只改名、不碰走向 ⇒ 走向冲突门禁不会响，正好单验这一关
    assert _set_cell(ft, '03', 3, ' 核验复核 ')
    rc2, out2 = run('table_to_dsl.py', '--fresh', ft)
    c.check(rc2 == 1 and '改过' in out2, '手工改过：--fresh 当场报出（rc 1）', f'rc={rc2}')
    c.check('走向冲突' not in out2, '这一改不是走向冲突（拦它的只可能是新鲜度这一关）')

    # ③ --apply 必须拦下：回灌是按图里的节点集合重建表格行的，手工改动会丢
    rc3, out3 = run('sync.py', prod(d, 'drawio'), ft, '--apply')
    c.check(rc3 == 1 and '覆盖被拦截' in out3, '--apply 被拦下（rc 1）', f'rc={rc3}')
    c.check('核验复核' in ft.read_text(encoding='utf-8'),
            '被拦下后手工改的名字仍在表里（没被图里的旧值覆盖回去）')
    rc4, _ = run('sync.py', prod(d, 'drawio'), ft)
    c.check(rc4 == 0, '预览照旧：拦的只是 --apply，不是看差异', f'rc={rc4}')

    # ④ 正路：表改完重跑 build → 指纹跟上，手工改动进产物
    rc5, _ = run('build.py', ft)
    rc6, _ = run('table_to_dsl.py', '--fresh', ft)
    c.check(rc5 == 0 and rc6 == 0, '重跑 build 后指纹跟上（rc 0）——这才是直改之后的走法',
            f'rc={rc5}/{rc6}')

    # ⑤ 没有基线（首轮，或契约被删）：判不出就直说，不假装"未变"
    mf = next(d.glob('*-flow.manifest.json'))
    mf.unlink()
    rc7, out7 = run('table_to_dsl.py', '--fresh', ft)
    c.check(rc7 == 1 and '无从判断' in out7, '没有基线：直说"无从判断"（rc 1），不谎报未变',
            f'rc={rc7}')


def _check_index_and_views(c, tmp):
    """G47 / G50：**同一张子表被多处引用**时，计数与警告都不许重复；派生物不许被报成孤儿表。"""
    c.section('子表被多处引用：内嵌计数与"缺席/待备"清单不重复（G47）')
    d = tmp / 'views'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    ft = d / 'flowtable.md'
    # 两个节点都指向**同一张缺席的子表**：`collect_views` 原先在 absent 这条路上完全没有去重，
    # 于是"N 张缺席"按引用次数虚高（读不动的表还会被第二次 append 进 views）。
    ft.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '子流程甲', '任务', '甲方', '甲', '—', '→03', '⊞ parts/缺/flowtable.md'),
        row('核验', '03', '子流程乙', '任务', '乙方', '乙', '—', '→04', '⊞ parts/缺/flowtable.md'),
        OK[3]]), encoding='utf-8')
    run('table_to_dsl.py', '--write', ft, '-o', prod(d, 'yaml'))
    import render_html as _rh
    got = _rh.collect_views(prod(d, 'yaml'))
    c.check(len(got['absent']) == 1,
            'G47 同一张缺席子表被两个节点引用 ⇒ 只记一次（原先按引用次数重复计入）',
            f"absent={len(got['absent'])} · pending={len(got['pending'])}")
    c.check(len(got['views']) == 0, 'G47 缺席的子表不进 views（下钻入口不许点了没反应）',
            f"views={len(got['views'])}")

    c.section('派生物不许被报成孤儿表（G50）')
    # `layer_index --write` 支持给**任意**表写索引（含子表）；原先 `generated` 只豁免主表那一个
    # 名字 ⇒ 给子表写过索引后再 build，那份索引被报成"孤儿表"——工具让写的它自己骂。
    d2 = tmp / 'orphanidx'
    shutil.rmtree(d2, ignore_errors=True)
    (d2 / 'parts' / '甲').mkdir(parents=True)
    ft2 = d2 / 'flowtable.md'
    ft2.write_text(HEAD + ''.join([
        OK[0],
        row('受理', '02', '子流程甲', '任务', '甲方', '甲', '—', '→04', '⊞ parts/甲/flowtable.md'),
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    sub = d2 / 'parts' / '甲' / 'flowtable.md'
    # 子表也要**结构完整**（`OK[0]` 指向 02，而子表里没有 02 ⇒ H3 会拦下——G40 修好后这不难踩到）
    sub.write_text(HEAD + ''.join([
        row('受理', '01', '收到申请', '开始', '甲方', '受理员', '—', '→04'),
        row('归档', '04', '归档', '结束', '双方', '双方共责', '—', '—')]), encoding='utf-8')
    rc0, out0 = run('build.py', ft2)
    if not c.check(rc0 == 0, '前置：带子表的稿子可 build', out0.strip()[-90:] if rc0 else ''):
        return
    (d2 / 'parts' / '甲' / '甲-index.md').write_text('# 子表索引\n', encoding='utf-8')
    rc1, out1 = run('build.py', ft2)
    c.check(rc1 == 0 and '孤儿表' not in out1,
            'G50 给子表写过的 `*-index.md`（派生物）不被报成孤儿表',
            [l for l in out1.splitlines() if '孤儿' in l][:1] or f'rc={rc1}')


def run_face(tmp):
    c = Case('面② 门禁拦截')
    tmp.mkdir(parents=True, exist_ok=True)
    _structure_bad_cases(c, tmp)
    _check_header_rules(c, tmp)
    _check_layering(c, tmp)
    _check_false_positives(c, tmp)
    _check_quality_gates(c, tmp)
    _check_overlap_predicate(c)
    _check_cli_failure_paths(c, tmp)
    _check_swimlane_slots(c, tmp)
    _check_swimlane_slot_spread(c, tmp)
    _check_swimlane_backedge(c, tmp)
    _check_swimlane_slot_align(c, tmp)
    _check_lane_cross_pass(c, tmp)
    _check_swimlane_left_corridor(c, tmp)
    _check_min_leg(c)
    _check_lanes_coverage(c, tmp)
    _check_lane_expectation(c, tmp)
    _check_build_rollback(c, tmp)
    _check_renderer_registry(c, tmp)
    _check_registry_scales(c, tmp)
    _check_degrade(c, tmp)
    _check_flow_parallel_branches(c, tmp)
    _check_clean_l_mirror(c, tmp)
    _check_stagger_slots(c, tmp)
    _check_writeback_semantics(c, tmp)
    _check_writeback_next_conflict(c, tmp)
    _check_apply_guard(c, tmp)
    _check_writeback_selfcheck(c, tmp)
    _check_html_robustness(c, tmp)
    _check_writeback_labels(c, tmp)
    _check_writeback_pseudo_diff(c, tmp)
    _check_label_overlap(c)
    _check_geometry_reuse_hint(c, tmp)
    _check_ai_pending_marks(c, tmp)
    _check_clarify_phase(c, tmp)
    _check_subflow_drill(c, tmp)
    _check_edge_flow(c, tmp)
    _check_artifact_naming(c, tmp)
    _check_single_file(c, tmp)
    _check_color_contract(c, tmp)
    _check_node_types(c, tmp)
    _check_drawio_weight(c, tmp)
    _check_source_freshness(c, tmp)
    _check_manifest_audit(c, tmp)
    _check_external_reader(c, tmp)
    _check_edge_merge_gate(c, tmp)
    _check_artifact_gate(c, tmp)
    _check_init_conflict(c, tmp)
    _check_escape(c, tmp)
    _check_degradation_trace(c, tmp)
    _check_xml_diff(c, tmp)
    _check_index_and_views(c, tmp)
    return c


if __name__ == '__main__':
    sys.exit(0 if run_face(SKILL / '.verify_tmp').summary() else 1)


