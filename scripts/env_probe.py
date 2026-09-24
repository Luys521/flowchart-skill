# -*- coding: utf-8 -*-
"""env_probe.py — 运行环境自述：告诉操作者（LLM / 人 / 脚本）**它此刻站在哪、有哪几只手**。

## 为什么需要它（2026-09-24）

同一份技能会在**两种环境**里跑：飞书托管（云函数 / 应用引擎）与办公电脑本地。两者**能力不同**——
托管能把产物发回群，本地只能落文件。而技能的其余部分**都不回答这个问题**：

  · `config.plugin_enabled()` 说的是"**用户开没开**"（意图），不是"环境支不支持"（事实）；
  · `serve.py` 的 `ping` 说的是"**插件注册了什么**"，而且它**走网关** —— 本地根本不会调它。

不区分环境的直接后果是 **LLM 说假话**：在本地环境声称"已发送到您的飞书群"，而它没有那只手。
所以这个探测器的产物不是"配置"，是**事实**：`enabled` 与"环境支不支持"是两问，两个都要报。

## 判据（只用客观事实，不猜）

    feishu-hosted      `APP_ID` 与 `APP_SECRET` **同时**存在 ⇒ 平台注入 ⇒ 托管环境
    feishu-configured  只有 `FEISHU_*` 或 `config.yaml` 有 app_id ⇒ 自配凭证，可连飞书
    local              都没有 ⇒ 只能出图，交付 = 落文件

取值链与 `integrations/feishu/feishu_client.py` 的 `FeishuClient.__init__` **同序**
（config.yaml → FEISHU_APP_ID → APP_ID）—— 两个地方不一致会让本探测器的结论失效。

用法：
    python scripts/env_probe.py            # 人读（LLM 直接照念）
    python scripts/env_probe.py --json     # 机器可读
退出码：**恒为 0** —— "本地"是一个有效结论，不是失败。
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config import plugin_config, plugin_enabled  # noqa: E402
from plugin import discover  # noqa: E402

FEISHU = 'feishu'

#: 凭证取值链（顺序即优先级，与 feishu_client 同序）。第三档是**飞书生态的约定名**：
#  飞书开放平台官方示例与官方 SDK（`Config.getInternalAppSettingsByEnv()`）用的就是
#  `APP_ID` / `APP_SECRET`，云函数 / 应用引擎**按这个约定注入**。别当成"多余兜底"删掉。
CRED_CHAIN = (
    ('config.yaml', 'config'),
    ('FEISHU_APP_ID', 'env'),
    ('APP_ID', 'platform'),
)


def _feishu_cfg():
    return plugin_config(FEISHU)


def _app_id_source():
    """返回 (来源标签, 值)；都没有则 (None, None)。**只报来源，不回显敏感值**。"""
    cfg = _feishu_cfg()
    for name, kind in CRED_CHAIN:
        if kind == 'config':
            v = cfg.get('app_id')
        else:
            v = os.environ.get(name)
        if v:
            return name, v
    return None, None


def _secret_present():
    cfg = _feishu_cfg()
    return bool(cfg.get('app_secret') or os.environ.get('FEISHU_APP_SECRET')
                or os.environ.get('APP_SECRET'))


def probe(verbose=False):
    """探测并返回结构化结论。`verbose` 让插件发现打印它自己的那几行。"""
    app_id_src, _ = _app_id_source()
    secret = _secret_present()
    platform_cred = bool(os.environ.get('APP_ID') and os.environ.get('APP_SECRET'))

    if platform_cred:
        env, env_why = 'feishu-hosted', '检测到平台注入的 APP_ID / APP_SECRET（飞书托管环境）'
    elif app_id_src:
        env, env_why = 'feishu-configured', f'凭证来自 {app_id_src}（自配，可连飞书）'
    else:
        env, env_why = 'local', '未检测到任何飞书凭证（办公电脑本地环境）'

    # 插件：**注册**（能做什么）与**启用**（允许做什么）分开报——两问不可互相推断
    _, report = discover(verbose=verbose)
    registered = sorted(report['loaded'] + report['disabled']
                        + list(report['missing_deps']) + report['failed'])
    enabled = plugin_enabled(FEISHU)

    caps = {
        'build': True,                       # 只要 scripts 在就能出图
        'source': bool(enabled and app_id_src and secret),
        'publish': bool(enabled and app_id_src and secret),
    }

    if env == 'feishu-hosted':
        advice = ('可直接发布：build 出图后把链接发回聊天（chat_id 来自收到的那条消息）。'
                  '用户问起画板再走 board。')
    elif env == 'feishu-configured':
        advice = ('凭证是自配的，可连飞书但**不保证在托管运行时里**。发布前确认 chat_id 来源可信；'
                  '若只是本机试跑，按本地方式交付更稳。')
    else:
        advice = ('产物**落本地文件**并把路径告诉用户；'
                  '**不要声称「已发送到飞书」** —— 本环境没有那只手。要发就先把凭证配好。')
    if not enabled:
        # **必须前置**：未启用时上面的环境结论一条也用不上，别让"托管可发布"这类话漏出去骗人。
        advice = ('飞书插件**未启用** ⇒ 它的 source / publish 都用不了（下面的建议要等启用后才成立）。'
                  '启用：环境变量 `FLOWCHART_PLUGIN_FEISHU=1`，或把 '
                  '`integrations/feishu/config.yaml` 的 `enabled` 改成 true。　' + advice)

    return {
        'environment': env,
        'environment_why': env_why,
        'credentials': {
            'app_id_source': app_id_src,
            'app_secret_present': secret,
            'platform_injected': platform_cred,
        },
        'plugins': {
            'registered': registered,
            'feishu_enabled': enabled,
        },
        'capabilities': caps,
        'advice': advice,
    }


def _render(r):
    """人读版：LLM 可以直接照念，所以**一句话说清"我是谁、能做什么、该怎么交付"**。"""
    caps = r['capabilities']
    mark = lambda ok: '✓' if ok else '✗'      # noqa: E731
    lines = [
        f"环境: {r['environment']}（{r['environment_why']}）",
        f"凭证: app_id 来自 {r['credentials']['app_id_source'] or '无'}"
        f" · secret {'已设' if r['credentials']['app_secret_present'] else '未设'}",
        f"插件: {', '.join(r['plugins']['registered']) or '无'}"
        f"（feishu {'已启用' if r['plugins']['feishu_enabled'] else '未启用'}）",
        f"可用: build {mark(caps['build'])} · source {mark(caps['source'])}"
        f" · publish {mark(caps['publish'])}",
        f"交付: {r['advice']}",
    ]
    return '\n'.join(lines)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(
        description='运行环境自述：报出当前是飞书托管 / 自配凭证 / 本地办公电脑，以及各项能力',
        epilog='退出码恒为 0——"本地"是有效结论，不是失败。取值链与 feishu_client 同序。')
    ap.add_argument('--json', action='store_true', help='输出机器可读 JSON')
    ap.add_argument('--verbose', action='store_true', help='插件发现过程也打印出来')
    a = ap.parse_args(argv)

    r = probe(verbose=a.verbose)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else _render(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
