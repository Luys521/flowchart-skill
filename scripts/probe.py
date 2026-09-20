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
# 有**自包含读取器**的那三种：docx/xlsx 靠声明的必须依赖，pptx 靠标准库（zip + `ppt/slides/*.xml`，
# 见公共层 `pptx_text`）。所以三种都能判 T1 —— **判 T1 的依据是"有人认领"，不是"看起来能读"**。
READABLE_OOXML = ('docx', 'xlsx', 'pptx')
NO_PART_REASON = ('zip 容器里没有可读的 OOXML 部件（要 word/document.xml / xl/workbook.xml / '
                  'ppt/presentation.xml）：多半是损坏 / 半成品包，请重新导出')

# 材料类型（**机器可读的 kind**，§2.1）：本仓"这是什么"的唯一判据源就是这里，别处不许按扩展名重判
KINDS = ('docx', 'xlsx', 'pptx', 'ole', 'pdf-text', 'pdf-scan', 'image', 'text', 'unknown')

# 判"是不是文本"时读多少字节：8 字节不够——中文一个字 3 字节，正好会被 8 字节的头切断（见 _text_tier）。
TEXT_HEAD = 4096

# **函数顺序按调用方向排**（判据助手紧跟 `sniff`，取元数据的紧跟 `probe_tree`）：单列函数流里
# 一条长跳就把门⑨ 的绕行读数顶上去（G12）。实测本模块 60% → 43%。


def _read_head(path, n=8):
    """前 n 字节；读不动就返回空（调用方按 T4 记账，不许崩）。"""
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''

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

def _decodes(seg, skip_head=0, trim_tail=True):
    """这段字节能不能解成 UTF-8。

    - `trim_tail=True`：**允许尾字节被切断**（读**头部**时必然遇到：4 KB 的块边界会切开一个汉字）；
    - `skip_head>0`：允许**开头几字节**是半个字符（读**尾部**时必然遇到，起点落在字符中间）；
    - 读**文件真尾部**时要 `trim_tail=False`——文件末尾没有"块边界"这个借口：那里就是文件真正的结尾，
      末尾若还剩半个字符/二进制字节，说明这份文件不是干净的文本（`parse_text` 也解不开，两边同源）。
    """
    for i in range(skip_head + 1):
        body = seg[i:]
        for cut in range(4 if trim_tail else 1):
            try:
                (body[:len(body) - cut] if cut else body).decode('utf-8')
                return True
            except UnicodeDecodeError:
                continue
    return False


def _text_tier(head, tail=b''):
    """能按 UTF-8 解码且无 NUL 字节 → 文本（T1）；否则 None。**头尾都要过**。

    **截断在多字节字符中间也要认**（实测踩到的真 bug）：只看前 8 字节时，"这"（3 字节）会被正好切开，
    于是**合法的中文 `.txt` 被判 T4**（当时记的原因是"魔数不认识，且不是文本"）——本仓的材料以中文为主，
    这条误判会成片出现。做法：整段先解一次，失败就**逐字节退**（UTF-8 单字符最多 4 字节），
    退完能解就说明只是尾字节被切断，不是二进制。

    **为什么要连尾部一起看**（审计实测）：原先只看前 4 KB，于是一份"头部是纯文本、尾部是二进制垃圾"
    的文件被判 T1「可直读」，而 `parse_text` 要解**整份** ⇒ 谁都读不动，档位语义是假的。
    看尾部很便宜（再一次 4 KB 读），且正是这一类错配的发生处；尾部起点也可能落在字符中间，故退位。
    """
    if head[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return 'T1', 'UTF-16 文本（BOM）'                     # **先看 BOM**：UTF-16 正文里满是 NUL 字节
    if not head or b'\x00' in head:                           # （下面的 NUL 判据是给"没 BOM 的二进制"用的）
        return None
    if tail and (b'\x00' in tail or not _decodes(tail, skip_head=3, trim_tail=False)):
        return None                                           # 尾部不是文本 ⇒ 整体不算"可直接读的文本"
    if _decodes(head):
        return 'T1', 'UTF-8 文本（无 NUL 字节）'
    return None

def sniff(path):
    """一个文件 → `(tier, probe, status, reason, kind)`。`probe` 是**判据**（人可核），`kind` 是机器可读类型。

    **一条不变式**（审计后加的，§1.2）：**`tier=T1`（可直读）⇒ 必须至少有一个适配器认领**。
    所以这里判 OOXML 时用的部件名与 `parse_ooxml.container_kind` 同源；三种 OOXML（docx/xlsx/pptx）
    都有 reader，都能判 T1——**曾经不是**：pptx 没有 reader 却判 T1，于是一份 pptx 就让整条链判"漏认"退 1
    （§1.4 的教训：探测的声明不许比实现的射程宽）。判不出不猜：一律 T4 + `unreadable` + 原因（§1.2 第 3 条）。
    """
    path = Path(path)
    head = _read_head(path, 8)
    if not head:
        return 'T4', '空文件或读不动', 'unreadable', '文件为空或不可读', 'unknown'

    if head[:2] == b'PK':
        kind = _ooxml_kind(path)
        if kind in READABLE_OOXML:
            return 'T1', f'PK 容器 + {kind} 可读部件', 'ok', '', kind
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

    # 判文本要看够多字节（见 `_text_tier`），**而且要看尾部**：只看头部会把"头文本、尾二进制"判成可直读
    text = _text_tier(_read_head(path, TEXT_HEAD), _read_tail(path, TEXT_HEAD))
    if text:
        return text[0], text[1], 'ok', '', 'text'

    # 判不出时，**原因必须能照着做**（§1.3：`unreadable` 的 reason 要可执行）。
    # 原先这里只写"魔数不认识，且不是文本"——那是**判据**，不是出路：一份 GBK 的 `.txt` 拿到这句话
    # 无从下手（而它其实是能读的，只差一个 `--encoding gbk`）。这里给的是"下一步可以试什么"，
    # 不是"它是什么"：probe 仍然不许猜（§1.2 第 3 条），而"拿 GBK 硬解二进制"由 `parse_text` 侧
    # 那两道门兜住（**用户显式认领编码** + 扩展名属纯文本族）。
    return ('T4', f'魔数不认识（{head[:4].hex()}）', 'unreadable',
            '魔数不认识，且不是 UTF-8 / 带 BOM 的 UTF-16 文本：若它是本地编码（GBK 等）的纯文本，'
            '给 `--encoding gbk` 再跑解析；否则按不参与处理（音视频 / 可执行文件等）', 'unknown')

def _mtime(path):
    """修改时间（ISO 8601 本地时区）；取不到返回空串（不崩）—§3「替代」的末位兜底。"""
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(path.stat().st_mtime))
    except OSError:
        return ''

def _read_tail(path, n):
    """末 n 字节（不足就全给）；读不动返回空（调用方按"没有尾部"处理，不崩）。"""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n))
            return f.read(n)
    except OSError:
        return b''


def _sha_and_size(path):
    """→ `(sha256, 字节数)`，**分块读**（默认 1 MiB 一块）。

    为什么要分块（审计实测）：原先 `p.read_bytes()` 只为算 sha256 就把**整份**读进内存——
    一份 400 MiB 的材料让 `probe` 峰值工作集到 421 MiB，而"别把内存吃光"的护栏在 `recon` 侧
    （`max_open_bytes`），根本护不到探测这一步。分块之后峰值 = 一块，sha256 与整份读**逐字节等价**。
    """
    h, n = hashlib.sha256(), 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


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
            sha, size = _sha_and_size(p)
        except OSError as e:
            tier, probe, status, reason, kind = ('T4', f'读不动（{type(e).__name__}）',
                                                 'unreadable', str(e), 'unknown')
            sha, size = '', 0
        item = {'id': f'M{i:02d}', 'path': p.as_posix(), 'sha256': sha, 'bytes': size,
                'mtime': _mtime(p), 'tier': tier, 'kind': kind, 'probe': probe, 'status': status,
                # `root` = 这一趟扫的根（2026-09-19 补，§2.1）。**没有它，"材料根变了"就无从判起**——
                # 只比单份文件看得见"改了/删了"，看不见"用户又往目录里补了一份"。
                'root': root.as_posix()}
        if reason:
            item['reason'] = reason
        out.append(item)
    return out


def verify_list(items):
    """**陈化检查**：`materials[]` 记的与材料根**当下**还对不对得上（PIPELINE-SPEC §1.2）。

    → `(问题行, 提示行)`；两条都空 = 没变。查两件事：
      · **记过的材料**：还在吗、`sha256` 还是那个吗（改了 / 删了都算）；
      · **根下有没有新文件**：用户补了一份合同而没重跑 03，就是这一种——**原来没有任何仪器看得见**。

    为什么消费端也要查（`parse.py` 默认调它）：各层 `check` 核的是"产物 ↔ 产物"，两边同源，
    **一起错时全绿**。表被直改有回边 `18→11` 兜着，材料这一侧一直没有等价物。
    """
    bad, notes = [], []
    by_root = {}
    for m in items or []:
        if not isinstance(m, dict):
            continue
        p = str(m.get('path') or '')
        by_root.setdefault(str(m.get('root') or ''), []).append(m)
        fp = Path(p)
        if not fp.exists():
            bad.append(f'`{m.get("id")}` 记的材料不在了：{p}')
            continue
        try:
            sha, size = _sha_and_size(fp)
        except OSError as e:
            bad.append(f'`{m.get("id")}` 记的材料读不了：{p}（{type(e).__name__}）')
            continue
        if m.get('sha256') and sha != m['sha256']:
            bad.append(f'`{m.get("id")}` 内容变了：{p}（{size} 字节，记的是 {m.get("bytes")} 字节）')
    for root, ms in by_root.items():
        r = Path(root) if root else None
        if not r or not r.is_dir():
            continue                        # 根是单份文件、或没记 root：只做上面那半
        known = {str(m.get('path')) for m in ms}
        now = {q.as_posix() for q in r.rglob('*') if q.is_file()}
        # **产物名不算新材料**：任务级产物（`materials/recon/intake/plan/drift` 那一套）本来就该住
        # **成果根**而不是材料根（§0），但真把两者放同一个目录时，那是**布局问题**，不是**陈化问题**——
        # 把它报成"材料根变了"会天天误报（夹具就是这么撞出来的）。判据按**名字**认，不看内容。
        new = sorted(q for q in (now - known) if not _is_artifact_name(q))
        if new:
            bad.append(f'材料根 `{root}` 下多了 {len(new)} 个没入账的文件：'
                       f'{"、".join(new[:3])}{"…" if len(new) > 3 else ""}')
    if not bad:
        notes.append(f'陈化检查：{len(items or [])} 份材料与材料根当下一致')
    return bad, notes


ARTIFACT_NAMES = ('materials.json', 'elements.json', 'notes.json', 'evidence.json',
                  'recon.md', 'intake.md', 'plan.md', 'drift.md',
                  'checklist.md', 'flowtable.md')


def _is_artifact_name(path_str):
    """这份"新文件"是不是**本工具链自己的产物**？（产物名 / `.todo.json` / `.bak` ⇒ 是）

    与 `artifact.NON_TABLE_MD` 同一类登记，但这里只按**名字**判、且**不 import**（probe 在流水线最上游，
    不该为了一个名字表把下游模块拖进来）。
    """
    n = Path(path_str).name
    return n in ARTIFACT_NAMES or n.endswith('.todo.json') or n.endswith('.bak')


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
    ap.add_argument('path', nargs='?', help='材料路径（文件或目录）')
    ap.add_argument('--json', action='store_true', help='输出 materials[] JSON')
    ap.add_argument('--verify', metavar='materials.json',
                    help='**陈化检查**：只比"记过的材料 + 材料根当下"，不重新分档；不一致退 2')
    a = ap.parse_args(argv)

    if a.verify:                                   # 陈化检查：材料根变了没有（§1.2）
        import json
        try:
            items = json.loads(Path(a.verify).read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            print(f'⚠ 材料层读不了（仪器故障）: {type(e).__name__}: {e}', file=sys.stderr)
            return 2
        bad, notes = verify_list(items)
        for n in notes:
            print(f'  · {n}')
        if bad:
            print(f'✗ 材料层陈化（{len(bad)} 条）——**回 03 重跑探测与解析**，别在旧账上继续：')
            for b in bad[:10]:
                print(f'   · {b}')
            return 2
        return 0

    if not a.path:
        print('⚠ 要么给材料路径，要么用 `--verify <materials.json>`', file=sys.stderr)
        return 2

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
