# -*- coding: utf-8 -*-
"""shot.py — 产物视觉自检：把 flow.html 截成 PNG，供 AI/人眼复核。

质量门禁管不了"是否好看"——必须看图（见 visual-spec §5）。
用法：python shot.py "output/<名称>/flow.html" [--crop 0:1200] [--scale 2]（依赖本机 Edge/Chrome）。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CANDIDATES = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    '/usr/bin/google-chrome',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]


def find_browser(explicit=None):
    if explicit:
        return explicit
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    return None


def build_crop_page(html_path, y0, y1, scale):
    """把 flow.html 的内联 SVG 裁到 [y0,y1) 区间，保留原 <style>（否则 class 失效全变黑）。"""
    html = Path(html_path).read_text(encoding='utf-8')
    style = re.search(r'<style[^>]*>.*?</style>', html, re.S)
    svg = re.search(r'<svg[^>]*>.*?</svg>', html, re.S)
    if not svg:
        raise ValueError('未在 HTML 中找到内联 SVG（本脚本只适用于 render_html.py 的产物）')
    style = style.group(0) if style else ''
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.group(0))
    w, h = (float(vb.group(1)), float(vb.group(2))) if vb else (1180.0, 1200.0)
    y1 = min(y1, int(h)) if y1 else int(h)
    svg_big = re.sub(r'<svg([^>]*)>',
                     lambda m: f'<svg{m.group(1)} width="{w * scale}" height="{h * scale}">',
                     svg.group(0), count=1)
    page = (f'<!DOCTYPE html><html><head><meta charset="utf-8">{style}'
            f'<style>html,body{{margin:0;padding:0;background:#fff}}'
            f'.win{{width:{w * scale}px;height:{(y1 - y0) * scale}px;overflow:hidden;position:relative}}'
            f'.win svg{{position:absolute;top:{-y0 * scale}px;left:0}}</style></head>'
            f'<body><div class="win">{svg_big}</div></body></html>')
    tmp = Path(tempfile.gettempdir()) / '_flowshot_crop.html'
    tmp.write_text(page, encoding='utf-8')
    return tmp, int(w * scale), int((y1 - y0) * scale)


def _parse_args(argv):
    """解析命令行参数。"""
    ap = argparse.ArgumentParser(description='flow.html → PNG 视觉自检')
    ap.add_argument('html_path')
    ap.add_argument('-o', '--out', help='输出 PNG 路径（默认同目录同名 .shot.png）')
    ap.add_argument('--crop', help='只看指定 y 区间，形如 0:1200')
    ap.add_argument('--scale', type=float, default=1.0, help='缩放倍数（默认 1）')
    ap.add_argument('--browser', help='浏览器可执行文件路径')
    return ap.parse_args(argv)


def _output_path(src, out_spec):
    """输出 PNG 路径（默认同目录同名 .shot.png），父目录不存在则先建。"""
    out = Path(out_spec) if out_spec else src.with_suffix('.shot.png')
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _parse_crop(spec):
    """--crop 形如 0:1200 → (y0, y1)；非法时第三项为错误文案。"""
    if not spec:
        return 0, 0, None
    try:
        y0, y1 = (int(x) for x in spec.split(':'))
    except ValueError:
        return 0, 0, '--crop 形如 0:1200'
    # 负高度窗口在浏览器里行为未定义（可能截出空白或报错），早说比事后猜强。
    if y1 and y1 <= y0:
        return 0, 0, f'--crop 的上界必须大于下界（收到 {y0}:{y1}）'
    return y0, y1, None


def _unlink_quiet(path):
    """删文件；不存在或删不掉都静默忽略。"""
    try:
        path.unlink()
    except OSError:
        pass


def _capture_screenshot(exe, page, out, w, h):
    """起无头浏览器对裁剪页截图并轮询等文件落盘；成功返回 True。

    Edge/Chrome 的 --screenshot 是异步落盘：进程退出时文件可能还没写完，
    因此先删旧图，再轮询等待新图出现，否则会误报失败、或读到上一张的尺寸。
    """
    _unlink_quiet(out)
    cmd = [exe, '--headless=new', '--disable-gpu', '--hide-scrollbars',
           f'--screenshot={out.resolve()}', f'--window-size={w},{h}', page.resolve().as_uri()]
    subprocess.run(cmd, capture_output=True)
    for _ in range(60):
        if out.exists() and out.stat().st_size > 0:
            break
        time.sleep(0.1)
    return out.exists()


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _parse_args(argv)

    src = Path(a.html_path)
    if not src.exists():
        print(f'✗ 找不到 {src}')
        return 1
    out = _output_path(src, a.out)
    y0, y1, crop_err = _parse_crop(a.crop)
    if crop_err:
        print(f'✗ {crop_err}')
        return 1

    try:
        page, w, h = build_crop_page(src, y0, y1, a.scale)
    except ValueError as e:
        print(f'✗ {e}')
        return 1
    exe = find_browser(a.browser)
    if not exe:
        print('✗ 找不到 Chromium 内核浏览器（Edge/Chrome），用 --browser 指定路径')
        return 1
    if not _capture_screenshot(exe, page, out, w, h):
        print('✗ 截图失败，请检查浏览器路径')
        return 1
    _unlink_quiet(page)
    print(f'✓ 已截图 {out}  ({w}x{h})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
