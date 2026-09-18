"""全自动模式：RapidOCR 检测文字行 → 用户免框选，服务端自动选字比对。

策略（参照 mixfont/lens"取最大文字块"）：对每个检测到的中文字符行，
横向投影切分单字，取面积最大的若干字作为比对对象。
仅在安装了 rapidocr_onnxruntime 时可用；未安装则前端退回手动模式。
"""
import io
from pathlib import Path

import base64
import numpy as np
from PIL import Image

from src.pipeline import Matcher

_ocr = None


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def auto_match(matcher: Matcher, image_b64: str, max_lines: int = 3, max_chars_per_line: int = 5) -> dict:
    """整图自动识别：OCR 检测行 → 切字 → 逐字比对 → 投票。

    OCR 对小图/单字/贴边文字检测不稳：依次尝试 [原图放大2x, 原图]，
    取首个有结果的尺度；都失败才报"未检测到文字"。
    """
    img_bytes = base64.b64decode(image_b64)
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    ocr = get_ocr()

    result = None
    arr = None
    # 尺度从大到小试：小图放大提升检测率，大图原样即可
    for scale in (2.0, 1.0) if max(im.size) < 400 else (1.0, 2.0):
        w, h = int(im.width * scale), int(im.height * scale)
        if w < 8 or h < 8:
            continue
        base = im.resize((w, h), Image.BILINEAR)
        # RapidOCR 对贴边文字检测失败：四周加 20% 白边
        pad = max(16, int(max(base.size) * 0.2))
        padded = Image.new("RGB", (base.width + pad * 2, base.height + pad * 2), (255, 255, 255))
        padded.paste(base, (pad, pad))
        arr = np.asarray(padded)
        result, _ = ocr(arr)
        if result:
            break

    if not result:
        # OCR 兜底：小图/单字检测不出时，假设整图就是一个字，
        # 对全部字体×全部字做向量化 IoU 搜索（~30ms），取最高分候选。
        return _fallback_single_glyph(matcher, im)

    # 按检测框面积降序，取前 max_lines 行
    boxes = sorted(result, key=lambda r: (r[0][2][0] - r[0][0][0]) * (r[0][2][1] - r[0][0][1]), reverse=True)[:max_lines]

    marks = []
    for box, text, score in boxes:
        if float(score) < 0.6:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        crop = arr[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        chars = _split_chars(crop, text[:max_chars_per_line])
        marks.extend(chars)

    if not marks:
        return {"error": "未能切出可用单字"}

    result_match = matcher.match(marks)
    from src.server import _candidate_sample  # 复用样张渲染
    from src.render import glyph_files
    files = glyph_files()
    ch_first = marks[0]["char"]
    candidates = []
    for c in result_match.candidates:
        meta = matcher.meta.get(c.font_id, {})
        candidates.append({
            "font_id": c.font_id,
            "name": meta.get("name", c.font_id),
            "license": meta.get("license", ""),
            "source_url": meta.get("source_url", ""),
            "score": round(c.score, 4),
            "votes": c.votes,
            "sample_png_b64": _candidate_sample(files.get(c.font_id, ""), ch_first),
        })
    return {
        "verdict": result_match.verdict,
        "confidence": result_match.confidence,
        "candidates": candidates,
        "per_char": result_match.per_char,
        "auto": True,
        "chars_used": [m["char"] for m in marks],
    }


def _fallback_single_glyph(matcher: Matcher, im: Image.Image) -> dict:
    """OCR 检测失败时的兜底：把整图当作单个字，与索引内全部字体×全部字符
    做向量化 IoU 全搜索，取最高分字符再走精排。约 30ms。"""
    from src.pipeline import _binarize_crop, _downsample64, _upsample128, _group_of
    from src.features import (
        iou_similarity, ncc_aligned, hog, hog_similarity, sdf,
        THRESHOLD_SUSPECT,
    )

    gray = np.asarray(im.convert("L"), dtype=np.uint8)
    b = _binarize_crop(gray)
    if b is None:
        return {"error": "图中未检测到文字（尝试了 OCR 与整体字形比对）"}

    b64 = _downsample64(b)
    glyphs = matcher.glyphs                      # [F, C, 64, 64]
    inter = np.logical_and(b64[None, None], glyphs).sum(axis=(-2, -1))
    union = np.logical_or(b64[None, None], glyphs).sum(axis=(-2, -1))
    iou = np.where(union > 0, inter / np.maximum(union, 1), 0.0)

    qi = sdf(b)
    qh = hog(b)
    # 取 IoU top-10 (font, char) 做精排
    flat = iou.ravel()
    tops = np.argsort(flat)[::-1][:10]
    refined = []
    for k in tops:
        fi, ci = int(k) // len(matcher.chars), int(k) % len(matcher.chars)
        s_sdf = ncc_aligned(qi, matcher.sdfs[fi, ci])
        s_hog = hog_similarity(qh, hog(_upsample128(glyphs[fi, ci])))
        s = (1.0 - _HOG_W_AUTO) * s_sdf + _HOG_W_AUTO * s_hog
        refined.append((matcher.font_ids[fi], matcher.chars[ci], float(s)))
    refined.sort(key=lambda x: -x[2])

    best_font, best_char, best_s = refined[0]
    if best_s < _MIN_AUTO:
        return {
            "verdict": "risky", "confidence": 0.0,
            "candidates": [], "per_char": [], "auto": True,
            "fallback": True, "note": "整体字形与白名单差异过大",
        }

    candidates = []
    for fid, ch, s in refined[:5]:
        meta = matcher.meta.get(fid, {})
        candidates.append({
            "font_id": fid, "name": meta.get("name", fid),
            "license": meta.get("license", ""),
            "source_url": meta.get("source_url", ""),
            "score": round(s, 4), "votes": 1,
            "char_matched": ch,
            "sample_png_b64": _candidate_sample(
                _glyph_path(matcher, fid), ch),
        })
    best_s = candidates[0]["score"]
    verdict = ("free" if best_s >= THRESHOLD_SUSPECT and best_s >= 0.9
               else "suspect" if best_s >= THRESHOLD_SUSPECT else "risky")
    return {
        "verdict": verdict, "confidence": best_s,
        "candidates": candidates, "per_char": [], "auto": True,
        "fallback": True,
        "chars_used": [candidates[0]["char_matched"]],
    }


def _HOG_W_AUTO():
    from src.pipeline import _HOG_W
    return _HOG_W


_HOG_W_AUTO = _HOG_W_AUTO()


def _glyph_path(matcher: Matcher, font_id: str) -> str:
    from src.render import glyph_files
    return glyph_files().get(font_id, "")


def _candidate_sample(font_path: str, ch: str) -> str | None:
    from src.render import render_char
    from src.server import _candidate_sample as _impl
    return _impl(font_path, ch)


_MIN_AUTO = 0.60  # 兜底路径最低可信分（无多字投票，取略高于 0.55）


def _split_chars(line_img: np.ndarray, text: str) -> list[dict]:
    """行图横向投影切字，返回 [{image: 灰度图, char: ch}]。
    字符数与 OCR 文本对齐；比例失衡时放弃该行（避免错位比对）。
    容错：seg 数与 text 不等时尝试合并最窄相邻段，仍不等则放弃。
    """
    gray = line_img.mean(axis=-1).astype(np.uint8) if line_img.ndim == 3 else line_img
    from src.pipeline import _otsu_threshold
    thr = _otsu_threshold(gray)
    dark = gray <= thr
    border = np.ones(gray.shape, dtype=bool)
    border[2:-2, 2:-2] = False
    ink = ~dark if dark[border].sum() >= (~dark)[border].sum() else dark

    col_ink = ink.sum(axis=0)
    has_ink = col_ink > 0
    # 连续非零段 = 单字
    segs, start = [], None
    for i, v in enumerate(has_ink):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > 4:
                segs.append((start, i))
            start = None
    if start is not None:
        segs.append((start, len(has_ink)))

    if not segs:
        return []
    widths = [b - a for a, b in segs]
    med_w = sorted(widths)[len(widths) // 2]
    segs = [(a, b) for (a, b), w in zip(segs, widths) if w > med_w * 0.35]

    # 容错：段数多于字符时，合并最窄的相邻段
    while len(segs) > len(text) and len(segs) >= 2:
        min_w = float('inf')
        min_i = -1
        for i in range(len(segs) - 1):
            w = segs[i + 1][1] - segs[i][0]
            if w < min_w:
                min_w, min_i = w, i
        segs[min_i] = (segs[min_i][0], segs[min_i + 1][1])
        segs.pop(min_i + 1)

    if len(segs) != len(text):
        return []  # 仍无法对齐，放弃该行

    marks = []
    for (a, b), ch in zip(segs, text):
        if not ch.strip():
            continue
        rows = np.where(ink[:, a:b].any(axis=1))[0]
        if len(rows) == 0:
            continue
        sub = gray[rows.min():rows.max() + 1, a:b]
        marks.append({"image": sub, "char": ch})
    return marks
