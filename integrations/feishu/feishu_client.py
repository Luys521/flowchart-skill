# -*- coding: utf-8 -*-
"""feishu_client.py — 飞书双令牌客户端（飞书插件内部模块，可整体插拔）。

两类凭证，各司其职（详见同目录 README.md）：
  tenant_access_token  应用身份：消息(IM)、云盘(Drive)、多维表格(Bitable) 等；自动获取并缓存。
  user_access_token    用户身份：云文档**导出**（docs:document:export 属用户权限，tenant 调用会被拒）。
                       走 OAuth 授权码：一次性浏览器登录 → 缓存 access/refresh → 到期自动刷新。

零强制第三方依赖：HTTP 用标准库 urllib，配置用核心已有的 PyYAML；
因此本插件在未安装任何可选 SDK 时也能加载（长连接 SDK 到阶段 3 才需要）。

敏感值（app_secret、token）只经环境变量注入或写入本地缓存文件，不回显、不提交。
"""
import argparse
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# 插件目录（本文件所在目录）
PLUGIN_DIR = Path(__file__).resolve().parent

# 默认端点（中国版）
DEFAULT_DOMAIN = "https://open.feishu.cn"
ACCOUNTS_DOMAIN = "https://accounts.feishu.cn"

# OAuth 路径
AUTHORIZE_PATH = "/open-apis/authen/v1/authorize"
TOKEN_PATH = "/open-apis/authen/v2/oauth/token"
TENANT_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"

# 默认用户授权 scope：offline_access 用于拿 refresh_token；docs:document:export 用于云文档导出。
DEFAULT_SCOPES = "offline_access docs:document:export"

# 提前刷新窗口（秒）：到期前先续，避免边界失效
REFRESH_SKEW = 300

# 默认本地 OAuth 回调
DEFAULT_REDIRECT_HOST = "127.0.0.1"
DEFAULT_REDIRECT_PORT = 8765
CALLBACK_PATH = "/callback"

# token 缓存文件名（gitignore）
TOKEN_CACHE_FILE = ".token-cache.json"


class FeishuError(Exception):
    """飞书 API / OAuth 调用失败。code 为平台错误码（可能为 None）。"""

    def __init__(self, message, code=None, payload=None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


def _http_json(method, url, body=None, token=None, headers=None, timeout=40):
    """发起 HTTP 请求并解析 JSON。返回 (status, dict)；网络层错误尽量转成 dict，不裸抛。"""
    raw = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"code": e.code, "msg": "无法解析的错误响应"}
    except Exception as e:  # noqa: BLE001 — 统一转 FeishuError 由上层处理
        raise FeishuError(f"网络请求失败：{type(e).__name__}: {e}")


def _http_get_bytes(url, token, timeout=60):
    """GET 下载二进制内容，返回 bytes。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        raise FeishuError(f"下载失败（HTTP {e.code}）",
                          code=payload.get("code"), payload=payload)


class FeishuClient:
    """双令牌飞书客户端。config 为该插件合并后的配置 dict。"""

    def __init__(self, config=None):
        self.config = config or {}
        self.app_id = self.config.get("app_id") or os.environ.get("FEISHU_APP_ID") \
            or os.environ.get("APP_ID")
        self.app_secret = self.config.get("app_secret") or os.environ.get("FEISHU_APP_SECRET") \
            or os.environ.get("APP_SECRET")
        self.domain = (self.config.get("domain") or DEFAULT_DOMAIN).rstrip("/")
        self.accounts = (self.config.get("accounts_domain") or ACCOUNTS_DOMAIN).rstrip("/")
        self.scopes = self.config.get("scopes") or DEFAULT_SCOPES
        self.redirect_host = self.config.get("redirect_host") or DEFAULT_REDIRECT_HOST
        self.redirect_port = int(self.config.get("redirect_port") or DEFAULT_REDIRECT_PORT)

        cache = self.config.get("token_cache")
        self.token_cache = Path(cache) if cache else PLUGIN_DIR / TOKEN_CACHE_FILE

        # 内存 tenant 缓存
        self._tenant_token = None
        self._tenant_expire_at = 0.0

    # ------------------------------------------------------------------ 凭证校验
    def require_app_credentials(self):
        """缺 app_id/secret 时给可操作的报错。"""
        if not self.app_id or not self.app_secret:
            raise FeishuError(
                "缺少飞书应用凭证：请设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET，"
                "或在 integrations/feishu/config.yaml 配置（参考 config.example.yaml）。")
        return True

    # ------------------------------------------------------------------ 通用 API
    def api(self, method, path, body=None, token=None, headers=None):
        """以应用身份调用标准 OpenAPI（返回完整 dict，code!=0 抛错）。"""
        self.require_app_credentials()
        token = token or self.tenant_token()
        status, r = _http_json(method, self.domain + path, body=body,
                               token=token, headers=headers)
        code = r.get("code")
        if code not in (0, None):
            raise FeishuError(f"飞书接口失败：{r.get('msg')}（code={code}）",
                              code=code, payload=r)
        return r

    def download(self, path, token=None):
        """下载二进制（如导出文件）。token 缺省用 user token。"""
        token = token or self.user_token()
        return _http_get_bytes(self.domain + path, token)

    # ------------------------------------------------------------------ tenant token
    def tenant_token(self):
        """返回有效的 tenant_access_token（内存缓存 + 提前刷新）。"""
        now = time.time()
        if self._tenant_token and now < self._tenant_expire_at - REFRESH_SKEW:
            return self._tenant_token
        self.require_app_credentials()
        status, r = _http_json(
            "POST", self.domain + TENANT_TOKEN_PATH,
            body={"app_id": self.app_id, "app_secret": self.app_secret})
        tok = r.get("tenant_access_token")
        if not tok:
            raise FeishuError(f"获取 tenant_access_token 失败：{r.get('msg')}（code={r.get('code')}）",
                              code=r.get("code"), payload=r)
        self._tenant_token = tok
        self._tenant_expire_at = now + int(r.get("expire", 7200))
        return tok

    # ------------------------------------------------------------------ user OAuth
    def redirect_uri(self):
        """本地 OAuth 回调地址（需与开发者后台「安全设置→重定向 URL」完全一致）。"""
        return f"http://{self.redirect_host}:{self.redirect_port}{CALLBACK_PATH}"

    def authorize_url(self, state=None, scope=None):
        """构造用户授权页 URL。"""
        params = {
            "client_id": self.app_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri(),
            "scope": scope or self.scopes,
            "state": state or secrets.token_urlsafe(16),
        }
        return self.accounts + AUTHORIZE_PATH + "?" + urllib.parse.urlencode(params), params["state"]

    def _token_call(self, payload):
        """POST OAuth v2 token 端点。响应字段平铺（access_token 在顶层）。"""
        status, r = _http_json("POST", self.domain + TOKEN_PATH, body=payload)
        if r.get("access_token"):
            return r
        # 失败：code 为 20xxx，带 error / error_description
        msg = r.get("error_description") or r.get("error") or r.get("msg") or "OAuth 令牌请求失败"
        raise FeishuError(f"{msg}（code={r.get('code')}）", code=r.get("code"), payload=r)

    def exchange_code(self, code, state=None):
        """授权码 → user token，并落缓存。返回 token dict。"""
        self.require_app_credentials()
        r = self._token_call({
            "grant_type": "authorization_code",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "code": code,
            "redirect_uri": self.redirect_uri(),
        })
        self._save_user(r)
        return r

    def refresh_user_token(self, refresh_token):
        """用 refresh_token 换新的 user token（refresh 仅可用一次，返回新 refresh）。"""
        self.require_app_credentials()
        r = self._token_call({
            "grant_type": "refresh_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "refresh_token": refresh_token,
        })
        self._save_user(r)
        return r

    def _save_user(self, r):
        """把 user token 响应写入缓存（记录绝对过期时刻）。"""
        now = time.time()
        doc = {
            "access_token": r.get("access_token"),
            "access_expire_at": now + int(r.get("expires_in", 7200)),
            "refresh_token": r.get("refresh_token"),
            "refresh_expire_at": now + int(r.get("refresh_token_expires_in", 0)),
            "scope": r.get("scope"),
            "token_type": r.get("token_type", "Bearer"),
            "obtained_at": now,
        }
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_cache, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)

    def _load_user(self):
        """读 user token 缓存；不存在/读不动返回 None。"""
        if not self.token_cache.exists():
            return None
        try:
            return json.loads(self.token_cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def user_token(self, force_refresh=False):
        """返回有效的 user_access_token，必要时自动刷新；无法恢复则提示重新登录。"""
        doc = self._load_user()
        if not doc or not doc.get("access_token"):
            raise FeishuError("尚未完成用户授权：请先运行 feishu_client.py login（或插件的登录命令）。")
        now = time.time()
        if not force_refresh and now < float(doc["access_expire_at"]) - REFRESH_SKEW:
            return doc["access_token"]
        # 需要刷新
        rt = doc.get("refresh_token")
        if not rt or now >= float(doc.get("refresh_expire_at", 0)):
            raise FeishuError("user token 已过期且无法自动刷新（refresh_token 缺失/到期）：请重新运行 login。")
        new = self.refresh_user_token(rt)
        return new["access_token"]

    # ------------------------------------------------------------------ 交互式登录
    def login(self, open_browser=True, timeout=300):
        """起本地回调服务，引导浏览器授权，接收 code 换 token。返回 token dict。"""
        self.require_app_credentials()
        url, state = self.authorize_url()
        captured = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def _reply(self, text, ok=True):
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self._reply("回调路径不对。", ok=False)
                    return
                q = urllib.parse.parse_qs(parsed.query)
                if q.get("state", [""])[0] != state:
                    self._reply("state 校验失败，请重试。", ok=False)
                    captured["error"] = "state mismatch"
                    return
                if q.get("code"):
                    captured["code"] = q["code"][0]
                    self._reply("授权成功，可以回到命令行。")
                else:
                    captured["error"] = q.get("error", ["未知错误"])[0]
                    self._reply("授权被拒绝或失败：" + captured["error"], ok=False)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer((self.redirect_host, self.redirect_port), Handler)
        server.timeout = 1
        print("请在浏览器中完成飞书授权（本进程正在等待回调）：")
        print(url)
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline and "code" not in captured and "error" not in captured:
            server.handle_request()
        server.server_close()

        if "code" not in captured:
            raise FeishuError("登录未完成（" + str(captured.get("error", "超时")) + "）。")
        r = self.exchange_code(captured["code"])
        print("✓ 用户授权完成，token 已缓存：" + self.token_cache.as_posix())
        return r

    # ------------------------------------------------------------------ 便捷自检
    def bot_info(self):
        """应用身份自检：拉机器人信息。"""
        return self.api("GET", "/open-apis/bot/v3/info")


def build_client(config=None):
    """工厂：供插件入口/其它模块复用。config 缺省时由核心配置组装。"""
    if config is None:
        # 允许独立运行：把技能 scripts 加入路径后用 env_or_config
        scripts = PLUGIN_DIR.parent.parent / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        try:
            from config import env_or_config  # type: ignore
            app_id = env_or_config("feishu", ["FEISHU_APP_ID", "APP_ID"], "")
            app_secret = env_or_config("feishu", ["FEISHU_APP_SECRET", "APP_SECRET"], "")
        except Exception:
            app_id, app_secret = "", ""
        config = dict(config or {})
        config.setdefault("app_id", app_id)
        config.setdefault("app_secret", app_secret)
    return FeishuClient(config)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="飞书双令牌客户端：登录授权 / 凭证自检")
    ap.add_argument("command", choices=["login", "check", "refresh"],
                    help="login=用户授权登录；check=应用身份自检；refresh=强制刷新 user token")
    ap.add_argument("--no-browser", action="store_true", help="只打印授权 URL，不自动打开浏览器")
    a = ap.parse_args(argv)

    client = build_client()
    try:
        if a.command == "login":
            client.login(open_browser=not a.no_browser)
        elif a.command == "check":
            r = client.bot_info()
            print("✓ 应用身份正常：" + str((r.get("data") or {}).get("app_name", "")))
        elif a.command == "refresh":
            tok = client.user_token(force_refresh=True)
            print("✓ user token 已刷新（长度 " + str(len(tok)) + "）")
    except FeishuError as e:
        print("✗ " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
