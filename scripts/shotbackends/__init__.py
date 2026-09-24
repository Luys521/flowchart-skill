# -*- coding: utf-8 -*-
"""shotbackends — 视觉自检的**可插拔截图后端**（通用核心）。

统一原语 `capture(page_html, out, width, height, ...)`：给定 HTML 与窗口尺寸截成 PNG。
后端默认自动选择：playwright（若装了，无头服务器更稳）→ chromium-cli（系统浏览器，零依赖）。

新增后端 = 在本目录加一个模块（提供 BACKEND / available() / capture()）并在 _BACKENDS 登记。
核心与各后端解耦：某后端不可用/报错，自动回退下一个，不影响出图主流程。
"""
from . import chromium_cli

# (名称, 模块)；顺序即默认优先级。
_BACKENDS = [('chromium-cli', chromium_cli)]
try:
    from . import playwright as _pw
    _BACKENDS.insert(0, ('playwright', _pw))
except ImportError:                              # 包目录结构固定，正常不会走到
    _pw = None


def list_backends():
    """返回 [(名称, 是否可用)]（用默认探测，不指定浏览器路径）。"""
    return [(name, mod.available()) for name, mod in _BACKENDS]


def select(backend=None, browser=None):
    """选一个可用后端名；指定的不可用或都不可用时返回 None。"""
    if backend:
        for name, mod in _BACKENDS:
            if name == backend:
                return name if mod.available(browser) else None
        return None
    for name, mod in _BACKENDS:
        if mod.available(browser):
            return name
    return None


def _module(name):
    for n, mod in _BACKENDS:
        if n == name:
            return mod
    return None


def capture(page_html, out, width, height, *, backend=None,
            browser=None, timeout=60, debug=False):
    """把 page_html 按 width×height 截成 PNG。成功返回 out(Path)，失败 None。

    width/height 即最终像素（--scale 已由调用方算进窗口）。
    指定 backend 失败不乱换（尊重指定）；自动选择时按优先级回退其余可用后端。
    browser（显式可执行路径）仅 chromium-cli 后端使用。
    """
    if backend:
        name = select(backend, browser)
        if name is None:
            if debug:
                print(f'[shot] 指定后端 {backend} 不可用')
            return None
        return _module(name).capture(
            page_html, out, width, height,
            browser=browser, timeout=timeout, debug=debug)

    for name, mod in _BACKENDS:
        if not mod.available(browser):
            continue
        result = mod.capture(
            page_html, out, width, height,
            browser=browser, timeout=timeout, debug=debug)
        if result is not None:
            return result
    return None
