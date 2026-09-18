"""FontCop 本地服务：托管 web/ 静态页 + 识别 API。

启动：python -m src.server   （默认 http://127.0.0.1:8642）
"""
import base64
import io
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

import sys

from src.pipeline import Matcher


def _resolve_dirs() -> tuple[Path, Path]:
    """返回 (资源根目录, 数据目录)。
    - 开发模式：都在项目根
    - 打包模式：资源在 _MEIPASS（只读临时目录），
      数据放可执行文件旁的 FontCop_data/（持久，跨重启保留历史）
    """
    if getattr(sys, "frozen", False):
        res = Path(getattr(sys, "_MEIPASS"))
        exe_dir = Path(sys.executable).resolve().parent
        data = exe_dir / "FontCop_data"
    else:
        res = Path(__file__).resolve().parent.parent
        data = res / "data"
    return res, data


ROOT, DATA_DIR = _resolve_dirs()
WEB_DIR = ROOT / "web"
HISTORY_PATH = DATA_DIR / "history.jsonl"

HOST, PORT = "127.0.0.1", 8642

_matcher: Matcher | None = None


def get_matcher() -> Matcher:
    global _matcher
    if _matcher is None:
        _matcher = Matcher()
    return _matcher


def _candidate_sample(font_path: str, ch: str) -> str | None:
    """渲染候选字体同字样张 → PNG base64。"""
    from src.render import render_char
    g = render_char(font_path, ch)
    if g is None:
        return None
    buf = io.BytesIO()
    Image.fromarray(g * 255).save(buf, format="PNG")
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

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 防止旧版前端资源被缓存
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/fonts":
            meta = json.loads((ROOT / "fonts" / "fonts.json").read_text(encoding="utf-8"))
            self._json(200, {"fonts": [
                {"id": m["id"], "name": m["name"], "license": m["license"],
                 "style": m["style"]} for m in meta]})
        elif path == "/api/history":
            entries = []
            if HISTORY_PATH.exists():
                lines = HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
                entries = [json.loads(l) for l in lines[-50:]][::-1]
            self._json(200, {"history": entries})
        elif path == "/" or path == "/index.html":
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send(200, (WEB_DIR / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        elif path == "/style.css":
            self._send(200, (WEB_DIR / "style.css").read_bytes(), "text/css; charset=utf-8")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/match":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                self._json(200, handle_match(payload))
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
        elif path == "/api/auto":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                from src.auto import auto_match, ocr_available
                if not ocr_available():
                    self._json(501, {"error": "RapidOCR 未安装"})
                    return
                self._json(200, auto_match(get_matcher(), payload["image_b64"]))
            except Exception as e:  # noqa: BLE001
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})


def main() -> None:
    print(f"FontCop 服务启动: http://{HOST}:{PORT}", flush=True)
    get_matcher()  # 预热索引
    print("索引已加载，等待识别请求…", flush=True)
    # 先起 HTTP 服务再后台预热 OCR：
    # 打包版 OCR 模型解压+初始化可达数十秒，若阻塞在此，端口迟迟不监听，用户会以为服务挂了
    import threading

    def _warm_ocr() -> None:
        try:
            from src.auto import ocr_available, get_ocr
            if ocr_available():
                t0 = time.time()
                get_ocr()
                print(f"OCR 预热完成 ({time.time()-t0:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"OCR 预热失败（自动识别将不可用）: {e}", flush=True)

    threading.Thread(target=_warm_ocr, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
