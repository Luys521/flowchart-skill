# -*- coding: utf-8 -*-
r"""textquality.py — 抽取质量判据（PIPELINE-SPEC §1.5「手段 0」）：**"抽出来了"不等于"抽对了"**。

**为什么需要它**（实测，不是假想）：`probe` 说某份 PDF"有文本层"（`/Font` x161）、`parse_pdf` 说"抽到
1563 字"——两边都真，可那条文本层是**竖排 / 字距碎裂的水印碎片**：整份 225 行里 140 行是单字行
（62%），前 3 页 100%。下游会把这种碎片当 `certainty=direct` 的证据去引「依据」列。
**"读不动"是诚实的，"读出垃圾却当直取证据"是最坏的一种**——它污染唯一事实源，而且没有仪器看得见。

三级判决（阈值是**数值**，家只有一个：`scripts/dictionary.yaml` 的 `material_quality:` 段）：

| 级别 | 含义 | 分派器怎么处置（`parse.py`） |
|---|---|---|
| `ok` | 干净 | 照收 |
| `noisy` | **有真内容，但混着碎片 / 坏字符** | 丢掉**纯碎片**的那几条元素，留下的每条挂 `degraded` 说明（§2.4 降级必须留痕）+ 建议转图片核对 |
| `garbled` | 碎片 / 坏字符主导 | 该材料的元素**一律不入账**，记 `unreadable` + **建议处置**（转图片 / OCR / 进澄清） |

**样本太小不判**（行数 < `min_lines`）：几行的材料没有统计意义，判了就是拿噪声当结论——
**宁可漏判，不可误判**（误判会把能读的材料判成读不动，那是把仪器的错算在材料头上）。

判据只吃**文字类** kind（`paragraph` / `heading` / `list_item` / `caption` / `code`）：
`table` / `sheet` 的内容在 `rows` 里，`figure` 是图——都不该按"行"统计。
"""
from pathlib import Path


def element_haystack(el):
    """一条证据的**可搜面**：正文 + 表格全部单元格 + 出处摘录（**小写**，供朴素子串匹配）。

    **放公共层是因为有两个消费者**：`query.py --grep`（取子集）与 `parse.py --grep`（抽取时收窄）。
    两边各写一份的话，同一句命令行在两个环节会命中不同的集合——"取子集时说有、收窄时却把它滤掉"
    这种不一致最难查（本仓的分层纪律：共用能力下沉到公共层，模块之间不许互相 import）。
    """
    parts = [str(el.get('text') or '')]
    for row in (el.get('rows') or []):
        parts += [str(c) for c in (row if isinstance(row, list) else [row])]
    parts.append(str((el.get('location') or {}).get('quote') or ''))
    return '\n'.join(parts).lower()

TEXT_KINDS = ('paragraph', 'heading', 'list_item', 'caption', 'code')

# 默认阈值（`dictionary.yaml` 的 `material_quality:` 段按名覆盖；**代码里这份只是兜底**）
DEFAULTS = {
    'min_lines': 30,            # 少于这么多行不判（样本太小）
    'garbled_single_ratio': 0.75,   # 单字行占比 ≥ 它 → 判垃圾（竖排碎片主导）
    'garbled_mean_line_len': 2.0,   # 平均行长 < 它 → 判垃圾
    'noisy_single_ratio': 0.25,     # 单字行占比 ≥ 它 → 判"有保留"（真内容里混着碎片）
    'bad_char_ratio': 0.02,         # 替换字符 / 控制字符 / 私用区 占比 ≥ 它 → 判垃圾
    'dominant_char_ratio': 0.6,     # 单一字符占比 ≥ 它 → 判"有保留"（表格线 / 点线噪声）
    'element_min_lines': 3,         # 元素级：行数 ≥ 它就按下面的比例丢纯碎片
    'element_single_ratio': 0.75,   # 元素级：单字行占比 ≥ 它 → 这条是纯碎片，丢
}
DICT_NAME = 'dictionary.yaml'


def load_thresholds(path=None):
    """阈值 = 默认 + `dictionary.yaml` 的 `material_quality:` 段（读不到就用默认，**不报错**）。

    读不到不报错是有意的：判据是"锦上添花的一道门"，不是主链依赖；缺 PyYAML / 缺字典时
    退化成内置默认，比让整条解析链停下来更合算。
    """
    th = dict(DEFAULTS)
    p = Path(path) if path else Path(__file__).with_name(DICT_NAME)
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            got = (yaml.safe_load(fh) or {}).get('material_quality') or {}
    except Exception:                                  # 缺依赖 / 缺文件 / 坏 YAML：一律退回默认
        return th
    for k, v in got.items():
        if k in th and isinstance(v, (int, float)) and not isinstance(v, bool):
            th[k] = v
    return th


def _bad_char(ch):
    """替换字符 / 控制字符 / 私用区：乱码常落在这三类里。"""
    o = ord(ch)
    return (ch == '\ufffd' or o < 0x20 or 0x7f <= o <= 0x9f
            or 0xe000 <= o <= 0xf8ff or 0xf0000 <= o <= 0x10fffd)


def stats(elements):
    """文字类元素 → 读数（人可核）：行 / 字 / 单字行 / 平均行长 / 坏字符 / 单一字符占比。"""
    chars = lines = single = bad = 0
    freq = {}
    for e in elements:
        if e.get('kind') not in TEXT_KINDS:
            continue
        for raw in str(e.get('text') or '').splitlines():
            line = raw.strip()
            if not line:
                continue
            lines += 1
            if len(line) == 1:
                single += 1
            for ch in line:
                if ch.isspace():
                    continue
                chars += 1
                if _bad_char(ch):
                    bad += 1
                freq[ch] = freq.get(ch, 0) + 1
    top = max(freq.values()) if freq else 0
    return {'chars': chars, 'lines': lines, 'single_lines': single,
            'single_ratio': single / lines if lines else 0.0,
            'mean_line_len': chars / lines if lines else 0.0,
            'bad_chars': bad, 'bad_ratio': bad / chars if chars else 0.0,
            'dominant_ratio': top / chars if chars else 0.0}


def _why(s, extra=''):
    """读数 → 人话（**判据要能被人复核**：比例后面永远跟上原始计数）。"""
    return (f'单字行 {s["single_ratio"]:.0%}（{s["single_lines"]}/{s["lines"]}）· '
            f'平均行长 {s["mean_line_len"]:.1f} 字 · 坏字符 {s["bad_ratio"]:.1%}'
            f'（{s["bad_chars"]}/{s["chars"]}）· 最高频字符占比 {s["dominant_ratio"]:.0%}{extra}')


def readout(elements, th=None):
    """一组元素 → **同一句人话形式**的读数（供"丢之前 / 丢之后"两次都打印）。

    为什么要有它（2026-09-18 实测）：`parse` 当场打印的是**丢纯碎片之前**的比例（某份资质 PDF 单字行 62%），
    而账本里留下的是**丢完之后的元素**（重算是 37%）——两个数都真，看的人却会以为读数在说谎。
    所以 `noisy` 那一档必须把两次读数**并排打**：丢前 62% → 丢后 37%（丢掉的 91 行**全部**是单字行）。
    """
    return _why(stats(elements))


def element_is_garbage(el, th):
    """单条元素是不是**纯碎片**（元素级判据；行数门槛比材料级低，因为一条元素可能就几行）。"""
    s = stats([el])
    if s['lines'] < th['element_min_lines']:
        return False
    return s['single_ratio'] >= th['element_single_ratio']


def verdict(elements, th=None):
    """一组元素 → `(级别, 判据说明, 该丢的元素 id)`。级别 ∈ `ok` / `noisy` / `garbled`。

    **只对机器抽出来的文字下判**（vlm 证据是另一档：它本来就标 `inferred`，不按"行"统计）。
    """
    th = dict(th or DEFAULTS)
    s = stats(elements)
    if s['lines'] < th['min_lines']:
        return 'ok', f'样本太小（{s["lines"]} 行 < {th["min_lines"]}）不判', []
    drop = [e.get('id') for e in elements if element_is_garbage(e, th)]
    tail = f' · 纯碎片元素 {len(drop)} 条' if drop else ''
    if s['bad_ratio'] >= th['bad_char_ratio']:
        return 'garbled', _why(s, tail + ' → 坏字符过多'), [e.get('id') for e in elements]
    if s['single_ratio'] >= th['garbled_single_ratio'] or s['mean_line_len'] < th['garbled_mean_line_len']:
        return 'garbled', _why(s, tail + ' → 碎片主导（疑似竖排 / 字距碎裂）'), [e.get('id') for e in elements]
    if s['single_ratio'] >= th['noisy_single_ratio'] or s['dominant_ratio'] >= th['dominant_char_ratio']:
        return 'noisy', _why(s, tail), drop
    return 'ok', _why(s, tail), drop


def scar(elements, why):
    """把"质量有保留"挂到**该材料的每条**上（§2.4 降级必须留痕；与 `parse_pdf` 的采样说明同一口径）。

    为什么要挂在元素上而不是只印在屏幕上：账本是唯一事实源（§2.5），下游（L1 卡片 / 流程表「依据」）
    只读账本——只印在屏幕上，等到引用时就没人知道这条文本层混着竖排碎片了。
    """
    note = f'抽取质量有保留：{why}'
    for e in elements:
        e['degraded'] = (e.get('degraded') + '；' if e.get('degraded') else '') + note
    return len(elements)
