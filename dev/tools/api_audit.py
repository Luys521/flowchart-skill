#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""api_audit.py — 函数面静态审计：原有的函数名/签名/嵌套关系一个都没丢、也没被偷偷改名。

## 为什么需要它（和 `dev/tools/equiv.py` 什么关系）
这轮重构把大函数拆成一串私有阶段函数、并把若干嵌套函数提升为模块级，新增了上百个函数。
`equiv.py` 证明的是「**跑过的路径**行为逐字节没变」——它自己列的第 1、2 条边界就是：
**没被用例触发的分支等于没验**，而且它不判断「代码逻辑是否等价」。
所以还需要一条**互补**的证据：**原有的函数名 / 参数面 / 嵌套关系一个都没丢，也没被偷偷改名**。
本工具只回答这一件事。

> **两个工具互补，不许互相替代。**
> 本工具是**静态**审计：它只读 AST，不跑代码。它**不回答**「行为是否相同」（那由 `equiv.py` 负责），
> 也不回答「新函数写得对不对」。反过来，`equiv.py` 跑不到的分支本工具也管不了。

## 四类判据（必须分开看，严重程度不同）
1. **丢失** `底本有 x、工作树没有 x`，且同文件内**找不到**对应新函数 → **严重**。这就是「功能丢了」。
2. **改名** `底本有 x、工作树没有 x，但**同一文件**内多出 y`，y 就是 x 的新名字 → **不计入失败**
   （但必须人看一眼）。按函数体贴近程度分两档：
   - **精确档**：函数体归一化后**逐字符相同** → 就是改名，没有别的解释；
   - **近似档**：函数体比值 `≥ --near`（默认 0.75）→ 这是**嵌套函数提升**的典型形态：原函数用到的
     闭包变量、外层局部量在提升后必须变成显式参数，函数体因此必然变；再加上重构要求新函数带
     docstring、递归调用要改成新名。三样叠加，精确指纹必然配不上，所以只能判「疑似」，
     **把比值印出来**供人复核。
   为什么近似档要单列、而不是继续算「丢失」：本仓全量对照时这 3 条近似配对的比值是
   **0.851 / 0.991 / 0.987**，而它们的**次优候选只有 0.227 / 0.096 / 0.137**——间距极大，
   说明判据不是勉强凑的。把它们报成「严重·丢失」是**假警报**，而假警报会让「严重」这个词失效。
3. **签名变更** `同名函数，但参数面变了`（参数名序列 / 默认值存在性 / `*args`·`**kwargs` 名 / kind）
   → **严重**。调用方是照旧签名写的，改签名会静默改行为或直接崩。
4. **新增** `工作树多出来的` → 只计数 + 列名单，**不影响退出码**。这轮重构的预期产物。
   （已被「改名」配掉的不重复计入新增。）

**函数体「归一化后完全相同」的口径**：`ast.dump(..., include_attributes=False)`——
必须**剥掉行号列号**，否则任何代码移动都会让"函数体相同"判成不同（这轮重构全是移动代码）。
并且**忽略正文首句文档字符串**：重构要求新函数都带 docstring，把嵌套函数原样提上来时
函数体只多了这一句，不该因此判成"丢了"。只 dump 函数体、**不含函数名**，否则"改了名"本身
就会让指纹不同，改名永远配不上对。

**为什么改名不算失败**：这轮重构**预期**就会改名（嵌套函数提升为模块级是硬要求，例如
`parse_next_raw.resolve` → `_resolve_target`）。把改名计入失败，工具会在正常的重构上永远报红，
于是没人再看它——那才是真正的失败。但「疑似」二字要落实：配对只按函数体比值做，可能误配，
所以报告里必须显著列出配对与比值，供人复核。
**不配对的改名**（名字和函数体都变了、或函数体被拆进别的函数）会落进「丢失」——那是给人看的信号，
不是假警报。

**配对只在同一文件内做**：跨文件同名太多（`path`、`width`、`height`、`rect`…），跨文件配对会造出
一堆假配对，比不配对更坏。

## 判不了的情形（诚实边界）
- **函数被拆成两个、名字都变了**：函数体指纹必然不同、比值也会掉到阈值以下 → 落进「丢失 + 新增」，
  本工具说不出它们是同一段代码。（这正是「丢失」需要人复核而非机器定罪的原因。）
- **函数体只改了一行**：精确档是逐字符比对，改一个常量就不再"精确"；但通常仍落在近似档（比值很高），
  所以报告里那句"请复核"不能省。
- **近似档本身是启发式**：删掉一个函数、同时新增一个**高度相似**的函数，会被判成"疑似改名"而非"丢失"。
  比值与新增名单都会印出来，可复核；`--near` 可调（调高更严，调到 1.0 就只剩精确档）。
- **参数注解、返回注解、装饰器、`global`/`nonlocal` 声明**：**不参与比对**（本轮约定「不加类型注解」，
  所以故意不比注解：加了注解不算签名变更。这是取舍，不是遗漏）。
- **参数顺序之外的语义变化**：默认值**内容**改了（`=1`→`=2`）只比「有没有」，不比值。
- **不是函数的 API 面**：模块级常量、`__all__`、导出名、类属性、模块名本身（本轮有文件被改名/合并）。
- **行为**：完全不判。跑一个用例比它准得多（见 `equiv.py`）。

## 用法
    # 全仓对照：底本取 git 版本，工作树取现状
    python dev/tools/api_audit.py --rev api-base

    # 只审自己包里的几个文件（分包复核）
    python dev/tools/api_audit.py --rev api-base --file scripts/flowtable.py --file scripts/flowtable_check.py

    # 结构化输出（给 CI / 别的脚本消费）
    python dev/tools/api_audit.py --rev api-base --json

    # 底本改用一棵目录树（自测造 mutant 用；也用于比对两份 checkout）
    python dev/tools/api_audit.py --base-dir /tmp/base --root .

    # --base 是 --base-dir 的别名（与 dev/tools/equiv.py 的 --base 同义：都指"底本目录"）
    python dev/tools/api_audit.py --base /tmp/base --root .

    # 改名近似阈值可调（默认 0.75；调到 1.0 就只剩「函数体逐字符一致」的精确档，最严）
    python dev/tools/api_audit.py --rev api-base --near 1.0

退出码：**无「丢失」且无「签名变更」→ 0；否则 1；输入读不了（rev 不存在 / 目录找不到）→ 2。**
1 与 2 分开，是为了让「工具没跑起来」不被误读成「函数面坏了」。
"""
import argparse
import ast
import difflib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO  # noqa: E402

ROOT_DEFAULT = str(REPO)
REV_DEFAULT = 'api-base'
NEAR_DEFAULT = 0.75
SCRIPTS_DIR = 'scripts'
# 参与比对的「参数面」字段；kind 也在内：普通函数改成 async 同样是签名变更
SIG_FIELDS = ('kind', 'params', 'has_default', 'vararg', 'kwarg')


# ---------------------------------------------------------------- 读取两侧
def git(root, *args):
    """在 root 下跑 git → CompletedProcess（调用方按 returncode 决定语义）。"""
    return subprocess.run(['git'] + list(args), cwd=root, capture_output=True)


def rev_ok(root, rev):
    """rev 是否是个能解析的 git 版本（解析不了就是仪器故障，不是「函数丢了」）。"""
    return git(root, 'rev-parse', '--verify', '--quiet', rev).returncode == 0


def list_py(rel_dir, root):
    """某个目录下直接子级的 *.py（不递归；scripts/ 是平铺的）。"""
    d = Path(root) / rel_dir
    if not d.is_dir():
        return []
    return sorted(f'{rel_dir}/{p.name}' for p in d.iterdir() if p.is_file() and p.suffix == '.py')


def list_py_at_rev(root, rev, rel_dir):
    """某个 git 版本下该目录的 *.py（用 ls-tree，读不了就抛错）。

    注意 `git ls-tree <rev>:<dir>` 输出的是**相对该目录**的名字，必须补回目录前缀，
    否则会拿 `artifact.py` 去 `git show`（仓库根下没这个文件）而静默读成「两侧都没有」。
    """
    p = git(root, 'ls-tree', '--name-only', f'{rev}:{rel_dir}')
    if p.returncode != 0:
        raise RuntimeError(f'git ls-tree {rev}:{rel_dir} 失败: '
                           + p.stderr.decode('utf-8', 'replace').strip())
    return sorted(f'{rel_dir}/{x}' for x in p.stdout.decode('utf-8').split('\n')
                  if x.endswith('.py'))


def decode(raw):
    """字节 → 源码文本；剥掉 BOM（带 BOM 的 .py 直接 ast.parse 会炸在 \\ufeff 上）。"""
    return raw.decode('utf-8').lstrip('\ufeff')


def read_side(root, rel, rev=None):
    """读一侧的源码 → str；该侧没有这个文件返回 None（用于「本轮新增/删除的文件」）。"""
    if rev is None:
        p = Path(root) / rel
        return decode(p.read_bytes()) if p.is_file() else None
    r = git(root, 'show', f'{rev}:{rel}')
    if r.returncode != 0:
        return None
    return decode(r.stdout)


# ---------------------------------------------------------------- 函数面
def iter_funcs(tree):
    """遍历 AST → [(qualname, node, kind)]，按源码顺序。

    qualname 含类与嵌套路径（`Model.__init__`、`parse_next_raw.resolve`），这样"嵌套函数被提升到
    模块级"会在名字上直接现形。kind 取 `async` / `method`（直接挂在 class 体内）/ `function`；
    异步一律记 async（不再细分是否方法）。
    """
    out = []

    def walk(node, prefix, in_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, prefix + [child.name], True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(('.'.join(prefix + [child.name]), child,
                            'async' if isinstance(child, ast.AsyncFunctionDef)
                            else ('method' if in_class else 'function')))
                walk(child, prefix + [child.name], False)

    walk(tree, [], False)
    return out


def signature(node):
    """函数的「参数面」：参数名序列 + 每个参数的默认值存在性 + *args/**kwargs 名。

    参数顺序按「仅位置 → 普通 → *args → 仅关键字 → **kwargs」拼；默认值存在性与之对齐
    （`defaults` 只覆盖仅位置+普通参数的**尾部**，`kw_defaults` 用 None 表示"无默认"）。
    """
    a = node.args
    pos = list(a.posonlyargs) + list(a.args)
    names = [p.arg for p in pos] + [p.arg for p in a.kwonlyargs]
    has_def = ([False] * (len(pos) - len(a.defaults)) + [True] * len(a.defaults)
               + [d is not None for d in a.kw_defaults])
    return {'params': names, 'has_default': has_def,
            'vararg': a.vararg.arg if a.vararg else None,
            'kwarg': a.kwarg.arg if a.kwarg else None}


def body_key(node):
    """函数体的归一化指纹：剥行号、剥首句 docstring、**不含函数名**（见 docstring 的口径说明）。"""
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)


def collect(src):
    """源码 → {qualname: {kind, params, has_default, vararg, kwarg, body}}；语法错抛 SyntaxError。"""
    funcs = {}
    for qual, node, kind in iter_funcs(ast.parse(src)):
        sig = signature(node)
        sig.update(kind=kind, body=body_key(node))
        funcs[qual] = sig
    return funcs


# ---------------------------------------------------------------- 比对与分类
def sig_diff(old, new):
    """两个参数面的差异 → [(字段, 旧值, 新值)]。"""
    return [(k, old[k], new[k]) for k in SIG_FIELDS if old[k] != new[k]]


def pair_renames(lost_names, added_names, base_funcs, work_funcs, near):
    """在同文件内给丢失的名字找改名配对 → (配对列表, 仍算丢失的名字)。

    只跟**同文件**的「新增」名字比。取比值最高的候选：`>= near` 就算配对（精确档是其中 ratio==1.0
    的特例），否则仍算丢失。配对成功后把新名字从 added_names 里**消费掉**，两个丢函数不会配上同一个新函数。
    """
    pairs, still_lost = [], []
    for n in lost_names:
        best, best_ratio = None, 0.0
        for m in added_names:
            r = difflib.SequenceMatcher(None, base_funcs[n]['body'], work_funcs[m]['body']).ratio()
            if r > best_ratio:
                best, best_ratio = m, r
        if best is None or best_ratio < near:
            still_lost.append(n)
            continue
        added_names.remove(best)
        pairs.append({'from': n, 'to': best,
                      'exact': base_funcs[n]['body'] == work_funcs[best]['body'],
                      'ratio': round(best_ratio, 3)})
    return pairs, still_lost


def audit_file(rel, base_src, work_src, near):
    """审一个文件 → 结果 dict（含 lost / sig_changed / renamed / added / 两侧是否缺文件）。"""
    res = {'file': rel, 'in_base': base_src is not None, 'in_work': work_src is not None,
           'lost': [], 'sig_changed': [], 'renamed': [], 'added': []}
    if base_src is None or work_src is None:
        # 文件级增删：一侧没有 → 另一侧的函数面整体算「新增」或「丢失」
        funcs = collect(work_src if base_src is None else base_src)
        if base_src is None:
            res['added'] = sorted(funcs)
        else:
            res['lost'] = [{'name': n, 'body': funcs[n]['body']} for n in sorted(funcs)]
        return res
    base_funcs, work_funcs = collect(base_src), collect(work_src)
    lost_names = sorted(set(base_funcs) - set(work_funcs))
    added_names = sorted(set(work_funcs) - set(base_funcs))
    res['renamed'], still_lost = pair_renames(lost_names, added_names, base_funcs, work_funcs, near)
    res['lost'] = [{'name': n, 'body': base_funcs[n]['body']} for n in still_lost]
    res['added'] = added_names
    res['sig_changed'] = [{'name': n, 'diff': sig_diff(base_funcs[n], work_funcs[n])}
                          for n in sorted(set(base_funcs) & set(work_funcs))
                          if sig_diff(base_funcs[n], work_funcs[n])]
    return res


def audit(root, rev, base_dir, files, near):
    """审一批文件 → (逐文件结果, 仪器错误列表)。"""
    results, errors = [], []
    for rel in files:
        try:
            base_src = (read_side(base_dir, rel) if base_dir
                        else read_side(root, rel, rev))
            work_src = read_side(root, rel)
        except OSError as e:
            errors.append(f'{rel}: 读不了: {e}')
            continue
        if base_src is None and work_src is None:
            # 只有文件清单解析错了才会走到这里（真删/真加都至少有一侧是 str）；当仪器故障报
            errors.append(f'{rel}: 两侧都读不到（文件清单解析有问题？）')
            continue
        try:
            results.append(audit_file(rel, base_src, work_src, near))
        except SyntaxError as e:
            errors.append(f'{rel}: 源码语法错，无法解析 AST: {e}')
    return results, errors


# ---------------------------------------------------------------- 报告
def fmt_value(v):
    """报告里怎么印一个参数面的值（列表紧凑印、None 印成 —）。"""
    if v is None:
        return '—'
    if isinstance(v, list):
        return '[' + ', '.join(str(x) for x in v) + ']'
    return str(v)


def emit(results, errors, rev, base_dir, root, as_json, files, near):
    """打印报告 → 退出码（0/1/2）。"""
    lost, sig, ren, added = [], [], [], []
    for r in results:
        lost += [dict(name=f'{r["file"]}::{x["name"]}', body=x['body']) for x in r['lost']]
        sig += [dict(name=f'{r["file"]}::{x["name"]}', diff=x['diff']) for x in r['sig_changed']]
        ren += [dict(frm=f'{r["file"]}::{x["from"]}', to=x['to'], exact=x['exact'],
                     ratio=x['ratio']) for x in r['renamed']]
        added += [f'{r["file"]}::{n}' for n in r['added']]
    added_by_file = defaultdict(list)
    for a in added:
        f, _, n = a.partition('::')
        added_by_file[f].append(n)
    n_exact = sum(1 for x in ren if x['exact'])

    code = 2 if errors else (1 if (lost or sig) else 0)
    if as_json:
        print(json.dumps({'rev': rev, 'base_dir': base_dir, 'root': root, 'files': files,
                          'near': near, 'lost': lost, 'sig_changed': sig, 'renamed': ren,
                          'added': dict(added_by_file), 'errors': errors,
                          'counts': {'lost': len(lost), 'sig_changed': len(sig),
                                     'renamed': len(ren), 'renamed_exact': n_exact,
                                     'added': len(added)},
                          'exit_code': code}, ensure_ascii=False, indent=1))
        return code

    print('=' * 74)
    print('函数面静态审计（只审 API 面，不审行为；行为等价请用 dev/tools/equiv.py）')
    if base_dir:
        print(f'底本 : {base_dir}（目录树）')
    else:
        print(f'底本 : {rev}（git show <rev>:scripts/*.py）')
    print(f'工作树: {root}')
    print(f'范围 : {len(files)} 个文件；改名近似阈值 --near={near}')

    print('-' * 74)
    print(f'丢失（底本有、工作树没有，同文件内也找不到对应新函数）: {len(lost)}'
          + ('   ← 严重' if lost else ''))
    for x in lost:
        print(f'      {x["name"]}')
    print(f'签名变更（同名但参数面变了）: {len(sig)}' + ('   ← 严重' if sig else ''))
    for x in sig:
        print(f'      {x["name"]}')
        for field, old, new in x['diff']:
            print(f'        {field}: {fmt_value(old)}  →  {fmt_value(new)}')
    print(f'疑似改名（同文件内找到对应新函数；不计入失败）: {len(ren)}'
          f'（精确 {n_exact} / 近似 {len(ren) - n_exact}）')
    for x in ren:
        tag = '函数体逐字符一致' if x['exact'] else f'函数体近似 {x["ratio"]}（疑似嵌套函数提升，请复核）'
        print(f'      {x["frm"]}  →  {x["to"]}     {tag}')
    print(f'新增（工作树多出，不影响退出码）: {len(added)}')
    for f in sorted(added_by_file):
        names = added_by_file[f]
        print(f'      {f}（+{len(names)}）: ' + '、'.join(names))

    if errors:
        print('-' * 74)
        print(f'仪器故障 {len(errors)} 条（当退出码 2，别读成「函数面坏了」）:')
        for e in errors:
            print(f'      {e}')
    print('-' * 74)
    print(f'结论: 丢失 {len(lost)} / 签名变更 {len(sig)} / 疑似改名 {len(ren)} / 新增 {len(added)}'
          f' → 退出码 {code}')
    if ren:
        print('      疑似改名不计入失败：本轮重构预期就会给提升到模块级的嵌套函数改名，'
              '计入会让工具永远报红；但"近似"档只按函数体比值判，请人看一眼上面的配对与比值。')
    return code


# ---------------------------------------------------------------- CLI
def build_parser():
    """装配命令行参数。"""
    ap = argparse.ArgumentParser(
        prog='api_audit.py',
        description='函数面静态审计：原有的函数名/签名/嵌套关系一个都没丢、也没被偷偷改名'
                    '（口径与边界见文件 docstring）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='例：python dev/tools/api_audit.py --rev api-base --file scripts/flowtable.py')
    ap.add_argument('--root', default=ROOT_DEFAULT, help='工作树根（默认：本文件的上上级）')
    ap.add_argument('--rev', default=REV_DEFAULT,
                    help=f'底本 git 版本（默认 {REV_DEFAULT}）')
    ap.add_argument('--base-dir',
                    help='底本改用一棵目录树（与 --rev 二选一；自测造 mutant 用）。'
                         '别名 --base：与 dev/tools/equiv.py 的 --base 同义（都是"底本目录"），'
                         '两个名字收的是同一件事，任给一个即可')
    # 别名：equiv.py 里同一概念叫 --base。以 --base-dir 为主名，别名不进 --help 列表
    # （help=SUPPRESS 才藏得住），但两种写法都收——argv 里给哪个都落到同一个 dest，
    # 于是"与 --rev 二选一"的判据一行都不用动。
    ap.add_argument('--base', dest='base_dir', default=argparse.SUPPRESS,
                    help=argparse.SUPPRESS)
    ap.add_argument('--dir', default=SCRIPTS_DIR, help=f'要审的目录（默认 {SCRIPTS_DIR}）')
    ap.add_argument('--file', action='append', default=[],
                    help='只审指定文件，相对工作树根（可重复；分包复核用）')
    ap.add_argument('--near', type=float, default=NEAR_DEFAULT,
                    help=f'改名配对的近似阈值（默认 {NEAR_DEFAULT}；调到 1.0 就只剩精确档）')
    ap.add_argument('--json', action='store_true', help='输出 JSON 报告')
    return ap


def resolve_files(a):
    """要审的文件清单：--file 优先；否则取「工作树 ∪ 底本」的并集（文件被整体删掉也能审出来）。"""
    if a.file:
        return sorted(a.file)
    files = set(list_py(a.dir, a.root))
    if a.base_dir:
        files |= set(list_py(a.dir, a.base_dir))
    else:
        files |= set(list_py_at_rev(a.root, a.rev, a.dir))
    return sorted(files)


def main(argv=None):
    """入口：算文件清单 → 两侧取 AST → 分类报告；返回 0/1/2。"""
    sys.stdout.reconfigure(encoding='utf-8')
    a = build_parser().parse_args(argv)
    if a.base_dir:
        if not Path(a.base_dir).is_dir():
            print(f'✗ 底本目录不是目录: {a.base_dir}（--base-dir，别名 --base）', file=sys.stderr)
            return 2
    elif not rev_ok(a.root, a.rev):
        print(f'✗ 底本 git 版本不存在: {a.rev}（在工作树 {a.root} 里解析不了）', file=sys.stderr)
        return 2
    try:
        files = resolve_files(a)
    except RuntimeError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 2
    if not files:
        print(f'✗ 没找到要审的文件（{a.dir}/*.py）', file=sys.stderr)
        return 2
    results, errors = audit(a.root, a.rev, a.base_dir, files, a.near)
    return emit(results, errors, a.rev, a.base_dir, a.root, a.json, files, a.near)


if __name__ == '__main__':
    sys.exit(main())
