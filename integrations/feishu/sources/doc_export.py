# -*- coding: utf-8 -*-
"""doc_export.py — 飞书云文档导出 source（用户身份）。

把在线云文档（docx / sheet / bitable / wiki 节点）导出成本地文件（pdf / xlsx / csv / zip 等），
作为"材料 → 流程表"的上游输入。

**为什么必须用户身份**：导出权限 docs:document:export 属用户身份权限，用 tenant token 会被拒
（code=99991672）。本模块统一用 FeishuClient.user_token()（首次需 feishu_client login 授权）。

链路（探针已验证）：
  POST /drive/v1/export_tasks                 → ticket
  GET  /drive/v1/export_tasks/{ticket}?token= → 轮询 job_status=0 → file_token
  GET  /drive/v1/export_tasks/file/{ft}/download → 二进制落盘
"""
import argparse
import re
import sys
import time
import urllib.parse
from pathlib import Path

# 同目录导入（插件目录已在 sys.path）
from feishu_client import FeishuError, build_client

# URL 路径段 → 飞书云盘类型
_PATH_TYPE = {
    "docx": "docx",
    "docs": "doc",
    "sheets": "sheet",
    "base": "bitable",
    "mindnotes": "mindnote",
    "wiki": "wiki",
    "file": "file",
}

# 各源类型支持的导出格式（飞书约束）
_DEFAULT_EXT = {
    "docx": "pdf",
    "doc": "pdf",
    "sheet": "xlsx",
    "bitable": "xlsx",
    "mindnote": "pdf",
}


def parse_doc_ref(ref):
    """从文档 URL 或裸 token 解析出 (token, type)。

    URL 形如 https://<domain>/docx/<token> 、/wiki/<token>；无法识别路径时按 docx 处理。
    wiki 节点的真实类型需再调 wiki get_node 解析（见 _resolve_wiki）。
    """
    ref = (ref or "").strip()
    if not ref:
        raise FeishuError("未提供文档 token 或 URL。")
    if not ref.startswith("http"):
        # 裸 token：默认 docx（可被 --type 覆盖）
        return ref, "docx"
    parsed = urllib.parse.urlparse(ref)
    seg = [s for s in parsed.path.split("/") if s]
    for i, s in enumerate(seg):
        if s in _PATH_TYPE and i + 1 < len(seg):
            return seg[i + 1], _PATH_TYPE[s]
    # 兜底：取最后一段当 token
    return seg[-1], "docx"


def _resolve_wiki(client, token):
    """wiki 节点 → 实际 obj_token / obj_type（GET /wiki/v2/spaces/get_node?token=）。"""
    r = client.api("GET",
                   "/open-apis/wiki/v2/spaces/get_node?token=" + urllib.parse.quote(token),
                   token=client.user_token())
    node = (r.get("data") or {}).get("node") or {}
    return node.get("obj_token"), node.get("obj_type")


def create_export_task(client, token, doc_type, file_extension):
    """创建导出任务，返回 ticket。"""
    body = {"file_extension": file_extension, "token": token, "type": doc_type}
    r = client.api("POST", "/open-apis/drive/v1/export_tasks",
                   body=body, token=client.user_token())
    ticket = (r.get("data") or {}).get("ticket")
    if not ticket:
        raise FeishuError("创建导出任务未返回 ticket。", payload=r)
    return ticket


def poll_export(client, ticket, token, interval=1.5, max_wait=120):
    """轮询导出任务，job_status=0 返回 file_token。"""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = client.api("GET",
                       f"/open-apis/drive/v1/export_tasks/{ticket}?token={token}",
                       token=client.user_token())
        result = (r.get("data") or {}).get("result") or {}
        status = result.get("job_status")
        if status == 0:
            ft = result.get("file_token")
            if not ft:
                raise FeishuError("导出完成但未返回 file_token。", payload=r)
            return ft
        if status not in (1, 2):
            raise FeishuError(
                f"导出失败（job_status={status}）：{result.get('job_error_msg')}", payload=r)
        time.sleep(interval)
    raise FeishuError("导出轮询超时。")


def export_doc(client, ref, out_dir, file_extension=None, doc_type=None, name=None):
    """完整导出：ref(URL/token) → 本地文件，返回文件路径。"""
    token, inferred_type = parse_doc_ref(ref)
    doc_type = doc_type or inferred_type

    if doc_type == "wiki":
        token, doc_type = _resolve_wiki(client, token)
        if not token:
            raise FeishuError("wiki 节点解析失败（确认应用有 wiki 读取权限）。")

    file_extension = file_extension or _DEFAULT_EXT.get(doc_type, "pdf")

    ticket = create_export_task(client, token, doc_type, file_extension)
    file_token = poll_export(client, ticket, token)
    data = client.download(
        f"/open-apis/drive/v1/export_tasks/file/{file_token}/download",
        token=client.user_token())

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    base = name or re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fa5]", "_", token[:12])
    target = out_path / f"{base}.{file_extension}"
    target.write_bytes(data)
    return target


# ---------------------------------------------------------------- source 注册入口
def fetch(ref, out_dir=".", file_extension=None, doc_type=None, name=None, config=None):
    """供 Registry sources 调用：ref → 本地材料文件路径。"""
    client = build_client(config)
    return export_doc(client, ref, out_dir, file_extension, doc_type, name)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="飞书云文档导出（用户身份）：ref → 本地文件")
    ap.add_argument("ref", help="文档 URL 或 token（docx/sheet/base/wiki）")
    ap.add_argument("-o", "--out-dir", default=".")
    ap.add_argument("--ext", help="导出格式（pdf/xlsx/csv/zip，缺省按源类型）")
    ap.add_argument("--type", help="强制源类型（docx/sheet/bitable）")
    ap.add_argument("--name", help="输出文件名（不含扩展名）")
    a = ap.parse_args(argv)
    client = build_client()
    try:
        p = export_doc(client, a.ref, a.out_dir, a.ext, a.type, a.name)
        print("✓ 已导出：" + str(p))
    except FeishuError as e:
        print("✗ " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
