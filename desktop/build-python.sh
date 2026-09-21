#!/usr/bin/env bash
# 构建 FontCop 桌面版所需的独立 Python 运行时（python-build-standalone + venv）。
# 产物：desktop/python-runtime/ （含 python3 + 已装依赖，Electron 用绝对路径 spawn）
# 用法：bash desktop/build-python.sh
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DESKTOP_DIR")"
OUT="$DESKTOP_DIR/python-runtime"

# 平台：这里按 macOS arm64 构建；跨平台需改下面的 VERSION/ARCH
PY_VER="3.14"            # 与项目开发环境一致
PBS_VER="20250317"       # python-build-standalone 发布日期标签
ARCH="aarch64-apple-darwin"
TAG="cpython-${PY_VER}+${PBS_VER}"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/cpython-${PY_VER}-${PBS_VER}-${ARCH/-apple-/-apple/}-install_only.tar.gz"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 下载 python-build-standalone ($TAG) =="
curl -fL --retry 3 -o "$TMP/py.tgz" "$URL"

echo "== 解压到 $OUT =="
rm -rf "$OUT"
mkdir -p "$OUT"
tar -xzf "$TMP/py.tgz" -C "$TMP"
cp -R "$TMP/python"/* "$OUT/"

echo "== 创建 venv 并装依赖 =="
"$OUT/bin/python3" -m venv "$OUT"
# venv 默认复用 base，重建确保独立
"$OUT/bin/python3" -m ensurepip
"$OUT/bin/pip" install -r "$ROOT/requirements.txt"

echo "== 校验关键依赖 =="
"$OUT/bin/python3" -c "import numpy, PIL, cv2, rapidocr_onnxruntime; print('deps ok')"

echo "== 完成：运行时会写入 $OUT =="
"$OUT/bin/python3" --version
