"""M1 回归测试：干净图 Top-1 ≥95%，加扰图 Top-5 ≥80%。"""
import random
import sys

sys.path.insert(0, ".")

from src.pipeline import Matcher, _group_of
from src.render import glyph_files
from tools.gen_testset import MODES, gen_case

# 中文测试字（索引字符集内）
TEST_CASES = [
    ("source-han-sans", "清"), ("source-han-serif", "度"), ("lxgw-wenkai", "说"),
    ("smiley-sans", "路"), ("noto-sans-cjk", "深"), ("zcool-kuaile", "的"),
    ("zcool-xiaowei", "报"), ("jetbrains-mono", "R"),
]


def main() -> int:
    m = Matcher()
    files = glyph_files()
    rng = random.Random(42)

    top1_hits = top5_hits = total = 0
    fails = []
    for fid, ch in TEST_CASES:
        true_group = _group_of(fid)
        for mode in MODES:
            img = gen_case(files[fid], ch, mode, rng)
            r = m.match([{"image": img, "char": ch}])
            ids = [c.font_id for c in r.candidates]
            total += 1
            # 组级判分：同源字体字形相同，命中组内任一即算正确
            pred_groups = [_group_of(i) for i in ids]
            if pred_groups and pred_groups[0] == true_group:
                top1_hits += 1
            if true_group in pred_groups[:5]:
                top5_hits += 1
            else:
                fails.append((fid, ch, mode, ids[:3]))

    print(f"Top-1: {top1_hits}/{total} ({top1_hits/total:.0%})")
    print(f"Top-5: {top5_hits}/{total} ({top5_hits/total:.0%})")
    for f in fails:
        print("  miss:", f)
    ok = top1_hits / total >= 0.95 and top5_hits / total >= 0.80
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
