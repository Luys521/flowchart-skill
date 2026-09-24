# -*- coding: utf-8 -*-
"""chromium_cli.py — 截图后端：本机已装的 Chromium 内核浏览器**命令行无头截图**。

零额外 Python 依赖（不装 Playwright 也能跑）：Edge(Win/macOS 自带) / Chrome / Chromium
都支持 `--headless --screenshot`。技能开箱即用的默认后端。

后端原语：capture(page_html, out, width, height, ...) —— 给定一个（可能是裁剪过的）HTML
和窗口尺寸，截成 PNG。裁剪页怎么构造由调用方（shot.py）负责，本模块只管"开窗截图"。
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

BACKEND = 'chromium-cli'

# 历史 shot.py 使用的浏览器候选（保持原查找口径），再补充常见路径。
_CANDIDATES = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    '/usr/bin/google-chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]


def find_browser(explicit=None):
    """显式路径也要验存在（路径打错该给人话，不抛 FileNotFoundError 裸栈）；找不到返回 None。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    # 环境变量兜底，再走候选表
    for env_key in ('EDGE_BIN', 'CHROME_BIN'):
        v = os.environ.get(env_key)
        if v and os.path.exists(v):
            return v
    for c in _CANDIDATES:
        if os.path.exists(c):
            return c
    # 用 PATH 找命令名
    for name in ('msedge', 'chrome', 'chromium', 'google-chrome',
                 'microsoft-edge', 'chromium-browser'):
        p = _which(name)
        if p:
            return p
    return None


def _which(name):
    """跨 PATH 找可执行文件。"""
    try:
        import shutil
        return shutil.which(name)
    except (OSError, ValueError):
        return None


def available(browser=None):
    """该后端在本机是否可用。"""
    return find_browser(browser) is not None


def _unlink_quiet(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def capture(page_html, out, width, height, *, browser=None,
            timeout=60, debug=False):
    """起无头浏览器对 page_html 按 width×height 窗口截图；成功返回 out(Path)，失败 None。

    width/height 即**最终像素尺寸**（调用方已把 --scale 算进窗口，见 shot.build_crop_page），
    故这里不加 --force-device-scale-factor，否则会双重放大。

    Edge/Chrome 的 --screenshot 异步落盘：进程退出时文件可能没写完，故先删旧图再轮询等待。
    """
    exe = find_browser(browser)
    if not exe:
        return None
    page_html = Path(page_html).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    # 独立临时用户数据目录，避免撞上已开着的浏览器实例（同 profile 会复用进程、不截图就退出）。
    tmp = tempfile.mkdtemp(prefix='flow-shot-')
    data_dir = Path(tmp) / 'data'
    _unlink_quiet(out)
    cmd = [exe, '--headless=new', '--disable-gpu', '--no-sandbox',
           '--hide-scrollbars',
           f'--window-size={int(width)},{int(height)}',
           f'--user-data-dir={data_dir}', '--virtual-time-budget=2000',
           f'--screenshot={out.resolve()}', page_html.as_uri()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        if debug:
            print(f'[shot:{BACKEND}] 起不来或超时（{timeout}s）')
        return None

    # 轮询等异步落盘（与历史 shot.py 同一做法）。
    for _ in range(60):
        if out.exists() and out.stat().st_size > 0:
            break
        time.sleep(0.1)
    if not out.exists() or out.stat().st_size < 100:
        if debug:
            print(f'[shot:{BACKEND}] rc={r.returncode}')
            if r.stderr:
                print(r.stderr[-1500:])
        return None
    return out
