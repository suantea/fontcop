#!/usr/bin/env python3
"""按 fonts/download_list.txt 批量下载字体到 fonts/files/。
支持直链文件和 zip（自动解包，取第一个 ttf/otf）。可重复执行（已存在则跳过）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts"
FILES_DIR = FONTS_DIR / "files"
LIST_FILE = FONTS_DIR / "download_list.txt"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# 可选 GitHub 加速镜像前缀：FONT_GH_MIRROR=https://gh-proxy.com/ python tools/fetch_fonts.py
GH_MIRROR = os.environ.get("FONT_GH_MIRROR", "").rstrip("/")


def _mirror(url: str) -> str:
    if GH_MIRROR and url.startswith("https://github.com/"):
        return GH_MIRROR + "/" + url
    return url


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def extract_font_archive(archive: Path, font_id: str) -> Path | None:
    """解压 zip，按字体 id 前缀匹配或取第一个 ttf/otf，落到 files/<id>_<name>。"""
    target = None
    with zipfile.ZipFile(archive) as zf:
        candidates = [
            n for n in zf.namelist()
            if n.lower().endswith((".ttf", ".otf")) and not n.startswith("__MACOSX")
        ]
        # 优先 Regular / 与 id 匹配的文件
        for n in candidates:
            base = Path(n).name.lower()
            if "regular" in base or font_id.replace("-", "") in base.replace("-", ""):
                target = n
                break
        target = target or (candidates[0] if candidates else None)
        if target is None:
            return None
        out = FILES_DIR / f"{font_id}_{Path(target).name}"
        out.write_bytes(zf.read(target))
    return out


def main() -> int:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    meta = json.loads((FONTS_DIR / "fonts.json").read_text(encoding="utf-8"))
    expected_files = {m["file"]: m["id"] for m in meta}

    entries = {}
    for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            fid, url = line.split(": ", 1)
            entries[fid] = url

    ok, fail = 0, 0
    for fid, url in entries.items():
        # 该字体在 fonts.json 里声明的文件是否已存在
        declared = [m["file"] for m in meta if m["id"] == fid]
        if declared and (FILES_DIR / declared[0]).exists():
            print(f"[skip] {fid}")
            ok += 1
            continue
        try:
            print(f"[get ] {fid} <- {_mirror(url)}")
            if url.endswith(".zip"):
                tmp = FILES_DIR / f"_tmp_{fid}.zip"
                download(_mirror(url), tmp)
                out = extract_font_archive(tmp, fid)
                tmp.unlink()
                if out is None:
                    raise RuntimeError("archive has no ttf/otf")
                print(f"       -> {out.name}")
                # 重命名以匹配 fonts.json 声明
                if declared and out.name != declared[0]:
                    out.rename(FILES_DIR / declared[0])
            else:
                dest = FILES_DIR / declared[0] if declared else FILES_DIR / Path(url).name
                download(_mirror(url), dest)
                print(f"       -> {dest.name}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {fid}: {e}", file=sys.stderr)
            fail += 1

    print(f"\ndone: {ok} ok, {fail} failed")
    if fail:
        print("缺失字体可手工下载放入 fonts/files/（文件名与 fonts.json 的 file 字段一致）")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
