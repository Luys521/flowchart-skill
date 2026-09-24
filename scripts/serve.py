# -*- coding: utf-8 -*-
"""serve.py — 技能调用网关（薄、无 LLM、不连飞书长连接）。

架构定位（B：SKILL 给别的智能体加能力）：flowchart-skill 是"被宿主智能体调用的能力包"，
本身不常驻、不持有飞书长连接、不与常驻 Agent 抢消息。本网关只把技能的**确定性原子**
（取材料 / build / 发布）统一成宿主最易消费的契约：

  · 零依赖单次 JSON 调用：
      python scripts/serve.py --run '<请求 JSON>' --plugin feishu
    请求也可用 --run - 从 stdin 读。
  · 可选 HTTP（装了 fastapi + uvicorn 才启用）：
      python scripts/serve.py --http --host 127.0.0.1 --port 8760
    POST /invoke（请求 JSON）、GET /health。

擅长命令行的宿主直接调 doc_export / build / feishu_push 即可，无需起本网关。
语义步骤（读懂材料 → 写流程表）归宿主智能体，网关不代做、也不内置任何模型。

请求/响应均为 JSON。动作：ping / source / build / publish，详见
integrations/feishu/HOST_CONTRACT.md。

退出码（单次模式）：0 = 请求执行成功；1 = 请求级失败（JSON 非法 / 动作报错 / build 失败）；
2 保留给输入读不了。HTTP 模式的成败由 HTTP 状态码表达。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import plugin as plugin_mod  # noqa: E402


def _jsonable(v):
    """把 Path / 嵌套容器转成可 JSON 序列化的普通值。"""
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def load_registry(plugins=None, verbose=False):
    """加载插件：--plugin 指定时只加载并强制启用这些插件；否则按配置/环境（默认全关）。"""
    only = plugins or None
    overrides = {p: True for p in plugins} if plugins else None
    registry, report = plugin_mod.discover(
        registry=None, only=only, ctx=None,
        cli_overrides=overrides, verbose=verbose)
    return registry, report


def _act_source(registry, args):
    name = args.pop("source", None) or "feishu_doc_export"
    fns = registry.all("sources")
    if name not in fns:
        raise KeyError(f"未注册的 source：{name}（已注册：{sorted(fns)}）")
    res = fns[name](**args)
    return {"source": name, "result": _jsonable(res)}


def _act_publish(registry, args):
    name = args.pop("publisher", None) or "feishu"
    fns = registry.all("publishers")
    if name not in fns:
        raise KeyError(f"未注册的 publisher：{name}（已注册：{sorted(fns)}）")
    res = fns[name](**args)
    return {"publisher": name, "receipt": _jsonable(res)}


def _act_build(registry, args):
    ft = Path(args["flowtable"]).resolve()
    if not ft.exists():
        raise FileNotFoundError(f"流程表不存在：{ft}")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build.py"), str(ft)],
        cwd=str(SKILL_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-1200:]
        raise RuntimeError(f"build 失败（rc={proc.returncode}）：\n{tail}")
    stem = ft.parent.name
    products = []
    for ext in ("html", "drawio", "svg"):
        p = ft.parent / f"{stem}-flow.{ext}"
        if p.exists():
            products.append(str(p))
    return {"products": products, "stdout_tail": (proc.stdout or "")[-800:]}


def run_request(req, registry):
    action = (req or {}).get("action")
    args = dict((req or {}).get("args") or {})
    if action == "ping":
        return {"snapshot": registry.snapshot()}
    if action == "source":
        return _act_source(registry, args)
    if action == "publish":
        return _act_publish(registry, args)
    if action == "build":
        return _act_build(registry, args)
    raise ValueError("未知 action：%s（ping / source / build / publish）" % action)


def _single(req_text, plugins):
    try:
        req = json.loads(req_text)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"请求不是合法 JSON：{e}"}, 1
    registry, _ = load_registry(plugins)
    try:
        result = run_request(req, registry)
        return {"ok": True, "action": req.get("action"), "result": result}, 0
    except Exception as e:  # noqa: BLE001 — 统一成 JSON 错误返回给宿主
        return {"ok": False, "action": req.get("action"),
                "error_type": type(e).__name__, "error": str(e)}, 1


def _http(plugins, host, port):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        import uvicorn
    except ImportError:
        print("HTTP 模式需要 fastapi 和 uvicorn：python -m pip install fastapi uvicorn",
              file=sys.stderr)
        return 1

    app = FastAPI(title="flowchart-skill gateway")
    registry, _ = load_registry(plugins)

    @app.get("/health")
    def health():
        return {"ok": True, "snapshot": registry.snapshot()}

    @app.post("/invoke")
    async def invoke(r: Request):
        req = await r.json()
        try:
            result = run_request(req, registry)
            return JSONResponse(
                {"ok": True, "action": req.get("action"), "result": result})
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {"ok": False, "error_type": type(e).__name__, "error": str(e)},
                status_code=400)

    uvicorn.run(app, host=host, port=port)
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="flowchart-skill 调用网关（无 LLM、不连飞书长连接）")
    ap.add_argument("--run", help="单次请求 JSON；传 - 从 stdin 读")
    ap.add_argument("--plugin", action="append",
                    help="启用并只加载指定插件（可重复）")
    ap.add_argument("--http", action="store_true",
                    help="起可选 HTTP 网关（需 fastapi/uvicorn）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8760)
    a = ap.parse_args(argv)

    if a.http:
        return _http(a.plugin, a.host, a.port)
    if a.run:
        text = sys.stdin.read() if a.run == "-" else a.run
        out, rc = _single(text, a.plugin)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return rc
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
