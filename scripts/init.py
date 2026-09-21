# -*- coding: utf-8 -*-
"""init.py — 初始化一个流程的工作目录（SKILL 第一段：读材料·落表）。

把两个模板复制进 `output/<名称>/`：flowtable-template → flowtable.md（事实源，AI 填）、
checklist-template → checklist.md。用法与退出码：init.py <名称> [-d <父目录>]；同名冲突则退 1。
"""
import argparse
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TPL_DIR = SKILL_ROOT / 'templates'


def _reject_conflict(target):
    """target 被同名文件或非空目录占用时打印原因并返回 True。"""
    # 先判"是不是文件"：target 是个同名文件时 iterdir() 会抛 NotADirectoryError，
    # 报错指向 Python 内部而不是"名称被占了"，退出码也不对。
    if target.is_file():
        print(f'✗ 同名文件已存在: {target}')
        print('  这是文件、不是目录；请换个名称或先移走它。')
        return True
    if target.exists() and any(target.iterdir()):
        print(f'✗ 目录已存在且非空: {target}')
        print('  同一流程的迭代应复用该目录；确需重来请先清空或换名称。')
        return True
    return False


def _copy_templates(target):
    """把两份模板复制进 target；模板缺失即返回 False（调用方退 1）。"""
    # **发空骨架，不发格式基准**（D-105）：`flowtable-template.md` 逐字等于 `examples/workflow`
    # 那张 30 节点的自举表——那是给人**对照格式**用的。拿它当用户的第一张表，一跑 `clarify.py`
    # 就会报**示例自己的** `⚠?` 并 exit 1。
    pairs = [('flowtable-skeleton.md', 'flowtable.md'),
             ('checklist-template.md', 'checklist.md')]
    for src_name, dst_name in pairs:
        src = TPL_DIR / src_name
        dst = target / dst_name
        if not src.exists():
            print(f'✗ 找不到模板: {src}')
            return False
        if dst.exists():
            print(f'· 已存在，跳过: {dst}')
            continue
        shutil.copyfile(src, dst)
    return True


def _print_summary(target):
    """打印初始化结果与下一步指引。"""
    print(f'✓ 已初始化: {target}')
    print('  流程表（待填写）: ' + str(target / 'flowtable.md'))
    print('  自检报告        : ' + str(target / 'checklist.md'))
    print('  下一步：填写 flowtable.md，然后跑 build.py')


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='初始化流程工作目录')
    ap.add_argument('name', help='流程短名（目录名），如 我的流程')
    ap.add_argument('-d', '--dir', default='output', help='父目录（默认 output）')
    a = ap.parse_args(argv)

    target = Path(a.dir) / a.name
    if _reject_conflict(target):
        return 1

    target.mkdir(parents=True, exist_ok=True)
    if not _copy_templates(target):
        return 1
    _print_summary(target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
