# -*- coding: utf-8 -*-
"""approval.py — 飞书审批 source（应用身份）。

把审批定义 / 审批实例（含表单字段、审批流转记录）拉取下来，结构化为"材料 → 流程表"的上游输入。

已验证的平台约束：
  · 没有"列出租户全部审批定义"的开放接口——必须先知道 **approval_code**（审批定义后台可见，
    或由审批开放接口/事件获得）。本模块在缺 code 时给明确提示。
  · 应用需被授权访问该审批定义（审批后台 → API 接入 / 应用授权），否则查询会被拒。
  · 审批走 **tenant token（应用身份）**，与云文档导出（用户身份）不同。

接口：
  GET  /approval/v4/approvals/{code}            审批定义
  POST /approval/v4/instances/query             按条件查实例（分页）
  GET  /approval/v4/instances/{instance_code}   实例详情（表单 + 流转）
"""
import argparse
import json
import sys
from pathlib import Path

from feishu_client import FeishuError, build_client


def fetch_definition(client, approval_code):
    """审批定义（含表单控件、节点流程）。"""
    r = client.api("GET", f"/open-apis/approval/v4/approvals/{approval_code}")
    return (r.get("data") or {}).get("approval") or r.get("data")


def query_instances(client, approval_code, page_size=100, page_token=None,
                    start_time=None, end_time=None, status=None):
    """查询审批实例（单页）。返回 {items, page_token, has_more}。"""
    body = {"approval_code": approval_code, "page_size": page_size}
    if page_token:
        body["page_token"] = page_token
    filters = {}
    if start_time:
        filters["start_time"] = start_time
    if end_time:
        filters["end_time"] = end_time
    if status:
        filters["status"] = status          # PENDING/APPROVED/REJECTED/CANCELED/DELETED
    if filters:
        body["filters"] = filters
    r = client.api("POST", "/open-apis/approval/v4/instances/query", body=body)
    data = r.get("data") or {}
    return {
        "items": data.get("instances") or data.get("items") or [],
        "page_token": data.get("page_token"),
        "has_more": bool(data.get("has_more")),
    }


def get_instance(client, instance_code):
    """实例详情（表单字段 form、流转任务 task_list、评论 comment_list 等）。"""
    r = client.api("GET", f"/open-apis/approval/v4/instances/{instance_code}")
    return (r.get("data") or {}).get("instance") or r.get("data")


def all_instances(client, approval_code, max_pages=50, **filters):
    """翻页拉全部实例（带上限，避免失控）。"""
    out, token = [], None
    for _ in range(max_pages):
        page = query_instances(client, approval_code, page_token=token, **filters)
        out.extend(page["items"])
        if not page["has_more"] or not page["page_token"]:
            break
        token = page["page_token"]
    return out


def _instance_brief(instance):
    """从实例里提炼一份可读摘要（表单字段、状态、起止时间）。"""
    def _form_rows(form):
        rows = []
        try:
            for ctl in json.loads(form or "[]"):
                rows.append({"控件": ctl.get("name"), "值": ctl.get("value")})
        except (TypeError, json.JSONDecodeError):
            pass
        return rows

    return {
        "instance_code": instance.get("instance_code"),
        "status": instance.get("status"),
        "serial_number": instance.get("serial_number"),
        "start_time": instance.get("start_time"),
        "end_time": instance.get("end_time"),
        "form": _form_rows(instance.get("form")),
    }


def export_approval(client, approval_code, out_dir, with_detail=True,
                    as_markdown=False, **filters):
    """拉定义 + 实例，落本地材料文件，返回文件路径。"""
    if not approval_code:
        raise FeishuError(
            "缺少 approval_code：飞书没有列出全部审批定义的接口，请在审批后台（或审批定义的"
            " API 接入页）获取该审批定义的 code 后重试。")
    definition = fetch_definition(client, approval_code)
    instances = all_instances(client, approval_code, **filters)
    details = []
    if with_detail:
        for inst in instances:
            code = inst.get("instance_code") if isinstance(inst, dict) else inst
            try:
                details.append(get_instance(client, code))
            except FeishuError:
                details.append(inst)
    else:
        details = [_instance_brief(i) if isinstance(i, dict) else i for i in instances]

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    payload = {"approval_code": approval_code,
               "definition": definition,
               "instances": details}
    target = out_path / f"approval-{approval_code}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    return target


# ---------------------------------------------------------------- source 注册入口
def fetch(approval_code, out_dir=".", with_detail=True, config=None, **filters):
    """供 Registry sources 调用：approval_code → 本地材料 JSON 路径。"""
    client = build_client(config)
    return export_approval(client, approval_code, out_dir, with_detail, **filters)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="飞书审批拉取（应用身份）：approval_code → 本地材料")
    ap.add_argument("approval_code", help="审批定义 code（审批后台获取）")
    ap.add_argument("-o", "--out-dir", default=".")
    ap.add_argument("--no-detail", action="store_true", help="只拉实例列表，不逐个取详情")
    ap.add_argument("--status", help="按状态过滤 PENDING/APPROVED/REJECTED/CANCELED")
    a = ap.parse_args(argv)
    client = build_client()
    try:
        p = export_approval(client, a.approval_code, a.out_dir,
                            with_detail=not a.no_detail, status=a.status)
        print("✓ 已拉取审批材料：" + str(p))
    except FeishuError as e:
        print("✗ " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
