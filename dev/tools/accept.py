# -*- coding: utf-8 -*-
r"""accept.py — **验收：一条命令跑完十二道门，只给一个结论**。

**为什么**：用户只做最终环节的验收。前面四件仪器各答一个问题、各有一条命令，收口时却要人把
五六条命令按顺序跑完再自己汇总——那不叫验收，那叫"人肉 CI"。本工具把收口清单固化成一台仪器：
`python dev/tools/accept.py` 跑完、印一份回执、用**退出码**说结论。

十二道门（判据**全部从被跑命令的输出里读**，不写死任何计数——写死会在下次改动后变成假绿）：

| 门 | 覆盖 | 判据来源 |
| --- | --- | --- |
| ① 套件 | `dev/verify/run.py` 四面（contract / gates / invariants / e2e） | 逐面 `【面…】N/M 通过` 行 + 进程退出码 |
| ② 结构 | 自举树每张 `flowtable.md` 过 H1–H8 + 表头 H9（H10 要账本，自举树没有 ⇒ 这一层跳过） | `table_to_dsl.py --check --json` 的 `len(hard)` / `len(soft)` |
| ③ 覆盖 | 每个函数都画进表了吗 | `coverage.py --tables-root` 的覆盖率行 + `✓/✗` 结论行 + 退出码 |
| ④ 几何 | 每张**模块表**的几何单独过 `validate` | `validate.py <模块>-flow.yaml` 的退出码与条目数 |
| ⑤ 出图 | 根表能不能 build 成三份产物（html / drawio / svg） | `build.py` 退出码 + `⚠` 告警**分类计数** |
| ⑥ 回执 | 这棵树是哪一版的 | 全树 `flowtable.md` 的表文本摘要（内容口径）＋ 整树摘要（去掉点开头的构建备份，产物口径） |
| ⑦ 分层 | 依赖方向对不对 | layering.py 退出码 + 违规清单；**先查依赖图是不是旧快照**，过期直接判仪器故障 |
| ⑧ 卫生 | scripts/*.py 的未用 import／死函数归零 | hygiene.py 退出码（0 过 / 1 有白写 / 其它=仪器故障）；**射程只有 scripts/**，见 D-88 |
| ⑨ 审美 | 三条审美律的读数不许退化（偏心 / 绕行 / 通道半径） | `aesthetic.py` 的读数与退出码；阈值见 `references/visual-spec.md` §0.1（当前收口值，见 G12） |
| ⑩ 等价 | 夹具自身有效 + 工作树可观测行为与底本 tag 逐字节相同 | `table_to_dsl --check` 对 `equiv-fixtures/*.md` 的期望结果；`equiv.py make-base` / `suite` 的退出码 |
| ⑪ 材料链 · 漂移 · 取子集 | `drift.py` 的判据 D1—D5 与账目对账 · `query.py` 的取子集边界 · pptx 全链（判 T1 / 摘要 / 按张撬开）· 幂等 · 只读 · 缺依赖提示 · 拒绝分支 | `pipeline-fixtures/suite.py` 的 `PASS/FAIL` 行 + 退出码；夹具在系统临时目录里现造现跑 |
| ⑫ API 面 | 对外函数面**丢没丢**（底本 tag ↔ 工作树） | `api_audit.py` 的退出码（0 无丢失/无签名变更 · 1 有 · 2 底本读不了=仪器故障）＋ 它印的四个计数 |

**门⑤在仓库外的副本上跑**：`build.py` 会往树里写 html / drawio / `.bak` / yaml。验收**不改产物**，
所以先把树整棵复制到临时目录再 build——副本的根目录仍叫 `self-boot`，产物名（`self-boot-flow.html`
这类，`artifact.artifact_stem` 取的是目录名）与实际交付**逐字一致**。副本目录**每次唯一**
（`mkdtemp`），**不用"先删再建"**（撞批量删除的安全钩子会把"门全过"变成"命令报错"）；
清理**只在成功且用的是默认现场时**发生（2026-09-19 改，D-113）：

- **没过 / 仪器故障 ⇒ 现场原样留着**（那正是要看的东西）；
- **过了 ⇒ 收掉"本次新建的"那几项**（进门之前先记下现场里已有什么，只删增量——不动你放在这儿的东西）；
- 清理动作**在结论印完之后**发生，`ignore_errors=True`，**永不参与判分**；删不掉只多印一行；
- `--keep` 留着不看结论也要现场；`--scratch` 是你给的目录 ⇒ 一律不动。
- 为什么改：原先写"只占约 2 MB、不替你删"，实测**每跑一次留 5.7 MB / 140 个文件**，
  连跑十几轮攒到 **134 MB / 2579 个文件**（没有人会想起来清）。存量用 `dev/tools/sweep.py` 收。

**门⑥是回执型门**：摘要没有阈值，它"不过"只意味着树为空或读不了。之所以并列成一道门，是因为
收口时**必须报出**"这份结论对应哪一版树"——否则数字和树对不上账。它印**两个口径**，因为两件事
要用不同的尺子量：
- **表文本（内容口径）**只算 `flowtable.md`，与产物、与 build 历史无关 → **比"表改没改"用它**；
- **整树（产物口径）**排除点开头文件（本仓里就是 `build.py` 留的 `.self-boot-flow.*.bak` 备份）
  → 去掉构建历史后**应可复现**，同一棵树跑两次 build 摘要不变 → **比"交付物变没变"用它**。
  备份不能算：算进去它就是"上一次渲染的副本"，会让同一棵树的回执每 build 一次漂一次，跨轮不可比。

退出码（与四件仪器同一套约定，**"命令没跑起来"绝不平摊成"门没过"**）：

| 码 | 含义 |
| --- | --- |
| `0` | 十二道门全过 |
| `1` | 有门未过（命令跑起来了、结论是"不过"） |
| `2` | **仪器故障**：表树不存在 / 命令起不来 / 输出解析不了（此时树是半成品或结论不可信） |

用法：
    python dev/tools/accept.py
    python dev/tools/accept.py --tables-root output/self-boot
    python dev/tools/accept.py --allow-soft        # 门②不再因软提示（如标签偏长）报红

**换机器 / 换目录之后先跑一次生成器**：表树（`output/self-boot/`）与图快照（`dev/tools/fn-*.json`）都是
**派生物**，`.gitignore` 把它们排除了 ⇒ 拷过去/克隆下来时它们本来就不存在，门②③④⑤⑥ 会一起报
"仪器故障"（那是"还没生成"，不是"门没过"）。顺序不可换（见 `ARCHITECTURE.md` 第七节）：

    python dev/tools/fn_graph.py && python dev/tools/selfboot_gen.py

再跑本命令即可。这条例外是刻意的：仓库要求"改了码必须重跑生成器"，否则 `coverage` 的分母是旧快照、
必然报 100%（**假绿**）。

**这台工具盖不住什么**（诚实列，别把它当"全绿就没事"）：
- 产品 CLI 的命令面由门⑩ 的用例清单（`dev/tools/equiv-cases.json`）覆盖——**清单之外**的参数组合
  仍等于没验（加用例要动那份 JSON，见 `dev/tools/equiv-README.md`）；
- **不重跑生成器**（那会重写 `output/self-boot/`），所以"生成器仍确定性"要靠"连跑两次比摘要"
  在**验收之外**单独做；本工具只保证"这一版的树本身自洽"；
- 门⑤的告警账本是**手工维护**的（`BUILD_WARNINGS`，当前 13 族）：build.py **或其调用链**
  （`table_to_dsl` 在进程内被调，它的 `⚠ 软提示` 也落入同一条 stdout）新增 `⚠` 告警时必须同步该表，
  否则门⑤ 会判**仪器故障**——那是刻意设计（宁可吵，不可静默漏计）。机制与穷举结论见该表上方注释；
  反过来，**不以 `⚠` 开头的告警不在账内**（`✗` 硬错误、`· 层级索引:` 正常行、`契约: …⚠ 推断 N`）；
- 门①的结论**覆盖面 = 套件用例的覆盖面**，套件没写的分支等于没验；
- 门④验的是**盘上已展开的几何**，不验"提示→几何"这一步（那一步的正确性由生成器自己的
  `_materialize` 保证；判它有没有跑，看模块 yaml 里有没有完整 `nodes/edges`，本工具不查这一项）。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO as ROOT, SCRIPTS, TOOLS, VERIFY  # noqa: E402

# 底本 tag 的**唯一出处**是 api_audit.py 的 REV_DEFAULT：门⑩ 与 api_audit 必须指同一个 tag，
# 不许在两处各写一份（写死就会漂）。
sys.path.insert(0, str(TOOLS))
from api_audit import REV_DEFAULT as API_BASE  # noqa: E402

DEFAULT_TABLES = ROOT / 'output' / 'self-boot'
PY = sys.executable

# 表树缺失时的修复指令（**不是补丁，是既定纪律**）：`output/` 与 `/tools/fn-*.json` 都在 `.gitignore` 里
# ——前者是"本地生成的流程产物目录"，后者注释明写"快照、可再生产"。所以换机器/换目录后表树本来就不存在，
# 那 5 道门报的"仪器故障"是"还没生成"而不是"门没过"。顺序不可换：图快照在前，表树由它派生。
GEN_COMMAND = 'python dev/tools/fn_graph.py && python dev/tools/selfboot_gen.py'

# 门⑤的账本：每族一条 `(标签, 片段)`，片段取自 **build.py 及其调用链**印出的告警原文。
#
# **机制（改这里之前先读）**：`build.py` 会**在进程内**调 `table_to_dsl.main`、`layer_index`、
# `validate.main`……它们的 `⚠` 行会一并落进门⑤ 抓到的 stdout。**这些地方新增任何以 `⚠` 开头的告警，
# 都必须同步这张表**——否则"⚠ 行总数"与"分类合计"对不上，门⑤ 会把**"账少了一族"误报成仪器故障**
# （而且故障文案会指向"措辞变了"，归因也是错的）。这不是可选维护项：门⑤ 的牙齿就是
# **"每一行 `⚠` 都恰好属于一族"**。
#
# 四条约定，都是为了让账经得起复核：
# 1. **每族只给一个片段**。一行同时命中两族 → 判仪器故障（表该拆细），不猜；
# 2. **片段不含变量数字**（张数/项目数会变），否则条数一变就数不准；
# 3. **按"族"匹配而非按单条措辞**：`⚠ 层级索引: ` 后面可能是孤儿表 / id 重复 / 层级声明不一致 /
#    层级歧义四种消息，只匹配其中一个词（如 `孤儿表`）会让同族其他消息漏成仪器故障；
# 4. **优先取"有辨识度的尾部"，慎用 `⚠ xxx ` 这类通用引导词**：通用前缀会把将来新增的告警
#    **悄悄吞进本族**——账反而平了，连仪器故障都不报，这比漏计更坏。取尾部则新告警会因"归不了族"
#    当场报故障。`⚠ 子表未内嵌（…）` 这类前缀之所以可用，是因为其后的并列措辞本身就构成族名。
#
# 穷举结论：`scripts/` 里所有"会在 build 运行时打到 stdout 的 `⚠` 行"共 **13 族**，全在这张表里。
# 复核方法（改了 build 就重跑一遍）：`grep -rn "⚠" scripts/*.py | grep print`
# 未列入的 `⚠` 都是**不进 build stdout** 的：其它命令（sync / writeback / clarify / xml_reader）的
# 输出、`layer_index` 自己 CLI 的 `print('⚠', n)`、`--help` 里的静态说明文字、
# `manifest` 里拼进 `契约: …` 行首的 `⚠ 推断 N`（该行以"契约:"开头，不算 `⚠` 行）。
BUILD_WARNINGS = (
    # —— build.py 本体 ——
    ('未内嵌·结构校验未过', '⚠ 子表未内嵌（结构校验未过）'),
    ('未内嵌·转 DSL 失败', '⚠ 子表未内嵌（转 DSL 失败）'),
    ('未内嵌·DSL 读不动', '⚠ 子表未内嵌（DSL 读不动'),
    ('已内嵌但几何未过', '⚠ 子表已内嵌但几何未过'),
    ('新增节点·复用旧几何', '复用旧几何会把它们一律放到 col=0'),
    ('嵌套超过 5 层', '⚠ 子图嵌套超过 5 层'),
    ('内嵌视图超过上限', '⚠ 内嵌视图超过上限（MAX_VIEWS='),
    ('未内嵌·DSL 读不动·子孙未枚举', '张子表 DSL 读不动：它们的子孙既未内嵌也未校验'),
    ('未内嵌·子表不存在', '⚠ 子表不存在，未内嵌'),
    ('层级索引·告警族', '⚠ 层级索引: '),
    ('AI 推断留痕', '处为 AI 推断（原文未载明）'),
    # —— 调用链：table_to_dsl.main（build 在进程内调它做结构校验与转 DSL）——
    ('软提示·不阻断', '⚠ 软提示（不阻断'),
    ('布局提示不存在', '⚠ 布局提示不存在，回退到基线自动布局'),
)

FACE_RE = re.compile(r'^【(.+?)】(\d+)/(\d+) 通过')
COV_RE = re.compile(r'覆盖率\s*=\s*(\d+)/(\d+)')


class Gate:
    """一道门的结果：过 / 没过 / 仪器故障。三态分开，故障不平摊成"没过"。"""

    def __init__(self, name, title):
        self.name, self.title = name, title
        self.lines = []
        self.ok = None          # True 过 / False 没过 / None 仪器故障
        self.reason = ''

    def note(self, text):
        self.lines.append(text)

    def passed(self):
        self.ok = True

    def failed(self, reason):
        self.ok = False
        self.reason = reason

    def broken(self, reason):
        self.ok = None
        self.reason = reason

    @property
    def mark(self):
        return {True: '✓', False: '✗', None: '⚠'}[self.ok]


def run(args, cwd=ROOT):
    """跑一条外部命令；命令起不来（OSError）由调用方按仪器故障处理。

    **子进程一律无缓冲输出**（`PYTHONUNBUFFERED=1`，被调脚本再 spawn 的孙子进程也继承）：
    否则子进程的 stdout 走块缓冲，遇到卡住/被杀时门⑤抓到的输出会**少掉尾部**——
    那时判出来的不是"门没过"，而是"账对不上"这种假仪器故障。

    **同时禁止写字节码缓存**（`PYTHONDONTWRITEBYTECODE=1`）：验收会反复 import `scripts/`
    与 `dev/verify/` 的模块，默认在仓库里留一堆 `__pycache__`——那是运行产物、不是仓库内容
    （`.gitignore` 同样认定）。代价只是每次 import 重新编译，这些模块都很小。
    """
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=str(cwd), env=env)


def rel(path, root):
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def items_of(stdout):
    """flowtable 类工具的条目行格式：`   - <条目>`。"""
    return [ln.strip()[2:] for ln in (stdout or '').splitlines()
            if ln.strip().startswith('- ')]


def tables_is_missing(tables_root):
    """表树还没生成吗 → 修复指令（生成好了返回 `''`）。

    为什么要专门判一次：表树是**派生物**（`.gitignore` 排除了 `output/` 与 `/tools/fn-*.json`），
    换机器/换目录后它本来就不存在，于是门②③④⑤⑥ 一起报"仪器故障"——**每条原因都对，但都不告诉人
    怎么修**。门⑦ 早已在自己的故障文案里带了"先跑 fn_graph.py"，这一条是同一做法的补齐。
    """
    if tables_root.is_dir() and any(tables_root.rglob('flowtable.md')):
        return ''
    return (f'表树本身不存在（{tables_root}）——它是**派生物**，`output/` 与 `dev/tools/fn-*.json` 都在 '
            f'`.gitignore` 里，换机器/换目录后本来就没有：先跑 `{GEN_COMMAND}` 再重跑本命令')


def module_dirs(tables_root):
    """模块表目录：根下每一个既含 `flowtable.md` 的**子目录**（根表本身不算模块）。"""
    if not tables_root.is_dir():
        return None
    return [d for d in sorted(tables_root.iterdir())
            if d.is_dir() and (d / 'flowtable.md').is_file()]


# ----------------------------------------------------------------门① 套件
def gate_suite(g, scratch):
    tmp = scratch / 'verify'
    try:
        r = run([PY, VERIFY / 'run.py', '--tmp', tmp])
    except OSError as e:
        return g.broken(f'dev/verify/run.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode not in (0, 1):
        return g.broken(f'dev/verify/run.py 退出码 {r.returncode}（既非 0 也非 1，'
                        f'不是"有面未过"而是"没跑成"）')
    faces = []
    for ln in (r.stdout or '').splitlines():
        m = FACE_RE.match(ln.strip())
        if m:
            faces.append((m.group(1), int(m.group(2)), int(m.group(3))))
    if not faces:
        return g.broken('dev/verify/run.py 没有印出任何「【面…】N/M 通过」小结行（输出不可解析）')
    for title, good, total in faces:
        g.note(f'{"✓" if good == total else "✗"} {title}  {good}/{total}')
    if r.returncode == 0 and all(a == b for _t, a, b in faces):
        g.passed()
    else:
        g.failed('套件有面未过：' + '、'.join(f'{t} {a}/{b}' for t, a, b in faces if a != b))


# ----------------------------------------------------------------门② 结构
def gate_structure(g, tables_root, allow_soft):
    tables = sorted(tables_root.rglob('flowtable.md')) if tables_root.is_dir() else []
    if not tables:
        return g.broken(f'表树里一张 flowtable.md 都没有：{tables_root}')
    hard = soft = 0
    bad, softs = [], []
    for md in tables:
        try:
            r = run([PY, SCRIPTS / 'table_to_dsl.py', '--check', '--json', md])
        except OSError as e:
            return g.broken(f'table_to_dsl.py 起不来（{type(e).__name__}: {e}）')
        try:
            j = json.loads((r.stdout or '').strip())
            h, s = len(j['hard']), len(j['soft'])
        except Exception:
            return g.broken(f'{rel(md, tables_root)} 的 --check --json 输出不可解析：'
                            f'{(r.stdout or "")[:120]!r}')
        hard += h
        soft += s
        if r.returncode != 0 or h:
            bad.append((rel(md, tables_root), h, s))
        elif s:
            softs.append((rel(md, tables_root), s))
    g.note(f'{len(tables)} 张表：hard {hard} · soft {soft}')
    for name, h, s in bad:
        g.note(f'  ✗ {name}: hard={h} soft={s}')
    for name, s in softs:
        g.note(f'  {"·" if allow_soft else "✗"} {name}: 软提示 {s} 条')
    if bad:
        return g.failed(f'{len(bad)} 张表有硬错误')
    if softs and not allow_soft:
        return g.failed(f'{len(softs)} 张表有软提示（需要它放过就加 --allow-soft）')
    g.passed()


# ----------------------------------------------------------------门③ 覆盖
def gate_coverage(g, tables_root):
    try:
        r = run([PY, TOOLS / 'coverage.py', '--tables-root', tables_root])
    except OSError as e:
        return g.broken(f'coverage.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode == 2:
        return g.broken('coverage.py 退 2：输入读不了（图缺失 / 目录不存在 / 解析失败）')
    if r.returncode not in (0, 1):
        return g.broken(f'coverage.py 退出码 {r.returncode}（不是它的 0/1/2 契约）')
    cov = next((ln for ln in (r.stdout or '').splitlines() if COV_RE.search(ln)), None)
    if cov is None:
        return g.broken('coverage.py 输出里找不到「覆盖率 = X/Y」行')
    m = COV_RE.search(cov)
    g.note(cov.strip())
    for ln in (r.stdout or '').splitlines():
        if ln.startswith('✓') or ln.startswith('✗'):
            g.note('  ' + ln.strip())
    if r.returncode == 0 and m.group(1) == m.group(2):
        g.passed()
    else:
        g.failed(f'覆盖未收口：{m.group(1)}/{m.group(2)}')


def gate_aesthetic(g, tables_root):
    """门⑨：三条审美律的读数不许退化（`references/visual-spec.md` §0.1，D-92）。

    **为什么它够格当一道门**：三条律都能算成数（`dev/tools/aesthetic.py`），而且**已经有过退化**——
    主轴偏心曾是 0.37~0.43（主轴永远是最左列）、回路绕行曾因分支分挂两侧而涨到 385%（左廊基准脱离
    了本列）。这两处都只有"看图的人"才会发现；接成门以后，改布局/路由把它们改回去就当场红。

    **阈值分两档，理由要看得见**：
      · 主轴偏心 ≤0.15 —— **达标**（可配平的表实测 0.00）；列数 <3 的表没有两侧可分，"臂"退化，
        工具自己标「单臂」且不进均值（拿它当失败是误伤）。
      · 通道半径 ≤0.5 —— **达标**（实测 0.00~0.17）。
      · 绕行均值 ≤45%、最坏 ≤60% —— 这是**收口值**（D-92 定的），`visual-spec` §0.1 与它逐值一致
        （当前实测 **41%**）。**这四个数现在只有一个家**：`aesthetic.LIMITS`——本函数从它印的汇总行里
        读，不再写死在这里；三处同值由面① 一条断言守着（2026-09-19，D-132）。原先 §0.1 挂着
        "均值 ≤35%"而这里执行 45%，**一条不执行的阈值就是一句空话**；35% 记为已知的机会
        （要动生成器把长跳拆到两列），不是欠账。门判的始终是"**不许变差**"。
    """
    try:
        r = run([PY, TOOLS / 'aesthetic.py', tables_root])
    except OSError as e:
        return g.broken(f'aesthetic.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode != 0:
        return g.broken(f'aesthetic.py 退出码 {r.returncode}（读不动表树？）')
    out = r.stdout or ''
    tail = next((ln for ln in out.splitlines() if ln.startswith('——')), None)
    if tail is None:
        return g.broken('aesthetic.py 输出里找不到汇总行')
    g.note(tail.strip())
    m = dict(re.findall(r'平均(主轴偏心|绕行|通道半径) ([\d.]+)', tail))
    off = float(m.get('主轴偏心', '0'))
    det = float(m.get('绕行', '0'))
    rad = float(m.get('通道半径', '0'))
    worst = max((float(x) for x in re.findall(r'平均绕行\s*(\d+)%', out)), default=0)
    # **阈值不写死在这里**（2026-09-19，D-132）：从它印的汇总行里读——这个文件的纪律是
    # "判据全部从被跑命令的输出里读"，而阈值原先在本函数里另有四个字面量，与 `visual-spec` §0.1
    # 的表**当时并不一致**（规范写"绕行均值 ≤35%"，这里执行 45%）。唯一出处是 `aesthetic.LIMITS`。
    m2 = re.search(r'阈值\s*偏心<=([\d.]+)\s*·\s*半径<=([\d.]+)\s*·\s*'
                   r'绕行<=(\d+)%\s*/\s*最坏<=(\d+)%', tail)
    if m2 is None:
        return g.broken('aesthetic.py 的汇总行里找不到阈值（它该印"阈值 偏心<=… · 半径<=… · '
                        '绕行<=… / 最坏<=…"）')
    # 逐个取组——**别用 `dict(re.findall(...))`**：四个组时 `findall` 回的是 4 元组，`dict()` 当场
    # 抛 `ValueError: dictionary update sequence element #0 has length 4`。这一版就是那么写的，
    # 而**四面测不到门⑨ 自己的健康**（它在 accept.py 里），是 `accept.py` 跑起来才现的形。
    off_lim, rad_lim = float(m2.group(1)), float(m2.group(2))
    det_lim, worst_lim = float(m2.group(3)), float(m2.group(4))
    bad = []
    if off > off_lim:
        bad.append(f'主轴偏心 {off:.2f} > {off_lim}')
    if rad > rad_lim:
        bad.append(f'通道半径 {rad:.2f} > {rad_lim}')
    if det > det_lim:
        bad.append(f'绕行均值 {det:.0f}% > {det_lim:.0f}%')
    if worst > worst_lim:
        bad.append(f'绕行最坏 {worst:.0f}% > {worst_lim:.0f}%')
    if bad:
        g.failed('；'.join(bad))
    else:
        g.passed()


# ----------------------------------------------------------------门④ 几何
def gate_geometry(g, tables_root):
    mods = module_dirs(tables_root)
    if mods is None:
        return g.broken(f'表树不是目录：{tables_root}')
    if not mods:
        return g.broken(f'表树下没有模块目录：{tables_root}')
    ok, bad = [], []
    for d in mods:
        yml = d / f'{d.name}-flow.yaml'
        if not yml.is_file():
            bad.append((d.name, f'缺 {yml.name}', 0))
            continue
        try:
            r = run([PY, SCRIPTS / 'validate.py', yml])
        except OSError as e:
            return g.broken(f'validate.py 起不来（{type(e).__name__}: {e}）')
        if r.returncode == 0:
            ok.append(d.name)
        else:
            bad.append((d.name, '几何未过', len(items_of(r.stdout))))
    g.note(f'{len(mods)} 张模块表：过关 {len(ok)}/{len(mods)}')
    for name, why, n in bad:
        g.note(f'  ✗ {name}: {why}' + (f'（{n} 项）' if n else ''))
    if bad:
        return g.failed(f'{len(bad)} 张模块表几何未过')
    g.passed()


# ----------------------------------------------------------------门⑤ 出图
def gate_build(g, tables_root, scratch):
    """在一份**仓库外**的临时副本上跑 build（见模块 docstring：验收不改产物）。

    副本目录**每次唯一**（`mkdtemp` 一个父目录，再在其下命名 `self-boot`——名字不能变，
    产物名由目录名派生）。**不用"先删再建"**：那会撞批量删除的安全钩子，把"门全过"变成
    "命令报错"；两份写法不是等价改写。
    """
    dest = Path(tempfile.mkdtemp(prefix='build-', dir=scratch)) / 'self-boot'
    try:
        shutil.copytree(tables_root, dest)
    except OSError as e:
        return g.broken(f'复制表树失败（{type(e).__name__}: {e}）')
    try:
        r = run([PY, SCRIPTS / 'build.py', dest / 'flowtable.md'])
    except OSError as e:
        return g.broken(f'build.py 起不来（{type(e).__name__}: {e}）')
    out = (r.stdout or '') + (r.stderr or '')
    # 总数按 **⚠ 开头的行** 数，不按 ⚠ 字符数：`⚠ 软提示（…请 AI 处理并打 ⚠ 留痕）：` 这一行
    # 行内还有第二个 ⚠，按字符数会把一条告警数成两条，凭空造出"账对不上"。
    wlines = [ln for ln in out.splitlines() if ln.lstrip().startswith('⚠')]
    # 每行**恰好**归一族：归不了族（漏了一族）或归了两族（表该拆细）都当场判仪器故障。
    hits = {label: 0 for label, _ in BUILD_WARNINGS}
    unmatched, ambiguous = [], []
    for ln in wlines:
        got = [label for label, text in BUILD_WARNINGS if text in ln]
        if len(got) == 1:
            hits[got[0]] += 1
        elif got:
            ambiguous.append((ln.strip(), got))
        else:
            unmatched.append(ln.strip())
    warns, counted = len(wlines), sum(hits.values())
    emb = re.search(r'内嵌 (\d+) 张子图', out)
    pages = re.search(r'页数:\s*(\d+)', out)
    g.note(f'rc = {r.returncode}（在仓库外副本上跑：{rel(dest, scratch)}）')
    g.note(f'告警分类计数 = {hits}')
    g.note(f'⚠ 行总数 = {warns}（分类合计 {counted}）'
           + (f'；内嵌 {emb.group(1)} 张子图' if emb else '')
           + (f'；页数 {pages.group(1)}' if pages else ''))
    if r.returncode not in (0, 1):
        return g.broken(f'build.py 退出码 {r.returncode}（不是 0/1）')
    if unmatched or ambiguous:
        why = []
        if unmatched:
            why.append(f'未归类 {len(unmatched)} 行：{"；".join(unmatched[:3])}')
        if ambiguous:
            why.append('一行命中多族（本表该拆细）：'
                       + '；'.join(f'{ln} → {got}' for ln, got in ambiguous[:2]))
        return g.broken(
            f'⚠ 行总数 {warns} 与分类合计 {counted} 不等 → 可能是 build.py（或其调用链，'
            f'含 table_to_dsl）新增/改了告警，也可能是本表漏了一族'
            f'（机制见 BUILD_WARNINGS 上方注释）：' + '；'.join(why))
    if r.returncode == 0 and warns == 0:
        g.passed()
    else:
        g.failed(f'build 未过或带告警（rc={r.returncode}，⚠ {warns} 条）——'
                 f'告警本身不一定代表错（例如软提示是正常的）；但收口态的自举树应为零告警，'
                 f'出现告警请先确认它属于哪一族、是否预期')


# ----------------------------------------------------------------门⑥ 回执
def tree_digest(root, files):
    h = hashlib.sha256()
    for p in files:
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def gate_digest(g, tables_root):
    """两口径回执：**内容口径**（表文本）与**产物口径**（整树，不含点开头文件）。

    为什么整树口径要排除点开头文件：`build.py` 会把上一版渲染留成 `.self-boot-flow.html.bak`
    这类备份、落在同一棵树里。把备份算进来，摘要就**随构建历史漂移**——同一棵树跑两次 build
    就换一个值，跨轮不可比，那它就不是回执。点开头文件在本仓一律是备份 / 元信息
    （`.gitignore` 同一口径），所以按"点开头即备份"整体排除，不做逐名白名单。
    """
    if not tables_root.is_dir():
        return g.broken(f'表树不是目录：{tables_root}')
    tables = sorted(tables_root.rglob('flowtable.md'))
    if not tables:
        return g.broken(f'表树里一张 flowtable.md 都没有：{tables_root}')
    every = [p for p in sorted(tables_root.rglob('*')) if p.is_file()]
    content = [p for p in every if not p.name.startswith('.')]
    skipped = [p for p in every if p.name.startswith('.')]
    g.note(f'表文本（{len(tables)} 张 flowtable.md） sha256 = {tree_digest(tables_root, tables)}')
    g.note('  ← 内容口径：只含表，与产物 / build 历史无关；比"表改没改"用它')
    g.note(f'整树（不含点开头文件，{len(content)} 个文件）'
           f' sha256 = {tree_digest(tables_root, content)}')
    g.note('  ← 产物口径：排除 build 备份后**应可复现**（同一棵树跑两次 build 摘要不变）；'
           '比"交付物变没变"用它')
    if skipped:
        names = '、'.join(p.relative_to(tables_root).as_posix() for p in skipped[:4])
        g.note(f'  （已排除 {len(skipped)} 个点开头文件（构建备份）：{names}'
               f'{"…" if len(skipped) > 4 else ""}）')
    g.passed()


# ----------------------------------------------------------------门⑦ 分层
def graph_is_stale():
    """依赖图是**快照**：任何 `scripts/*.py` 比 `dev/tools/fn-graph.json` 新 → 图已过期。

    **为什么这道检查必须在这里**：`layering.py` 的分母来自图，图不新鲜时它看不见新模块的边；
    `coverage.py` 同理（分母也是图）——"代码改了没重跑生成器"这条通道会让门③/门⑦ 一起假绿。
    实测过一次：图比代码旧一个提交时 `coverage.py` 报 100%，重跑后立刻变成"缺失 1"。
    所以这里用**文件系统事实**（mtime）把它拦在门外：图过期 = 结论不可信 = 仪器故障，不是"门没过"。
    """
    gp = TOOLS / 'fn-graph.json'
    if not gp.is_file():
        return True, 'dev/tools/fn-graph.json 不存在'
    mt = gp.stat().st_mtime
    newer = [p.name for p in sorted(SCRIPTS.glob('*.py')) if p.stat().st_mtime > mt]
    if newer:
        head = '、'.join(newer[:4]) + ('…' if len(newer) > 4 else '')
        return True, f'{len(newer)} 个脚本比图新（{head}）'
    return False, ''


def gate_layering(g):
    stale, why = graph_is_stale()
    if stale:
        return g.broken(f'依赖图是旧快照：{why} → 先跑 python dev/tools/fn_graph.py；'
                        f'图不新鲜时门③（覆盖）与门⑦（分层）都会假绿')
    try:
        r = run([PY, TOOLS / 'layering.py'])
    except OSError as e:
        return g.broken(f'layering.py 起不来（{type(e).__name__}: {e}）')
    for ln in (r.stdout or '').splitlines():
        if ln.strip():
            g.note(ln.rstrip())
    if r.returncode == 2:
        return g.broken('layering.py 退 2：输入读不了（图缺失 / 有新模块没归层）')
    if r.returncode not in (0, 1):
        return g.broken(f'layering.py 退出码 {r.returncode}（不是它的 0/1/2 契约）')
    if r.returncode == 0:
        g.passed()
    else:
        g.failed('模块层之间有代码依赖，或公共层反向依赖上层（违规清单见上）')


# ----------------------------------------------------------------主流程
#: 默认临时目录名（仓库内、已被 .gitignore 覆盖）。
SCRATCH_NAME = '.accept_tmp'


def _pinned_scratch():
    """真跑起来**真能出图**的临时目录（按优先级）。

    为什么默认不用系统临时目录：本机 Edge 的 `--headless=new --screenshot` **静默拒绝**把 PNG 写进
    `%TEMP%` 的**子目录**——实测 `%TEMP%` 根可写、其下手工 `mkdir` 与 `mkdtemp` 建的目录都写不出，
    且 **rc=0、stderr 为空、文件不存在**。后果很隐蔽：`dev/verify/run.py` 的临时目录在仓库内，
    面④「截图自检可用」照过；而本工具默认 `mkdtemp()` 落在 `%TEMP%`，同一套件就会红在
    「截图自检可用」——**看起来像套件坏了，其实是这台机器的浏览器行为**。
    注意探针要测**基准目录本身**：各道门会在它下面再建子目录（`<scratch>/verify/e2e/…`），
    所以"`%TEMP%` 根能出图"并不够——子目录才是真正落图的地方。
    教训：验收工具的临时目录**不该挑一个能力更差的地方**，所以默认改为仓库内、可写、可出图。
    """
    return [ROOT / SCRATCH_NAME, ROOT, Path(tempfile.gettempdir())]


def _can_screenshot_here(d):
    """探针：这个目录能不能真的截出图（用最小页面走一遍 shot.py 的同一条命令）。"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(SCRIPTS))
        import shot as _shot
        exe = _shot.find_browser()
        if not exe:
            return False
        d.mkdir(parents=True, exist_ok=True)
        probe = d / '_probe.html'
        probe.write_text('<!DOCTYPE html><html><body>x</body></html>', encoding='utf-8')
        png = d / '_probe.png'
        if png.exists():
            png.unlink()
        cmd = [exe, '--headless=new', '--disable-gpu', '--hide-scrollbars',
               f'--screenshot={png.resolve()}', '--window-size=200,150', probe.as_uri()]
        subprocess.run(cmd, capture_output=True)
        for _ in range(40):
            if png.exists() and png.stat().st_size > 0:
                return True
            time.sleep(0.1)
        return False
    except Exception:
        return False
    finally:
        for n in ('_probe.html', '_probe.png'):
            try:
                (d / n).unlink()
            except OSError:
                pass


def _default_scratch():
    """选一个能出图的目录；都不行就退回系统临时目录（照旧会红，但至少不改变既有行为）。"""
    return next((d for d in _pinned_scratch() if _can_screenshot_here(d)),
                Path(tempfile.gettempdir()) / SCRATCH_NAME)


# ----------------------------------------------------------------门⑧ 卫生
def gate_hygiene(g):
    """门⑧：`scripts/*.py` 的"白写"归零（未用 import / 没人调的模块级函数）。

    为什么它够格当一道门：`dev/coding-spec.md` 第 17 行的规则是"未用 import／死函数归零"，
    而在这之前它**只有仪器、没有验收路径**——实测过 6 处未用 import + 1 个死函数躺着，七道门
    照样全绿（G6）。规则要么进验收、要么承认靠人记，不能停在中间（D-88）。
    **射程只有 `scripts/`**：`dev/` 的未用 import 不改变任何产物字节与退出码，为它把 `dev/`
    塞进依赖图会让门③ 的分母多出上百个 dev 函数（N31）。
    """
    try:
        r = run([PY, TOOLS / 'hygiene.py'])
    except OSError as e:
        return g.broken(f'hygiene.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode not in (0, 1):
        return g.broken(f'hygiene.py 退出码 {r.returncode}（不是它的 0/1 契约）')
    for ln in (r.stdout or '').splitlines():
        if ln.strip().startswith(('──', '（无）', '   ')) and ln.strip():
            g.note(ln.strip())
    if r.returncode == 0:
        g.passed()
    else:
        g.failed('有未用 import 或没人调的模块级函数（上面点名了具体位置）')


# ----------------------------------------------------------------门⑫ API 面
def gate_api(g):
    """门⑫：**对外函数面的增删记账**——底本 tag 有、工作树没有的（丢失 / 签名变更）为 0。

    为什么它够格当一道门（`coding-spec` G8 的另一半，2026-09-19 D-131 收口）：那条规则是
    "对外 API 增删要记账"（第 19 行），而此前**只有等价性那一半进了验收**——`equiv` 比的是
    "可观测行为逐字节相同"，它回答不了"**谁把函数删了**"：删掉一个没人走的公开函数，
    `equiv` 照样全绿。`api_audit.py` 早就能跑（要 git 底本，本仓 2026-09-17 起就有 tag
    `api-base`），只是**只在有人想起来时手跑一次**——那正是"规则停在中间"的形态。

    判据**从它的输出里读**（不写死计数，也不自己再解析一遍源码）：退出码 0 = 无丢失且无签名变更。
    `api_audit` 的三态契约与本门一致（0/1/2），所以 2 直接当**仪器故障**——不是"门没过"。
    **射程**：它比的是"底本 tag ↔ 工作树"，所以它**只在你提交前后有意义**；工作树脏的时候
    它报的是"你正在改的东西"，那是对的（改动要不要紧、要不要重钉 tag，是人来判，
    本门只保证"**丢函数这件事不会静默发生**"）。`--near` 的近似改名那一档**不计入失败**
    （同文件内找到对应新函数 = 改名，不是删）——那是 `api_audit` 自己的取舍，门沿用。
    """
    try:
        r = run([PY, TOOLS / 'api_audit.py'])
    except OSError as e:
        return g.broken(f'api_audit.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode == 2:
        return g.broken('api_audit 退 2：底本读不了（没有 git / tag `api-base` 不在）')
    if r.returncode not in (0, 1):
        return g.broken(f'api_audit 退出码 {r.returncode}（不是它的 0/1/2 契约）')
    for ln in (r.stdout or '').splitlines():
        s = ln.strip()
        if s.startswith(('丢失', '签名变更', '疑似改名', '新增', '结论')):
            g.note(s)
    if r.returncode == 0:
        g.passed()
    else:
        g.failed('对外函数面有丢失或签名变更（上面点名了）——要么补回来，要么记进 DECISIONS')


# ----------------------------------------------------------------门⑩ 等价
def gate_equiv(g, scratch):
    """门⑩：equiv 链自身健康，且工作树的可观测行为与底本 tag 逐字节相同。

    **为什么它够格当一道门**：`equiv.py` 回答「我这次改动改变可观测行为了吗」，可它**自己**此前不在
    验收路径（`coding-spec` G8/R2 记的就是这个缺口）——后果实测过：D-66 把 `tools/` 挪进 `dev/` 时，
    `equiv-cases.json` 里 5 处夹具路径没跟着改，`suite` 每条用例都以「源文件不存在」报仪器故障；
    4 张夹具表还停在 9 列旧表头，`--check` 全退 1 ⇒ 成功路径**全部空跑**、两侧同失败被判「相同」。
    两次都是「没人跑它」养出来的，所以把它接进来。

    **判据三件**（缺一不可）：
      ① 夹具自身有效：`equiv-fixtures/*.md` 里三张好表过 `--check`、`broken.md` 不过。这条专防
         「夹具过期 ⇒ 两侧同样失败 ⇒ 假绿」——`suite` 只比两侧，夹具烂了它照样报全同；
      ② `make-base --rev <API_BASE>` 成功（没 git / tag 不存在 / 工作树读不了 → 仪器故障）；
      ③ `suite` 退出码 0（它的合约：0 全同 / 1 有不同 / 2 仪器故障）。

    **行为有意变更时怎么放行**：重钉底本 tag（`git tag -f api-base HEAD`）——与「改渲染器要重钉
    `dev/baseline`」同一条纪律（`coding-spec` 第 23 行）。
    """
    fixtures = TOOLS / 'equiv-fixtures'
    expect = [('tour.md', 0), ('lane.md', 0), ('tour-rewired.md', 0), ('broken.md', 1)]
    for name, want in expect:
        p = fixtures / name
        if not p.is_file():
            return g.broken(f'夹具不存在：{rel(p, ROOT)}')
        try:
            r = run([PY, SCRIPTS / 'table_to_dsl.py', '--check', p])
        except OSError as e:
            return g.broken(f'table_to_dsl.py 起不来（{type(e).__name__}: {e}）')
        got = 0 if r.returncode == 0 else 1
        g.note(f'{"✓" if got == want else "✗"} 夹具 {name}：--check 退出码 {r.returncode}'
               f'（期望{"过" if want == 0 else "不过"}）')
        if got != want:
            return g.failed(f'夹具 {name} 的校验结果与预期不符：夹具一过期，suite 就会'
                            f'「两侧同失败仍判全同」——先修夹具再谈等价')

    base = scratch / 'equiv-base'
    try:
        r = run([PY, TOOLS / 'equiv.py', 'make-base', '--rev', API_BASE,
                 '--dest', base, '--all-scripts'])
    except OSError as e:
        return g.broken(f'equiv.py 起不来（{type(e).__name__}: {e}）')
    if r.returncode != 0:
        return g.broken(f'equiv.py make-base 退 {r.returncode}：底本 tag {API_BASE} 取不到'
                        f'（没 git / tag 不存在 / 工作树读不了）——先 `git tag -l` 看一眼')
    g.note(f'底本 tag {API_BASE} 已展开到 {rel(base, ROOT)}')

    try:
        r = run([PY, TOOLS / 'equiv.py', 'suite', '--base', base,
                 '--scratch', scratch / 'equiv', '--cases', TOOLS / 'equiv-cases.json'])
    except OSError as e:
        return g.broken(f'equiv.py suite 起不来（{type(e).__name__}: {e}）')
    tail = next((ln for ln in (r.stdout or '').splitlines() if ln.startswith('共 ')), None)
    if tail is None:
        return g.broken('equiv.py suite 输出里找不到「共 N 条比对」小结行（输出不可解析）')
    g.note(tail.strip())
    if r.returncode == 0:
        return g.passed()
    if r.returncode == 1:
        return g.failed('工作树的可观测行为与底本 tag 不再逐字节相同（上面点了具体条目）；'
                        '若是有意变更，重钉：git tag -f api-base HEAD')
    return g.broken(f'equiv.py suite 退 {r.returncode}（它的合约是 0/1/2）')


# ----------------------------------------------------------------门⑪ 材料链与漂移
def gate_drift(g):
    """门⑪：材料链的两台仪器（`PIPELINE-SPEC` §5 / §5.3）**每轮验收都跑一遍**，用合成夹具钉住判据与边界。

    覆盖：`drift.py` 的判据 D1—D5 与 `check` 的**账目对账**（说谎 / 过期 / 无理由都要被抓住）；
    `query.py` 的点名取子集（分批 + 游标 / 范围 / 关键词 / 只裁显示不筛 / 语法错退 2）；
    pptx 全链（probe 判 T1 / recon 出摘要 / 读者按张撬开 + 超限留痕）。

    **为什么它够格当一道门**：这两台仪器的判据都有"读得对不对"与"边界守不守得住"两半，
    后者**只能用合成夹具验**（真实材料造不出"故意标错"），而在这之前它只有人手动跑：
    `coding-spec` G14 记的就是这个缺口。实测抓到的三件真问题（都在夹具里现形）：
    `check` 原先**只查了"已修是否真修"、没查"现在的命中是否漏在账外"**；伴生表**一行少一列被静默
    当成"没给"**（D2 静默不跑，表头还写"跳过了 D2"）；`--range rows=` 差点把命中筛成 0。
    三件都是「没人跑它」养出来的，所以把它接进来。

    **夹具不进仓库的产物**：`suite.py` 在系统临时目录里现造现跑现清，验收不写任何字节到树里。
    """
    try:
        r = run([PY, TOOLS / 'pipeline-fixtures' / 'suite.py'])
    except OSError as e:
        return g.broken(f'材料链夹具起不来（{type(e).__name__}: {e}）')
    if r.returncode not in (0, 1):
        return g.broken(f'材料链夹具退 {r.returncode}（它的合约是 0/1/2，2 = 夹具自身造不出来）')
    lines = [ln.strip() for ln in (r.stdout or '').splitlines()
             if ln.startswith(('PASS', 'FAIL', '——'))]
    for ln in lines:
        g.note(ln)
    n_pass = sum(1 for ln in lines if ln.startswith('PASS'))
    n_fail = sum(1 for ln in lines if ln.startswith('FAIL'))
    # **不能只看退出码**（审计实测：rc 0 + 一堆 FAIL、甚至 rc 0 + 零输出都判绿——那门是装饰）。
    # 判据：至少看到一条 PASS、且一条 FAIL 都没有。
    if r.returncode == 0 and n_fail == 0 and n_pass >= 20:
        return g.passed()
    if n_fail or r.returncode != 0:
        return g.failed(f'材料链夹具：{n_pass} 条 PASS · {n_fail} 条 FAIL（退 {r.returncode}）——'
                        f'红一条就是这条判据或这条守卫坏了')
    return g.broken(f'夹具没输出可判的行（只看到 {n_pass} 条 PASS 行）——夹具没跑起来就当仪器故障')


def _bytes_of(p):
    """一个现场项占多少字节（文件直接算，目录递归）——收尾那行读数用它（D-113）。"""
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for q in p.rglob('*'):
        if q.is_file():
            try:
                total += q.stat().st_size
            except OSError:
                pass
    return total


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='验收：一条命令跑完十二道门，只给一个结论',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='退出码：0 十二道门全过 / 1 有门未过 / 2 仪器故障（树不存在、命令起不来、输出解析不了）')
    ap.add_argument('--tables-root', default=str(DEFAULT_TABLES),
                    help=f'流程表树根（默认 {rel(DEFAULT_TABLES, ROOT)}）')
    ap.add_argument('--scratch', help='临时目录（默认落在仓库内 .accept_tmp/；见下方注释）')
    ap.add_argument('--keep', action='store_true',
                    help='门全过也留着现场（默认成功即收本次新建的；没过一律留着）')
    ap.add_argument('--allow-soft', action='store_true',
                    help='门②不因软提示报红（默认严格：hard 与 soft 都要求 0）')
    a = ap.parse_args(argv)

    tables_root = Path(a.tables_root).resolve()
    scratch = Path(a.scratch).resolve() if a.scratch else _default_scratch()
    scratch.mkdir(parents=True, exist_ok=True)      # --scratch 可能是新建的；mkdtemp 那份已存在
    # **进门之前记下现场里已有什么**：收尾只清"本次新建的"，你放在这儿的现场一律不动（D-113）。
    before = {p.name for p in scratch.iterdir()}

    print(f'验收：{rel(tables_root, ROOT)}')
    print(f'快照时刻：{time.strftime("%Y-%m-%d %H:%M:%S")}'
          f'（数字只对这一刻的树与脚本成立）')
    gates = []
    plan = [('①', '套件 dev/verify/run.py 四面', lambda g: gate_suite(g, scratch)),
            ('②', '结构 H1–H8 + 表头 H9', lambda g: gate_structure(g, tables_root, a.allow_soft)),   # H10 有账本才启用，自举树不覆盖它
            ('③', '覆盖 coverage.py', lambda g: gate_coverage(g, tables_root)),
            ('④', '几何 validate.py 逐张', lambda g: gate_geometry(g, tables_root)),
            ('⑤', '出图 build.py', lambda g: gate_build(g, tables_root, scratch)),
            ('⑥', '回执 整树摘要', lambda g: gate_digest(g, tables_root)),
            ('⑦', '分层 layering.py', lambda g: gate_layering(g)),
            ('⑧', '卫生 hygiene.py', lambda g: gate_hygiene(g)),
            ('⑨', '审美 visual-spec §0.1（偏心/绕行/通道半径）',
             lambda g: gate_aesthetic(g, tables_root)),
            ('⑩', '等价 equiv（夹具 + 可观测行为逐字节）',
             lambda g: gate_equiv(g, scratch)),
            ('⑪', '材料链 · 漂移 · 取子集 pipeline-fixtures 夹具', lambda g: gate_drift(g)),
            ('⑫', 'API 面 api_audit（丢失 / 签名变更 = 0）', lambda g: gate_api(g))]
    for num, title, fn in plan:
        g = Gate(num, title)
        print(f'\n=== 门{num} {title} ===')
        try:
            fn(g)
        except Exception as e:                      # 仪器内部异常也算仪器故障，不冒充"门没过"
            g.broken(f'验收器内部异常（{type(e).__name__}: {e}）')
        for ln in g.lines:
            print('  ' + ln)
        if g.ok is None:
            print(f'  ⚠ 仪器故障：{g.reason}')
        elif not g.ok:
            print(f'  ✗ 未过：{g.reason}')
        gates.append(g)

    broken = [g for g in gates if g.ok is None]
    failed = [g for g in gates if g.ok is False]
    npass = len(gates) - len(broken) - len(failed)
    print('\n' + '─' * 56)
    for g in gates:
        print(f'  {g.mark} 门{g.name} {g.title}'
              + (f'   {g.reason}' if g.ok is not True else ''))
    print(f'十二道门：{npass} 过 / {len(failed)} 未过 / {len(broken)} 仪器故障')
    missing = tables_is_missing(tables_root) if broken else ''
    if missing:
        print(f'  ⚠ {len(broken)} 道门无法裁决，根因是同一件事：{missing}')
    if broken:
        code = 2
        verdict = '仪器故障——结论不可信（先把"没跑成"修掉，再谈门过不过）'
    elif failed:
        code = 1
        verdict = '有门未过，未收口'
    else:
        code = 0
        verdict = '十二道门全过'
    print(f'退出码 {code}：{verdict}')
    # 收尾（2026-09-19 改，D-113）：**结论先印完，清理不参与判分**。三条不变的原则照旧——
    #   ① 不"先删再建"（撞批量删除的安全钩子）；② 退出码只由十二道门决定；③ 没过就留现场。
    # 改的只有一条：**过了就收掉"本次新建的"那几项**。原先写着"不替你删"，可它没有配套的收口——
    # 实测每跑一次留 5.7 MB / 140 个文件（门⑤ 的 build-* 副本），连跑十几轮攒到 134 MB / 2579 个文件，
    # 而没人会想起来清。`ignore_errors=True`：删不掉（被占用 / 权限）只多印一行，绝不改结论。
    made = [p for p in sorted(scratch.iterdir()) if p.name not in before]
    mb = sum(_bytes_of(p) for p in made) / 1048576
    if code == 0 and not a.keep and not a.scratch:
        for p in made:
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        left = [p.name for p in made if p.exists()]
        print(f'（临时现场：本次新建 {len(made)} 项 / {mb:.1f} MB —— '
              + (f'已收 {len(made) - len(left)} 项' if not left
                 else f'⚠ {len(left)} 项没删掉：{"、".join(left)}')
              + '；门全过想留现场加 `--keep`）')
    else:
        why = ('有门未过 / 仪器故障 ⇒ 现场留着看' if code else
               ('--keep' if a.keep else '`--scratch` 是你给的目录'))
        print(f'（临时现场：本次新建 {len(made)} 项 / {mb:.1f} MB —— {why}；'
              f'要腾空间跑 `python dev/tools/sweep.py`）')
    return code


if __name__ == '__main__':
    sys.exit(main())
