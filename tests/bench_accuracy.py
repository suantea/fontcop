#!/usr/bin/env python3
"""大规模准确性评测：全部字体 × 多字 × 全扰动模式，输出 Top-1/Top-5 基线。
用法：.venv/bin/python tests/bench_accuracy.py [--quick]
"""
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import Matcher, _group_of
from src.render import glyph_files, render_char
from tools.gen_testset import MODES, gen_case

# 覆盖不同结构复杂度的测试字（索引字符集内），每字体同一组字便于横向对比
BENCH_CHARS = ["的", "清", "深", "说", "路", "报", "度", "永", "国", "经"]


def main() -> int:
    quick = "--quick" in sys.argv
    if quick:
        BENCH_CHARS[:] = BENCH_CHARS[:5]

    m = Matcher()
    files = glyph_files()
    cjk_fonts = [fid for fid in sorted(files) if fid.startswith("system-")
                 or fid in ("source-han-sans", "source-han-serif", "lxgw-wenkai",
                            "smiley-sans", "noto-sans-cjk", "noto-serif-cjk",
                            "zcool-kuaile", "zcool-xiaowei")]
    rng = random.Random(1234)

    top1 = top5 = total = 0
    per_mode = defaultdict(lambda: [0, 0])   # mode -> [top1_hits, total]
    per_font = defaultdict(lambda: [0, 0])
    confusions = defaultdict(int)

    for fid in cjk_fonts:
        true_g = _group_of(fid)
        for ch in BENCH_CHARS:
            for mode in MODES:
                img = gen_case(files[fid], ch, mode, rng)
                r = m.match([{"image": img, "char": ch}])
                ids = [c.font_id for c in r.candidates]
                pred_groups = [_group_of(i) for i in ids]
                total += 1
                per_mode[mode][1] += 1
                per_font[fid][1] += 1
                if pred_groups and pred_groups[0] == true_g:
                    top1 += 1
                    per_mode[mode][0] += 1
                    per_font[fid][0] += 1
                if true_g in pred_groups[:5]:
                    top5 += 1
                else:
                    confusions[(fid, ids[0] if ids else "none")] += 1

    print(f"评测规模: {len(cjk_fonts)} 字体 × {len(BENCH_CHARS)} 字 × {len(MODES)} 模式 = {total} 例")
    print(f"\n总体: Top-1 {top1}/{total} = {top1/total:.1%}   Top-5 {top5}/{total} = {top5/total:.1%}")
    print("\n按扰动模式:")
    for mode in MODES:
        h, t = per_mode[mode]
        print(f"  {mode:<12} Top-1 {h}/{t} = {h/t:.0%}")
    print("\n按字体 (Top-1 最低的 6 款):")
    for fid, (h, t) in sorted(per_font.items(), key=lambda x: x[1][0]/x[1][1])[:6]:
        print(f"  {fid:<18} {h}/{t} = {h/t:.0%}")
    print("\n主要混淆 (真实→误判 次数):")
    for (true, pred), n in sorted(confusions.items(), key=lambda x: -x[1])[:8]:
        print(f"  {true} → {pred}: {n}")
    return 0


if __name__ == "__main__":
    main()
