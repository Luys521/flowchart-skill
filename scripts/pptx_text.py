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
RUN_RE = re.compile(r'<a:t[^>]*>(.*?)</a:t>', re.S)

# **幻灯片之外、但可能装着文字**的部件（2026-09-18 实测：它们会被静默漏掉）。
# 这份清单是"我们**没**读什么"的口径来源——`other_text_parts` 按它统计，调用方据此记账。
OTHER_TEXT_PARTS = (('ppt/charts/', '图表'), ('ppt/diagrams/', 'SmartArt'),
                    ('ppt/notesSlides/', '备注页'))


def slide_names(blob):
    """`pptx` 字节 → `[(序号, zip 内部件名)]`，**按序号升序**。不是 pptx / zip 坏了 → `[]`（不抛）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return []
    got = []
    for name in names:
        m = SLIDE_RE.match(name)
        if m:
            got.append((int(m.group(1)), name))
    return sorted(got)


def slide_lines(xml):
    """一张幻灯片的 XML → 文本行（按 `<a:p>` 切段，段内 `<a:t>` 顺序拼接，去空段）。

    `a:p` 是段落、`a:t` 是文字运行——只取这两个，**不碰样式/坐标**：判语义是 AI 的事（§0 责任边界）。
    """
    out = []
    for para in PARA_RE.findall(xml):
        line = unescape(''.join(RUN_RE.findall(para))).strip()
        if line:
            out.append(' '.join(line.split()))       # 段内换行/多空格压成单个空格
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
            names = z.namelist()
            got = {}
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
    except (OSError, zipfile.BadZipFile):
        return {}
    return got


def slides(blob, max_slides=0):
    """`pptx` 字节 → `[(幻灯片序号, [文本行…])]`；`max_slides > 0` 时最多读这么多张（从第 1 张起）。"""
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for n, name in slide_names(blob):
                if max_slides and len(out) >= max_slides:
                    break
                try:
                    out.append((n, slide_lines(z.read(name).decode('utf-8', 'replace'))))
                except (KeyError, OSError, zipfile.BadZipFile):
                    continue                          # 单张坏不让整份失败
    except (OSError, zipfile.BadZipFile):
        return []
    return out
