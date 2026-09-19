# -*- coding: utf-8 -*-
"""contract.py — 面①：契约一致性。文档说的与代码做的是不是同一件事。

四类检查：
  1 frontmatter（name 与目录名一致、description 可用）
  2 文档引用的文件路径都存在；面向用户的资源（references/、templates/）都有文档出处
  3 文档里的命令行参数都在对应脚本的 argparse 里
  4 visual-spec 的参数表逐值与 dictionary.yaml 一致；门禁编号与检查项数对得上
"""
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import EXAMPLES, SCRIPTS, SKILL, Case  # noqa: E402

# SKILL.md 里说「scripts/ 只执行命令，不读源码」，所以脚本内部实现层不要求文档出处；
# 但 references/ 与 templates/ 是给人读的资源，必须能从 SKILL.md 找到。

# 决策日志是历史记录，**必须能原样引用当年说过的话**（旧术语、旧举例、被否决的方案）。
# 术语断言扫全部 md，所以对它豁免——不豁免就等于要求历史记录改写自己的引文。
HISTORY_DOCS = {'DECISIONS.md'}


def _mds():
    """产品文档集（SKILL.md / README / DECISIONS / examples/README / references / templates）。

    用 `rglob` 拿全集，但**剔掉非产品目录**：`.verify_tmp/` 与 `.accept_tmp/`（两者的验证/验收现场，
    全过本会删、有失败才留，但 `accept.py` 有意保留现场供事后翻）、`output/`（本地产物目录，
    见 .gitignore——里面的 `flowtable.md` 是用户建流程时的**生成物**、不是产品文档）、
    `dev/tools/`（开发工具，如函数依赖图分析器）与 `archive/`（从市场克隆的第三方 skill 原文，
    供 D-55 评查，**2026-09-15 从 `参考资料/` 改名而来**——旧名与本产品的 `references/` 太像，
    容易混；它整块与产品运行时无关）。
    那些目录里的 md 性质是"记录现状 / 复现缺陷 / 生成物 / 开发工具文档 / 他人产品文档"，
    天然会带旧术语、裸代码块、领域词、指向自己包内的相对路径——用产品文档的规矩去卡它们，
    只会逼着人删掉一手记录；开发工具目录还会随并行工作反复增删，扫它等于让别人的半成品
    来决定本套件的红绿。`output/` 更直接：它的内容由本套件**自己的产物**生成，扫它等于让
    产物反过来决定本套件的红绿。**实测踩过**：`.accept_tmp/` 没进这张表时，`accept.py` 一跑，
    它生成的 self-boot 流程表就被当成产品文档，面①当场红在"H1–H9"那条断言上。

    D-66 起多了一个 `dev/`：`DECISIONS.md` / `ARCHITECTURE.md` / `REPO-MAP.md` 与
    `dev/verify/` `dev/tools/` 都搬了进去，那是**维护文档不是产品文档**——它对领域词与术语两条断言
    是豁免的（`DECISIONS.md` 按设计要能原样引用当年的旧词与旧举例，见 HISTORY_DOCS），
    扫进来只会把这些记录逼成不实陈述。
    """
    skip = {'.verify_tmp', '.accept_tmp', '__pycache__', '.git', '.workbuddy', 'output', 'dev'}
    return {p: p.read_text(encoding='utf-8') for p in sorted(SKILL.rglob('*.md'))
            if not (set(p.relative_to(SKILL).parts) & skip)}


def _code_prose(path):
    """一个 `.py` 里的**散文部分**：注释 + 各级文档串（**不含字符串字面量**）。

    只扫散文是有意的：字面量里有大量不是路径的字符串（产物名模板、配置键、正则），
    扫它们只会造假红；注释与文档串才是"写给人看的引用"，也正是会指空的那一类。
    """
    src = Path(path).read_text(encoding='utf-8')
    out = []
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d:
                    out.append(d)
    except SyntaxError:
        pass
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.append(tok.string)
    except tokenize.TokenError:
        pass
    return out


def _flags(script):
    tree = ast.parse((SCRIPTS / script).read_text(encoding='utf-8'))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'add_argument':
            for a in node.args:
                if isinstance(a, ast.Constant) and str(a.value).startswith('-'):
                    out.add(a.value)
    return out


def run_face(tmp=None):
    c = Case('面① 契约一致性')
    mds = _mds()
    skill_md = (SKILL / 'SKILL.md').read_text(encoding='utf-8')

    c.section('frontmatter')
    fm = re.match(r'^---\n(.*?)\n---\n', skill_md, re.S)
    if not c.check(bool(fm), 'SKILL.md 有 frontmatter'):
        return c
    name = re.search(r'^name:\s*(\S+)', fm.group(1), re.M)
    desc = re.search(r'^description:\s*(.+)$', fm.group(1), re.M)
    c.check(name and name.group(1) == SKILL.name, 'name 与目录名一致',
            f'name={name.group(1) if name else "?"} 目录={SKILL.name}')
    d = (desc.group(1).strip() if desc else '')
    # 上限取《SKILL 最佳设计指南》4.6 的 100 字符（原为 120）。理由不只是"短"：
    # 技能列表按字符预算截断，**触发词落在前 50 字符内**才保证截断后仍被认出。
    # 实测原描述 111 字，`流程图` 要到第 27 字才出现——压到 95 字后触发词更靠前。
    c.check(0 < len(d) <= 100, 'description 非空且 ≤100 字', f'{len(d)} 字')

    c.section('文档引用的路径都存在')
    # 前缀组含 `dev`：D-66 起 dev/verify/tools 与三份设计文档住 `dev/`，文档会写 `dev/verify/run.py`
    # 这种路径；不认它，引用的路径就查不到（这条`正则`是"文档说的文件真的在"的唯一守卫）。
    # **前缀组也含 `tools`/`verify`**：搬迁之后旧写法（裸 `dev/tools/fn_graph.py`）整批失去守卫——
    # 实测 ARCHITECTURE / REPO-MAP / README 一共 34 处照旧写着搬迁前的路径，而这条断言恒绿。
    # 认了它，旧写法当场变成"引用的路径不存在"，正是我们要的。
    pat = re.compile(r'(?:flowchart-skill/)?(scripts|references|templates|examples|dev|tools|verify)'
                     r'/[\w\-./\u4e00-\u9fff]+\.(?:py|md|yaml|drawio|html)')
    # 扫的范围比 `_mds()` 宽：路径是否真实在，与"是不是产品文档"无关（dev/ 的维护文档同样会
    # 指错路）。**历史文档除外**：它按设计要保留当年的旧路径与旧目录名（HISTORY_DOCS）。
    docs_all = {p: p.read_text(encoding='utf-8') for p in sorted(SKILL.rglob('*.md'))
                if not (set(p.relative_to(SKILL).parts)
                        & {'.verify_tmp', '.accept_tmp', '__pycache__', '.git', '.workbuddy', 'archive', 'old'})
                and p.name not in HISTORY_DOCS}
    seen = {}
    for p, t in docs_all.items():
        for m in pat.finditer(t):
            rel = re.sub(r'^flowchart-skill/', '', m.group(0))
            seen.setdefault(rel, set()).add(p.relative_to(SKILL).as_posix())
    missing = sorted(r for r in seen if not (SKILL / r).exists())
    c.check(not missing, f'{len(seen)} 个引用路径全部存在（含 dev/ 维护文档）',
            '；'.join(f'{r} ← {sorted(seen[r])[0]}' for r in missing[:3]))

    c.section('代码注释里的引用路径都存在')
    # 上面那条只扫 `.md`；**代码注释与文档串里的引用没人看**，而 D-66 搬迁后实测有 15 处仍写着
    # `tools/…` / `verify/…`（读者照着它去找文件，扑空）。判据与上面同一套正则。
    codemiss = {}
    for p in sorted(list(SCRIPTS.glob('*.py')) + list((SKILL / 'dev').rglob('*.py'))):
        if '__pycache__' in p.parts:
            continue
        for piece in _code_prose(p):
            for m in pat.finditer(piece):
                rel = re.sub(r'^flowchart-skill/', '', m.group(0))
                if any(ch in rel for ch in '*<>…'):
                    continue                  # 通配符 / 占位符写法（`scripts/<模块>.py`）：不是具体引用
                if not (SKILL / rel).exists():
                    codemiss.setdefault(rel, set()).add(p.relative_to(SKILL).as_posix())
    c.check(not codemiss, '代码注释与文档串里的引用路径都存在',
            '；'.join(f'{r} ← {sorted(codemiss[r])[0]}' for r in sorted(codemiss)[:3]))

    c.section('文档提到的 .md 都在包里')
    # 上一条的正则要求带目录前缀，`见 XXX.md §4.1` 这种**裸文件名**漏过——实测漏过一次：
    # `DESIGN-lane-slot.md` 被引用 8 处却不在包里，槽位算法的落点直接悬空，代码里的"细则见某文档"
    # 也就无处可查。例外只有生成物名：仓库里不必有它们。
    GENERATED = {'checklist.md'}
    known = {q.name for q in SKILL.rglob('*.md')}
    dangling = []
    for p, t in mds.items():
        for m in re.findall(r'`([A-Za-z0-9_\-]+\.md)`', t):
            if m not in known and m not in GENERATED:
                dangling.append(f'{p.name}:{m}')
    c.check(not dangling, '文档提到的 .md 都在包里', '；'.join(sorted(set(dangling))[:4]))

    c.section('面向用户的资源都有文档出处')
    orphan = []
    for sub in ('references', 'templates'):
        for f in sorted((SKILL / sub).iterdir()):
            if f.name not in skill_md:
                orphan.append(f'{sub}/{f.name}')
    c.check(not orphan, 'references/ 与 templates/ 均在 SKILL.md 里出现', '；'.join(orphan))

    c.section('命令行参数与 argparse 一致')
    badflag = []
    for p, t in mds.items():
        for line in t.splitlines():
            m = re.search(r'([\w\-]+\.py)\s+([^\n`|]*)', line)
            if not m or not (SCRIPTS / m.group(1)).exists():
                continue
            allowed = _flags(m.group(1))
            for tok in re.findall(r'(?<!\S)(--?[A-Za-z][\w-]*)', m.group(2)):
                if tok not in allowed:
                    badflag.append(f'{m.group(1)} 不支持 {tok}')
    c.check(not badflag, '文档里的参数都真实存在', '；'.join(badflag[:3]))

    c.section('参数表与 dictionary.yaml 逐值一致')
    cfg = yaml.safe_load((SCRIPTS / 'dictionary.yaml').read_text(encoding='utf-8'))
    leaf = {}

    def walk(d, pre=''):
        for k, v in d.items():
            if isinstance(v, dict):
                walk(v, f'{pre}{k}.')
            else:
                leaf[f'{pre}{k}'] = v
    walk(cfg)
    spec = (SKILL / 'references' / 'visual-spec.md').read_text(encoding='utf-8')
    i = spec.index('| 参数 | 默认 | 作用 |')
    rows = []
    for line in spec[i:].splitlines():
        if not line.startswith('| `'):
            if rows:
                break
            continue
        rows.append([x.strip() for x in line.strip('|').split('|')])
    mism = []
    for cells in rows:
        nums = re.findall(r'\d+(?:\.\d+)?', cells[1])
        names = re.findall(r'`([^`]+)`', cells[0])
        base, resolved, wilds = None, [], []
        for nm in names:
            if '.' in nm:
                base = nm.rsplit('.', 1)[0]
                key = nm
            else:
                key = f'{base}.{nm}' if base else nm
            wild = '*' in key
            key = key.replace('.*', '').replace('*', '')
            hit = [v for k, v in leaf.items()
                   if k == key or k.startswith(key + '.') or (wild and k.startswith(key))]
            resolved.append(hit)
            wilds.append(wild)
        # 通配名（如 shapes.*.size）解析为空是合法的，另行人工核对；
        # 但非通配的名字一个都匹配不到 = 文档写了字典没有的东西——continue 掉就是漏检盲区
        lost = [nm for nm, r, w in zip(names, resolved, wilds) if not r and not w]
        if lost:
            mism.append(f'{cells[0]}：字典中找不到 {lost}')
            continue
        if any(not r for r in resolved):
            # 有解析为空的（多为通配符）：整行 continue 会把**同行的具体参数**一起放过——
            # 那正是默认值漂移最该被看见的地方。集合比对做不了（数字对不上是谁的），
            # 但具体项可以逐个做成员检查：字典里写了 60、文档默认列里没有 60，就是漂移。
            if nums:
                for nm, r, w in zip(names, resolved, wilds):
                    if w or not r:
                        continue
                    for v in r:
                        if isinstance(v, bool) or not isinstance(v, (int, float)):
                            continue
                        if str(v) not in nums:
                            mism.append(f'{cells[0]}：{nm} 的字典值 {v} 不在文档默认 {nums} 里')
            continue                                   # 空解析本身合法（通配），不算不一致
        # 布尔不算"数值参数"：字典里写 true/false 的开关项，文档行不必带数字。
        # （Python 里 bool 是 int 的子类，不排除的话会得到 flat=['True'] 这种伪数值。）
        flat = [str(v) for r in resolved for v in r
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(resolved) == len(nums) and all(len(r) == 1 for r in resolved):
            ok = all(nums[i] == str(resolved[i][0]) for i in range(len(nums)))
        else:
            ok = sorted(nums) == sorted(flat)
        if not ok:
            mism.append(f'{cells[0]}：文档 {nums} ≠ 字典 {flat}')
    c.check(not mism, f'参数表 {len(rows)} 行与字典一致', '；'.join(mism[:3]))

    # 同一件事的第二面：**代码里的兜底常量**不许自成一套数。`cfg.get('legend_band', 110)` 这种写法
    # 把同一个数写了两遍，而字典改了、代码兜底不改时**没有任何症状**——实测漂过两处（110 vs 80、
    # 20 vs 16），两次都是"只在字典改一半"的静默错值。判据只认**唯一同名**的字典叶：同名多处
    # （如 `gap` 在 lane / grid 下各一处）时无法判定是谁的，跳过不报，避免造出假红。
    drift = []
    for p in sorted(SCRIPTS.glob('*.py')):
        tree = ast.parse(p.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get' and len(node.args) == 2):
                continue
            k, dflt = node.args
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and isinstance(dflt, ast.Constant) and not isinstance(dflt.value, bool)
                    and isinstance(dflt.value, (int, float))):
                continue
            same = [v for kk, v in leaf.items()
                    if kk.rsplit('.', 1)[-1] == k.value and isinstance(v, (int, float))
                    and not isinstance(v, bool)]
            if len(same) == 1 and float(same[0]) != float(dflt.value):
                drift.append(f'{p.name}:{node.lineno} `{k.value}` 兜底 {dflt.value} ≠ 字典 {same[0]}')
    c.check(not drift, '代码里的字典兜底常量与 dictionary.yaml 同值（兜底不许自成一套数）',
            '；'.join(drift[:3]))

    c.section('门禁编号与检查项数')
    # H 编号是给用户看的规则主题，它的家是 flowtable-spec 第 3 节的三张表。
    # 以前这条断言盯着 table_to_dsl.py 的 docstring，等于**逼代码抄一份规则表**——
    # 代码里的重复就是这么来的。改盯文档；代码侧只要求三层函数与统一入口还在。
    spec_t = (SKILL / 'references' / 'flowtable-spec.md').read_text(encoding='utf-8')
    # H 编号是**两位以内**的（H10 一度让这条断言"看着变红"：它抓的是单个数字字符）。
    # 判据改成"从 H1 连续到最大的那个编号"，加 H11 时只需在文档里写出来。
    nums = sorted({int(n) for n in re.findall(r'\bH(\d{1,2})\b', spec_t)})
    c.check(nums == list(range(1, len(nums) + 1)) and nums[-1] >= 9,
            'flowtable-spec 里的 H 编号从 H1 连续到 H10',
            f'实际 {["H" + str(n) for n in nums]}')
    t2d = (SCRIPTS / 'flowtable_check.py').read_text(encoding='utf-8')
    layers = ['check_nodes', 'check_by_type', 'check_relations', 'run_checks']
    miss = [f for f in layers if f'def {f}(' not in t2d]
    c.check(not miss, '三层函数 + 统一入口仍在 flowtable_check.py', '缺 ' + '、'.join(miss))
    import validate
    c.check(len(validate.CHECK_NAMES) == 8, '质量门禁是八项', f'{len(validate.CHECK_NAMES)} 项')
    for p, t in mds.items():
        m = re.search(r'H1[–\-~]H(\d)', t)
        if m and m.group(1) != '8':
            c.check(False, f'{p.name} 把结构校验写成 H1–H{m.group(1)}')

    c.section('产物侧判据与文档一致')
    # 产物侧复核是**契约**（visual-spec §4.1 写清查什么 / 不查什么 / 不过就阻断）。清单钉在
    # `validate.ARTIFACT_RULES` 里，两处文档逐名核到——改了判据没改文档，读者会以为它只管那六项。
    rules = list(validate.ARTIFACT_RULES)
    c.check(len(rules) == 9, '产物侧判据是九项（六项通用 + 微残段 + 泳道两条）', f'{len(rules)} 项')
    vs = (SKILL / 'references' / 'visual-spec.md').read_text(encoding='utf-8')
    miss = [r for r in rules if r not in vs or r not in skill_md]
    c.check(not miss, 'visual-spec 与 SKILL.md 都写到了每条产物判据', '；'.join(miss))
    for phrase in ('不查什么',                     # 边界要写明，否则读者以为它能兜住标签
                   '标签盒不在产物',               # 唯一"不在产物侧做"的那一项
                   '还原'):                        # 不过就阻断：产物要还原，不留半成品
        c.check(phrase in vs, f'visual-spec §4.1 写清了「{phrase}」')
    c.section('术语一致性：改名后不许漂回旧词')
    # 这套术语是有意统一的：「门禁」只留给真阻断点（结构校验 / 质量门禁），
    # ②③ 按性质叫自检留痕 / 同步闭环。旧词留着会让读者以为 SKILL 有三道阻断门。
    BANNED = ('门禁①', '门禁②', '门禁③', '门禁 ①', '门禁 ②', '门禁 ③',
              '三道门禁', '结构硬校验', '待确认清单', '数值门禁')
    hits = []
    for p, t in _mds().items():
        if p.name in HISTORY_DOCS:
            continue                      # 历史文档要引用旧词，见 HISTORY_DOCS 上方注释
        for term in BANNED:
            if term in t:
                hits.append(f'{p.name}:{term}')
    for p in sorted(SCRIPTS.glob('*.py')):
        t = p.read_text(encoding='utf-8')
        for term in BANNED:
            if term in t:
                hits.append(f'{p.name}:{term}')
    c.check(not hits, '文档与脚本里无废弃术语', '；'.join(hits[:5]))

    c.section('决策日志：只记改过主意的事，且每条有编号')
    # 决策历史的家是 `dev/DECISIONS.md`（D-66 起它与 ARCHITECTURE / REPO-MAP 一起住 dev/）。
    # 没有这个文档，被否决过的方案会被下一个会话重新提议一遍；有了它，
    # 代码里的 why-not 注释可以只写一句"见 D-xx"。
    # **指针挂在 README 而不挂 SKILL.md**：SKILL.md 是"出图"的调度层，读它的 AI 不需要
    # 知道仓库怎么维护（见 SKILL.md 目录表末的说明）。维护入口统一在 README「改完东西跑自检」。
    dp = SKILL / 'dev' / 'DECISIONS.md'
    if c.check(dp.exists(), 'DECISIONS.md 存在'):
        dt = dp.read_text(encoding='utf-8')
        ids = re.findall(r'^## (D-\d\d) ', dt, re.M)
        c.check(len(ids) == len(set(ids)), 'D 编号不重复', f'{len(ids)} 条')
        c.check(ids == sorted(ids), 'D 编号按序排列', f'{ids[:3]}…')
        ents = re.split(r'^## D-\d\d ', dt, flags=re.M)[1:]
        over = [ids[i] for i, e in enumerate(ents) if len(e.rstrip().splitlines()) > 16]
        c.check(not over, '每条决策 ≤16 行（是日志不是公案）', '超长 ' + '、'.join(over))
        rd = _mds()[SKILL / 'README.md']
        c.check('DECISIONS.md' in rd, 'README 里能找到 DECISIONS.md')

        # 指针不许指空：实测发生过——两个模块的注释里 6 处指向一个从未写过的编号，
        # 而 DECISIONS.md 从那前后直接跳号。读者照着编号去翻，翻不到任何东西。
        # "编号不重复""按序排列"两条都管不了这种缺口，所以单加这一条。
        refs = {}
        srcs = [(p, t) for p, t in _mds().items() if p.name != 'DECISIONS.md']
        srcs += [(p, p.read_text(encoding='utf-8'))
                 for p in sorted(list((SKILL / 'scripts').glob('*.py'))
                                 + list((SKILL / 'dev').rglob('*.py')))]
        for p, t in srcs:
            for m in re.findall(r'D-\d\d', t):
                refs.setdefault(m, set()).add(p.name)
        missing = sorted(k for k in refs if k not in set(ids))
        c.check(not missing, '被引用的 D 编号都存在（指针不许指空）',
                '；'.join(f'{k} ← {"、".join(sorted(refs[k])[:3])}' for k in missing))

    c.section('调度层不掺维护内容')
    # 指南《SKILL 最佳设计指南》第四部分：SKILL.md 是**调度员**，只写出图要走的流程。
    # 维护动作（跑自检、读决策日志、看模块地图）对出图毫无用处，却要和流程争注意力——
    # 实测过一次：这些行原本混在 SKILL.md 的目录表里，而 `scripts/*.py` 对它们**零依赖**
    # （那 7 处 `ARCHITECTURE.md` 全是注释指针，不是 import）。所以钉成断言，别再漂回来。
    # 判据只看"指向仓库维护产物的引用"，不禁止提到文件名本身（正文讲设计理由时会被引用）。
    sk = _mds()[SKILL / 'SKILL.md']
    DEV = ('dev/verify/run.py', 'dev/verify/README.md', 'DECISIONS.md',
           'REPO-MAP.md', 'dev/tools/fn_graph.py', 'dev/tools/fn-graph.json')
    leak = [t for t in DEV if t in sk]
    c.check(not leak, 'SKILL.md 只写出图流程，不掺维护指令', '；'.join(leak))

    c.section('.gitignore 存在且盖住已知派生量')
    # 这个文件在发布的包里**丢失过**，而 `dev/tools/accept.py`(6 处)、`dev/verify/run.py`、本文件都在
    # 引用它声称的口径（"`output/` 与 `dev/tools/fn-*.json` 都在 .gitignore 里"）——"代码里写着、
    # 实际没有"正是 D-63 记过的那类缺陷。所以把它钉成断言，别再悄悄丢。
    # 判据只覆盖**代码已声明**的那几项；不越界规定"还该忽略什么"（那是仓库策略，不是契约）。
    gi = SKILL / '.gitignore'
    if c.check(gi.exists(), '.gitignore 存在（代码多处引用它）'):
        gt = gi.read_text(encoding='utf-8')
        NEEDED = {
            '__pycache__/': '字节码缓存——按文档跑 `scripts/build.py` 就会长（实测）',
            'output/': '出图产物目录（用户产物，不是仓库内容）',
            '.verify_tmp/': '验证现场',
            'dev/tools/fn-graph.json': '依赖图快照（accept.py 门②专门判它是否过期）',
        }
        miss = [k for k in NEEDED if k not in gt]
        c.check(not miss, '已知派生量都在 .gitignore 里',
                '缺 ' + '、'.join(miss) if miss else '')

    c.section('入口命令都要重设 stdout 编码')
    # 入口命令会打印 ✓ / ✗ / ⚠ 与中文，而 Windows 控制台默认 GBK（CP936）——不重设就在
    # **打印成功信息这一行**抛 UnicodeEncodeError，进程退 1，而产物其实已经写好了。
    # 实测过一次：`shot.py` 截图成功、PNG 落盘，却因末行 `print('✓ 已截图…')` 崩掉，
    # e2e 的「截图自检可用」因此长期报红（`-X utf8` 即通过）。这个失败模式极难归因
    # ——报错栈指着成功路径，特征与"浏览器没起来/没出图"完全不像。
    # 判据是"有 `__main__` 的模块"，不设例外：`render_svg` 看着只打印半角 `生成: …`，
    # 但它的错误分支打印 `✗ 找不到输入文件`，同一条坑照样踩得到（故一并补齐）。
    # reconfigure 必须在入口模块里：它改的是本进程的 stdout，不是被 import 的库行为。
    noenc = [p.name for p in sorted(SCRIPTS.glob('*.py'))
             if 'if __name__' in p.read_text(encoding='utf-8')
             and 'stdout.reconfigure' not in p.read_text(encoding='utf-8')]
    c.check(not noenc, '每个入口命令都重设了 stdout 编码',
            '缺 ' + '、'.join(noenc) if noenc else '')

    c.section('泛化性：产品文档里不许出现具体领域')
    # 本 SKILL 不预设任何业务领域。产品文档（SKILL.md / references / templates）一旦举了某个领域的例子，
    # 读者会反推"这是给那个领域用的"，还会把该领域的结构预设（主体形态、环节构成）带进别的场景。
    # 示例一律取自 examples/workflow/（自举）——它是唯一预置样例。examples/ 里不放真实业务样例：
    # 任何具体领域当范例都会把该领域的结构预设带进别的场景。
    DOMAIN = ('光伏', '踏勘', 'EPC', '珈伟', '怡亚通', '怡云智', '逆变器', '并网',
              '投决', '质保金', '消纳', '配电房', '无人机', '外勤', '施工合伙人', '甲方', '乙方')
    docs = [SKILL / 'SKILL.md']
    docs += sorted((SKILL / 'references').glob('*.md'))
    docs += sorted((SKILL / 'templates').glob('*.md'))
    leak = []
    for p in docs:
        t = p.read_text(encoding='utf-8')
        for term in DOMAIN:
            if term in t:
                leak.append(f'{p.name}:{term}')
    c.check(not leak, '产品文档无领域词（示例只取自自举）', '；'.join(leak[:6]))

    c.section('注释归属：文档已有的理由不许抄进代码')
    # 用户 2026-09-10 的两次反馈合起来定下了这件事的边界：
    #   1. 脚本注释占 18.8%，而最大的一笔不是"解释代码"，是**把文档讲过的理由又抄了一遍**。
    #   2. "你用脚本检查注释是否冗余，我不认同"——**体积不是冗余**。机械指标分不出
    #      "必须留的 why-not"和"该走的叙事"，当裁判会让"删掉有用注释去凑指标"变成正确做法。
    # 所以这里只留**归属**这一条（可机械判定、且不会误伤）：文档级表述不许出现在脚本里；
    # "是否冗余"由定期的人工/子代理通读判断（判据：删掉它，下一个 AI 会不会做出错误的"改进"？）。
    DOC_ONLY = ('高级 mermaid',           # 产品定位，家在 SKILL.md
                '分层不是为了好看')        # 三层理由，家在 flowtable-spec.md 第 3 节
    dup = []
    for p in sorted(SCRIPTS.glob('*.py')):
        t = p.read_text(encoding='utf-8')
        for term in DOC_ONLY:
            if term in t:
                dup.append(f'{p.name}:{term}')
    c.check(not dup, '文档级表述没被抄进脚本', '；'.join(dup))

    c.section('Markdown 格式：代码块必须标语言')
    # 不标语言的代码块会被高亮器猜错，且渲染成一片灰——这是纯格式债，一次修干净就该守住。
    no_lang = []
    for p, t in _mds().items():
        in_f = False
        for i, l in enumerate(t.split('\n'), 1):
            if l.strip().startswith('```'):
                if not in_f and not l.strip()[3:].strip():
                    no_lang.append(f'{p.name}:{i}')
                in_f = not in_f
    c.check(not no_lang, '所有代码块都标了语言', '；'.join(no_lang[:5]))

    c.section('格式基准：workflow 必须被标为规范范例')
    # 用户明确要求「用自举描述这个 SKILL 并作为典型与规范」——别让它在文档里掉队。
    # 样例目录 2026-09-15 由 `self-demo` 更名为 `workflow`（D-66）：旧名与本仓的
    # `output/self-boot/`（代码地图）撞了"自举"二字，读者分不清谁画什么。
    sk = _mds()[SKILL / 'SKILL.md']
    rd = _mds()[SKILL / 'examples' / 'README.md']
    c.check('examples/workflow/' in sk, 'SKILL.md 指向 examples/workflow')
    c.check('格式基准' in rd, 'examples/README 明说 workflow 是格式基准')
    # 有样例就得在 README 里交代清楚：加了一个样例却没写说明，读者不知道该照着谁写。
    for q in sorted(EXAMPLES.glob('*/flowtable.md')):
        c.check(q.parent.name in rd, f'examples/{q.parent.name} 在 examples/README 里有说明')

    c.section('格式基准：模板示例必须逐字等于 workflow')
    # 模板自称"范本，逐字等于 examples/workflow/flowtable.md"。改了一边而没改另一边，
    # 这句话就变成不实陈述——而"不实的说明"比没有说明更会误导。所以钉死。
    def _tbl(p):
        # 三区结构（D-59）后文件里有渲染配置/主体配色等别的表——逐字比较只看「## 流程表」小节
        t = Path(p).read_text(encoding='utf-8').split('\n')
        start = next((i for i, l in enumerate(t) if l.strip() == '## 流程表'), None)
        if start is None:
            return ['!missing-flowtable-section']
        return [l for l in t[start + 1:]
                if l.startswith('| ') and not l.startswith('| 项目运作阶段') and not l.startswith('| ---')]
    tpl = _tbl(SKILL / 'templates' / 'flowtable-template.md')
    demo = _tbl(EXAMPLES / 'workflow' / 'flowtable.md')
    c.check(tpl == demo, '模板示例与 workflow 逐字一致',
            f'模板 {len(tpl)} 行 / workflow {len(demo)} 行' if tpl != demo else '')
    return c


if __name__ == '__main__':
    sys.exit(0 if run_face(SKILL / '.verify_tmp').summary() else 1)
