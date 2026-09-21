#!/usr/bin/env bash
# 构建 FontCop 桌面版所需的独立 Python 运行时（python-build-standalone + venv）。
# 产物：desktop/python-runtime/ （含 python3 + 已装依赖，Electron 用绝对路径 spawn）
# 用法：bash desktop/build-python.sh
set -euo pipefail

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$DESKTOP_DIR")"
OUT="$DESKTOP_DIR/python-runtime"

# 平台：自动按当前 OS/ARCH 选 python-build-standalone 资产（也可用 PBS_ARCH 环境变量覆盖）
PY_FULL="3.14.7"         # 具体补丁版本（release 资产按此命名）
PBS_VER="20260901"       # python-build-standalone 发布日期标签（releases/tags/<此值>）
case "${PBS_ARCH:-$(uname -s)-$(uname -m)}" in
  Darwin-arm64)  ARCH="aarch64-apple-darwin" ;;
  Darwin-x86_64) ARCH="x86_64-apple-darwin" ;;
  Linux-x86_64)  ARCH="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64) ARCH="aarch64-unknown-linux-gnu" ;;
  MINGW*-x86_64*|Windows*-x86_64*|MSYS*-x86_64*) ARCH="x86_64-pc-windows-msvc" ;;
  *) echo "不支持的平台: $(uname -s)-$(uname -m)（可用 PBS_ARCH 覆盖）"; exit 1 ;;
esac
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/cpython-${PY_FULL}+${PBS_VER}-${ARCH}-install_only.tar.gz"
# Windows 资产解压后无 bin/ 目录，可执行文件在根下
if [[ "$ARCH" == *windows* ]]; then
  PY_EXE_REL="python.exe"
else
  PY_EXE_REL="bin/python3"
fi

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
PY_EXE="$OUT/$PY_EXE_REL"
"$PY_EXE" -m venv "$OUT"
"$PY_EXE" -m ensurepip
"$PY_EXE" -m pip install -r "$ROOT/requirements.txt"

echo "== 校验关键依赖 =="
"$PY_EXE" -c "import numpy, PIL, cv2, rapidocr_onnxruntime; print('deps ok')"

echo "== 完成：运行时会写入 $OUT =="
"$PY_EXE" --version
