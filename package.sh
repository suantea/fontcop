#!/usr/bin/env bash
# 打包 FontCop 绿色发行版（解压即用，无需安装）。
# 产物：FontCop-<platform>.zip，含 项目源码 + fonts/subset + data 索引 + python-runtime。
# 前置：先跑 build_python.sh 生成 ./python-runtime，且 data/glyph_index.npz 已建好。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 定位项目内的独立 Python（Windows 是 python.exe，mac/linux 是 bin/python3）
if [[ -x python-runtime/bin/python3 ]]; then
  PY="python-runtime/bin/python3"
elif [[ -f python-runtime/python.exe ]]; then
  PY="python-runtime/python.exe"
else
  echo "[package] 缺少 python-runtime，请先运行 bash build_python.sh"
  exit 1
fi
if [[ ! -f data/glyph_index.npz ]]; then
  echo "[package] 缺少 data/glyph_index.npz，请先运行 '$PY -m src.indexer'"
  exit 1
fi

OS="$(uname -s)"
case "$OS" in
  Darwin) TAG="macos" ;;
  Linux)  TAG="linux" ;;
  MINGW*|MSYS*|Windows*) TAG="windows" ;;
  *) TAG="$(uname -m)" ;;
esac
ZIP="FontCop-${TAG}.zip"

echo "== 打包 ${ZIP}（用 Python zipfile，跨平台无外部 zip 依赖）=="
# 用项目内 Python 的 zipfile 打包：Windows runner 无 zip 命令，且需保留 unix 权限位
"$PY" - "$ZIP" <<'PYEOF'
import io, os, sys, zipfile

# Windows 控制台默认 cp1252，直接 print 中文会 UnicodeEncodeError 让构建红掉。
# 把 stdout 强制成 utf-8：跨平台同一套输出，无需在调用处到处 encode。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

out = sys.argv[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".atomcode", ".anchors", "node_modules", "dist-win", "docs"}
SKIP_PREFIX = ("fonts/files/",)          # 大体积全量字体，不打包（用子集）
SKIP_FILES = {".DS_Store", "nul"}
SKIP_EXT = (".pyc", ".log", ".bak", ".bak3")

# 瘦身：只剔除运行期用不到的文件（跨平台安全，mac/win 同一套规则）
#   - pip：分发包里靠它装东西没意义；仅占 11MB
#   - fontTools：只有 tools/subset_fonts.py 等构建脚本用，服务/OCR 运行期零引用（20MB）
#   - include/share/dist-info/LICENSE：纯构建期产物或元数据
# 注意：C 扩展的 .so/.pyd 与 numpy/onnxruntime/PIL 等运行期必需包一律保留。
SKIP_ANY = ("/site-packages/pip/", "/site-packages/pip-", "/site-packages/fontTools/",
            "/site-packages/fonttools-")
SKIP_PART = ("/include/", "/share/", ".dist-info/", "/__pycache__/")

def mode_of(path: str) -> int:
    """保留可执行位（start.command / bin/python3 在 mac 上必须可执行）。"""
    st = os.stat(path)
    return st.st_mode & 0o777

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, ".").replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for fn in filenames:
            rel = prefix + fn
            if rel == out or fn in SKIP_FILES or fn.endswith(SKIP_EXT):
                continue
            if rel.startswith(SKIP_PREFIX):
                continue
            full = "/" + rel
            if any(p in full for p in SKIP_ANY) or any(p in full for p in SKIP_PART):
                continue
            zi = zipfile.ZipInfo.from_file(rel, rel)
            zi.compress_type = zipfile.ZIP_DEFLATED
            # external_attr 高 16 位存 unix 权限，解压端才能还原可执行位
            zi.external_attr = (mode_of(rel) & 0xFFFF) << 16
            with open(rel, "rb") as f, z.open(zi, "w") as dst:
                while chunk := f.read(1 << 20):
                    dst.write(chunk)

print(f"  写入 {sum(1 for _ in zipfile.ZipFile(out).namelist())} 个条目".encode("utf-8", "replace").decode("utf-8", "replace"))
PYEOF
echo "== 完成：$ZIP = $(du -h "$ZIP" | cut -f1) =="
echo "解压后双击 start.$( [[ "$OS" == Darwin ]] && echo command || echo bat ) 即可启动"
