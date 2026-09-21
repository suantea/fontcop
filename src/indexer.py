"""建库：每款字体渲染常用字 → 二值图 + SDF → 存 data/glyph_index.npz。

索引结构（npz）：
  font_ids : [n_fonts] str
  chars    : [n_chars] str（每字符一个 unicode 码点）
  glyphs   : [n_fonts, n_chars, 64, 64] uint8   二值图（粗排 IoU 用）
  sdfs     : [n_fonts, n_chars, 64, 64] float16 SDF（精排 NCC 用）
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from src.features import SDF_SIZE, sdf
from src.render import FINAL_SIZE, glyph_files, render_char
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "glyph_index.npz"

# 索引字符集：常用汉字（fonts/common_chars.txt，jieba 词频 top3500 + 原形近字）
# + 常见标点/字母数字。common_chars.txt 由 tools/expand_whitelist.py 同源维护，
# 改字表后必须重建索引。
CHARS = (
    (ROOT / "fonts" / "common_chars.txt").read_text(encoding="utf-8").strip()
    + "，。、；：？！""''（）《》【】…—·0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


def build(verbose: bool = True) -> None:
    files = glyph_files()
    font_ids = sorted(files)
    chars = [c for c in CHARS]

    n_f, n_c = len(font_ids), len(chars)
    glyphs = np.zeros((n_f, n_c, SDF_SIZE, SDF_SIZE), dtype=np.uint8)
    sdfs = np.zeros((n_f, n_c, SDF_SIZE, SDF_SIZE), dtype=np.float16)

    t0 = time.time()
    for i, fid in enumerate(font_ids):
        t1 = time.time()
        for j, ch in enumerate(chars):
            g = render_char(files[fid], ch)
            if g is None:
                continue  # 缺字形保持全 0（IoU/NCC 自然为低分）
            g64 = np.asarray(
                Image.fromarray(g * 255).resize((SDF_SIZE, SDF_SIZE), Image.NEAREST)
            )
            b64 = (g64 > 127).astype(np.uint8)
            glyphs[i, j] = b64
            sdfs[i, j] = sdf(b64).astype(np.float16)
        if verbose:
            print(f"[{i+1}/{n_f}] {fid} done in {time.time()-t1:.1f}s", flush=True)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        INDEX_PATH,
        font_ids=np.array(font_ids),
        chars=np.array(chars),
        glyphs=glyphs,
        sdfs=sdfs,
    )
    mb = INDEX_PATH.stat().st_size / 1e6
    print(f"\nsaved {INDEX_PATH} ({mb:.0f} MB) in {time.time()-t0:.0f}s")


def load() -> dict:
    if not INDEX_PATH.exists():
        sys.exit("索引不存在，先运行: python -m src.indexer")
    z = np.load(INDEX_PATH, allow_pickle=False)
    return {
        "font_ids": z["font_ids"].tolist(),
        "chars": z["chars"].tolist(),
        "glyphs": z["glyphs"],
        "sdfs": z["sdfs"],                                   # float16（ncc_aligned 内部会转 float32 算）
    }


if __name__ == "__main__":
    build()
