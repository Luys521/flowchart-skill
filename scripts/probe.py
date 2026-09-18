# -*- coding: utf-8 -*-
r"""probe.py — 材料探测分档器（PIPELINE-SPEC §1.2）：**按内容**判 T1 / T2 / T3 / T4。

**为什么按内容**：实测同一个目录里两个 `.pdf` 会分属 T2（有文本层）与 T3（扫描件）；
legacy `.doc` / `.xls` 与 `.docx` / `.xlsx` 扩展名像、容器完全不同。按扩展名判必错。

**自包含**（PIPELINE-SPEC §0）：只用标准库读文件头 + 数 PDF 的字体标记，**不装任何东西**。
宿主加速器（本地 Office SDK / 多模态模型）不在这里探测 — 那是解析阶段的事。

只做一件事：把一个路径（文件或目录）变成 `materials[]` 骨架
（`id` / `path` / `sha256` / `bytes` / `mtime` / `tier` / `kind` / `probe` / `status` / `reason`），
供账本写入器消费。**不读内容、不抽 element、不做语义判断**（那是 L1 清点的事）。

`kind` 是**机器可读的材料类型**（§2.1 的封闭枚举）：本仓"这是什么"的唯一判据源就是这里。
别处（侦查 / 适配器 / 渲染）**只许读它，不许按扩展名或魔数重判**——审计实测过：同字节材料换个
文件名（真 docx 改名 `.doc`）会让两处判据给出互相矛盾的结论，而"按内容判"正是 §1.2 的第一条理由。
**一条不变式**：`tier=T1`（可直读）⇒ **必须至少有一个适配器认领**（判据与 reader 同源，见 `sniff`）。

退出码：0 = 探测完成（即使有 T4）；2 = 输入读不了（路径不存在）。
"""
import argparse
import codecs
import hashlib
import sys
import time
import zipfile
from pathlib import Path

# 图片魔数 — 用内容判，防"改扩展名"（PIPELINE-SPEC §1.2）。
IMAGE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'\xff\xd8\xff', 'jpeg'),
    (b'GIF87a', 'gif'),
    (b'GIF89a', 'gif'),
    (b'BM', 'bmp'),
    (b'II*\x00', 'tiff'),
    (b'MM\x00*', 'tiff'),
)

# zip 容器里**真正能被读出来的那个部件** → 具体是哪种 OOXML。
# **为什么必须是确切部件、不能是目录前缀**（审计抓到的真 bug）：原先写 `n.startswith('word/')`，
# 于是一个"有 word/ 目录、却没有 word/document.xml"的包被判 T1 可直读，而 `parse_ooxml` 要的正是
# 那个部件 → 没人认领 → 分派器判"漏认"、整条链退 1、不落盘。**探测的声明必须与读者的射程对齐**：
# 判据跟 reader 用同一句（`parse_ooxml.container_kind` 也认这两个名字）。
OOXML_PARTS = (('word/document.xml', 'docx'), ('xl/workbook.xml', 'xlsx'),
               ('ppt/presentation.xml', 'pptx'))
# 有**自包含读取器**的那两种；其余 OOXML（pptx）按 §1.4 的依赖表降级：可选依赖没装 ⇒ 记 T4 + 可执行提示。
READABLE_OOXML = ('docx', 'xlsx')
NO_READER_REASON = {
    'pptx': '本仓尚无 .pptx 读取器（python-pptx 是**可选**依赖，未落地）：'
            '装 `python -m pip install python-pptx` 并补一个适配器，或把材料另存为 .docx / .xlsx',
}
NO_PART_REASON = ('zip 容器里没有可读的 OOXML 部件（要 word/document.xml 或 xl/workbook.xml）：'
                  '多半是损坏 / 半成品包，请重新导出')

# 材料类型（**机器可读的 kind**，§2.1）：本仓"这是什么"的唯一判据源就是这里，别处不许按扩展名重判
KINDS = ('docx', 'xlsx', 'pptx', 'ole', 'pdf-text', 'pdf-scan', 'image', 'text', 'unknown')

# 判"是不是文本"时读多少字节：8 字节不够——中文一个字 3 字节，正好会被 8 字节的头切断（见 _text_tier）。
TEXT_HEAD = 4096


def _read_head(path, n=8):
    """前 n 字节；读不动就返回空（调用方按 T4 记账，不许崩）。"""
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def _mtime(path):
    """修改时间（ISO 8601 本地时区）；取不到返回空串（不崩）—§3「替代」的末位兜底。"""
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(path.stat().st_mtime))
    except OSError:
        return ''


def _ooxml_kind(path):
    """PK 容器 → `docx` / `xlsx` / `pptx`；不是 OOXML 就返回 None。

    **判据是"确切部件在不在"，不是"目录前缀在不在"**（见 `OOXML_PARTS` 上的那段）：
    前者才等于"有 reader 读得动"。判据与 `parse_ooxml.container_kind` 同源（都认这两个部件名），
    所以 `tier=T1` 才真的意味着"有人认领"。
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    for part, kind in OOXML_PARTS:
        if part in names:
            return kind
    return None


def _pdf_tier(path):
    """PDF：有字体标记 → 有文本层（T2），否则判扫描件（T3）。依据写成 `/Font` 计数，人可核。

    **这是粗判**：正式口径是"抽前 N 页算字符密度"（阈值进 `scripts/dictionary.yaml`）；
    这里先用"有没有字体"当前哨 — 有字体才可能有文本层，没字体必然是扫描件。
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return 'T4', 'PDF 读不动'
    fonts = blob.count(b'/Font')
    if fonts:
        return 'T2', f'PDF 有文本层（/Font x{fonts}）'
    return 'T3', f'PDF 无字体标记（/Font 0, /Image x{blob.count(b"/Image")}）→判扫描件'


def _text_tier(head):
    """能按 UTF-8 解码且无 NUL 字节 → 文本（T1）；否则 None。

    **截断在多字节字符中间也要认**（实测踩到的真 bug）：只看前 8 字节时，"这"（3 字节）会被正好切开，
    于是**合法的中文 `.txt` 被判 T4**（"魔数不认识，且不是文本"）——本仓的材料以中文为主，
    这条误判会成片出现。做法：整段先解一次，失败就**逐字节退**（UTF-8 单字符最多 4 字节），
    退完能解就说明只是尾字节被切断，不是二进制。
    """
    if head[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return 'T1', 'UTF-16 文本（BOM）'                     # **先看 BOM**：UTF-16 正文里满是 NUL 字节
    if not head or b'\x00' in head:                           # （下面的 NUL 判据是给"没 BOM 的二进制"用的）
        return None
    for cut in range(4):
        try:
            (head[:len(head) - cut] if cut else head).decode('utf-8')
            return 'T1', 'UTF-8 文本（无 NUL 字节）'
        except UnicodeDecodeError:
            continue
    return None


def sniff(path):
    """一个文件 → `(tier, probe, status, reason, kind)`。`probe` 是**判据**（人可核），`kind` 是机器可读类型。

    **一条不变式**（审计后加的，§1.2）：**`tier=T1`（可直读）⇒ 必须至少有一个适配器认领**。
    所以这里判 OOXML 时用的部件名与 `parse_ooxml.container_kind` 同源；`pptx` 没有读取器，
    就**不许**说它"可直读"，按 §1.4 的依赖表降级成 T4 + 可执行提示（探测的声明不许比实现的射程宽）。
    判不出不猜：一律 T4 + `unreadable` + 原因（§1.2 第 3 条）。
    """
    path = Path(path)
    head = _read_head(path, 8)
    if not head:
        return 'T4', '空文件或读不动', 'unreadable', '文件为空或不可读', 'unknown'

    if head[:2] == b'PK':
        kind = _ooxml_kind(path)
        if kind in READABLE_OOXML:
            return 'T1', f'PK 容器 + {kind} 可读部件', 'ok', '', kind
        if kind in NO_READER_REASON:                 # pptx：容器认出来了，但**没有 reader**
            return 'T4', f'PK 容器 + {kind}（无读取器）', 'unreadable', NO_READER_REASON[kind], kind
        return 'T4', 'PK 容器但缺可读部件', 'unreadable', NO_PART_REASON, 'unknown'

    if head[:4] == b'\xd0\xcf\x11\xe0':
        return 'T2', 'OLE 复合文档（legacy doc/xls/ppt）', 'ok', '', 'ole'

    if head[:4] == b'%PDF':
        tier, probe = _pdf_tier(path)
        kind = 'pdf-text' if tier == 'T2' else ('pdf-scan' if tier == 'T3' else 'unknown')
        if tier == 'T4':
            return tier, probe, 'unreadable', probe, kind
        return tier, probe, 'ok', '', kind

    for magic, name in IMAGE_MAGIC:
        if head.startswith(magic):
            return 'T3', f'图片魔数（{name}）', 'ok', '', 'image'
    if head[:4] == b'RIFF' and _read_head(path, 16)[8:12] == b'WEBP':
        return 'T3', '图片魔数（webp）', 'ok', '', 'image'

    text = _text_tier(_read_head(path, TEXT_HEAD))       # 判文本要看够多字节（见 _text_tier）
    if text:
        return text[0], text[1], 'ok', '', 'text'

    return 'T4', f'魔数不认识（{head[:4].hex()}）', 'unreadable', '魔数不认识，且不是文本', 'unknown'


def probe_tree(root):
    """路径（文件或目录）→ `materials[]`；目录按**材料路径字典序**编号 `M01`…（PIPELINE-SPEC §0）。"""
    root = Path(root)
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted((p for p in root.rglob('*') if p.is_file()), key=lambda p: p.as_posix())
    else:
        return None

    out = []
    for i, p in enumerate(files, 1):
        tier, probe, status, reason, kind = sniff(p)
        try:
            blob = p.read_bytes()
            sha, size = hashlib.sha256(blob).hexdigest(), len(blob)
        except OSError as e:
            tier, probe, status, reason, kind = ('T4', f'读不动（{type(e).__name__}）',
                                                 'unreadable', str(e), 'unknown')
            sha, size = '', 0
        item = {'id': f'M{i:02d}', 'path': p.as_posix(), 'sha256': sha, 'bytes': size,
                'mtime': _mtime(p), 'tier': tier, 'kind': kind, 'probe': probe, 'status': status}
        if reason:
            item['reason'] = reason
        out.append(item)
    return out


def _print_table(items):
    """人读摘要：一行一份材料。"""
    counts = {}
    for it in items:
        counts[it['tier']] = counts.get(it['tier'], 0) + 1
    print('  '.join(f'{k} x{counts[k]}' for k in sorted(counts)) or '（没有材料）')
    for it in items:
        print(f"  {it['id']}  {it['tier']}  {it['kind']:<9} {it['status']:<10} {it['probe']}")


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')  # 摘要/报错走 stderr，同样要定编码（GBK 控制台会乱码）
    ap = argparse.ArgumentParser(description='材料探测分档（按内容，不按扩展名）')
    ap.add_argument('path', help='材料路径（文件或目录）')
    ap.add_argument('--json', action='store_true', help='输出 materials[] JSON')
    a = ap.parse_args(argv)

    items = probe_tree(a.path)
    if items is None:
        print(f'⚠ 路径不存在: {a.path}', file=sys.stderr)
        return 2

    if a.json:
        import json
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        _print_table(items)
    return 0


if __name__ == '__main__':
    sys.exit(main())
