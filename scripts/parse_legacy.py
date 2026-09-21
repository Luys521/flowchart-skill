# -*- coding: utf-8 -*-
r"""parse_legacy.py — legacy（`.doc` / `.xls` / `.ppt`）解析适配器（PIPELINE-SPEC §1.4）：OLE 复合文档 → `elements[]`。

**这一档是全域唯一"承认自己读不动"的地方**（§0 硬约束里最贵的一条）：legacy 二进制格式
**没有纯 Python 的可靠读法**，所以自包含路径 = **外部转换器**（LibreOffice / `soffice`，通用工具，
不是宿主技能）——先转成 OOXML，再交给 `parse_ooxml.py` 抽（§1.1 的 T2 定义就是"转换后可用，
抽完等价 T1"）。所以**不在这里重复实现一遍 docx / xlsx 抽取**：那一步走**子进程 + 产物**
（模块层不许横向 import，与 `selfboot_gen → table_to_dsl` 同一手法）。

三条边界：

1. **材料只读**：转换产物落在系统临时目录，绝不写回材料所在目录（§1.4 硬要求 1）。
2. **缺转换器不假装能读**：该材料出一条**材料层补注**（`status=unreadable` + **可执行**提示），
   不产 element ——材料读不动是**数据事实**，不是仪器故障，所以**退 0**（§1.4"不许静默降级"的另一半：
   也不许把"读不动"报成"命令坏了"）。⚠ 这条只适用于**可选外部工具**（soffice）：缺了它有降级路
   （UTF-16LE 直捞）。缺**必须依赖**（python-docx 那类）是仪器故障、整链退 2 不落盘——
   两件事的判据是"缺了它还有没有自包含的下一步"（D-133，`deps.import_dep` 的 docstring 同款）。
3. **走了哪条路要记账**：成功元素的 `extractor` 写 `soffice+py:docx` / `soffice+py:openpyxl`，
   出处 `location.path` 改回**原材料**路径（内容来自转换副本，但证据指向用户给的那份）。

**没有转换器时不是"读不动"，而是"降级读"**（2026-09-18 盲读实测补，判据见 §1.6）：
OLE 里的正文本身常常就是一段连续的 **UTF-16LE**，**按字节捞 run 就能拿到成段文字**——
这条路**自包含**（只用标准库）、**不可靠**（不解析结构、不保证顺序、可能有缺漏），
所以它**排在转换器之后**，抽出来一律挂 `degraded`、`extractor=py:oletext`，
**并且照样要过 §1.5 的质量门**（抽出来是碎片就还是不入账）。
为什么值得有：实测三份真 OLE 都捞回了成段正文，而且**因此抓到"原件与转述件"的一处真差异**——
只把原件记成"读不动"，那种差异就永远没人看得见。阈值在 `dictionary.yaml` 的 `legacy_text:` 段。

判档**按内容**（§1.2）：OLE 头 `D0 CF 11 E0` 才归本脚本；是 `.doc` 还是 `.xls` **先看 OLE 目录里的
流名**（`WordDocument` / `Workbook` / `PowerPoint Document`），取不到才退到扩展名——改名件不骗人。

退出码：0 = 跑完（**可能有读不动的材料**，逐份给了原因与提示）；2 = 输入读不了（materials JSON 缺失/坏）。
"""
import argparse
import json
import locale
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from semantics import DICT_NAME
import thresholds

# OLE 复合文档头（§1.2 的魔数判据）
OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

# ---- 自包含降级读法（`legacy_text`）的默认阈值：**代码里这份只是兜底**，家在 `dictionary.yaml` ----
DEFAULT_TH = {
    'min_run': 24, 'min_word_ratio': 0.5, 'max_low0_ratio': 0.4, 'min_common_ratio': 0.85,
    'max_markup_ratio': 0.25,
    'min_chars': 200, 'max_chars': 2000, 'max_elements': 200, 'max_scan_bytes': 33554432,
    'join_gap': 64,
}
OLETEXT_EXTRACTOR = 'py:oletext'
OLETEXT_CAVEAT = ('py:oletext 降级抽取（只捞 UTF-16LE 文本 run：不解析结构、不保证顺序；'
                  '**别的语言的 run**（内嵌 XML / 域代码）已按判据丢掉，'
                  '流名 / 属性串这类短 run 靠长度下限挡着——仍可能漏进几条，别当正文）')

# ---- 「不是正文」的两种**可判**形态（D-109）--------------------------------------------------
# 判据只认"**自己有语法的两种东西**"，不做"读起来不像人话"的猜测——后者是理解，归 AI（§0.1）。
# 两条都要求**结构证据**，所以它能进 `dictionary.yaml` 当阈值，而不必靠人逐个盯。
MARKUP_TAG_RE = re.compile(r'</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>')
FIELD_CODE_RE = re.compile(r'^\s*(?:PAGE|NUMPAGES|DATE|TIME|TOC|HYPERLINK|MERGEFIELD|REF|SEQ'
                           r'|INCLUDEPICTURE|INCLUDETEXT|AUTHOR|FILENAME|STYLEREF|IF|BEGIN|END)'
                           r'\b[\s\\*"]')

# OLE 目录里的流名 → 该用哪个 OOXML 读取器（UTF-16LE 存，按字节找；**按内容判，不看扩展名**）
OLE_STREAMS = (
    (b'W\x00o\x00r\x00d\x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t', 'docx'),
    (b'W\x00o\x00r\x00k\x00b\x00o\x00o\x00k', 'xlsx'),
    (b'P\x00o\x00w\x00e\x00r\x00P\x00o\x00i\x00n\x00t\x00 \x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t', 'pptx'),
)
# 内容标记取不到时的**兜底**（目录扇区可能在探测窗口之外）：扩展名只是先验，不作结论
OLE_EXT = {'.doc': 'docx', '.xls': 'xlsx', '.ppt': 'pptx'}
# 我认的转换目标：三种 OOXML。**`.pptx` 现在也算**——本仓已有零依赖的 pptx 读取器
# （公共层 `pptx_text` + `parse_ooxml.parse_pptx`），所以 `.ppt` 转出来有人读得动（2026-09-18 修）。
TARGET_OF = {'docx': 'docx', 'xlsx': 'xlsx', 'pptx': 'pptx'}
EXTRACTOR_OF = {'docx': 'py:docx', 'xlsx': 'py:openpyxl', 'pptx': 'py:pptx'}
# 认出来的族 → 人话（**提示里要指名族**，用户才知道该另存为什么；实测真样本是 WPS 产的 .wps，
# 它其实是 Word 97-2003 族，泛泛说"另存为 OOXML"等于没说）
FAMILY_CN = {'docx': 'Word 97-2003（OLE 里有 `WordDocument` 流）',
             'xlsx': 'Excel 97-2003（有 `Workbook` 流）',
             'pptx': 'PowerPoint 97-2003（有 `PowerPoint Document` 流）'}
STREAM_WINDOW = 2 << 20                      # 找流名只看前 2 MB（OLE 目录在最前面，够用且不整份读）

CONVERTER_NAMES = ('soffice', 'soffice.exe', 'libreoffice')
CONVERTER_PATHS = (
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    '/usr/bin/soffice', '/usr/local/bin/soffice', '/opt/libreoffice/program/soffice',
    '/Applications/LibreOffice.app/Contents/MacOS/soffice',
)
NO_CONVERTER = ('legacy 二进制没有纯 Python 可靠读法，自包含侧也没探到外部转换器：'
                '装 LibreOffice（`soffice`）后重跑')


def no_converter_reason(kind):
    """缺转换器时的**按族给话**：这份是什么、最省事的下一步是什么。

    为什么值得分开写：真样本实测（`关于韶关…告知函.wps`，WPS 产出）——它是 Word 97-2003 族，
    用户最省事的动作是**用 WPS 直接另存为 .docx**，而不是去装一个多半不认 Kingsoft 格式的 LibreOffice。
    泛泛的"另存为 OOXML"等于没说（用户不知道该存成哪个）。
    """
    fam = FAMILY_CN.get(kind, 'OLE 复合文档')
    return (f'{NO_CONVERTER}。这份是 **{fam}**：最省事的是**用原程序另存为 .{kind}** '
            f'（存完就是 T1，直读）；或在装了 LibreOffice 的环境里重跑本链')


def _read_json(path):
    """读 JSON（容忍 BOM）。"""
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _head(path, n):
    """前 n 字节；读不动返回空（调用方按读不动记账，不崩）。"""
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def ole_kind(path):
    """OLE 复合文档 → `'docx'` / `'xlsx'` / `'pptx'`；不是 OLE 或判不出返回 None（**不猜**）。"""
    path = Path(path)
    if _head(path, 8) != OLE_MAGIC:
        return None
    blob = _head(path, STREAM_WINDOW)
    for marker, kind in OLE_STREAMS:
        if marker in blob:
            return kind
    return OLE_EXT.get(path.suffix.lower())          # 兜底：扩展名只是先验（§1.2 第 1 条）


# ----------------------------------------------------------------外部转换器探测（§1.4 判据）
def _argv_of(explicit):
    """`--soffice` 的取值 → argv 前缀。**存在就整条当路径**（躲开 `C:\\Program Files\\...` 里的空格），
    否则按命令行拆（允许 `python 我的包装器.py` 这类自定义转换器）——
    拆分用 `posix=False`：POSIX 规则会把 Windows 路径里的 `\\` 当转义符吃掉（实测 `C:\\a\\b.py` → `C:ab.py`），
    拆完再把两端的引号剥掉（`posix=False` 保留引号，是为让带空格的整段不被再切一刀）。
    """
    p = Path(explicit)
    try:
        if p.is_file():
            return [str(p)]
    except OSError:
        pass
    out = []
    for tok in shlex.split(explicit, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in '"\'':
            tok = tok[1:-1]
        out.append(tok)
    return out


def _decode(blob):
    """外部转换器的输出 → 文本。**不能假定它说 UTF-8**：Windows 上的 soffice 往管道里写本地编码
    （实测 GBK），硬按 utf-8 解会把版本说明变成乱码（我们自己的脚本能 `reconfigure`，别人的不能）。
    先 utf-8、再本地首选编码、最后 replace——只影响给人看的那几行，不影响任何判定。
    """
    if isinstance(blob, str):
        return blob
    for enc in ('utf-8', locale.getpreferredencoding(False)):
        try:
            return blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return blob.decode('utf-8', errors='replace')


def _runs(argv, timeout, version=True):
    """跑一次 `<转换器> --version` → `(退出码, 输出)`；起不来返回 (None, 原因)。"""
    try:
        r = subprocess.run(list(argv) + (['--version'] if version else []),
                           capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f'{type(e).__name__}: {e}'
    return r.returncode, _decode((r.stdout or b'') + (r.stderr or b'')).strip()


def find_converter(explicit, timeout=60):
    """探测外部转换器 → `(argv 前缀, 版本说明, 报错文案)`。

    判据照 §1.4：**`--version` 能通**（退出码 0）才算有——文件存在不等于能跑（缺 DLL 的 soffice
    多得很），所以不许只 `which` 一下就当真。一个都探不到 → argv 为 None（调用方记读不动 + 提示）。
    """
    if explicit:
        cands = [_argv_of(explicit)]
    else:
        found = [shutil.which(n) for n in CONVERTER_NAMES]
        cands = ([[p] for p in found if p] +
                 [[p] for p in CONVERTER_PATHS if Path(p).is_file()])
    tried = []
    for argv in cands:
        rc, out = _runs(argv, timeout)
        if rc == 0:
            return argv, ' '.join(out.split())[:80], ''
        tried.append(f'{" ".join(argv)} → {out}')
    if explicit:
        return None, '', f'--soffice 指定的转换器跑不通（--version 非 0 或起不来）：{tried[0] if tried else explicit}'
    return None, '', ''


def convert(argv, src, target, outdir, timeout):
    """`<转换器> --headless --convert-to <target> --outdir <dir> <材料>` → `(产物路径, 报错文案)`。

    产物名**不假定**等于材料名：soffice 各版本对 `.doc`（老 Word 二进制）的出名不完全一致，
    所以先按 `<stem>.<target>` 找，找不到就退到"目录里唯一的 `.<target>`"，都找不到才报错——
    **退 0 却没产出**要当场说清，不许让下游拿到空 elements 还以为是空材料。

    **调用方必须给本份材料一个独立 outdir**（`parse_materials` 按序号建子目录，G27）：
    "目录里唯一的 .<target>"这条兜底只在**独享目录**下才安全——共享目录里它会把上一份的产物
    当成这一份的正文（转换失败时静默串料）。
    """
    cmd = list(argv) + ['--headless', '--norestore', '--convert-to', target,
                        '--outdir', str(outdir), str(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f'转换超时（>{timeout} 秒）'
    except (OSError, subprocess.SubprocessError) as e:
        return None, f'转换起不来 {type(e).__name__}: {e}'
    suffix = '.' + target
    hits = sorted(p for p in Path(outdir).iterdir() if p.is_file() and p.suffix.lower() == suffix)
    exact = [p for p in hits if p.stem == Path(src).stem]
    if exact:
        return exact[0], ''
    if len(hits) == 1:
        return hits[0], ''
    tail = ' '.join(_decode((r.stdout or b'') + (r.stderr or b'')).split())[-200:]
    if r.returncode != 0:
        return None, f'转换器退 {r.returncode}：{tail}'
    return None, f'转换器退 0 但没产出 {Path(src).stem}{suffix}（目录里有 {len(hits)} 个 {suffix}）：{tail}'


def extract_via_ooxml(converted, mid, original, timeout):
    """子进程调 `parse_ooxml.py` 抽转换产物 → `(elements, 报错文案)`；出处改回原材料。

    **为什么要改 `location.path`**：证据必须指向用户给的那份材料（§2.3 的 `path` 是出处），
    转换副本是中间物、跑完就随临时目录消失——留着它，账本上就是一条指向不存在文件的引用。
    `extractor` 前面加 `soffice+`：走的是"先转换再读"这条路，与直读要能分辨（§1.4 最后一条）。
    """
    script = Path(__file__).resolve().parent / 'parse_ooxml.py'
    with tempfile.TemporaryDirectory(prefix='parse_legacy_') as td:
        mp, ep = Path(td) / 'materials.json', Path(td) / 'elements.json'
        mp.write_text(json.dumps([{'id': mid, 'path': Path(converted).as_posix(),
                                   'tier': 'T1', 'status': 'ok'}], ensure_ascii=False),
                      encoding='utf-8', newline='\n')
        try:
            r = subprocess.run([sys.executable, str(script), '--materials', str(mp), '-o', str(ep)],
                               capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            return None, f'调 parse_ooxml 起不来 {type(e).__name__}: {e}'
        if r.returncode != 0 or not ep.is_file():
            tail = ' '.join(((r.stdout or '') + (r.stderr or '')).split())[-200:]
            return None, f'parse_ooxml 退 {r.returncode}：{tail}'
        got = json.loads(ep.read_text(encoding='utf-8'))
    for e in got:
        e['location']['path'] = original
        e['extractor'] = 'soffice+' + e.get('extractor', 'py:?')
    return got, ''


# ----------------------------------------------------------------自包含降级读法（§1.6）
def load_thresholds(path=None):
    """阈值 = 内置默认 + `dictionary.yaml` 的 `legacy_text:` 段（**读取口径只有一处**：`thresholds.load`）。

    读不到不报错是有意的（见 `thresholds.py` 文件头）：这是"多一条降级路"，不是主链依赖。
    """
    return thresholds.load('legacy_text', DEFAULT_TH, path)


def _is_text_unit(ch):
    """这个字符**像正文**吗（拿它当 run 的粘合剂）。

    **宽进**是故意的：run 的边界要落在真噪声上（二进制控制符 / 替换字符 / 未配对代理被解成 `\\ufffd`），
    而不是落在标点或制表符上——不然一段正常的话会被切成十几条碎片。误收的噪声由 `_word_ratio`
    与 §1.5 的质量门兜住（两道都在）。
    """
    o = ord(ch)
    return (ch in '\t\n\r' or 0x20 <= o <= 0x7e
            or 0xa0 <= o <= 0x2fff                      # 拉丁补充 / 标点 / 箭头 / 制表符
            or 0x3000 <= o <= 0x303f or 0x3400 <= o <= 0x4dbf
            or 0x4e00 <= o <= 0x9fff or 0xf900 <= o <= 0xfaff
            or 0xfe30 <= o <= 0xfe4f or 0xff00 <= o <= 0xffef)


def _is_word(ch):
    """算不算"字"（判 run 像不像正文用）：中日韩 + 字母 + 数字。"""
    o = ord(ch)
    return ch.isalnum() or 0x3400 <= o <= 0x4dbf or 0x4e00 <= o <= 0x9fff


def _word_ratio(text):
    return sum(1 for ch in text if _is_word(ch)) / len(text) if text else 0.0


def _low0_ratio(text):
    """码位**低字节恒为 0** 的比例——这是"单字节二进制被当成 UTF-16LE 读"的指纹。

    为什么它够格当判据：真 UTF-16LE 正文里，低字节与高字节一样是变的（中日韩两字节都有值，
    ASCII 是"低字节=字符、高字节=0"）；而把**单字节**流按两字节读时，形如 `00 3A 00 3C …` 的字节对
    会解成一串"低字节全是 0"的怪字（实测抓到一条：`Ȁ㨀㰀䠀䨀怀戀搀琀瘀砀稀踀退鈀鐀鸀`——
    每个字看起来都是合法汉字，`isalnum()` 全过，只有这个比例能一眼看穿）。
    """
    return sum(1 for ch in text if ord(ch) & 0xFF == 0) / len(text) if text else 0.0


def _is_common(ch):
    """"常用字面"：ASCII / 拉丁补充 / 常用标点 / 中日韩与全角——**真正文几乎全落在这一片里**。"""
    o = ord(ch)
    return (ch in '\t\n\r' or 0x20 <= o <= 0x7e or 0xa0 <= o <= 0x24f
            or 0x2000 <= o <= 0x206f or 0x3000 <= o <= 0x303f
            or 0x3400 <= o <= 0x4dbf or 0x4e00 <= o <= 0x9fff
            or 0xf900 <= o <= 0xfaff or 0xfe30 <= o <= 0xfe4f or 0xff00 <= o <= 0xffef)


def _common_ratio(text):
    """常用字面占比——用来丢"字符撒在几十个文种里"的高熵噪声（那些也是二进制，只是碰巧合了法）。

    与 `_word_ratio` 分工：后者防"纯符号"，前者防"什么文种的字都有"（实测抓到一条混杂希腊 / 西里尔 /
    阿拉伯 / 天城文 / 泰文的 run——单个字符全合法，连起来不是任何一种语言）。
    """
    return sum(1 for ch in text if _is_common(ch)) / len(text) if text else 0.0


def _noise_reason(text, th):
    """这段 run 是不是**可判的非正文** → 理由（不是就返回空串）。

    为什么值得加这一道（D-109）：`py:oletext` 是"按字节捞文本"，它**分不清**正文与
    文档里另外两种**有自己语法**的东西——内嵌的 XML（`<w:WordDocument>…`）与 Word 的域代码
    （`PAGE \\* MERGEFORMAT`）。它们长度够、字符也"像字"，前四道判据全过，于是混进账本，
    下游「依据」一引就是一段标签。两种形态**机器一眼能认**，所以它们该被挡在这里，
    而不是留给 AI 在几百条 run 里自己挑。

    **窄**是刻意的：只认这两种有结构证据的；"读起来不像正文"不判（那是理解，归 AI）。
    """
    if MARKUP_TAG_RE.search(text):
        covered = sum(len(m.group(0)) for m in MARKUP_TAG_RE.finditer(text))
        if covered / len(text) >= th['max_markup_ratio']:
            return '内嵌 XML'
    if FIELD_CODE_RE.match(text):
        return '域代码'
    return ''


def _emit(out, buf, start, th, drops=None):
    """一条 run 收尾：**够长 · 够"像正文" · 不是错位读的怪字 · 不是多种文字混在一起的高熵噪声 ·
    不是别的语言（内嵌 XML / 域代码）**才留。**丢掉的按理由计数**（`drops`），理由要能说出来。

    **"别的语言"排在长度前面判**：一段 18 字的 `PAGE \\* MERGEFORMAT` 被记成"太短"虽然也对，
    可它真正的问题是"它是域代码"，不是"它短"——计数要按**最能说明问题的那条理由**归。
    """
    s = ''.join(buf).strip()
    if not s:
        return out
    why = _noise_reason(s, th)
    if not why and len(s) < th['min_run']:
        why = '太短'
    if not why and not (_word_ratio(s) >= th['min_word_ratio']
                        and _low0_ratio(s) <= th['max_low0_ratio']
                        and _common_ratio(s) >= th['min_common_ratio']):
        why = '不像正文（符号 / 错位读 / 多文种混杂）'
    if why:
        if drops is not None:
            drops[why] = drops.get(why, 0) + 1
        return out
    out.append((start, s))
    return out


def _runs_at(blob, shift, th, drops=None):
    """按 `shift` 字节对齐扫一遍 → `[(字节偏移, 文本)]`。"""
    text = blob[shift:].decode('utf-16-le', errors='replace')
    out, buf, start = [], [], shift
    for i, ch in enumerate(text):
        if _is_text_unit(ch):
            if not buf:
                start = shift + 2 * i
            buf.append(ch)
            continue
        _emit(out, buf, start, th, drops)
        buf = []
    return _emit(out, buf, start, th, drops)


def runs_of(path, th=None):
    """OLE 原始字节 → `(run 列表, 说明)`。**两种对齐都扫**：正文 run 未必从偶数字节开始。

    `说明` 里除了"扫了多少字节"，还要报**按理由丢了多少条**（D-109）：这两种 run（内嵌 XML /
    域代码）是"文档里另外两种语言"，用户看到账本里没有它们时该知道**是判据丢的**，
    而不是以为原件里没有——降级留痕（§2.4）在这一层同样算数。
    """
    th = dict(th or DEFAULT_TH)
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return [], f'读不动（{type(e).__name__}: {e}）'
    cap = max(2, int(th['max_scan_bytes']))
    cut = len(data) > cap
    blob = data[:cap]
    drops = {}
    cand = _runs_at(blob, 0, th, drops) + _runs_at(blob, 1, th, drops)
    # 同一段正文会被两种对齐各命中一次（一次真解、一次错位半格）：按字节区间去重，**留更长的那条**。
    cand.sort(key=lambda r: (r[0], -len(r[1])))
    kept = []
    for off, text in cand:
        end = off + 2 * len(text)
        if any(not (end <= a or off >= b) for a, b, _t in kept):
            continue
        kept.append((off, end, text))
    bits = []
    if cut:
        bits.append(f'只扫了前 {cap // 1048576} MiB（材料共 {len(data) / 1048576:.1f} MiB）')
    # 只报"**别的语言**"那两类：其余理由（太短 / 不像正文）是判据的常态，条数以千计，报出来是噪声。
    for why in ('内嵌 XML', '域代码'):
        if drops.get(why):
            bits.append(f'丢掉{why} {drops[why]} 条')
    return [(o, t) for o, _e, t in kept], '；'.join(bits)


def fallback_elements(mid, path, runs, th, note=''):
    """run 列表 → `elements[]`：**并相邻 run → 按 `max_chars` 切块 → 每条挂降级说明**。

    `degraded` 挂在这里而不是只印在屏幕上：账本是唯一事实源（§2.5），下游只读账本——
    "这条是从二进制里捞出来的文本 run"必须跟着证据走，否则引用它的人不知道它不解析结构。
    """
    groups, cur, used = [], [], 0
    for off, text in runs:
        prev_end = cur[-1][0] + 2 * len(cur[-1][1]) if cur else 0   # runs 的元素是 (起点, 文本)，不是 (起, 止)
        if cur and (off - prev_end > th['join_gap'] or used + len(text) > th['max_chars']):
            groups.append(cur)
            cur, used = [], 0
        cur.append((off, text))
        used += len(text)
    if cur:
        groups.append(cur)
    out = []
    for g in groups[:int(th['max_elements'])]:
        body = '\n'.join(t for _o, t in g).strip()
        if not body:
            continue
        cut = len(body) > th['max_chars']
        if cut:
            body = body[:int(th['max_chars'])] + '…'
        degraded = OLETEXT_CAVEAT + (f'；{note}' if note else '')
        if cut:
            degraded += f'；正文截断到 {int(th["max_chars"])} 字'
        out.append({'id': f'{mid}#o{len(out) + 1:03d}', 'material_id': mid, 'kind': 'paragraph',
                    'text': body, 'location': {'path': path.as_posix(), 'quote': body},
                    'extractor': OLETEXT_EXTRACTOR, 'certainty': 'direct', 'degraded': degraded})
    # **判据是"上限截断"**（G73）：原先写 `len(groups) > len(out)`，而 `out` 比 `groups[:cap]` 少
    # 还可能因为**空组被跳过**（`if not body: continue`）——于是"只收前 N 个"这句会为"跳过空组"报出来，
    # 两种原因读的人分不清。按上限判，说的是同一件事。
    if len(groups) > int(th['max_elements']):
        for e in out:
            e['degraded'] += f'；只收前 {int(th["max_elements"])} 组（捞到的 run 还有更多）'
    return out


def parse_legacy(path, mid, argv, workdir, timeout, th=None):
    """一份 legacy 材料 → `(elements, 材料补注, 跳过说明, 报错文案)`。

    三种结局都要**落到账上**：转成功（产 element + 补注 extractor）、**降级读出正文**（同上，但 extractor
    记 `py:oletext`、逐条挂 `degraded`）、真的捞不出来（记读不动 + 可执行提示）。
    """
    th = dict(th or DEFAULT_TH)
    kind = ole_kind(path)
    if kind is None:
        return [], None, '', ''
    why = ''
    if argv is not None:
        target = TARGET_OF[kind]
        converted, err = convert(argv, path, target, workdir, timeout)
        if err:
            why = f'转换失败（{err}）'
        else:
            got, err = extract_via_ooxml(converted, mid, path.as_posix(), timeout)
            if not err:
                note = {'material_id': mid, 'extractor': f'soffice+{EXTRACTOR_OF.get(target, "py:?")}'}
                return got, note, f'{mid}({kind}→{target}) {len(got)}', ''
            why = f'转换产物读不了（{err}）'
    else:
        why = '本机没探到外部转换器（soffice）'
    # 转换器这条路走不通 → **降级读**（§1.6）：捞 UTF-16LE 文本 run；捞不出来才记读不动
    runs, scan = runs_of(path, th)
    total = sum(len(t) for _o, t in runs)
    if total >= th['min_chars']:
        got = fallback_elements(mid, path, runs, th, scan)
        if got:
            note = {'material_id': mid, 'status': 'ok', 'extractor': OLETEXT_EXTRACTOR}
            return got, note, f'{mid}({kind}·降级 {total} 字) {len(got)}', ''
    return [], {'material_id': mid, 'status': 'unreadable',
                'reason': (f'{why}；降级读（UTF-16LE 文本 run）也只捞出 {total} 字'
                           f'（少于 {th["min_chars"]}）。{no_converter_reason(kind)}')}, \
        f'{mid}: 读不动', ''


def parse_materials(materials, argv, timeout, th=None):
    """材料层 → `(elements, 材料补注, 摘要, 跳过清单, 报错文案)`。只认 OLE；别的材料**不归我管**（不给补注）。"""
    th = dict(th or DEFAULT_TH)
    elements, notes, done, skipped = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='parse_legacy_out_') as workdir:
        for i, m in enumerate(materials):
            mid = m.get('id', '?')
            path = Path(m.get('path', ''))
            if m.get('status') != 'ok':
                skipped.append(f'{mid}: status={m.get("status")}（不解析）')
                continue
            # **每份材料一个独立子目录**（G27）：整批共用一个 outdir 时，`convert` 的
            # "目录里唯一的 .<target>"兜底会把**上一份**的产物当成这一份的正文——
            # 转换失败（退 1、无产出）时静默串料，账本上 M02 的证据实际是 M01 的正文。
            # 独立子目录让"唯一命中"只可能是本份自己的产物（soffice 出名不一致时仍旧成立）。
            sub = Path(workdir) / f'{i:03d}'
            sub.mkdir()
            try:
                got, note, line, err = parse_legacy(path, mid, argv, sub, timeout, th)
            except Exception as e:                       # 单份坏不让整批失败
                skipped.append(f'{mid}: 解析失败 {type(e).__name__}: {e}')
                continue
            if err:
                return None, notes, done, skipped, err
            if not line:
                continue                                 # 不是 OLE：留给别的适配器，不记账
            elements += got
            if note:
                notes.append(note)
            (done if got else skipped).append(line)
    return elements, notes, done, skipped, ''


def _write_json(obj, path):
    """写 JSON：UTF-8 / LF / 缩进 2 / 中文不转义（与账本同一套写盘口径，见 ledger.dump）。"""
    Path(path).write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='legacy 解析适配器：.doc / .xls / .ppt → elements[]（走外部转换器）')
    ap.add_argument('--materials', required=True, help='材料层 JSON（probe.py --json 的输出）')
    ap.add_argument('-o', '--out', help='写到哪里（默认 stdout，供管道接 ledger）')
    ap.add_argument('--notes', help='材料层补注写到哪里（status / reason / extractor，交给 ledger.py --notes）')
    ap.add_argument('--soffice', help='显式指定转换器命令（默认识别 PATH 与常见安装位置；判据仍是 --version 能通）')
    ap.add_argument('--timeout', type=int, default=180, help='单份材料的转换 / 抽取超时秒数')
    ap.add_argument('--dict', help=f'{DICT_NAME}（默认取 scripts/ 下那份；`legacy_text:` 段的阈值）')
    a = ap.parse_args(argv)

    try:
        materials = _read_json(a.materials)
    except (OSError, ValueError) as e:
        print(f'⚠ 输入读不了: {e}', file=sys.stderr)
        return 2
    if not isinstance(materials, list):
        print('⚠ 输入必须是 JSON 数组（materials[]）', file=sys.stderr)
        return 2

    started = time.monotonic()
    th = load_thresholds(a.dict)
    conv, version, err = find_converter(a.soffice, a.timeout)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2
    if conv is None:
        print('ℹ 没探到外部转换器（soffice）：legacy 材料走**自包含降级读法**（捞 UTF-16LE 文本 run，'
              '逐条挂 degraded）；捞不出正文的才记读不动 + 可执行提示（§1.4「都没有时」那一列 + §1.6）',
              file=sys.stderr)
    else:
        print(f'ℹ 转换器：{" ".join(conv)}（{version or "版本未报"}）', file=sys.stderr)

    elements, notes, done, skipped, err = parse_materials(materials, conv, a.timeout, th)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2

    text = json.dumps(elements, ensure_ascii=False, indent=2) + '\n'
    if a.out:
        Path(a.out).write_bytes(text.encode('utf-8'))
        where = a.out
    else:
        sys.stdout.write(text)
        where = 'stdout'
    if a.notes:
        _write_json(notes, a.notes)
    print(f'→ 已写出 {where}：元素 {len(elements)} · 解析 {len(done)} 份 · 读不动/跳过 {len(skipped)} 份'
          f' · 补注 {len(notes)} 条 · 耗时 {time.monotonic() - started:.1f}s', file=sys.stderr)
    for s in skipped:
        print(f'  · {s}', file=sys.stderr)
    if a.notes:
        for n in notes:
            if n.get('status') == 'unreadable':
                print(f'  · 读不动 {n["material_id"]}：{n["reason"]}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
