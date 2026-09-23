"""全自动模式：RapidOCR 检测文字行 → 用户免框选，服务端自动选字比对。

策略（参照 mixfont/lens"取最大文字块"）：对每个检测到的中文字符行，
横向投影切分单字，取面积最大的若干字作为比对对象。
仅在安装了 rapidocr_onnxruntime 时可用；未安装则前端退回手动模式。
"""
from __future__ import annotations

import io
import multiprocessing as mp
import os
import threading
from pathlib import Path

import base64
import numpy as np
from PIL import Image

from src.pipeline import Matcher, _group_of
from src.features import verdict_of

# OCR 在异常输入下可能 SIGSEGV / 永久挂起。为不让一次 OCR 崩溃打死整个 HTTP 服务，
# 把 RapidOCR 放进独立子进程：崩溃/挂起只影响该子进程，父进程（服务）超时后重启它并回退。
_OCR_WORKER: "_OcrWorker | None" = None
_OCR_WORKER_LOCK = threading.Lock()


def ocr_available() -> bool:
    # 先装 shim：剥掉 opencv 后，父进程直接 import rapidocr 会因缺 cv2 失败，
    # 而真正干活的 OCR 子进程是装了 shim 的 —— 不先补上会误报「RapidOCR 未安装」（501）
    _install_cv2_shim_if_needed()
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _install_cv2_shim_if_needed() -> None:
    """未装 opencv 时，把 src/cv2_shim.py 注册成 `cv2` 模块供 RapidOCR 使用。

    opencv-python 占 120MB 且是分发包最大头，而 RapidOCR 只用到 24 个函数。
    RapidOCR 全部是 `import cv2`（无 from-import），所以在它导入前塞进
    sys.modules 即可完全不改上游源码地替换 —— 这也是唯一能剥离 opencv 的前提。
    """
    import sys
    if "cv2" in sys.modules:
        return
    try:
        import cv2  # noqa: F401  真装了 opencv 就用真的，shim 只作兜底
        return
    except ImportError:
        pass
    from src import cv2_shim
    sys.modules["cv2"] = cv2_shim


def _ocr_child(child_conn) -> None:
    """OCR 隔离子进程：独占 RapidOCR session，崩溃/挂起不影响 HTTP 服务。"""
    import signal as _s
    _s.signal(_s.SIGINT, _s.SIG_IGN)  # 仅父进程控制生命周期
    _install_cv2_shim_if_needed()
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except Exception as e:  # 初始化失败：每个请求回错误，由调用方走回退路径
        while True:
            try:
                child_conn.recv()
            except EOFError:
                return
            child_conn.send((False, f"OCR 初始化失败: {e}"))
        return
    while True:
        try:
            arr = child_conn.recv()
        except EOFError:
            return
        try:
            res, _ = ocr(arr)
            child_conn.send((True, res))
        except Exception as e:  # ponytail: 捕获一切，避免子进程因 OCR 异常退出
            child_conn.send((False, f"OCR 运行失败: {e}"))


class _OcrWorker:
    """单例 OCR 子进程管理器：带超时与崩溃重启隔离。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        parent_conn, child_conn = mp.Pipe()
        self._parent = parent_conn
        self._proc = mp.Process(target=_ocr_child, args=(child_conn,), daemon=True)
        self._proc.start()
        child_conn.close()
        # 预热：触发子进程内 OCR 模型初始化（耗时数十秒），失败不致命
        try:
            self.call(np.zeros((32, 32, 3), dtype=np.uint8), timeout=180)
        except Exception:
            pass

    def call(self, arr, timeout: float):
        with self._lock:
            try:
                self._parent.send(arr)
            except (BrokenPipeError, EOFError):
                self._restart()
                self._parent.send(arr)
            if not self._parent.poll(timeout):
                self._restart()
                raise TimeoutError("OCR 子进程超时")
            try:
                ok, payload = self._parent.recv()
            except (EOFError, BrokenPipeError):
                self._restart()
                raise RuntimeError("OCR 子进程已退出")
        if not ok:
            raise RuntimeError(str(payload))
        return payload

    def _restart(self) -> None:
        try:
            self._proc.kill()
        except Exception:
            pass
        try:
            self._parent.close()
        except Exception:
            pass
        self._start()


class _OcrHandle:
    """get_ocr() 返回的可调用句柄，保持 ocr(arr) -> (result, None) 契约（兼容测试 mock）。"""

    def __init__(self, worker: "_OcrWorker") -> None:
        self._worker = worker

    def __call__(self, arr, timeout: float = 55.0):
        return (self._worker.call(arr, timeout), None)


def get_ocr() -> _OcrHandle:
    global _OCR_WORKER
    if _OCR_WORKER is None:
        with _OCR_WORKER_LOCK:
            if _OCR_WORKER is None:  # 双重检查：防止并发下重复起子进程
                _OCR_WORKER = _OcrWorker()
    return _OcrHandle(_OCR_WORKER)


def auto_match(matcher: Matcher, image_b64: str, max_lines: int = 3, max_chars_per_line: int = 20) -> dict:
    """整图自动识别：OCR 检测行 → 切字/逐段搜索 → 投票。

    OCR 对小图/单字/贴边文字检测不稳：依次尝试 [原图放大2x, 原图]，
    取首个有结果的尺度；都失败才走逐段兜底。
    每行：列投影段数与 OCR 文本长度对齐时按文本切字（字符引导）；
    段数与字数不一致（OCR 漏读/误读/粘连，如 4 字读成「美城d」）时，
    改逐段全索引搜索投票（不依赖 OCR 文本，避免误读字被贴上正确字形）。
    """
    img_bytes = base64.b64decode(image_b64)
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    # 超大图先缩到合理尺寸：OCR 对超大图检出更差且更耗时；前端已缩，这里兜底第三方/旧客户端
    _auto_max_edge = float(os.environ.get("FONTOP_AUTO_MAX_EDGE", "2200"))
    if max(im.size) > _auto_max_edge:
        s = _auto_max_edge / max(im.size)
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BILINEAR)
    ocr = get_ocr()

    result = None
    arr = None
    # 尺度从大到小试：小图放大提升检测率，大图原样即可；加 1.5x 中间尺度提高中等尺寸文字的检出率
    scales = (2.5, 2.0, 1.5, 1.0) if max(im.size) < 400 else (1.0, 1.5, 2.0, 2.5)
    for scale in scales:
        w, h = int(im.width * scale), int(im.height * scale)
        if w < 8 or h < 8:
            continue
        base = im.resize((w, h), Image.BILINEAR)
        # RapidOCR 对贴边文字检测失败：四周加 20% 白边
        pad = max(16, int(max(base.size) * 0.2))
        padded = Image.new("RGB", (base.width + pad * 2, base.height + pad * 2), (255, 255, 255))
        padded.paste(base, (pad, pad))
        arr = np.asarray(padded)
        try:
            result, _ = ocr(arr)
        except Exception as e:  # OCR 子进程崩溃/超时：隔离后回退逐段搜索，不打死服务
            print(f"[auto] OCR 调用失败（回退逐段搜索）: {e}", flush=True)
            result = None
        if result:
            break

    if not result:
        # OCR 兜底：小图/单字检测不出时，不依赖文字内容，按列投影切字，
        # 逐段对全部字体×全部字做向量化 IoU 搜索（~30ms/段），按字体投票。
        return _fallback_line(matcher, im)

    # RapidOCR 偶发返回 None 坐标/文本/分数（上游版本性抖动），先整体过滤，避免排序/循环 TypeError
    valid = [r for r in (result or [])
             if r and r[0] and r[1] is not None and all(p is not None for p in r[0])
             and len(r) > 2 and r[2] is not None]
    # 按检测框面积降序，取前 max_lines 行
    boxes = sorted(valid, key=lambda r: (r[0][2][0] - r[0][0][0]) * (r[0][2][1] - r[0][0][1]), reverse=True)[:max_lines]

    marks = []
    per_font: dict[str, dict] = {}
    per_seg: list[dict] = []
    for box, text, score in boxes:
        if score is None:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        crop = arr[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        gray = crop.mean(axis=-1).astype(np.uint8) if crop.ndim == 3 else crop
        ink = _ink_mask(gray)
        if ink is None:
            continue
        segs = _column_segs(ink)
        if float(score) < 0.6:
            # OCR 置信度低（部分检出/误读，常见于宽间距 logo 字）：
            # 文本不可靠，弃用字符引导，逐段全索引搜索投票（列投影不依赖 OCR 文本）
            pf, ps = _mask_votes(matcher, ink)
            _merge_votes(per_font, pf)
            per_seg.extend(ps)
            continue
        chars = _usable_chars(text[:max_chars_per_line])
        if not chars:
            continue
        if len(segs) != len(chars):
            # 段数与 OCR 字数对不齐（漏读/误读/粘连/过切，如 4 字读成「美城d」）：
            # 字符引导对齐不可信，逐段全索引搜索投票（不依赖 OCR 文本）
            pf, ps = _mask_votes(matcher, ink)
            _merge_votes(per_font, pf)
            per_seg.extend(ps)
        else:
            line_marks = _split_chars(crop, text[:max_chars_per_line])
            # 字符引导切字后逐字全索引校验：任一标签与真实字形不符（OCR 误读，
            # 如「创城」读成「城d」）→ 整行改走逐段搜索，避免误读标签带偏投票
            if line_marks and _labels_consistent(matcher, line_marks):
                marks.extend(line_marks)
            elif ink is not None:
                pf, ps = _mask_votes(matcher, ink)
                _merge_votes(per_font, pf)
                per_seg.extend(ps)

    if per_font:
        # 可用的字符引导票也并入（补足逐段搜索可能漏掉的段）
        for m in marks:
            tops = matcher.match_char(m["image"], m["char"])
            if tops and tops[0][1] >= _MIN_AUTO:
                fid, s = tops[0]
                g = _group_of(fid)   # 并入时归并到同源代表
                d = per_font.setdefault(g, {"scores": [], "chars": []})
                d["scores"].append(s)
                d["chars"].append(m["char"])
                per_seg.append({"char": m["char"], "top": [
                    {"font_id": _group_of(t[0]),
                     "name": matcher.meta.get(_group_of(t[0]), {}).get("name", _group_of(t[0])),
                     "score": round(t[1], 4)} for t in tops[:3]]})
        return _assemble(matcher, per_font, per_seg)

    if not marks:
        # OCR 框出的文字全部被 _usable_chars 过滤（标点误读/无可用字）：
        # 无可比对的字 → 按设计返回中性 unknown，不判版权
        return {"verdict": "unknown", "confidence": 0.0,
                "candidates": [], "per_char": [], "auto": True,
                "note": "OCR 识别到文字但无可比对的字（标点/噪声被过滤）：无法判断",
                "fallback": True}

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


def _seg_img(mask: np.ndarray, x0: int, x1: int) -> np.ndarray | None:
    """掩膜段 [x0,x1) 紧裁等比缩放 → 128×128 二值图（0/1 uint8）。"""
    from PIL import Image as PILImage
    from src.render import FINAL_SIZE
    sub = mask[:, x0:x1]
    rows = np.where(sub.any(axis=1))[0]
    if not len(rows):
        return None
    sub = sub[rows.min():rows.max() + 1]
    h, w = sub.shape
    scale = min(FINAL_SIZE / h, FINAL_SIZE / w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    img = PILImage.fromarray(sub.astype(np.uint8) * 255).resize((nw, nh), PILImage.BILINEAR)
    c = PILImage.new("L", (FINAL_SIZE, FINAL_SIZE), 0)
    c.paste(img, ((FINAL_SIZE - nw) // 2, (FINAL_SIZE - nh) // 2))
    return (np.asarray(c, dtype=np.uint8) > 32).astype(np.uint8)


def _vsearch(matcher: Matcher, b: np.ndarray) -> list[tuple[str, str, float]]:
    """单字二值图 → 全索引 (font×char) 向量化 IoU 粗筛 top10 → SDF+NCC+HOG 精排。"""
    from src.pipeline import _downsample64, _upsample128
    from src.features import hog, hog_similarity, ncc_aligned, sdf

    b64 = _downsample64(b)
    # 粗排：复用 Matcher 预打包位图（_fonts_bin）的 popcount 加速 IoU
    b64p = np.packbits(b64.ravel())
    inter = np.bitwise_and(b64p[None, None], matcher._fonts_bin).astype(np.uint16).sum(axis=-1)
    union = np.bitwise_or(b64p[None, None], matcher._fonts_bin).astype(np.uint16).sum(axis=-1)
    iou = np.where(union > 0, inter / np.maximum(union, 1), 0.0)

    qi, qh = sdf(b), hog(b)
    refined = []
    for k in np.argsort(iou.ravel())[::-1][:10]:
        fi, ci = int(k) // len(matcher.chars), int(k) % len(matcher.chars)
        s_sdf = ncc_aligned(qi, matcher.sdfs[fi, ci])
        s_hog = hog_similarity(qh, hog(_upsample128(matcher.glyphs[fi, ci])))
        s = (1.0 - _HOG_W_AUTO) * s_sdf + _HOG_W_AUTO * s_hog
        refined.append((matcher.font_ids[fi], matcher.chars[ci], float(s)))
    refined.sort(key=lambda x: -x[2])
    return refined


def _ink_mask(gray: np.ndarray) -> np.ndarray | None:
    """灰度图 → 文字掩膜（bool）。自动判定极性；空图返回 None。"""
    from src.pipeline import _otsu_threshold
    a = np.asarray(gray, dtype=np.uint8)
    thr = _otsu_threshold(a)
    dark = a <= thr
    # 极性按多数类判定（与 _binarize_crop 一致），墨色占少数视为笔画
    ink = dark if dark.sum() <= dark.size - dark.sum() else ~dark
    return ink if ink.any() else None


def _column_segs(ink: np.ndarray, filter_narrow: bool = True) -> list[tuple[int, int]]:
    """按列投影切段（连续 ink 列、最小 5 列）。
    filter_narrow=True（默认）：剔除过窄段（< 中位宽×0.35），用于字符引导切字。
    filter_narrow=False：保留全部段，供 _mask_votes 先合并左右结构字碎片再搜索
    （「创」的「刂」等窄部件若在此被剔除，剩半字会匹配成垃圾字）。"""
    col_ink = ink.sum(axis=0)
    segs, start = [], None
    for i, v in enumerate(col_ink > 0):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > 4:
                segs.append((start, i))
            start = None
    if start is not None:
        segs.append((start, len(col_ink)))
    if not segs or not filter_narrow:
        return segs
    widths = [b - a for a, b in segs]
    med_w = sorted(widths)[len(widths) // 2]
    return [(a, b) for (a, b), w in zip(segs, widths) if w > med_w * 0.35]


def _sub_wide(ink: np.ndarray, x0: int, x1: int) -> list[tuple[int, int]]:
    """单个列段过宽（多字母粘连成整块）时按等宽细分，返回子段坐标列表。
    宽高比超过约 1.35 视为粘连（CJK 单字 ≈0.7-1.0、拉丁单字 ≈0.4-1.2 均不受影响）。"""
    rows = np.where(ink[:, x0:x1].any(axis=1))[0]
    if not len(rows):
        return [(x0, x1)]
    h = rows.max() - rows.min() + 1
    w = x1 - x0
    n = max(1, int(np.ceil(w / max(h * 1.35, 1))))
    if n <= 1:
        return [(x0, x1)]
    return [(x0 + w * i // n, x0 + w * (i + 1) // n) for i in range(n)]


def _merge_narrow(ink: np.ndarray, segs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并过窄列段：宽高比 < 0.5 的段视为左右结构字部件碎片（如「创」的「刂」），
    并入相邻段。完整汉字/字母宽高比 ≥0.5（如「创」0.62），不得误并。"""
    if len(segs) < 2:
        return segs
    merged = list(segs)
    i = 0
    while i < len(merged) and len(merged) > 1:
        a, b = merged[i]
        rows = np.where(ink[:, a:b].any(axis=1))[0]
        if not len(rows):
            i += 1
            continue
        h = rows.max() - rows.min() + 1
        if (b - a) / h >= 0.5:
            i += 1
            continue
        # 碎片：并入间隙更小的一侧
        left = merged[i - 1] if i > 0 else None
        right = merged[i + 1] if i < len(merged) - 1 else None
        gap_l = (a - left[1]) if left else float("inf")
        gap_r = (right[0] - b) if right else float("inf")
        if right is not None and gap_r <= gap_l:
            merged[i] = (a, right[1])
            merged.pop(i + 1)
        elif left is not None:
            merged[i - 1] = (left[0], b)
            merged.pop(i)
        else:
            i += 1
    return merged


def _mask_votes(matcher: Matcher, ink: np.ndarray) -> tuple[dict[str, dict], list[dict]]:
    """掩膜逐段全索引搜索 → (per_font 投票表, per_seg 逐段结果列表)。
    先合并过窄段：左右结构汉字（绿/创/城…）部件间竖隙会被列投影切成碎片，
    碎片（如「刂」立刀旁）全索引匹配成垃圾字（如 'd'），合并后按整字搜索。"""
    segs = _merge_narrow(ink, _column_segs(ink, filter_narrow=False))
    per_font: dict[str, dict] = {}
    per_seg: list[dict] = []
    for x0, x1 in segs:
        for a, b in _sub_wide(ink, x0, x1):
            seg = _seg_img(ink, a, b)
            if seg is None:
                continue
            refined = _vsearch(matcher, seg)
            if not refined or refined[0][2] < _MIN_AUTO:
                continue
            fid, ch, s = refined[0]
            if not _usable_chars(ch):
                continue  # 无字符引导的兜底搜索：标点结果不可信，丢弃
            g = _group_of(fid)   # 同源字体（noto/source-han 等）归并到代表
            d = per_font.setdefault(g, {"scores": [], "chars": []})
            d["scores"].append(s)
            d["chars"].append(ch)
            per_seg.append({
                "char": ch,
                "top": [{"font_id": _group_of(f),
                         "name": matcher.meta.get(_group_of(f), {}).get("name", _group_of(f)),
                         "score": round(sc, 4)} for f, _, sc in refined[:3]],
            })
    return per_font, per_seg


def _merge_votes(target: dict[str, dict], src: dict[str, dict]) -> None:
    for fid, d in src.items():
        t = target.setdefault(fid, {"scores": [], "chars": []})
        t["scores"].extend(d["scores"])
        t["chars"].extend(d["chars"])


def _assemble(matcher: Matcher, per_font: dict[str, dict], per_seg: list[dict] | None = None) -> dict:
    """按字体投票聚合 → 结果字典（逐段搜索/混合路径共用）。"""

    if not per_font:
        return {
            "verdict": "unknown", "confidence": 0.0,
            "candidates": [], "per_char": [], "auto": True,
            "fallback": True, "note": "该截图没有可比的字（0 个可比字）：无法判断，不回退版权结论",
        }

    items = sorted(per_font.items(),
                   key=lambda kv: (-len(kv[1]["scores"]), -float(np.mean(kv[1]["scores"]))))
    best_s = float(np.mean(items[0][1]["scores"]))

    candidates = []
    for fid, d in items[:5]:
        meta = matcher.meta.get(fid, {})
        candidates.append({
            "font_id": fid, "name": meta.get("name", fid),
            "license": meta.get("license", ""),
            "source_url": meta.get("source_url", ""),
            "score": round(float(np.mean(d["scores"])), 4), "votes": len(d["scores"]),
            "char_matched": d["chars"][0],
            "sample_png_b64": _candidate_sample(_glyph_path(matcher, fid), d["chars"][0]),
        })
    verdict = verdict_of(best_s)
    chars_used = []
    for fid, d in items:
        for ch in d["chars"]:
            if ch not in chars_used:
                chars_used.append(ch)
    return {
        "verdict": verdict, "confidence": best_s,
        "candidates": candidates, "per_char": per_seg or [], "auto": True,
        "fallback": True,
        "chars_used": chars_used,
    }


def _fallback_line(matcher: Matcher, im: Image.Image) -> dict:
    """OCR 无结果时的兜底：不依赖文字内容，按列投影切字，逐段全索引搜索后按字体投票。
    整图只剩一段时退化为单字搜索（原行为）。"""
    gray = np.asarray(im.convert("L"), dtype=np.uint8)
    ink = _ink_mask(gray)
    if ink is None:
        return {"error": "图中未检测到文字（尝试了 OCR 与整体字形比对）"}
    per_font, per_seg = _mask_votes(matcher, ink)
    return _assemble(matcher, per_font, per_seg)


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


def _usable_chars(text: str) -> list[str]:
    """只保留可做字形比对的字符：字母/数字/汉字。
    OCR 常把 logo 里的字形误读成标点（如 ' ，：】【），这些参与比对只会产生垃圾票。"""
    return [c for c in text if c.isalnum() or "\u4e00" <= c <= "\u9fff"]


def _labels_consistent(matcher: Matcher, marks: list[dict]) -> bool:
    """逐字全索引校验 OCR 标签：每个切出字形的最像索引字应与标签一致且达标，
    否则认为 OCR 误读（如「创城」读成「城d」），标签不可信。"""
    for mk in marks:
        ink = _ink_mask(mk["image"])
        if ink is None:
            return False
        seg = _seg_img(ink, 0, ink.shape[1])
        top = _vsearch(matcher, seg)
        if not top or top[0][1] != mk["char"] or top[0][2] < _MIN_AUTO:
            return False
    return True


def _split_chars(line_img: np.ndarray, text: str) -> list[dict]:
    """行图横向投影切字，返回 [{image: 灰度图, char: ch}]。
    字符数与 OCR 文本对齐；比例失衡时放弃该行（避免错位比对）。
    容错：seg 数与 text 不等时尝试合并最窄相邻段，仍不等则放弃。
    新增：当段数少于字符数时（粘连导致漏切），等宽按字符数切分以保留全部字符。
    """
    gray = line_img.mean(axis=-1).astype(np.uint8) if line_img.ndim == 3 else line_img
    ink = _ink_mask(gray)
    if ink is None:
        return []
    segs = _column_segs(ink)
    if not segs:
        return []

    # 只保留可做字形比对的字符（字母/数字/汉字），标点噪声不参与
    chars = _usable_chars(text)
    if not chars:
        return []

    # ---------- 案例 A：段数 >= 字符数（可能过切） ----------
    # 容错：段数多于字符时，合并最窄相邻段
    while len(segs) > len(chars) and len(segs) >= 2:
        min_w = float('inf')
        min_i = -1
        for i in range(len(segs) - 1):
            w = segs[i + 1][1] - segs[i][0]
            if w < min_w:
                min_w, min_i = w, i
        segs[min_i] = (segs[min_i][0], segs[min_i + 1][1])
        segs.pop(min_i + 1)

    # ---------- 案例 B：段数 < 字符数（粘连导致漏切） ----------
    if len(segs) < len(chars):
        # 尝试基于 OCR 文本长度进行等宽切分
        rows = np.where(ink.any(axis=1))[0]
        cols = np.where(ink.any(axis=0))[0]
        if len(rows) and len(cols):
            y0, y1 = int(rows.min()), int(rows.max()) + 1
            x0, x1 = int(cols.min()), int(cols.max()) + 1
            marks = []
            for i, ch in enumerate(chars):
                a = x0 + (x1 - x0) * i // len(chars)
                b = x0 + (x1 - x0) * (i + 1) // len(chars)
                sub = gray[y0:y1, max(a, x0):min(b, x1)]
                if sub.size:
                    marks.append({"image": sub, "char": ch})
            if len(marks) == len(chars):
                return marks
        # 等宽切分仍不可用 → 放弃该行
        return []

    # ---------- 案例 C：段数 == 字符数 ----------
    marks = []
    for (a, b), ch in zip(segs, chars):
        rows = np.where(ink[:, a:b].any(axis=1))[0]
        if len(rows) == 0:
            continue
        sub = gray[rows.min():rows.max() + 1, a:b]
        marks.append({"image": sub, "char": ch})
    return marks
