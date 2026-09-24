# -*- coding: utf-8 -*-
"""plugin.py — 通用插件框架（与平台无关）：扩展点注册表 + 插件发现 + 依赖自检。

## 扩展点（point）契约
  sources       输入连接器：把外部数据拉成本地材料/流程表；
  renderers     渲染器（插件侧；build 自带的 html/drawio/svg 注册表独立、不受影响）；
  publishers    分发器：把产物送到外部平台，返回收执；
  sync          事实源同步：流程表 ↔ 外部结构化载体；
  commands      插件提供的 CLI 子命令；
  serve_routes  HTTP/事件路由（阶段 3 服务化用）。

## 插件形态（可整体插拔）
  integrations/<name>/plugin.yaml   清单（entry/requirements/provides）；
  integrations/<name>/<entry>.py    入口，定义 `register(registry, config, ctx)`；
  integrations/<name>/config.yaml   私有配置，`enabled` 默认缺省 = 关闭。

核心代码**绝不 import 具体插件**：运行 discover() 时按清单动态加载；
缺依赖/未启用 → 跳过并留痕，不影响核心。
"""
import importlib
import importlib.util
import sys
from pathlib import Path

import config as cfg_mod
from console import warn

# 标准扩展点（唯一出处）。插件可自定义新 point，无需在此登记。
POINTS = ('sources', 'renderers', 'publishers', 'sync', 'commands', 'serve_routes')


class Registry:
    """命名扩展点注册表。每个 (point, name) 存一个 callable + 元数据。

    注册值支持 callable，或延迟引用字符串 "module:attr"（get 时现解析，
    便于测试替换；与 build.RENDERERS 的 late-binding 同理）。
    """

    def __init__(self):
        self._items = {}

    def register(self, point, name, fn, **meta):
        """注册一个扩展实现。重复注册以最后一次为准（允许插件覆盖）。"""
        if not callable(fn) and not isinstance(fn, str):
            raise TypeError(f'扩展 {point}/{name} 必须是 callable 或 "module:attr"')
        self._items.setdefault(point, {})[name] = {'fn': fn, 'meta': meta}
        return fn

    def _resolve(self, spec):
        fn = spec['fn']
        if callable(fn):
            return fn
        mod, _, attr = fn.partition(':')
        return getattr(importlib.import_module(mod), attr)

    def get(self, point, name):
        """取一个扩展 callable；不存在抛 KeyError。"""
        return self._resolve(self._items[point][name])

    def meta(self, point, name):
        return self._items[point][name]['meta']

    def has(self, point, name):
        return point in self._items and name in self._items[point]

    def all(self, point):
        """返回 {name: callable}（已解析）。"""
        return {n: self._resolve(s) for n, s in self._items.get(point, {}).items()}

    def names(self, point):
        return sorted(self._items.get(point, {}))

    def snapshot(self):
        """{point: [names]}，用于打印与自检。"""
        return {p: sorted(d) for p, d in self._items.items() if d}


def _read_manifest(plugin_dir):
    """读插件清单 plugin.yaml → dict（PyYAML 已为核心依赖）。"""
    import yaml
    p = Path(plugin_dir) / 'plugin.yaml'
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding='utf-8')) or {}


def _check_requirements(requirements):
    """自检插件依赖。返回缺失项列表 [{import, pip}]；全部满足返回 []。"""
    missing = []
    for req in requirements or []:
        imp = (req or {}).get('import') if isinstance(req, dict) else req
        pip = req.get('pip', imp) if isinstance(req, dict) else imp
        if importlib.util.find_spec(imp) is None:
            missing.append({'import': imp, 'pip': pip})
    return missing


def _load_entry(plugin_dir, entry, registry, plugin_cfg, ctx):
    """加载插件入口并调用 register()。

    两个坑（实测）：
      · 入口模块**按文件路径 + 唯一模块名**加载（`_flowplugin_<插件>_<entry>`），
        否则不同插件的同名入口（都叫 plug/plugin）会命中 sys.modules 缓存、互相串；
      · 插件目录加入 sys.path，使入口内部 `from feishu_client import ...` 等同目录导入可用。
    """
    pdir = Path(plugin_dir).resolve()
    pdir_s = str(pdir)
    if pdir_s not in sys.path:
        sys.path.insert(0, pdir_s)
    entry_file = pdir / f'{entry}.py'
    mod_name = f'_flowplugin_{pdir.name}_{entry}'
    spec = importlib.util.spec_from_file_location(
        mod_name, entry_file, submodule_search_locations=[pdir_s])
    if spec is None or spec.loader is None:
        raise ImportError(f'找不到插件入口 {entry_file}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    register = getattr(mod, 'register', None)
    if register is None:
        raise AttributeError(f'插件入口 {entry} 未定义 register(registry, config, ctx)')
    return register(registry, plugin_cfg, ctx or {})


def discover(registry=None, only=None, ctx=None, cli_overrides=None, verbose=True):
    """扫描 integrations/ 加载已启用插件。

    返回 (registry, report)；report = {'loaded': [...], 'disabled': [...],
    'missing_deps': {name: [...]}, 'failed': [...]}。
    only: 只考虑这些插件（白名单）；默认全部扫描（各自按 enabled 决定）。
    """
    registry = registry or Registry()
    report = {'loaded': [], 'disabled': [], 'missing_deps': {}, 'failed': []}
    root = cfg_mod.INTEGRATIONS_DIR
    if not root.exists():
        return registry, report

    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir() or not (pdir / 'plugin.yaml').exists():
            continue
        name = pdir.name
        if only and name not in only:
            continue
        manifest = _read_manifest(pdir)
        if not cfg_mod.plugin_enabled(name, cli_overrides):
            report['disabled'].append(name)
            continue
        missing = _check_requirements((manifest or {}).get('requirements'))
        if missing:
            report['missing_deps'][name] = missing
            pkgs = ' '.join(m['pip'] for m in missing)
            warn(f'⚠ 插件 {name} 已启用但缺依赖，未加载：python -m pip install {pkgs}')
            continue
        try:
            _load_entry(pdir, (manifest or {}).get('entry', 'plugin'),
                        registry, cfg_mod.plugin_config(name), ctx)
            report['loaded'].append(name)
        except Exception as e:                      # noqa: BLE001 — 单个插件坏不拖垮核心
            report['failed'].append(name)
            warn(f'⚠ 插件 {name} 加载失败（{type(e).__name__}: {str(e)[:120]}）')

    if verbose:
        if report['loaded']:
            print(f'[plugins] 已加载: {", ".join(report["loaded"])}')
        if report['disabled']:
            print(f'[plugins] 未启用: {", ".join(report["disabled"])}（默认关闭）')
        if report['missing_deps']:
            print('[plugins] 缺依赖未加载: '
                  + ", ".join(report['missing_deps'].keys()))
        if report['failed']:
            print('[plugins] 加载失败: ' + ", ".join(report['failed']))
    return registry, report
