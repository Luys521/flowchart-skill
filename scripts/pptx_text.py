# -*- coding: utf-8 -*-
r"""pptx_text.py — 从 `.pptx` 的 zip 里**直接取文字**（PIPELINE-SPEC §1.4）：零依赖、只读、不判断。

**为什么单独成一层**（而不是让用它的两边各写一遍）：**摘要器（`recon`）与读者（`parse_ooxml`）
要的是同一件事**——"这一页上写了什么字"。两边各写一份正则，迟早一个认 `<a:t>`、另一个只认
`<a:r>`，于是出现最坏的那种不一致：**摘要里看得见线索，撬开却找不到**（§5 的循环当场断掉）。
本仓的分层纪律正是为这种情况设的：模块之间不许互相 import，**共用能力下沉到公共层**。

**为什么零依赖就够**：`.pptx` 是 zip，正文在 `ppt/slides/slideN.xml` 的 `<a:t>` 运行里。
`python-pptx` 能做的事远不止取文字（形状 / 样式 / 图表），但**本仓要的只是"可引用的文字与出处"**——
为它引一个可选依赖，等于让"能不能读"取决于环境（§0 自包含优先）。

**三条纪律**：
- **只读**：打开的是内存里的字节，不落临时文件、不改材料；
- **按序号排，不按文件名字典序**：`slide10` 会排到 `slide2` 前面，那是错的；
- **单张坏不让整份失败**（§1.4 硬要求 2）：某张读不动就跳过它，其余照常。
"""
import io
import re
import zipfile
from xml.sax.saxutils import unescape

SLIDE_RE = re.compile(r'^ppt/slides/slide(\d+)\.xml$')
PARA_RE = re.compile(r'<a:p[ >].*?</a:p>', re.S)
# 文字运行：`<a:t>` 或 `<a:t xml:space="preserve">`——**必须紧跟空格或 `>`**。
# 原先写 `<a:t[^>]*>`（`[^>]*` 允许零个字符）会把**同前缀的别的标签**当开标签：
# `<a:tab pos="914400" algn="l"/>`、`<a:tabLst>`、`<a:tbl>` 全部命中，于是 `(.*?)</a:t>`
# 一路吃到下一个真 `</a:t>`，把**原始 XML 当正文**写进账本（还标 `certainty=direct`）。
# 真样本造得出这种稿（段落设制表位很常见），这是"最坏的一种"：污染唯一事实源且没有仪器看得见。
RUN_RE = re.compile(r'<a:t(?:\s[^>]*)?>(.*?)</a:t>', re.S)

# **幻灯片之外、但可能装着文字**的部件（2026-09-18 实测：它们会被静默漏掉）。
# 这份清单是"我们**没**读什么"的口径来源——`other_text_parts` 按它统计，调用方据此记账。
OTHER_TEXT_PARTS = (('ppt/charts/', '图表'), ('ppt/diagrams/', 'SmartArt'),
                    ('ppt/notesSlides/', '备注页'))


def slide_lines(xml):
    """一张幻灯片的 XML → 文本行（按 `<a:p>` 切段，段内 `<a:t>` 顺序拼接，去空段）。

    `a:p` 是段落、`a:t` 是文字运行——只取这两个，**不碰样式/坐标**：判语义是 AI 的事（§0 责任边界）。

    **只去两端的空白，不压段内空白**（G65）：原先 `' '.join(line.split())` 把段内连续空格折成一个，
    于是 `location.quote` 不再是逐字原文（最严解释下碰到 §1.6「不改字」），引用粒度也跟着退化。
    `<a:br/>`（软换行）目前仍并进同一段——按形状级切是另一版判据，仍登记在 G65。
    """
    out = []
    for para in PARA_RE.findall(xml):
        line = unescape(''.join(RUN_RE.findall(para))).strip()
        if line:
            out.append(line)
    return out


def other_text_parts(blob):
    """**我们没读**、但里面确实有文字的那些部件 → `{'图表': 1, 'SmartArt': 2}`（没有就不出现在字典里）。

    为什么必须能报出来：`.pptx` 的文字不只在 `ppt/slides/*.xml`——图表（`ppt/charts/*.xml`）、
    SmartArt（`ppt/diagrams/*.xml`）、备注页（`ppt/notesSlides/*.xml`）**各自有 XML、各自有 `<a:t>`**。
    只读 slides 就等于**静默漏掉**那几处的文字——而"静默少几条"正是本仓明令不许的（§2.4）。
    本函数只**统计**、不读：读它们要连带解决"这段文字属于哪一页"（要靠 rels），那是下一步的事；
    在那之前，**先把"没读"变成看得见**。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return _other_from(z)
    except (OSError, zipfile.BadZipFile):
        return {}


def _slides_from(z, max_slides):
    """已打开的 zip → `([(序号, [行…])], [读不动的部件名])`（`slides` 与 `slides_in_file` 共用）。

    **按序号升序，不按文件名字典序**：`slide10` 会排到 `slide2` 前面，那是错的。
    （真页序其实在 `ppt/presentation.xml` 的 `sldIdLst` + rels 里；本读法假设两者一致——
    真稿实测过两份都一致，**乱序稿仍未验**，见 `coding-spec` G14。）

    **读不动的部件要报出来，不许静默少一页**：原先只接 `(KeyError, OSError, BadZipFile)`，
    于是"加密条目"（`RuntimeError`）、"未知压缩法"（`NotImplementedError`）会**穿透出去**
    把整份材料判成读不动（其余页的文字一起丢）；而 CRC 坏的页被这三种接住、**无声消失**、
    摘要还把它写成"这份稿子本来就没文字"。两个方向都错，所以：**宽接 + 记账**。
    """
    named = []
    for name in z.namelist():
        m = SLIDE_RE.match(name)
        if m:
            named.append((int(m.group(1)), name))
    got, failed = [], []
    for n, name in sorted(named):
        if max_slides and len(got) >= max_slides:
            break
        try:
            got.append((n, slide_lines(z.read(name).decode('utf-8', 'replace'))))
        except Exception as e:                        # 宽接：任何单张的毛病都不许掀翻整份
            failed.append((n, name, type(e).__name__, str(e)[:60]))
    return got, failed


def _other_from(z):
    """已打开的 zip → `{类别: 个数}`（只统计**含文字**的那些部件）。"""
    got = {}
    names = z.namelist()
    for prefix, label in OTHER_TEXT_PARTS:
        n = 0
        for name in names:
            if not (name.startswith(prefix) and name.endswith('.xml')):
                continue
            try:
                xml = z.read(name).decode('utf-8', 'replace')
            except (KeyError, OSError, zipfile.BadZipFile):
                continue
            if any(t.strip() for t in RUN_RE.findall(xml)):
                n += 1
        if n:
            got[label] = n
    return got


def slides_in_file(path, max_slides=0):
    """**按路径**读幻灯片，只解开要读的那几个部件（`slides` 的路径版）→ `([(序号, 行)], [读不动])`。

    为什么侦查器要用这一份：一份 42 MB 的演示稿里，媒体占 42 MB、`ppt/slides/*.xml` 只有几百 KB——
    按**整份字节**设护栏，等于"因为图多就不给摘要"，而摘要恰恰是这些大材料最需要的东西（真样本实测）。
    """
    try:
        with zipfile.ZipFile(path) as z:
            return _slides_from(z, max_slides)
    except (OSError, zipfile.BadZipFile):
        return [], []


def other_text_parts_in_file(path):
    """**按路径**统计"我们没读但含文字"的部件（`other_text_parts` 的路径版）。"""
    try:
        with zipfile.ZipFile(path) as z:
            return _other_from(z)
    except (OSError, zipfile.BadZipFile):
        return {}


def scan_cost(path, total=0):
    """这份 zip **摘要/解析要读的字节数**：算"会读的部件"，**媒体与嵌入件不算**。

    护栏要挡的是"打开它会不会把内存吃光"，而 zip 系（docx/pptx）按需解压——图多不等于贵。
    读不了 / 不是 zip → 返回 `total`（按整份算，保守）。
    """
    try:
        with zipfile.ZipFile(path) as z:
            return sum(i.file_size for i in z.infolist()
                       if '/media/' not in i.filename and '/embeddings/' not in i.filename)
    except (OSError, zipfile.BadZipFile):
        return total


def slides(blob, max_slides=0):
    """`pptx` 字节 → `([(序号, 行…)], [读不动])`；`max_slides > 0` 时最多读这么多张（从第 1 张起）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return _slides_from(z, max_slides)
    except (OSError, zipfile.BadZipFile):
        return [], []
