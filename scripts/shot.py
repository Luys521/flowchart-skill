# -*- coding: utf-8 -*-
"""shot.py — 产物视觉自检：把 flow.html 截成 PNG，供 AI/人眼复核。

质量门禁管不了"是否好看"——必须看图（见 visual-spec §5）。

截图原语走可插拔后端 `shotbackends/`（默认自动：playwright → 系统 Edge/Chrome）。
本模块保留技能特有的**裁剪页构造**（从内联 SVG 抽指定 y 区间），再把"开窗截图"交给后端。

用法（与历史 CLI 兼容）：
  python shot.py "output/<名称>/<名称>-flow.html"
  python shot.py <html> -o out.png --crop 0:1200 --scale 2 [--browser <路径>]
  python shot.py <html> --backend chromium-cli
  python shot.py --list-backends
退出码：0 = 落了图；1 = 页面 / 浏览器 / 裁剪参数有问题（本族只有 0 与 1）。

注意：PNG 是**按需兜底快照**（目标环境打不开 HTML / 打印 / 静态汇报时用），不是正式交付物。
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

import shotbackends


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
    tmp.write_text(page, encoding='utf-8', newline='\n')
    return tmp, int(w * scale), int((y1 - y0) * scale)


def _parse_args(argv):
    """解析命令行参数（历史参数全保留，后端开关为新增可选项）。"""
    ap = argparse.ArgumentParser(description='flow.html → PNG 视觉自检')
    ap.add_argument('html_path', nargs='?')
    ap.add_argument('-o', '--out', help='输出 PNG 路径（默认同目录同名 .shot.png）')
    ap.add_argument('--crop', help='只看指定 y 区间，形如 0:1200')
    ap.add_argument('--scale', type=float, default=1.0, help='缩放倍数（默认 1）')
    ap.add_argument('--browser', help='浏览器可执行文件路径（chromium-cli 后端用）')
    ap.add_argument('--backend', default='auto',
                    choices=['auto'] + [n for n, _ in shotbackends.list_backends()],
                    help='截图后端，默认 auto（自动选择）')
    ap.add_argument('--timeout', type=int, default=60, help='截图超时秒数，默认 60')
    ap.add_argument('--list-backends', action='store_true', help='列出可用截图后端后退出')
    ap.add_argument('--debug', action='store_true', help='打印后端报错，便于排查')
    return ap.parse_args(argv)


def _output_path(src, out_spec):
    """输出 PNG 路径（默认同目录同名 .shot.png），父目录不存在则先建。"""
    out = Path(out_spec) if out_spec else src.with_suffix('.shot.png')
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _parse_crop(spec):
    """--crop 形如 0:1200 → (y0, y1)；非法时第三项为错误文案。

    `y1 = 0` 与"没给上界"要分开：`--crop 1200:` / `--crop 0:1200` 才是支持的写法
    （上界留空 ⇒ y1=0 表示全高）。
    """
    if not spec:
        return 0, 0, None
    parts = spec.split(':')
    if len(parts) != 2:
        return 0, 0, '--crop 形如 0:1200（不留空 = 指定上界；`1200:` = 从 1200 到底）'
    try:
        y0 = int(parts[0])
        y1 = int(parts[1]) if parts[1].strip() else 0     # 上界留空 ⇒ 0 = 全高
    except ValueError:
        return 0, 0, '--crop 形如 0:1200'
    if parts[1].strip() and y1 <= y0:
        return 0, 0, f'--crop 的上界必须大于下界（收到 {y0}:{y1}）'
    return y0, y1, None


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    a = _parse_args(argv)

    if a.list_backends:
        print('可用截图后端：')
        for name, ok in shotbackends.list_backends():
            print(f'  {name}: {"✓ 可用" if ok else "✗ 不可用（缺依赖/未找到浏览器）"}')
        return 0

    if not a.html_path:
        print('✗ 需要给出 flow.html 路径（或用 --list-backends）')
        return 1
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

    backend = None if a.backend == 'auto' else a.backend
    if backend is not None and not shotbackends.select(backend, a.browser):
        print(f'✗ 指定后端 {backend} 不可用；用 --list-backends 查看，或留 --backend auto')
        return 1

    result = shotbackends.capture(
        page, out, w, h, backend=backend,
        browser=a.browser, timeout=a.timeout, debug=a.debug)

    # 清理临时裁剪页
    try:
        page.unlink()
    except OSError:
        pass

    if result is None:
        if shotbackends.select(browser=a.browser) is None:
            if a.browser:
                print(f'✗ `--browser` 指的路径不存在：{a.browser}')
            else:
                print('✗ 找不到 Chromium 内核浏览器（Edge/Chrome），用 --browser 指定路径，'
                      '或装 Playwright：python -m pip install playwright '
                      '&& python -m playwright install chromium')
        else:
            print('✗ 截图失败，可用 --debug 看后端报错')
        return 1

    print(f'✓ 已截图 {out}  ({w}x{h})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
