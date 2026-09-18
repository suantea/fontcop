#!/usr/bin/env python3
"""FontCop 端到端测试：覆盖所有 UI 交互路径。
测试内容：
  1. 页面加载 / GET /api/fonts / /api/history
  2. 手动识别：POST /api/match（干净图 + 噪声图）
  3. 自动识别：POST /api/auto
  4. 服务器稳定性：连续请求、错误处理
"""
import base64
import io
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.render import glyph_files
from tools.gen_testset import MODES, gen_case

BASE = "http://127.0.0.1:8642"
FAILURES = []


def ok(name: str, condition: bool, detail: str = "") -> None:
    status = "✅" if condition else "❌"
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append((name, detail))


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return json.load(resp)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode()[:200]}
    except Exception as e:
        return {"_error": str(e)}


def get(path: str) -> dict:
    try:
        return json.load(urllib.request.urlopen(BASE + path, timeout=10))
    except Exception as e:
        return {"_error": str(e)}


def test_page_load():
    print("\n=== 1. 页面加载 ===")
    # GET /
    try:
        r = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
        ok("首页 200", len(r) > 500, f"length={len(r)}")
    except Exception as e:
        ok("首页 200", False, str(e))
    # GET /app.js
    try:
        r = urllib.request.urlopen(BASE + "/app.js", timeout=10).read().decode()
        ok("app.js 200", "fetch" in r, f"length={len(r)}")
    except Exception as e:
        ok("app.js 200", False, str(e))
    # GET /style.css
    try:
        r = urllib.request.urlopen(BASE + "/style.css", timeout=10).read().decode()
        ok("style.css 200", len(r) > 50, f"length={len(r)}")
    except Exception as e:
        ok("style.css 200", False, str(e))


def test_api_fonts():
    print("\n=== 2. GET /api/fonts ===")
    r = get("/api/fonts")
    ok("fonts 返回", "_error" not in r, f"error={r.get('_error')}")
    if "_error" not in r:
        fonts = r.get("fonts", [])
        ok("fonts 数量 ≥15", len(fonts) >= 15, f"有 {len(fonts)} 款")
        ok("有 source-han-sans", any(f["id"] == "source-han-sans" for f in fonts))
        ok("有 system-* 字体", any(f["id"].startswith("system-") for f in fonts))


def test_api_history():
    print("\n=== 3. GET /api/history ===")
    r = get("/api/history")
    ok("history 返回", "_error" not in r)
    if "_error" not in r:
        ok("history 是列表", isinstance(r.get("history"), list))


def test_manual_match():
    print("\n=== 4. 手动识别 POST /api/match ===")
    files = glyph_files()
    rng = random.Random(99)
    cases = [
        ("source-han-sans", "的", "free"),
        ("lxgw-wenkai", "说", "free"),
        ("zcool-kuaile", "的", "free"),
    ]
    for fid, ch, expect in cases:
        img = gen_case(files[fid], ch, "clean", rng)
        buf = io.BytesIO(); Image.fromarray(img).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        r = post("/api/match", {"marks": [{"image_b64": b64, "char": ch}]})
        top = r.get("candidates", [{}])[0]
        ok(f"manual {fid}+{ch}",
           top.get("font_id") == fid,
           f"expected={fid} got={top.get('font_id')} conf={top.get('score')}")
        ok(f"verdict={expect}",
           r.get("verdict") == expect,
           f"got={r.get('verdict')}")


def test_auto_match():
    print("\n=== 5. 自动识别 POST /api/auto ===")
    files = glyph_files()
    font = ImageFont.truetype(files["source-han-sans"], 64)
    img = Image.new("L", (260, 90), 255)
    ImageDraw.Draw(img).text((10, 10), "的清深", fill=0, font=font)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    r = post("/api/auto", {"image_b64": b64})
    ok("auto 不报错", "_error" not in r, r.get("_error"))
    # auto 可能返回 error（切字失败）或正常结果，两种都算合理；关键是结构正确
    if "_error" not in r:
        ok("auto 返回 verdict", r.get("verdict") in ("free", "suspect", "risky"),
           f"verdict={r.get('verdict')}")
        if r.get("candidates"):
            ok("auto 有候选", bool(r["candidates"][0].get("font_id")),
               f"top={r['candidates'][0]['name']} conf={r['candidates'][0]['score']}")


def test_error_handling():
    print("\n=== 6. 错误处理 ===")
    r = post("/api/match", {})
    ok("空 marks 处理", "error" in r or "verdict" in r)
    r = post("/api/auto", {"image_b64": "not_base64!!!"})
    ok("坏 base64 处理", "_error" in r or "error" in r)
    r = get("/nonexistent")
    ok("404 页面", r.get("_error") is not None or isinstance(r, dict) and "error" in r)


def test_stress():
    print("\n=== 7. 稳定性（10 连请求）===")
    files = glyph_files()
    t0 = time.time()
    for i in range(10):
        img = gen_case(files["source-han-sans"], "的", MODES[i % len(MODES)], random.Random(i))
        buf = io.BytesIO(); Image.fromarray(img).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        r = post("/api/match", {"marks": [{"image_b64": b64, "char": "的"}]})
        ok(f"stress-{i}", r.get("verdict") == "free" and r.get("candidates"),
           f"err={r.get('_error')} verdict={r.get('verdict')}")
    dt = time.time() - t0
    ok("总耗时 <10s", dt < 10, f"{dt:.1f}s")


def main() -> int:
    # 预热
    get("/api/fonts")
    get("/api/fonts")
    get("/api/fonts")

    test_page_load()
    test_api_fonts()
    test_api_history()
    test_manual_match()
    test_auto_match()
    test_error_handling()
    test_stress()

    print(f"\n{'='*50}")
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for name, detail in FAILURES:
            print(f"  ❌ {name}: {detail}")
        return 1
    else:
        print("ALL TESTS PASSED ✅")
        return 0


if __name__ == "__main__":
    sys.exit(main())
