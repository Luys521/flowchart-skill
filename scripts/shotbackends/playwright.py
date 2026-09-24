# -*- coding: utf-8 -*-
"""playwright.py — 截图后端：Playwright（可选依赖，无头服务器/CI 场景更稳）。

启用：`python -m pip install playwright && python -m playwright install chromium`。
未安装时 available()=False，框架自动跳过、回退 chromium-cli。

后端原语与 chromium_cli 同签名：给定 HTML + 窗口尺寸 → PNG。
"""
from pathlib import Path

BACKEND = 'playwright'


def available(browser=None):
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def capture(page_html, out, width, height, *, browser=None,
            timeout=60, debug=False):
    """用 Playwright 按 width×height 视口截图；成功返回 out(Path)，失败 None。

    width/height 即最终像素（--scale 已由调用方算进窗口），device_scale_factor 保持 1。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    page_html = Path(page_html).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser_obj = p.chromium.launch()
            page = browser_obj.new_page(
                viewport={'width': int(width), 'height': int(height)})
            page.goto(page_html.as_uri(), wait_until='load',
                      timeout=int(timeout) * 1000)
            page.wait_for_timeout(200)
            page.screenshot(path=str(out), full_page=False)
            browser_obj.close()
    except Exception as e:                          # noqa: BLE001 — 统一交回上层
        if debug:
            print(f'[shot:{BACKEND}] {type(e).__name__}: {str(e)[:200]}')
        return None
    if not out.exists() or out.stat().st_size < 100:
        return None
    return out
