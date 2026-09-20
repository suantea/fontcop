"""识别管线：预处理 → 粗排(IoU top50) → 精排(SDF+NCC top5) → 多字投票 → 三档判定。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.features import (
    hog,
    hog_similarity,
    iou_similarity,
    ncc_aligned,
    ncc_similarity,
    sdf,
    verdict_of,
)
from src.render import FINAL_SIZE, render_char

ROOT = Path(__file__).resolve().parent.parent

_IOU_TOP = 50   # 粗排保留数
_TOP_K = 5      # 精排输出数
_HOG_W = 0.35   # HOG 在精排融合中的权重（其余为 SDF+NCC）
_MIN_VALID = 0.55  # 最低可信分数：低于此值的候选视为"不可信匹配"，不输出
# （实测：同字体同字 ≥0.9；标错字 ~0.45；纯噪声 ~0.2。0.55 可靠分隔真匹配与噪声）

# 同源字体组：字形完全相同（NCC=1.0 实测），归并为一组，命中时合并展示
# 每组的第一个成员为展示代表（优先中文名：思源系列；系统字体组除外）
DUP_GROUPS = [
    ("source-han-serif", "noto-serif-cjk"),
    ("source-han-sans", "noto-sans-cjk"),
    ("system-0", "system-1"),   # 黑體-繁/簡（STHeiti 同 TTC）
    ("system-2", "system-3"),   # 宋體-簡/繁（Songti 同 TTC）
]


def _group_of(font_id: str) -> str:
    """字体所属同源组的代表 font_id（组内第一个成员）；无组返回自身。"""
    for g in DUP_GROUPS:
        if font_id in g:
            return g[0]
    return font_id


def group_representative(font_id: str) -> str:
    """同源组的代表 font_id（用于展示层合并）；无组返回自身。"""
    return _group_of(font_id)


@dataclass
class Candidate:
    font_id: str
    score: float
    votes: int = 0


@dataclass
class MatchResult:
    verdict: str                  # free | suspect | risky
    confidence: float
    candidates: list[Candidate] = field(default_factory=list)
    per_char: list[dict] = field(default_factory=list)


def load_meta() -> dict[str, dict]:
    meta = json.loads((ROOT / "fonts" / "fonts.json").read_text(encoding="utf-8"))
    return {m["id"]: m for m in meta}


class Matcher:
    def __init__(self) -> None:
        from src.indexer import load
        self.index = load()
        self.meta = load_meta()
        self.font_ids: list[str] = self.index["font_ids"]
        self.chars: list[str] = self.index["chars"]
        self.glyphs: np.ndarray = self.index["glyphs"]     # [F, C, 64, 64] uint8
        self.sdfs: np.ndarray = self.index["sdfs"]         # [F, C, 64, 64] f32
        self._char_pos = {c: i for i, c in enumerate(self.chars)}
        self._fonts_bin = np.packbits(  # 预打包粗排用位图加速 IoU
            self.glyphs.reshape(len(self.font_ids), len(self.chars), -1), axis=-1
        )

    # ---------- 单字 ----------
    def match_char(self, char_img: np.ndarray, ch: str) -> list[tuple[str, float]]:
        """char_img: 用户截图裁出的单字灰度图；ch: 用户标注的字符。
        返回 [(font_id, ncc_score)] 按 score 降序。
        """
        b = _binarize_crop(char_img)               # 0/1 uint8, 128×128
        if b is None:
            return []
        qi = sdf(b)                                 # 查询 SDF (64,64) f32
        b64 = _downsample64(b)                      # 粗排与索引位图同尺寸

        j = self._char_pos.get(ch)
        if j is None:                               # 索引缺字：退化用同形字符比对
            return []

        # 粗排：对全部字体该字符的位图算 IoU
        cand = self.glyphs[:, j]                    # [F, 64, 64]
        scores = np.array([
            iou_similarity(b64, g) for g in cand
        ])
        top = np.argsort(scores)[::-1][:_IOU_TOP]

        # 精排：SDF+NCC（平移对齐）与 HOG 笔画方向特征加权融合
        q_hog = hog(b)
        refined = []
        for fi in top:
            s_sdf = ncc_aligned(qi, self.sdfs[fi, j])
            g128 = _upsample128(self.glyphs[fi, j])
            s_hog = hog_similarity(q_hog, hog(g128))
            s = (1.0 - _HOG_W) * s_sdf + _HOG_W * s_hog
            refined.append((self.font_ids[int(fi)], float(s)))
        refined.sort(key=lambda x: -x[1])
        return refined[:_TOP_K]

    # ---------- 多字投票（按同源组归并）----------
    def match(self, marks: list[dict]) -> MatchResult:
        """marks: [{image: 灰度np.ndarray, char: str}, ...]"""
        group_scores: dict[str, list[float]] = {}   # 代表font_id -> 加权得分列表
        per_char = []
        for m in marks:
            tops = self.match_char(m["image"], m["char"])
            # 逐字 top 映射到同源代表（noto-serif-cjk → source-han-serif），
            # 展示层统一显示中文名，避免同源字体以英文名重复出现
            mapped = [{"font_id": _group_of(f),
                       "name": self.meta.get(_group_of(f), {}).get("name", _group_of(f)),
                       "score": round(s, 4)} for f, s in tops]
            per_char.append({"char": m["char"], "top": mapped})
            for rank, (fid, s) in enumerate(tops):
                g = _group_of(fid)
                # 排名加权：Top1 权重 1.0，依次衰减
                w = s * (1.0 - 0.15 * rank)
                group_scores.setdefault(g, []).append(w)

        if not group_scores:
            # 0 票（如框选的字不在索引字符集内）：无可比对证据，
            # 按设计返回中性 unknown，绝不兜底 risky（用户反馈过的坑）
            return MatchResult(verdict="unknown", confidence=0.0, per_char=per_char)

        cands = sorted(
            (Candidate(g, float(np.mean(v)), len(v))
             for g, v in group_scores.items()),
            key=lambda c: -c.score,
        )
        # 最低可信度门槛：完全不像（标错字/噪声/非白名单字形）时不硬排序，
        # 避免误导用户。宁可输出"无匹配"也不给一个荒谬的第一名。
        cands = [c for c in cands if c.score >= _MIN_VALID][:_TOP_K]
        if not cands:
            return MatchResult(verdict="unknown", confidence=0.0,
                               per_char=per_char)
        best = cands[0]
        return MatchResult(verdict_of(best.score), round(best.score, 4), cands, per_char)


def _downsample64(b: np.ndarray) -> np.ndarray:
    from PIL import Image as PILImage
    im = PILImage.fromarray(b * 255).resize((64, 64), PILImage.NEAREST)
    return (np.asarray(im) > 127).astype(np.uint8)


def _upsample128(b64: np.ndarray) -> np.ndarray:
    """索引中 64×64 位图 → 128×128（供 HOG 与查询图同分辨率计算）。"""
    from PIL import Image as PILImage
    im = PILImage.fromarray(b64 * 255).resize((128, 128), PILImage.BILINEAR)
    return (np.asarray(im) > 127).astype(np.uint8)


def _otsu_threshold(gray: np.ndarray) -> int:
    """Otsu 大津法全局阈值。"""
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = np.dot(np.arange(256), hist)
    sum_b = 0.0
    w_b = 0.0
    best_thr, best_var = 0, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_thr = var, t
    return best_thr


def _binarize_crop(gray: np.ndarray) -> np.ndarray | None:
    """用户裁剪的单字灰度图 → 紧裁 → 等比缩放 → 居中 128×128 二值图。"""
    from PIL import Image as PILImage

    a = np.asarray(gray, dtype=np.uint8)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=-1).astype(np.uint8)
    thr = _otsu_threshold(a)
    dark = a <= thr
    # 极性按多数类判定：墨色(笔画)通常占少数
    # （不用边框环形判定：裁剪紧贴笔画时边框会混入笔画像素，造成极性反转）
    ink = ~dark if dark.sum() > dark.size - dark.sum() else dark
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    mask = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8) * 255

    img = PILImage.fromarray(mask)
    gh, gw = mask.shape
    scale = min(FINAL_SIZE / gh, FINAL_SIZE / gw)
    nh, nw = max(1, round(gh * scale)), max(1, round(gw * scale))
    img = img.resize((nw, nh), PILImage.BILINEAR)
    canvas = PILImage.new("L", (FINAL_SIZE, FINAL_SIZE), 0)
    canvas.paste(img, ((FINAL_SIZE - nw) // 2, (FINAL_SIZE - nh) // 2))
    b = (np.asarray(canvas, dtype=np.uint8) > 32).astype(np.uint8)
    return b
