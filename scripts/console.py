# -*- coding: utf-8 -*-
r"""console.py — **公共层唯一的"留痕出口"**（D-129）：降级 / 兜底 / 缺段的告警都从这里出去。

**为什么值得单独一个模块**：留痕是"降级必须留痕"落地的最后一厘米，而它此前散在各处——
CLI 模块那边有约定（入口把 stdout 与 stderr 都配成 utf-8），**纯库这边没有**。库写一句中文，
可读性却取决于**调用方**配没配编码，于是实测出这样一种失效（2026-09-19）：

    Windows 上**管道 / 重定向**时 stderr 默认是本地编码（实测 gbk），而 `⚠`（U+26A0）不在 GBK 里
    ⇒ Python 的 stderr 用 `backslashreplace`，**不报错、只悄悄退化**：
    `⚠ 输入读不了（仪器故障，不是内容问题）` 变成 `\u26a0 ��������ˣ…`。

**读不出来的留痕等于没留痕**——而退化的那两句恰好在最需要它的时候出现（"这是仪器故障不是内容
问题"、`thresholds` 的"段名是不是改了"）。所以这一段责任收在一处，由这一处保证可读。

**为什么写字节、不 `print`**（本模块唯一的技术选择，值得写清）：真实控制台上 Python 本来就是
utf-8（Windows 走 `_WindowsConsoleIO`），只有**管道 / 重定向**时才退到本地编码——而管道那一头
（验收器 / 夹具 / AI / CI）一律按 utf-8 读。所以"**一律写 utf-8 字节**"在两种消费方式下都对，
而且**不必按流的编码分支**：分支本身就是第二条规则，会再漂一次（本仓栽过——`load_thresholds`
六份实现里"正整数"那一半漂了，见 `thresholds.py` 文件头）。

**射程**（声明不许比射程宽）：本模块管留痕的**去向与编码**，不管**措辞**（`⚠` 标记由调用方写），
也不管 stdout——那是 CLI 的地盘，各入口自己已配 utf-8。**面③ 有一条不变式**钉住这个分工：
往 stderr 写非 ASCII 文本的，只许是带 CLI 的模块（并且它必须自己配编码），纯库一律走这里。
"""
import sys


def warn(msg):
    """一句留痕 → stderr，**任何流编码下都读得出来**（结尾没换行就补一个）。

    调用方写全整句（含 `⚠`）：这里只管把它**送得出去**。
    """
    text = msg if msg.endswith('\n') else msg + '\n'
    err = sys.stderr
    buf = getattr(err, 'buffer', None)
    if buf is None:
        # 被换成了 StringIO / 测试替身：没有字节层，退回文本层（那种场合也不会有编码问题）
        err.write(text)
        err.flush()
        return
    try:
        # **先冲文本层，再写字节层**：否则"先 print 后 warn"两句的先后会在这里翻过来
        err.flush()
        buf.write(text.encode('utf-8'))
        buf.flush()
    except (OSError, ValueError):
        # 流已经关了 / 坏了：留痕本来就送不出去，不该让业务逻辑（退默认值那条路）跟着炸
        pass
