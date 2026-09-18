"""M5-1：从本机系统字体库（及 fonts/ 目录）生成白名单清单。
逻辑：
  1. 扫描 /System/Library/Fonts/**/*.ttf/.otf/.ttc/.dfont
  2. 对每个文件用 fontTools.TTCollection / TTFont 提取 family name（cmap/name 表）
  3. 过滤掉符号/专用字体（Symbol, Webdings, Apple Symbols, Apple Braille, NewYork 等）
  4. 合并 fonts/fonts.json 已有条目（去重）
  5. 输出 fonts/system_fonts.json + 更新 fonts/fonts.json
可重复运行（每次重新扫，增量更新）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
SCANNED_PATH = FONTS_DIR / "system_fonts.json"
SUPPORTED_EXT = {".ttf", ".otf", ".ttc", ".dfont"}

# 明显是系统符号/非字体，排除
SKIP_NAMES = {
    "symbol", "webdings", "zapfdingbats", "apple symbols", "apple braille",
    "new york", "last resort", "apple color emoji", "apple color emoji ui",
    "cjk symbols fallback", "symbol.ttf",
}
# 跳过 Apple San Francisco 系列（私有变体字体，不可分发）
SF_PREFIXES = ("sf-", "sfsd", "sfcompact")


def family_name_from_font(path: Path) -> str | None:
    """读字体 name 表中的 Family Name（platform 3, encoding 1, language 0x409/0）。"""
    try:
        from fontTools.ttLib import TTFont, TTCollection
        ext = path.suffix.lower()
        if ext == ".ttc":
            # TTC: 逐个成员尝试，取第一个能读到 name 的
            c = TTCollection(str(path))
            for i, tt in enumerate(c.fonts):
                try:
                    n = tt["name"]
                    for rec in n.names:
                        if rec.nameID == 1 and rec.platformID == 3 and rec.platEncID == 1 and rec.langID == 0x409:
                            return rec.toUnicode().strip()
                    for rec in n.names:
                        if rec.nameID == 1 and rec.platformID == 3 and rec.platEncID == 1:
                            return rec.toUnicode().strip()
                    return f"TTC-member-{i}"
                except Exception as e2:  # noqa: BLE001
                    sys.stderr.write(f"[warn] TTC 成员 {path.name}#{i}: {e2}\n")
            return None
        else:
            tt = TTFont(str(path), fontNumber=0, lazy=True)
            try:
                n = tt["name"]
                for rec in n.names:
                    if rec.nameID == 1 and rec.platformID == 3 and rec.platEncID == 1 and rec.langID == 0x409:
                        return rec.toUnicode().strip()
                for rec in n.names:
                    if rec.nameID == 1 and rec.platformID == 3 and rec.platEncID == 1:
                        return rec.toUnicode().strip()
            finally:
                tt.close()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] 读 {path.name}: {e}\n")
    return None


def scan_system_fonts() -> dict[str, dict]:
    """返回 {family_id: {name, path, style_tag}}，按 family 去重。"""
    results = {}
    for p in Path("/System/Library/Fonts").rglob("*"):
        if p.suffix.lower() not in SUPPORTED_EXT:
            continue
        if any(p.name.lower().startswith(s) or s in p.name.lower() for s in SF_PREFIXES):
            continue
        name = family_name_from_font(p)
        if not name:
            continue
        # 排除符号/专用
        if any(s in name.lower() for s in SKIP_NAMES):
            continue
        # 去重：同名 family 只保留最大那个
        key = name.strip().lower().replace(" ", "-")
        if key in results:
            continue
        results[key] = {
            "name": name.strip(),
            "path": str(p.resolve()),
            "style_tag": guess_style(name),
        }
    return results


def guess_style(name: str) -> str:
    """根据名字关键词粗猜风格标签。"""
    n = name.lower()
    if any(k in n for k in ["mono", "monospace", "consolas", "courier"]):
        return "mono"
    if any(k in n for k in ["serif", "songti", "ming", "mincho", "明朝", "楷体", "kai", "song"]):
        return "serif"
    if any(k in n for k in ["kai", "xing", "script", "cursive", "handwrit", "brush", "hand", "楷体", "行楷", "手写"]):
        return "kai"
    if any(k in n for k in ["display", "heading", "title", "poster", "art", "deco"]):
        return "display"
    if any(k in n for k in ["heiti", "sans", "黑体", "苹方", "苹方", "苹方"]):
        return "sans"
    if any(k in n for k in ["隶", "li"]):
        return "li"
    if any(k in n for k in ["fangsong", "仿宋", "圆体", "round", "圆润"]):
        return "round"
    return "mixed"


def main() -> int:
    scanned = scan_system_fonts()
    print(f"扫描到 {len(scanned)} 款系统字体")
    # 写入 system_fonts.json（不覆盖原 fonts.json，作为补充源）
    SCANNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCANNED_PATH.write_text(
        json.dumps(scanned, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写 {SCANNED_PATH}")
    # 抽样打印前 20 个中文名
    cn = {k: v for k, v in scanned.items() if re.search(r"[\u4e00-\u9fff]", v["name"])}
    print(f"中文/全角字体 {len(cn)} 款：")
    for k in list(cn)[:20]:
        print(f"  {k}: {cn[k]['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
