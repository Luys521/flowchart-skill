# -*- coding: utf-8 -*-
"""sync_bitable.py — 流程表 12 列 ↔ 飞书多维表格 双向同步（飞书插件内部模块，可整体插拔）。

两条主路径：
  push：flowtable.md → 解析 12 列 → ensure_schema（复用文档内空表的 3 个默认字段）→
        记录增 / 改 / 删对齐（批量）。
  pull：多维表格记录 → 反解 12 列 → rows_to_flowtable 只重建主表、保留身份区 / 配置区 / 表后内容。

多维表格默认作为**独立 app** 交付（delivery.enable_bitable=true 或用户明确要可编辑表格时）；
app_token / table_id 也可从文档内嵌 bitable block 的 bitable.token（形如 appToken_tableId）拆出。
核心 scripts/ 零 import feishu，本文件在 integrations/feishu 内。

退出码（CLI）：0 = 同步成功；1 = 凭证缺失 / 任一步失败（人话报错）；2 = 读不到 flowtable。
"""
import argparse
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
SKILL_ROOT = PLUGIN_DIR.parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
for _p in (str(PLUGIN_DIR), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from feishu_client import FeishuError, build_client  # noqa: E402
from flowtable import COLUMNS, C_ID, split_row_cells  # noqa: E402

# ----------------------------------------------------------------字段规格
# bitable 展示顺序（主字段必须第一且固定为"节点编号"；其余按可读性排）。
# type：1 文本 / 3 单选。dynamic=True 的单选，选项从流程表数据收集。
BITABLE_ORDER = [
    ("节点编号", 1, False),
    ("节点名称", 1, False),
    ("节点类型", 3, False),
    ("项目运作阶段", 3, True),
    ("执行主体", 3, True),
    ("输入", 1, False),
    ("依据", 1, False),
    ("输出", 1, False),
    ("执行者", 1, False),
    ("行动所需时间", 1, False),
    ("下个节点", 1, False),
    ("节点描述", 1, False),
]
NODE_TYPES = ["开始", "结束", "任务", "判断"]
# 文档内空表默认字段名（中英文，命中即可改造复用）
DEFAULT_FIELD_NAMES = {
    "Multiline", "Multiline 1", "Single option", "Text", "Text 1",
    "Single Select", "单选", "多行文本", "多行文本 1",
}
SELECT_COLS = {"节点类型", "项目运作阶段", "执行主体"}


# ----------------------------------------------------------------值转换
def _options_for(name, rows):
    """单选字段的选项：节点类型固定；阶段 / 主体从数据行收集唯一非空值。"""
    if name == "节点类型":
        return [{"name": t} for t in NODE_TYPES]
    col_idx = COLUMNS.index(name)
    seen = []
    for r in rows:
        v = (r[col_idx] or "").strip()
        if v and v not in seen:
            seen.append(v)
    return [{"name": v} for v in seen]


def _record_fields(cells):
    """12 列单元格 → bitable records.fields（单选 / 文本都传字符串；空串传 None）。"""
    out = {}
    for name, _t, _d in BITABLE_ORDER:
        v = (cells[COLUMNS.index(name)] or "").strip()
        out[name] = v if v else None
    return out


def _to_text(v):
    """bitable 字段值 → 纯文本（兼容字符串 / 富文本数组 / 选项对象 / None）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("text") or v.get("name") or ""
    if isinstance(v, list):
        parts = [_to_text(x) for x in v]
        return "".join(p for p in parts if p)
    return str(v)


# ----------------------------------------------------------------schema
def _list_fields(client, app_token, table_id):
    r = client.api("GET",
                   f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields?page_size=100")
    return (r.get("data") or {}).get("items") or []


def ensure_schema(client, app_token, table_id, rows=None):
    """让该表字段与 BITABLE_ORDER 对齐：复用默认字段改造、缺失新建、多余默认字段删除。幂等。"""
    rows = rows or []
    existing = _list_fields(client, app_token, table_id)
    by_name = {f["field_name"]: f for f in existing}
    used_ids = set()

    # 主字段（is_primary）固定第一，必须保留改造
    primary = next((f for f in existing if f.get("is_primary")), existing[0] if existing else None)

    for name, ftype, _dynamic in BITABLE_ORDER:
        opts = _options_for(name, rows)
        target = {"field_name": name, "type": ftype}
        if ftype == 3:
            target["property"] = {"options": opts}

        # 1) 已存在同名字段 → 单选补选项
        if name in by_name:
            f = by_name[name]
            used_ids.add(f["field_id"])
            if ftype == 3:
                client.api(
                    "PUT",
                    f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{f['field_id']}",
                    body=target)
            continue

        # 2) 主字段 → 改造为"节点编号"
        if primary is not None and name == "节点编号" and primary["field_id"] not in used_ids:
            client.api(
                "PUT",
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{primary['field_id']}",
                body=target)
            used_ids.add(primary["field_id"])
            continue

        # 3) 找一个类型兼容、未占用的默认字段改造
        candidate = next((f for f in existing
                          if f["field_id"] not in used_ids
                          and f.get("type") == ftype
                          and f["field_name"] in DEFAULT_FIELD_NAMES), None)
        if candidate is not None:
            client.api(
                "PUT",
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{candidate['field_id']}",
                body=target)
            used_ids.add(candidate["field_id"])
            continue

        # 4) 新建
        client.api(
            "POST",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            body=target)

    # 5) 清理仍是默认名、未被改造 / 占用的残留字段
    for f in existing:
        if f["field_id"] not in used_ids and f["field_name"] in DEFAULT_FIELD_NAMES:
            client.api(
                "DELETE",
                f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{f['field_id']}")


# ----------------------------------------------------------------记录读取
def _list_all_records(client, app_token, table_id):
    """分页拉全量记录 → items（含 record_id / fields）。"""
    items, page_token = [], None
    while True:
        path = (f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
                f"?page_size=500" + (f"&page_token={page_token}" if page_token else ""))
        r = client.api("GET", path)
        data = r.get("data") or {}
        items += data.get("items") or []
        if data.get("has_more") and data.get("page_token"):
            page_token = data["page_token"]
            continue
        break
    return items


def _is_blank_record(fields):
    return not any(_to_text(v).strip() for v in (fields or {}).values())


def pull_records(client, app_token, table_id, drop_blank=True):
    """多维表格 → 12 列 rows（按 COLUMNS 顺序）；默认丢弃全空行，按节点编号排序。"""
    items = _list_all_records(client, app_token, table_id)
    rows = []
    for it in items:
        cells = [_to_text(it["fields"].get(name)).strip() for name in COLUMNS]
        if drop_blank and _is_blank_record(it["fields"]):
            continue
        rows.append(split_row_cells(cells))

    def _key(r):
        raw = r[C_ID]
        return (0, "") if not raw else (1, raw)
    return sorted(rows, key=_key)


# ----------------------------------------------------------------记录写入
def sync_records(client, app_token, table_id, rows):
    """用 rows 对齐表内记录：按"节点编号"匹配，批量增 / 改 / 删，清空默认空行。"""
    items = _list_all_records(client, app_token, table_id)
    by_id, blank_ids = {}, []
    for it in items:
        nid = _to_text(it["fields"].get("节点编号")).strip()
        if not nid and _is_blank_record(it["fields"]):
            blank_ids.append(it["record_id"])
        elif nid:
            by_id[nid] = it["record_id"]

    wanted = {r[C_ID].strip() for r in rows if r[C_ID].strip()}

    to_create, to_update = [], []
    for r in rows:
        nid = r[C_ID].strip()
        if not nid:
            continue
        fields = _record_fields(r)
        if nid in by_id:
            to_update.append({"record_id": by_id[nid], "fields": fields})
        else:
            to_create.append({"fields": fields})
    to_delete = blank_ids + [rid for nid, rid in by_id.items() if nid not in wanted]

    base = f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    if to_create:
        client.api("POST", base + "/batch_create", body={"records": to_create})
    if to_update:
        client.api("POST", base + "/batch_update", body={"records": to_update})
    if to_delete:
        client.api("POST", base + "/batch_delete", body={"records": to_delete})
    return {"created": len(to_create), "updated": len(to_update),
            "deleted": len(to_delete)}


# ----------------------------------------------------------------flowtable 重建
def _escape_cell(v):
    """文本 → markdown 表格安全形态（| 转义）。"""
    return str(v).replace("|", "\\|")


def rows_to_flowtable(orig_text, rows):
    """只重建主表数据行，保留表头 / 分隔行 / 表前身份区与配置区 / 表后内容。返回新文本。"""
    lines = orig_text.splitlines()
    header_idx = next((i for i, l in enumerate(lines)
                       if l.startswith("|") and "节点编号" in l), -1)
    if header_idx < 0:
        raise FeishuError("原流程表缺少标准表头（须含「节点编号」列）")
    end_idx = header_idx
    while end_idx < len(lines) and lines[end_idx].startswith("|"):
        end_idx += 1

    new_data = []
    for r in rows:
        cells = split_row_cells(list(r))
        new_data.append("| " + " | ".join(_escape_cell(c) for c in cells) + " |")

    out_lines = lines[:header_idx + 2] + new_data + lines[end_idx:]
    tail = "\n" if orig_text.endswith("\n") else ""
    return "\n".join(out_lines) + tail


# ----------------------------------------------------------------push / pull 入口
def split_bitable_token(raw):
    """bitable.token（appToken_tableId）→ (app_token, table_id)。"""
    app, _, table = raw.rpartition("_")
    return app, table


def push_flowtable(flowtable_path, app_token, table_id, client=None):
    """flowtable.md → 多维表格（schema + 记录对齐）。"""
    from flowtable import parse_table
    ft = Path(flowtable_path)
    if not ft.exists():
        raise FeishuError(f"找不到流程表：{ft}")
    title, _meta, raw_rows = parse_table(ft.read_text(encoding="utf-8-sig"))
    rows = [split_row_cells(r) for r in raw_rows]
    client = client or build_client()
    ensure_schema(client, app_token, table_id, rows)
    stats = sync_records(client, app_token, table_id, rows)
    return {"title": title, "rows": len(rows), **stats}


def pull_to_flowtable(app_token, table_id, orig_flowtable, out_path=None, client=None):
    """多维表格 → 反解并重建 flowtable（写到 out_path，缺省覆盖 orig 的 .pull.md）。"""
    client = client or build_client()
    rows = pull_records(client, app_token, table_id)
    orig = Path(orig_flowtable)
    out = Path(out_path) if out_path else orig.parent / (orig.stem + ".pull.md")
    new_text = rows_to_flowtable(orig.read_text(encoding="utf-8-sig"), rows)
    out.write_text(new_text, encoding="utf-8", newline="\n")
    return {"out": str(out), "rows": len(rows)}


def create_standalone(config, flowtable_path, client=None, name=None):
    """新建独立多维表格 app + 表 → push 流程表，返回 {app_token, table_id, url, 增删改}。

    独立于 docx，供 delivery.enable_bitable=true 或用户明确要可编辑表格时使用。
    chat 授权由调用方（门面）按需补。
    """
    import os
    from flowtable import parse_table
    ft = Path(flowtable_path)
    title, _meta, raw_rows = parse_table(ft.read_text(encoding="utf-8-sig"))
    name = name or title or "流程表"
    client = client or build_client(config)

    r = client.api("POST", "/open-apis/bitable/v1/apps", body={"name": name})
    app_token = r["data"]["app"]["app_token"]
    r = client.api(
        "POST", f"/open-apis/bitable/v1/apps/{app_token}/tables",
        body={"table": {
            "name": "流程表", "default_view_name": "流程表",
            # 建表必须带 fields：先给主字段“节点编号”，其余 ensure_schema 补齐
            "fields": [{"field_name": "节点编号", "type": 1}]}})
    table_id = r["data"]["table_id"]

    rows = [split_row_cells(x) for x in raw_rows]
    ensure_schema(client, app_token, table_id, rows)
    stats = sync_records(client, app_token, table_id, rows)

    domain = ((config or {}).get("tenant_domain")
              or os.environ.get("FEISHU_TENANT_DOMAIN", "")).rstrip("/")
    url = f"https://{domain}/base/{app_token}" if domain else None
    return {"app_token": app_token, "table_id": table_id, "url": url, **stats}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="流程表 12 列 ↔ 飞书多维表格双向同步")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("push", help="flowtable → 多维表格")
    p.add_argument("flowtable")
    p.add_argument("--app-token", required=True)
    p.add_argument("--table-id", required=True)

    g = sub.add_parser("pull", help="多维表格 → flowtable")
    g.add_argument("--app-token", required=True)
    g.add_argument("--table-id", required=True)
    g.add_argument("--orig", required=True, help="原 flowtable（提供表头 / 表前后内容）")
    g.add_argument("-o", "--out", default=None)

    a = ap.parse_args(argv)
    try:
        if a.cmd == "push":
            r = push_flowtable(a.flowtable, a.app_token, a.table_id)
        else:
            r = pull_to_flowtable(a.app_token, a.table_id, a.orig, a.out)
        print(json.dumps({"ok": True, "result": r}, ensure_ascii=False, indent=2))
        return 0
    except FeishuError as e:
        print(json.dumps({"ok": False, "error": str(e)},
                         ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
