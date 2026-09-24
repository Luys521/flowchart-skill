# -*- coding: utf-8 -*-
"""orchestrate.py — 宿主智能体调用本技能的飞书侧薄门面（prepare / finish / board / bitable）。

架构定位（B 路线）：本技能是被宿主调用的**能力包**，自身不含 LLM、不持飞书长连接。
宿主负责会话、语义理解、@接收、回复；本门面只做"确定性编排 + 飞书落地"。

交付层次（由插件 config.yaml 的 delivery 段配置，全局记忆；CLI 可临时覆盖）：
  finish（默认首选）build → 单文件 HTML 上传云盘 → 群里发 /file/ 链接（在线渲染），
         并按 offer_board 追问一句“需要我提供可编辑的画板吗？”。
  board（按需）用户明确要画板时才调用：建 docx + 可协同编辑画板，发 /docx/ 链接。
  bitable（可选开关 enable_bitable）建独立多维表格承载流程表 12 列，发 /base/ 链接。

退出码（CLI）：0 = 成功；1 = 凭证缺失 / 任一步失败（打印人话报错）。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
SKILL_ROOT = PLUGIN_DIR.parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
for _p in (str(PLUGIN_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from feishu_client import FeishuError, build_client  # noqa: E402

DEFAULT_DELIVERY = {
    "primary": "html",       # html | doc
    "html_to_drive": True,   # HTML 走云盘在线渲染
    "offer_board": True,     # 发 HTML 后追问是否要画板
    "board_on_request": True,
    "enable_bitable": False,
}


# ----------------------------------------------------------------配置
def load_config():
    """加载插件合并配置（config.yaml + 全局段），补 delivery 默认值。凭证由 build_client 经 env 补。"""
    from config import plugin_config
    cfg = plugin_config("feishu")
    delivery = dict(DEFAULT_DELIVERY)
    delivery.update(cfg.get("delivery") or {})
    cfg["delivery"] = delivery
    return cfg


def _domain(cfg):
    import os
    return (cfg.get("tenant_domain")
            or os.environ.get("FEISHU_TENANT_DOMAIN", "")).rstrip("/")


def _require_domain(cfg):
    """拼可访问链接前强制要有租户域名，否则报人话（避免发出 https:///file/ 坏链接）。"""
    domain = _domain(cfg)
    if not domain:
        raise FeishuError(
            "缺少租户域名：请在插件 config.yaml 配置 tenant_domain，"
            "或设环境变量 FEISHU_TENANT_DOMAIN（形如 xxxxx.feishu.cn）。")
    return domain


def _stem_paths(flowtable):
    """flowtable.md → (stem, dsl.yaml, html)（build 输出命名约定）。"""
    ft = Path(flowtable).resolve()
    stem = ft.parent.name
    return ft, stem, ft.parent / f"{stem}-flow.yaml", ft.parent / f"{stem}-flow.html"


def _run_build(flowtable):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build.py"), str(flowtable)],
        cwd=str(SKILL_ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if proc.returncode != 0:
        raise FeishuError("build 失败：" + (proc.stderr or proc.stdout))
    return proc.stdout.strip()


# ----------------------------------------------------------------prepare
def prepare(materials_dir, flowtable, config=None):
    """宿主在语义步骤前调用：检查材料 + 校验流程表（确定性）。"""
    from flowtable_check import run_checks
    materials = Path(materials_dir)
    ft = Path(flowtable)
    files = sorted(p.name for p in materials.glob("*") if p.is_file())
    _title, _meta, rows = run_checks(str(ft))
    return {"materials": files, "node_count": len(rows),
            "flowtable": str(ft.resolve())}


# ----------------------------------------------------------------finish（默认首选：HTML 云盘）
def finish(flowtable, chat_id=None, note=None, config=None, overrides=None):
    """默认：build → HTML 上传云盘 → 群里发 /file/ 链接（+ 画板追问）。

    delivery.primary=doc 时直接建云文档画板（等同 board）。
    """
    cfg = config or load_config()
    delivery = dict(cfg["delivery"])
    delivery.update(overrides or {})

    build_tail = _run_build(flowtable)
    _ft, stem, dsl_path, html_path = _stem_paths(flowtable)
    result = {"build_tail": build_tail}

    # 首选 doc：直接云文档画板
    if delivery.get("primary") == "doc":
        from publishers.feishu_doc import publish_doc
        result["doc"] = publish_doc(
            str(dsl_path), chat_id=chat_id, note=note, config=cfg)
        return result

    # 首选 html
    client = build_client(cfg)
    if delivery.get("html_to_drive"):
        from publishers.feishu_push import send_text, upload_drive
        up = upload_drive(client, str(html_path))
        url = f"https://{_require_domain(cfg)}/file/{up['file_token']}"
        result["html_url"] = url
        result["file_token"] = up["file_token"]
        if chat_id:
            body = url
            if delivery.get("offer_board"):
                body += "\n需要我提供可编辑的画板吗？"
            send_text(client, chat_id,
                      "\n".join(x for x in (note, body) if x))
    else:
        # 退回 IM 文件
        from publishers.feishu_push import send_text, upload_im_file, send_file
        if chat_id and note:
            send_text(client, chat_id, note)
        key = upload_im_file(client, str(html_path))
        if chat_id:
            send_file(client, chat_id, key)
        result["im_file_key"] = key
    return result


# ----------------------------------------------------------------board（按需：云文档 + 画板）
def board(flowtable, chat_id=None, note=None, title=None, config=None):
    """用户明确要"可编辑画板"后调用：建 docx + 画板，授权群可编辑，发 /docx/ 链接。"""
    cfg = config or load_config()
    _ft, _stem, dsl_path, _html = _stem_paths(flowtable)
    domain = _require_domain(cfg)
    from publishers.feishu_doc import publish_doc
    return publish_doc(
        str(dsl_path), chat_id=chat_id, title=title, note=note,
        config=cfg, tenant_domain=domain)


# ----------------------------------------------------------------bitable（可选开关）
def bitable(flowtable, chat_id=None, note=None, config=None):
    """delivery.enable_bitable=true 时：建独立多维表格承载流程表，授权群可编辑，发 /base/ 链接。"""
    cfg = config or load_config()
    if not cfg["delivery"].get("enable_bitable"):
        raise FeishuError(
            "多维表格能力未启用：请在插件 config.yaml 将 delivery.enable_bitable 设为 true。")
    _require_domain(cfg)
    import sync_bitable
    client = build_client(cfg)
    info = sync_bitable.create_standalone(cfg, flowtable, client=client)
    if chat_id:
        client.api(
            "POST",
            f"/open-apis/drive/v1/permissions/{info['app_token']}/members?type=bitable",
            body={"member_type": "openchat", "member_id": chat_id, "perm": "edit"})
        from publishers.feishu_push import send_text
        send_text(client, chat_id,
                  "\n".join(x for x in (note, info["url"]) if x))
    return info


# ----------------------------------------------------------------CLI
def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="飞书薄门面：prepare / finish / board / bitable")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("materials")
    p.add_argument("flowtable")

    f = sub.add_parser("finish", help="默认首选：HTML 云盘链接 + 画板追问")
    f.add_argument("flowtable")
    f.add_argument("--chat-id")
    f.add_argument("--note")
    f.add_argument("--primary", choices=["html", "doc"], default=None)
    f.add_argument("--no-offer-board", action="store_true")
    f.add_argument("--no-drive", action="store_true")

    b = sub.add_parser("board", help="按需：云文档 + 可编辑画板")
    b.add_argument("flowtable")
    b.add_argument("--chat-id")
    b.add_argument("--note")
    b.add_argument("--title")

    t = sub.add_parser("bitable", help="可选开关：独立多维表格")
    t.add_argument("flowtable")
    t.add_argument("--chat-id")
    t.add_argument("--note")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "prepare":
            r = prepare(a.materials, a.flowtable)
        elif a.cmd == "finish":
            overrides = {}
            if a.primary:
                overrides["primary"] = a.primary
            if a.no_offer_board:
                overrides["offer_board"] = False
            if a.no_drive:
                overrides["html_to_drive"] = False
            r = finish(a.flowtable, chat_id=a.chat_id, note=a.note,
                       overrides=overrides)
        elif a.cmd == "board":
            r = board(a.flowtable, chat_id=a.chat_id, note=a.note,
                      title=a.title)
        else:
            r = bitable(a.flowtable, chat_id=a.chat_id, note=a.note)
        print(json.dumps({"ok": True, "result": r}, ensure_ascii=False,
                         indent=2, default=str))
        return 0
    except FeishuError as e:
        print(json.dumps({"ok": False, "error": str(e)},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
