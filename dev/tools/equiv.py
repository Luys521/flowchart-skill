#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""equiv.py — 重构的「可观测行为等价」比对仪：一条命令证明"这次改动没改变任何可观测行为"。

一句话：**同一件事，在「工作树现状」与「隔离底本」上各跑一遍，逐字节比结果。**

## 为什么需要它
函数级原子化拆分（把一个函数体内的一串阶段拆成多个私有函数）唯一的安全性依据是
"行为逐字节不变"。这类改动看不出来对不对——**只能比**。没有统一工具时，每个拆包的人
各写一份临时脚本、口径各不相同（有人 strip 了输出、有人忘了比退出码、有人拿整目录回退
把队友的并发改动也一起回退了），于是"我这边是绿的"变成一句无法复核的话。

## 四种可比对物
1. `cli`   —— CLI 行为：同一命令 + 参数 + cwd，比对 `stdout` / `stderr` / 退出码，**原始字节**。
2. `files` —— 文件产物：给定路径的 SHA256 与字节数（含"一方有、另一方无"）。
3. `tree`  —— 目录整树：一棵目录里所有文件的**集合**与内容（如一个 `out/<名称>/`）。
4. `make-base` —— 隔离底本机制：把工作树里的**指定文件**回退到某个 git 版本（`git show <rev>:<path>`），
   其余保持工作树现状。

## 两种"根"，别混用
- `{side}` —— **代码**根：工作树根 / 底本目录。用来指 `scripts/<模块>.py`。
- `{work}` —— **数据**根：`--scratch` 下的一个目录，**两侧共用同一份，每次开跑前清空**
  （见下面「为什么必须共用数据区」）。产物、fixture、待测流程表都放这里。

### 为什么必须共用数据区（而不是各给一份）
初版实现给两侧各一份数据区（`work/`、`base/`），结果 `--write` / `build` / `render_*` / `sync`
几乎全部报"不同"——不是行为变了，而是这些命令会把**产物绝对路径回显到 stdout**，
两个目录的路径字符串本来就不一样。要修就得归一化输出（把路径替换掉），
而那正是本方法论**禁止**的事：一归一化，真正的差异也可能被一起抹掉。
所以改成：**同一份数据区，先跑完工作树侧、清空、再跑底本侧**。两侧看到的是同一批路径字符串，
回显自然逐字节相同；差异只可能来自代码。代价是两侧不能并行——对本用途完全可接受。

## 用法
    # ① 造隔离底本：只把「我改的」4 个文件回退到底本 tag，其余照工作树
    python dev/tools/equiv.py make-base --rev api-base --dest /tmp/base \\
        --file scripts/flowtable.py --file scripts/flowtable_check.py

    # ② 比 CLI 行为（{side}/{work}/{root}/{base}/{py} 逐侧替换）
    python dev/tools/equiv.py cli --base /tmp/base --scratch /tmp/eq \\
        --cwd '{side}/scripts' -- '{py}' '{side}/scripts/table_to_dsl.py' --check '{work}/t.md'

    # ③ 比文件产物 / ④ 比整树
    python dev/tools/equiv.py files --base /tmp/base --scratch /tmp/eq '{work}/out/demo-flow.yaml'
    python dev/tools/equiv.py tree  --base /tmp/base --scratch /tmp/eq '{work}/out/demo'

    # ⑤ 按清单批量跑（清单见 dev/tools/equiv-cases.json，说明见 dev/tools/equiv-README.md）
    python dev/tools/equiv.py suite --base /tmp/base --scratch /tmp/eq --cases dev/tools/equiv-cases.json

    # ⑥ 只造底本不跑（给别的脚本消费）
    python dev/tools/equiv.py make-base --rev HEAD --dest /tmp/base --all-scripts

## 清单（suite）的格式
    {
      "setup": [                                                        // 每侧开跑前各做一遍，不比
        {"kind": "copy", "name": "铺 fixture", "src": "{root}/dev/tools/equiv-fixtures/tour.md",
         "dst": "{work}/out/tour/flowtable.md"},
        {"kind": "cli",  "name": "init", "cwd": "{side}",
         "argv": ["{py}", "{side}/scripts/init.py", "demo", "-d", "{work}/out"]}
      ],
      "cases": [
        {"kind": "cli",   "argv": ["{py}", "{side}/scripts/table_to_dsl.py", "--check", "…"]},
        {"kind": "cli",   "name": "可选别名", "cwd": "{side}/scripts", "argv": [...]},
        {"kind": "files", "paths": ["{work}/out/tour/tour-flow.yaml"]},
        {"kind": "tree",  "dirs":  ["{work}/out/tour"]},
        {"kind": "copy",  "name": "换成与图冲突的那版表", "src": "{root}/…", "dst": "{work}/…"},
        {"kind": "prep",  "name": "改一版再跑", "argv": [...]}
      ]
    }
清单条目**按顺序执行**，所以"先 build、再用产物做下一步"直接写成先后两条即可。
`copy` / `prep`（在 setup 或 cases 里都行）是"只做不比"的预备步骤：**照样会真的执行**，
只是结果不计入相同/不同。这一点必须实现对——它们不执行时后面的用例会静默地比一件没发生的事。

## 纪律（这套方法能立住的原因；改本文件前先读一遍）
- **只比可观测行为，不做代码级等价性推断。** 静态读 diff 判断"这两段逻辑等价"是另一件事，
  不能替代本工具；本工具只回答"跑出来的字节一不一样"。它盖不住的维度见 equiv-README.md 末节。
- **底本隔离必须显式列出文件**（`--file`）。整目录回退会把队友的并发改动一起回退，
  于是 diff 里混进不是你造成的差异——**假差异比没差异更坏**：你会去修一个不存在的问题。
  （确实要整体回退时用 `--all-scripts`；那时它的语义是"回退整个脚本层"，报告里会写明。）
- **先观察、后比对，数据区共用。** 两侧先后跑在同一份数据区上（跑前清空），
  所以"产物路径回显"这类两侧本来就不同的字符串不会冒充差异；也因此**不许归一化输出**。
- **报告粒度**：每条都给「相同/不同 + 两侧字节数」；不同时给 **第一个差异字节的偏移** 与
  前后各 80 字节上下文。只报一句"不同"等于没报：定位不到就修不了。
- **退出码**：全相同 `0`，有任一不同 `1`，仪器故障 `2`。
  1 与 2 分开，是为了让"底本不存在 / 命令根本跑不起来"不被误读成"行为变了"。
- **不归一化**：不 strip、不替换路径、不忽略空白、不统一换行。唯一的"排序"是 `tree` 按相对
  路径排序枚举（只为报告可读，不改变"哪些文件存在、内容是否相同"的判定）。
- **防陈旧字节码**：`make-base` 复制时排除 `__pycache__`，跑比对时注入
  `PYTHONDONTWRITEBYTECODE=1`。否则底本目录里的陈旧 `.pyc` 可能让"底本"实际加载了
  工作树的模块，比对就成了自己跟自己比——这个坑很隐蔽，且症状恰好是"全相同"。
- **两侧同环境**：`--env` 与默认注入的 `PYTHONIOENCODING=utf-8` 对两侧**完全一致**，
  所以它不掩盖差异，只是让 Windows 上的中文输出在两份底本间可比。
- **数据区在仓库外**：`{work}` 只落在 `--scratch` 目录下（默认系统临时目录），
  工作树那一侧也**不往仓库里写**。
- **比不到就不装作比到了**：大于 `CONTENT_CAP` 的文件只比指纹，报告里明说"未做差异定位"。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# dev/ 是本文件的上一级——布局假设只表述一次（见 dev/_paths.py 与 D-66）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _paths import REPO  # noqa: E402

ROOT_DEFAULT = str(REPO)
CTX = 80                      # 差异点前后各取多少字节做上下文
CONTENT_CAP = 4 * 1024 * 1024  # 单文件超过这个大小就只比指纹、不读内容（报告里会写明）


# ----------------------------------------------------------------两侧上下文
class Ctx:
    """一次比对的两侧上下文：代码根、共用数据区、超时与环境，以及占位符替换的唯一口径。"""

    def __init__(self, root, base, scratch=None, timeout=180.0, env=None):
        self.root, self.base = str(Path(root).resolve()), str(Path(base).resolve())
        self.scratch = str(Path(scratch or tempfile.mkdtemp(prefix='equiv-')).resolve())
        self.work = os.path.join(self.scratch, 'work')
        self.timeout, self.env = timeout, env or []

    def sides(self):
        """(标签, 代码根) 两侧——报告里以"工作树 / 底本"称呼，别用路径区别人。"""
        return (('工作树', self.root), ('底本', self.base))

    def expand(self, tmpl, side):
        """把 {side} / {work} / {root} / {base} / {py} 替换成实际值。"""
        return (str(tmpl).replace('{side}', side).replace('{work}', self.work)
                .replace('{py}', sys.executable)
                .replace('{root}', self.root).replace('{base}', self.base))

    def wipe_work(self):
        """清空共用数据区——两侧必须从同一片空白开始，否则上一次的产物会冒充结果。"""
        shutil.rmtree(self.work, ignore_errors=True)
        os.makedirs(self.work, exist_ok=True)


# ----------------------------------------------------------------差异定位（报告的地基）
def first_diff(a, b):
    """比对两段字节 → None（完全相同）或 (偏移, a 的上下文, b 的上下文)。"""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            lo, hi = max(0, i - CTX), i + CTX
            return i, a[lo:hi], b[lo:hi]
    if len(a) != len(b):
        i, lo, hi = n, max(0, n - CTX), n + CTX
        return i, a[lo:hi], b[lo:hi]
    return None


def context_lines(label, chunk):
    """把一段上下文渲染成报告里的一行（bytes repr 最忠实，不做任何解码猜测）。"""
    return [f'      {label}: {chunk!r}']


def describe_bytes(name, a, b):
    """两段字节的比对叙述 → (same, [报告行...])。"""
    if a == b:
        return True, [f'      {name} 相同（{len(a)} 字节）']
    lines = [f'      {name} {len(a)}B vs {len(b)}B']
    d = first_diff(a, b)
    if d is None:
        lines.append('      （长度相同、内容相同——不应到达这里，请报 bug）')
        return True, lines
    lines.append(f'      首处差异 @{d[0]}（±{CTX} 字节上下文）:')
    lines += context_lines('工作树', d[1])
    lines += context_lines('底本', d[2])
    return False, lines


# ----------------------------------------------------------------报告
class Report:
    """一次比对的全部条目；`all_same` 决定退出码，`emit` 决定输出形态。"""

    def __init__(self, kind, ctx, manifest=None):
        self.kind, self.ctx, self.manifest = kind, ctx, manifest
        self.items = []

    def add(self, name, same, detail=None, lines=None, prep=False):
        """记一条比对结果：name 是这一条在比什么，same 是结论。

        `prep=True` 表示"只预备、不做比对"（如把 fixture 铺到数据区），不参与相同/不同计数。
        """
        self.items.append({'name': name, 'same': bool(same), 'prep': bool(prep),
                           'detail': detail or {}, 'lines': lines or []})

    def fail_instrument(self, name, why):
        """仪器故障：命令跑不起来 / 底本缺失。与"行为不同"分开记，退出码也不同。"""
        self.items.append({'name': name, 'same': False, 'instrument': True, 'prep': False,
                           'detail': {'error': why}, 'lines': [f'      仪器故障: {why}']})

    @property
    def all_same(self):
        return all(i['same'] for i in self.items)

    @property
    def broke(self):
        return any(i.get('instrument') for i in self.items)

    def exit_code(self):
        if self.broke:
            return 2
        return 0 if self.all_same else 1

    def emit(self, as_json):
        """打印报告；--json 时输出结构化版本（供 CI / 别的脚本消费）。"""
        if as_json:
            print(json.dumps({'kind': self.kind, 'root': self.ctx.root, 'base': self.ctx.base,
                              'work': self.ctx.work, 'manifest': self.manifest,
                              'all_same': self.all_same, 'instrument_failure': self.broke,
                              'items': self.items}, ensure_ascii=False, indent=1))
            return
        print(self._header())
        counted = [i for i in self.items if not i.get('prep')]
        n_same = sum(1 for i in counted if i['same'])
        for it in self.items:
            if it.get('prep'):
                tag = '预备故障' if it.get('instrument') else '预备'
            else:
                tag = '仪器故障' if it.get('instrument') else ('相同' if it['same'] else '不同')
            print(f'{tag}  {it["name"]}')
            for l in it['lines']:
                print(l)
        tail = (f'共 {len(counted)} 条比对：相同 {n_same}，不同 {len(counted) - n_same}'
                f'（另有 {len(self.items) - len(counted)} 条预备步骤，不计入）')
        if self.broke:
            tail += '；含仪器故障 → 退出码 2'
        elif self.all_same:
            tail += ' → 退出码 0'
        else:
            tail += ' → 退出码 1'
        print(tail)

    def _header(self):
        """报告头：把"底本是哪一版、回退了哪些文件、数据区在哪"写清楚，否则报告无法复核。"""
        head = ['=' * 72]
        if self.manifest:
            files = self.manifest.get('files') or []
            head.append(f'底本 : {self.ctx.base}')
            head.append(f'        回退到 {self.manifest.get("rev")} 的文件 {len(files)} 个：'
                        + '、'.join(files[:6]) + ('…' if len(files) > 6 else ''))
            if self.manifest.get('all_scripts'):
                head.append('        （--all-scripts：回退了整个 scripts/，不是隔离某个人的改动）')
            if self.manifest.get('head'):
                head.append(f'        造底本时的 git HEAD={self.manifest["head"]}'
                            f'{"（工作树脏）" if self.manifest.get("dirty") else "（工作树干净）"}')
        else:
            head.append(f'底本 : {self.ctx.base}（无 .equiv-manifest.json，无法说明底本怎么造的）')
        head.append(f'工作树: {self.ctx.root}')
        head.append(f'数据区: {self.ctx.work}（两侧共用同一份，每次开跑前清空）')
        head.append('-' * 72)
        return '\n'.join(head)


# ----------------------------------------------------------------子进程执行
def build_env(extra):
    """两侧共用的子进程环境：默认注入 UTF-8 输出与"不写字节码"，再叠加 --env。"""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for kv in (extra or []):
        k, _, v = kv.partition('=')
        env[k] = v
    return env


def run_once(argv, cwd, env, timeout):
    """跑一次命令 → {rc, out, err, sec}；起不来时返回 {error}（调用方当仪器故障）。"""
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        return {'error': f'命令不存在: {e}'}
    except subprocess.TimeoutExpired:
        return {'error': f'超时（>{timeout}s）'}
    except OSError as e:
        return {'error': f'无法启动: {e}'}
    return {'rc': p.returncode, 'out': p.stdout, 'err': p.stderr, 'sec': time.monotonic() - t0}


# ----------------------------------------------------------------文件指纹与观察
def fingerprint(path):
    """文件指纹 → None（不存在）或 {size, sha256}。"""
    if not os.path.isfile(path):
        return None
    h, size = hashlib.sha256(), 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
            size += len(chunk)
    return {'size': size, 'sha256': h.hexdigest()}


def read_capped(path):
    """读文件内容用于差异定位；过大或读不了返回 None（只比指纹）。"""
    try:
        if os.path.getsize(path) > CONTENT_CAP:
            return None
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def observe_cli(ctx, side, spec):
    """观察一条命令在该侧的 CLI 行为 → {od, rc, out, err, sec, error}。"""
    argv = [ctx.expand(x, side) for x in spec['argv']]
    cwd = ctx.expand(spec.get('cwd', '{side}'), side)
    if not os.path.isdir(cwd):
        return {'od': 'cli', 'error': f'cwd 不存在: {cwd}'}
    r = run_once(argv, cwd, build_env(ctx.env), ctx.timeout)
    if 'error' in r:
        return {'od': 'cli', 'error': f'{r["error"]}  [{argv}]'}
    return {'od': 'cli', 'rc': r['rc'], 'out': r['out'], 'err': r['err'], 'sec': r['sec']}


def observe_files(ctx, side, paths):
    """观察一组文件在该侧的存在性/指纹（含内容，供差异定位）→ {od, facts}。"""
    facts = {}
    for tmpl in paths:
        p = ctx.expand(tmpl, side)
        f = fingerprint(p)
        facts[tmpl] = None if f is None else dict(f, content=read_capped(p))
    return {'od': 'files', 'facts': facts}


def observe_tree(ctx, side, dirs):
    """观察一棵目录在该侧的整树 → {od, trees}，每个文件带指纹与（限额内的）内容。"""
    trees = {}
    for tmpl in dirs:
        root_dir = Path(ctx.expand(tmpl, side))
        if not root_dir.is_dir():
            trees[tmpl] = None
            continue
        files = {}
        for f in sorted(root_dir.rglob('*')):
            if f.is_file():
                rel = f.relative_to(root_dir).as_posix()
                files[rel] = dict(fingerprint(str(f)) or {}, content=read_capped(str(f)))
        trees[tmpl] = files
    return {'od': 'tree', 'trees': trees}


def observe(ctx, side, case):
    """按 case 的 kind 分派观察；未知 kind 返回带 error 的观察。"""
    kind = case['kind']
    if kind == 'cli':
        return observe_cli(ctx, side, case)
    if kind == 'files':
        return observe_files(ctx, side, case['paths'])
    if kind == 'tree':
        return observe_tree(ctx, side, case['dirs'])
    return {'od': kind, 'error': f'清单里未知的 kind: {kind}'}


# ----------------------------------------------------------------两侧观察的比对
def compare_cli(obs_a, obs_b):
    """两侧 CLI 观察 → (same, lines, detail)。"""
    if 'error' in obs_a or 'error' in obs_b:
        return False, [f'      仪器故障: 工作树 {obs_a.get("error")} / 底本 {obs_b.get("error")}'], \
               {'error': [obs_a.get('error'), obs_b.get('error')]}
    subs = [describe_bytes('stdout', obs_a['out'], obs_b['out']),
            describe_bytes('stderr', obs_a['err'], obs_b['err'])]
    same = all(s for s, _ in subs) and obs_a['rc'] == obs_b['rc']
    lines = [f'      退出码: {obs_a["rc"]} vs {obs_b["rc"]}'
             + ('' if obs_a['rc'] == obs_b['rc'] else '  ← 不同')]
    for _, ls in subs:
        lines += ls
    return same, lines, {'rc': [obs_a['rc'], obs_b['rc']],
                         'stdout': [len(obs_a['out']), len(obs_b['out'])],
                         'stderr': [len(obs_a['err']), len(obs_b['err'])],
                         'sec': [round(obs_a['sec'], 3), round(obs_b['sec'], 3)]}


def _describe_fact(name, fa, fb):
    """一个文件的两侧指纹差异 → (same, lines)；含"一方没有"与内容差异定位。"""
    if fa is None and fb is None:
        # 两侧都没有 = 两侧一致（原先也判不同，会印出自相矛盾的存在性不同: 工作树无、底本无）
        return True, [f'      {name} 两侧都不存在（一致）']
    if fa is None or fb is None:
        missing = ([f'工作树无'] if fa is None else []) + ([f'底本无'] if fb is None else [])
        return False, [f'      {name} 存在性不同: {"、".join(missing)}']
    if fa['sha256'] == fb['sha256']:
        return True, [f'      {name} 相同（{fa["size"]} 字节，sha256 {fa["sha256"][:16]}…）']
    lines = [f'      {name} sha256 不同: 工作树 {fa["sha256"][:16]}… ({fa["size"]}B)  vs  '
             f'底本 {fb["sha256"][:16]}… ({fb["size"]}B)']
    ca, cb = fa.get('content'), fb.get('content')
    if ca is None or cb is None:
        lines.append(f'      （文件大于 {CONTENT_CAP >> 20} MiB、或读不到内容，只比指纹）')
    else:
        d = first_diff(ca, cb)
        if d:
            lines.append(f'      首处差异 @{d[0]}（±{CTX} 字节上下文）:')
            lines += context_lines('工作树', d[1])
            lines += context_lines('底本', d[2])
    return False, lines


def compare_files(obs_a, obs_b):
    """两侧文件观察 → (same, lines, detail)。"""
    if 'error' in obs_a or 'error' in obs_b:
        return False, [f'      仪器故障: {obs_a.get("error") or obs_b.get("error")}'], {}
    same, lines = True, []
    for tmpl in obs_a['facts']:
        s, ls = _describe_fact(f'files {tmpl}', obs_a['facts'][tmpl], obs_b['facts'].get(tmpl))
        same = same and s
        lines += ls
    return same, lines, {'paths': list(obs_a['facts'])}


def compare_tree(obs_a, obs_b):
    """两侧整树观察 → (same, lines, detail)：先比文件集合，再逐文件比内容。"""
    if 'error' in obs_a or 'error' in obs_b:
        return False, [f'      仪器故障: {obs_a.get("error") or obs_b.get("error")}'], {}
    same, lines = True, []
    for tmpl in obs_a['trees']:
        ta, tb = obs_a['trees'][tmpl], obs_b['trees'].get(tmpl)
        if ta is None or tb is None:
            which = '工作树侧' if ta is None else '底本侧'
            lines.append(f'      tree {tmpl}: {which}不是目录')
            same = False
            continue
        only_a, only_b = sorted(set(ta) - set(tb)), sorted(set(tb) - set(ta))
        common = sorted(set(ta) & set(tb))
        diffs = [r for r in common if ta[r].get('sha256') != tb[r].get('sha256')]
        lines.append(f'      tree {tmpl}: 文件数 {len(ta)} vs {len(tb)}；共有 {len(common)}，'
                     f'内容不同 {len(diffs)}')
        if only_a:
            lines.append(f'      仅工作树有（{len(only_a)}）: ' + '、'.join(only_a[:8])
                         + ('…' if len(only_a) > 8 else ''))
        if only_b:
            lines.append(f'      仅底本有（{len(only_b)}）: ' + '、'.join(only_b[:8])
                         + ('…' if len(only_b) > 8 else ''))
        for rel in diffs[:8]:
            lines.append(f'      · {rel}')
            lines += _describe_fact(rel, ta[rel], tb[rel])[1]
        if len(diffs) > 8:
            lines.append(f'      （内容不同的文件还有 {len(diffs) - 8} 个，未逐个列出）')
        if only_a or only_b or diffs:
            same = False
    return same, lines, {'trees': list(obs_a['trees'])}


def compare_observations(obs_a, obs_b):
    """按观察类型分派 → (same, lines, detail)。"""
    if obs_a['od'] != obs_b['od']:
        return False, [f'      观察类型不一致: {obs_a["od"]} vs {obs_b["od"]}'], {}
    if obs_a['od'] == 'cli':
        return compare_cli(obs_a, obs_b)
    if obs_a['od'] == 'files':
        return compare_files(obs_a, obs_b)
    return compare_tree(obs_a, obs_b)


# ----------------------------------------------------------------逐侧执行
def case_name(case, ctx=None, side=None):
    """给一条 case 起个能进报告的短名：优先 name，否则用**展开后**的命令/路径本身。

    没给 name 时必须展开占位符——报告里印一行 `{py} {side}/scripts/…` 等于没印命令。
    """
    if case.get('name'):
        return case['name']

    def ex(s):
        return ctx.expand(s, side) if ctx else str(s)

    if case['kind'] == 'cli':
        return 'cli    ' + ' '.join(ex(a) for a in case['argv'])
    if case['kind'] == 'files':
        return 'files  ' + '、'.join(ex(p) for p in case['paths'])
    if case['kind'] == 'tree':
        return 'tree   ' + '、'.join(ex(d) for d in case['dirs'])
    return case['kind']


def run_setup(ctx, side, specs):
    """某一侧的预备步骤：只关心"做成了没有"，不比对；做不成返回错误字符串。"""
    for spec in specs:
        name = spec.get('name') or ' '.join(spec.get('argv') or [spec.get('src', '?')])
        if spec.get('kind') == 'copy':
            src, dst = ctx.expand(spec['src'], side), ctx.expand(spec['dst'], side)
            if not os.path.isfile(src):
                return f'预备步骤「{name}」失败: 源文件不存在 {src}'
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            continue
        argv = [ctx.expand(x, side) for x in spec['argv']]
        cwd = ctx.expand(spec.get('cwd', '{side}'), side)
        r = run_once(argv, cwd, build_env(ctx.env), ctx.timeout)
        if 'error' in r:
            return f'预备步骤「{name}」失败: {r["error"]}'
    return None


def run_case(ctx, side, case):
    """执行一条 case 并取观察；`copy` / `prep` 是"只做不比"的侧效应步骤（语义同 setup）。

    这两类步骤**必须真的被执行**：它们是"先换一版表、再跑命令"这类用例的前提。
    漏执行不会报错，只会让后面的用例比对一件根本没发生过的事——症状恰好是"两侧一致"，
    比报错更坏。所以它们走 setup 的执行路径，失败也算仪器故障。
    """
    if case['kind'] in ('copy', 'prep'):
        err = run_setup(ctx, side, [case])
        return {'od': case['kind'], 'error': err} if err else {'od': case['kind']}
    return observe(ctx, side, case)


def run_side(ctx, side, setup, cases):
    """在一侧完整跑一遍（先清空数据区、再 setup、再逐条执行）→ {setup_error, obs}。"""
    ctx.wipe_work()
    err = run_setup(ctx, side, setup)
    if err:
        return {'setup_error': f'{side} 侧 {err}', 'obs': None}
    return {'setup_error': None, 'obs': [run_case(ctx, side, c) for c in cases]}


def run_sequence(ctx, setup, cases, report):
    """两侧各完整跑一遍，再逐条比对，把结果写进 report；返回是否全部相同。

    必须"先跑完一侧、清空、再跑另一侧"：两侧共用数据区，回显的路径字符串才会逐字节相同。
    """
    runs = {label: run_side(ctx, side, setup, cases) for label, side in ctx.sides()}
    broke = {label: r['setup_error'] for label, r in runs.items() if r['setup_error']}
    if broke:
        for label, err in broke.items():
            report.fail_instrument('setup', err)
        # **不许在这里 return**（D-85）：一 return，剩下的用例既不执行也不留条目，报告就只剩一条
        # setup 故障 —— 59 条清单对 1 条报告，而 `Report.all_same` 只看"有没有 False"，看起来像全过。
        # 逐条补"未执行（仪器故障）"，让**报告条数恒等于清单条数**，缺口一目了然。
        for case in cases:
            report.add('未执行(仪器故障) ' + case_name(case, ctx, ctx.sides()[0][1]),
                       False, {'instrument': True},
                       ['      （另一侧 setup 失败：本轮这条没跑）'])
        return False
    if not cases and not report.items:
        # 空清单同样不许算"全相同"：`all_same` 对空表恒真，退出码会变 0，而这一轮什么都没比。
        report.fail_instrument('cases', '清单里一条用例都没有——这轮比对没有任何内容')
        return False
    la, lb = ctx.sides()[0][0], ctx.sides()[1][0]
    obs_a, obs_b = runs[la]['obs'], runs[lb]['obs']
    all_same = True
    for case, oa, ob in zip(cases, obs_a, obs_b):
        name = case_name(case, ctx, ctx.sides()[0][1])
        if case['kind'] in ('prep', 'copy'):
            if oa.get('error') or ob.get('error'):
                report.fail_instrument('prep   ' + name,
                                       f'预备步骤没做成: 工作树 {oa.get("error")} / 底本 {ob.get("error")}')
                return False
            report.add('prep   ' + name, True, {'prep': True},
                       ['      （预备步骤：两侧各做一遍，不做比对）'], prep=True)
            continue
        same, lines, detail = compare_observations(oa, ob)
        all_same = all_same and same
        report.add(name, same, detail, lines)
    return all_same


# ----------------------------------------------------------------make-base
def git(root, *args):
    """在 root 下跑 git 并返回原始字节 stdout；失败抛 RuntimeError（带上 stderr）。"""
    p = subprocess.run(['git'] + list(args), cwd=root, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} 失败: {p.stderr.decode("utf-8", "replace").strip()}')
    return p.stdout


def copy_entries(root, dest, names):
    """把工作树的若干条目复制进底本目录（排除 __pycache__：陈旧字节码会让比对失真）。"""
    copied = []
    for name in names:
        src, dst = Path(root) / name, Path(dest) / name
        if not src.exists():
            raise RuntimeError(f'要复制的工作树条目不存在: {src}')
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        copied.append(name)
    return copied


def make_base(args):
    """造隔离底本：复制工作树条目，再把显式列出的文件回退到 --rev，并写清单供报告引用。"""
    root, dest = str(Path(args.root).resolve()), str(Path(args.dest).resolve())
    files = list(args.file or [])
    if args.all_scripts:
        files = sorted(p.relative_to(root).as_posix()
                       for p in (Path(root) / 'scripts').glob('*.py'))
    if not files:
        print('✗ 没指定要回退的文件：用 --file scripts/<模块>.py 显式列出（纪律见本文件 docstring），'
              '或用 --all-scripts 明确表示"回退整个 scripts/"', file=sys.stderr)
        return 2
    if Path(dest).exists():
        shutil.rmtree(dest)
    Path(dest).mkdir(parents=True)
    try:
        copied = copy_entries(root, dest, args.copy)
        for rel in files:
            blob = git(root, 'show', f'{args.rev}:{rel}')
            target = Path(dest) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
    except RuntimeError as e:
        print(f'✗ {e}', file=sys.stderr)
        return 2
    head = git(root, 'rev-parse', '--short', 'HEAD').decode().strip()
    dirty = bool(git(root, 'status', '--porcelain').strip())
    manifest = {'tool': 'dev/tools/equiv.py', 'rev': args.rev, 'files': files,
                'copied': copied, 'root': root, 'head': head, 'dirty': dirty,
                'all_scripts': bool(args.all_scripts)}
    (Path(dest) / '.equiv-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'✓ 隔离底本: {dest}')
    print(f'  回退到 {args.rev} 的文件 {len(files)} 个: ' + '、'.join(files))
    print(f'  整体复制的条目: ' + '、'.join(copied))
    print(f'  工作树 HEAD={head}{"（脏）" if dirty else "（干净）"}')
    print('  注意：底本里的其他文件仍是工作树现状——所以两份的差异只可能来自上面这些文件。')
    return 0


# ----------------------------------------------------------------suite 与单条比对
def load_manifest(base):
    """读底本清单（没有就返回 None，报告里会写明"无法说明底本怎么造的"）。"""
    p = Path(base) / '.equiv-manifest.json'
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def spec_from_args(a):
    """把 cli / files / tree 三个单条子命令的参数统一成一条 case。"""
    if a.cmd == 'cli':
        argv = a.argv[1:] if a.argv[:1] == ['--'] else a.argv
        return {'kind': 'cli', 'argv': argv, 'cwd': a.cwd} if argv else None
    if a.cmd == 'files':
        return {'kind': 'files', 'paths': a.paths}
    return {'kind': 'tree', 'dirs': a.dirs}


def run_simple(args):
    """单条比对：造 ctx、跑两侧、比对、出报告，返回退出码。"""
    base = str(Path(args.base).resolve())
    if not os.path.isdir(base):
        print(f'✗ 底本目录不存在: {base}（先用 make-base 造一个）', file=sys.stderr)
        return 2
    case = spec_from_args(args)
    if case is None:
        print('✗ cli 需要一个命令：... cli --base DIR -- <命令…>', file=sys.stderr)
        return 2
    ctx = Ctx(args.root, base, args.scratch, args.timeout, args.env)
    report = Report(args.cmd, ctx, load_manifest(base))
    run_sequence(ctx, [], [case], report)
    report.emit(args.json)
    return report.exit_code()


def run_suite(args):
    """按清单批量比对：两侧各完整跑一遍（含 setup），再逐条比。"""
    base = str(Path(args.base).resolve())
    if not os.path.isdir(base):
        print(f'✗ 底本目录不存在: {base}', file=sys.stderr)
        return 2
    cases_doc = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    ctx = Ctx(args.root, base, args.scratch, args.timeout, args.env)
    report = Report('suite', ctx, load_manifest(base))
    run_sequence(ctx, cases_doc.get('setup') or [], cases_doc.get('cases') or [], report)
    report.emit(args.json)
    return report.exit_code()


# ----------------------------------------------------------------cli 装配
def add_common(sub, name, helptext):
    """给一个子命令挂公共参数（--base / --json / --timeout / --env / --scratch）。"""
    c = sub.add_parser(name, help=helptext)
    c.add_argument('--base', required=True, help='由 make-base 造出的底本目录')
    c.add_argument('--json', action='store_true', help='输出 JSON 报告')
    c.add_argument('--timeout', type=float, default=180.0, help='单次命令超时秒数（默认 180）')
    c.add_argument('--env', action='append', default=[], metavar='K=V',
                   help='给两侧同时注入的环境变量（可重复）')
    c.add_argument('--scratch', help='数据区根目录（{work} 落在这里；默认取系统临时目录）')
    return c


def build_parser():
    """装配命令行：make-base / cli / files / tree / suite 五个子命令。"""
    ap = argparse.ArgumentParser(
        prog='equiv.py', description='重构的「可观测行为等价」比对仪（用法与纪律见文件 docstring）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='例：python dev/tools/equiv.py cli --base /tmp/base --scratch /tmp/eq '
               '--cwd "{side}/scripts" -- "{py}" "{side}/scripts/table_to_dsl.py" --check "{work}/t.md"')
    ap.add_argument('--root', default=ROOT_DEFAULT, help='工作树根（默认：本文件的上上级）')
    sub = ap.add_subparsers(dest='cmd', required=True)

    mb = sub.add_parser('make-base', help='造隔离底本：显式列出的文件回退到某 git 版本')
    mb.add_argument('--rev', required=True, help='git 版本，如 api-base / HEAD~1')
    mb.add_argument('--dest', required=True, help='底本目录（会被清空重建）')
    mb.add_argument('--file', action='append', default=[],
                    help='要回退的文件，相对工作树根（可重复；建议每次显式列出）')
    mb.add_argument('--all-scripts', action='store_true',
                    help='回退整个 scripts/（语义是"回退脚本层"，不是隔离某个人的改动）')
    mb.add_argument('--copy', action='append', default=None,
                    help='整体复制的工作树条目（可重复；默认 scripts 与 templates）')

    c = add_common(sub, 'cli', '比 CLI 行为：stdout / stderr / 退出码，原始字节')
    c.add_argument('--cwd', default='{side}', help='两侧的 cwd 模板（默认 {side}）')
    c.add_argument('argv', nargs=argparse.REMAINDER,
                   help='命令；{side}/{work}/{py} 替换为实际值。建议前置 --')
    f = add_common(sub, 'files', '比文件产物：SHA256 + 字节数')
    f.add_argument('paths', nargs='+', help='路径模板（可用 {side} / {work} / {root} / {base}）')
    t = add_common(sub, 'tree', '比目录整树：文件集合 + 内容')
    t.add_argument('dirs', nargs='+', help='目录模板（可用 {side} / {work} / {root} / {base}）')

    su = add_common(sub, 'suite', '按清单批量比对（清单见 dev/tools/equiv-cases.json）')
    su.add_argument('--cases', required=True, help='用例清单 JSON')
    return ap


def main(argv=None):
    """入口：分发子命令，返回进程退出码（0 全同 / 1 有不同 / 2 仪器故障）。"""
    sys.stdout.reconfigure(encoding='utf-8')
    a = build_parser().parse_args(argv)
    if a.cmd == 'make-base':
        if a.copy is None:
            a.copy = ['scripts', 'templates']
        return make_base(a)
    if a.cmd == 'suite':
        return run_suite(a)
    return run_simple(a)


if __name__ == '__main__':
    sys.exit(main())
