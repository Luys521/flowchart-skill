# -*- coding: utf-8 -*-
r"""capability.py — 能力指纹（PIPELINE-SPEC §1.2）：给产物盖上"**这是哪一版机制产的**"。

**为什么要有它**：材料陈化（`probe.verify_list`）答的是"材料还算不算当初那份"，
答不了"**做这份产物的机制还是不是当初那套**"。机制一变（改一条抽取判据、挪一个阈值），
**旧产物一个字节都不变**——于是它安安静静地继续被消费，谁也不知道它按的是上一版判据。
这是"一起错时全绿"的另一种形态：各层 `check` 核的都是**产物 ↔ 产物**，两边同源。

**两个指纹是不同的东西**（合成一个就等于逼人二选一）：

- `code` = `scripts/*.py` + `scripts/dictionary.yaml`：**机制**。它一改，机器产物的字节就可能变
  ⇒ 旧产物**本身**可能是旧机制做的：回 03 重跑 `probe → parse → ledger`。
- `rules` = `references/*.md` + `templates/*.md`：**判据**。它一改，机器产物一个字节都不变，
  但 **AI 的判断会变**（同一个句子按新尺子可能不该成节点）⇒ 机器产物不用重跑，但**人和 AI
  写下的那些结论**（计划 / 流程表 / 澄清答复）值得回看一遍。

**不盖时间戳**：§2.4 要"同输入两次同字节"，时间戳当场破坏它。指纹只由**内容**算，所以它是确定的。

**射程**（声明不许比射程宽）：指纹只覆盖上面这两组**文件内容**。它看不见环境——Python 版本、
装没装 `soffice` / OCR、`--encoding` 这类**调用参数**，一个都没进来。所以"没漂"只等于
"这份产物与当下这套**文件**同版"，**不等于**"结果一定对"。

退出码：`check` **0** = 都对得上；**2** = 有对不上的（**缺章**也算——"不知道是哪版产的"与
"知道是旧的"一样不能用）或产物读不了。`--json` / 纯打印模式恒 0。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

#: 仓库根 = `scripts/` 的上一级（布局假设只表述一次，见 `dev/_paths.py` / D-66）
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

#: 指纹组（顺序 = 打印顺序，也是比较顺序）
GROUPS = ('code', 'rules')

#: 产物里那个字段名：`evidence.json` 的**顶层键**，也是 `plan.md` 那一行的名字
KEY = 'capability'

#: 每一组漂了该怎么办（消费端要能照着做，不能只说"对不上"）
ADVICE = {
    'code': '机制变了 ⇒ 这份产物**本身**可能是旧机制做的：回 03 重跑 `probe → parse → ledger`',
    'rules': '判据变了 ⇒ 机器产物不用重跑，但按旧判据写下的结论（计划 / 表 / 澄清答复）值得回看',
}


def _rel(p):
    """仓库相对路径（posix）。**指纹里只许出现相对名**：绝对路径一进来，换机器换目录就全漂。"""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:                      # 仓外文件（不该有；留个不打脸的兜底）
        return Path(p).as_posix()


def files(group):
    """这一组覆盖哪些文件（**按仓库相对路径排序**：与平台、cwd、列目录次序都无关）。"""
    if group == 'code':
        got = list(SCRIPTS.glob('*.py')) + [SCRIPTS / 'dictionary.yaml']
    elif group == 'rules':
        got = list((ROOT / 'references').glob('*.md')) + list((ROOT / 'templates').glob('*.md'))
    else:
        raise ValueError(f'不认得的指纹组：{group!r}（只有 {" / ".join(GROUPS)}）')
    return sorted((p for p in got if p.is_file()), key=_rel)


def fingerprint(group='code'):
    """这一组的指纹 = `相对路径 \\0 内容 \\0` 逐份喂进 sha256，取前 12 位。

    **路径也进哈希**：只看内容的话，"把 A 的内容搬到 B"会算出同一个指纹——可改名就是改机制
    （下游 import 的正是名字）。
    """
    h = hashlib.sha256()
    for p in files(group):
        h.update(_rel(p).encode('utf-8') + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()[:12]


def stamp():
    """当下的章：`{'code': ..., 'rules': ...}`（**没有时间戳**，理由见文件头）。"""
    return {g: fingerprint(g) for g in GROUPS}


def compare(recorded):
    """产物里的章 ↔ 当下 → `(状态, 差异行)`。

    状态四态，因为"对不上"其实有三种不同的处境：`same`（同版）· `drift`（是旧的）·
    `absent`（**没盖章** = 来自盖指纹之前的版本，同样不知道它按哪版判据做的）·
    `bad`（章读不动 = 产物被改坏了）。后两种与 `drift` 一样**不能用**，但话说得不一样。
    """
    now = stamp()
    if recorded is None:
        return 'absent', [f'当下 code={now["code"]} rules={now["rules"]}']
    if not isinstance(recorded, dict):
        return 'bad', [f'章应当是对象，实际 {type(recorded).__name__}：{recorded!r}']
    diff = [f'{g} {recorded.get(g) or "（缺）"} → {now[g]}' for g in GROUPS
            if recorded.get(g) != now[g]]
    return ('drift', diff) if diff else ('same', [])


def warn(recorded, what='这份产物'):
    """消费端那几句话 → 行清单（`same` 时是**空表**，调用方直接逐行打印即可）。

    **只提醒、不拦**：拦着读等于不让人取证（"我知道它旧，我偏要看一眼"是合法需求）；
    该硬拦的是 `check`（一次把该重跑的列出来）。
    """
    state, lines = compare(recorded)
    if state == 'same':
        return []
    if state == 'absent':
        return [f'⚠ {what}没盖能力指纹——**无从判断它按哪一版判据做的**',
                f'   · 当下 code={stamp()["code"]} rules={stamp()["rules"]}；'
                f'要么重跑一次补上章（`probe → parse → ledger`），要么按旧产物对待']
    if state == 'bad':
        return [f'⚠ {what}的能力指纹读不动（**当它是旧的**）：{lines[0]}']
    out = [f'⚠ {what}的能力指纹对不上当下（**别当它是刚跑出来的**）：']
    for ln in lines:
        g, _, move = ln.partition(' ')
        out.append(f'   · {g} {move}：{ADVICE.get(g, "")}')
    return out


def md_line(recorded=None):
    """`plan.md` 表头那一行（**写与读同一句**：抄两遍必漂）。"""
    s = recorded or stamp()
    return f'> 机制指纹：code={s["code"]} rules={s["rules"]}'


def read_md(text):
    """从 markdown 里读回那一行 → 章（没有就是 `None` → `absent`）。"""
    m = re.search(r'^>\s*机制指纹[：:].*?code=([0-9a-f]+).*?rules=([0-9a-f]+)\s*$', text, re.M)
    return {'code': m.group(1), 'rules': m.group(2)} if m else None


def read_json(obj):
    """从产物对象里读章（`evidence.json` 顶层键）→ **章原样**，或 `None`（没这个键）。

    **键在但不是对象时原样返回**（G73）：原先这里把非 dict 一律折成 `None`，于是 `compare` 里
    那条 `bad`（"章读不动 = 产物被改坏了"）**永远进不来**——一份章被改坏的账本会被报成
    `absent`（"来自盖指纹之前的版本"），那是两种处境、两句话。现在把值原样交给 `compare` 判。
    """
    if not isinstance(obj, dict) or KEY not in obj:
        return None
    return obj[KEY]


def _describe():
    """纯打印模式的两行（顺带报每组覆盖多少份文件——"射程"要看得见）。"""
    s = stamp()
    return '\n'.join(
        f'  {g:<6}= {s[g]}   （{"机制：scripts/*.py + dictionary.yaml" if g == "code" else "判据：references/*.md + templates/*.md"}'
        f' · {len(files(g))} 份）' for g in GROUPS)


def cmd_check(paths):
    """逐份核对产物上的章。**退 2** = 有对不上的（缺章也算）或读不了。"""
    bad = 0
    for p in paths:
        f = Path(p)
        try:
            text = f.read_text(encoding='utf-8-sig')
            recorded = (read_md(text) if f.suffix.lower() == '.md'
                        else read_json(json.loads(text)))
        except (OSError, ValueError) as e:
            print(f'✗ {p}: 产物读不了（{type(e).__name__}: {e}）')
            bad += 1
            continue
        state, lines = compare(recorded)
        if state == 'same':
            print(f'✓ {p}: 与当下同版（code={stamp()["code"]}）')
            continue
        bad += 1
        print(f'✗ {p}: ' + {'absent': '没盖章（盖指纹之前的产物）',
                             'bad': '章读不动（产物被改坏了）',
                             'drift': '与当下对不上'}[state])
        for ln in lines:
            if state == 'drift':
                g, _, move = ln.partition(' ')
                print(f'   · {g} {move}：{ADVICE.get(g, "")}')
            else:
                print(f'   · {ln}')
    if bad:
        print(f'✗ {bad}/{len(paths)} 份产物的能力指纹对不上当下——**先把它们重跑**，'
              f'别在旧产物上接着做（`PIPELINE-SPEC` §1.2）')
        return 2
    print(f'✓ {len(paths)} 份产物与当下这套机制同版')
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='能力指纹：盖 / 查"这份产物是哪一版机制产的"（PIPELINE-SPEC §1.2）')
    ap.add_argument('cmd', nargs='?', choices=('check',), help='check = 核对产物上的章（退 2 = 对不上）')
    ap.add_argument('paths', nargs='*', help='check 要核的产物（证据账本 `evidence.json` / 计划 `plan.md`）')
    ap.add_argument('--json', action='store_true', help='把当下的章打成 JSON（给脚本吃）')
    a = ap.parse_args(argv)

    if a.cmd == 'check':
        if not a.paths:
            print('⚠ check 要给至少一份产物（`evidence.json` / `plan.md`）', file=sys.stderr)
            return 2
        return cmd_check(a.paths)
    if a.cmd:
        print(f'⚠ 不认得的子命令：{a.cmd}', file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(stamp(), ensure_ascii=False))
    else:
        print('能力指纹（PIPELINE-SPEC §1.2）：')
        print(_describe())
        print('  → 核对产物：`python scripts/capability.py check evidence.json plan.md`')
    return 0


if __name__ == '__main__':
    sys.exit(main())
