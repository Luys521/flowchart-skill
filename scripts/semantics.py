# -*- coding: utf-8 -*-
"""semantics.py — 文本语义层：路由编号→名称、多行悬浮文本、节点显示行。

独立于几何与路由，只处理"写什么字"。依赖 Model 的节点索引。
"""
import re
from pathlib import Path

PENDING_MARK = '⚠'

# 「下个节点」列里多个出口之间的分隔符。为什么是 `｜` 而不是 `<br>` / `；` 见 DECISIONS.md D-04。
BRANCH_SEP = '｜'


class Finding(str):
    """带结构化定位的报错/提示（见 D-55）。

    本体是 **str 子类**：打印、join、startswith、gates 的 250 条输出断言全部零改动；
    另挂 `subject`（节点/边 id 等定位）与 `fix`（建议修法）两个属性，
    `--json` 回执时透出——AI 修复循环直接消费字段，不必正则反解中文句子
    （借鉴 byai-diagram-designer 的 finding 结构）。
    """

    def __new__(cls, msg, subject=None, fix=None):
        s = super().__new__(cls, msg)
        s.subject = subject
        s.fix = fix
        return s


def findings_receipt(items):
    """报错/提示列表 → 结构化回执（纯 dict 列表，供 --json 输出）。"""
    return [{'message': str(x),
             **({'subject': x.subject} if getattr(x, 'subject', None) else {}),
             **({'fix': x.fix} if getattr(x, 'fix', None) else {})}
            for x in items]

# 待裁决标记：`⚠?`（⚠ 后紧跟 `?`）。与 `⚠` 的区别**不是程度，是收敛条件**（见 D-46）：
# `⚠`  = AI 能从材料/条款/行业惯例中**单独找到依据**的推断 → 无需收敛，图上留痕即可；
# `⚠?` = AI **推不出、必须业务方拍板**的决策 → 必须问过一次并得到回答才算收敛。
# 为什么用后缀而不是换个新字符：⚠ 在仓库里有 60+ 处（脚本 + 文档），换字符要全量迁移；
# 后缀是最小改动面，且 `⚠?` 读起来就是"这里有个待回答的问题"。
VERDICT_SUFFIX = '?'

# 子流程引用标记：`⊞ 路径`（见 D-47）。写在「节点描述」里，声明"这个节点内部还有一张流程表"。
# 为什么用描述内标记而不是新增一列：新增列要动列结构 / parse_table / 全部校验 / 全部模板，
# 而描述列**已有** ★(关键点) / ⚠(推断) / ⚠?(待裁决) 三类标记，加一类是同类的最小改动面。
# 为什么是 ⊞ 而不是别的：它在视觉上就是个"方框套方框"（嵌套），且不在正文里自然出现。
SUBFLOW_MARK = '⊞'
# 子表路径的终止符：分号（中英）、行尾、或下一个 ⊞（一个节点至多声明一个子表）。
SUBFLOW_STOP = '；;'

# drawio 侧的**机器标记**：都写在 cell 的 `style` 里（drawio 忽略未知键、原样保留）。
# 三处字符串原先各写两遍（渲染器写字面量、回读器另定常量），改一处必漏一处；家放在这里（D-85）。
NATIVE_MARK = 'flowchartSkillNative=1'   # 本 SKILL 的渲染器产出的节点（回读据此判"自产 / 外部"）
BG_MARK = 'flowchartSkillBg=1'           # 泳道背景带（部门列 / 阶段带）：是背景，不是节点
SUB_MARK = 'flowchartSkillSub=1'         # 子流程内衬线：是装饰，不是节点

# 箭头（三份产物同一枚，见 D-89）：**边长（px）**。html 与 svg 用 SVG marker 画、drawio 用
# `endArrow=block` 画，两边都由这两个数推出——此前 drawio 写 `blockThin`（导出实测 8×5.3px）、
# marker 写 14×14，同一张图两份产物的箭头差 2.6 倍，drawio 那份小到"看不出有箭头"。
ARROW_LEN = 10
#: drawio 的 `endSize`。block 三角形实测为 `endSize + 2` 见方，故 = 边长 - 2。
ARROW_END_SIZE = ARROW_LEN - 2
#: 箭头颜色**不在这里**：它就是该极性边的 `stroke`（`dictionary.yaml` 的 `edges.<极性>.color`），
#: marker 按极性逐个生成（`arrow_markers`）——写死两个色值等于把边色陈述第二遍。

# 数值字典的**文件名**：六个模块原先各写一遍（`Path(__file__).with_name(DICT_NAME)`）。
# 为什么这名字必须只有一个家（D-115）：改名时漏掉一处**不会报错**——那几处 `load_thresholds`
# 都"读不到就用内置默认、不报错"，于是漏掉的那个模块**静默退回兜底值**，而账本字节照旧。
# 家放在这里，与 `ARROW_*` 同一类：跨模块约定常量。
DICT_NAME = 'dictionary.yaml'

# 内嵌子视图（点 `⊞` 下钻那张）在节点框里的内缩量（px）。三份渲染器原先各写一遍 ⇒ 改一处会让
# 同一张表在 html / drawio / svg 里长得不一样，而**没有任何门禁比这个数**（D-115）。
SUB_INSET = 2.0

# 中英类型对照（唯一事实源）：流程表中文类型 ↔ DSL 英文类型。
# 此前 TYPE_MAP / TYPE_ZH / DICT_ZH 在 table_to_dsl / writeback / xml_reader 各抄一份，新增类型要改三处。
# **只有四种**（见 flowtable-spec §2《类型登记表》）：形状是类型的可见形式，一个不多一个不少。
# 「子流程」不再当别名：那个词在本 SKILL 里只指 `⊞` 声明的可下钻子表（一名一物）。
TYPE_ZH_EN = {'开始': 'start', '结束': 'end', '任务': 'task', '判断': 'decision'}
TYPE_EN_ZH = {'start': '开始', 'end': '结束', 'task': '任务', 'decision': '判断'}


def split_table_row(line):
    r"""markdown 表格行 → 单元格列表。

    `\|` 是单元格内的转义竖线（GFM 表格规范）——先护起来再切列，否则描述里的 `A\|B`
    会被切断列：落在末列被 cells[:9] 静默截断，落在前列则整行列错位。
    """
    s = line.strip().strip('|')
    parts = s.replace('\\|', '\x00').split('|')
    return [c.replace('\x00', '|').strip() for c in parts]


def arrow_markers(cfg):
    """箭头 marker 串（SVG 的 `<defs>` 内容）——html 与 svg 两份产物共用一份（见 D-89）。

    **按极性生成、不按线型**：`ar-main` / `ar-negative` 各带自己的边色。早先按"实线/虚线"写死
    `#666666` / `#adb5bd` 两个色值，那等于把 `dictionary.yaml` 的边色抄了第二遍——用户改字典的边色，
    线换了色、箭头还是灰的（而且"虚线"与"负向"是两件事，判据错配时连这份重复都遮不住）。

    `refX` 取**箭头尖端**：针尖正好落在端口上（旧值 8 让针尖扎进框内 2.8px、drawio 那边则缩在框外
    2.2px，两头都不"对接"）。`markerUnits="userSpaceOnUse"` 不能省：默认按 `strokeWidth` 缩放，
    线宽一变箭头就跟着变（D-89 的 2.6 倍差正是这么来的）。
    """
    out = []
    for pol, ed in (cfg.get('edges') or {}).items():
        half = ARROW_LEN / 2
        out.append(
            f'<marker id="ar-{pol}" viewBox="0 0 {ARROW_LEN} {ARROW_LEN}" refX="{ARROW_LEN:g}" '
            f'refY="{half:g}" markerWidth="{ARROW_LEN:g}" markerHeight="{ARROW_LEN:g}" '
            f'markerUnits="userSpaceOnUse" orient="auto">'
            f'<path d="M0,0L{ARROW_LEN:g},{half:g}L0,{ARROW_LEN:g}z" fill="{ed["color"]}"/></marker>')
    return ''.join(out)



def split_branches(s):
    """「下个节点」列 → 出口文本列表（只认 `｜`，兼容 `<br>` 与真换行——见 flowtable-spec §2）。"""
    pat = r'\s*' + re.escape(BRANCH_SEP) + r'\s*|<br\s*/?>|\n'
    return [p.strip() for p in re.split(pat, s or '') if p.strip()]


def parse_span(spec, what='范围', unit='条数'):
    """`'40-60'` / `'7'` → `(40, 60)` / `(7, 7)`；空 → `None`；**写歪或反区间抛 `ValueError`**。

    **这段语法原先在四处各写一遍**（`parse._span` / `parse_ooxml._span` / `parse_pdf._page_span` /
    `query.parse_range` 的数值分支，D-122），而 `parse._span` 的文档串里还留着事故记录：
    "与 `query.py` 的同一句声明保持一致……（**审计实测两处曾相反**）"。口径靠人同步，
    结局就是那样——所以语法与它的两条校验（起点 ≥1、上界 ≥ 下界）只有这一份。

    **写歪了不许猜**：范围写歪还照跑，等于把"我要第 3 条"执行成"全都要"，而下游以为收窄生效了
    （与 `query.py` 的同一句声明一致：**两边都抛错、都由调用方退 2**）。

    `what` / `unit` 只影响**报错文案**（`--pages 40-60：上界小于下界` / `页码是 1 起`）——
    文案要能让人对上自己敲的那个参数，所以调用方把参数名传进来。
    """
    if not str(spec or '').strip():
        return None
    m = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', str(spec))
    if not m:
        raise ValueError(f'{what}写法不认：{spec!r}（应为 N 或 A-B，1 起，闭区间）')
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    if a < 1:
        raise ValueError(f'{what} {spec!r}：起点要 ≥1（{unit}是 1 起）')
    if b < a:
        raise ValueError(f'{what} {spec!r}：上界小于下界')
    return (a, b)


def has_ambiguous_sep(s):
    """「下个节点」列里，把分号当成了分隔符用（`通过→05；不通过→06`）。

    判据必须是**分号后还跟着 `标签→目标` 的形状**，而不是"有没有分号"——后者会误伤注解里的分号。
    """
    return bool(re.search(r'[；;][^；;]*?(?:→|->)', s or ''))


def pending_kind(desc):
    """节点描述的标记 → None / 'inferred' / 'verdict'（判据与收敛条件见 D-46、flowtable-spec §2）。

    两类都是"AI 没底"，渲染时一视同仁画虚线；分开是为了**收敛条件不同**——
    `inferred` 已经有依据，不必打断用户；`verdict` 必须问，`clarify.py` 靠它算 frontier。

    **`⚠` 与 `?` 之间允许空格/换行**（`⚠ ?`、`⚠?`、`⚠??` 一律判 verdict）。这不是宽松，
    是单向保险：把该问的误判成不用问，未决项会静默混进交付的图里；把不用问的误判成该问，
    只是多问一句。两个方向的代价差一个数量级，所以**一律倒向"算 verdict"**。
    只认半角 `?`（全角 `？` 判 inferred）——理由见 flowtable-spec §2：ASCII `?` 在
    markdown 与终端里不会和中文标点混淆。
    """
    s = str(desc or '').lstrip()
    if not s.startswith(PENDING_MARK):
        return None
    rest = s[len(PENDING_MARK):].lstrip()
    return 'verdict' if rest.startswith(VERDICT_SUFFIX) else 'inferred'


def pending_style(cfg, desc):
    """节点描述 → 留痕外观 `{'stroke', 'dash', 'note'}`；不是 `⚠` 开头则返回 `{}`。

    两档取值都在 dictionary 的 `pending:` 段：基档给 `⚠`，`verdict:` 子档给 `⚠?`。
    **两档必须画得不一样**——`⚠` 是"AI 有依据，你不必管"，`⚠?` 是"必须你拍板"；画成同一款，
    图上就分不出哪几处要人拍板，而这正是 D-46 拆标记的动机。dash 也分开是有意的：
    只靠颜色区分的话，色弱的人分不出来。
    """
    kind = pending_kind(desc)
    if not kind:
        return {}
    base = cfg.get('pending') or {}
    sub = base.get(kind)
    sub = sub if isinstance(sub, dict) else {}
    return {'stroke': sub.get('stroke') or base.get('stroke'),
            'dash': sub.get('dash') or ('6 4' if base.get('dashed') else ''),
            'note': sub.get('note') or base.get('note') or ''}


def _normalize_subflow_path(path):
    """子表相对路径规范化：越界（绝对路径 / 逃出目录）一律返回 None。"""
    p = path.replace('\\', '/')
    if p.startswith('/') or re.match(r'^[a-zA-Z]:', p):
        return None
    parts = []
    for seg in p.split('/'):
        if seg in ('', '.'):
            continue
        if seg == '..':
            if not parts:
                return None        # 已经退到根之上 → 越界
            parts.pop()
        else:
            parts.append(seg)
    if not parts:
        return None
    return '/'.join(parts)


def subflow_ref(desc):
    """节点描述 → 子表相对路径（无则 None）。见 D-47。

    语法：`⊞ parts/渲染.md`。路径**以空白或 `；`/`;` 或行尾结束**——
    不枚举"下一个标记是什么"，而是规定**路径本身不含空白**（真实路径也确实不含）。
    这样 `⊞ parts/x.md ⚠ 推断` 会正确停在 `parts/x.md`，不必把 ⚠ / ★ 等标记
    一个个列进终止符表（列了就会漏，漏了就把后面的说明文字吃进路径）。
    路径**相对该流程表所在目录**（主表在 output/<名称>/，故写 `parts/渲染.md`）。

    **越界一律拒绝**（返回 None）：子表路径不得逃出流程表所在目录。
    宁可少一个"可下钻"入口，也不能让一个 `⊞ ../../etc/passwd` 变成可点的链接——
    这是给用户点的东西，路径必须钉死在项目目录内。
    绝对路径（Windows 盘符 / POSIX 根）同样拒绝：它必然越界。
    """
    s = str(desc or '')
    i = s.find(SUBFLOW_MARK)
    if i < 0:
        return None
    # 先吃掉 `⊞` 与路径之间的空白——`⊞ parts/x.md` 里的那个空格不是终止符。
    rest = s[i + len(SUBFLOW_MARK):].lstrip()
    # 再截到第一个空白或分号（路径本身不含空白；分号是显式终止符）
    cut = len(rest)
    for m in re.finditer(r'[\s' + re.escape(SUBFLOW_STOP) + ']', rest):
        cut = m.start()
        break
    path = rest[:cut].strip().strip('`').strip()
    if not path:
        return None
    return _normalize_subflow_path(path)


def subflow_target(desc):
    """节点描述 → **子表流程表**的相对路径（无则 None）。见 D-47 / D-51。

    返回的是**流程表**（`parts/渲染.md`），不是产物。产物名带流程名之后（D-51），
    "流程表 → 产物"的换算要知道那张表叫什么、在哪个目录（约定名还得退到目录名）——
    那是文件层的事，由 `artifact.artifact_stem` 完成。纯文本层不该、也无法猜：
    早先这里写死拼 `flow.html`，实测"按后缀猜产物名"永远猜不中（下钻入口一个都不出）。

    `.md` 后缀是补出来的：`⊞ parts/渲染` 与 `⊞ parts/渲染.md` 指同一张表，
    调用方（判断产物是否存在、反查父表）都按带后缀比，统一在这里补齐。
    """
    ref = subflow_ref(desc)
    if not ref:
        return None
    return str(Path(ref).with_suffix('.md')).replace('\\', '/')


def is_pending(desc):
    """节点描述**以 ⚠ 开头**（含 `⚠?`）= 留痕节点，渲染时必须画虚线（约定见 flowtable-spec §2，定位见 D-02）。

    **语义刻意保持"任何 ⚠ 前缀都算"**：manifest 计数与两个渲染器都调它，
    把 `⚠?` 排除在外会让待裁决节点在图上失去虚线——那恰恰是最该被看见的一类。
    需要细分时用 `pending_kind`。
    """
    return pending_kind(desc) is not None


def text_width(s, full, half):
    """文本宽度估算：CJK/带圈数字按全角宽，其余按半角宽（SVG 无自动排版，必须自己推进 x）。"""
    return sum(full if (ord(c) >= 0x2E80 or 0x2460 <= ord(c) <= 0x24FF) else half
               for c in s)


class Syntax:
    def __init__(self, model):
        self.M = model

    def route_names(self, s):
        """路由文本：节点编号→节点名（仅替换 →/回 引导的编号，避开 30日、10MW 等）"""
        nodes = self.M.nodes
        ids = sorted(nodes, key=len, reverse=True)
        pat = re.compile(r'(→|回\s)(' + '|'.join(map(re.escape, ids)) + r')')
        return pat.sub(lambda m: m.group(1) + str(nodes[m.group(2)]['name']), s)

    def route_text(self, nid):
        """路由文本：编号→名称，多个出口换成真正的换行。

        悬浮框只认 `\n`，所以 `｜` 必须归一再拼——否则会当字面文本显示、多个出口挤成一行。
        分隔符只经 `split_branches` 一处定义。
        """
        rn = self.route_names(self.M.nodes[nid].get('route', '—'))
        return '\n'.join(split_branches(rn))

    def node_lines(self, nid):
        """节点显示行：判断节点只放名称；其余 名称行+执行者+行动所需时间(可选)"""
        n = self.M.nodes[nid]
        if n['type'] == 'decision':
            return [('name', n['lines'][0])]
        out = [('name', t) for t in n['lines']]
        out.append(('executor', n['executor']))
        if n.get('time'):
            out.append(('time', n['time']))
        return out