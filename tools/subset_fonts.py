#!/usr/bin/env python3
"""字体子集化：把 fonts/files/*.ttf|otf 裁剪到索引所需字符集，输出到 fonts/subset/。

用途：FontCop 只用 793 个常用字（src/indexer.py CHARS）做字形比对，
全量字体动辄 10-25MB/款，子集化后可压到 1-2MB/款，大幅缩小打包体积。

- 保留 CHARS（+ 换行/空格）在子集内；字体缺该字形则保留默认 fallback 字形。
- CFF 表用 fontTools.subset 时默认会重打包为 CFF，需 drop_tables 处理。
- 幂等：重复运行覆盖输出。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.subset import Options, Subsetter

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT / "fonts" / "files"
SUBSET_DIR = ROOT / "fonts" / "subset"


def main() -> int:
    # 与 src/indexer.py CHARS 保持同源（构造时避免循环导入）
    sys.path.insert(0, str(ROOT))
    from src.indexer import CHARS
    chars = set(CHARS)
    chars.add(" ")          # 渲染留白/空格需要
    chars.add("\n")         # 部分渲染路径会用到换行占位
    # 明确按码点收集，避免子集化时字体厂商 fallback 编造字形
    unicodes = {ord(c) for c in chars}

    SUBSET_DIR.mkdir(parents=True, exist_ok=True)
    total_in = total_out = 0
    n_ok = n_skip = n_fail = 0

    for src in sorted(FILES_DIR.glob("*.ttf")) + sorted(FILES_DIR.glob("*.otf")):
        total_in += src.stat().st_size
        out = SUBSET_DIR / src.name
        try:
            opts = Options()
            opts.name_IDs = ["*"]            # 保留全部 name 记录
            opts.name_legacy = True
            opts.name_languages = ["*"]
            opts.layout_features = ["*"]     # 保留 kern/liga 等（渲染差异极小，稳妥起见保留）
            opts.notdef_outline = True       # 缺字形时给默认轮廓，避免渲染炸
            opts.recalc_bounds = True
            opts.drop_tables += ["FFTM", "post", "GDEF", "GPOS"]  # 比对用不到
            opts.retain_gids = False
            opts.desubroutinize = True       # CFF 子程序打散，体积更小更稳

            from fontTools.ttLib import TTFont
            font = TTFont(str(src), fontNumber=0, lazy=True)
            ss = Subsetter(options=opts)
            ss.populate(unicodes=unicodes)
            ss.subset(font)
            font.save(str(out))
            font.close()

            osz = out.stat().st_size
            total_out += osz
            n_ok += 1
            print(f"[sub] {src.name}: {src.stat().st_size/1e6:.1f}MB -> {osz/1e6:.1f}MB")
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            print(f"[FAIL] {src.name}: {e}", file=sys.stderr)
            if out.exists():
                out.unlink()

    print(f"\n子集化完成: {n_ok} ok, {n_skip} skip, {n_fail} fail")
    print(f"体积: {total_in/1e6:.1f}MB -> {total_out/1e6:.1f}MB "
          f"(节省 {100*(1-total_out/total_in):.0f}%)")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
