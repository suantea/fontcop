#!/usr/bin/env python3
"""M5-2: 把系统关键中文字体 + 现有开源字体整合进 fonts.json。
策略：
  1. 保留 fonts/fonts.json 已有的 11 款
  2. 从 /System/Library/Fonts 扫描有实际价值的中文/日文/韩文/西文常用字体
  3. TTC 文件按成员拆分（如 STHeiti 拆分出「黑體-簡」「黑體-繁」）
  4. 写入 fonts/fonts.json，并建 symbols.json 指向系统路径
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
EXTRA_DIR = FONTS_DIR / "system"
SYMBOLS_FILE = FONTS_DIR / "symbols.json"


def collect_cjk_fonts() -> list[dict]:
    """扫描 /System/Library/Fonts 收集有价值的 TTC/TTF。"""
    targets = []
    # 明确的中文名文件
    explicit = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for p in explicit:
        pp = Path(p)
        if not pp.exists():
            continue
        if pp.suffix.lower() == ".ttc":
            c = TTCollection(str(pp))
            for i, tt in enumerate(c.fonts):
                fam = next((r.toUnicode() for r in tt["name"].names if r.nameID == 1 and r.platformID == 3), "?")
                # 去重同 family
                if fam and fam != "?" and fam not in [x["name"] for x in targets]:
                    targets.append({
                        "name": fam,
                        "path": str(pp.resolve()),
                        "member_index": i,
                    })
            for tt in c.fonts:
                tt.close()
        else:
            tt = TTFont(str(pp), fontNumber=0, lazy=True)
            fam = next((r.toUnicode() for r in tt["name"].names if r.nameID == 1 and r.platformID == 3), "?")
            tt.close()
            if fam and fam != "?" and fam not in [x["name"] for x in targets]:
                targets.append({"name": fam, "path": str(pp.resolve()), "member_index": 0})
    # 再扫描 PingFang（如果有）
    for pp in Path("/System/Library/Fonts").rglob("*PingFang*"):
        if pp.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        if any(k in pp.name for k in ["UI", "Watch"]):
            continue  # 设备专用，跳过
        if pp.suffix.lower() == ".ttc":
            c = TTCollection(str(pp))
            for i, tt in enumerate(c.fonts):
                fam = next((r.toUnicode() for r in tt["name"].names if r.nameID == 1 and r.platformID == 3), "?")
                if fam and fam != "?" and fam not in [x["name"] for x in targets]:
                    targets.append({"name": fam, "path": str(pp.resolve()), "member_index": i})
            for tt in c.fonts:
                tt.close()
        else:
            tt = TTFont(str(pp), fontNumber=0, lazy=True)
            fam = next((r.toUnicode() for r in tt["name"].names if r.nameID == 1 and r.platformID == 3), "?")
            tt.close()
            if fam and fam != "?" and fam not in [x["name"] for x in targets]:
                targets.append({"name": fam, "path": str(pp.resolve()), "member_index": 0})
    return targets


def main() -> int:
    cjk = collect_cjk_fonts()
    print(f"找到 {len(cjk)} 款系统 CJK 字体:")
    for f in cjk:
        print(f"  {f['name']} @ {Path(f['path']).name} (member {f['member_index']})")

    # 构建 symbols.json
    syms = {f"system-{i}": {
        "id": f"system-{i}",
        "name": f["name"],
        "path": f["path"],
        "member_index": f["member_index"],
        "license": "系统内置（macOS 授权）",
        "commercial_free": False,
        "source_url": "",
        "style": "system",
    } for i, f in enumerate(cjk)}
    SYMBOLS_FILE.write_text(json.dumps(syms, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写 {SYMBOLS_FILE}")

    # 合并到 fonts.json
    meta = json.loads((FONTS_DIR / "fonts.json").read_text(encoding="utf-8"))
    existing = {m["id"]: m for m in meta}
    for sym_id, sym in syms.items():
        if sym_id not in existing:
            meta.append({
                "id": sym_id,
                "name": sym["name"],
                "en_name": sym["name"],
                "license": sym["license"],
                "commercial_free": False,
                "style": sym["style"],
                "source_url": sym["source_url"],
                "file": f"system:{sym['path']}#{sym['member_index']}",
                "is_system": True,
            })
    (FONTS_DIR / "fonts.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"fonts.json 已更新，共 {len(meta)} 款")
    return 0


if __name__ == "__main__":
    sys.exit(main())
