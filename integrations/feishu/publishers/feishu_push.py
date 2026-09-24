# -*- coding: utf-8 -*-
"""feishu_push.py — 飞书产物发布器 publisher（应用身份）。

两种交付通道（都走 tenant token）：
  云盘 Drive  POST /drive/v1/files/upload_all（multipart，**不传 checksum**，传了报 1062008）
              → file_token；可指定 parent_node 文件夹（空 = 我的空间根目录）。
  消息 IM     POST /im/v1/messages：
                .png → 先 /im/v1/images 取 image_key，发 image 消息；
                其它（.html/.drawio/.svg/.pdf…）→ 先 /im/v1/files 取 file_key，发 file 消息；
                可先发一条文本说明。

关于 SVG：飞书文档正文插图接口不接受 SVG（仅 jpg/png/bmp/gif），SVG 的原生落点是**画板**。
本阶段 SVG 先作为云盘/IM 文件交付，并在回执里给出画板/PNG 建议；画板写入不在本阶段范围。
"""
import argparse
import json
import mimetypes
import sys
import uuid
from pathlib import Path

from feishu_client import FeishuError, build_client

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}


def _multipart(fields, file_field, filename, filedata, content_type):
    """构造 multipart/form-data（标准库）。返回 (body_bytes, content_type)。"""
    boundary = uuid.uuid4().hex
    lines = []
    for k, v in fields.items():
        lines.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    lines.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n")
    head = "".join(lines).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + filedata + tail, f"multipart/form-data; boundary={boundary}"


def _post_multipart(client, url, fields, file_field, filename, filedata, content_type):
    """POST multipart 并返回完整响应 dict（code!=0 抛错）。"""
    import urllib.request
    body, ct = _multipart(fields, file_field, filename, filedata, content_type)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", ct)
    req.add_header("Authorization", "Bearer " + client.tenant_token())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        # HTTPError 也尝试解析 body
        body_obj = getattr(e, "read", None)
        if body_obj:
            try:
                r = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise FeishuError(f"上传失败：{type(e).__name__}: {e}")
        else:
            raise FeishuError(f"上传失败：{type(e).__name__}: {e}")
    if r.get("code") not in (0, None):
        raise FeishuError(f"上传被拒：{r.get('msg')}（code={r.get('code')}）",
                          code=r.get("code"), payload=r)
    return r


# ---------------------------------------------------------------- 云盘
def upload_drive(client, path, parent_node="", name=None):
    """上传单个文件到云盘，返回 {file_token, name}。"""
    p = Path(path)
    filedata = p.read_bytes()
    fname = name or p.name
    mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    fields = {"file_name": fname, "parent_type": "explorer",
              "parent_node": parent_node, "size": str(len(filedata))}
    r = _post_multipart(client, client.domain + "/open-apis/drive/v1/files/upload_all",
                        fields, "file", fname, filedata, mime)
    token = (r.get("data") or {}).get("file_token")
    return {"file_token": token, "name": fname}


# ---------------------------------------------------------------- IM
def send_text(client, receive_id, text, receive_id_type="chat_id"):
    """发文本消息。"""
    body = {"receive_id": receive_id, "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)}
    return client.api("POST",
                      f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                      body=body)


def upload_im_image(client, path):
    """上传图片取 image_key。"""
    p = Path(path)
    filedata = p.read_bytes()
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    fields = {"image_type": "message"}
    r = _post_multipart(client, client.domain + "/open-apis/im/v1/images",
                        fields, "image", p.name, filedata, mime)
    return (r.get("data") or {}).get("image_key")


def send_image(client, receive_id, image_key, receive_id_type="chat_id"):
    body = {"receive_id": receive_id, "msg_type": "image",
            "content": json.dumps({"image_key": image_key})}
    return client.api("POST",
                      f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                      body=body)


def upload_im_file(client, path):
    """上传文件取 file_key。"""
    p = Path(path)
    filedata = p.read_bytes()
    fields = {"file_type": "stream", "file_name": p.name}
    r = _post_multipart(client, client.domain + "/open-apis/im/v1/files",
                        fields, "file", p.name, filedata, "application/octet-stream")
    return (r.get("data") or {}).get("file_key")


def send_file(client, receive_id, file_key, receive_id_type="chat_id"):
    body = {"receive_id": receive_id, "msg_type": "file",
            "content": json.dumps({"file_key": file_key})}
    return client.api("POST",
                      f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                      body=body)


# ---------------------------------------------------------------- 批量发布
def publish(artifacts, chat_id=None, receive_id_type="chat_id", parent_node="",
            note=None, to_drive=True, config=None):
    """把一批本地产物发布到飞书。

    artifacts：文件路径列表。
    to_drive：是否上传云盘（默认 True）；chat_id 给定时额外推送到群（png 图片、其余文件）。
    note：随附文本说明（chat_id 给定时先发送）。
    返回回执 {drive: [...], im: [...], svg_note: ...}。
    """
    client = build_client(config)
    client.require_app_credentials()
    receipt = {"drive": [], "im": [], "svg_note": None}

    has_svg = any(Path(a).suffix.lower() == ".svg" for a in artifacts)
    if has_svg:
        receipt["svg_note"] = (
            "含 SVG：飞书文档正文不支持 SVG 插图。可①作为文件交付（已做）；"
            "②导入飞书画板；③需要内嵌图片时用 PNG 快照（shot.py）。")

    if chat_id and note:
        send_text(client, chat_id, note, receive_id_type)
        receipt["im"].append({"type": "text"})

    for art in artifacts:
        p = Path(art)
        if to_drive:
            receipt["drive"].append(upload_drive(client, p, parent_node=parent_node))
        if chat_id:
            if p.suffix.lower() in IMAGE_EXTS:
                key = upload_im_image(client, p)
                send_image(client, chat_id, key, receive_id_type)
                receipt["im"].append({"type": "image", "key": key})
            else:
                key = upload_im_file(client, p)
                send_file(client, chat_id, key, receive_id_type)
                receipt["im"].append({"type": "file", "key": key, "name": p.name})
    return receipt


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="飞书产物发布：本地文件 → 云盘 / 群消息")
    ap.add_argument("files", nargs="+", help="要发布的文件路径")
    ap.add_argument("--chat-id", help="目标群 chat_id（不给则只传云盘）")
    ap.add_argument("--folder", default="", help="云盘目标文件夹 token（空=根目录）")
    ap.add_argument("--note", help="随附文本说明")
    ap.add_argument("--no-drive", action="store_true", help="不上传云盘")
    a = ap.parse_args(argv)
    try:
        r = publish(a.files, chat_id=a.chat_id, parent_node=a.folder,
                    note=a.note, to_drive=not a.no_drive)
        print("✓ 发布完成："
              f"云盘 {len(r['drive'])} 个 · 消息 {len(r['im'])} 条")
        if r["svg_note"]:
            print("· " + r["svg_note"])
    except FeishuError as e:
        print("✗ " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
