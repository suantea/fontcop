"""字体渲染封装：任意字体渲染单字 → 归一化 128×128 二值图。"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.features import SIZE

RENDER_SIZE = 160          # 先大图渲染再紧裁，避免小字抗锯齿损失
FINAL_SIZE = SIZE          # 128


@lru_cache(maxsize=128)
def load_font(path: str, size: int = RENDER_SIZE) -> ImageFont.FreeTypeFont:
    """支持 system:path#member 格式（TTC 多成员）。"""
    if path.startswith("system:"):
        full_path, member_str = path[7:].split("#", 1)
        member = int(member_str)
        return ImageFont.truetype(full_path.strip(), size, index=member)
    return ImageFont.truetype(path, size)


def render_char(font_path: str, ch: str) -> np.ndarray | None:
    """渲染字符为 FINAL_SIZE×FINAL_SIZE 二值图（0/1 uint8）。
    流程：大图渲染 → 紧裁外接框 → 等比缩放（保持宽高比）→ 居中。
    字体缺该字形或文件不可用（如 Windows 无 macOS 系统字体）返回 None。
    """
    try:
        font = load_font(font_path)
    except (OSError, ValueError):
        return None  # 字体文件缺失/不可读：跨平台降级（Windows 无 system: 字体）
    try:
        bbox = font.getbbox(ch)
    except OSError:
        return None
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None

    pad = 8
    img = Image.new("L", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), 0)
    draw = ImageDraw.Draw(img)
    draw.text((pad - x0, pad - y0), ch, fill=255, font=font)

    arr = np.asarray(img, dtype=np.uint8)
    mask = arr > 32
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    glyph = arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    # 等比缩放到 FINAL_SIZE 内，居中放置
    gh, gw = glyph.shape
    scale = min(FINAL_SIZE / gh, FINAL_SIZE / gw)
    nh, nw = max(1, round(gh * scale)), max(1, round(gw * scale))
    glyph_img = Image.fromarray(glyph).resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("L", (FINAL_SIZE, FINAL_SIZE), 0)
    canvas.paste(glyph_img, ((FINAL_SIZE - nw) // 2, (FINAL_SIZE - nh) // 2))
    return (np.asarray(canvas, dtype=np.uint8) > 32).astype(np.uint8)


def glyph_files() -> dict[str, str]:
    """fonts.json → {font_id: 文件路径字符串}。
    支持普通路径与 system:path#member 两种格式。
    """
    import json
    meta = json.loads((Path(__file__).resolve().parent.parent / "fonts" / "fonts.json").read_text(encoding="utf-8"))
    base = Path(__file__).resolve().parent.parent / "fonts" / "files"
    result = {}
    for m in meta:
        f = m["file"]
        if m.get("is_system"):
            result[m["id"]] = f  # 已含 system: 前缀
        else:
            result[m["id"]] = str(base / f)
    return result
