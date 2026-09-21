"""FontCop 服务：托管 web/ 静态页 + 识别 API。

启动：python -m src.server   （默认 http://127.0.0.1:8642）
本机模式自动开浏览器；部署模式（HOST 非回环）关浏览器、可配 token/CORS。
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from src.pipeline import Matcher

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
HISTORY_PATH = DATA_DIR / "history.jsonl"


# ---------- 运行配置（环境变量可覆盖，便于部署/反代） ----------
def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


HOST = _env("FONTOP_HOST", "127.0.0.1")                            # 部署时设 0.0.0.0 或交给反代
PORT = int(_env("FONTOP_PORT", "8642"))
MAX_BODY = int(_env("FONTOP_MAX_BODY", str(16 * 1024 * 1024)))     # 请求体上限，防大图打爆内存
TOKEN = _env("FONTOP_TOKEN", "") or None                           # 设值后所有页面/API 需 Bearer token
CORS_ORIGIN = _env("FONTOP_CORS_ORIGIN", "") or None               # 需跨域访问时设来源域名

_IS_LOCAL = HOST in ("127.0.0.1", "localhost", "::1")

_matcher: Matcher | None = None


def get_matcher() -> Matcher:
    global _matcher
    if _matcher is None:
        _matcher = Matcher()
    return _matcher


def _candidate_sample(font_path: str, ch: str) -> str | None:
    """渲染候选字体同字样张 → PNG base64。
    白底黑字主题：白背景 + 黑色字形，且字形略缩小（四周留白）提升阅读性。"""
    from src.render import render_char
    g = render_char(font_path, ch)
    if g is None:
        return None
    glyph = (g * 255).astype(np.uint8)          # 黑字（0）
    glyph_img = Image.fromarray(glyph)
    # 字形缩小 ~72% 并居中，四周留白 → “字体缩小一圈”
    gw, gh = glyph_img.size
    nw, nh = max(1, round(gw * 0.72)), max(1, round(gh * 0.72))
    glyph_img = glyph_img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("L", (gw, gh), 255)      # 白底
    canvas.paste(glyph_img, ((gw - nw) // 2, (gh - nh) // 2))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def handle_match(payload: dict) -> dict:
    from src.render import glyph_files
    files = glyph_files()
    marks = []
    for m in payload.get("marks", []):
        img_bytes = base64.b64decode(m["image_b64"])
        im = Image.open(io.BytesIO(img_bytes)).convert("L")
        marks.append({"image": np.asarray(im, dtype=np.uint8), "char": m["char"]})
    if not marks:
        return {"error": "no marks"}

    t0 = time.time()
    result = get_matcher().match(marks)
    elapsed = time.time() - t0

    ch_first = marks[0]["char"]
    candidates = []
    for c in result.candidates:
        meta = get_matcher().meta.get(c.font_id, {})
        candidates.append({
            "font_id": c.font_id,
            "name": meta.get("name", c.font_id),
            "license": meta.get("license", ""),
            "source_url": meta.get("source_url", ""),
            "score": round(c.score, 4),
            "votes": c.votes,
            "sample_png_b64": _candidate_sample(files.get(c.font_id, ""), ch_first),
        })
    resp = {
        "verdict": result.verdict,
        "confidence": result.confidence,
        "elapsed": round(elapsed, 3),
        "candidates": candidates,
        "per_char": result.per_char,
    }
    _append_history(resp, [m["char"] for m in marks])
    return resp


def _append_history(resp: dict, chars: list[str]) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chars": chars,
            "verdict": resp["verdict"],
            "top": resp["candidates"][0]["name"] if resp["candidates"] else "",
            "score": resp["confidence"],
        }
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静模式
        pass

    def _authorized(self) -> bool:
        """配置了 FONTOP_TOKEN 时校验 Bearer 头（常数时间比较）。"""
        if not TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:], TOKEN)
        return hmac.compare_digest(self.headers.get("X-FontCop-Token", ""), TOKEN)

    def _read_json(self) -> dict:
        """读取并解析 JSON 请求体，限制大小防止大 base64 图打爆内存。"""
        length = self.headers.get("Content-Length")
        if length is None:
            raise ValueError("missing Content-Length")
        n = int(length)
        if n <= 0 or n > MAX_BODY:
            raise ValueError(f"body too large: {n} > {MAX_BODY}")
        body = self.rfile.read(n)
        return json.loads(body)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 防止旧版前端资源被缓存
        if CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_OPTIONS(self):  # noqa: N802  # CORS 预检
        self.send_response(204)
        if CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json(200, {"status": "ok", "version": VERSION})
        elif path == "/api/fonts":
            meta = json.loads((ROOT / "fonts" / "fonts.json").read_text(encoding="utf-8"))
            # 同源字体组（Noto/思源等字形相同）合并展示：同一组只显示一个代表条目，
            # 比对引擎仍保留各 font_id 参与匹配，仅白名单列表去重
            from src.pipeline import group_representative
            seen: set[str] = set()
            merged = []
            for m in meta:
                rep = group_representative(m["id"])
                if rep in seen:
                    continue
                seen.add(rep)
                merged.append(m)
            self._json(200, {"fonts": [
                {"id": m["id"], "name": m["name"], "license": m["license"],
                 "style": m["style"]} for m in merged]})
        elif path == "/" or path == "/index.html":
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send(200, (WEB_DIR / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        elif path == "/style.css":
            self._send(200, (WEB_DIR / "style.css").read_bytes(), "text/css; charset=utf-8")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/match":
            try:
                self._json(200, handle_match(self._read_json()))
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"error": f"bad request: {e}"})
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
        elif path == "/api/auto":
            try:
                if os.environ.get("FONTOP_NO_OCR"):
                    self._json(501, {"error": "OCR 已禁用（FONTOP_NO_OCR=1），请使用手动框选"})
                    return
                from src.auto import auto_match, ocr_available
                if not ocr_available():
                    self._json(501, {"error": "RapidOCR 未安装"})
                    return
                payload = self._read_json()
                t0 = time.time()
                resp = auto_match(get_matcher(), payload["image_b64"])
                resp["elapsed"] = round(time.time() - t0, 3)
                self._json(200, resp)
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"error": f"bad request: {e}"})
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})


def start_server(open_browser: bool = True) -> ThreadingHTTPServer | None:
    """启动 HTTP 服务（本机模式带单实例保护）。返回 httpd（未 serve_forever，由调用方阻塞）。

    - 本机模式（HOST 绑定回环）：
      * 端口已被本应用占用（旧实例/上次双击残留）→ 打开浏览器界面后返回 None
      * 正常启动 → 预热索引 → 后台预热 OCR → 可选自动打开浏览器
    - 部署模式（HOST 非回环）: 跳过单实例/自动开浏览器，方便反代与进程管理托管。
    """
    # 单实例保护（仅本机模式）：端口已被占用时不再重复起服务，
    # 只确保浏览器打开界面后退出自身，避免 GUI 双击堆积进程。
    if _IS_LOCAL:
        import socket
        port_busy = False
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                port_busy = True
        except OSError:
            pass

        if port_busy:
            print(f"检测到已有 FontCop 实例在 {HOST}:{PORT}，仅打开界面并退出", flush=True)
            import webbrowser
            webbrowser.open(f"http://{HOST}:{PORT}")
            return None

    print(f"FontCop 服务启动: http://{HOST}:{PORT}", flush=True)
    get_matcher()  # 预热索引
    print("索引已加载，等待识别请求…", flush=True)
    # 先起 HTTP 服务再后台预热 OCR：
    # OCR 模型解压+初始化可达数十秒，若阻塞在此，端口迟迟不监听，用户会以为服务挂了
    import threading

    def _warm_ocr() -> None:
        if os.environ.get("FONTOP_NO_OCR"):
            return
        try:
            from src.auto import ocr_available, get_ocr
            if ocr_available():
                t0 = time.time()
                get_ocr()
                print(f"OCR 预热完成 ({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"OCR 预热失败（自动识别将不可用）: {e}", flush=True)

    threading.Thread(target=_warm_ocr, daemon=True).start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)

    if open_browser and _IS_LOCAL:
        # 桌面/本机模式无可见窗口：服务就绪后自动打开默认浏览器（独立线程）
        import webbrowser

        def _open_browser() -> None:
            try:
                webbrowser.open(f"http://{HOST}:{PORT}")
            except Exception as e:  # noqa: BLE001
                print(f"打开浏览器失败: {e}", flush=True)
        threading.Thread(target=_open_browser, daemon=True).start()
    return httpd


def main() -> None:
    httpd = start_server(open_browser=True)
    if httpd is not None:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
