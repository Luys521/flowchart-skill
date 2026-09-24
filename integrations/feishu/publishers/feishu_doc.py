# -*- coding: utf-8 -*-
"""feishu_doc.py — 飞书云文档发布器（DSL → docx + 可在线协同编辑的画板流程图）。

交付流程（阶段 4c，应用身份 tenant token）：
  1. 建一篇 docx；
  2. 文档内插一个画板 block（block_type=43），拿到 whiteboard_id；
  3. 按我方 DSL 的几何/配色 POST 图形节点（composite_shape，样式**嵌套 style**）；
  4. 用节点返回的 data.ids 作为附着点 POST 连线（connector，shape=right_angled_polyline，
     走线由服务端自动正交，端口与附着点按我方几何）；
  5. 授权目标群可编辑（member_type=openchat / perm=edit）；
  6. 群里只发云文档链接（文件后置，本发布器不上传文件）。

几何复用核心 engine.load（L.rect 给坐标、L.path 给端口方向），本模块只做"DSL→画板 JSON"翻译，
不重算布局。核心零 import feishu；本文件在 integrations/feishu 内，可整体插拔。

退出码（CLI）：0 = 已建并返回链接；1 = 凭证缺失 / 任一步失败（人话报错；已建文档不会自动删，
可用返回的 document_id 调 DELETE /open-apis/drive/v1/files/:id?type=docx 清理）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

PUBLISHERS_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = PUBLISHERS_DIR.parent
SKILL_ROOT = PLUGIN_DIR.parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
for _p in (str(PLUGIN_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from feishu_client import FeishuError, build_client  # noqa: E402

# DSL 节点类型 → 画板 composite_shape.type
BOARD_SHAPE = {
    "start": "round_rect2",      # 胶囊（开始/结束）
    "end": "round_rect2",
    "task": "round_rect",        # 圆角矩形
    "decision": "diamond",       # 菱形
}

_EPS = 1.5


def _nearest(px, py, rect):
    """点没落在边界容差内时，按最近边给 (snap_to, position)。"""
    x, y, w, h = rect
    cands = {
        "left": (abs(px - x), {"x": 0, "y": max(0.0, min(1.0, (py - y) / h))}),
        "right": (abs(px - (x + w)), {"x": 1, "y": max(0.0, min(1.0, (py - y) / h))}),
        "top": (abs(py - y), {"x": max(0.0, min(1.0, (px - x) / w)), "y": 0}),
        "bottom": (abs(py - (y + h)), {"x": max(0.0, min(1.0, (px - x) / w)), "y": 1}),
    }
    snap, (_, pos) = min(cands.items(), key=lambda kv: kv[1][0])
    return snap, {k: round(v, 3) for k, v in pos.items()}


def _port(px, py, rect):
    """节点边界上的点 → (snap_to, position)；position 为相对框的归一化坐标。"""
    x, y, w, h = rect
    dL, dR = abs(px - x), abs(px - (x + w))
    dT, dB = abs(py - y), abs(py - (y + h))
    ry = max(0.0, min(1.0, (py - y) / h))
    rx = max(0.0, min(1.0, (px - x) / w))
    if dL <= _EPS and dL <= min(dR, dT, dB):
        return "left", {"x": 0, "y": round(ry, 3)}
    if dR <= _EPS and dR <= min(dT, dB):
        return "right", {"x": 1, "y": round(ry, 3)}
    if dT <= _EPS and dT <= dB:
        return "top", {"x": round(rx, 3), "y": 0}
    if dB <= _EPS:
        return "bottom", {"x": round(rx, 3), "y": 1}
    return _nearest(px, py, rect)


def _shape_node(L, n):
    """DSL 节点 → 画板 composite_shape JSON（样式嵌套 style）。"""
    x, y, w, h = L.rect(n["id"])
    subjects = L.dsl["meta"].get("subjects", {})
    col = subjects.get(n.get("subject")) or subjects.get("默认") or {}
    return {
        "type": "composite_shape",
        "x": int(round(x)), "y": int(round(y)),
        "width": int(round(w)), "height": int(round(h)),
        "composite_shape": {"type": BOARD_SHAPE.get(n["type"], "round_rect")},
        "style": {
            "fill_color": col.get("fill", "#f0f4fc"),
            "border_color": col.get("stroke", "#000000"),
            "border_style": "solid", "border_width": "narrow",
            "fill_opacity": 100, "border_opacity": 100,
        },
        "text": {"text": n.get("name", ""), "font_size": 14,
                 "horizontal_align": "center", "vertical_align": "mid"},
    }


def _connector(L, e, id_map):
    """DSL 边 → 画板 connector JSON（起止附着点按我方几何，走线服务端自动正交）。"""
    pts = L.path(e)
    s_snap, s_pos = _port(pts[0][0], pts[0][1], L.rect(e["from"]))
    t_snap, t_pos = _port(pts[-1][0], pts[-1][1], L.rect(e["to"]))
    conn = {
        "type": "connector",
        "connector": {
            "start": {"arrow_style": "none", "attached_object": {
                "id": id_map[e["from"]], "position": s_pos, "snap_to": s_snap}},
            "end": {"arrow_style": "triangle_arrow", "attached_object": {
                "id": id_map[e["to"]], "position": t_pos, "snap_to": t_snap}},
            "shape": "right_angled_polyline",
        },
    }
    if e.get("label"):
        conn["connector"]["captions"] = {
            "data": [{"text": e["label"], "font_size": 12}]}
    return conn


def publish_doc(dsl_path, chat_id=None, title=None, note=None, config=None,
                share=True, push=True, tenant_domain=None):
    """DSL → 飞书云文档（docx + 可编辑画板）。

    返回 {document_id, whiteboard_id, url, node_count, edge_count}。
    chat_id 给定时：授权该群可编辑（share=True）并把链接发到群里（push=True）。
    """
    from engine import load

    dsl_path = Path(dsl_path).resolve()
    L = load(str(dsl_path))
    L.head_band(False)

    client = build_client(config)
    client.require_app_credentials()
    title = title or L.dsl.get("meta", {}).get("title", "流程图")

    # 1) 建 docx
    r = client.api("POST", "/open-apis/docx/v1/documents", body={"title": title})
    doc_id = r["data"]["document"]["document_id"]

    # 2) page 根 block
    r = client.api("GET", f"/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=20")
    blocks = (r.get("data") or {}).get("items") or []
    page_id = next((b["block_id"] for b in blocks if b.get("block_type") == 1), doc_id)

    # 3) 插一个画板 block
    r = client.api(
        "POST",
        f"/open-apis/docx/v1/documents/{doc_id}/blocks/{page_id}/children",
        body={"index": 0, "children": [{"block_type": 43, "board": {}}]})
    children = (r.get("data") or {}).get("children") or []
    wb = (children[0].get("board", {}) if children else {}).get("token")
    if not wb:
        raise FeishuError("插画板 block 失败，未拿到 whiteboard_id", payload=r)

    # 4) POST 图形节点
    dsl_nodes = L.dsl["nodes"]
    r = client.api("POST", f"/open-apis/board/v1/whiteboards/{wb}/nodes",
                   body={"nodes": [_shape_node(L, n) for n in dsl_nodes]})
    board_ids = (r.get("data") or {}).get("ids") or []
    if len(board_ids) != len(dsl_nodes):
        raise FeishuError(
            f"画板节点数不符：要 {len(dsl_nodes)}，回 {len(board_ids)}", payload=r)
    id_map = {n["id"]: bid for n, bid in zip(dsl_nodes, board_ids)}

    # 5) POST 连线
    connectors = [_connector(L, e, id_map) for e in L.edges]
    if connectors:
        client.api("POST", f"/open-apis/board/v1/whiteboards/{wb}/nodes",
                   body={"nodes": connectors})

    # 6) 授权群可编辑
    if share and chat_id:
        client.api(
            "POST",
            f"/open-apis/drive/v1/permissions/{doc_id}/members?type=docx",
            body={"member_type": "openchat", "member_id": chat_id, "perm": "edit"})

    # 7) 文档链接（租户域名来自参数 / config / 环境变量）
    domain = (tenant_domain or (config or {}).get("tenant_domain")
              or os.environ.get("FEISHU_TENANT_DOMAIN", "")).rstrip("/")
    url = f"https://{domain}/docx/{doc_id}" if domain else None

    # 8) 群里只发链接（文件后置）
    if push and chat_id:
        from publishers.feishu_push import send_text
        send_text(client, chat_id, "\n".join(x for x in (note, url) if x))

    return {"document_id": doc_id, "whiteboard_id": wb, "url": url,
            "node_count": len(dsl_nodes), "edge_count": len(L.edges)}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="DSL → 飞书云文档（docx + 可编辑画板流程图）")
    ap.add_argument("dsl", help="DSL yaml 路径")
    ap.add_argument("--chat-id", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--note", default=None)
    ap.add_argument("--tenant-domain", default=None)
    ap.add_argument("--no-share", action="store_true", help="不授权群可编辑")
    ap.add_argument("--no-push", action="store_true", help="不发群消息")
    a = ap.parse_args(argv)
    try:
        r = publish_doc(a.dsl, chat_id=a.chat_id, title=a.title, note=a.note,
                        share=not a.no_share, push=not a.no_push,
                        tenant_domain=a.tenant_domain)
        print(json.dumps({"ok": True, "result": r}, ensure_ascii=False, indent=2))
        return 0
    except FeishuError as e:
        print(json.dumps({"ok": False, "error": str(e)},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
