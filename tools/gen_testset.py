"""程序化生成测试图：白名单字体渲染单字 → 加噪声/背景/缩放/JPEG压缩，模拟截图。"""
from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from src.render import render_char


def gen_case(font_path: str, ch: str, mode: str = "clean", rng: random.Random | None = None) -> np.ndarray:
    """返回灰度 uint8 图（模拟用户裁出的单字截图）。"""
    rng = rng or random.Random()
    g = render_char(font_path, ch)
    assert g is not None, f"render failed: {ch}"
    h, w = g.shape

    if mode == "clean":
        return (g * 255).astype(np.uint8)

    ink = (g * 255).astype(np.uint8)

    if mode == "noise":
        out = ink.astype(np.float32) + rng.gauss(0, 30) + np.random.normal(0, 18, ink.shape)
        return np.clip(out, 0, 255).astype(np.uint8)

    if mode == "background":
        # 纯色/渐变背景 + 深色前景（模拟截图常见深字浅底/浅字深底）
        if rng.random() < 0.5:
            bg = rng.randint(120, 220)
            ink_val = rng.randint(0, 40)        # 深字浅底
        else:
            bg = rng.randint(0, 70)
            ink_val = rng.randint(190, 240)     # 浅字深底（反相）
        out = np.full((h, w), bg, dtype=np.float32)
        out += np.linspace(-25, 25, w)[None, :] * (w > 1)
        out = np.clip(out, 0, 255)
        fg = np.clip(ink_val + np.random.normal(0, 6, ink.shape), 0, 255)
        out = np.where(g > 0, fg, out)
        return out.astype(np.uint8)

    if mode == "scale":
        s = rng.uniform(0.5, 2.0)
        im = Image.fromarray(ink).resize((max(8, int(w * s)), max(8, int(h * s))), Image.BILINEAR)
        return np.asarray(im, dtype=np.uint8)

    if mode == "jpeg":
        buf = io.BytesIO()
        Image.fromarray(ink).save(buf, format="JPEG", quality=rng.randint(30, 70))
        buf.seek(0)
        return np.asarray(Image.open(buf).convert("L"), dtype=np.uint8)

    if mode == "blur":
        im = Image.fromarray(ink).filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.5)))
        return np.asarray(im, dtype=np.uint8)

    raise ValueError(mode)


MODES = ["clean", "noise", "background", "scale", "jpeg", "blur"]
