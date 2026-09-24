# -*- coding: utf-8 -*-
"""config.py — 技能与插件的**统一配置加载**（通用核心，与平台无关）。

口径（优先级从高到低）：
  1. CLI 显式传入的配置（调用方把 dict merge 进来）；
  2. 环境变量（`FLOWCHART_<...>` / 插件私有变量，如 `FEISHU_APP_ID`）；
  3. 技能根 `config.yaml`（全局开关）；
  4. 插件目录 `integrations/<name>/config.yaml`（插件私有配置）；
  5. 代码内默认值。

零强制依赖：PyYAML 缺失时退回默认值并留痕（配置读不出不该让 CLI 崩）。
"""
import os
from pathlib import Path

from console import warn

try:
    import yaml
except ImportError:
    yaml = None

SKILL_ROOT = Path(__file__).resolve().parent.parent
INTEGRATIONS_DIR = SKILL_ROOT / 'integrations'

# 全局配置文件名（住技能根）。唯一出处。
GLOBAL_CONFIG = 'config.yaml'


def _read_yaml(path):
    """读一个 yaml → dict；文件不存在返回 {}；读不动留痕并返回 {}。"""
    p = Path(path)
    if not p.exists():
        return {}
    if yaml is None:
        warn(f'⚠ 未安装 PyYAML，配置 {p} 被忽略（deps.hint: pip install pyyaml）')
        return {}
    try:
        doc = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
        return doc if isinstance(doc, dict) else {}
    except (OSError, yaml.YAMLError) as e:
        warn(f'⚠ 配置 {p} 读不动（{type(e).__name__}），已忽略')
        return {}


def global_config():
    """技能根全局配置（含 `integrations: {name: {enabled: ...}}` 开关）。"""
    return _read_yaml(SKILL_ROOT / GLOBAL_CONFIG)


def plugin_config(name):
    """插件私有配置：`integrations/<name>/config.yaml`，再叠全局里该插件的段与环境变量。

    合并顺序（后者覆盖前者）：插件 config.yaml ← 全局 config 的 integrations.<name> ← 环境变量。
    """
    base = _read_yaml(INTEGRATIONS_DIR / name / GLOBAL_CONFIG)
    g = (global_config().get('integrations') or {}).get(name) or {}
    merged = dict(base)
    for k, v in g.items():
        merged[k] = v
    return merged


def plugin_enabled(name, cli_overrides=None):
    """该插件是否启用。**默认关闭**（缺省即 False，保证零凭证可跑、不误连平台）。

    覆盖来源（任一为真即启用，任一显式关闭即关闭）：
      · 全局/插件配置里的 `enabled`；
      · 环境变量 `FLOWCHART_PLUGIN_<NAME>=1/0`；
      · CLI overrides：{name: True/False}。
    """
    cfg = plugin_config(name)
    env = os.environ.get(f'FLOWCHART_PLUGIN_{name.upper()}', '').strip()
    cli = (cli_overrides or {}).get(name)

    # 显式关闭优先级最高（CLI > env > config）
    if cli is False:
        return False
    if cli is True:
        return True
    if env:
        return env in ('1', 'true', 'TRUE', 'on', 'ON', 'yes')
    return bool(cfg.get('enabled', False))


def env_or_config(name, keys, default=None):
    """插件取一个值：先环境变量（keys 依次试），再配置 dict，最后默认。

    用于把 app_id/secret 等敏感值经环境变量注入而不必写进配置文件。
    """
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    cfg = plugin_config(name)
    for k in keys:
        if k.lower() in cfg and cfg[k.lower()]:
            return cfg[k.lower()]
    return default
