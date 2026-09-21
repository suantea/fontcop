"""回归：宽间距 logo 式 CJK 文字（OCR 只部分检出/低置信）应能自动识别。

复现 2026-09 缺陷：'绿美创航' 类宽间距大字图，RapidOCR 只读出中间 2 字
且置信度低，旧代码据此整行丢弃 → unknown；同时 _sub_wide 把每个汉字腰斩
成两半 → 半字搜索出垃圾票。修复后走列投影逐段全索引搜索，正常出判定。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
PILImageDraw = ImageDraw

from src.pipeline import Matcher  # noqa: E402
from src.render import glyph_files  # noqa: E402
import src.auto as A  # noqa: E402
import base64, io  # noqa: E402
from PIL import Image as PILImage  # noqa: E402

FAILURES = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append((name, detail))


def make_wide(font_path: str, text: str = "绿美创航") -> Image.Image:
    """复刻用户截图形态：近白底、1000×1000、大字、字间距宽。"""
    font = ImageFont.truetype(font_path, 150)
    im = Image.new("RGB", (1000, 1000), (250, 250, 250))
    d = ImageDraw.Draw(im)
    widths = [d.textbbox((0, 0), c, font=font)[2] - d.textbbox((0, 0), c, font=font)[0] for c in text]
    gap = 40
    total = sum(widths) + gap * (len(text) - 1)
    x = (1000 - total) // 2
    for c, w in zip(text, widths):
        d.text((x, 415), c, font=font, fill="black")
        x += w + gap
    return im


def b64_png(im: Image.Image) -> str:
    import base64, io
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    if not A.ocr_available():
        print("ℹ️ OCR 不可用，跳过（自动模式依赖 OCR）")
        return 0
    files = glyph_files()
    m = Matcher()

    print("\n=== 宽间距 logo 文字自动识别 ===")
    # 关键断言：得意黑图必须识出得意黑且为有效判定（不再是 unknown/垃圾票）
    r = A.auto_match(m, b64_png(make_wide(files["smiley-sans"])))
    ok("得意黑图非 unknown", r.get("verdict") in ("free", "suspect", "risky"),
       f"verdict={r.get('verdict')}")
    top = r.get("candidates", [{}])[0]
    ok("得意黑图 top=得意黑", top.get("font_id") == "smiley-sans",
       f"top={top.get('name')} conf={top.get('score')}")
    ok("得意黑图高置信", (top.get("score") or 0) >= 0.90, f"conf={top.get('score')}")

    # 其余字体：不应再出现 unknown（低置信 OCR 兜底到列投影逐段搜索）
    for fid in ["alibaba-puhuiti", "misans", "source-han-sans", "zcool-kuaile", "lxgw-wenkai"]:
        if fid not in files:
            continue
        r = A.auto_match(m, b64_png(make_wide(files[fid])))
        ok(f"{fid} 非 unknown", r.get("verdict") in ("free", "suspect", "risky"),
           f"verdict={r.get('verdict')} note={r.get('note','')[:30]}")

    print("\n=== 对齐但标签误读（OCR 读「美城d」，真实为美创城）===")
    # 4 字图像但检测框只框中 3 字：列投影 3 段 == OCR 3 字 → 旧代码字符引导贴错标签
    im3 = PILImage.new("RGB", (900, 300), (250, 250, 250))
    d3 = PILImageDraw.Draw(im3)
    f3 = ImageFont.truetype(files["smiley-sans"], 130)
    ws3 = [d3.textbbox((0, 0), c, font=f3)[2] - d3.textbbox((0, 0), c, font=f3)[0] for c in "美创城"]
    g3 = 30
    x3 = (900 - sum(ws3) - g3 * 2) // 2
    for c, w in zip("美创城", ws3):
        d3.text((x3, 80), c, font=f3, fill="black")
        x3 += w + g3

    class FakeOCR:  # 固定返回误读文本「美城d」，覆盖全图
        def __call__(self, arr):
            h, w = arr.shape[:2]
            box = [[w * 0.15, h * 0.4], [w * 0.85, h * 0.4], [w * 0.85, h * 0.6], [w * 0.15, h * 0.6]]
            return [(box, "美城d", 0.72)], None

    orig_ocr = A.get_ocr
    A.get_ocr = lambda: FakeOCR()
    try:
        r = A.auto_match(m, b64_png(im3))
    finally:
        A.get_ocr = orig_ocr
    ok("误读标签不残留", "d" not in (r.get("chars_used") or []) and "创" in (r.get("chars_used") or []),
       f"chars_used={r.get('chars_used')}")
    top = r.get("candidates", [{}])[0]
    ok("误读标签下字体仍正确", top.get("font_id") == "smiley-sans",
       f"top={top.get('name')} conf={top.get('score')}")

    print("\n" + "=" * 50)
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for name, detail in FAILURES:
            print(f"  ❌ {name}: {detail}")
        return 1
    print("ALL TESTS PASSED ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
