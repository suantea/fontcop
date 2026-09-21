#!/usr/bin/env bash
# 构建 FontCop 桌面版所需的独立 Python 运行时（python-build-standalone + venv）。
# 产物：desktop/python-runtime/ （含 python3 + 已装依赖，Electron 用绝对路径 spawn）
# 用法：bash desktop/build-python.sh
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DESKTOP_DIR")"
OUT="$DESKTOP_DIR/python-runtime"

# 平台：这里按 macOS arm64 构建；跨平台需改下面的 PY_VER/PBS_VER/ARCH
PY_VER="3.14"            # 与项目开发环境一致（python-build-standalone 用 X.Y.Z 全版本号）
PY_FULL="3.14.7"         # 具体补丁版本（release 资产按此命名）
PBS_VER="20260901"       # python-build-standalone 发布日期标签（releases/tags/<此值>）
ARCH="aarch64-apple-darwin"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/cpython-${PY_FULL}+${PBS_VER}-${ARCH}-install_only.tar.gz"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 下载 python-build-standalone (cpython-${PY_FULL}+${PBS_VER}) =="
# 用 HTTP/1.1 + 断点续传避免大文件传输中 HTTP2 framing 层断流（GitHub CDN 在弱网下常见）
curl -fL --retry 5 --retry-all-errors -C - --http1.1 -o "$TMP/py.tgz" "$URL"
# 校验：tar 能列出即下载完整
tar -tzf "$TMP/py.tgz" >/dev/null || { echo "下载不完整或 corrupted，请重试"; exit 1; }

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
