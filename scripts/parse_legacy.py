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
   也不许把"读不动"报成"命令坏了"）。
3. **走了哪条路要记账**：成功元素的 `extractor` 写 `soffice+py:docx` / `soffice+py:openpyxl`，
   出处 `location.path` 改回**原材料**路径（内容来自转换副本，但证据指向用户给的那份）。

判档**按内容**（§1.2）：OLE 头 `D0 CF 11 E0` 才归本脚本；是 `.doc` 还是 `.xls` **先看 OLE 目录里的
流名**（`WordDocument` / `Workbook` / `PowerPoint Document`），取不到才退到扩展名——改名件不骗人。

退出码：0 = 跑完（**可能有读不动的材料**，逐份给了原因与提示）；2 = 输入读不了（materials JSON 缺失/坏）。
"""
import argparse
import json
import locale
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# OLE 复合文档头（§1.2 的魔数判据）
OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'

# OLE 目录里的流名 → 该用哪个 OOXML 读取器（UTF-16LE 存，按字节找；**按内容判，不看扩展名**）
OLE_STREAMS = (
    (b'W\x00o\x00r\x00d\x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t', 'docx'),
    (b'W\x00o\x00r\x00k\x00b\x00o\x00o\x00k', 'xlsx'),
    (b'P\x00o\x00w\x00e\x00r\x00P\x00o\x00i\x00n\x00t\x00 \x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t', 'pptx'),
)
# 内容标记取不到时的**兜底**（目录扇区可能在探测窗口之外）：扩展名只是先验，不作结论
OLE_EXT = {'.doc': 'docx', '.xls': 'xlsx', '.ppt': 'pptx'}
# 我认的转换目标：OOXML 三种；.pptx 本仓**还没有读取器**（python-pptx 是可选依赖，未落地）
TARGET_OF = {'docx': 'docx', 'xlsx': 'xlsx'}
STREAM_WINDOW = 2 << 20                      # 找流名只看前 2 MB（OLE 目录在最前面，够用且不整份读）

CONVERTER_NAMES = ('soffice', 'soffice.exe', 'libreoffice')
CONVERTER_PATHS = (
    r'C:\Program Files\LibreOffice\program\soffice.exe',
    r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
    '/usr/bin/soffice', '/usr/local/bin/soffice', '/opt/libreoffice/program/soffice',
    '/Applications/LibreOffice.app/Contents/MacOS/soffice',
)
NO_CONVERTER = ('legacy 二进制没有纯 Python 可靠读法，自包含侧也没探到外部转换器：'
                '装 LibreOffice（`soffice`）后重跑，或把材料另存为 .docx / .xlsx')
NO_PPTX = ('这里拿到的是**转换出来的临时** pptx，账本不回填它：本仓的 .pptx 读取器在 `parse_ooxml` '
           '那条路上（材料里的 .pptx 直接走 T1）。把 .ppt 另存为 .pptx 后作为材料重投即可')


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
                      encoding='utf-8')
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


def parse_legacy(path, mid, argv, workdir, timeout):
    """一份 legacy 材料 → `(elements, 材料补注, 跳过说明, 报错文案)`。

    三种结局都要**落到账上**：转成功（产 element + 补注 extractor）、转失败/缺转换器、判不出类型。
    """
    kind = ole_kind(path)
    if kind is None:
        return [], None, '', ''
    if kind not in TARGET_OF:
        return [], {'material_id': mid, 'status': 'unreadable', 'reason': NO_PPTX}, f'{mid}: pptx', ''
    if argv is None:
        return [], {'material_id': mid, 'status': 'unreadable', 'reason': NO_CONVERTER}, \
            f'{mid}: 缺转换器', ''
    target = TARGET_OF[kind]
    converted, err = convert(argv, path, target, workdir, timeout)
    if err:
        return [], {'material_id': mid, 'status': 'unreadable',
                    'reason': f'转换失败（{err}）：装/修 LibreOffice，或把材料另存为 .{target}'}, \
            f'{mid}: 转换失败', ''
    got, err = extract_via_ooxml(converted, mid, path.as_posix(), timeout)
    if err:
        return [], {'material_id': mid, 'status': 'unreadable',
                    'reason': f'转换产物读不了（{err}）：材料可能已损坏，请人工核对'}, \
            f'{mid}: 转换产物读不了', ''
    note = {'material_id': mid, 'extractor': f'soffice+py:{"docx" if target == "docx" else "openpyxl"}'}
    return got, note, f'{mid}({kind}→{target}) {len(got)}', ''


def parse_materials(materials, argv, timeout):
    """材料层 → `(elements, 材料补注, 摘要, 跳过清单, 报错文案)`。只认 OLE；别的材料**不归我管**（不给补注）。"""
    elements, notes, done, skipped = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='parse_legacy_out_') as workdir:
        for m in materials:
            mid = m.get('id', '?')
            path = Path(m.get('path', ''))
            if m.get('status') != 'ok':
                skipped.append(f'{mid}: status={m.get("status")}（不解析）')
                continue
            try:
                got, note, line, err = parse_legacy(path, mid, argv, workdir, timeout)
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
    conv, version, err = find_converter(a.soffice, a.timeout)
    if err:
        print(f'⚠ {err}', file=sys.stderr)
        return 2
    if conv is None:
        print('ℹ 没探到外部转换器（soffice）：legacy 材料一律记读不动 + 可执行提示（§1.4 的"都没有时"那一列）',
              file=sys.stderr)
    else:
        print(f'ℹ 转换器：{" ".join(conv)}（{version or "版本未报"}）', file=sys.stderr)

    elements, notes, done, skipped, err = parse_materials(materials, conv, a.timeout)
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
